# OfficeQA Arena

Sentient Arena OfficeQA challenge — Treasury bulletin numeric QA.

## Submission Path

```
arena.yaml -> run_mcp.sh -> python3 -m server.mcp_stdio
```

The canonical MCP server is `server.mcp_stdio` (zero external dependencies, pure JSON-RPC over stdio). `server/mcp_server.py` is a compatibility wrapper that delegates to the same entrypoint.

## Local Eval (Diagnostic Only)

```bash
python3 scripts/eval.py --cases CASES.json --db PATH.sqlite3 --max-iterations 10 --output results/out.json
```

This is **not** the actual Arena runtime. It drives the same tool surface via `src/agent.py` for local diagnostics.

## Smoke Test

```bash
python3 scripts/smoke_stdio.py --db PATH.sqlite3
```

Validates the stdio MCP server starts, registers all tools, and handles basic calls.

## Tools (15)

| Tool | Purpose |
|------|---------|
| `search_tables` | Find tables by keyword + year |
| `query_table_rows` | Get cell data with filters |
| `get_file_structure` | List tables in a bulletin file |
| `get_table_profile` | Inspect table columns/coverage |
| `compute_expression` | Deterministic arithmetic |
| `get_cpi_index` | CPI-U reference data |
| `get_exchange_rate` | Historical FX rates |
| `get_fiscal_year_bounds` | Fiscal year date resolution |
| `extract_values` | Mega-tool: search + fetch in one call |
| `get_time_series` | Contiguous year range series |
| `get_multi_year_series` | Sparse multi-year series |
| `grep_corpus` | Last-resort raw file grep |
| `web_lookup` | Fetch external URL data |
| `resolve_agency_alias` | Map historical agency names |
| `verify_answer` | Pre-write answer validation |

## Key Files

- `arena.yaml` — Arena harness config
- `prompts/system.j2` — System prompt template
- `run_mcp.sh` — MCP server launcher
- `server/mcp_stdio.py` — Canonical MCP server
- `server/tools.py` — Tool implementations
- `server/db.py` — SQLite read layer
- `skills/` — Domain knowledge (auto-injected)

## Scoring

Fuzzy numeric matching, 1% tolerance.
