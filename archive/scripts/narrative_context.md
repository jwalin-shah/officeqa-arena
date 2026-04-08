ADDITIONAL REQUIREMENT for reingest_from_json.py:

When walking JSON elements in `build_normalized_rows_from_payload`, collect text elements that appear BETWEEN a section_header and its table. Store them as `context_text` in table_index.

The JSON element types appear in this order per table:
1. `section_header` — table title
2. `text` — narrative paragraphs (0 or more)
3. `footnote` — footnotes (0 or more)
4. `table` — the actual table

Collect all `text` elements between the header and the table, join with newlines, and store as:
- `table_index.context_text TEXT` — the narrative paragraphs preceding the table
- Truncate to 2000 chars to keep the DB lean

This gives the agent "why did X change?" context without needing the full document text.
