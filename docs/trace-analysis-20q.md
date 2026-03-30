# Trace Analysis: 20-Question Test Run (2026-03-30)

**Run:** `run-20260330-173547-54fd59/full-20q-v1`
**Model:** `minimax/minimax-m2.5` via OpenRouter
**Harness:** OpenCode v1.3.7, max_iterations=15, temperature=0.0
**MCP Server:** SSE transport at `http://172.17.0.1:8081/sse`

## Executive Summary

- **Completed:** 8 of 20 questions (4 still running/timed out at analysis time)
- **Pass rate:** 6/8 = 75% (of completed), 6/7 = 85.7% (as reported by Arena for first 7)
- **Failures:** uid0194 (wrong data values extracted), uid0030 (impossible question -- chart/visual)
- **Total cost:** $1.77 across 8 completed questions
- **Key finding:** MCP tools work well for structured table lookups but fail when query_table_rows returns 0 rows due to filter mismatches. Grep is the critical fallback that saves most questions. The model follows the decision-tree prompt reasonably well but burns many iterations on repeated MCP searches before falling back to grep.

---

## Per-Question Detailed Analysis

### uid0041 -- PASS (Theil index, Rural Electrification Admin, FY 1961-1970)

| Metric | Value |
|--------|-------|
| Steps | 32 |
| Agent execution time | ~7 min |
| Cost | $0.184 |
| Input tokens | 872,842 (687K cached) |
| Output tokens | 8,060 |
| Answer written | Step 29 |
| Submitted | 0.011 |
| Correct | 0.011 |

**Tool call sequence:**

| Step | Tool | Response Size | Useful? | Notes |
|------|------|---------------|---------|-------|
| 1 | search_tables (REA + Treasury Holdings + Securities) | 6,152 | YES | Found table_pk 51379, score 111.5 -- excellent match |
| 2 | query_table_rows (pk=51379, column_label=REA, year=1961) | 303 | NO | 0 rows -- column_label filter too specific |
| 3 | query_table_rows (pk=51379, row_label=REA) | 395 | NO | 0 rows -- row_label filter mismatch |
| 4 | extract_values (REA, year=1965) | 2,146 | YES | Got some values |
| 5 | get_time_series (REA, 1961-1970, file=1973_09) | 669 | PARTIAL | Got some years but not all |
| 6 | get_time_series (REA, 1961-1963, file=1964_01) | 756 | PARTIAL | More data but incomplete |
| 7 | compute_expression (mean of initial values) | 116 | YES | But values were wrong at this point |
| 8 | bash (python Theil calc) | 35 | YES | Got 0.143 -- wrong values |
| 9-10 | get_time_series (various files) | ~750 | PARTIAL | Collecting more data |
| 11-12 | query_table_rows (pk=51379, various years) | 6,400 | MIXED | Step 11 returned lots of rows, step 12 was empty |
| 13 | get_time_series (file=1972_01) | 715 | YES | More data |
| 14 | read (1972_01 raw file) | 7,141 | YES | Switched to raw file reading |
| 15 | grep (Table FD-10 in 1972_01) | 171 | YES | Found table at line 1730 |
| 16-17 | read (targeted offsets) | 12,410 | YES | Got the actual table data |
| 18 | get_time_series (1961, file=1962_01) | -- | PARTIAL | |
| 19-20 | grep (various patterns) | 14 each | NO | No matches -- bad regex patterns |
| 21 | glob (1960s files) | 14 | NO | Glob doesn't work in container |
| 22-23 | bash (ls commands) | 940 | YES | Found file listing |
| 24 | grep (Treasury Holdings in 1962_01) | 166 | YES | Found the table |
| 25 | read (1962_01 at offset) | 3,705 | YES | Got 1961 data |
| 26-27 | grep + read (1963_01) | 3,667 | YES | Got 1962-1963 data |
| 28 | bash (python Theil calc with correct values) | 104 | YES | 0.011 -- correct! |
| 29 | write answer | 24 | -- | 0.011 |
| 30-32 | verification reads | -- | -- | Double-checking |

**Analysis:**
- The model correctly found the right table on step 1 via search_tables.
- query_table_rows failed 3 times due to filter mismatches (column_label, row_label, year).
- The winning strategy was grep + read: finding the table heading in raw text, then reading targeted line ranges.
- **32 steps is very high.** The model burned ~12 steps on MCP tools that returned empty/partial data before switching to grep fallback.
- **Key issue:** query_table_rows returned 0 rows even when the table existed. The column_label/year filter semantics don't match what the model expects.
- **Decision tree compliance:** Used search_tables twice (steps 1, N/A), but then used many other MCP tools before grep. Did not write by iteration 7 -- wrote at step 29.

**Wasted calls:** Steps 2, 3, 19, 20, 21 (5 wasted = 16% of steps)

---

### uid0048 -- PASS (Criminal case dispositions, Alcohol Tax Bureau, Dec 1938)

| Metric | Value |
|--------|-------|
| Steps | 9 |
| Agent execution time | ~2 min |
| Cost | $0.040 |
| Input tokens | 193,127 (100K cached) |
| Output tokens | 1,398 |
| Answer written | Step 8 |
| Submitted | 3 |
| Correct | 3% |

**Tool call sequence:**

| Step | Tool | Response Size | Useful? | Notes |
|------|------|---------------|---------|-------|
| 1 | search_tables (criminal case + alcohol tax + bureau) | 4,398 | YES | Found table_pk 121, good match |
| 2 | query_table_rows (pk=121, year=1938, month=12) | 301 | NO | 0 rows returned |
| 3 | query_table_rows (pk=121, no filters) | 16,397 | YES | Got all rows -- data found! |
| 4 | read (1939_02 raw file) | 9,189 | YES | Confirmatory read |
| 5 | grep (Summary of Criminal Cases in 1939_02) | 134 | YES | Located at line 2325 |
| 6 | read (1939_02 at offset 2320) | 3,459 | YES | Got the table with exact values |
| 7 | compute_expression (abs(7 - 4)) | 60 | YES | Correct computation |
| 8 | write answer | 24 | -- | |

**Analysis:**
- **This is the ideal pattern.** search_tables -> query_table_rows -> grep+read for confirmation -> compute -> write.
- Only 1 wasted call (step 2: query with month=12 filter returned 0 rows).
- 9 steps total, wrote answer at step 8. Very efficient.
- The model correctly identified the table, extracted the data, and computed the answer.
- **Pattern: When query_table_rows with filters fails, immediately trying without filters works well.**

**Wasted calls:** 1 (step 2)

---

### uid0111 -- PASS (HP filter, FY 2010-2024 receipts/outlays)

| Metric | Value |
|--------|-------|
| Steps | 33 |
| Agent execution time | ~7 min |
| Cost | $0.280 |
| Input tokens | 1,355,100 (937K cached) |
| Output tokens | 7,275 |
| Answer written | Step 32 |
| Submitted | [-1832816, -2049753, 216937] |
| Correct | [-1832816, -2049753, 216937] |

**Tool call sequence highlights:**

| Steps | Activity | Notes |
|-------|----------|-------|
| 1-3 | search_tables (3 calls) | Found FFO-1 tables across multiple bulletins |
| 4-9 | query_table_rows (6 calls) | Extracted receipts/outlays for 2010-2024 across multiple tables |
| 10-13 | More search_tables + query_table_rows | Chasing FY2024 data specifically |
| 14 | get_file_structure (2025_03.txt) | 22,943 chars -- BLOATED response |
| 15-16 | grep (regex for receipts) | Both returned "No files found" |
| 17 | query_table_rows (row_label=2024) | 6,278 chars, useful |
| 18 | glob (2024/2025 files) | Empty -- glob broken in container |
| 19 | bash ls | Found file listing |
| 20-25 | More MCP + file reads | Gathering remaining data points |
| 26 | bash (numpy HP filter) | FAILED: no numpy installed |
| 27-28 | pip install numpy scipy | Needed --break-system-packages |
| 29-31 | bash (HP filter computation) | Multiple attempts to get computation right |
| 32 | write answer | Correct! |

**Analysis:**
- This is a complex multi-step question requiring 15 years of data + HP filtering.
- The model handled it remarkably well despite needing 33 steps.
- **get_file_structure returned 22,943 chars** -- this is bloated and wastes context window.
- **glob tool doesn't work in Docker container** -- consistently returns "No files found". This is a bug.
- The model had to install numpy/scipy to do the HP filter, which cost 3 steps.
- **Pattern: For time-series data spanning many years, query_table_rows works well when called without restrictive filters.**

**Wasted calls:** Steps 15, 16, 18 (grep with bad patterns, broken glob) = 3 wasted
**Bloated responses:** Step 14 (get_file_structure: 22,943 chars), Step 21 (get_file_structure: 16,748 chars)

---

### uid0136 -- PASS (Geometric mean of 91-day bill discount rates, Sep 1953-1955)

| Metric | Value |
|--------|-------|
| Steps | 13 |
| Agent execution time | ~2.5 min |
| Cost | $0.084 |
| Input tokens | 405,353 (221K cached) |
| Output tokens | 2,185 |
| Answer written | Step 11 |
| Submitted | 1.558 |
| Correct | 1.558 |

**Tool call sequence:**

| Step | Tool | Response Size | Useful? | Notes |
|------|------|---------------|---------|-------|
| 1 | search_tables (91-day bills discount rate) | 5,241 | PARTIAL | Found tables but not perfect match |
| 2 | search_tables (weekly Treasury bills 91 day) | 6,655 | YES | Better results |
| 3 | get_file_structure (1953_10.txt) | 23,448 | BLOATED | Way too much data for just finding a table |
| 4-5 | get_table_profile (2 tables) | 1,503 | YES | Got column info |
| 6 | grep (discount rate + 91) | 14 | NO | Bad regex, no matches |
| 7 | grep (average rate + bills) | 46,405 | BLOATED | 3000+ matches, way too broad |
| 8 | grep (September + 91 in 1954 files) | 8,298 | YES | Found relevant data |
| 9 | grep (September + discount in 1955 files) | 1,819 | YES | Found more data |
| 10 | compute_expression (geometric_mean) | 176 | YES | Correct computation |
| 11 | write answer | 24 | -- | 1.558 |
| 12-13 | Verification bash + msg | -- | -- | Confirmed |

**Analysis:**
- Used 2 search_tables calls (compliant with decision tree).
- **get_file_structure response at 23,448 chars is bloated** -- the model didn't need the full file TOC.
- Grep at step 7 returned 46,405 chars -- **massively bloated**. The pattern was too broad.
- The winning strategy was targeted grep with file + month filters (steps 8-9).
- compute_expression's geometric_mean function worked perfectly.

**Wasted calls:** Step 6 (bad regex) = 1 wasted
**Bloated responses:** Step 3 (23,448 chars), Step 7 (46,405 chars)

---

### uid0167 -- PASS (Statutory debt limitation utilization, March 1950 + March 1955)

| Metric | Value |
|--------|-------|
| Steps | 16 |
| Agent execution time | ~3 min |
| Cost | $0.130 |
| Input tokens | 631,577 (423K cached) |
| Output tokens | 2,816 |
| Answer written | Step 15 |
| Submitted | 95.04 |
| Correct | 95.04 |

**Tool call sequence:**

| Step | Tool | Response Size | Useful? | Notes |
|------|------|---------------|---------|-------|
| 1 | search_tables (debt limitation statutory) | 4,802 | PARTIAL | Found related tables |
| 2 | search_tables (debt limit securities outstanding) | 6,471 | YES | Better matches |
| 3 | extract_values (statutory debt limitation, year=1950, month=3) | 412 | NO | No matching tables found |
| 4 | grep (debt limit/statutory debt) | 23,390 | LARGE | Found many matches across corpus |
| 5-6 | read (targeted bulletin files) | 15,758 | YES | Got 1950 and 1951 data |
| 7 | grep (March 31, 1950) | 42,592 | BLOATED | Too many matches |
| 8 | grep (Status under Limitation) | 11,064 | YES | More targeted, useful |
| 9-11 | read (various bulletin files) | 10,006 | YES | Getting exact figures |
| 12 | grep (March 31, 1955) | 9,474 | YES | Found 1955 data |
| 13 | read (1955_05 bulletin) | 2,947 | YES | Got the actual numbers |
| 14 | compute_expression | 109 | YES | Correct: 95.04 |
| 15 | write answer | 24 | -- | |

**Analysis:**
- extract_values (step 3) completely failed -- returned 0 results for a very specific query. This tool seems unreliable.
- **grep was the hero tool here.** Steps 4, 8, 12 found the right data.
- Step 7 grep returned 42,592 chars -- too broad a pattern ("March 31.*1950").
- The model correctly identified that it needed "Status under Limitation" tables and used grep to find them.
- **Pattern: For fiscal/date-specific queries, grep with the exact date string is more reliable than MCP query_table_rows.**

**Wasted calls:** Step 3 (extract_values failed) = 1 wasted
**Bloated responses:** Step 7 (42,592 chars)

---

### uid0194 -- FAIL (CAGR of bank liabilities to foreigners, June 2003 to June 2013)

| Metric | Value |
|--------|-------|
| Steps | 36 |
| Agent execution time | ~7.5 min |
| Cost | $0.446 |
| Input tokens | 2,183,507 (1,300K cached) |
| Output tokens | 7,639 |
| Answer written | Step 35 |
| Submitted | 7.81 |
| Correct | 7.60 |

**Tool call sequence:**

| Step | Tool | Response Size | Useful? | Notes |
|------|------|---------------|---------|-------|
| 1 | search_tables | 4,974 | YES | Found TABLE IFS-2 (pk=88650) |
| 2 | query_table_rows (pk=88650, month=6, year=2013) | 443 | NO | 0 rows -- filter mismatch |
| 3 | query_table_rows (pk=88650, month=6) | 443 | NO | 0 rows again |
| 4 | query_table_rows (pk=88650, no filters) | 9,092 | YES | Got rows but only 2000-2013 annual |
| 5-7 | search_tables (3 more attempts) | ~15K | WASTED | Same table returned each time |
| 8 | grep (bank.*liabilities.*foreigners) | 71,245 | **VERY BLOATED** | 3143 matches! Massive context waste |
| 9 | extract_values (year=2003, month=6) | 438 | NO | 0 results |
| 10 | get_file_structure (2013_06.txt) | 31,420 | BLOATED | Full TOC |
| 11-16 | read (6 sequential reads of 2013_06) | ~36K | PARTIAL | Browsing through file trying to find June 2003 data |
| 17-18 | grep (June 2003 liability) | 14 | NO | Bad patterns, no matches |
| 19-20 | bash ls | 1,150 | YES | Found relevant files |
| 21 | grep (bank liabilities trillion in 2003_06) | 643 | YES | Found narrative mention |
| 22 | read (2003_06 at offset 2820) | 7,320 | YES | Found CAPITAL MOVEMENTS section |
| 23-24 | get_time_series (2 calls) | 1,441 | NO | No useful time series data returned |
| 25 | query_table_rows (pk=88650, row_label=2013) | 2,367 | YES | Got 2013 monthly data |
| 26 | query_table_rows (pk=88650, year=2003, month=6) | 443 | NO | 0 rows again -- same failed filter |
| 27-30 | read (multiple files) | ~34K | YES | Found CM-I-1 tables |
| 31 | grep (CM-I-1 in 2013_06) | 189 | YES | Found at line 2200 |
| 32-33 | read (2013_06 and 2013_09 CM-I-1 tables) | 13,069 | YES | Got the data |
| 34 | compute_expression ((4764858/2247160)^(1/10)-1) | 97 | YES | 0.0781 = 7.81% |
| 35 | bash echo answer | 0 | -- | Wrote 7.81 |

**WHERE IT WENT WRONG:**

The model extracted:
- June 2003: 2,247,160 (millions)
- June 2013: 4,764,858 (millions)

But the **correct values** should have yielded CAGR = 7.60%, meaning the actual values are different. The model likely pulled the wrong row/column from the CM-I-1 table. The question asks for "total nominal liabilities to foreigners reported by banks" for the specific month of June in each year.

**Root cause analysis:**
1. query_table_rows with month/year filters never worked -- returned 0 rows every time (steps 2, 3, 26). The IFS-2 table likely doesn't have monthly granularity exposed through the MCP tool.
2. The model eventually found the CM-I-1 table by browsing raw text files (steps 29-33).
3. The CM-I-1 table has complex structure with multiple holder types and categories. The model appears to have picked **the wrong column or row** for the June data.
4. **71,245 chars from grep in step 8** wasted massive context window space and likely confused the model's ability to track what data it had vs needed.

**Pattern of failure:** When the structured MCP tools fail, the model falls back to raw file reading, but with very large and complex tables, it misidentifies the correct cell. The sheer volume of data (2.18M input tokens) likely degraded the model's ability to reason precisely about which numbers to use.

**Decision tree compliance:** Used search_tables 4 times (should be max 2). Did not write by iteration 7 -- wrote at step 35.

**Wasted calls:** Steps 2, 3, 5, 6, 7, 8, 9, 17, 18, 23, 24, 26 = **12 wasted (33% of steps)**

---

### uid0199 -- PASS (Net capital movement, gold bloc countries, 1935)

| Metric | Value |
|--------|-------|
| Steps | 47 |
| Agent execution time | ~7.5 min |
| Cost | $0.472 |
| Input tokens | 2,319,192 (1,694K cached) |
| Output tokens | 7,055 |
| Answer written | Step 46 |
| Submitted | 0.479 |
| Correct | 0.479 |

**Tool call sequence highlights:**

| Steps | Activity | Notes |
|-------|----------|-------|
| 1-3 | search_tables (3 calls) | Found capital movement tables but no country breakdown |
| 4 | grep (France capital movement) | 0 matches |
| 5-8 | read + bash | Exploring corpus structure, discovering earliest files are 1939 |
| 9 | query_table_rows (pk=8112, year=1935) | 2,551 chars -- got aggregate data |
| 10 | grep (France/Switzerland/Netherlands/Italy capital) | 1,063 chars -- found mentions |
| 11 | grep (gold bloc) | 0 matches -- term not in corpus |
| 12-13 | search_tables + query_table_rows | More attempts |
| 14-32 | Extensive grep + read exploration | 19 steps of searching through bulletins |
| 33 | skill (treasury_reasoning) | 1,221 chars -- invoked a skill |
| 34-35 | get_table_profile + grep with pipe-delimited pattern | Found France 1935 data! |
| 36-44 | More reads of 1940s/1946 bulletins | Finding country-level data |
| 43 | grep (Net Capital Movement Countries 194x) | 14,530 chars -- found the key table |
| 44 | read (1941_01 at offset 1710) | 13,311 chars -- got country-by-country data |
| 45 | compute_expression | Correct |
| 46 | write answer | 0.479 |

**Analysis:**
- This was the hardest question -- it required domain knowledge (gold bloc countries) + finding country-level capital movement data from 1935 in bulletins that start from 1939.
- **47 steps** -- the highest of any question. The model was remarkably persistent.
- The model correctly identified that it needed to look in early 1940s bulletins for historical 1935 data.
- **grep with pipe-delimited table patterns (step 35)** was the breakthrough that found France's 1935 data.
- Many grep calls returned empty because the data format is pipe-delimited markdown tables, not natural text.

**Wasted calls:** ~15 steps of failed grep patterns = 32% waste
**Key learning:** The model needs to know that corpus data is in markdown pipe tables, so grep patterns should match `| France |` not `France.*capital movement`.

---

### uid0030 -- FAIL (Local maxima on line plots, Sep 1990 bulletin page 5)

| Metric | Value |
|--------|-------|
| Steps | 20 |
| Agent execution time | ~? |
| Cost | $0.133 |
| Input tokens | 612,568 |
| Output tokens | 8,630 |
| Answer written | Step 18 |
| Submitted | 4 |
| Correct | 18 |

**Tool call sequence:**

| Step | Tool | Response Size | Useful? | Notes |
|------|------|---------------|---------|-------|
| 1-2 | glob (1990_09 file) | 14 | NO | Glob broken |
| 3-5 | bash ls | 2,440 | YES | Found file listing |
| 6 | read (full 1990_09 file) | 54,897 | **VERY BLOATED** | Read entire file! |
| 7 | read (offset 405, limit 70) | 1,332 | PARTIAL | |
| 8 | grep (Exhibit/chart/plot/line) | 7,335 | YES | Found references |
| 9 | grep (local maximum/peak) | 503 | YES | Found mentions |
| 10 | skill (treasury_reasoning) | 1,221 | -- | Reasoning skill |
| 11 | grep (saving rate) | 3,198 | YES | Found mentions |
| 12 | grep (WWII/1940s) | 1,382 | PARTIAL | |
| 13 | read (offset 460, limit 20) | 545 | YES | |
| 14-15 | search_tables (saving rate) | 10,198 | NOT USEFUL | Wrong approach |
| 16 | grep (Exhibit 1/2/3) | 124 | YES | Found exhibit refs |
| 17 | bash (python -- fabricated reasoning) | 0 | **FABRICATED** | Model guessed "4" |
| 18 | write answer | 24 | -- | Wrote 4 |

**WHERE IT WENT WRONG:**

This question asks about **visual chart features (local maxima on line plots)** which cannot be answered from parsed text files. The corpus contains markdown text, not images. The model:
1. Correctly found the file and read it.
2. Could not find the actual chart data (because charts are not in the text corpus).
3. **Fabricated an answer** in step 17 -- ran a Python script with hardcoded "reasoning" about what the charts might show.
4. Answered 4 when the correct answer is 18.

**Root cause:** This is an **impossible question** for text-based corpus access. The question requires visual inspection of chart images. Unless the chart data points are tabulated in the text, there is no way to count local maxima from markdown text.

**Decision tree compliance:** N/A -- the question type is fundamentally unsolvable with available tools.

---

## Overall Pattern Summary

### Tool Effectiveness

| Tool | Times Called | Useful | Bloated | Empty/Failed | Effectiveness |
|------|------------|--------|---------|--------------|---------------|
| search_tables | ~18 | 12 | 0 | 6 (duplicate results) | 67% useful |
| query_table_rows | ~20 | 8 | 0 | 12 (0 rows) | 40% useful |
| extract_values | 3 | 1 | 0 | 2 | 33% useful |
| get_time_series | ~8 | 3 | 0 | 5 | 38% useful |
| get_file_structure | 4 | 1 | 3 | 0 | 25% useful (75% bloated) |
| get_table_profile | 3 | 2 | 0 | 1 | 67% useful |
| compute_expression | 6 | 6 | 0 | 0 | **100% useful** |
| grep | ~35 | 18 | 5 | 12 | 51% useful |
| read | ~30 | 25 | 1 | 4 | 83% useful |
| bash | ~15 | 12 | 0 | 3 | 80% useful |
| write | 7 | 7 | 0 | 0 | 100% useful |

### Bloated Response Analysis

| Tool / Instance | Size | Problem |
|----------------|------|---------|
| get_file_structure | 16-31K chars | Returns full table-of-contents for entire bulletin file. Model rarely needs all of it. |
| grep (broad patterns) | 42-71K chars | Patterns like `March 31.*1950` or `bank.*liabilities.*foreigners` match thousands of lines |
| query_table_rows (no filters) | 9-16K chars | Returns all rows when filters fail, which is actually useful but large |
| read (full file) | 55K chars | uid0030 read entire file -- should read targeted sections |

### Critical Findings

#### 1. query_table_rows filter failures (12 of 20 calls = 60% failure rate)

The most common failure pattern: the model calls `query_table_rows` with `year`, `month`, or `column_label` filters that don't match the actual row/column labels in the parsed table. The table might have rows labeled "2013 - Jan. p" but the model filters for `year=2013, month=1` and gets 0 rows.

**Fix needed:** Either make the filter matching more flexible (fuzzy year/month matching) or change the tool's API to accept year ranges and return the best match.

#### 2. get_file_structure is too verbose (avg 23K chars per call)

Every call returns the complete table of contents with all table titles, PKs, and column samples. The model uses this once or twice per question but each call consumes ~6000 tokens.

**Fix needed:** Add a `brief=true` option that returns just table titles and PKs without column samples.

#### 3. Repeated search_tables calls return identical results

The model calls search_tables 3-4 times with slightly different query terms and gets the same candidates back. The search engine's term matching is not sensitive enough to distinguish between query variations.

**Fix needed:** The prompt should be stronger about "do NOT re-search with synonyms -- if search_tables finds candidates, use them."

#### 4. glob tool is broken in Docker containers

Every glob call returned "No files found" even for files that clearly exist. This wastes a step each time.

**Fix needed:** Either fix the glob tool's path handling in Docker or remove it from the available tools.

#### 5. grep is the most reliable data-finding tool

Despite only 51% success rate (due to bad regex patterns), grep was the tool that saved most questions. The winning pattern is:
1. `grep` to find the table heading in the right file + line number
2. `read` at that offset to get the actual data

#### 6. Model fabrication risk is low but exists

Only uid0030 showed clear fabrication (hardcoded Python guess). All other questions used data from actual tool responses. The key risk factor is **impossible questions** where no tool can provide the answer.

### Pass vs Fail Pattern Comparison

| Factor | Passes (6) | Fails (2) |
|--------|-----------|-----------|
| Avg steps | 25 | 28 |
| Avg cost | $0.198 | $0.290 |
| search_tables found right table on first call | 5/6 | 1/2 |
| Used grep+read as fallback | 5/6 | 1/2 |
| query_table_rows with filters worked | 2/6 | 0/2 |
| Answer written by step 15 | 2/6 | 0/2 |
| Total input tokens (avg) | 963K | 1,398K |
| Data fabrication | 0/6 | 1/2 |

### Decision Tree Compliance

| Rule | Compliance | Notes |
|------|-----------|-------|
| Max 2 search_tables calls | 4/8 compliant | uid0041 OK, uid0111 used 5, uid0194 used 4, uid0199 used 5+ |
| Write by iteration 7 | 1/8 compliant | Only uid0048 wrote early. Most wrote at steps 15-46. |
| Use grep as fallback | 7/8 used grep | All but uid0048 (which didn't need it) |
| compute_expression for math | 6/8 used it | Always worked correctly when used |

### Recommendations

1. **Fix query_table_rows filtering** -- Make year/month filters fuzzy-match against row labels. This single fix would eliminate ~10 wasted steps per question.

2. **Reduce get_file_structure verbosity** -- Trim to just table titles and PKs. Save ~20K chars per call.

3. **Cap grep output** -- Limit grep responses to first 20 matches (~5K chars). The model cannot usefully process 71K chars of grep output.

4. **Kill glob tool** -- It does not work in the Docker environment. Remove it to save the model from wasting a step.

5. **Strengthen prompt guardrails:**
   - "After 1 search_tables, immediately try grep+read if MCP tools return empty data"
   - "Never call search_tables more than twice with similar keywords"
   - "Data is in pipe-delimited markdown tables -- use grep patterns like `| France |` not `France.*capital`"

6. **Add early-write pressure** -- The prompt says write by iteration 7 but this was almost never followed. Consider: "If you have extracted any plausible values by step 10, write your best answer immediately, then continue refining."

7. **Flag impossible questions** -- Questions about visual/chart features cannot be answered from text. The model should detect this pattern and write a best-guess answer quickly rather than burning 20 steps.

8. **Token budget awareness** -- uid0194 consumed 2.18M input tokens ($0.45) and still got the wrong answer. The model should have an internal budget limit and write its best answer when approaching it.
