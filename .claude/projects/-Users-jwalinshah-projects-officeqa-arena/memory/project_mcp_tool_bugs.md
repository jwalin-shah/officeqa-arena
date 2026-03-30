---
name: MCP Tool Bugs and Working Paths
description: Three root causes for broken tools in baked-in SSE server, plus working tool paths
type: project
---

The baked-in SSE MCP server (`docker-mcp-sse-1` on droplet port 8080) has three independent bugs:

1. **`extract_values` discards `table_pk`** — only uses file_id+table_title, then filters row_label=metric. But Treasury tables have years as rows and metrics as columns. Result: always 0 rows. Our local `server/tools.py` fixes this with a cascade (column_label → row_label → no filter).

2. **`search_documents` wrong directory** — globs `/app/corpus/*.txt` but files are in `/app/corpus/transformed/`. Returns 0 always. Also breaks extract_values fallback path.

3. **`document_elements` table empty** — several tools query it, get nothing.

**Working path:** `search_tables(query, year_range)` → `query_table_rows(table_pk, year)` → `compute_expression`. The prompt MUST tell the model to use this path and skip `extract_values`.

**Why:** Correct prompt routing to working tools is the single highest-impact change. The DB has 92K tables and 18.4M cells — the data IS there, just the retrieval chain was broken.

**How to apply:** Always route through search_tables + query_table_rows. Our SSE server at 209.38.74.239:8080 has the full DB. For submission, use SSE transport to public IP.
