# Tool Quick Reference

## Primary Path

- **resolve_numeric_evidence(question, metric, year, period_basis)** — One call handles most questions. Searches across bulletin vintages, returns ranked candidates with recommended_value and confidence level. Use this first.

- **search_data(query, year)** — Merged canonical + ledger search. Use when resolve_numeric_evidence returns no_data.

## Table Drill-Down (Fallback)

- **search_tables(query)** — Find tables by keyword. Keep queries short.
- **get_table_profile(table_pk)** — See columns, units, year coverage. Call before computing to verify units.
- **query_table_rows(table_pk, row_label, column_label, year)** — Get specific cells. Use exact labels from profile.

## Series Tools

- **get_period_series(metric, year)** — Returns all 12 monthly values + sum for a given year.
- **get_time_series(metric, year_start, year_end, period_basis)** — Contiguous year ranges.
- **get_multi_year_series(metric, years, period_basis)** — Sparse or non-contiguous years.

## Computation

- **compute_expression(expression, variables)** — ALL arithmetic. Supports: +, -, *, /, **, sum(), mean(), stdev(), cagr(), linreg(), geometric_mean(), round(), sqrt(), cv(), correlation(), theil_index(), boxcox(), percentile(), mad(), interpolate().

## Reference Data

- **get_cpi_index(year, month)** — CPI-U index, monthly 1930–2026. Base: 1982-84 = 100.
  - CPI adjustment: real_value = nominal × (target_CPI / source_CPI)
- **get_exchange_rate(pair, year, month)** — FX rates. Pairs: USD/JPY, USD/GBP, USD/INR, USD/DEM, USD/CAD.
- **submit_answer(answer, question)** — Automatically verifies. If it returns warnings, fix and re-submit.

## Worked Example — Unit Scaling Trap (most common failure)

Q: "What is the mean of Total Assets from ESF tables for Sept 1991, June 1992, Sept 1992 in nominal dollars?"

Wrong: Found values [30,766,025 | 34,368,939 | 33,047,531], computed mean = 32,727,498.
Why wrong: Table header says "In thousands of dollars". These are thousands, not nominal dollars.
Right: Multiply each by 1,000 → [30,766,025,000 | 34,368,939,000 | 33,047,531,000], mean = 32,727,498,333.
Key: Always call get_table_profile(table_pk=N) to check the units_line before computing.
