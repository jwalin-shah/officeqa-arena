# Runner Pool Runbook

This repo supports a DigitalOcean runner pool for parallel Arena runs.

Default topology:
- `2` droplets
- `4` Arena lanes per droplet
- `8` total concurrent task runs

The pool runner is [scripts/do_runner_pool.sh](/Users/jwalinshah/projects/officeqa-arena/scripts/do_runner_pool.sh).

## Snapshot

The pool defaults to the ready-made DO snapshot:
- snapshot id: `223007008`
- snapshot name: `officeqa-runner-ready-2026-04-02`

That means `up` creates runners from the snapshot rather than from plain Ubuntu.

## Bring Up The Pool

Create or reuse the two runner droplets:

```bash
./scripts/do_runner_pool.sh up
./scripts/do_runner_pool.sh ips
```

What `up` does:
- creates missing droplets
- waits for SSH
- installs missing system deps if needed
- syncs the repo to each runner
- does the create and prepare stages in parallel across runners

Useful checks:

```bash
./scripts/do_runner_pool.sh status
python3 scripts/pull_telemetry.py --summary
```

## Run Sample Tasks

Run all local sample tasks:

```bash
./scripts/do_runner_pool.sh run --all
```

One-shot lifecycle run:

```bash
./scripts/do_runner_pool.sh run --all --down-after
```

Run one sample task:

```bash
./scripts/do_runner_pool.sh run --filter 'uid0030'
```

Run a subset of matching sample tasks:

```bash
./scripts/do_runner_pool.sh run --filter 'uid00*' -n 8
```

Notes:
- `--filter` matches against task folders already present under `.arena/samples`
- `--all` means all currently available local sample tasks
- `*` also means all sample tasks, but `--all` is clearer
- `run` now auto-creates missing droplets before syncing and launching the pool
- `run` always pulls `.runner_pool/<run_label>` artifacts and `.arena/runs/` back locally before exit
- `--down-after` destroys the droplets after artifact pullback completes

## Run Non-Sample CSV Tasks

For tasks that are in `data/officeqa_full.csv` but not already materialized in `.arena/samples`, use `--uids`.

Example:

```bash
./scripts/do_runner_pool.sh run --uids 'UID0001,UID0002,UID0201' --cases data/officeqa_full.csv
```

What happens:
- the runner script calls [scripts/generate_arena_samples.py](/Users/jwalinshah/projects/officeqa-arena/scripts/generate_arena_samples.py)
- that creates `.arena/samples/officeqa-uidXXXX/` task folders from the CSV rows
- then the normal pool run proceeds

You can also generate those task folders manually:

```bash
python3 scripts/generate_arena_samples.py --cases data/officeqa_full.csv --uids UID0001,UID0002 --overwrite
```

## Monitoring

Live per-task telemetry summary:

```bash
python3 scripts/pull_telemetry.py --summary --live
```

Filter telemetry to one task:

```bash
python3 scripts/pull_telemetry.py --summary --task-id UID0001
```

Show raw trajectory summaries:

```bash
python3 scripts/pull_telemetry.py --trajectories
```

## Output Locations

Pool-run artifacts are written locally under:

```text
results/runner_pool/<run_label>/
```

Inside each runner directory:
- `logs/lane*.log` — lane stdout/stderr
- `results/lane*.jsonl` — per-task cost ledger and exit codes

Arena run outputs are also synced back into:

```text
.arena/runs/
```

## Tear Down

Destroy the pool:

```bash
./scripts/do_runner_pool.sh down
```

## Important Distinction

Use:

```bash
./scripts/do_runner_pool.sh run ...
```

for the `2 x 4` droplet pool.

Use:

```bash
bash scripts/arena_test.sh ...
```

only for running on a single machine.
