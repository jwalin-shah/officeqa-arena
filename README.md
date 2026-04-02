# OfficeQA Arena — Lean Goose Architecture

High-performance, low-latency Treasury Data QA system using the Goose Orchestrator.

## 🚀 Core Philosophy
1. **Lightweight Persona:** Using Goose instead of OpenHands saves ~4,000 tokens per turn.
2. **Built-in Schemas:** Tool schemas and logic are consolidated in `server/tools.py`.
3. **No Redundancy:** Removed all skills and custom agent logic to ensure strict instruction adherence.
4. **Traceable DB:** SQL queries are logged to stderr for debugging (use `--debug`).

## 🛠 Project Structure
- `server/mcp_stdio.py` — Canonical MCP server launcher.
- `server/tools.py` — **The Truth:** Contains both Tool Schemas and Python implementation.
- `server/db.py` — Optimized SQLite read layer with debug logging.
- `prompts/goose_instructions.md` — High-signal search strategy for the model.
- `scripts/daytona_sandbox.py` — Unified A/B testing runner.

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
