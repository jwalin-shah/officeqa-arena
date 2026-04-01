# Tool Quick Reference

## Golden Rule
If any tool returns a result where `year` is NULL, check the `source` or `source_file` field (e.g. "treasury_bulletin_1945_06") to verify the era.

## GOLD PATH — Start Here
- **search_ledger(metric, year, period_basis, years)** — Master Ledger lookup. Sub-millisecond. Pre-computed CY/FY totals. Use this FIRST for every question.
  - Single value: `search_ledger(metric="customs", year=1940, period_basis="fiscal")`
  - Two values for comparison: `search_ledger(metric="customs", years=[1940, 1941])`
  - All periods: `search_ledger(metric="customs", year=1940)` (returns CY, FY, and annual)
  - Monthly breakdown: `search_ledger(metric="customs", year=1940, period_basis="monthly")`
  - The result includes `table_pk` — use it with get_table_profile to verify units and footnotes.

## SILVER PATH — Full Table Context
- **extract_values(query, metric, year, month)** — Search + fetch with full table rows. Use when ledger returns empty or you need row structure/footnotes.
- **get_time_series(metric, year_start, year_end)** — For contiguous year ranges. More efficient than multiple calls.
- **get_multi_year_series(metric, years)** — For sparse/non-contiguous years.

## BRONZE PATH — If Silver Fails
- **search_tables(query)** — Find tables by keyword. Max 2 calls. Keep queries short.
- **get_table_profile(table_pk)** — See columns, units, year coverage. ALWAYS call to verify units from ledger results.
- **query_table_rows(table_pk, row_label, column_label, year)** — Get specific cells. Use exact labels from profile.

## Computation
- **compute_expression(expression, variables)** — ALL arithmetic. Supports: +, -, *, /, **, sum(), mean(), stdev(), cagr(), linreg(), geometric_mean(), round(), sqrt(), cv(), correlation(), theil_index(), boxcox().

## Reference Data
- **get_cpi_index(year, month)** — CPI-U index. Monthly 1930-2026.
- **get_exchange_rate(pair, year, month)** — Historical FX rates.
- **get_fiscal_year_bounds(fiscal_year)** — Start/end dates for a federal fiscal year.
- **resolve_agency_alias(query)** — Map old agency names to search terms.

## Verification
- **verify_answer(question, candidate_answer)** — Call once before writing answer.

## Emergency Only
- **grep_corpus(pattern, file_id)** — Raw text search. Use `"| keyword |"` pattern. Max 3 calls.
