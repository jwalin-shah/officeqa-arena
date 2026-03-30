---
name: Current State (2026-03-30 ~12:20pm PST)
description: Full system state, what works, what's pending, next steps for a new Claude instance
type: project
---

## What's Running RIGHT NOW

1. **Submission #1 (SSE)**: ID `cc19566b-0c49-440c-b4b2-10687ac55c74`, status: in_progress. Uses SSE MCP at 209.38.74.239:8081. Check: `arena status cc19566b-0c49-440c-b4b2-10687ac55c74`
2. **Smoke test (stdio+indexed DB)**: tag "indexed-db-v1", running. Tests the full pipeline: install → download 931MB DB → decompress to 7GB → stdio MCP server. This is our best config.
3. **SSE server on port 8081**: Running with full 11GB DB. PID on droplet.
4. **HTTP server on port 9090**: Serving the compressed lean DB for container downloads.

## Architecture (PROVEN WORKING)

**stdio+DB approach** (for submission):
- `scripts/build_install.sh` patches Harbor's `install-opencode.sh.j2` template
- Embeds our `server/` code (mcp_stdio.py, tools.py, db.py, safe_eval.py) as base64 tarball
- Downloads lean DB from `http://209.38.74.239:9090/officeqa_lean_final.sqlite3.zst` (931MB)
- Decompresses to 7GB at `/app/corpus/officeqa_corpus.sqlite3`
- `run_mcp.sh` does `cd /opt/officeqa && exec python3 -m server.mcp_stdio`
- **MUST run `bash scripts/build_install.sh` on droplet before `arena submit`**

**Lean DB contents** (7GB with indexes):
- `table_first_table_cells`: 18.4M rows (all cell values) + indexes on (table_pk), (year), (table_pk, year)
- `table_index`: 92K rows (search index)
- `table_first_tables`: 92K rows (table metadata with units)
- `table_term_index`: 8.7M rows (keyword search scoring) + index on (term_norm, table_pk)
- `table_scope_index`, `table_first_table_scopes`, `file_year_coverage`, `documents`

**Tool speeds with indexed DB:**
- search_tables: 1-10s (was 14-19s without term_index)
- query_table_rows: 0.008s (was 12s without index!)
- extract_values: 0.7-3.6s (was 60s timeout!)
- get_table_profile: 0.002s

## Test Results

| Test | Config | Score | Notes |
|------|--------|-------|-------|
| 20q dev (latest) | SSE + full DB | 11/20 = 55% | Projected ~148 on 246q |
| 4q focused | SSE + fixed tools | 4/4 = 100% | uid0041,0048,0136,0199 |
| Smoke stdio+DB (no index) | stdio, 4.8GB DB | 1/1 PASS | uid0199, 483s, $0.10 |
| Smoke stdio+indexed DB | stdio, 7GB DB | RUNNING | Should be faster |

## Key Files

| File | Purpose |
|------|---------|
| `arena.yaml` | Config: stdio transport, `/opt/officeqa/run_mcp.sh`, max_iterations=30, reasoning_effort=medium, MiniMax M2.5 |
| `prompts/system.j2` | Decision tree: SEARCH → INSPECT → EXTRACT → VERIFY → COMPUTE → WRITE |
| `scripts/build_install.sh` | Patches Harbor template. **Run before every submit.** |
| `server/mcp_stdio.py` | Zero-dep MCP server (JSON-RPC over stdio) |
| `server/mcp_sse.py` | SSE MCP server (for local testing on port 8081) |
| `server/tools.py` | Fixed extract_values (cascade), get_time_series (new) |
| `server/db.py` | search_tables + query_table_rows (working, with year-range SQL filter) |
| `server/safe_eval.py` | compute_expression: +linreg, cagr, theil_index, cv |
| `skills/tool_guide.md` | Tool priority guide |
| `skills/treasury_domain.md` | Domain knowledge (fiscal years, defense decomposition, units) |
| `docs/` | All research: findings.md, trace-analysis-20q.md, failure-analysis-20q.md, question-analysis.md, prompt-optimization.md, etc. |

## Known Issues & Remaining Improvements

1. **Search quality**: search_tables returns wrong-era tables for some queries. term_index helps but scoring could be better (year penalty for mismatched eras).
2. **Model over-searches**: Calls search_tables 3-4x despite prompt saying max 2. M2.5 overrides instructions.
3. **Unit conversion**: Model sometimes ignores "in thousands" in table_info. Prompt now emphasizes it.
4. **Grep output too large**: Broad grep patterns return 71K chars. Should cap at `| head -20`.
5. **Visual questions**: ~6 questions need chart reading (impossible with text corpus).
6. **query_table_rows returns 0 rows**: Some tables have years embedded in row labels, not as separate year column. Model needs to use get_table_profile first.

## Submissions

- 3/day, resets midnight UTC (5 PM PST)
- Submission #1 used (SSE). 2 remaining today.
- Deadline April 4 (vote to extend to April 11)
- **Before submitting**: Run `bash scripts/build_install.sh` on droplet, verify HTTP server (port 9090) is running.

## Droplet Services (must be running)

- **HTTP server (port 9090)**: `cd /root/officeqa-serve && nohup python3 -m http.server 9090 &`
- **SSE server (port 8081)**: `cd /root/officeqa-arena && OFFICEQA_SQLITE_DB=... nohup python3 -m server.mcp_sse --port 8081 &`
- **MCP SSE (port 8080)**: Old baked-in server (broken tools, but always running in Docker)
