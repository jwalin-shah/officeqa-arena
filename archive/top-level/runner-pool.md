# DigitalOcean runner pool

This document matches `scripts/do_runner_pool.sh`, which provisions DigitalOcean droplets from a snapshot and runs Arena tasks across multiple **lanes** per machine.

## Topology (defaults)

- **Droplets:** `RUNNER_COUNT` (default `2`), names like `officeqa-big-runner-01`.
- **Lanes per runner:** `LANES_PER_RUNNER` (default `2`). Total concurrent lanes ≈ `RUNNER_COUNT × LANES_PER_RUNNER` (see the script’s own comment block for the intended production topology).
- **Size / region:** `RUNNER_SIZE` (default `s-8vcpu-16gb`), `RUNNER_REGION` (default `sfo3`).
- **Image:** `RUNNER_IMAGE` (snapshot ID; default noted in script comments, e.g. `officeqa-runner-ready` snapshot).

Override any of these via environment variables when invoking the script.

## Requirements

- **`doctl`** configured with a DigitalOcean API token.
- **SSH key** available locally; `SSH_KEY_ID` must match a key registered in DO (default in script may need updating for your account).
- Network access from your machine to droplet public IPs.

## Common commands

Bring up droplets:

```bash
./scripts/do_runner_pool.sh up
```

List IPs:

```bash
./scripts/do_runner_pool.sh ips
```

Sync project files to droplets (when implemented in your workflow):

```bash
./scripts/do_runner_pool.sh sync
```

Run tasks:

```bash
# All sample / default task set (see script implementation)
./scripts/do_runner_pool.sh run --all

# Glob filter and cap concurrency
./scripts/do_runner_pool.sh run --filter 'uid00*' -n 8

# Explicit UIDs
./scripts/do_runner_pool.sh run --uids 'UID0001,UID0002,UID0201'

# Custom case file (CSV)
./scripts/do_runner_pool.sh run --uids 'UID0001,UID0002' --cases data/officeqa_full.csv
```

Status and teardown:

```bash
./scripts/do_runner_pool.sh status
./scripts/do_runner_pool.sh down
```

## Outputs

- Local pool state and logs are under `results/runner_pool/` (see `LOCAL_POOL_DIR` in the script).

## Related

- General running options: [running.md](running.md)
- Architecture and harness differences: [ARCHITECTURE.md](../ARCHITECTURE.md)
