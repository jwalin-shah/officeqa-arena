# Running OfficeQA Arena

This runbook covers local tooling, cloud sandboxes (Daytona), and DigitalOcean runner pools. For the pool script’s flags and topology in detail, see [runner-pool.md](runner-pool.md).

## Prerequisites

- **Python 3.12+** for most scripts under `scripts/`.
- **API keys** (as needed): `OPENROUTER_API_KEY` for LLM calls; `DAYTONA_API_KEY` for Daytona sandboxes; `doctl` + DigitalOcean token for the runner pool.
- Optional: `pip install -r requirements.txt` and a `.env` file at the repo root (some scripts load it).

## Arena harness configs (which YAML to use)

| Path | Harness | Prompt file (must match) | Typical use |
|------|---------|---------------------------|-------------|
| `arena.yaml` | Goose + remote MCP | `submit-goose/prompts/system.j2` | Root submit path: Harbor `/app/resources/` + remote `streamable_http` MCP at `/mcp` |
| `submit/arena.yaml` | OpenHands SDK + MCP | `prompts/system.j2` | Same contract as root; **Sentient submission** OpenHands path |
| `openhands/arena.yaml` | OpenHands SDK + MCP | `openhands/prompts/system.j2` | Alternate OpenHands + bundled `mcp_server.py` layout |
| `submit-goose/arena.yaml` | Goose + MCP | `submit-goose/prompts/system.j2` | **Harbor / manifest** workflow: `/app/resources/` + `manifest.json` (task-scoped files, not full corpus) |
| `analyst/arena.yaml` | Goose + `SOLVE_MODE=briefing` | `analyst/prompts/system.j2` | Mentor + briefing solver |
| `nomcp/arena.yaml` | Goose + MCP | `nomcp/prompts/system.j2` | `solve.py`-style tools via MCP |
| `nomcp/bottomup/arena.yaml` | Goose | `nomcp/bottomup/prompts/system.j2` | Orchestrator / decompose pipeline |

**Do not** point Goose Harbor configs at repo-root `prompts/system.j2` (OpenHands MCP-only rules) unless you intend that contract. See **§9.0** in [ARCHITECTURE.md](../ARCHITECTURE.md) (Harbor manifest subset vs OpenHands MCP).

**Trace checks:** after pulling trajectories (`scripts/pull_arena_traces.py`), run `python3 scripts/audit_traces.py <trace_dir>` to see harness name and harbor / manifest / `officeqa_*` signals.

See [ARCHITECTURE.md](../ARCHITECTURE.md) for pipeline behavior and scores.

## Local and single-machine workflows

### A/B comparison (`scripts/daytona_sandbox.py`)

Quick prompt vs. logic experiments (outputs JSONL with accuracy/cost/time):

```bash
python3 scripts/daytona_sandbox.py --samples 5 --output baseline.jsonl
# change code or prompts
python3 scripts/daytona_sandbox.py --samples 5 --output experiment.jsonl
```

Other useful modes (see script docstring): `run` (single UID + question), `batch` / `plan` with `--cases data/officeqa_full.csv`, `--goose` for Goose harness, `--workers` for parallelism.

### MCP server (stdio / remote)

The local stdio MCP entrypoint is `server/mcp_stdio.py`, used by the OpenHands configs (`submit/arena.yaml`, `openhands/arena.yaml`) together with `run_mcp.sh`. The root `arena.yaml` currently uses Goose with a remote `streamable_http` MCP endpoint instead. Keep the prompt and harness contract aligned with the YAML you submit.

## Corpus and large directory trees

**What counts as “the corpus”**

- **`corpus/`** — Treasury Bulletin plaintext (many `.txt` files). This is the **source text** agents search; it is not documentation.
- **Enriched SQLite** — Referenced by some runners (e.g. downloads in `scripts/daytona_sandbox.py`); paths like `/app/corpus/officeqa_enriched.sqlite3` in sandboxes.

**What is not “docs” but is huge in the repo**

- **`scripts/chrome_profile/`** — Chrome user profile and model-cache blobs from automation. Heavy on disk; safe to exclude from backups or `.gitignore` locally if you do not need browser sessions.
- **`corpus/`** — Large **data** tree; treat as dataset, not hand-written project docs.

## DigitalOcean pool (summary)

For `2 × N` droplets and parallel Arena lanes:

```bash
./scripts/do_runner_pool.sh up
./scripts/do_runner_pool.sh run --all
```

Full workflow, environment variables, and filtering are in [runner-pool.md](runner-pool.md).

## Scoring (Arena)

- **Correctness:** fuzzy numeric match within 1%.
- **Cost / time:** feed into the competition score (see ARCHITECTURE.md for the current formula and targets).
