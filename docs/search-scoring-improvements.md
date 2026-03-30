# Search Scoring Investigation: `search_tables` in `server/db.py`

**Date:** 2026-03-30
**Scope:** Read-only analysis of scoring logic and year-range filtering

---

## 1. How Scoring Works

The `search_tables` function (line 650) uses a two-phase approach:

### Phase 1: Candidate retrieval via `table_term_index` (lines 719-796)

If `table_term_index` exists and query_match_terms are non-empty, the function runs a SQL query that:
- Joins `table_term_index` (tti) with `table_index` (ti) on `table_pk`
- Filters by `tti.term_norm IN (query_match_terms)`
- Computes per-table scores across 6 term types: `entity_phrase`, `series_core`, `header_phrase`, `family`, `row_label_phrase`/`alias_phrase`, `row_label_token`
- Computes `year_overlap_score` (how many query years fall within `ti.min_year..ti.max_year`)
- Computes `source_year_score` (does the source filename contain a query year)
- Results are ranked by `(year_overlap, source_year, entity+col, series+row, phrase+row_token, token+col_token)` tuple
- Top `max_rows` (50-2000) PKs become the candidate pool

**Problem:** The ORDER BY in the SQL uses `year_overlap_score DESC` as primary sort, but the LIMIT caps results before Python scoring happens. If many tables match the terms, tables from the right era rank first -- but if few match, wrong-era tables fill the pool.

### Phase 2: Python-side scoring (lines 854-977)

Each candidate gets a score from 8 additive signals:

| Signal | Points | Description |
|--------|--------|-------------|
| Title match | 3 pts per term | Query terms found in `table_title` |
| Entity match | 10 pts per entity | Known entity phrases (line 23-52) found in query AND table |
| Column match | 8 pts per term | Query terms matching column labels |
| Year coverage | 4 pts per year | Each query year within table's `[min_year, max_year]` |
| Monthly bonus | 6 + 12/yr | If query needs monthly data and table has it |
| Y+1 bulletin | 15 pts | Jan-Mar bulletin from year after query year |
| Term index total | raw sum | All term_index weights summed directly |
| Family alignment | 5 pts | Table family matches query family |

**Hard reject** (line 894): If `query_years_set` is non-empty and table has `min_year`/`max_year`, reject if NO query year falls in `[min_year, max_year]`.

---

## 2. Why Year-Range Filters Fail

### Root cause: `year_range` is NOT used for SQL-level filtering

The `year_range` parameter is used in exactly two ways:
1. **Populating `query_years_set`** (line 698-700): years from the range are added to the set
2. **Temporal completeness filter** (line 703-708): only activated when `wants_complete_year_rollup` is true (calendar year / annual queries)

For typical queries like "Rural Electrification Administration 1961-1970", the year_range feeds into `query_years_set`, which is used for:
- The hard reject check (line 894): skip if no overlap with `[min_year, max_year]`
- Year coverage scoring: +4 pts per overlapping year
- Year overlap in the term_index SQL: used for ORDER BY but not WHERE

### Why 1939 tables appear for 1960s queries

A table with `min_year=1935, max_year=1970` would PASS the hard reject because some query years (1961-1970) overlap. Even a table covering 1930-1945 could pass if it reports `max_year=1970` due to how min/max year are computed from the source bulletin date rather than actual data coverage.

**Critical gap:** There is no penalty for year-range breadth mismatch. A table covering 1930-1970 gets the same year_coverage score as one covering 1960-1972 for a 1961-1970 query -- both have 10 years of overlap. But the narrower table is far more relevant.

### The `year_range` parameter is essentially decorative

Since it only feeds `query_years_set` and the same years are already extracted from the query text (line 697), explicitly passing `year_range=[1961, 1970]` adds no filtering power beyond what `_query_search_terms` already provides.

---

## 3. Is `table_term_index` Being Used?

Yes, it IS used (line 719). The 8.7M-row `table_term_index` is the primary candidate retrieval path when available. The function:
1. Matches query terms against `tti.term_norm`
2. Aggregates weighted scores by term type
3. Uses the matched PKs to filter the `table_index` query

**However, the term matching is exact.** For "Rural Electrification Administration", `_query_match_terms` would produce phrases like "rural electrification", "electrification administration", "rural electrification administration" plus individual tokens "rural", "electrification", "administration". These must exactly match `term_norm` values in the index. If the index stores "r.e.a." or "rea" as the term, the phrase match fails.

---

## 4. Are Column Names Being Matched?

**Partially.** Column matching happens in two places:

1. **Phase 2 scoring** (line 917-921): Column labels are fetched from `table_first_table_cells` for all candidate PKs, and query terms are checked against them. This awards 8 pts per matching term -- a strong signal.

2. **Comment at line 779:** "Cell-level supplement removed for speed. The term_index already includes column names as alias_phrases." So column names should also be indexed in `table_term_index` as `alias_phrase` terms.

**Problem for "91-day weekly bills discount rate":** The metric "discount rate" is likely a column header. But `_query_search_terms` tokenizes the query into individual terms: "91", "day", "weekly", "bills", "discount", "rate". "day" is dropped (< 3 chars). The column match checks each remaining token individually against column labels. Since columns likely contain "discount rate" as a phrase, matching individual tokens like "discount" or "rate" dilutes the signal -- many unrelated tables also have "rate" columns.

---

## 5. No `facts` Table in `db.py`

There is no reference to a "facts" table anywhere in `server/db.py` or any other file in `server/`. The trace mentions `lookup_numeric_answer` and `find_candidate_evidence` tools, but these are not defined in the current codebase -- they may have been removed or exist in a different version. If a 5.8M-row facts table exists in the SQLite database, it is completely unused by the current search code.

---

## 6. Specific Code Improvements

### Improvement A: Add year-range precision penalty (high impact)

Currently, year_coverage gives +4 pts per overlapping year with no penalty for tables that span far beyond the query range. Add a **precision ratio** penalty:

```python
# After line 927 (year_hits calculation)
if query_years_set and mn is not None and mx is not None and year_hits > 0:
    table_span = mx - mn + 1
    query_span = len(query_years_set)
    # Penalize tables whose span is much wider than needed
    # A table spanning 40 years for a 10-year query gets 0.25 precision
    precision = min(query_span, year_hits) / max(table_span, 1)
    score += 10.0 * precision  # up to 10 bonus for tight fit
```

This would cause a 1960-1972 table to score much higher than a 1930-1970 table for a 1961-1970 query.

### Improvement B: Hard filter by year_range in SQL (high impact)

Add actual WHERE clause filtering when `year_range` is provided:

```python
# After line 700, add:
if query_years_set and not normalized_source_file:
    yr_min = min(query_years_set)
    yr_max = max(query_years_set)
    # Require some overlap: table's max_year >= query min, table's min_year <= query max
    where.append("(max_year >= ? AND min_year <= ?)")
    params.extend([yr_min, yr_max])
```

Also apply the same filter in the term_index SQL (add to `term_where` at line 733):
```python
if query_years_set:
    yr_min = min(query_years_set)
    yr_max = max(query_years_set)
    term_where.append("ti.max_year >= ? AND ti.min_year <= ?")
    term_params.extend([yr_min, yr_max])
```

### Improvement C: Boost phrase matches over token matches (medium impact)

The current `_query_match_terms` returns both phrases and individual tokens, but the term_index SQL treats them equally in the WHERE clause. Multi-word phrases like "rural electrification" should be weighted much higher than single tokens like "rural".

In the Python scoring (line 951), the term_total sums all weights equally. Instead:

```python
# Replace line 951-954 with:
entity_w = float(term_scores.get("entity_score", 0))
series_w = float(term_scores.get("series_score", 0))
header_w = float(term_scores.get("header_score", 0))
phrase_w = float(term_scores.get("phrase_score", 0))
token_w = float(term_scores.get("token_score", 0))
# Boost phrase-level matches 2x over token matches
term_total = entity_w * 2.0 + series_w * 1.5 + header_w * 1.5 + phrase_w * 1.5 + token_w * 0.5
score += term_total
```

### Improvement D: Add source_file year proximity bonus (medium impact)

Tables from bulletins published close to the query years are more likely relevant than tables from distant bulletins. The Y+1 bulletin boost (line 942-948) only handles one specific case. Generalize:

```python
# Replace the Y+1 bulletin boost (lines 942-948) with:
if query_years_set and issue_year is not None:
    query_center = sum(query_years_set) / len(query_years_set)
    distance = abs(issue_year - query_center)
    if distance <= 2:
        score += 15.0
        match_signals.append("source_near_query")
    elif distance <= 5:
        score += 8.0
        match_signals.append("source_close_query")
    # Penalize distant bulletins
    elif distance > 15:
        score -= 5.0
        match_signals.append("source_distant")
```

### Improvement E: Investigate and expose `facts` table (high potential impact)

If the SQLite database contains a `facts` table with 5.8M pre-extracted key-value pairs, adding a `search_facts` function could bypass the table search entirely for direct value lookups. This would help queries like "91-day weekly bills discount rate September 1953" where the answer is a specific numeric value. Steps:

1. Run `SELECT name, sql FROM sqlite_master WHERE type='table'` to inventory all tables
2. If `facts` exists, examine its schema and add a search function
3. This could eliminate the need for multi-step table-find-then-extract workflows

### Improvement F: Tighten the hard reject (low effort, high impact)

The current hard reject (line 894) checks if ANY query year is within `[min_year, max_year]`. For multi-year queries, require a minimum overlap fraction:

```python
# Replace lines 894-896 with:
if query_years_set and mn is not None and mx is not None:
    overlap = sum(1 for yr in query_years_set if mn <= yr <= mx)
    # Require at least 50% of query years to overlap
    if overlap < max(1, len(query_years_set) * 0.5):
        continue
```

---

## Summary of Root Causes by Failing Query

| Query | Root Cause | Best Fix |
|-------|-----------|----------|
| Rural Electrification Administration 1961-1970 | Term index matches REA in tables spanning 1930-1970; no year precision penalty; 1939 bulletin tables rank high due to token matches | Improvements A + B + D |
| 91-day weekly bills discount rate Sep 1953-1955 | "rate" and "bills" tokens match many irrelevant tables; phrase "discount rate" not weighted higher; 1939 tables returned | Improvements B + C |
| Alcohol Tax Bureau Dec 1938 | Entity "Alcohol Tax Bureau" not in `_KNOWN_ENTITY_PHRASES` (actual name is "Alcohol Tax Unit"); no fuzzy matching | Add "alcohol tax unit" to `_KNOWN_ENTITY_PHRASES` at line 23 |
| Year range filtering general | `year_range` parameter only populates `query_years_set` -- no SQL-level WHERE filtering, no precision scoring | Improvements A + B + F |

---

## Priority Order

1. **B** (SQL year filtering) -- eliminates wrong-era candidates at source, biggest single improvement
2. **A** (year precision penalty) -- among correctly-era tables, prefers tight-fitting ones
3. **D** (source file proximity) -- penalizes 1939 bulletins for 1960s queries
4. **C** (phrase boost) -- helps "discount rate" and "rural electrification" rank higher
5. **F** (tighten hard reject) -- safety net for edge cases
6. **E** (facts table) -- potentially transformative but needs DB schema investigation first
