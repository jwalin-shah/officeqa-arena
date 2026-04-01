#!/usr/bin/env python3
"""Daytona sandbox manager for OfficeQA Arena.

Creates cloud sandboxes with 4 CPU / 4GB RAM / 10GB disk, downloads the
corpus DB, and runs the agent loop or stage_runner inside the sandbox.

Usage:
  # Create a snapshot (one-time, builds image in Daytona cloud)
  python3 scripts/daytona_sandbox.py snapshot

  # Spin up a sandbox and run a single question
  python3 scripts/daytona_sandbox.py run --uid UID0004 --question "What was the..."

  # Spin up N sandboxes in parallel for batch replay
  python3 scripts/daytona_sandbox.py batch --cases data/officeqa_full.csv --workers 2

  # Just create a sandbox (for debugging / manual use)
  python3 scripts/daytona_sandbox.py create

Env vars:
  DAYTONA_API_KEY      — required, from https://app.daytona.io/dashboard/keys
  DAYTONA_TARGET       — optional, default "us"
  OPENROUTER_API_KEY   — passed into sandbox for LLM calls
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load .env file if present (OPENROUTER_API_KEY, DAYTONA_API_KEY, etc.)
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        # Fallback: parse .env manually
        for line in _env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

try:
    from daytona import (
        Daytona,
        DaytonaConfig,
        CreateSandboxFromImageParams,
        CreateSandboxFromSnapshotParams,
        CreateSnapshotParams,
        Resources,
    )
except ImportError:
    print("ERROR: daytona SDK not installed. Run: pip install daytona")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent

# ── Config ─────────────────────────────────────────────────────────

SNAPSHOT_NAME = "officeqa-arena"
DOCKER_IMAGE = "python:3.12-slim"  # base image; openhands-sdk requires >=3.12
SANDBOX_RESOURCES = Resources(cpu=2, memory=2, disk=6)

DB_URL = "http://147.182.206.223:9090/officeqa_slim_v2.sqlite3.zst"
DB_PATH = "/app/corpus/officeqa_enriched.sqlite3"

# Files to upload are discovered dynamically from the repo
def _discover_upload_files() -> list[str]:
    """Discover files to upload into the sandbox (relative to repo root)."""
    files = []
    # Server package — all .py files
    for p in sorted((ROOT / "server").glob("*.py")):
        files.append(f"server/{p.name}")
    # Reference data
    ref_dir = ROOT / "data" / "reference"
    if ref_dir.is_dir():
        for p in sorted(ref_dir.iterdir()):
            if p.is_file():
                files.append(f"data/reference/{p.name}")
    # Agent code — all .py files in src/
    for p in sorted((ROOT / "src").glob("*.py")):
        files.append(f"src/{p.name}")
    # Prompt templates — all .j2 files
    for p in sorted((ROOT / "prompts").glob("*.j2")):
        files.append(f"prompts/{p.name}")
    # Config + launcher
    for name in ("run_mcp.sh", "run_mcp_with_db.sh", "requirements.txt", "arena.yaml"):
        if (ROOT / name).exists():
            files.append(name)
    return files

UPLOAD_FILES = _discover_upload_files()

# Skills directories to upload
SKILLS_DIR = ROOT / "skills"
SKILLS_OH_DIR = ROOT / "skills_openhands"

# Install script (no DB download — DB is uploaded separately)
INIT_SCRIPT = f"""#!/bin/bash
set -e
apt-get update -qq
apt-get install -y -qq zstd >/dev/null 2>&1
pip install --no-cache-dir openai pyyaml jinja2 >/dev/null 2>&1
mkdir -p /app/corpus
echo "[init] Deps installed, sandbox ready"
"""

# DB download script (used when uploading compressed DB from local)
DB_DECOMPRESS_SCRIPT = f"""#!/bin/bash
set -e
if [ -f /tmp/db.zst ] && [ ! -f "{DB_PATH}" ]; then
    echo "[db] Decompressing corpus DB..."
    zstd -d /tmp/db.zst -o "{DB_PATH}" -f
    rm -f /tmp/db.zst
    echo "[db] DB ready at {DB_PATH}"
elif [ -f "{DB_PATH}" ]; then
    echo "[db] DB already exists"
else
    echo "[db] ERROR: No DB source found"
    exit 1
fi
"""

# Local compressed DB path (downloaded separately)
LOCAL_DB_ZST = ROOT / "data" / "officeqa_slim_v2.sqlite3.zst"
LOCAL_DB = ROOT / "data" / "officeqa_slim_v2.sqlite3"


# ── Daytona client ─────────────────────────────────────────────────

def _get_client() -> Daytona:
    api_key = os.environ.get("DAYTONA_API_KEY", "")
    if not api_key:
        print("ERROR: Set DAYTONA_API_KEY env var")
        print("Get one at: https://app.daytona.io/dashboard/keys")
        sys.exit(1)
    return Daytona(DaytonaConfig(
        api_key=api_key,
        target=os.environ.get("DAYTONA_TARGET", "us"),
    ))


def _sandbox_env_vars() -> dict[str, str]:
    """Environment variables to inject into every sandbox."""
    env = {
        "OFFICEQA_SQLITE_DB": DB_PATH,
        "PYTHONUNBUFFERED": "1",
    }
    # Pass through API keys and telemetry
    for key in ("OPENROUTER_API_KEY", "LLM_API_KEY", "TELEMETRY_URL"):
        val = os.environ.get(key, "")
        if val:
            env[key] = val
    # Default telemetry to DB droplet if not set
    if "TELEMETRY_URL" not in env:
        env["TELEMETRY_URL"] = "http://147.182.206.223:8080"
    return env


# ── Sandbox lifecycle ──────────────────────────────────────────────

def create_snapshot(client: Daytona):
    """Create a snapshot with deps + corpus DB baked in (no code).

    Code is uploaded fresh at sandbox creation so you never need to rebuild
    the snapshot when changing server/, src/, prompts/, or skills/.
    Only rebuild when the DB or Python deps change.
    """
    from daytona import Image

    print(f"Building snapshot '{SNAPSHOT_NAME}' (deps + DB only, no code)...")
    print(f"Resources: {SANDBOX_RESOURCES}")

    # Build image: base + system deps + pip deps + DB
    image = (
        Image.base(DOCKER_IMAGE)
        .run_commands(
            "apt-get update -qq",
            "apt-get install -y -qq --no-install-recommends zstd",
            "rm -rf /var/lib/apt/lists/*",
            "mkdir -p /app/corpus /opt/officeqa/server /opt/officeqa/src "
            "/opt/officeqa/data/reference /opt/officeqa/prompts /opt/officeqa/skills "
            "/opt/officeqa/skills_openhands",
        )
        .pip_install(["openai", "pyyaml", "jinja2", "msgpack", "zstandard", "requests",
                     "openhands-sdk", "openhands-tools"])
        .workdir("/opt/officeqa")
        .env({"OFFICEQA_SQLITE_DB": DB_PATH, "PYTHONUNBUFFERED": "1"})
    )

    # Bake in the corpus DB (the heavy part — only reason to rebuild)
    if LOCAL_DB_ZST.exists() and not LOCAL_DB_ZST.is_symlink():
        print(f"Baking in corpus DB ({LOCAL_DB_ZST.stat().st_size // 1048576}MB compressed)...")
        image = image.add_local_file(str(LOCAL_DB_ZST), "/tmp/db.zst")
        image = image.run_commands(
            f"zstd -d /tmp/db.zst -o {DB_PATH} -f",
            "rm -f /tmp/db.zst",
        )
    elif LOCAL_DB.exists() and not LOCAL_DB.is_symlink():
        print(f"Baking in corpus DB ({LOCAL_DB.stat().st_size // 1048576}MB)...")
        image = image.add_local_file(str(LOCAL_DB), DB_PATH)
    else:
        # Download from hosted URL during image build
        print(f"Downloading corpus DB from {DB_URL} during image build...")
        image = image.run_commands(
            "apt-get update -qq && apt-get install -y -qq --no-install-recommends curl",
            f"curl -fsSL {DB_URL} | zstd -d -o {DB_PATH} -f",
            "rm -rf /var/lib/apt/lists/*",
        )

    # Bake in reference data (small, rarely changes)
    for relpath in UPLOAD_FILES:
        if relpath.startswith("data/reference/"):
            local = ROOT / relpath
            if local.exists():
                image = image.add_local_file(str(local), f"/opt/officeqa/{relpath}")

    print("Uploading and building image (this takes a while the first time)...\n")
    client.snapshot.create(
        CreateSnapshotParams(
            name=SNAPSHOT_NAME,
            image=image,
            resources=SANDBOX_RESOURCES,
        ),
        on_logs=lambda chunk: print(chunk, end=""),
    )
    print(f"\nSnapshot '{SNAPSHOT_NAME}' created successfully.")
    print("Code is uploaded fresh at sandbox creation — no rebuild needed for code changes.")


def create_sandbox(client: Daytona):
    """Create a sandbox from snapshot, then upload latest code.

    Snapshot has: python, deps, DB, reference data (heavy, rarely changes).
    Code is uploaded fresh: server/, src/, prompts/, skills/ (light, changes often).
    """
    env = _sandbox_env_vars()

    print("Creating sandbox from snapshot...")
    sandbox = client.create(
        CreateSandboxFromSnapshotParams(
            snapshot=SNAPSHOT_NAME,
            language="python",
            env_vars=env,
        ),
        timeout=120,
    )
    print(f"Sandbox created (id: {sandbox.id}, cpu={sandbox.cpu}, mem={sandbox.memory}GB, disk={sandbox.disk}GB)")

    # Upload latest code (skips data/reference/ — already in snapshot)
    print("Uploading latest code...")
    for relpath in UPLOAD_FILES:
        if relpath.startswith("data/reference/"):
            continue
        local = ROOT / relpath
        if not local.exists():
            continue
        sandbox.fs.upload_file(local.read_bytes(), f"/opt/officeqa/{relpath}")

    # Upload skills/*.md
    if SKILLS_DIR.is_dir():
        for md in sorted(SKILLS_DIR.glob("*.md")):
            sandbox.fs.upload_file(md.read_bytes(), f"/opt/officeqa/skills/{md.name}")

    # Upload skills_openhands/ (OpenHands SDK skill format: subdir/SKILL.md)
    if SKILLS_OH_DIR.is_dir():
        for skill_dir in sorted(SKILLS_OH_DIR.iterdir()):
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    sandbox.fs.upload_file(
                        skill_file.read_bytes(),
                        f"/opt/officeqa/skills_openhands/{skill_dir.name}/SKILL.md",
                    )

    # Upload sub-agent definitions for DelegateTool
    agents_dir = ROOT / ".openhands" / "agents"
    if agents_dir.is_dir():
        for md in sorted(agents_dir.glob("*.md")):
            for base in ("/opt/officeqa/.openhands/agents", "/workspace/.openhands/agents"):
                sandbox.process.exec(f"mkdir -p {base}", timeout=5)
                sandbox.fs.upload_file(md.read_bytes(), f"{base}/{md.name}")

    # Upload overrides/ (sitecustomize.py for terminal restriction)
    overrides_dir = ROOT / "overrides"
    if overrides_dir.is_dir():
        sandbox.process.exec("mkdir -p /opt/officeqa/overrides", timeout=5)
        for f in sorted(overrides_dir.glob("*.py")):
            sandbox.fs.upload_file(f.read_bytes(), f"/opt/officeqa/overrides/{f.name}")

    # Fix script permissions
    sandbox.process.exec("chmod +x /opt/officeqa/run_mcp.sh /opt/officeqa/run_mcp_with_db.sh", timeout=5)

    print("Sandbox ready")
    return sandbox


def _upload_runner(sandbox) -> None:
    """Upload the OpenHands SDK runner script (same as arena uses)."""
    runner_src = Path("/opt/homebrew/lib/python3.14/site-packages"
                      "/harbor/agents/installed/openhands_sdk_runner.py")
    if not runner_src.exists():
        # Fallback: find it
        import importlib
        mod = importlib.import_module("harbor.agents.installed.openhands_sdk")
        runner_src = Path(mod.__file__).parent / "openhands_sdk_runner.py"
    sandbox.fs.upload_file(runner_src.read_bytes(), "/opt/officeqa/run_agent.py")


def _render_instruction(question: str, template: str = "system.j2") -> str:
    """Render a prompt template with the question."""
    import jinja2
    tmpl_path = ROOT / "prompts" / template
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(tmpl_path.parent)))
    tmpl = env.get_template(tmpl_path.name)
    return tmpl.render(instruction=question)


def run_question_in_sandbox(
    client: Daytona,
    sandbox,
    uid: str,
    question: str,
    gold: str = "",
    model: str = "openrouter/minimax/minimax-m2.5",
    max_iterations: int = 15,
    use_orchestrator: bool = False,
) -> dict:
    """Run a single question in a sandbox.

    If use_orchestrator=True, uses src/orchestrator.py (staged pipeline).
    Otherwise uses run_agent.py (flat OpenHands SDK loop, same as arena submit).
    """
    # Upload the runner script
    _upload_runner(sandbox)

    # MCP server config — exactly as arena.yaml specifies
    mcp_config = json.dumps([{
        "name": "officeqa-arena",
        "transport": "stdio",
        "command": "/opt/officeqa/run_mcp.sh",
    }])

    # Build the env vars
    env = _sandbox_env_vars()
    telemetry_url = env.get("TELEMETRY_URL", "")
    run_env = " ".join([
        f'LLM_MODEL="{model}"',
        f'LLM_API_KEY="{env.get("OPENROUTER_API_KEY", env.get("LLM_API_KEY", ""))}"',
        'LLM_TEMPERATURE="0.0"',
        f'MAX_ITERATIONS="{max_iterations}"',
        f"MCP_SERVERS_JSON='{mcp_config}'",
        f'OFFICEQA_SQLITE_DB="{DB_PATH}"',
        'PYTHONUNBUFFERED="1"',
        f'PROMPTS_DIR="/opt/officeqa/prompts"',
    ])

    if use_orchestrator:
        # Orchestrator mode: raw question, custom system prompts per phase
        escaped = question.replace("'", "'\\''")
        cmd = (
            f"cd /opt/officeqa && {run_env} python3 src/orchestrator.py "
            f"--instruction='{escaped}' "
            f"--logs-dir=/tmp/logs "
            f"--trajectory-path=/tmp/logs/trajectory.json"
        )
    else:
        # Legacy mode: OpenHands SDK flat loop with system.j2
        instruction = _render_instruction(question)
        skill_paths = "/opt/officeqa/skills_openhands"
        run_env += f' LOAD_SKILLS="1" SKILL_PATHS="{skill_paths}"'
        escaped = instruction.replace("'", "'\\''")
        cmd = (
            f"cd /opt/officeqa && {run_env} python3 run_agent.py "
            f"--instruction='{escaped}' "
            f"--logs-dir=/tmp/logs "
            f"--trajectory-path=/tmp/logs/trajectory.json"
        )

    print(f"  [{uid}] Running via OpenHands SDK (model={model}, max_iter={max_iterations})...")
    resp = sandbox.process.exec(cmd, timeout=600)
    print(resp.result[-1000:] if len(resp.result) > 1000 else resp.result)

    # Read the answer from /app/answer.txt (same as arena)
    try:
        answer_bytes = sandbox.fs.download_file("/app/answer.txt")
        predicted = answer_bytes.decode("utf-8").strip()
    except Exception:
        predicted = ""

    # Read trajectory for metadata
    trajectory = {}
    try:
        traj_bytes = sandbox.fs.download_file("/tmp/logs/trajectory.json")
        trajectory = json.loads(traj_bytes)
    except Exception:
        pass

    result = {
        "uid": uid,
        "question": question,
        "gold": gold,
        "predicted": predicted,
        "iterations": len(trajectory.get("steps", [])),
        "cost_usd": trajectory.get("final_metrics", {}).get("total_cost_usd", 0),
        "exit_code": resp.exit_code,
    }

    # Save full trajectory locally for analysis
    if trajectory:
        traj_dir = ROOT / "results" / "trajectories"
        traj_dir.mkdir(parents=True, exist_ok=True)
        traj_file = traj_dir / f"{uid}.json"
        traj_file.write_text(json.dumps(trajectory, indent=2, default=str))
        result["trajectory_path"] = str(traj_file)

    # Clean up answer file for next question
    sandbox.process.exec("rm -f /app/answer.txt", timeout=5)

    return result


# ── Plan mode ──────────────────────────────────────────────────────

def plan_question_in_sandbox(
    client: Daytona,
    sandbox,
    uid: str,
    question: str,
    gold: str = "",
    model: str = "openrouter/minimax/minimax-m2.5",
) -> dict:
    """Run a single question in plan-only mode (1 iteration, no tool execution)."""
    _upload_runner(sandbox)

    # Use plan-only prompt — model sees tool list but is told to only output JSON
    instruction = _render_instruction(question, template="plan_only.j2")

    # MCP server config — same as real runs so model sees the real tool list
    mcp_config = json.dumps([{
        "name": "officeqa-arena",
        "transport": "stdio",
        "command": "/opt/officeqa/run_mcp.sh",
    }])

    skill_paths = "/opt/officeqa/skills_openhands"
    env = _sandbox_env_vars()
    run_env = " ".join([
        f'LLM_MODEL="{model}"',
        f'LLM_API_KEY="{env.get("OPENROUTER_API_KEY", env.get("LLM_API_KEY", ""))}"',
        'LLM_TEMPERATURE="0.0"',
        f'MAX_ITERATIONS="1"',
        'LOAD_SKILLS="1"',
        f'SKILL_PATHS="{skill_paths}"',
        f"MCP_SERVERS_JSON='{mcp_config}'",
        f'OFFICEQA_SQLITE_DB="{DB_PATH}"',
        'PYTHONUNBUFFERED="1"',
    ])

    escaped = instruction.replace("'", "'\\''")
    cmd = (
        f"cd /opt/officeqa && {run_env} python3 run_agent.py "
        f"--instruction='{escaped}' "
        f"--logs-dir=/tmp/logs "
        f"--trajectory-path=/tmp/logs/trajectory.json"
    )

    print(f"  [{uid}] Planning (1 iteration)...")
    resp = sandbox.process.exec(cmd, timeout=120)

    # Extract plan from trajectory
    trajectory = {}
    plan_json = {}
    try:
        traj_bytes = sandbox.fs.download_file("/tmp/logs/trajectory.json")
        trajectory = json.loads(traj_bytes)
        # The model's first response should contain the JSON plan
        for step in trajectory.get("steps", []):
            # Look for the assistant's text output (not tool calls)
            for obs in step.get("observations", []):
                content = obs.get("content", "")
                if content and "{" in content:
                    # Try to extract JSON from the response
                    start = content.find("{")
                    end = content.rfind("}") + 1
                    if start >= 0 and end > start:
                        try:
                            plan_json = json.loads(content[start:end])
                        except json.JSONDecodeError:
                            pass
            # Also check action output
            action = step.get("action", {})
            if action.get("action") == "message":
                content = action.get("args", {}).get("content", "")
                if content and "{" in content:
                    start = content.find("{")
                    end = content.rfind("}") + 1
                    if start >= 0 and end > start:
                        try:
                            plan_json = json.loads(content[start:end])
                        except json.JSONDecodeError:
                            pass
    except Exception:
        pass

    # Also try reading the raw output
    if not plan_json:
        output = resp.result
        if output and "{" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    plan_json = json.loads(output[start:end])
                except json.JSONDecodeError:
                    pass

    result = {
        "uid": uid,
        "question": question,
        "gold": gold,
        "plan": plan_json,
        "raw_output": resp.result[-2000:] if resp.result else "",
        "exit_code": resp.exit_code,
        "cost_usd": trajectory.get("final_metrics", {}).get("total_cost_usd", 0),
    }

    # Save trajectory
    if trajectory:
        traj_dir = ROOT / "results" / "trajectories" / "plans"
        traj_dir.mkdir(parents=True, exist_ok=True)
        (traj_dir / f"{uid}.json").write_text(json.dumps(trajectory, indent=2, default=str))

    # Clean up for next question
    sandbox.process.exec("rm -f /app/answer.txt /tmp/logs/trajectory.json", timeout=5)

    return result


def run_plan_batch(
    cases: list[dict],
    workers: int = 5,
    model: str = "openrouter/minimax/minimax-m2.5",
    output_path: str = "",
):
    """Run plan-only phase across N parallel Daytona sandboxes."""
    client = _get_client()

    if not output_path:
        output_path = str(ROOT / "results" / "phase1_plans.jsonl")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"\nPhase 1 Plan: {len(cases)} cases, {workers} parallel sandboxes")
    print(f"Output: {out}\n")

    # Pre-create sandboxes
    print(f"Creating {workers} sandboxes...")
    sandboxes = []
    for i in range(workers):
        print(f"\n--- Sandbox {i+1}/{workers} ---")
        sb = create_sandbox(client)
        sandboxes.append(sb)
    print(f"\nAll {workers} sandboxes ready.\n")

    results = []
    lock = __import__("threading").Lock()

    def _run_one(sandbox, case):
        t0 = time.time()
        try:
            result = plan_question_in_sandbox(
                client, sandbox,
                uid=case["uid"],
                question=case["question"],
                gold=case.get("gold", ""),
                model=model,
            )
            result["elapsed_s"] = round(time.time() - t0, 2)
            return result
        except Exception as e:
            return {
                "uid": case["uid"],
                "error": str(e),
                "elapsed_s": round(time.time() - t0, 2),
            }

    # Sequential per sandbox, parallel across sandboxes
    # Split cases into per-sandbox queues for sequential execution
    sandbox_queues: list[list[dict]] = [[] for _ in range(workers)]
    for i, case in enumerate(cases):
        sandbox_queues[i % workers].append(case)

    def _run_queue(sb_idx):
        sb = sandboxes[sb_idx]
        queue = sandbox_queues[sb_idx]
        local_results = []
        for case in queue:
            result = _run_one(sb, case)
            local_results.append(result)
            with lock:
                results.append(result)
                with open(out, "a") as f:
                    f.write(json.dumps(result, default=str) + "\n")
                done = len(results)
                uid = result.get("uid", "?")
                feasibility = result.get("plan", {}).get("feasibility", "?")
                comp = result.get("plan", {}).get("computation", {}).get("type", "?")
                err = result.get("error", "")
                if err:
                    print(f"  [{done}/{len(cases)}] {uid}: ERROR — {err[:60]}")
                else:
                    print(f"  [{done}/{len(cases)}] {uid}: {feasibility:10s} | {comp}")
        return local_results

    # Clear output file
    with open(out, "w") as f:
        pass

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_run_queue, i) for i in range(workers)]
        for fut in as_completed(futures):
            fut.result()  # raise any exceptions

    # Summary
    print(f"\n{'='*60}")
    print(f"PHASE 1 PLAN COMPLETE ({len(results)} questions)")
    print(f"{'='*60}")

    feasibility = {}
    for r in results:
        f = r.get("plan", {}).get("feasibility", "error" if r.get("error") else "no_plan")
        feasibility[f] = feasibility.get(f, 0) + 1
    print("\nFeasibility:")
    for f, c in sorted(feasibility.items(), key=lambda x: -x[1]):
        print(f"  {f:15s}: {c:3d} ({100*c/len(results):.0f}%)")

    comp_types = {}
    for r in results:
        ct = r.get("plan", {}).get("computation", {}).get("type", "?")
        comp_types[ct] = comp_types.get(ct, 0) + 1
    print("\nComputation types:")
    for ct, c in sorted(comp_types.items(), key=lambda x: -x[1]):
        print(f"  {ct:25s}: {c:3d}")

    all_factors = {}
    for r in results:
        for f in r.get("plan", {}).get("difficulty_factors", []):
            all_factors[f] = all_factors.get(f, 0) + 1
    print("\nDifficulty factors:")
    for f, c in sorted(all_factors.items(), key=lambda x: -x[1]):
        print(f"  {f:30s}: {c:3d}")

    all_funcs = {}
    for r in results:
        for f in r.get("plan", {}).get("computation", {}).get("functions_needed", []):
            all_funcs[f] = all_funcs.get(f, 0) + 1
    print("\nCompute functions needed:")
    for f, c in sorted(all_funcs.items(), key=lambda x: -x[1]):
        print(f"  {f:25s}: {c:3d}")

    total_cost = sum(r.get("cost_usd", 0) for r in results)
    print(f"\nTotal cost: ${total_cost:.4f}")
    print(f"Results: {out}")

    # Cleanup
    print(f"\nCleaning up {workers} sandboxes...")
    for sb in sandboxes:
        try:
            client.delete(sb)
        except Exception:
            pass


# ── Batch mode ─────────────────────────────────────────────────────

def load_cases(path: str) -> list[dict]:
    """Load cases from CSV."""
    cases = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cases.append({
                "uid": row.get("uid", ""),
                "question": row.get("question", ""),
                "gold": row.get("answer", row.get("expected_answer", "")),
            })
    return cases


def run_batch(
    cases: list[dict],
    workers: int = 2,
    model: str = "openrouter/minimax/minimax-m2.5",
    max_iterations: int = 15,
    output_path: str = "",
    use_orchestrator: bool = False,
):
    """Run cases across N parallel Daytona sandboxes."""
    client = _get_client()

    if not output_path:
        output_path = str(ROOT / "results" / "stages" / "daytona_batch.jsonl")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    mode = "orchestrator" if use_orchestrator else "flat"
    print(f"\nBatch run: {len(cases)} cases, {workers} sandboxes, mode={mode}")
    print(f"Output: {out}\n")

    # Pre-create sandboxes
    print(f"Creating {workers} sandboxes...")
    sandboxes = []
    for i in range(workers):
        print(f"\n--- Sandbox {i+1}/{workers} ---")
        sb = create_sandbox(client)
        sandboxes.append(sb)
    print(f"\nAll {workers} sandboxes ready.\n")

    results = []

    def _run_one(sandbox, case):
        t0 = time.time()
        try:
            result = run_question_in_sandbox(
                client, sandbox,
                uid=case["uid"],
                question=case["question"],
                gold=case.get("gold", ""),
                model=model,
                max_iterations=max_iterations,
                use_orchestrator=use_orchestrator,
            )
            result["elapsed_s"] = round(time.time() - t0, 2)
            return result
        except Exception as e:
            return {
                "uid": case["uid"],
                "question": case["question"],
                "error": str(e),
                "elapsed_s": round(time.time() - t0, 2),
            }

    # Round-robin cases across sandboxes
    with open(out, "w") as f:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for i, case in enumerate(cases):
                sb = sandboxes[i % workers]
                fut = executor.submit(_run_one, sb, case)
                futures[fut] = case

            done = 0
            for fut in as_completed(futures):
                done += 1
                case = futures[fut]
                result = fut.result()
                f.write(json.dumps(result, default=str) + "\n")
                f.flush()
                results.append(result)

                pred = result.get("predicted", result.get("error", "?"))
                print(f"  [{done}/{len(cases)}] {case['uid']} -> {pred}")

    # Cleanup
    print(f"\nCleaning up {workers} sandboxes...")
    for sb in sandboxes:
        try:
            client.delete(sb)
        except Exception:
            pass

    correct = sum(1 for r in results if r.get("is_correct"))
    print(f"\nBatch complete: {len(results)} tasks, {correct} correct")
    print(f"Results: {out}")


# ── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Daytona sandbox manager for OfficeQA Arena")
    sub = parser.add_subparsers(dest="command", required=True)

    # snapshot
    sub.add_parser("snapshot", help="Create a reusable Daytona snapshot (one-time)")

    # create
    sub.add_parser("create", help="Create a sandbox (for debugging)")

    # run (single question)
    run_p = sub.add_parser("run", help="Run a single question in a sandbox")
    run_p.add_argument("--uid", required=True)
    run_p.add_argument("--question", required=True)
    run_p.add_argument("--gold", default="")
    run_p.add_argument("--model", default="openrouter/minimax/minimax-m2.5")
    run_p.add_argument("--max-iterations", type=int, default=15)
    run_p.add_argument("--orchestrator", action="store_true", help="Use staged orchestrator")

    # plan (phase 1: plan-only across all questions)
    plan_p = sub.add_parser("plan", help="Phase 1: plan-only (no tool execution)")
    plan_p.add_argument("--cases", default=str(ROOT / "data" / "officeqa_full.csv"))
    plan_p.add_argument("--workers", type=int, default=5)
    plan_p.add_argument("--model", default="openrouter/minimax/minimax-m2.5")
    plan_p.add_argument("--output", default="")
    plan_p.add_argument("--subset", default="", help="'arena' or comma-separated UIDs")
    plan_p.add_argument("--limit", type=int, default=0)

    # batch
    batch_p = sub.add_parser("batch", help="Batch replay across parallel sandboxes")
    batch_p.add_argument("--cases", required=True, help="CSV/JSONL with questions")
    batch_p.add_argument("--workers", type=int, default=2, help="Number of parallel sandboxes")
    batch_p.add_argument("--model", default="openrouter/minimax/minimax-m2.5")
    batch_p.add_argument("--max-iterations", type=int, default=15)
    batch_p.add_argument("--output", default="")
    batch_p.add_argument("--subset", default="", help="'arena' or comma-separated UIDs")
    batch_p.add_argument("--limit", type=int, default=0)
    batch_p.add_argument("--orchestrator", action="store_true", help="Use staged orchestrator")

    args = parser.parse_args()

    if args.command == "snapshot":
        client = _get_client()
        create_snapshot(client)

    elif args.command == "create":
        client = _get_client()
        sb = create_sandbox(client)
        print(f"\nSandbox ready! ID: {sb.id}")
        print("Use daytona dashboard or client.delete(sandbox) to clean up.")

    elif args.command == "run":
        client = _get_client()
        sb = create_sandbox(client)
        try:
            result = run_question_in_sandbox(
                client, sb,
                uid=args.uid, question=args.question, gold=args.gold,
                model=args.model, max_iterations=args.max_iterations,
                use_orchestrator=args.orchestrator,
            )
            print(f"\nResult: {json.dumps(result, indent=2, default=str)}")
        finally:
            client.delete(sb)

    elif args.command == "plan":
        cases = load_cases(args.cases)
        if args.subset:
            uids = {u.strip().upper() for u in args.subset.split(",")}
            cases = [c for c in cases if c["uid"].upper() in uids]
        if args.limit > 0:
            cases = cases[:args.limit]
        run_plan_batch(
            cases, workers=args.workers, model=args.model,
            output_path=args.output,
        )

    elif args.command == "batch":
        cases = load_cases(args.cases)
        if args.subset == "arena":
            ARENA_UIDS = {
                "UID0004", "UID0023", "UID0030", "UID0033", "UID0041", "UID0048",
                "UID0057", "UID0097", "UID0111", "UID0127", "UID0136", "UID0167",
                "UID0192", "UID0194", "UID0199", "UID0217", "UID0220", "UID0230",
                "UID0241", "UID0246",
            }
            cases = [c for c in cases if c["uid"] in ARENA_UIDS]
        elif args.subset:
            uids = {u.strip().upper() for u in args.subset.split(",")}
            cases = [c for c in cases if c["uid"].upper() in uids]
        if args.limit > 0:
            cases = cases[:args.limit]

        run_batch(
            cases, workers=args.workers, model=args.model,
            max_iterations=args.max_iterations, output_path=args.output,
            use_orchestrator=args.orchestrator,
        )


if __name__ == "__main__":
    main()
