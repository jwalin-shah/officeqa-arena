---
name: MCP breakthrough and current state
description: Zero-dep MCP server fixes startup timeout. Arena test results and next steps as of 2026-03-30.
type: project
---

## MCP Breakthrough
The `mcp` Python package needs 30-60s to install (apt-get + pip) inside the Arena Docker container. OpenCode has a short timeout for MCP server startup (~5s). Solution: `server/mcp_stdio.py` implements the full MCP JSON-RPC 2.0 protocol using ONLY Python stdlib (json, sys). Starts instantly. Zero external dependencies.

## Arena Test Results (2026-03-30)
- **With MCP working (smoke):** UID0199 PASSED (first time ever — capital movements question)
- **Full 20q test:** 5/20 = 25% (uid0004, uid0033, uid0097, uid0217, uid0230)
- **Old 60% system comparison:** We lost 8 questions it passed, gained 1 new
- **Root cause of gap:** MCP tools still failed on first 1-2 calls due to startup race condition. With mcp_stdio.py this should be fixed.

## What Still Needs Testing
- Run `arena test --all` with the new zero-dep `mcp_stdio.py` server
- If MCP tools work from the FIRST call, accuracy should increase significantly
- The 60% system used grep because MCP never worked. Now MCP can work.

## Architecture (current)
- Harness: OpenCode
- MCP: stdio via `run_mcp.sh` → `python3 -m server.mcp_stdio`
- Tools: 7 (search_tables, query_table_rows, get_table_profile, get_file_structure, compute_expression, get_cpi_index, get_fiscal_year_bounds)
- Model: MiniMax M2.7 via OpenRouter
- Prompt: Lean ~50 lines, MCP-first with grep fallback
- DB: 11GB SQLite on the Docker image at /app/corpus/

## Key Files
- `server/mcp_stdio.py` — zero-dep MCP server (THE fix)
- `server/tools.py` — tool implementations backed by db.py
- `server/db.py` — SQLite read layer
- `server/safe_eval.py` — compute_expression (fixed: list syntax, ^, round)
- `run_mcp.sh` — launcher script
- `arena.yaml` — OpenCode + stdio MCP config
- `prompts/system.j2` — lean system prompt
