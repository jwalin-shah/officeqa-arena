---
name: Current State (2026-03-30 evening)
description: Full system state after adding FX/CPI tools, awaiting submission #2 results
type: project
---

## Leaderboard (2026-03-30)
- #1: Dolores Research — 152.498
- #2: Bayes Foundry — 141.849
- #3: Us (Zero Node) — 135.461 (sub #1)
- Sub #2 ID: 121d5f33-f133-4d2b-806d-6f626ef36e44 (in_progress)
- 1 submission remaining today (resets midnight UTC = 5 PM PST)
- Deadline: April 4

## What Changed Since Last Update
- Added `get_exchange_rate` MCP tool + bundled exchange_rates.csv (USD/JPY, USD/GBP, USD/INR, USD/DEM, USD/CAD)
- Expanded CPI from annual-only (97 points) to monthly (1153 points, 1930-2026 via BLS API)
- Build script now bundles data/reference/ into containers
- Prompt + tool_guide updated with FX/CPI guidance
- All changes synced to droplet + build_install.sh re-run

## Key Facts
- No webfetch in Arena sandbox — only our MCP tools + bash
- 13 questions need exchange rates, 11 need monthly CPI — both now covered
- ~6 chart/visual questions unsolvable (MiniMax M2.5 not multimodal)
- max_iterations MUST stay at 15
- Model: openrouter/minimax/minimax-m2.5

## Architecture
- stdio MCP via `run_mcp.sh` → `python3 -m server.mcp_stdio`
- 14 tools now (was 13): added get_exchange_rate
- DB: 931MB compressed → 5.5GB decompressed, served via HTTP port 9090
- Build: `bash scripts/build_install.sh` on droplet before every submit
