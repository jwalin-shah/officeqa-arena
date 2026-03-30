# Treasury Domain Knowledge

## Fiscal Year Convention

The federal fiscal year ran July 1 to June 30 through the 1970s (shifted to Oct 1 - Sep 30 starting FY1977).

A row labeled "1940" in a "Fiscal year or month" table means FY1940 (Jul 1939 - Jun 1940), NOT calendar year 1940. For calendar-year data, sum the 12 monthly rows (Jan-Dec). Always check the row-label column header to know which convention applies.

## Bulletin Temporal Patterns

- Annual totals for year Y appear in bulletins from early Y+1 (January through March).
- Prefer later summary bulletins over earlier monthly bulletins when the question asks for a completed annual figure.
- Filenames follow the pattern `treasury_bulletin_YYYY_MM.txt` — parse the date to reason about which bulletin is most likely to contain finalized data.
- Do NOT assume the first year-matching bulletin is correct. Search both Y and Y+1 bulletins.

## Defense Decomposition (1940s)

- 1940-1948 bulletins split "National Defense" into "War Department" and "Navy Department" with no combined total row.
- If no single defense total row exists, sum War Dept + Navy Dept using `compute_expression`.
- Post-1950 bulletins have an explicit "National defense and related activities" row.
- A column labeled "Total" in a defense-specific table IS the national defense total — use it directly.

## Unit Reconciliation

Before binding any number to a variable:

1. Locate the exact "Units", "Scale", or equivalent descriptor in the table header or `get_table_profile` output.
2. Apply the correct multiplier:
   - "In thousands" = 10^3
   - "In millions" = 10^6
   - "In billions" = 10^9
3. Convert ALL intermediate values to the same base unit before computation.
4. If unit descriptors conflict across nearby rows or tables, stop and re-read the table header.

## Numerical Verification

- Use `compute_expression` for ALL arithmetic. Never do mental math.
- If the table has a subtotal or total row, compute the component sum and compare it to the reported total.
- If your computed sum does not match the reported total, re-read the table — possible OCR errors.
- Keep intermediate precision exact until the final formatting step.

## Evidence Extraction Discipline

- Use EXACT row and column labels as they appear in the table. No paraphrasing.
- If the table says "Admin. Expenses", do NOT write "Administrative Expenses".
- Preserve the raw numeric format from the table (e.g., "1,234.5" not "1234.5").

## Search Strategy

When initial search fails to find the right data:

1. Widen the year range: search Y-1 through Y+2.
2. Try alternate metric names (e.g., "receipts" vs "revenue", "expenditures" vs "outlays").
3. Use `get_file_structure` to browse a bulletin you know is close to the right time period.
4. Check `get_table_profile` to verify column names and year coverage before querying rows.

## Reading Grounding Metadata from Tool Responses

Every tool response carries metadata that tells you whether you have the right data. Use it.

### search_tables response fields
- **file_id**: Which bulletin issue this table comes from. Parse the year/month to check temporal alignment.
- **score**: Relevance ranking. Higher is better, but always verify by inspecting the table — a high score does not guarantee correctness.
- **year_range**: `[min_year, max_year]` of data in the table. If your target year falls outside this range, skip this candidate.
- **columns_sample**: First 5 column labels. Check whether your target entity or metric appears here before fetching rows.

### get_table_profile response fields
- **period_basis**: "fiscal" or "calendar" — tells you whether row years mean fiscal years or calendar years.
- **columns**: Full list of column labels. Use these exact strings as `column_label` filters in `query_table_rows`.
- **years**: All years with data in this table. Confirm your target year is present.
- **frequency**: "annual", "monthly", "quarterly" — tells you the granularity of the data.

### query_table_rows response fields
- **row_label**: The exact label from the source table. Verify it matches the entity you need.
- **column_label**: The exact column header. Verify it matches the metric you need.
- **year** / **month**: The time period for this cell. Cross-check against your extraction plan.
- **value**: The raw cell value from the table. Check for footnote markers or missing-data indicators before using.
- **was_truncated**: If true, your query hit the row limit. Add more filters (row_label, column_label, year) to narrow results.

## Common Mistakes (from v5 evaluation)

### 1. Grabbing aggregate rows instead of specific categories
When the question asks about a specific category (e.g., "customs duties"), do NOT use a "Total receipts" row. Filter by the exact `row_label` for the specific category. Similarly, for monthly data, specify both the entity AND the month — a row labeled "Total" for the right month is not the same as the specific category for that month.

### 2. Wrong bulletin / wrong year
A bulletin published in March 1941 contains FY1940 annual data. If you search for year=1940 and get a result from a 1939 bulletin, that bulletin likely has FY1939 data, not FY1940. Always cross-check the `file_id` date against the data year.

### 3. Fiscal vs calendar year mismatch
If the question says "fiscal year 1940" and the table's `period_basis` is "calendar", you have the wrong table (or you need to sum the right monthly rows). Use `get_table_profile` to check `period_basis` before trusting a year value.

### 4. Unit scale errors
The most common arithmetic error: taking a value from a table denominated "in thousands" and reporting it as if it were "in millions". Always check units. When combining values from different tables, convert everything to the same scale first using `compute_expression`.

### 5. Assuming the first search result is correct
`search_tables` ranks by relevance, but relevance scoring is imperfect. A table about "Total receipts by source" might score higher than "Internal revenue by category" even when you need the latter. Read `columns_sample` and `year_range` for every candidate before choosing.

### 6. Not using row_label filters
`query_table_rows` returns up to 20 rows by default. If you don't filter by `row_label`, you may get header rows, subtotals, or unrelated categories. Always pass a `row_label` filter when you know what entity you need.
