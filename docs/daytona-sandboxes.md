# Daytona Sandboxes

Cloud sandboxes for running OfficeQA Arena tasks. Each sandbox gets 4 CPU, 4GB RAM, 10GB disk with the full corpus DB pre-loaded.

## Setup (one-time)

```bash
# 1. Create venv and install deps
bash scripts/setup.sh

# 2. Activate venv
source .venv/bin/activate

# 3. Add your Daytona API key to .env
#    Get one at https://app.daytona.io/dashboard/keys
#    Needs: write:sandboxes, delete:sandboxes, write:snapshots, delete:snapshots
```

Your `.env` should have:
```
OPENROUTER_API_KEY=sk-or-v1-...
DAYTONA_API_KEY=dtn_...
DAYTONA_TARGET=us
```

## Architecture

The system is split into two layers:

**Snapshot** (heavy, rebuild only when DB or deps change):
- Python 3.11-slim + zstd
- pip packages: openai, pyyaml, jinja2
- Corpus DB (~7GB decompressed from 931MB zst)
- Reference data (CPI, exchange rates, GDP, agency aliases)

**Sandbox** (light, created per-run with latest code):
- Created from snapshot in ~2 seconds
- Uploads latest `server/`, `src/`, `prompts/`, `skills/` code (~few KB)
- Env vars (API keys) injected at creation

This means you **never need to rebuild the snapshot** when changing code — only when the DB or Python deps change.

## Commands

### Build the snapshot

```bash
python3 scripts/daytona_sandbox.py snapshot
```

Uploads the compressed DB from `data/officeqa_lean_final.sqlite3.zst` and builds the image in Daytona's cloud. Takes ~10 minutes. Only needed once, or when the DB changes.

Requires the compressed DB locally:
```bash
# Download from droplet if you don't have it
scp root@134.122.25.72:/root/officeqa-serve/officeqa_lean_final.sqlite3.zst data/
```

### Create a sandbox (debugging)

```bash
python3 scripts/daytona_sandbox.py create
```

Spins up a sandbox and prints its ID. Stays alive for manual testing. Clean up via the Daytona dashboard or delete in code.

### Run a single question

```bash
python3 scripts/daytona_sandbox.py run \
  --uid UID0004 \
  --question "What was the total public debt in 1941?" \
  --gold "48961"
```

Creates a sandbox, runs the full agent loop, prints the result, deletes the sandbox.

### Batch run (parallel sandboxes)

```bash
# 2 parallel sandboxes, arena subset (20 questions)
python3 scripts/daytona_sandbox.py batch \
  --cases data/officeqa_full.csv \
  --workers 2 \
  --subset arena

# All 246 questions, 3 parallel sandboxes
python3 scripts/daytona_sandbox.py batch \
  --cases data/officeqa_full.csv \
  --workers 3

# Specific UIDs
python3 scripts/daytona_sandbox.py batch \
  --cases data/officeqa_full.csv \
  --workers 2 \
  --subset "UID0004,UID0030,UID0097"

# Limit to first N
python3 scripts/daytona_sandbox.py batch \
  --cases data/officeqa_full.csv \
  --workers 2 \
  --limit 10
```

Results go to `results/stages/daytona_batch.jsonl` by default, or use `--output`.

## When to rebuild the snapshot

- DB changes (new lean DB version, schema changes)
- Python deps change (new package in requirements.txt)
- Reference data changes (CPI, exchange rates CSVs)

You do **not** need to rebuild for:
- Code changes in `server/`, `src/`, `prompts/`, `skills/`
- arena.yaml changes
- Prompt template changes

To rebuild:
```bash
# Delete old snapshot first
python3 -c "
from dotenv import load_dotenv; load_dotenv('.env')
from daytona import Daytona, DaytonaConfig
import os
client = Daytona(DaytonaConfig(api_key=os.environ['DAYTONA_API_KEY'], target='us'))
snap = client.snapshot.get('officeqa-arena')
client.snapshot.delete(snap)
"

# Build new one
python3 scripts/daytona_sandbox.py snapshot
```

## Resource limits

| Resource | Sandbox spec | Daytona max (default org) |
|----------|-------------|---------------------------|
| CPU      | 4 vCPU      | 4 vCPU                    |
| RAM      | 4 GiB       | 8 GiB                     |
| Disk     | 10 GiB      | 10 GiB                    |

DB is ~7GB of the 10GB disk. Contact support@daytona.io to increase limits.

## File layout inside sandbox

```
/opt/officeqa/           # Working directory
  server/                # MCP server (uploaded fresh)
  src/                   # Agent code (uploaded fresh)
  prompts/               # Prompt templates (uploaded fresh)
  skills/                # Skill docs (uploaded fresh)
  data/reference/        # CPI, exchange rates (in snapshot)
  run_mcp.sh             # MCP launcher (uploaded fresh)
/app/corpus/
  officeqa_corpus.sqlite3  # 7GB corpus DB (in snapshot)
```

## Env vars in sandbox

Set automatically:
- `OFFICEQA_SQLITE_DB=/app/corpus/officeqa_corpus.sqlite3`
- `PYTHONUNBUFFERED=1`

Passed through from your `.env`:
- `OPENROUTER_API_KEY`
- `LLM_API_KEY`
