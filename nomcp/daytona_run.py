#!/usr/bin/env python3
"""Daytona-based runner for nomcp OfficeQA Arena.

Creates a Daytona sandbox with DB pre-decompressed, uploads latest code,
and runs run_all.py inside the sandbox with concurrency.

Usage:
  # One-time: create snapshot (bakes in DB + Python deps)
  python3 nomcp/daytona_run.py snapshot

  # Run all 246 questions (default concurrency=8)
  python3 nomcp/daytona_run.py run

  # Run specific UIDs
  python3 nomcp/daytona_run.py run --uids UID0001,UID0002,UID0003

  # Run with custom concurrency
  python3 nomcp/daytona_run.py run --concurrency 4

  # Create sandbox for manual debugging (ssh in)
  python3 nomcp/daytona_run.py create

Env vars:
  DAYTONA_API_KEY      — required, from https://app.daytona.io/dashboard/keys
  OPENROUTER_API_KEY   — required for LLM calls
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Load .env
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        for line in _env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

try:
    from daytona import (
        Daytona,
        DaytonaConfig,
        CreateSandboxFromSnapshotParams,
        CreateSnapshotParams,
        Resources,
    )
except ImportError:
    print("ERROR: daytona SDK not installed. Run: pip install daytona")
    sys.exit(1)

# ── Paths ──────────────────────────────────────────────────────────────
NOMCP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = NOMCP_DIR.parent
QUESTIONS_CSV = PROJECT_ROOT / "data" / "officeqa_full.csv"

# ── Config ─────────────────────────────────────────────────────────────
SNAPSHOT_NAME = "officeqa-nomcp"
SANDBOX_RESOURCES = Resources(cpu=3, memory=3, disk=10)  # 3 sandboxes fit in Tier 1 (10 CPU, 10GB RAM, 30GB disk)
DB_URL = "http://147.182.206.223:9090/officeqa_v3.sqlite3.zst"
# solve.py checks /tmp/officeqa.db first (DB_PATH), so we decompress there.
DB_RUNTIME_PATH = "/tmp/officeqa.db"
# Compressed DB bundled in skills/
LOCAL_DB_GZ = NOMCP_DIR / "skills" / "officeqa_optimal.sqlite3.gz"
LOCAL_DB_ZST = PROJECT_ROOT / "officeqa_optimal.sqlite3.zst"


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


def _load_api_key() -> str:
    """Get OPENROUTER_API_KEY from env, .env, or arena.yaml (fallback)."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key
    # Try arena.yaml
    import yaml
    for yaml_path in (NOMCP_DIR / "arena.yaml", PROJECT_ROOT / "arena.yaml"):
        if yaml_path.exists():
            try:
                cfg = yaml.safe_load(yaml_path.read_text())
                key = cfg.get("agent", {}).get("env", {}).get("OPENROUTER_API_KEY", "")
                if key:
                    return key
            except Exception:
                pass
    return ""


def _sandbox_env() -> dict[str, str]:
    env = {"PYTHONUNBUFFERED": "1"}
    api_key = _load_api_key()
    if api_key:
        env["OPENROUTER_API_KEY"] = api_key
        env["LLM_API_KEY"] = api_key
    return env


# ── Snapshot ───────────────────────────────────────────────────────────

def cmd_snapshot():
    """Build snapshot: python:3.12-slim + deps + DB pre-decompressed."""
    from daytona import Image

    client = _get_client()
    print(f"Building snapshot '{SNAPSHOT_NAME}'...")

    image = (
        Image.debian_slim("3.12")
        .run_commands(
            "apt-get update -qq",
            "apt-get install -y -qq --no-install-recommends zstd sqlite3 curl bzip2 libxcb1 libgomp1",
            "rm -rf /var/lib/apt/lists/*",
            "mkdir -p /installed-agent /tmp /app/corpus /logs/agent",
        )
        .pip_install(["openai", "pyyaml", "jinja2", "requests", "msgpack", "zstandard"])
        # Install goose CLI
        .run_commands(
            "export CONFIGURE=false GOOSE_DISABLE_KEYRING=true && "
            "curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | bash",
            "ls -la /root/.local/bin/goose && /root/.local/bin/goose --version",
        )
        # Write goose config
        .run_commands(
            "mkdir -p /root/.config/goose",
            """cat > /root/.config/goose/config.yaml << 'GOOSECFG'
GOOSE_MODEL: ${GOOSE_MODEL}
GOOSE_PROVIDER: ${GOOSE_PROVIDER}
extensions:
  developer:
    bundled: true
    display_name: Developer
    enabled: true
    name: developer
    timeout: 300
    type: builtin
  todo:
    bundled: true
    display_name: Todo
    enabled: true
    name: todo
    type: platform
GOOSECFG""",
        )
        .workdir("/installed-agent")
        .env({
            "PYTHONUNBUFFERED": "1",
            "GOOSE_DISABLE_KEYRING": "true",
            "PATH": "/root/.local/bin:/usr/local/bin:/usr/bin:/bin",
        })
    )

    # Bake in the DB, pre-decompressed at /tmp/officeqa.db
    if LOCAL_DB_GZ.exists():
        print(f"Baking in DB from {LOCAL_DB_GZ} ({LOCAL_DB_GZ.stat().st_size // 1048576}MB gz)...")
        image = (
            image
            .add_local_file(str(LOCAL_DB_GZ), "/tmp/officeqa_optimal.sqlite3.gz")
            .run_commands(
                f"python3 -c \""
                f"import gzip,shutil;"
                f"f_in=gzip.open('/tmp/officeqa_optimal.sqlite3.gz','rb');"
                f"f_out=open('{DB_RUNTIME_PATH}','wb');"
                f"shutil.copyfileobj(f_in,f_out);"
                f"f_in.close();f_out.close()\"",
                "rm -f /tmp/officeqa_optimal.sqlite3.gz",
                f"echo DB ready: $(du -h {DB_RUNTIME_PATH})",
            )
        )
    elif LOCAL_DB_ZST.exists():
        print(f"Baking in DB from {LOCAL_DB_ZST} ({LOCAL_DB_ZST.stat().st_size // 1048576}MB zst)...")
        image = (
            image
            .add_local_file(str(LOCAL_DB_ZST), "/tmp/db.zst")
            .run_commands(
                f"zstd -d /tmp/db.zst -o {DB_RUNTIME_PATH} -f",
                "rm -f /tmp/db.zst",
            )
        )
    else:
        print(f"No local DB found — downloading from {DB_URL} during build...")
        image = image.run_commands(
            f"curl -fsSL {DB_URL} | zstd -d -o {DB_RUNTIME_PATH} -f",
        )

    # Bake in corpus .txt files (for raw grep fallback in solve.py)
    corpus_tar = Path("/tmp/corpus.tar.gz")
    corpus_dir = PROJECT_ROOT / "corpus"
    if corpus_tar.exists():
        print(f"Baking in corpus from {corpus_tar} ({corpus_tar.stat().st_size // 1048576}MB)...")
        image = (
            image
            .add_local_file(str(corpus_tar), "/tmp/corpus.tar.gz")
            .run_commands(
                "mkdir -p /app/corpus",
                "tar xzf /tmp/corpus.tar.gz -C /app/corpus",
                "rm -f /tmp/corpus.tar.gz",
                "echo Corpus ready: $(ls /app/corpus/*.txt | wc -l) files",
            )
        )
    elif corpus_dir.is_dir():
        # Compress on the fly
        print(f"Compressing and baking in corpus from {corpus_dir}...")
        import subprocess
        subprocess.run(["tar", "czf", "/tmp/corpus.tar.gz", "-C", str(corpus_dir), "."],
                       check=True)
        image = (
            image
            .add_local_file("/tmp/corpus.tar.gz", "/tmp/corpus.tar.gz")
            .run_commands(
                "mkdir -p /app/corpus",
                "tar xzf /tmp/corpus.tar.gz -C /app/corpus",
                "rm -f /tmp/corpus.tar.gz",
                "echo Corpus ready: $(ls /app/corpus/*.txt | wc -l) files",
            )
        )
    else:
        print("WARNING: No corpus found — raw grep fallback won't work")

    # Bake in CPI data (needed by solve.py)
    cpi_csv = NOMCP_DIR / "cpi_monthly.csv"
    if cpi_csv.exists():
        image = image.add_local_file(str(cpi_csv), "/installed-agent/cpi_monthly.csv")

    print("Building image (first time takes a few minutes)...\n")
    client.snapshot.create(
        CreateSnapshotParams(
            name=SNAPSHOT_NAME,
            image=image,
            resources=SANDBOX_RESOURCES,
        ),
        on_logs=lambda chunk: print(chunk, end=""),
    )
    print(f"\nSnapshot '{SNAPSHOT_NAME}' created.")
    print("DB is pre-decompressed at /tmp/officeqa.db — solve.py skips decompression.")


# ── Upload code ────────────────────────────────────────────────────────

def _upload_code(sandbox) -> None:
    """Upload latest nomcp/ code to /installed-agent/."""
    print("Uploading code...")
    uploaded = 0

    # Core files
    for name in ("solve.py", "run_all.py", "search.py", "build_index.py",
                 "load_context.py", "cpi_monthly.csv", "arena.yaml"):
        local = NOMCP_DIR / name
        if local.exists():
            sandbox.fs.upload_file(local.read_bytes(), f"/installed-agent/{name}")
            uploaded += 1

    # Prompts
    prompts_dir = NOMCP_DIR / "prompts"
    if prompts_dir.is_dir():
        sandbox.process.exec("mkdir -p /installed-agent/prompts", timeout=5)
        for f in prompts_dir.iterdir():
            if f.is_file():
                sandbox.fs.upload_file(f.read_bytes(), f"/installed-agent/prompts/{f.name}")
                uploaded += 1

    # Skills (only .md files — skip the .gz DB and .py files already uploaded)
    skills_dir = NOMCP_DIR / "skills"
    if skills_dir.is_dir():
        sandbox.process.exec("mkdir -p /installed-agent/skills", timeout=5)
        for f in skills_dir.iterdir():
            if f.is_file() and f.suffix == ".md":
                sandbox.fs.upload_file(f.read_bytes(), f"/installed-agent/skills/{f.name}")
                uploaded += 1

    # Questions CSV
    if QUESTIONS_CSV.exists():
        sandbox.process.exec("mkdir -p /installed-agent/data", timeout=5)
        sandbox.fs.upload_file(QUESTIONS_CSV.read_bytes(), "/installed-agent/data/officeqa_full.csv")
        uploaded += 1

    print(f"Uploaded {uploaded} files.")


# ── Create sandbox ─────────────────────────────────────────────────────

def _create_sandbox(client: Daytona):
    """Create sandbox from snapshot and upload code."""
    env = _sandbox_env()
    print(f"Creating sandbox from snapshot '{SNAPSHOT_NAME}'...")
    sandbox = client.create(
        CreateSandboxFromSnapshotParams(
            snapshot=SNAPSHOT_NAME,
            language="python",
            env_vars=env,
        ),
        timeout=120,
    )
    print(f"Sandbox ready (id: {sandbox.id})")

    _upload_code(sandbox)

    # Verify DB is present
    check = sandbox.process.exec(
        f"python3 -c \"import os; print(os.path.getsize('{DB_RUNTIME_PATH}'))\" 2>&1",
        timeout=10,
    )
    db_size = check.result.strip()
    try:
        size_mb = int(db_size) // (1024 * 1024)
        print(f"DB verified: {size_mb}MB at {DB_RUNTIME_PATH}")
    except ValueError:
        print(f"WARNING: DB check returned: {db_size}")
        print("Attempting to decompress from skills/...")
        sandbox.fs.upload_file(LOCAL_DB_GZ.read_bytes(), "/tmp/officeqa_optimal.sqlite3.gz")
        sandbox.process.exec(
            f"python3 -c \""
            f"import gzip,shutil;"
            f"f_in=gzip.open('/tmp/officeqa_optimal.sqlite3.gz','rb');"
            f"f_out=open('{DB_RUNTIME_PATH}','wb');"
            f"shutil.copyfileobj(f_in,f_out);"
            f"f_in.close();f_out.close()\"",
            timeout=120,
        )

    return sandbox


# ── Goose runner (mimics arena test) ───────────────────────────────────

def _build_recipe(system_prompt: str, question: str) -> str:
    """Build a goose recipe YAML with proper escaping."""
    import yaml
    recipe = {
        "version": "1.0.0",
        "title": "harbor-task",
        "description": "harbor task recipe",
        "instructions": system_prompt,
        "prompt": question,
        "extensions": [
            {
                "bundled": True,
                "display_name": "Developer",
                "enabled": True,
                "name": "developer",
                "timeout": 300,
                "type": "builtin",
            }
        ],
    }
    return yaml.dump(recipe, default_flow_style=False, allow_unicode=True)


def _run_goose_question(sandbox, uid: str, question: str, expected: str,
                        difficulty: str, api_key: str, max_turns: int) -> dict:
    """Run a single question through the real goose CLI, mimicking arena test."""
    import jinja2
    start = time.time()

    # Render system prompt
    tmpl_path = NOMCP_DIR / "prompts" / "system.j2"
    template = jinja2.Template(tmpl_path.read_text())
    system_prompt = template.render(instruction=question)

    # Write recipe YAML (use Python yaml serializer for proper escaping)
    recipe_yaml = _build_recipe(system_prompt, question)
    # Upload as file to avoid shell escaping issues
    sandbox.fs.upload_file(recipe_yaml.encode(), f"/tmp/recipe_{uid}.yaml")

    # Clear previous answer
    sandbox.process.exec("rm -f /app/answer.txt", timeout=5)

    # Run goose
    cmd = (
        f"export PATH=/root/.local/bin:$PATH && "
        f"export GOOSE_MODEL=minimax/minimax-m2.5 && "
        f"export GOOSE_PROVIDER=openrouter && "
        f"export OPENROUTER_API_KEY='{api_key}' && "
        f"export GOOSE_DISABLE_KEYRING=true && "
        f"rm -f /app/answer.txt && "
        f"goose run --recipe /tmp/recipe_{uid}.yaml "
        f"--max-turns {max_turns} "
        f"2>&1; echo GOOSE_EXIT=$?"
    )

    try:
        result = sandbox.process.exec(cmd, timeout=300)
        goose_out = result.result[-500:] if result.result else ""
        print(f"  [{uid}] goose done: ...{goose_out[-200:]}", file=sys.stderr)
    except Exception as e:
        print(f"  [{uid}] goose error: {e}", file=sys.stderr)

    # Read answer
    answer = None
    try:
        ans_result = sandbox.process.exec(
            "cat /app/answer.txt 2>/dev/null || echo ''", timeout=5
        )
        raw = ans_result.result.strip()
        if raw:
            answer = raw
    except Exception:
        pass

    elapsed = time.time() - start

    # Score
    import re
    correct = False
    if answer and expected:
        pred_clean = re.sub(r"[,%$\s]", "", answer.replace("−", "-").strip().rstrip("%"))
        exp_clean = re.sub(r"[,%$\s]", "", expected.replace("−", "-").strip().rstrip("%"))
        try:
            pred_val = float(pred_clean)
            exp_val = float(exp_clean)
            correct = abs(pred_val - exp_val) / abs(exp_val) <= 0.01 if exp_val != 0 else abs(pred_val) < 0.01
        except (ValueError, TypeError):
            correct = answer.strip().lower() == expected.strip().lower()

    status = "PASS" if correct else "FAIL"
    print(f"  [{uid}] {status} | answer={answer} | expected={expected} | {elapsed:.0f}s",
          file=sys.stderr)

    return {
        "uid": uid, "expected": expected, "answer": answer,
        "correct": correct, "elapsed_s": round(elapsed, 1),
        "difficulty": difficulty, "mode": "goose",
    }


# ── Commands ───────────────────────────────────────────────────────────

def cmd_create():
    """Create a sandbox for manual debugging."""
    client = _get_client()
    sandbox = _create_sandbox(client)
    print(f"\nSandbox ID: {sandbox.id}")
    print(f"SSH in with: daytona ssh {sandbox.id}")
    print(f"Run solve.py: daytona exec {sandbox.id} -- python3 /installed-agent/solve.py \"your question\"")
    return sandbox


def _run_on_sandbox(client, uid_chunk: list[str], chunk_idx: int,
                     concurrency: int, api_key: str) -> Path | None:
    """Create a sandbox, run a chunk of UIDs, download results."""
    tag = f"[sandbox-{chunk_idx}]"
    print(f"{tag} Creating sandbox for {len(uid_chunk)} questions...")
    sandbox = _create_sandbox(client)

    uids_str = ",".join(uid_chunk)
    cases_path = "/installed-agent/data/officeqa_full.csv"
    output_file = f"/installed-agent/results_s{chunk_idx}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"

    cmd = (
        f"cd /installed-agent && "
        f"OPENROUTER_API_KEY='{api_key}' "
        f"python3 run_all.py "
        f"--corpus /app/corpus "
        f"--cases {cases_path} "
        f"--concurrency {concurrency} "
        f"--skip-index "
        f"--output {output_file} "
        f"--uids {uids_str}"
    )

    print(f"{tag} Running {len(uid_chunk)} questions (concurrency={concurrency})...")
    estimated_timeout = max(600, (len(uid_chunk) * 180) // concurrency)
    try:
        result = sandbox.process.exec(cmd, timeout=estimated_timeout)
        # Print last few lines (summary)
        lines = result.result.strip().splitlines()
        for line in lines[-10:]:
            print(f"{tag} {line}")
    except Exception as e:
        print(f"{tag} Execution error: {e}")

    # Download results
    local_output = NOMCP_DIR / Path(output_file).name
    try:
        results_bytes = sandbox.fs.download_file(output_file)
        local_output.write_bytes(results_bytes)
        print(f"{tag} Results saved: {local_output}")
        return local_output
    except Exception as e:
        print(f"{tag} Could not download: {e}")
        print(f"{tag} Manual: daytona exec {sandbox.id} -- cat {output_file}")
        return None


def cmd_run(args):
    """Create sandbox(es) and run questions."""
    import csv
    from concurrent.futures import ThreadPoolExecutor, as_completed

    client = _get_client()
    api_key = _load_api_key()
    num_sandboxes = args.sandboxes

    # Load UIDs
    if args.uids:
        all_uids = [u.strip() for u in args.uids.split(",")]
    else:
        with open(QUESTIONS_CSV) as f:
            reader = csv.DictReader(f)
            all_uids = [row["uid"] for row in reader]
        if args.n:
            all_uids = all_uids[:args.n]

    print(f"Running {len(all_uids)} questions across {num_sandboxes} sandbox(es)")
    print(f"Concurrency per sandbox: {args.concurrency}")
    print(f"{'='*60}\n")

    if num_sandboxes == 1:
        # Single sandbox — simple path
        result_file = _run_on_sandbox(client, all_uids, 0, args.concurrency, api_key)
        result_files = [result_file] if result_file else []
    else:
        # Split UIDs across sandboxes
        chunks = [[] for _ in range(num_sandboxes)]
        for i, uid in enumerate(all_uids):
            chunks[i % num_sandboxes].append(uid)

        # Launch sandboxes in parallel
        result_files = []
        with ThreadPoolExecutor(max_workers=num_sandboxes) as executor:
            futures = {
                executor.submit(_run_on_sandbox, client, chunk, idx,
                                args.concurrency, api_key): idx
                for idx, chunk in enumerate(chunks) if chunk
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    result_files.append(result)

    # Merge results
    if result_files:
        merged = NOMCP_DIR / f"results_merged_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        all_lines = []
        for rf in result_files:
            all_lines.extend(rf.read_text().strip().splitlines())
        merged.write_text("\n".join(all_lines) + "\n")

        correct = sum(1 for l in all_lines if json.loads(l).get("correct"))
        total = len(all_lines)
        print(f"\n{'='*60}")
        print(f"MERGED RESULTS: {correct}/{total} ({correct/total*100:.1f}%)")
        print(f"Saved to: {merged}")
        print(f"{'='*60}")
    else:
        print("No results collected.")

    # List remaining sandboxes
    for s in client.list().items:
        print(f"Sandbox {s.id} ({s.state}) — delete when done")

    return result_files


def _run_goose_on_sandbox(client, questions: list[dict], chunk_idx: int,
                          api_key: str, max_turns: int) -> Path | None:
    """Create a sandbox and run questions through real goose CLI (serial per sandbox)."""
    tag = f"[goose-{chunk_idx}]"
    print(f"{tag} Creating sandbox for {len(questions)} questions...")
    sandbox = _create_sandbox(client)

    # Copy skills to goose skills dir
    sandbox.process.exec(
        "mkdir -p /root/.config/goose/skills && "
        "cp /installed-agent/skills/*.md /root/.config/goose/skills/ 2>/dev/null; "
        "cp /installed-agent/skills/*.py /root/.config/goose/skills/ 2>/dev/null; "
        "cp /installed-agent/cpi_monthly.csv /root/.config/goose/skills/ 2>/dev/null; true",
        timeout=10,
    )

    # Verify goose works
    check = sandbox.process.exec("export PATH=/root/.local/bin:$PATH && goose --version", timeout=10)
    print(f"{tag} Goose: {check.result.strip()}")

    results = []
    output_file = NOMCP_DIR / f"results_goose_s{chunk_idx}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"

    for i, q in enumerate(questions):
        print(f"{tag} [{i+1}/{len(questions)}] {q['uid']}...", file=sys.stderr)
        result = _run_goose_question(
            sandbox, q["uid"], q["question"], q["answer"],
            q.get("difficulty", "unknown"), api_key, max_turns,
        )
        results.append(result)
        # Write incrementally
        with open(output_file, "a") as f:
            f.write(json.dumps(result) + "\n")

    correct = sum(1 for r in results if r["correct"])
    print(f"{tag} Done: {correct}/{len(results)} correct")
    return output_file


def cmd_goose(args):
    """Run questions through real goose CLI in Daytona (mimics arena test)."""
    import csv
    from concurrent.futures import ThreadPoolExecutor, as_completed

    client = _get_client()
    api_key = _load_api_key()
    num_sandboxes = args.sandboxes
    max_turns = args.max_turns

    # Load questions with full details
    all_questions = []
    with open(QUESTIONS_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_questions.append(row)

    if args.uids:
        uid_set = {u.strip().upper() for u in args.uids.split(",")}
        all_questions = [q for q in all_questions if q["uid"].upper() in uid_set]
    elif args.n:
        all_questions = all_questions[:args.n]

    print(f"Running {len(all_questions)} questions via GOOSE across {num_sandboxes} sandbox(es)")
    print(f"Max turns per question: {max_turns}")
    print(f"{'='*60}\n")

    if num_sandboxes == 1:
        result_file = _run_goose_on_sandbox(client, all_questions, 0, api_key, max_turns)
        result_files = [result_file] if result_file else []
    else:
        chunks = [[] for _ in range(num_sandboxes)]
        for i, q in enumerate(all_questions):
            chunks[i % num_sandboxes].append(q)

        result_files = []
        with ThreadPoolExecutor(max_workers=num_sandboxes) as executor:
            futures = {
                executor.submit(_run_goose_on_sandbox, client, chunk, idx, api_key, max_turns): idx
                for idx, chunk in enumerate(chunks) if chunk
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    result_files.append(result)

    # Merge
    if result_files:
        merged = NOMCP_DIR / f"results_goose_merged_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        all_lines = []
        for rf in result_files:
            all_lines.extend(rf.read_text().strip().splitlines())
        merged.write_text("\n".join(all_lines) + "\n")

        correct = sum(1 for l in all_lines if json.loads(l).get("correct"))
        total = len(all_lines)
        print(f"\n{'='*60}")
        print(f"GOOSE RESULTS: {correct}/{total} ({correct/total*100:.1f}%)")
        print(f"Saved to: {merged}")
        print(f"{'='*60}")

    for s in client.list().items:
        print(f"Sandbox {s.id} ({s.state}) — delete when done")


def main():
    parser = argparse.ArgumentParser(description="Daytona runner for nomcp OfficeQA")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("snapshot", help="Create Daytona snapshot (one-time)")
    sub.add_parser("create", help="Create sandbox for manual debugging")

    run_parser = sub.add_parser("run", help="Run questions via API simulation")
    run_parser.add_argument("--concurrency", type=int, default=8,
                            help="Concurrent questions per sandbox (default: 8)")
    run_parser.add_argument("--sandboxes", type=int, default=1,
                            help="Number of parallel sandboxes (max 3 on Tier 1)")
    run_parser.add_argument("--uids", type=str, default=None,
                            help="Comma-separated UIDs (default: all 246)")
    run_parser.add_argument("-n", type=int, default=None,
                            help="Run first N questions only")

    goose_parser = sub.add_parser("goose", help="Run questions via real goose CLI (mimics arena test)")
    goose_parser.add_argument("--sandboxes", type=int, default=3,
                              help="Number of parallel sandboxes (default: 3)")
    goose_parser.add_argument("--max-turns", type=int, default=8,
                              help="Max goose turns per question (default: 8, matches arena.yaml)")
    goose_parser.add_argument("--uids", type=str, default=None,
                              help="Comma-separated UIDs (default: all 246)")
    goose_parser.add_argument("-n", type=int, default=None,
                              help="Run first N questions only")

    args = parser.parse_args()

    if args.command == "snapshot":
        cmd_snapshot()
    elif args.command == "create":
        cmd_create()
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "goose":
        cmd_goose(args)


if __name__ == "__main__":
    main()
