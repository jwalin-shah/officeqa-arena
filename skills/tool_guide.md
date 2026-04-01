# Tool Quick Reference

## CRITICAL: Terminal Restrictions
**TERMINAL IS RESTRICTED.** Only use terminal for writing `/app/answer.txt`.
- **NEVER use grep, sed, cat, head, tail, or any other text tools on /app/corpus files**
- **ALL data retrieval MUST go through MCP tools ONLY**
- Use search_canonical first, then search_ledger, then extract_values — in that order
- If you need to inspect files, use the MCP tools provided (search_tables, get_table_profile, etc.)

## Golden Rule
If any tool returns a result where `year` is NULL, check the `source` or `source_file` field (e.g. "treasury_bulletin_1945_06") to verify the era.

## GOLD PATH — Start Here
- **search_canonical(query, year, years, table_family, limit)** — Hierarchical canonical fact store (935K facts). Use this FIRST.
  - Single value: `search_canonical(query="customs duties", year=1940)`
  - Multiple years: `search_canonical(query="customs duties", years=[1940, 1941])`
  - Disambiguate by family: `search_canonical(query="public debt", table_family="public_debt")`
  - Families: public_debt, revenue_receipts, federal_securities, international_capital, monetary, cash_operations, budget_expenditures.

## FALLBACK — If search_canonical errors or returns empty
- **search_ledger(metric, year, period_basis, years)** — Flat Master Ledger. Pre-computed CY/FY totals.
  - Single value: `search_ledger(metric="customs", year=1940, period_basis="fiscal")`
  - Two values: `search_ledger(metric="customs", years=[1940, 1941])`
  - Monthly: `search_ledger(metric="customs", year=1940, period_basis="monthly")`
  - The result includes `table_pk` — use with get_table_profile to verify units.

## SILVER PATH — Full Table Context
- **extract_values(query, metric, year, month)** — Search + fetch with full table rows. Use when gold/fallback return empty.
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

## Emergency Only (MCP Tool, Not Terminal)
- **grep_corpus(pattern, file_id)** — Raw text search via MCP. Use `"| keyword |"` pattern. Max 3 calls.
  - **DO NOT attempt grep/sed/cat on /app/corpus from terminal** — use this MCP tool instead
