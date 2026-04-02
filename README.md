# OfficeQA Arena — Meta-Harness Architecture

High-performance, low-latency Treasury Data QA system using a specialized deterministic routing harness based on the Goose Orchestrator.

## 🚀 Core Philosophy (Meta-Harness)
1. **Ledger-First Pathing:** The harness enforces a strict `route_question` phase before execution. The `master_ledger` is treated as a cheap "facts layer," handling most lookups, time-series, and aggregations.
2. **Aggressive Output Truncation:** Tools return extremely compact JSON payloads (e.g., top 5 matches only, truncated profiles) to prevent context inflation and LLM confusion.
3. **Anti-Spin Guardrails:** The system enforces strict tool budgets (e.g., 6 calls for the `ledger` path) and halts spinning loops (e.g., repeating failed searches). A robust finalizer guarantees a verified best-guess answer if budgets are exhausted.
4. **Visual Escape Hatch:** Automatically abstains early for pure visual/plot questions, preserving budget.
5. **No Redundancy:** Removed all skills and custom agent logic to ensure strict instruction adherence in the routing pipeline.

## 🛠 Project Structure
- `server/mcp_stdio.py` — Canonical MCP server launcher, managing paths, telemetry, and anti-spin constraints.
- `server/tools.py` — **The Truth:** Contains tool schemas and Python implementations designed for aggressive output compaction.
- `server/db.py` — Optimized SQLite read layer with debug logging.
- `prompts/goose_instructions.md` — Strict path-based instructions for the LLM.
- `scripts/daytona_sandbox.py` — Unified A/B testing runner.
- `scripts/do_runner_pool.sh` — DigitalOcean pool runner for `2 x 4` concurrent Arena lanes.
- `docs/running.md` — Primary runbook for local runs, single-droplet runs, and the pool runner.
- `docs/runner-pool.md` — Runbook for bringing up the droplet pool and running sample or CSV-backed tasks.

## 🏃 Runner Pool
For the DigitalOcean `2 droplets x 4 lanes = 8 concurrent tasks` workflow, use:

```bash
./scripts/do_runner_pool.sh up
./scripts/do_runner_pool.sh run --all
```

For non-sample tasks from the CSV:

```bash
./scripts/do_runner_pool.sh run --uids 'UID0001,UID0002,UID0201' --cases data/officeqa_full.csv
```

Full instructions are in [docs/runner-pool.md](/Users/jwalinshah/projects/officeqa-arena/docs/runner-pool.md).
General run instructions are in [docs/running.md](/Users/jwalinshah/projects/officeqa-arena/docs/running.md).

## 🧪 A/B Testing Protocol
To test a change (Prompt vs. Tool Logic):
1. Run baseline: `python3 scripts/daytona_sandbox.py --samples 5 --output baseline.jsonl`
2. Apply changes.
3. Run experiment: `python3 scripts/daytona_sandbox.py --samples 5 --output experiment.jsonl`
4. Compare `accuracy`, `cost_usd`, and `elapsed_sec` in the output files.

## 📊 Scoring
- **Correctness:** 1% tolerance fuzzy numeric match.
- **Cost:** MiniMax M2.5 ($0.20/M in, $1.20/M out).
- **Time:** Goal is < 60s per complex question.
