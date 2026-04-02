# Ideal Tool Design for OfficeQA Arena

## Problem Statement

MiniMax M2.5 has 15 iterations to answer 246 questions about US Treasury Bulletins. Current system scores ~25% (5/20 dev). The model over-searches: it calls `search_tables` 5+ times without converging on the right data, exhausting its iteration budget. The ideal system should reach a correct answer in 3-5 tool calls for most question types.

### Core Insight

The model's job should be **asking the right question** -- the tools should do the heavy lifting. Every tool call that returns ambiguous or partial data causes the model to burn another iteration "clarifying." The fix is not more tools or smarter prompts alone; it is **tool responses that eliminate ambiguity in one shot**.

---

## 1. Question Type Taxonomy and Ideal Call Sequences

### Type A: Simple Lookup (1 value from 1 table) -- ~15% of questions

**Examples:** UID0001 (defense spending 1940), UID0012 (highest spending dept FY1955), UID0002 (VA expenditures FY1934)

**Ideal sequence (3 calls):**
1. `extract_values(query, metric, year)` -- returns the value directly
2. `compute_expression(...)` -- format/round if needed (often skippable)
3. Write answer

**Current failure mode:** `extract_values` returns 5 rows from 2 tables, model cannot tell which is the answer. It calls `search_tables` again with different keywords, then `get_table_profile`, then `query_table_rows` -- 6+ calls for a 1-call problem.

### Type B: Multi-Step Computation (math on 1-2 extracted values) -- ~30% of questions

**Examples:** UID0015 (Box-Cox difference), UID0032 (sum tobacco - sum wool), UID0017 (total bids + percent noncash)

**Ideal sequence (3-4 calls):**
1. `extract_values(query, metric, year)` -- get the raw values
2. (Optional) Second `extract_values` if values come from different tables
3. `compute_expression(formula, variables)` -- do the math
4. Write answer

**Current failure mode:** Model extracts values but then does mental math instead of calling `compute_expression`, or gets confused by which row contains the target metric.

### Type C: Multi-Year / Time-Series (aggregate across many months/years) -- ~25% of questions

**Examples:** UID0007 (geometric mean, 79 months), UID0029 (avg yield spread, 120 months), UID0013 (OLS regression, 14 years)

**Ideal sequence (3-4 calls):**
1. `get_time_series(query, metric, year_start, year_end, granularity)` -- returns ALL values in one shot
2. `compute_expression(formula, variables)` -- geometric_mean, linreg, mean, etc.
3. Write answer

**Current failure mode:** Model calls `extract_values` for each year individually, burns 10+ iterations on a 10-year series, never reaches the computation step.

### Type D: Cross-Table (data from 2+ bulletins) -- ~20% of questions

**Examples:** UID0028 (min yield spread month -> railroad retirement), UID0022 (agriculture outlays from 2 bulletins -> regression)

**Ideal sequence (4-5 calls):**
1. `extract_values(query_part_1, ...)` -- get first data point
2. `compute_expression(...)` -- intermediate computation (e.g., find the min month)
3. `extract_values(query_part_2, ...)` -- get second data point using result from step 2
4. `compute_expression(...)` -- final computation
5. Write answer

**Current failure mode:** Model searches broadly, finds wrong tables, retries. The chaining of "output of step 2 feeds step 3" is where iteration budgets explode.

### Type E: Statistical / Regression -- ~20% of questions

**Examples:** UID0013 (OLS regression), UID0022 (linear regression + predict), UID0049 (coefficient of variation)

**Ideal sequence (3-4 calls):**
1. `get_time_series(...)` -- get all data points
2. `compute_expression("linreg(...)")` -- fit the model, returns [slope, intercept]
3. (Optional) `compute_expression(...)` -- compute prediction
4. Write answer

**Current failure mode:** Same as Type C -- iteration exhaustion gathering data.

### Type F: Visual / Chart -- ~5% of questions

**Examples:** UID0030 (count local maxima), UID0035 (count leading digit 1)

These are likely unsolvable with text-only data. Strategy: write best-guess answer early, do not waste iterations.

---

## 2. Ideal Tool Response Format

### Principle: Every response must answer "What do I do next?"

The model wastes iterations because tool responses are ambiguous. Each response should contain:
1. **The data** (obviously)
2. **Confidence signal** -- how well does this match the query?
3. **Next-step hint** -- what tool to call next if this is not sufficient

### 2a. `extract_values` Response (the workhorse)

Current response returns a list of table matches with rows. The problem: too many matches, unclear which is right, rows are truncated at 5 per table.

**Ideal response format:**

```json
{
  "best_match": {
    "table_pk": 4821,
    "table_title": "Budget Expenditures by Function -- 1940-1949",
    "file_id": "treasury_bulletin_1950_02.txt",
    "confidence": "high",
    "match_reason": "exact metric match + year coverage",
    "values": [
      {"label": "National defense", "year": 1940, "month": null, "value": 2602, "unit": "millions"},
      {"label": "National defense", "year": 1941, "month": null, "value": 6301, "unit": "millions"}
    ],
    "total_matching_rows": 24,
    "columns_available": ["National defense", "Veterans' services", "Interest on public debt", ...],
    "years_covered": [1940, 1941, 1942, 1943, 1944, 1945, 1946, 1947, 1948, 1949]
  },
  "alternatives": [
    {"table_pk": 4822, "table_title": "...", "confidence": "low", "reason": "partial keyword match only"}
  ],
  "action_hint": "If you need more rows from best_match, call query_table_rows with table_pk=4821. If this is the wrong table, try get_file_structure on the source bulletin."
}
```

**Key differences from current:**
- **Single `best_match` not a list** -- forces the tool to commit to a ranking, reduces model ambiguity
- **`confidence` field** -- "high" means the model can trust it and move to compute; "low" means it should search differently
- **`match_reason`** -- explains WHY this table was chosen, so the model can evaluate
- **`years_covered` and `columns_available`** -- the model knows immediately if it has all the data it needs or must search again
- **`unit` field** -- critical for Treasury data where the same number can be in millions, thousands, or raw dollars
- **`total_matching_rows`** -- tells the model "there are 24 rows, you saw 5; call query_table_rows for the rest"
- **`action_hint`** -- explicit guidance on what to do next

### 2b. `get_time_series` Response (new tool, replaces `get_multi_year_series`)

The current `get_multi_year_series` calls `extract_values` per year, which is O(N) searches. This should be a single DB query.

**Ideal response format:**

```json
{
  "metric": "national defense expenditures",
  "table_pk": 4821,
  "table_title": "Budget Expenditures by Function -- 1940-1949",
  "file_id": "treasury_bulletin_1950_02.txt",
  "unit": "millions",
  "granularity": "monthly",
  "series": {
    "1942-03": 1245, "1942-04": 1302, "1942-05": 1456,
    "...": "...",
    "1948-10": 3201
  },
  "count": 79,
  "coverage": {"requested": 79, "found": 79, "missing": []},
  "action_hint": "All 79 values found. Use compute_expression with geometric_mean() on these values."
}
```

**Key design decisions:**
- **Returns ALL values, not paginated** -- for 120 months, this is ~2KB of JSON. Well within context limits.
- **`coverage` object** -- immediately tells the model if any months are missing, preventing phantom data problems
- **`missing` array** -- if 3 of 79 months are missing, the model knows exactly which ones and can decide whether to search a different bulletin
- **`granularity`** -- "monthly" vs "annual" vs "quarterly" so the model knows if it needs to aggregate

### 2c. `compute_expression` Response

Current response is fine (`{"ok": true, "result": 4962.46}`). One addition:

```json
{
  "ok": true,
  "result": 4962.46,
  "expression_echo": "geometric_mean(1245, 1302, ..., 3201)",
  "variable_count": 79,
  "intermediate_values": {
    "product": 1.23e+250,
    "n": 79
  }
}
```

**Why `expression_echo`:** The model sometimes passes wrong variable names. Echoing the resolved expression lets it catch mistakes without burning another iteration. The `intermediate_values` help debug statistical computations.

### 2d. `search_tables` Response

Only used when `extract_values` fails. Should return richer metadata to prevent the model from needing `get_table_profile` as a separate call.

```json
{
  "candidates": [
    {
      "table_pk": 4821,
      "table_title": "Budget Expenditures by Function",
      "file_id": "treasury_bulletin_1950_02.txt",
      "bulletin_date": "February 1950",
      "score": 0.87,
      "columns": ["National defense", "Veterans' services", "Interest on public debt"],
      "row_labels_sample": ["January 1940", "February 1940", "Total calendar year 1940"],
      "years_covered": [1940, 1941, 1942, 1943, 1944, 1945, 1946, 1947, 1948, 1949],
      "row_count": 130,
      "unit_hint": "millions"
    }
  ],
  "total_matches": 3,
  "action_hint": "Use query_table_rows(table_pk=4821, row_label='National defense', year=1940) to get values."
}
```

**Key addition: `columns`, `row_labels_sample`, `years_covered` inline.** This eliminates the need for `get_table_profile` as a separate call. The model sees column names and can go straight to `query_table_rows`.

---

## 3. Tool Architecture: Fewer, More Powerful Tools

### Recommended: 4 Primary Tools + 2 Reference Tools

| Tool | Purpose | When to use |
|------|---------|-------------|
| **`extract_values`** | Find + fetch values in one call | First call for every question |
| **`get_time_series`** | Fetch N values across a date range | Any question mentioning year ranges or "from X to Y" |
| **`query_table_rows`** | Targeted fetch from a known table | After extract_values when you need more rows |
| **`compute_expression`** | All arithmetic, stats, regression | After data extraction |
| **`get_cpi_index`** | CPI-U reference data | Inflation adjustment questions |
| **`get_file_structure`** | Browse a bulletin's tables | Fallback when search fails |

### Tools to REMOVE or MERGE

| Current Tool | Recommendation | Reason |
|-------------|---------------|--------|
| `search_tables` | Merge into `extract_values` | The model should never search without fetching. Searching alone wastes an iteration. |
| `get_table_profile` | Merge into `search_tables` response | Profile data (columns, years) should be inline in search results. |
| `get_multi_year_series` | Replace with `get_time_series` | Current impl does N separate searches. New one should do 1 DB query. |
| `get_fiscal_year_bounds` | Encode in prompt | Only 2 patterns (pre/post 1977). Not worth a tool call. |
| `resolve_agency_alias` | Encode in search scoring | Agency aliases should be resolved inside `extract_values`, not as a separate tool call. |

### Why Fewer Tools Win with MiniMax M2.5

MiniMax M2.5 is "great at function calling but tends to over-search." Every additional tool is a branching point the model must evaluate. With 10 tools, it spends reasoning tokens deciding which to call. With 4, the decision tree is:

```
Question arrives
  |
  +--> Does it mention a year range or "from X to Y"?
  |      YES --> get_time_series
  |      NO  --> extract_values
  |
  +--> Got data?
  |      YES --> compute_expression (if math needed) --> write answer
  |      NO  --> query_table_rows with different params, or get_file_structure
  |
  +--> Inflation adjustment?
         YES --> get_cpi_index --> compute_expression
```

This is a 3-4 step decision tree, not a 7-step exploration.

---

## 4. Prompt Decision Tree

```
You are a Treasury data retrieval agent. Answer in 3-5 tool calls.

STEP 1 - CLASSIFY the question:
  (A) Single value lookup --> extract_values
  (B) Year range / "from X to Y" / time series --> get_time_series
  (C) Needs inflation adjustment --> extract_values + get_cpi_index

STEP 2 - EXTRACT:
  Call the tool from Step 1. Read the "confidence" field.
  - "high": proceed to Step 3
  - "low": read "action_hint" and follow it (ONE retry only)

STEP 3 - COMPUTE (if math needed):
  Call compute_expression with ALL extracted values as variables.
  NEVER do math in your head. ALWAYS use compute_expression.

STEP 4 - WRITE:
  Write ONLY the numeric answer to /app/answer.txt.
  Match the requested format: check for "millions", "billions",
  "percent", "nearest hundredths", bracket format, etc.

BUDGET RULE: Write your BEST answer by iteration 5.
You can refine later, but never reach iteration 6 without an answer file.

DOMAIN HINTS (encoded, not tool calls):
- Year Y data is often in the Y+1 bulletin (e.g., 1940 data in 1941_01)
- Fiscal year before 1977: Jul 1 (Y-1) to Jun 30 (Y)
- Fiscal year 1977+: Oct 1 (Y-1) to Sep 30 (Y)
- 1940s "national defense" = "War Department" + "Navy Department"
- Units in tables: look for "in millions" or "(millions of dollars)" in table title
```

---

## 5. Traced Ideal Sequences for 10 Dev Questions

### UID0012 -- Highest spending department, FY1955

**Question:** "What was the amount spent in millions of nominal dollars by the highest spending U.S Federal Department in the fiscal year of 1955?"
**Answer:** `36080 million`
**Source:** treasury_bulletin_1958_10.txt

**Ideal sequence (3 calls):**
1. `extract_values(query="federal department expenditures fiscal year 1955", metric="department expenditures", year=1955)`
   - Returns: table "Administrative Budget Expenditures by Department and Agency" with rows for each department. Best match row: "Department of Defense" = 36,080
   - confidence: high
2. `compute_expression(expression="max(36080, 4366, 507, ...)", variables={})`
   - Or: model reads the table, identifies 36080 as max directly from the response
   - Returns: 36080
3. Write `36080 million`

**Current failure:** Model searches for "highest spending department" -- too vague. Gets wrong tables. Retries 4x.

### UID0007 -- Geometric mean of monthly expenditures Mar 1942 - Oct 1948

**Question:** Geometric mean of budget expenditures, March 1942 to October 1948
**Answer:** `4962.46`
**Source:** treasury_bulletin_1950_02.txt

**Ideal sequence (3 calls):**
1. `get_time_series(query="budget expenditures", metric="total budget expenditures", year_start=1942, year_end=1948, month_start=3, month_end=10)`
   - Returns: 79 monthly values in `series` dict
   - coverage: {requested: 79, found: 79, missing: []}
2. `compute_expression(expression="geometric_mean(1245, 1302, ..., 3201)")`
   - The model constructs this from the 79 values in the series
   - Returns: 4962.46
3. Write `4962.46`

**Current failure:** Model calls extract_values for each year (1942, 1943, ..., 1948) -- 7 calls just for data. Runs out of iterations before computing.

### UID0029 -- Average yield spread, 1960-1969

**Question:** Average yield spread between corporate Aa bonds and Treasury bonds, all months 1960-1969
**Answer:** `0.88525`
**Source:** treasury_bulletin_1970_06.txt

**Ideal sequence (3-4 calls):**
1. `get_time_series(query="corporate Aa bonds treasury bonds yield", year_start=1960, year_end=1969, file_id="1970_06")`
   - Returns: 120 monthly rows with columns for "Corporate Aa" and "Treasury bonds"
   - OR: returns the spread directly if it is a column
2. `compute_expression(expression="mean(spread_values...)")`
   - If the tool returned two columns, model first computes spreads, then mean
   - Returns: 0.88525
3. Write `0.88525`

### UID0013 -- OLS regression on income tax receipts 1929-1942

**Question:** Fit OLS, return [slope, intercept]
**Answer:** `[0.096, -184.143]`
**Source:** treasury_bulletin_1942_07.txt

**Ideal sequence (3 calls):**
1. `get_time_series(query="individual income tax receipts net refunds", year_start=1929, year_end=1942, file_id="1942_07")`
   - Returns: 14 annual values
2. `compute_expression(expression="linreg([1929,1930,...,1942], [0.1, 0.1, ...])")`
   - Returns: [0.096, -184.143] (slope, intercept)
3. Write `[0.096, -184.143]`

### UID0005 -- Inflation-adjusted difference, 1953 vs 1940 defense spending

**Question:** Absolute difference of CPI-adjusted defense sums
**Answer:** `39482.03`
**Sources:** treasury_bulletin_1941_01.txt, treasury_bulletin_1954_02.txt

**Ideal sequence (5 calls):**
1. `extract_values(query="national defense expenditures monthly 1940", year=1940, file_id="1941_01")`
   - Returns: 12 monthly values for 1940 defense spending
2. `extract_values(query="national defense expenditures monthly 1953", year=1953, file_id="1954_02")`
   - Returns: 12 monthly values for 1953 defense spending
3. `get_cpi_index(year=1953)`
   - Returns: {year: 1953, annual_avg: 26.7}
   - (1940 CPI-U from Minneapolis Fed is the base -- model needs this from the CPI data too)
4. `compute_expression(expression="abs(sum_1953 - sum_1940 * cpi_1953 / cpi_1940)", variables={"sum_1953": 44463, "sum_1940": 2602, "cpi_1953": 26.7, "cpi_1940": 14.0})`
   - Returns: 39482.03
5. Write `39482.03`

### UID0028 -- Min yield spread month -> railroad retirement receipts

**Question:** Find min yield spread month (1960-1969), then look up railroad retirement receipts for that month
**Answer:** `92000000`
**Sources:** treasury_bulletin_1970_06.txt, treasury_bulletin_1964_12.txt

**Ideal sequence (4-5 calls):**
1. `get_time_series(query="corporate Aa bonds treasury bonds yield", year_start=1960, year_end=1969, file_id="1970_06")`
   - Returns: 120 monthly values (or pairs) for yield data
2. `compute_expression(expression="min(spread_values...)")`
   - Returns: the minimum spread value. Model reads the series to identify the month (e.g., August 1964).
   - Better: tool returns the min AND its index/label
3. `extract_values(query="railroad retirement trust receipts", year=1964, month=8)`
   - Returns: railroad retirement receipts = 92 (in millions)
4. `compute_expression(expression="92 * 1000000")` -- convert to nominal dollars
5. Write `92000000`

### UID0015 -- Box-Cox transformed difference

**Question:** Difference of Box-Cox(lambda=0.75) of net interest outlays 1981 vs 1980
**Answer:** `6.1596`
**Source:** treasury_bulletin_1981_11.txt

**Ideal sequence (3 calls):**
1. `extract_values(query="net interest outlays", year=1981, file_id="1981_11")`
   - Returns: FY1981 value AND the "comparable period" FY1980 value (both on same table)
   - Values: 1981 = 68.7, 1980 = 52.5 (billions)
2. `compute_expression(expression="boxcox(a, 0.75) - boxcox(b, 0.75)", variables={"a": 68.7, "b": 52.5})`
   - Returns: 6.1596
3. Write `6.1596`

### UID0032 -- Tobacco vs wool import values

**Question:** Absolute difference: sum(tobacco Feb-Jun 1940) - sum(wool Feb-Jun 1940)
**Answer:** `11.60`
**Source:** treasury_bulletin_1941_03.txt

**Ideal sequence (3-4 calls):**
1. `extract_values(query="tariff schedule imports tobacco wool", year=1940, file_id="1941_03")`
   - Returns: table with rows for tobacco and wool, columns for each month
   - Values include Feb-Jun 1940 for both commodities
2. `compute_expression(expression="abs(sum(tobacco_feb, tobacco_mar, tobacco_apr, tobacco_may, tobacco_jun) - sum(wool_feb, wool_mar, wool_apr, wool_may, wool_jun))", variables={...})`
   - Returns: 11.60
3. Write `11.60`

### UID0036 -- Liquidity ratio change (dot-com to housing crash)

**Question:** Change in US liquidity ratio from 2001 (Amazon lowest) to 2008 (bank bailout)
**Answer:** `9.89%`
**Source:** treasury_bulletin_2011_09.txt

**Ideal sequence (3-4 calls):**
1. `extract_values(query="US liquidity ratio marketable liabilities foreign official institutions", file_id="2011_09")`
   - Returns: table with liquidity ratios by year, including 2001 and 2008
   - The question decodes to: dot-com burst = 2001, housing crash = 2008
2. `compute_expression(expression="abs(a - b)", variables={"a": ratio_2008, "b": ratio_2001})`
   - Returns: 9.89
3. Write `9.89%`

**Key insight:** The domain knowledge decoding (Amazon lowest stock -> 2001, bank bailout -> 2008) must happen in the MODEL's reasoning, not in tools. The prompt should include a hint table for common historical event references.

### UID0009 -- Weighted average denomination of US currency

**Question:** Bureau merged with Public Debt = Financial Management Service. Look up currency data from June 2011 report.
**Answer:** `32.703`
**Source:** treasury_bulletin_2011_09.txt

**Ideal sequence (3-4 calls):**
1. `extract_values(query="coin currency circulation outstanding", file_id="2011_09", year=2011)`
   - Returns: table with denominations, pieces in circulation, and total value
2. `compute_expression(expression="total_value / total_pieces", variables={"total_value": X, "total_pieces": Y})`
   - Returns: 32.703
3. Write `32.703`

---

## 6. Critical Design Principles

### 6a. The "One Search, All Data" Rule

Every data-retrieval tool should return ENOUGH data that the model never needs to call it again for the same table. Currently, `extract_values` returns 5 rows per table. If a question needs 12 monthly values, the model must call `query_table_rows` again. This wastes an iteration.

**Fix:** When `extract_values` or `get_time_series` identifies the right table, return ALL matching rows (up to 200). For monthly data across a decade (120 values), this is ~5KB of JSON -- well within model context.

### 6b. The "Confidence Gate" Pattern

Every response includes a `confidence` field. The prompt instructs the model:
- `confidence: "high"` -> proceed to compute/answer
- `confidence: "medium"` -> proceed but note uncertainty
- `confidence: "low"` -> try ONE alternative search, then proceed anyway

This prevents the infinite-retry loop where the model keeps searching because it is "not sure."

### 6c. The "Budget Awareness" Pattern

The tool response should include remaining iteration budget:

```json
{
  "data": {...},
  "meta": {
    "iteration": 2,
    "budget_remaining": 13,
    "suggestion": "You have enough budget. Proceed to compute_expression."
  }
}
```

This is better encoded in the prompt/harness than in the tool, but the principle stands: the model must feel urgency to converge.

### 6d. Unit Detection in Tool Responses

Many errors come from unit confusion (millions vs billions vs raw dollars). Every numeric response should include:

```json
{"value": 2602, "unit": "millions of dollars", "source_text": "(In millions of dollars)"}
```

The `source_text` field shows the exact unit annotation from the original table header, letting the model verify.

### 6e. The "Action Hint" Pattern

Every tool response ends with a 1-sentence hint about what to do next:
- "All data found. Call compute_expression with geometric_mean()."
- "3 of 12 months missing. Call query_table_rows(table_pk=4821, year_range=[1943,1943]) to fill gaps."
- "No matching tables. Try get_file_structure(file_id='1950_02') to browse available tables."

This nudges the model toward convergence instead of exploration.

---

## 7. Historical Event Reference Table (for prompt)

Several questions reference events indirectly. Include this in the system prompt to save tool calls:

| Reference | Year |
|-----------|------|
| Start of World War II (US entry) | 1941 |
| End of World War II | 1945 |
| Korean War started | 1950 |
| Korean War ended | 1953 |
| Dot-com bubble burst / Amazon lowest stock | 2001 |
| US housing crash / bank bailout (TARP) | 2008 |
| COVID-19 pandemic declared | 2020 (March 11) |
| Bureau of Fiscal Service formed | 2012 (merger of Financial Management Service + Bureau of Public Debt) |

---

## 8. Implementation Priority

| Priority | Change | Expected Impact |
|----------|--------|-----------------|
| P0 | Add `confidence` + `action_hint` + `unit` to all tool responses | Reduces wasted search iterations by ~50% |
| P0 | Build `get_time_series` as single-query DB operation | Unblocks all multi-year questions (Type C/E, ~45% of dataset) |
| P0 | Inline column/year metadata into `search_tables` response (kill `get_table_profile` as separate call) | Saves 1 iteration per question |
| P1 | Increase default row limit in `extract_values` to return all matching rows (up to 200) | Eliminates need for follow-up `query_table_rows` in most cases |
| P1 | Add `linreg` return format as `[slope, intercept]` to `compute_expression` | Direct match to bracket-list answer format |
| P1 | Add historical event table to prompt | Saves 1-2 iterations on ~10% of questions |
| P2 | Add `boxcox(value, lambda)` to safe_eval if not present | Needed for UID0015-type questions |
| P2 | Agency alias resolution inside search scoring (not a separate tool) | Saves 1 iteration when agency names don't match |
| P2 | File_id suggestion in `extract_values` -- when the question mentions a specific bulletin date, auto-map to file_id | Reduces search space dramatically |

---

## 9. Summary: The 3-Call Ideal

For the majority of questions, the ideal is:

```
Call 1: extract_values or get_time_series  (FIND + FETCH)
Call 2: compute_expression                  (MATH)
Call 3: write answer                        (OUTPUT)
```

Every tool design decision should be evaluated against: "Does this get us closer to the 3-call ideal, or does it create another branching point for the model to explore?"
