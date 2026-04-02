# Computation Patterns for compute_expression

These are the common statistical operations asked in Treasury bulletin questions.

Single-series statistics:
  sum([v1, v2, ...])
  mean([v1, v2, ...])
  median([v1, v2, ...])
  stdev([v1, v2, ...])
  geometric_mean([v1, v2, ...])
  cv([v1, v2, ...])                    — coefficient of variation
  theil_index([v1, v2, ...])           — Theil index of dispersion
  percentile([v1, v2, ...], 25)        — Q1 (Tukey exclusive median)
  mad([v1, v2, ...])                   — median absolute deviation

Two-series:
  correlation([x1,x2,...], [y1,y2,...])
  linreg([x1,x2,...], [y1,y2,...])     — returns [slope, intercept]

Growth and change:
  cagr(start_value, end_value, n_years)
  (end - start) / abs(start) * 100     — percent change

Transforms:
  boxcox([v1, v2, ...], lambda)
  interpolate([x1,x2,...], [y1,y2,...], target_x)

H-spread = percentile(values, 75) - percentile(values, 25)
Winsorized range (10%): sort values, trim top/bottom 10%, then max - min

## Unit Conversion

Tables declare units in their header. Always check get_table_profile before using any value.

| Table says              | Multiply raw value by | Example: raw "1,234" means |
|-------------------------|----------------------|---------------------------|
| "In thousands"          | × 1,000              | $1,234,000                |
| "In millions"           | × 1,000,000          | $1,234,000,000            |
| "In billions"           | × 1,000,000,000      | $1,234,000,000,000        |
| "In thousands of dollars" | × 1,000            | $1,234,000                |
| No unit stated / "Dollars" | × 1 (use as-is)  | $1,234                    |

If query_table_rows or extract_values returns value_scaled, that value is already in actual dollars. Do not multiply again.

Mixing units across tables: convert both to the same base before computing.
Example: A_actual = A_raw × 1,000,000; B_actual = B_raw × 1,000; then compute_expression(expression="a - b", ...)

Answer unit: if question asks "in millions", divide actual-dollar result by 1,000,000. If unspecified, match the table's unit scale.
