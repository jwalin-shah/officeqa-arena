# Tool Usage Guide

## search_tables

**When**: Always start here. Use keywords for the metric and year you need.

**Tips**:
- Keep queries short: "defense expenditures 1940" not full sentences.
- If no results, try synonyms: "receipts" / "revenue", "outlays" / "expenditures".
- Search both year Y and Y+1 bulletins for annual totals.

## query_table_rows

**When**: After `search_tables` gives you a `table_pk`.

**Tips**:
- Filter by year to reduce noise. If the year filter returns nothing, widen the range.
- Read the unit header in the response — it tells you if values are in millions, billions, etc.
- When you need multiple years from the same table, fetch them in one call.

## get_table_profile

**When**: You have a `table_pk` but are unsure of column names or table structure.

**Tips**:
- Use this before `query_table_rows` if column names are unclear.
- Helps you write correct filters and avoid empty results.

## get_file_structure

**When**: You need to browse all tables in a specific bulletin file.

**Tips**:
- Useful when `search_tables` finds the right file but wrong table.
- Returns all table names and section headers in the file.

## compute_expression

**When**: ANY arithmetic at all. Never do math in your head.

**Tips**:
- Define variables first, then write the expression: `{"a": 100, "b": 200}` with `"a + b"`.
- Supports `+`, `-`, `*`, `/`, `**`, `abs()`, `round()`, `min()`, `max()`, `sum()`.
- Convert units to the same base before computing.

## get_cpi_index

**When**: The question asks about inflation-adjusted values or real dollars.

**Tips**:
- Returns the CPI-U index for a given year and optional month.
- To adjust: `value * (target_cpi / source_cpi)`.

## get_fiscal_year_bounds

**When**: The question references a fiscal year and you need exact start/end dates.

**Tips**:
- Pre-1977: Jul 1 to Jun 30. Post-1976: Oct 1 to Sep 30.
- Use this to confirm date ranges, not to guess.
