# OfficeQA Arena — Research Findings

## Critical Discovery: MCP Was Never Connecting (2026-03-30)

**Root cause:** `arena.yaml` pointed MCP command to `/installed-agent/run_mcp.sh` which doesn't exist in the container. The Docker image bakes the MCP server into `/opt/officeqa/` via the install script.

**Evidence:** OpenCode log from container:
```
service=mcp key=officeqa-arena mcp stderr: bash: /installed-agent/run_mcp.sh: No such file or directory
ERROR service=mcp key=officeqa-arena command=["bash","/installed-agent/run_mcp.sh"] error=MCP error -32000: Connection closed local mcp startup failed
```

**Fix:** Changed `arena.yaml` to point to `/opt/officeqa/run_mcp.sh`.

**Impact:** ALL previous Arena runs (including the 25% score) had NO MCP tools. The model only had grep/bash/read. This means our actual MCP-enabled performance is **unknown** — could be significantly higher.

## Container Architecture

- `/installed-agent/` — only contains `install.sh` (generated from `install-opencode.sh.j2`)
- `/opt/officeqa/` — full MCP server with venv, 16 tools, skills, config
- `/app/corpus/` — 697 treasury bulletin .txt files + SQLite DB
- `~/.config/opencode/opencode.json` — OpenCode config with MCP server definition
- `~/.config/opencode/skills/` — skills copied from `/opt/officeqa/skills/`

## Baked-in MCP Server (16 tools)

Located at `/opt/officeqa/mcp_server_arena.py`:
1. search_documents — document discovery
2. search_tables — table discovery
3. fetch_table_data — focused table evidence
4. query_table_rows — cell-level queries
5. get_file_structure — bulletin table listing
6. get_multi_year_series — time-series across years
7. extract_values — mega search+fetch tool
8. compute_expression — safe math evaluator
9. verify_answer — answer verification
10. verify_grounding — grounding check
11. get_cpi_index — CPI-U index
12. get_national_gdp — GDP values
13. get_fiscal_year_bounds — fiscal year dates
14. resolve_agency_alias — historical name mapping
15. rerank_evidence — evidence reranking
16. list_reference_library — reference data manifest

## OpenCode + MCP Integration

- OpenCode v1.3.7 installed via nvm (Node.js)
- MCP tools appear as native function-call tools alongside built-in tools (bash, read, glob, grep, edit, write, task, webfetch, todowrite, skill)
- Config written to `~/.config/opencode/opencode.json`
- `environment` field in MCP config for env vars (Arena SDK drops this silently — use auto-detect in run_mcp.sh)
- MCP server cold-boots fresh per `opencode run` invocation
- Default timeout: 5 seconds for MCP startup

## Arena SDK Issues Found

1. `MCPServerConfig` class has no `env`/`environment` field — env vars from arena.yaml silently dropped
2. `install-opencode.sh.j2` embeds a base64 tarball — our repo code doesn't directly reach the container
3. Memory override warning ("Overriding memory to 4096 MB") comes from task definition, not our config

## Scoring Formula

```
Score = correct_tasks × (1.0 + cost_adj + time_adj)
```
- Max possible: 282.9 (246 questions × ~1.15 max multiplier)
- Adjustments are ~10% of total
- Eval model: MiniMax M2.5

## Leaderboard (2026-03-30)

| Rank | Team | Score | Approx % Correct |
|------|------|-------|-------------------|
| 1 | Bayes Foundry | 103.478 | ~37% |
| 2 | GroundWire | 43.984 | ~16% |
| 3 | Pranav Patel | 41.979 | ~15% |
| 4-5 | Others | 38-39 | ~14% |

## Key Constraints

- 3 submissions/day, resets midnight UTC (5 PM PST)
- Deadline: April 4, 11:59 PM PST
- Only harness-based agents: opencode, codex, goose, openhands-sdk
- Custom MCP servers explicitly allowed
- Custom skills explicitly allowed
- Pre-computed answers prohibited

## Model: MiniMax M2.5

- OpenRouter ID: `minimax/minimax-m2.5`
- Context: 196,608 tokens
- Max output: 65,536 tokens
- Cost: $0.19/M input, $1.15/M output
- Strong at coding/office tasks (SWE-Bench 80.2%)

## Skills Analysis

- `setup_mcp_deps.md` — **DELETED** (harmful: told model to run apt-get, wasted iterations)
- `tool_guide.md` — useful but partially redundant with system prompt
- `treasury_domain.md` — most valuable skill, contains domain knowledge
- Baked-in skills at `/opt/officeqa/skills/arena_sdk/` include: treasury_reasoning, unit_reconciliation, metadata_aware_search, numerical_verification, master_protocol, reference_library, table_hierarchy_check, temporal_revision_audit, mcp_first_retrieval

## Previous Test Results

| Run | Config | Score | Notes |
|-----|--------|-------|-------|
| smoke (1q) | 7 tools, MCP broken | 1/1 (100%) | UID0199, grep-only |
| dev (20q) | old system, grep-only | 12/20 (60%) | No MCP tools |
| dev (20q) | current, MCP broken | 5/20 (25%) | MCP timeout on every call |
| smoke (1q) | 10 tools, MCP still broken | 1/1 (100%) | Still grep-only |
| 5q SSE old server | search_tables direct, skip extract_values | 3/5 (60%) | Multi-year questions fail (need get_time_series) |
