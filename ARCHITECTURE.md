# OfficeQA Arena: Comprehensive Architecture Document

**Date:** April 6, 2026 (updated)
**Best Score:** 184.5/246 (v5, 75.0% pass rate) | Latest: v12 = 181, v10 = 180
**Status:** Competition complete — 15+ submissions, 9 architectural generations

---

## 1. Architecture Overview

The OfficeQA Arena project has three main pipelines for answering Treasury Bulletin questions, each with different trade-offs:

### Pipeline 1: Analyst (Best-Scoring)
- **Config:** `analyst/arena.yaml`
- **Model:** `openrouter/minimax/minimax-m2.5` (reasoning_effort: high)
- **Mode:** "briefing" (solve_briefing.py)
- **Max turns:** 20
- **Timeout:** 300s
- **Score:** 180.4+ (highest)
- **Architecture:** MiniMax-as-Analyst mentor/intern pattern

**Data Flow:**
1. Question → `solve_briefing.py` (junior analyst)
2. Returns structured briefing with evidence, conflicts, proposed answer
3. MiniMax reviews, may iterate with refinements or grep commands
4. Final answer written to `/app/answer.txt`

**Why it wins:**
- Mentor persona guides the LLM to review work like a senior analyst
- Briefing mode provides explicit conflict detection (multiple sources → different values)
- Evidence units explicitly stated, period basis tagged (fiscal vs calendar)
- Iterative refinement: MiniMax can ask intern to try different keywords/years
- Situational framing (be a mentor) is more effective than imperative rules

### Pipeline 2: nomcp (Fallback, Single-Call)
- **Config:** `nomcp/arena.yaml`
- **Model:** Same as analyst
- **Max turns:** 8
- **Timeout:** 300s
- **Architecture:** Direct solver via Python tools + LLM one-shot

**Data Flow:**
1. Question → `route_question()` classifies question type
2. **Deterministic route:** `parse_question()` → `deterministic_search()` (multi-strategy keyword matching) → `score_candidate_rows()` (deterministic row ranking) → `detect_conflicts()` → `format_evidence_for_llm()` (with PRE-EXTRACTED MONTHLY VALUES for CY) → single LLM call → Python computes → `verify_with_llm` cross-checks
3. **Decompose route:** Falls through to `solve_decompose.solve()` for multi-year/ratio/superlative questions
4. **Fallback:** If primary route returns no answer, tries the other pipeline
5. Answer written to `/app/answer.txt`

**Why it matters:**
- Deterministic pipeline (no tool loop required)
- Router dispatches complex questions to decompose automatically
- Row scorer eliminates metric disambiguation errors before LLM sees evidence
- Conflict detection warns LLM about mixed period/unit/metric data
- Works when MiniMax breaks down (tool loop failures)
- 80% accuracy on 20-sample test set (nomcp baseline)

### Pipeline 3: Decompose (Complex Questions)
- **Script:** `nomcp/bottomup/solve_decompose.py`
- **Architecture:** 8-phase LLM-guided pipeline

**Data Flow:**
1. **Phase 1 (Decompose):** LLM breaks question into 1-4 sub-queries (max 4 to prevent confusion)
2. **Phase 2 (Search):** grep_table_metadata finds tables for each sub-query
3. **Phase 3 (Select):** LLM picks the table most likely to have ACTUAL (not estimated) data
4. **Phase 4 (Extract):** LLM extracts exact numeric values from selected table
5. **Phase 5 (Compute):** Python executes computation formula (sum, difference, ratio, etc.)
6. **Phase 6-8:** Mentor/Librarian review phases (currently in test, not production)

**Why it matters:**
- Handles questions requiring multiple data points (comparisons, ratios, sums across years)
- Explicit monthly value collection (not 12 separate queries)
- Computation happens in Python, not LLM (no math errors)
- Currently runs E2E but search accuracy needs improvement before full production

---

## 2. All LLM Prompts (Verbatim)

Paths are relative to the repository root. **Line numbers** in code pointers are approximate; search for the named constant (for example `SYSTEM_PROMPT`, `DECOMPOSE_SYSTEM`) in the file if they drift after edits.

### 2.1 Analyst Pipeline: System Prompt

**File:** `analyst/prompts/system.j2`

```
You are a Senior Treasury Analyst mentoring a junior intern. The intern has built a research tool (`solve_briefing.py`) that searches 696 U.S. Treasury Bulletin files (1939–2025) and produces a briefing with evidence and a proposed answer.

Your intern is eager but still learning. They sometimes pull the wrong row from a table, confuse fiscal years with calendar years, or miss unit conversions. Your role is to review their work, catch mistakes, and guide them toward the right answer — like a good mentor would.

Start by having your intern run their tool:
```
python3 /installed-agent/solve_briefing.py "{{ instruction }}"
```

When the briefing comes back, review it the way you'd review an intern's first draft:

- Does the table they found actually match what the question is asking? Sometimes they grab a table with a similar title but different data.
- Check the row labels — did they pick "Total receipts" when the question asked about "Net receipts"? These are common intern mistakes.
- Look at the units line. If the table says "In millions of dollars" and the intern's proposed answer is 2,602 — is the question asking for millions or the raw number?
- Fiscal year vs calendar year is where interns trip up most. Pre-1977, fiscal years run July to June. Post-1977, October to September. If the question says "calendar year 1940" and the data shows "FY1940," those are different things. Point this out.
- If the data has a column for the exact year and period asked about, great. If the intern had to sum monthly values or interpolate, double-check their math.

If the briefing looks solid and the evidence clearly supports the answer:
```
printf '%s' "ANSWER_VALUE" > /app/answer.txt
```

If something doesn't look right, guide the search in a new direction — the way you'd tell an intern "try looking at it this way instead":
- Different search terms: `python3 /installed-agent/solve_briefing.py "{{ instruction }}" --keywords "military expenditures" --year 1941`
- A direct look at the source: `grep -i "specific phrase" /app/corpus/*.txt | head -30`
- A quick calculation: `python3 -c "print(132 + 456)"`
- The full solver as backup: `python3 /installed-agent/solve.py "{{ instruction }}"` (writes answer.txt automatically)

Remember: a reasonable answer submitted is better than a perfect answer never written. When the evidence is good enough, commit to the answer and move on.
```

### 2.2 nomcp Pipeline: System Prompt (One-Shot Briefing)

**File:** `nomcp/prompts/system.j2`

```
Your FIRST action: run the solver with the EXACT question below.

```
python3 /installed-agent/solve.py "{{ instruction }}"
```

This searches 696 Treasury Bulletin files, extracts values, computes the answer, and writes it to /app/answer.txt automatically.

After running, verify the answer:
```
cat /app/answer.txt
```

If the answer is "N/A" or looks wrong, try the decompose solver as backup:
```
python3 /installed-agent/solve_decompose.py "{{ instruction }}"
cat /app/answer.txt
```

If still wrong, adjust: `printf '%s' "CORRECT_VALUE" > /app/answer.txt`

DO NOT grep/sed/cat corpus files directly. The solvers handle everything.

{{ instruction }}
```

### 2.3 solve.py: Tool-Calling Loop System Prompt

**File:** `nomcp/solve.py` — `SYSTEM_PROMPT` (approx. lines 2791–2884)

```
You are a Treasury Data Analyst. Answer questions using 696 U.S. Treasury Bulletin text files (1939-2025).

Your ONLY job: find data -> compute -> submit answer.

WORKFLOW (aim for 3-5 tool calls total):
1. PARSE the question: what metric, what year(s), fiscal vs calendar, what units?
2. SEARCH using search_raw_corpus (primary) — this greps the original source files with zero data loss
3. READ the vertical key-value data returned — your answer is already extracted as "column: value" pairs
4. COMPUTE using compute_expression for any arithmetic
5. SUBMIT using submit_answer — a wrong answer beats no answer

SEARCH STRATEGY (ordered by reliability):

  Step 1 (PRIMARY — start here): search_raw_corpus
    Searches the ORIGINAL Treasury Bulletin TXT files. Returns pre-extracted vertical data:
    each row is formatted as key-value pairs like "ROW: National defense\n  1940 > Jan: 132\n  1940 > Feb: 129".
    - Use 2-3 specific keywords from the question (e.g. "national defense expenditures")
    - Set year to focus on relevant bulletins
    - Read matched_row_vertical FIRST — it has the specific row matching your query with all values labeled
    - If matched_row_vertical doesn't have your answer, scan vertical_data for other rows
    - Headers use ">" for nested levels: "1940 > Jan." means January 1940
    - Check the "units" field for scale (millions, thousands, etc.)
    Example: search_raw_corpus(keywords="national defense expenditures", year=1940)

  Step 2 (DB lookup — fast but may miss data): resolve_numeric_evidence
    Searches a pre-built database. Fast for simple lookups but misses ~50% of data.
    Use AFTER search_raw_corpus if you need a quick cross-check or if grep didn't find it.

  Step 3 (DB fallback): search_canonical or search_ledger
    Keyword search across the database. Use only if Steps 1-2 both failed.

  Step 4 (CPI/inflation): lookup_cpi
    For "real dollars", "constant dollars", "inflation-adjusted" questions.
    lookup_cpi(year=1970, month=3) -> monthly CPI-U value
    lookup_cpi(year=1970) -> annual average
    Formula: real_value = nominal_value × (target_CPI / source_CPI)

  Step 5 (visual/chart): fetch_pdf_page
    For questions about charts, figures, or "on page X".

  Step 6 (compute): compute_expression
    For ALL arithmetic. Available functions: sum, mean, median, stdev, variance,
    correlation, percentile, cagr, geometric_mean, linreg, yoy_growth, theil_index,
    gini, herfindahl, hp_filter, cv, min, max, abs, round, sqrt, log, exp.
    Example: compute_expression(expression="abs(a - b)", variables={"a": 71, "b": 68})

  Step 7 (submit): submit_answer
    Submit your final answer. ALWAYS submit something before running out of calls.

READING SEARCH RESULTS:
When search_raw_corpus returns results, use this reading order:
1. matched_row_vertical — the best-matching row, already formatted as "column_name: value" pairs
   Example: "ROW: National defense\n  1940 > Jan: 132\n  1940 > Feb: 129\n  1940 > Total: 2,602"
   Just find the column matching your year/month and read the value directly.
2. vertical_data — all rows from the table in the same vertical format. Scan these if you need a different row.
3. units — tells you the scale (e.g. "In millions of dollars"). Always check this.
4. table_data — backup dict format with {column_name: value}. Use only if vertical data is unclear.
5. context — a few lines around the match for footnotes. Usually not needed.

ITERATIVE SEARCH:
When you find partial data, BUILD ON IT:
- If you found the right table but wrong rows, note the FILE and LINE, then search for nearby content
- Different sections of the same bulletin have related data — look for "Table 2", "Table 3", etc.
- If you see "1938" in column headers, January-December data is in the rows below

SEARCH TIPS — how to search EFFECTIVELY:
- Use SHORT, DISTINCT keywords: "national defense" not "total expenditures of the U.S federal government for national defense"
- If first search fails, DON'T tweak the same keywords. Try COMPLETELY DIFFERENT terms:
  * Different metric name: "defense spending" -> "war activities" -> "military expenditures"
  * Different table title: instead of the metric, search for the TABLE NAME visible in the bulletin
  * Different bulletin year: data from 1938 appears in bulletins from 1939-1941
- If you found the right table but wrong time period, note the file name and search for more context in that same file
- The data you need is ALWAYS in the corpus. If you can't find it, your keywords are wrong.

CRITICAL RULES:
- Use compute_expression for ALL math — never compute in your head
- NEVER call the same tool with identical arguments twice
- If you have data, COMPUTE and SUBMIT. Do not keep searching for "better" data
- Budget: 10 tool calls max. Aim for 3-5. Past 7 calls: stop and submit immediately
- A wrong answer scores higher than no answer. Always submit something.

FISCAL YEAR RULES:
- Pre-1977: FY runs Jul 1 (Y-1) to Jun 30 (Y). FY1940 = Jul 1939 - Jun 1940.
- Post-1977: FY runs Oct 1 (Y-1) to Sep 30 (Y). FY1980 = Oct 1979 - Sep 1980.
- Calendar year = Jan 1 to Dec 31. CY1940 != FY1940.
- If asked for "calendar year" total and you only find monthly data, SUM the 12 months (Jan-Dec).

COMMON MISTAKES:
- WRONG ROW: Match the EXACT metric name from the question
- UNIT SCALE: Check "In millions" vs "In thousands" before answering
- WRONG YEAR: A 1941 bulletin contains FY1940 data. Match data year, not bulletin year
- DOUBLE COUNTING: "Total" already includes sub-items. Never sum a parent with its children

ANSWER FORMAT: Return just the numeric value. Keep % for percentages.
```

### 2.4 Deterministic Extraction Prompt (Single LLM Call)

**File:** `nomcp/solve.py` (lines 3186-3223)

```
You are a data extraction specialist. You receive pre-searched Treasury Bulletin data and a question. Your job: identify the correct values in the data and output them in a structured format.

STEP 1 — IDENTIFY: Fill out this extraction table:
TABLE_TITLE: (which table has the answer)
ROW_LABEL: (which row matches the question's metric)
UNITS: (millions, thousands, billions, percent — from the Units field)
PERIOD: (calendar year, fiscal year, or monthly)

STEP 2 — EXTRACT VALUES: List the raw numeric values you found.
- If the answer is a single value: VALUES: [2602]
- If you need to sum monthly values: VALUES: [132, 129, 143, 159, 154, 153, 177, 200, 219, 287, 376, 473]
- If you need two values for a calculation: VALUES: [44463, 2602]

STEP 3 — SPECIFY OPERATION:
OPERATION: direct (just return the value)
OPERATION: sum (add all values)
OPERATION: difference (subtract second from first)
OPERATION: percent_change (((new - old) / old) * 100)
OPERATION: ratio (first / second)
OPERATION: geometric_mean
OPERATION: custom — EXPRESSION: <math expression using the values>

STEP 4 — ANSWER: The final numeric answer.

FISCAL YEAR RULES:
- Pre-1977: FY = Jul 1 (Y-1) to Jun 30 (Y). FY1940 = Jul 1939–Jun 1940.
- Post-1977: FY = Oct 1 (Y-1) to Sep 30 (Y).
- Calendar year = Jan 1 to Dec 31. If asked for CY total with monthly data, sum Jan–Dec.

CRITICAL: If the data shows monthly values (Jan, Feb, Mar...) and the question asks for a calendar year total, you MUST list ALL 12 monthly values in VALUES and set OPERATION: sum. Do NOT use an annual/fiscal total row.

Output format — use EXACTLY this structure:
TABLE_TITLE: ...
ROW_LABEL: ...
UNITS: ...
VALUES: [...]
OPERATION: ...
ANSWER: ...
```

### 2.5 Verification Prompt

**File:** `nomcp/solve.py` (lines 3226-3246)

```
You are a verification specialist checking a Treasury Bulletin data answer.

QUESTION: {question}

EVIDENCE USED:
{evidence}

PROPOSED ANSWER: {answer}

Check these common errors:
1. WRONG ROW: Does the row label match the question's metric EXACTLY?
2. WRONG COLUMN: Does the year/month match what was asked?
3. WRONG UNITS: Is the scale correct (millions vs thousands vs billions)?
4. WRONG ARITHMETIC: If sum/difference/percent change — are ALL required values included?
5. FISCAL vs CALENDAR: Pre-1977 FY=Jul-Jun, post-1977 FY=Oct-Sep. CY=Jan-Dec.

If the answer is CORRECT, respond: VERDICT: CORRECT
If the answer is WRONG, respond:
VERDICT: WRONG
CORRECTED_ANSWER: <the right answer>
REASON: <one line why>
```

### 2.6 Decompose Pipeline: Planning Prompt

**File:** `nomcp/bottomup/solve_decompose.py` — `DECOMPOSE_SYSTEM` (starts ~line 145)

```
You are a senior Treasury research librarian mentoring a new intern. The intern will execute your plan by searching ONE table per sub-query. If you create too many sub-queries, the intern gets confused and the whole project fails. Your department head reviews every plan and rejects any with more than 4 sub-queries for a single-year question.

You receive a question about Treasury Bulletin data and produce a structured plan -- independent sub-queries searchable in raw Treasury Bulletin text files (treasury_bulletin_YYYY_MM.txt, pipe-delimited tables).

CRITICAL FACTS:
- Rows labeled with bare year = FISCAL YEAR totals. No calendar year total rows exist.
- For CY sums: collect all 12 monthly values (Jan-Dec) and sum.
- FY changed: pre-1977 = Jul(Y-1)-Jun(Y). Post-1977 = Oct(Y-1)-Sep(Y).
- Monthly rows: "YYYY-Month" or just "Month" under a FY block.
- Later bulletins revise earlier numbers. Use bulletins from year after data year.
- "-" = zero, "nan" = not available, pipe-delimited columns.

OUTPUT FORMAT -- respond with ONLY this JSON:
{"sub_queries": [{"id": "A", "description": "what to find", "search_terms": ["term1", "term2"], "target_bulletin_year": YYYY, "target_bulletin_months": [1,2,3], "data_year": YYYY, "data_months": "all_12", "specific_months": [], "value_type": "monthly_series", "period_basis": "calendar", "column_hint": "expected column header"}], "computation": {"type": "direct|sum|difference|percent_change|ratio|geometric_mean|custom", "description": "how to combine", "formula": "expr using sub-query IDs"}, "output_format": {"units": "millions|billions|percent|ratio|other", "rounding": null, "suffix": ""}}

PLANNING RULES:
- Each sub-query independent. One per year for multi-year ranges.
- CY data in single year: ONE sub-query with data_months="all_12", value_type="monthly_series". NOT 12 separate queries.
- CY questions: period_basis="calendar", computation="sum". FY questions: value_type="annual_total", period_basis="fiscal".
- target_bulletin_year: year AFTER data year. target_bulletin_months: 2-4 months to search.
- search_terms: 2-5 words from TABLE TITLE or column headers.
- Specific month: value_type="single", data_months="specific", specific_months=[N] (numbers 1-12, not names).
- Max among categories: value_type="max_in_row".

COMPUTATION TYPES: direct, sum, difference (abs(B-A)), percent_change (abs((B-A)/A)*100), ratio (A/B), geometric_mean, custom (Python math: abs, round, sqrt, log, pow, min, max, sum).

EXAMPLES:

Q: "What were total expenditures for national defense in calendar year 1940?"
CORRECT (1 sub-query, monthly_series):
{"sub_queries": [{"id": "A", "description": "National defense expenditures, all 12 calendar months of 1940", "search_terms": ["national defense", "expenditures"], "target_bulletin_year": 1941, "target_bulletin_months": [1,2,3], "data_year": 1940, "data_months": "all_12", "specific_months": [], "value_type": "monthly_series", "period_basis": "calendar", "column_hint": "National defense"}], "computation": {"type": "sum", "description": "Sum Jan-Dec 1940 monthly values", "formula": "sum(A)"}, "output_format": {"units": "millions", "rounding": null, "suffix": ""}}
WRONG (12 sub-queries for each month separately -- NEVER DO THIS)

Q: "What was the absolute difference between total budget receipts in FY 1950 and FY 1949?"
CORRECT (2 sub-queries, annual_total):
{"sub_queries": [{"id": "A", "description": "Total budget receipts FY 1950", "search_terms": ["budget receipts", "total"], "target_bulletin_year": 1951, "target_bulletin_months": [1,2,3], "data_year": 1950, "data_months": "annual", "specific_months": [], "value_type": "annual_total", "period_basis": "fiscal", "column_hint": "Total"}, {"id": "B", "description": "Total budget receipts FY 1949", "search_terms": ["budget receipts", "total"], "target_bulletin_year": 1950, "target_bulletin_months": [1,2,3], "data_year": 1949, "data_months": "annual", "specific_months": [], "value_type": "annual_total", "period_basis": "fiscal", "column_hint": "Total"}], "computation": {"type": "difference", "description": "Absolute difference", "formula": "abs(A - B)"}, "output_format": {"units": "millions", "rounding": null, "suffix": ""}}

Q: "What was the interest cost for calendar year 1981 using monthly values?"
CORRECT (1 sub-query, monthly_series):
{"sub_queries": [{"id": "A", "description": "Interest cost monthly values for CY 1981", "search_terms": ["interest", "outlays", "function"], "target_bulletin_year": 1982, "target_bulletin_months": [1,2,3,4], "data_year": 1981, "data_months": "all_12", "specific_months": [], "value_type": "monthly_series", "period_basis": "calendar", "column_hint": "Net interest"}], "computation": {"type": "sum", "description": "Sum Jan-Dec 1981", "formula": "sum(A)"}, "output_format": {"units": "millions", "rounding": null, "suffix": ""}}

Output ONLY the JSON.
```

### 2.7 Decompose: Data Extraction Prompt

**File:** `nomcp/bottomup/solve_decompose.py` — `EXTRACT_SYSTEM` (starts ~line 189)

```
You are a data reader. You extract exact numeric values from pipe-delimited Treasury Bulletin tables.

TABLE FORMAT: | row_label | col1 | col2 | ... |
- Dashes or "-" mean zero. "nan" means not available.
- Bare year like "1940" = FY total. "January" or "1940-January" = monthly value.
- Strip commas and footnote markers (3/, r, p, *).
- Monthly series may span two FY blocks (e.g. Jul-Jun for pre-1977 FY).
- PREFER rows labeled with the actual year over rows labeled "(Estimated)".
- For monthly_series: extract ALL 12 values Jan-Dec in order. If a month shows "-", use 0.

Return ONLY JSON: {"values": <number or [12 monthly numbers Jan-Dec] or null>, "source_row": "row label", "source_column": "column header", "confidence": "high|medium|low", "notes": "any notes"}
```

### 2.8 Decompose: Table Selection Prompt

**File:** `nomcp/bottomup/solve_decompose.py` — `SELECT_SYSTEM` (~line 203)

```
You are the senior analyst reviewing intern candidates. Pick the table most likely to contain the ACTUAL data (not estimates, not projections). Prefer tables with more data rows, actual year labels (not 'Estimated'), and column headers matching the metric. Respond with ONLY the number (1, 2, 3, etc.).
```

---

## 3. Search Strategy

### 3.1 Keyword Index

**Purpose:** Fast table-level co-occurrence search.

**Structure:** Tab-delimited file (`/tmp/keyword_index.txt`):
```
file:line_num	table_title	metadata	INDEX_META
treasury_bulletin_1940_01.txt:1234	National Defense Expenditures	...	HAS_12_MONTHS|HAS_ANNUAL|BASIS:calendar|BASIS:monthly
```

**Build Process:**
- Built on startup by `build_index.py` from raw TXT corpus
- Scans all files for pipe-delimited tables
- Indexes table titles and column headers
- Tags completeness (HAS_12_MONTHS, HAS_ANNUAL) and period basis

**Search Logic (search_raw_corpus, lines 2380-2429):**
1. Read all index lines
2. For each line, check if **ALL** metric terms appear (co-occurrence)
3. If year specified, check that at least one year term appears
4. Year filtering: pub_year must be in range [yr, yr+8]
   - Rationale: Data from 1940 appears in bulletins 1940-1948
5. Return candidates ranked by file, then by completeness metadata

**Limitations:**
- Index misses ~41% of tables (from Tool Fix Findings)
- Direct COLUMN LIKE search fixes it (see 3.3)

### 3.2 search_raw_corpus Implementation

**File:** `nomcp/solve.py` (lines 2356-2510+)

**Two-Stage Approach:**

**Stage 1: Keyword Index Lookup**
- Searches index for co-occurrence of metric terms
- Ranks by bulletin year proximity to (data_year + 1)
- Prefers monthly data if calendar year question
- Limits: 4 tables from best file, 2 from others

**Stage 2: Parse Table from Raw TXT**
- Reads file and extracts pipe-delimited table block
- Merges multi-row headers (handles "Year > Month" nesting)
- Formats rows in vertical key-value format:
  ```
  ROW: National Defense Expenditures
    Jan. (month 1): 132
    Feb. (month 2): 129
    ...
    Total: 2,602
  ```
- Extracts units line (e.g., "(In millions of dollars)")
- Scores rows by term matching (prefer rows with search keywords in label)
- Returns matched_row_vertical + vertical_data + table_data

**Key Functions:**
- `_merge_multi_row_headers()` — handles 2+ header rows
- `_row_to_vertical()` — converts pipe row to "ROW: label\n  col: value" format
- `_parse_table_at()` — extracts table structure, headers, data
- `_build_result()` — ranks rows by term matching, builds result dict

**Output Format:**
```python
{
    "file": "treasury_bulletin_1940_01.txt",
    "line": 1234,
    "table_title": "National Defense Expenditures by Category",
    "units": "(In millions of dollars)",
    "matched_row_vertical": "ROW: Total\n  Jan: 132\n  Feb: 129\n  ...",
    "vertical_data": [list of all rows in vertical format],
    "table_data": [list of dicts for backward compat],
    "context": "snippet around the table"
}
```

### 3.3 deterministic_search: Multi-Strategy Keyword Matching

**File:** `nomcp/solve.py` (lines 3035-3088)

**Purpose:** Try multiple keyword strategies, merge results, rank by relevance.

**Process:**

1. **parse_question() — Extract Intent**
   - Extract years, period basis (fiscal vs calendar)
   - Detect operation type (sum, difference, percent_change, ratio, etc.)
   - Look up metric in TABLE_FAMILY_MAP for boost terms
   - Build strategies (longest phrase → 2 words → 1 word → full metric → boost terms)

2. **Multiple Searches**
   - For each strategy keyword set:
     - search_raw_corpus(keywords=strategy, year=primary_year, period_hint=period)
     - For multi-year questions, search each year separately
   - Deduplicate by (file, line) tuple
   - Stop when enough results collected

3. **Ranking Function: `_score(r)`**
   ```python
   has_match = 2 if r.get("matched_row_vertical") else 0
   has_data = 1 if r.get("vertical_data") or r.get("table_data") else 0
   fname = r.get("file", "")
   pub_yr = extract_year_from_filename(fname)
   proximity = -abs(pub_yr - (year + 1)) if year else 0
   family_boost = sum(1 for bt in boost_terms if bt in table_title.lower())
   return (has_match, family_boost, has_data, proximity)
   ```
   - Prefer results with matched_row_vertical (specific row match)
   - Boost by table family match
   - Prefer year+1 bulletins (data published next year)

### 3.4 TABLE_FAMILY_MAP

**File:** `nomcp/solve.py` (lines 32-56)

Maps question keywords → (family_name, boost_terms) tuples:

```python
"national defense": ("expenditures", ["analysis", "general", "expenditures", "function"]),
"defense": ("expenditures", ["analysis", "general", "expenditures", "function"]),
"military": ("expenditures", ["military", "defense", "expenditures"]),
"expenditures": ("expenditures", ["analysis", "expenditures", "budget"]),
"receipts": ("receipts", ["budget", "receipts", "internal", "revenue"]),
"revenue": ("receipts", ["internal", "revenue", "collections"]),
"customs": ("receipts", ["customs", "duties", "import"]),
"public debt": ("debt", ["public", "debt", "outstanding"]),
"interest-bearing": ("debt", ["interest", "bearing", "debt"]),
"securities": ("debt", ["federal", "securities", "ownership"]),
"intergovernmental": ("transfers", ["intergovernmental", "transfer", "grants"]),
"grants": ("transfers", ["grants", "aid", "intergovernmental"]),
"savings bonds": ("debt", ["savings", "bonds", "series"]),
"tax": ("receipts", ["tax", "internal", "revenue", "collections"]),
"income tax": ("receipts", ["income", "tax", "individual", "corporation"]),
"corporation": ("receipts", ["corporation", "income", "tax"]),
"employment": ("receipts", ["employment", "tax", "social", "insurance"]),
"trust fund": ("trust", ["trust", "fund", "social", "security"]),
"gold": ("monetary", ["gold", "stock", "monetary"]),
"currency": ("monetary", ["currency", "circulation", "money"]),
"balance of payments": ("international", ["balance", "payments", "international"]),
"imports": ("international", ["imports", "merchandise", "trade"]),
"exports": ("international", ["exports", "merchandise", "trade"]),
```

**Usage:** During ranking, boost results whose table_title contains any boost_term. Helps disambiguate between similar tables.

---

## 4. Evidence Formatting

### 4.1 format_evidence_for_llm Function

**File:** `nomcp/solve.py` (lines 3091-3183)

**Purpose:** Format search results into a clean, LLM-friendly evidence block.

**Key Features:**

1. **Calendar Year Detection**
   - If period="calendar" AND year specified
   - Prepend explicit instruction: "IMPORTANT: This question asks for CALENDAR YEAR {year} (Jan-Dec {year})."
   - Tell LLM: "If you find monthly values, you MUST sum all 12 months."
   - Tell LLM: "Do NOT use a 'fiscal year' or 'FY' total."

2. **Monthly Data Filtering**
   - For CY questions, filter matched_row_vertical to only show:
     - ROW: label line (kept)
     - Lines with month names (Jan, Feb, ..., Dec)
     - Lines with target year
     - Skip "Total", "Fiscal", "FY" lines (confuse LLM)
   - Extract numeric values from filtered lines
   - If ≥6 monthly values found, prepend:
     ```
     PRE-EXTRACTED MONTHLY VALUES for CY {year}: [132, 129, 143, 159, 154, 153, 177, 200, 219, 287, 376, 473]
     (Count: 12 values — sum these for the calendar year total)
     ```

3. **Row Prioritization**
   - For CY questions: show month rows first, then other rows
   - Filter out FY/Total rows to prevent LLM confusion
   - Show up to 3 evidence sources, max 10 extra rows per source

4. **Evidence Presentation Structure**
   ```
   QUESTION: {question}
   SEARCH PARAMS: metric='...', year=..., period=...

   IMPORTANT: This question asks for CALENDAR YEAR ... (Jan-Dec ...)
   If you find monthly values (Jan, Feb, Mar...), you MUST sum all 12 months...

   --- EVIDENCE 1: {file}:{line} ---
   TABLE: {table_title}
   UNITS: {units}

   PRE-EXTRACTED MONTHLY VALUES for CY {year}: [...]
   (Count: N values — sum these for the calendar year total)

   ROW: National defense
     Jan.: 132
     Feb.: 129
     ...

   --- Other rows in this table ---
   ROW: ...
   ...
   ```

### 4.2 Calendar Year Filtering Logic

**File:** `nomcp/solve.py` (lines 3127-3153)

**Problem Addressed:** LLM confuses fiscal year totals with calendar year sums, leading to wrong answers (CY failures).

**Solution:**

```python
if mv and period == "calendar" and year:
    _month_pats = ["jan", "feb", "mar", "apr", "may", "jun",
                   "jul", "aug", "sep", "oct", "nov", "dec"]
    _yr_str = str(year)
    mv_lines = mv.split("\n")
    filtered_mv_lines = [mv_lines[0]]  # keep ROW: label
    monthly_values = []

    for line in mv_lines[1:]:
        line_lower = line.lower().strip()
        has_month = any(m in line_lower for m in _month_pats)
        has_year = _yr_str in line_lower
        is_total = any(w in line_lower for w in ["total", "fiscal", " fy"])

        if has_month and (has_year or ...):
            filtered_mv_lines.append(line)
            # Extract numeric value
            val_match = re.search(r':\s*([\d,]+\.?\d*)', line)
            if val_match:
                monthly_values.append(val_match.group(1))
        elif not is_total:
            filtered_mv_lines.append(line)

    # Show pre-extracted values to LLM
    if len(monthly_values) >= 6:
        parts.append(f"\nPRE-EXTRACTED MONTHLY VALUES for CY {year}: [{', '.join(monthly_values)}]")
        parts.append(f"(Count: {len(monthly_values)} values — sum these for the calendar year total)")
```

**Impact:** Increases CY accuracy by explicitly presenting monthly values separated from annual/fiscal totals.

### 4.3 PRE-EXTRACTED MONTHLY VALUES Feature

**File:** `nomcp/solve.py` (lines 3151-3153)

**What it does:**
1. Extracts all monthly values from matched_row_vertical
2. Pre-computes their count
3. Tells LLM explicitly: "Count: N values — sum these for the calendar year total"

**Example Evidence Block:**
```
PRE-EXTRACTED MONTHLY VALUES for CY 1940: [132, 129, 143, 159, 154, 153, 177, 200, 219, 287, 376, 473]
(Count: 12 values — sum these for the calendar year total)
```

**Why it helps:**
- Removes ambiguity: LLM knows these are the 12 monthly values to sum
- Reduces arithmetic errors: LLM just reads the values, Python does the sum
- Explicit instruction: tells LLM this is the RIGHT path to the answer

---

## 5. Computation Pipeline

### 5.1 deterministic_solve Main Flow

**File:** `nomcp/solve.py` (lines 3279-3400+)

**Step-by-Step:**

```python
def deterministic_solve(question):
    # Step 1: Parse question
    params = parse_question(question)
    # Returns: metric, years, year, period_basis, strategies, operation, etc.

    # Step 2: Search with multiple strategies
    results, params = deterministic_search(question, limit=5)
    # Returns: ranked list of search results

    # Step 3: Format evidence for LLM
    evidence = format_evidence_for_llm(results, question, params)
    # Returns: clean evidence block with monthly values pre-extracted

    # Step 4: ONE LLM call to extract structure
    llm_response = call_llm(DETERMINISTIC_SYSTEM_PROMPT, evidence, max_tokens=4096)
    # LLM returns: TABLE_TITLE, ROW_LABEL, UNITS, VALUES: [...], OPERATION, ANSWER

    # Step 5: Parse LLM output
    for line in llm_response.strip().split("\n"):
        # Extract VALUES: [132, 129, ...]
        vm = re.match(r'^VALUES:\s*\[(.+)\]', line, re.I)
        if vm:
            values = [float(v.strip().replace(",", "")) for v in vm.group(1).split(",")]

        # Extract OPERATION: sum, difference, etc.
        om = re.match(r'^OPERATION:\s*(\S+)', line, re.I)
        if om:
            operation = om.group(1).lower()

        # Extract ANSWER: 2602
        am = re.match(r'^ANSWER:\s*(.+)', line, re.I)
        if am:
            answer = am.group(1).strip()

    # Step 6: Compute in Python (more reliable than LLM math)
    if values and operation:
        if operation == "direct" and len(values) == 1:
            computed = values[0]
        elif operation == "sum":
            computed = sum(values)
        elif operation == "difference" and len(values) >= 2:
            computed = values[0] - values[1]
        elif operation == "percent_change" and len(values) >= 2:
            computed = ((values[1] - values[0]) / abs(values[0])) * 100
        elif operation == "ratio" and len(values) >= 2:
            computed = values[0] / values[1] if values[1] != 0 else None
        elif operation == "geometric_mean" and values:
            import math
            computed = math.prod(values) ** (1.0 / len(values))
        elif operation == "custom":
            computed = safe_eval_finance(custom_expr, {"v": values})

        # Format answer
        if isinstance(computed, float):
            if computed == int(computed) and abs(computed) >= 1:
                answer = f"{int(computed):,}"
            else:
                answer = f"{computed}"

    # Step 7: Fallback if no answer extracted
    if not answer:
        # Try ANSWER line directly
        # Try any number in response

    # Step 8: Post-LLM validation (check CY monthly count, etc.)
    if operation == "sum" and "calendar year" in q_lower and len(values) != 12:
        # Warn but continue

    # Return answer
    return answer, evidence
```

### 5.2 Supported Operations

**File:** `nomcp/solve.py` (lines 3339-3361)

| Operation | Behavior | Example |
|-----------|----------|---------|
| `direct` | Return single value as-is | VALUES: [2602] → 2602 |
| `sum` | Add all values | VALUES: [132, 129, ...] → sum all 12 |
| `difference` | First - Second | VALUES: [50000, 2602] → 47398 |
| `percent_change` | ((new - old) / old) × 100 | VALUES: [2602, 39482] → +1414.76% |
| `ratio` | First / Second | VALUES: [6548, 39482] → 0.1658 |
| `geometric_mean` | nth root of product | VALUES: [1.05, 1.03, 1.07] → 1.0499 |
| `custom` | Python expression | EXPRESSION: "abs(a - b)" → safe_eval_finance |

### 5.3 Python Computation Engine: safe_eval_finance

**File:** `nomcp/solve.py` (lines 400-604)

**Purpose:** Safe mathematical evaluation with no security holes.

**Supported Functions:**
- Arithmetic: `+`, `-`, `*`, `/`, `**`, `//`, `%`
- Built-ins: `abs`, `round`, `min`, `max`, `sqrt`, `log`, `exp`, `pow`
- Statistics: `mean`, `median`, `stdev`, `variance`, `percentile`
- Financial: `cagr`, `geometric_mean`, `linreg`, `yoy_growth`
- Advanced: `theil_index`, `gini`, `herfindahl`, `hp_filter`, `cv`

**Restricted:** No imports, no function definitions, no variable assignments. Only expressions.

**Example:**
```python
safe_eval_finance("sum([132, 129, 143, 159])", {})  # → 563
safe_eval_finance("cagr(begin=1000, end=2500, years=10)", {})  # → 9.6049...
```

### 5.4 verify_with_llm Cross-Check

**File:** `nomcp/solve.py` (lines 3249-3276)

**Purpose:** Optional verification step to catch errors before submission.

**Process:**
1. Format VERIFY_PROMPT with question, evidence, proposed answer
2. Call LLM once
3. Parse response for: `VERDICT: CORRECT` or `VERDICT: WRONG`
4. If wrong, extract `CORRECTED_ANSWER: {value}`
5. Use corrected answer if provided

**Example Verification:**
```
VERDICT: WRONG
CORRECTED_ANSWER: 39482.03
REASON: Wrong row — used net receipts instead of total budget receipts
```

---

## 6. Known Failure Modes

### Based on Test Results (From memory/project_parse_findings.md and Tool Fix Findings)

#### 6.1 DEC_01: CY Aggregation (Wrong Row Selection)

**Problem:** Question asks for CY 1940 expenditures. Search finds the right TABLE, but LLM picks the wrong ROW.
- Finds table: "National Defense Expenditures by Category"
- Picks row: "Salaries" (subcategory) instead of "Total"
- Or picks row: "FY1940 Total" instead of summing Jan-Dec monthly values

**Evidence:** 46% of answers partially correct, 25% marked "partial" (right table, wrong metric)

**Root Cause:** LLM reasoning doesn't reliably distinguish between:
- Annual/fiscal totals (wrong for CY questions)
- Row labels that seem relevant but are subcategories (wrong subtotal)
- Monthly values scattered across rows

**Fix Applied (Apr 2):** PRE-EXTRACTED MONTHLY VALUES feature makes right answer obvious.

---

#### 6.2 DEC_02: Historical Data in Later Bulletins

**Problem:** Question asks for data from 1938, but:
- 1938 bulletins don't exist (Treasury started publishing Jan 1938+)
- 1939 bulletins contain 1938 data (published 1 year later)
- Current search range: [year, year+8] (may be too narrow)

**Evidence:** Some historical year questions fail because search doesn't go far enough forward in time.

**Fix:** Search window should extend further (year to year+12?) for very old data. Or use explicit bulletin selection by decompose pipeline.

---

#### 6.3 DEC_09: Wrong Metric Selection ("total budget receipts" vs "net receipts")

**Problem:** Question says "total budget receipts" but table has columns for:
- "Total Budget Receipts" (answer: 44,463M)
- "Net Receipts" (answer: 39,482M)
- "Gross Receipts" (answer: 50,000M)

**Root Cause:** Keyword matching picks "receipts" but LLM doesn't reliably choose "Total" variant.

**Evidence:** One of the key failure patterns in pilot results.

**Fix:** TABLE_FAMILY_MAP includes metric variants. deterministic_search boosts exact matches. But still insufficient — may need deterministic column matching (no LLM).

---

#### 6.4 Keyword Index Misses 41% of Tables

**Problem:** Index built by scanning table titles. But some tables:
- Have generic titles ("Table 5: Economic Data")
- Hide metric names in column headers only
- Have titles in paragraph above table, not immediately above

**Evidence:** Tool Fix Findings report: term index misses 41% of tables.

**Fix Applied:** Direct COLUMN LIKE search supplements index lookup. If index returns nothing, search_raw_corpus falls back to brute-force file scanning.

---

#### 6.5 MiniMax Ignores Imperative Rules

**Problem:** System prompt says:
- "Use compute_expression for ALL math"
- "Never compute in your head"
- "Aim for 3-5 tool calls"

But MiniMax:
- Ignores budget warnings
- Repeats same tool calls
- Enters infinite tool loops

**Evidence:** Anti-spin testing showed prompt warnings don't work.

**Fix Applied:**
- Analyst pipeline: Mentor framing works better (situational, not imperative)
- nomcp pipeline: Structured deterministic_solve (no tool loop)
- Decompose pipeline: Explicit phase architecture prevents loops

**Lesson:** Situational framing ("You are a mentor reviewing an intern") beats imperative rules ("DO NOT ...").

---

### 6.6 Summary Table

| Failure | Cause | Impact | Fix |
|---------|-------|--------|-----|
| CY aggregation (wrong row) | LLM confused by multiple rows | 46% partial | PRE-EXTRACTED MONTHLY VALUES + filtering |
| Historical data missing | Search range too narrow | Some 1938-1942 Q fail | Extend search window or decompose |
| Metric disambiguation | "receipts" picks wrong column | DEC_09 failure | TABLE_FAMILY_MAP + deterministic selection |
| Index misses tables | Generic titles, hidden metrics | 41% miss rate | Fallback to direct COLUMN LIKE search |
| MiniMax tool loops | Imperative rules ignored | Timeouts | Mentor framing + deterministic architecture |

---

## 7. Proposed Improvements

### 7.1 Evidence Formatting Fix for CY Questions (DONE — Apr 2)

**Status:** Implemented and tested.

**What:** PRE-EXTRACTED MONTHLY VALUES + filtering of FY/Total rows.

**Impact:** Reduced CY confusion. Expected +5-10% on CY questions.

---

### 7.2 Deterministic Row Scorer (DONE — Apr 3)

**Status:** Implemented as `score_candidate_rows()` in `solve.py`.

**What:** Scores search results by token overlap between question metric and row labels, with bonuses for positive qualifiers (e.g., "total" when question asks for total) and penalties for negative qualifiers (e.g., "net" when question doesn't mention it). Subcategory rows penalized when total is requested.

**Impact:** "Total budget receipts" scores +0.70, "Net receipts" drops to +0.02. Eliminates DEC_09-type metric disambiguation failures.

**Scoring formula:**
- Base: token containment (0-1)
- +0.2 per positive modifier match (total, net, gross, etc.)
- -0.15 per negative modifier in row
- -0.3 for subcategory when total requested
- +0.1 for exact substring match

---

### 7.3 Era-Aware Search Windows (DONE — Apr 3)

**Status:** Implemented as `preferred_pub_years()` in `solve.py`.

**What:** Replaces flat `year+1` proximity scoring with era-aware preferred publication years:
- Pre-1945: 9-year window `[year+1, year+2, year, year+3, ..., year+12]`
- 1945-1976: 5-year window `[year+1, year+2, year, year+3, year+4]`
- Post-1977: 3-year window `[year+1, year, year+2]`

**Impact:** Better ranking for historical questions (1930s-1940s data often published 10+ years later).

---

### 7.4 Question Router (DONE — Apr 3)

**Status:** Implemented as `route_question()` in `solve.py`.

**What:** Deterministic classifier dispatches questions to the right pipeline:
- **Decompose:** multi-year questions, difference/ratio/percent_change, multi-year superlatives, multi-year mean
- **Deterministic:** single-year lookups, sums, single-year superlatives/averages
- **Fallback:** if primary route fails, tries the other pipeline

**Routing split on 246 questions:** 101 deterministic / 145 decompose (41%/59%).

---

### 7.5 Conflict Detection (DONE — Apr 3)

**Status:** Implemented as `detect_conflicts()` in `solve.py`.

**What:** Detects period (fiscal vs calendar), unit (millions vs billions), and metric variant (total vs net) conflicts across search results. Injects warnings into LLM evidence.

**Test results:** 8/10 sample questions had period conflicts detected (expected — Treasury data mixes fiscal/calendar).

---

### 7.6 Candidate Answer Objects (DONE — Apr 3)

**Status:** Implemented as `AnswerCandidate` dataclass in `solve.py`.

**What:** Structured return type from `deterministic_solve()` with: value, numeric, row_label, table_title, period_basis, operation, source_pipeline, confidence, conflicts, evidence. Enables future cross-pipeline comparison and voting.

---

### 7.7 Stochastic Multi-Path with Majority Vote (NOT DONE)

**Idea:** Run deterministic_solve 3 times with different random seeds. Take majority vote.

**Expected Impact:** +3-5% accuracy. **Cost:** 3× slower.

---

### 7.8 Search Recall Improvement (NOT DONE — Highest Priority)

**Current:** 23% recall on first 30 questions (search finds expected source file in top 5 results).

**Diagnosis:** The search finds files in the right era but often misses the exact bulletin month. Common patterns:
- Right year, wrong month (e.g., expected 1982_03, got 1982_01)
- Right decade, too early (e.g., expected 1944_01 for FY1934 data, got 1939 files)
- Empty results for some questions (keyword mismatch)

**Proposed fixes:**
- Broader month coverage within matched year
- Table title indexing (currently only searches within file content)
- Multi-pass search: narrow first, then widen if no results

---

## 8. Implementation Details & Edge Cases

### 8.1 Fiscal Year Calculation

**Pre-1977:**
- FY1940 = July 1, 1939 to June 30, 1940
- Monthly data for FY1940: Jul 1939, Aug 1939, ..., Jun 1940

**Post-1977:**
- FY1980 = October 1, 1979 to September 30, 1980
- Monthly data for FY1980: Oct 1979, Nov 1979, ..., Sep 1980

**Search Strategy:**
- Question asks for "FY1940"
- Look for bulletin from year ≥ 1940 (data published next year)
- Extract rows labeled "1940" or "FY1940"
- Rows may span two years if FY crosses calendar boundary

### 8.2 Unit Conversion

**Common Scales:**
- "(In millions of dollars)" → raw number × 1M
- "(In thousands)" → raw number × 1K
- "(In billions of dollars)" → raw number × 1B
- "(Percent)" → already a percentage

**Implementation:** Extracted in `_parse_table_at()`, stored in `units` field.

**LLM Instruction:** "Check the units field for scale (millions, thousands, etc.)"

### 8.3 Footnote & Revision Markers

**Format in Tables:**
- `2,602r/` = 2,602 (revised, `r/` is marker, not part of number)
- `6,548*` = 6,548 (footnoted, `*` is marker)
- `3,000(1)` = 3,000 (footnote reference)

**Cleanup:** Regex strips non-numeric characters:
```python
def _parse_numeric(val_str):
    cleaned = re.sub(r'[,$ ]', '', val_str.replace('\u2212', '-'))
    cleaned = cleaned.strip().rstrip('%')
    # Handle (123) → -123
    m = re.match(r'^\(([0-9,.]+)\)$', cleaned)
    if m:
        cleaned = '-' + m.group(1).replace(',', '')
    return float(cleaned)
```

### 8.4 Negative Values in Parentheses

**Format:** `(2,920)` = -2,920 (standard accounting notation)

**Handled in:** `_parse_numeric()` regex pattern (see above).

### 8.5 Monthly Value Extraction for CY

**Constraints:**
- CY = Jan-Dec (same calendar year)
- FY = Jul-Jun (pre-1977) or Oct-Sep (post-1977)
- Monthly rows may be labeled: "January", "1940-January", "01", etc.

**Algorithm:**
1. Identify all rows with month names (Jan-Dec)
2. Filter for target year (if year specified)
3. Preserve order: Jan=1, Feb=2, ..., Dec=12
4. If "-" (dash) or missing month, use 0
5. Skip "Total", "Fiscal", "FY" rows
6. Sum all 12 values

**Example (from evidence):**
```
ROW: National Defense Expenditures
  Jan. (month 1): 132
  Feb. (month 2): 129
  Mar. (month 3): 143
  ...
  Dec. (month 12): 473
```

Python sum: `sum([132, 129, 143, ..., 473])` = 2,602

---

## 9. Configuration & Environment

### 9.0 Evaluation modes (Harbor manifest vs OpenHands MCP)

Sentient Arena tasks do not all expose the same filesystem contract. Treat these as **two different stacks**:

1. **Harbor / Goose + task resources (subset corpus)**  
   The platform typically provides `/app/resources/manifest.json` and a **preselected** set of files (aligned with CSV `source_files` / `source_docs` per task), not all Treasury Bulletin text files at once. Prompts that tell the agent to `cat` the manifest and grep under `/app/resources/` match this mode (for example `submit-goose/prompts/system.j2`). Traces often show `harbor-task` in the recipe line and `trajectory.agent.name: goose`.

2. **OpenHands + MCP + enriched SQLite**  
   Root `prompts/system.j2` assumes **MCP tools** (`officeqa_*`) backed by `server/tools.py` / `server/db.py` — database-wide search, not “read every raw `.txt` in `/app/corpus/`” in one shot. Use `arena.yaml` / `submit/arena.yaml` with `openhands-sdk` and `run_mcp.sh`. Traces should show the OpenHands harness and MCP tool traffic if the submission is wired correctly.

**Validating which mode a run used:** run `python3 scripts/audit_traces.py <trace_dir>` on pulled trajectory JSON. Goose + harbor + no `officeqa_*` substrings usually means the file/manifest contract; OpenHands MCP runs should show MCP tool names in tool-call payloads when serialized into step messages.

### 9.1 Arena YAML Configs

**analyst/arena.yaml:**
- Model: minimax-m2.5
- Max turns: 20
- Timeout: 300s
- Mode: briefing
- Solver: solve_briefing.py + MiniMax mentor

**nomcp/arena.yaml:**
- Model: minimax-m2.5 (same)
- Max turns: 8
- Timeout: 300s
- Mode: direct
- Solver: solve.py (deterministic)

### 9.2 Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| CORPUS_DIR | /app/corpus | 696 TXT files, 1939-2025 |
| INDEX_PATH | /tmp/table_index.jsonl | (Unused in current version) |
| KEYWORD_INDEX_PATH | /tmp/keyword_index.txt | Fast table lookup index |
| BUILD_SCRIPT | /installed-agent/build_index.py | Builds keyword_index at startup |
| SOLVE_MODE | briefing | Switches solve_briefing vs solve.py |
| OPENROUTER_API_KEY | (set via environment / `.env`) | LLM access token |
| LLM_API_KEY | (same) | Alternate name for token |

### 9.3 Resource Limits

- **Timeout:** 300s per question (hard limit in arena)
- **Tool calls:** 10 max in nomcp/solve.py (self-enforced)
- **LLM context:** ~12K chars for analyst prompt, ~8K for evidence
- **Tarball size:** 200MB max (slim DB without cell_blobs = 118MB gzip)

---

## 10. References & Related Documents

### Memory Files (from .claude/projects/.../memory/):
- `project_status.md` — Current score & timeline
- `project_parse_findings.md` — Parser accuracy (46% correct, 25% partial)
- `project_tool_fix_findings.md` — Term index at 41% miss rate
- `feedback_minimax_ignores_prompts.md` — Imperative rules don't work
- `completion_tool_fix_april2.md` — Apr 2, 2026 fixes (180.4 score)
- `project_grep_primary_v2.md` — grep > DB search strategy
- `project_decompose_pipeline.md` — 8-phase decompose

### Source Files (absolute paths):
- `analyst/arena.yaml` — Best-scoring config
- `analyst/prompts/system.j2` — Mentor prompt
- `analyst/solve_briefing.py` — Briefing generator
- `nomcp/solve.py` — Deterministic solver (3600+ lines)
- `nomcp/bottomup/solve_decompose.py` — Decompose pipeline
- `analyst/skills/computation_patterns.md` — Math templates
- `analyst/skills/financial_glossary.md` — Grep keywords

---

## 11. Lessons Learned

1. **Mentor framing beats imperative rules:** "You are a mentor" works. "DO NOT loop" doesn't.
2. **Evidence formatting is everything:** Pre-extracted values reduce LLM confusion by 10-20%.
3. **Python computes better than LLM:** Never ask LLM to do arithmetic. Extract VALUES + OPERATION, compute in Python.
4. **Search quality >> LLM reasoning:** 80% of failures trace to wrong search result, not LLM confusion.
5. **Period basis tagging is critical:** CY vs FY confusion causes 15%+ of failures. Tag explicitly.
6. **Deterministic > interactive:** nomcp deterministic_solve more reliable than tool loops.
7. **Index bottleneck:** 41% of tables missed by keyword index. Direct COLUMN LIKE search essential.

---

**Document Last Updated:** April 3, 2026
**Generated By:** Architecture Analysis Agent
**For:** Team review and improvement planning
