# Tool Usage Guide

## extract_values (BEST FIRST TOOL)
**When**: Start every question here. Combines search + fetch in one call.
**Tips**: Pass query + metric + year. Returns compact rows from best-matching tables. If results look wrong, refine with search_tables + query_table_rows.

## search_tables
**When**: extract_values didn't find the right table, or you need to explore.
**Tips**: Keep queries short: "defense expenditures" not full sentences. Try synonyms if no results. Max 2 calls.

## query_table_rows
**When**: After search_tables gives you a table. Need specific cell values.
**Tips**: Use EXACT labels from get_table_profile. If 0 rows returned, follow suggest_relaxation hints in the response. Returns value_scaled when units need conversion.

## get_table_profile
**When**: ALWAYS call before query_table_rows. Shows units, columns, row_label_samples, year coverage.
**Tips**: Check units field — if it says "in thousands", query_table_rows will return value_scaled. Check row_label_samples for exact strings to use.

## get_time_series
**When**: Question spans a contiguous year range (e.g., 1961-1970). More efficient than get_multi_year_series.
**Tips**: Pass metric + year_start + year_end. Returns {period: value} pairs with coverage info.

## get_multi_year_series
**When**: Question spans non-contiguous years. Gets a metric across all years in one call.

## compute_expression
**When**: ANY arithmetic. Never do math in your head.
**Tips**: Define variables: `{"a": 100, "b": 200}` with `"a + b"`. Supports sum(), geometric_mean(), round(), abs(), min(), max(), sqrt(), linreg(), cagr(), theil_index(), stdev(), cv().

## verify_answer (CALL BEFORE WRITING)
**When**: ALWAYS call before echo "VALUE" > /app/answer.txt.
**Tips**: Pass question, candidate_answer, evidence_table_pks, evidence_values. Checks unit scale and value provenance. Fix any warnings before writing.

## get_file_structure
**When**: Browse all tables in a specific bulletin. Use file_id like "1941_01".

## grep_corpus (MCP tool — ONLY grep allowed)
**When**: MCP tools return nothing after 2 attempts.
**How**: Call `grep_corpus(pattern="| keyword |", file_id="YYYY_MM")`. Output is always capped.
- NEVER use the built-in grep tool or bash grep. ALWAYS use grep_corpus.
- Data is in pipe-delimited markdown tables: `| row_label | col1 | col2 |`
- Use `| keyword |` patterns, NOT `keyword.*other` (too broad)
- For year Y data, check Y+1 January bulletin first.

## web_lookup
**When**: Need external data not in bundled reference files (rare exchange rates, GDP data, etc.)
**Tips**: Fetch any URL and get its text content (max 10KB). Useful APIs:
  - Current FX rates: `https://api.exchangerate-api.com/v4/latest/USD` (returns JSON with all rates)
  - Or use `bash: python3 -c "import urllib.request, json; ..."` for more complex fetching
  - The container has full internet access

## get_exchange_rate
**When**: Question asks to convert between currencies (USD to JPY, GBP, INR, DEM, CAD).
**Tips**: Call `get_exchange_rate(pair="USD/JPY", year=2025, month=3, day=31)`. Returns historical rates. Available pairs: USD/JPY, USD/GBP, USD/INR, USD/DEM, USD/CAD. Do NOT guess exchange rates from training data — always use this tool.

## get_cpi_index
**When**: Question asks for inflation-adjusted/real/constant dollar values.
**Tips**: Call `get_cpi_index(year=1970, month=3)` for monthly CPI-U. Omit month for annual average. Formula: real_value = nominal_value × (target_CPI / source_CPI).

## resolve_agency_alias
**When**: search_tables returns nothing for a historical agency name.
**Tips**: Maps old names to canonical phrases (e.g., "war department" → search terms).
