# Running OfficeQA

This repo has three main ways to run Arena:

1. Local single-machine runs
2. Single-droplet runs
3. Snapshot-based runner pool runs

Use this file as the entrypoint for run commands and operational notes.

## 1. Local Single-Machine

Use [scripts/arena_test.sh](/Users/jwalinshah/projects/officeqa-arena/scripts/arena_test.sh) when you want to run on the current machine only.

Examples:

```bash
bash scripts/arena_test.sh --smoke
bash scripts/arena_test.sh --filter 'uid0030'
bash scripts/arena_test.sh --all
bash scripts/arena_test.sh --all -j8
```

Notes:
- `-j8` is handled by the wrapper script, not by `arena test` itself
- this is for one machine only
- it is useful when the current machine already has Docker and Arena working

## 2. Single Droplet

Use the single-runner scripts when you want one DO droplet instead of the full pool.

Relevant scripts:
- [scripts/do_runner.sh](/Users/jwalinshah/projects/officeqa-arena/scripts/do_runner.sh)
- [scripts/arena_droplet.sh](/Users/jwalinshah/projects/officeqa-arena/scripts/arena_droplet.sh)

Typical flow:

```bash
./scripts/do_runner.sh up
./scripts/do_runner.sh test --smoke
./scripts/do_runner.sh down
```

Use this when:
- you only want one droplet
- you are debugging setup or telemetry
- you do not need the `2 x 4` pool

## 3. Runner Pool

Use the pool runner for the full DigitalOcean parallel flow.

Main script:
- [scripts/do_runner_pool.sh](/Users/jwalinshah/projects/officeqa-arena/scripts/do_runner_pool.sh)

Full pool runbook:
- [docs/runner-pool.md](/Users/jwalinshah/projects/officeqa-arena/docs/runner-pool.md)

Typical flow:

```bash
./scripts/do_runner_pool.sh up
./scripts/do_runner_pool.sh run --all
python3 scripts/pull_telemetry.py --summary --live
./scripts/do_runner_pool.sh down
```

Default pool topology:
- `2` droplets
- `4` lanes per droplet
- `8` total concurrent Arena tasks

Default image source:
- DO snapshot `223007008`
- snapshot name `officeqa-runner-ready-2026-04-02`

## Running Non-Sample CSV Tasks

If a task is in `data/officeqa_full.csv` but is not already materialized under `.arena/samples`, generate it from the CSV.

Generator:
- [scripts/generate_arena_samples.py](/Users/jwalinshah/projects/officeqa-arena/scripts/generate_arena_samples.py)

Generate manually:

```bash
python3 scripts/generate_arena_samples.py --cases data/officeqa_full.csv --uids UID0001,UID0002 --overwrite
```

Or let the pool runner do it automatically:

```bash
./scripts/do_runner_pool.sh run --uids 'UID0001,UID0002,UID0201' --cases data/officeqa_full.csv
```

## Monitoring

Per-task telemetry summary:

```bash
python3 scripts/pull_telemetry.py --summary
python3 scripts/pull_telemetry.py --summary --live
python3 scripts/pull_telemetry.py --summary --task-id UID0001
```

Trajectory summaries:

```bash
python3 scripts/pull_telemetry.py --trajectories
```

## Result Locations

Arena run outputs:

```text
.arena/runs/
```

Pool runner artifacts:

```text
results/runner_pool/<run_label>/
```

## Which Command Should I Use?

Use:

```bash
bash scripts/arena_test.sh ...
```

when you want one-machine local execution.

Use:

```bash
./scripts/do_runner.sh ...
```

when you want one droplet.

Use:

```bash
./scripts/do_runner_pool.sh ...
```

when you want the snapshot-based `2 x 4 = 8 lane` pool.
