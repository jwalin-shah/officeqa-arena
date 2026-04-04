# OfficeQA Arena

Treasury Bulletin question answering for the Arena **grounded-reasoning** track: deterministic routing, corpus search, and optional mentor-style harnesses. Deep design and prompt inventory: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Harness configs

| File | Stack | Notes |
|------|--------|--------|
| [arena.yaml](arena.yaml) | OpenHands SDK + MCP stdio | Tool-calling loop with `server/` MCP tools |
| [analyst/arena.yaml](analyst/arena.yaml) | Goose, `SOLVE_MODE=briefing` | Mentor + briefing solver ([analyst/solve_briefing.py](analyst/solve_briefing.py)) |
| [nomcp/arena.yaml](nomcp/arena.yaml) | Goose + [nomcp/solve.py](nomcp/solve.py) | Direct deterministic solver, fewer turns |

## Core ideas

1. **Route before spend:** Classify the question, then run search / deterministic extraction before wide LLM reasoning.
2. **Compact tool payloads:** Truncated JSON and tight evidence formatting to limit context blow-up.
3. **Budgets and anti-spin:** Bounded tool use and stop conditions so the model cannot loop forever.
4. **Skills:** Goose configs set `skills_dir: skills/`. Markdown skills live under [analyst/skills/](analyst/skills/) and [nomcp/skills/](nomcp/skills/) (patterns, glossary, CPI notes). They supplement the harness; they are not “redundant agents.”

## Project layout (main entrypoints)

- `server/mcp_stdio.py` — MCP stdio server (paths, telemetry, tool budgets).
- `server/tools.py` — Tool schemas and implementations.
- `server/db.py` — SQLite read path for enriched tables (when used).
- `prompts/goose_instructions.md` — Goose-oriented instruction text.
- `scripts/daytona_sandbox.py` — Daytona sandboxes, batch runs, A/B JSONL output.
- `scripts/do_runner_pool.sh` — DigitalOcean droplet pool for parallel Arena runs.
- `docs/running.md` — **Runbook:** local runs, Daytona, corpus notes, harness choice.
- `docs/runner-pool.md` — **Pool runbook:** `do_runner_pool.sh` topology and commands.

## Runner pool (DigitalOcean)

```bash
./scripts/do_runner_pool.sh up
./scripts/do_runner_pool.sh run --all
```

CSV-backed UIDs:

```bash
./scripts/do_runner_pool.sh run --uids 'UID0001,UID0002,UID0201' --cases data/officeqa_full.csv
```

Details: [docs/runner-pool.md](docs/runner-pool.md). General execution: [docs/running.md](docs/running.md).

## A/B testing

```bash
python3 scripts/daytona_sandbox.py --samples 5 --output baseline.jsonl
# change prompts or code
python3 scripts/daytona_sandbox.py --samples 5 --output experiment.jsonl
```

Compare `accuracy`, `cost_usd`, and `elapsed_sec` in the JSONL files.

## Scoring (Arena)

- **Correctness:** 1% tolerance fuzzy numeric match.
- **Cost:** MiniMax M2.5 via OpenRouter (see current pricing in your dashboard).
- **Time:** target &lt; 60s for complex questions when tuning.

## Large trees in the repo (not “missing docs”)

- **`corpus/`** — Treasury Bulletin **plaintext data** (hundreds of `.txt` files). This is the searchable source corpus, not hand-written documentation.
- **`scripts/chrome_profile/`** — Chrome profile and embedded **model cache** from automation; very large on disk. Exclude from git or delete locally if you do not need saved browser state.

See [docs/running.md](docs/running.md#corpus-and-large-directory-trees) for a short breakdown.
