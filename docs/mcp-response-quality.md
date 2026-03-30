# MCP Tool Response Quality Analysis

Investigation date: 2026-03-30
Run: `run-20260330-171951-0d0eff` / tag `fixed-sse-8081-v1`

## Results Summary

3 of 5 questions completed at time of analysis. All 3 completed got **reward 1.0** (correct).
uid0041, uid0048, uid0136 -- all correct. uid0194 and uid0199 still running.

Despite correct answers, the model wasted significant token budget re-searching.

---

## uid0041: Rural Electrification Administration Treasury Holdings (1961-1970)

### What happened
- **14 tool calls** to answer one question (should take 2-3)
- Model found the right table (pk=51379, FD-10) on the **first search** with score 111.5
- Successfully queried REA column for 1964-1970 (7 values from 3828 to 5328)
- Then **could not find 1961-1963 data** in the same table

### Root cause: Data gap in pk=51379
Table pk=51379 (from `treasury_bulletin_1973_09.txt`) has `min_year=1950` but scopes jump from "1950" to "1964". Years 1951-1963 are simply not present as rows. The model:
1. Queried `year_range=[1961,1963]` on pk=51379 --> **0 rows returned**
2. Re-searched 3 more times trying different year ranges
3. Browsed file structures for `1964_01` and `1965_01` bulletins
4. Finally found pk=32807 and pk=34535 (earlier bulletins) which also had FD-10 data
5. But those tables had **different column names**: "Agriculture Department" instead of "Rural Electrification Administration"

### Key confusion points
- **`units` field shows "1970" instead of actual units** (e.g., "millions of dollars"). The field is actually the time_scope, not units. This is misleading.
- **Multiple cells returned for one row with same column_label**: When querying pk=32807 for year=1961, got rows like `column_label="Agriculture Department"` with values 1107, 11534, 3332 -- three different values under the same column name. This is because the table has sub-columns under "Agriculture Department" that aren't distinguished in the column_label.
- **`label_match: "unfiltered"`** appears on every row -- provides no signal about whether filters matched.

### Token waste
Model made 14 tool calls. With better data, 2-3 would suffice:
1. search_tables (finds pk=51379 + pk=32807)
2. query_table_rows on pk=51379, column="REA", year_range=[1964,1970]
3. query_table_rows on pk=32807, column="REA", year_range=[1961,1963]

But the model couldn't do step 3 because pk=32807 didn't have "Rural Electrification Administration" as a column -- it was nested under "Agriculture Department".

---

## uid0048: Alcohol Tax Bureau Criminal Dispositions Dec 1938

### What happened
- **12 tool calls** total
- search_tables found "Treasury Criminal Cases, by Months" tables (pk=215, 362, 519) with score ~44-53
- But these tables have **generic column names** ("Percent convicted", "Number cases closed") without bureau-level breakdown in columns
- The bureau breakdown exists as **row labels** (e.g., "Alcohol Tax") in the raw text, but `query_table_rows` with `row_label="Alcohol Tax"` returned **0 rows**

### Root cause: Row label parsing failure
The raw data has rows like:
```
| Alcohol Tax | 2534 | 16% | 10% | 4% | 30% | 7% | 63% | 70% |
```
But when the model queried `row_label="Alcohol Tax"`, it got 0 results. The row_label matching is failing on these bureau names. The model had to **fall back to grep** to find the actual data in the raw text files.

### Key confusion points
- **Duplicate column labels**: pk=215 returns multiple rows for Dec 1938 with `column_label="Percent convicted"` having values 27%, 8%, 65%, 73%. These are actually sub-columns (found guilty, plead guilty, total, etc.) that share the parent label.
- **Row label "Dec..." vs month filter**: The data uses `row_label="Dec....."` (with dots) and `month=12`, but the row labels are inconsistently formatted across tables.
- **The model eventually used grep** to read the raw corpus text to find the December 1938 Alcohol Tax data, proving the MCP tools couldn't surface this hierarchical table structure properly.

### How the model succeeded
Despite tool limitations, the model used grep on `treasury_bulletin_1939_02.txt` which had December 1938 data with Alcohol Tax showing 30% total released and 70% convicted, then computed the answer.

---

## uid0136: 91-Day Weekly Bills Discount Rate September (1953-1955)

### What happened
- **~13 tool calls**, but ultimately fell back to **grep on raw text**
- search_tables returned "Average Yields of Taxable Treasury..." tables (score ~61) which are NOT the right tables
- The actual data is in **narrative text paragraphs**, not structured tables

### Root cause: Data is in prose, not tables
The discount rates for weekly 91-day bill auctions are mentioned in the bulletin's editorial text, e.g.:
```
New issues of weekly Treasury bills during September totaled $6.0 billion...
The average rates of discount on the new issues were 1.961 percent for
September 3, 1.953 percent for September 10, 1.957 percent for
September 17, and 1.634 percent for September 24.
```

This data was **never parsed into any table**. search_tables can never find it.

### Key confusion points
- **search_tables returns irrelevant matches**: "Average Yields of Taxable Treasury Bonds" tables score highest because they match "Treasury" + "yields" + year overlap. But they contain bond yields, not bill auction rates.
- **"New Money Financing through Regular Weekly Treasury Bills"** (pk=29696, 23495) was found but contains bid amounts and new money figures, not the average discount rates the model needs.
- The model tried **5 different search_tables queries** before giving up and using grep.

### How the model succeeded
Used grep to find the prose paragraphs in each September bulletin (1953, 1954, 1955), extracted the discount rates manually from the narrative text, then computed the geometric mean.

---

## uid0199: Net Capital Movement by Country 1935

### What happened (still running at analysis time)
- **18+ tool calls** and counting
- search_tables consistently returns pk=4423 ("Net Capital Movement to the United States, 1935 through November 1942") with score ~71.5
- But this table has only **5 columns** (aggregate breakdown by type: banking funds, brokerage, domestic securities, foreign securities) -- NOT by country
- The country-level breakdown exists in a **different table** in `treasury_bulletin_1940_04.txt` that the model eventually found via grep

### Root cause: Country breakdown table not in search index
The country-level "Net Capital Movement between the United States and Foreign Countries" table exists in `treasury_bulletin_1940_04.txt` around line 1656 with columns: England, France, Germany, Italy, Netherlands, Switzerland, etc. But search_tables never surfaces this table. Reasons:
1. The table title in the corpus is "Net Capital Movement between the United States and Foreign Countries" -- should match "net capital movement" queries
2. The columns include country names (France, Germany, etc.) which the model searched for
3. Yet the scoring algorithm ranks the aggregate table (pk=4423) higher because it has "Net capital movement" in BOTH title AND column names, getting double credit

### Key confusion points
- **columns_sample misleading**: pk=4423 shows `columns_sample: ["Net capital movement", "Analysis of net capital movement"]` -- the model has no way to know this is aggregate-only without calling get_table_profile
- **Country names not indexed**: When model searched for "capital movement France Netherlands Switzerland Italy", it got currency tables instead (score=55 for "Value of Selected Currencies") because country names appear in currency tables' columns
- **No bulletins before 1939**: The corpus starts at 1939_01, so there's no 1935/1936 bulletin. The 1935 data only appears as historical series in later bulletins, making it harder to find.

---

## Systemic Issues Found

### 1. `units` field is actually `time_scope`
Every row returns `"units": "1970"` or `"units": "1938-12"` -- this is the time period, not the data units (millions of dollars, percent, etc.). **Extremely confusing** for the model. Should be renamed to `time_scope` or `period` and a real `units` field should be added from the table metadata.

### 2. Duplicate column_labels hide sub-column structure
Tables with hierarchical headers (e.g., "Percent convicted > Found guilty" / "Percent convicted > Plead guilty") return multiple rows with identical `column_label="Percent convicted"` but different values. The model cannot distinguish which sub-column a value belongs to without reading the raw snippet. This caused confusion in uid0048.

### 3. Row label matching failures
`query_table_rows(row_label="Alcohol Tax")` returns 0 rows even though "Alcohol Tax" clearly exists as a row in the raw data. The fuzzy LIKE matching is not working for multi-word row labels that appear in parsed table data.

### 4. Narrative/prose data invisible to search_tables
Weekly bill auction discount rates (uid0136) exist only in editorial paragraphs, not in any parsed table. search_tables can never find this data. The model must fall back to grep, which wastes many calls discovering this limitation.

### 5. search_tables over-ranks tables with term overlap in both title AND columns
Tables where the same concept appears in title and columns get inflated scores (e.g., "Net Capital Movement" in both title and column_name). This causes aggregate summary tables to consistently outrank more specific tables with the actual data breakdown.

### 6. Massive response payloads waste context
Each query_table_rows call returns **every cell in the row** when no column_label filter is specified. For uid0041's pk=51379, querying year=1970 returns 14 cells (one per column) when the model only needs the REA column. Each cell includes full table_title, source_file, table_pk, and a snippet -- roughly 200 tokens per cell. A single query_table_rows call can consume 2000+ tokens of context.

### 7. `label_match: "unfiltered"` is always present and useless
Every single row in every response shows `"label_match": "unfiltered"`. This provides zero information and wastes tokens.

---

## Recommendations

1. **Rename `units` to `period`** and add actual units from table metadata
2. **Include sub-column hierarchy** in column_label (e.g., "Percent convicted > Found guilty")
3. **Fix row_label matching** for multi-word labels like "Alcohol Tax"
4. **Add a `search_text` tool** that searches narrative/prose sections of bulletins
5. **Compress response payloads**: remove redundant fields (table_title, source_file, table_pk repeated on every row), remove useless `label_match`
6. **When column_label is specified**, only return that column's data (not all columns in the row)
7. **Improve search scoring** to not double-count concepts that appear in both title and column names
