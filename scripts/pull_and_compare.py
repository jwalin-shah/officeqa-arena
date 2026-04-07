#!/usr/bin/env python3
"""Pull arena traces and compare against a previous run.

Naming: traces are saved as traces/<label>_<YYYYMMDD>/
If that directory already exists, appends _2, _3, etc. — never overwrites.

Workflow for retriggered submissions (same ID, new results):
    # You already have traces/v13/ from the old run.
    # Arena retriggered it. Pull the new results and compare:
    ~/.arena/venv/bin/python scripts/pull_and_compare.py SUB_ID --before v13

    # Or pull two submission IDs and compare them:
    ~/.arena/venv/bin/python scripts/pull_and_compare.py SUB_A SUB_B

    # Pull latest completed and compare against an existing baseline:
    ~/.arena/venv/bin/python scripts/pull_and_compare.py --latest --before v20_best

    # Just pull, no compare:
    ~/.arena/venv/bin/python scripts/pull_and_compare.py SUB_ID --label v15_rerun

    # Compare two existing trace dirs (no pulling):
    ~/.arena/venv/bin/python scripts/pull_and_compare.py --compare v13 v20_best

Requires: ~/.arena/venv/bin/python (has arena_cli package)
"""
import asyncio
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACES_DIR = ROOT / "traces"
SLUG = "grounded-reasoning"


# ---------------------------------------------------------------------------
# Unique directory naming
# ---------------------------------------------------------------------------

def unique_dir(base_label: str) -> Path:
    """Return a non-existing directory under TRACES_DIR.

    Tries:  base_label  ->  base_label_2  ->  base_label_3  -> ...
    """
    candidate = TRACES_DIR / base_label
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = TRACES_DIR / f"{base_label}_{n}"
        if not candidate.exists():
            return candidate
        n += 1


def make_label(info: dict, custom_label: str = "") -> str:
    """Build a directory label from submission info + today's date."""
    today = datetime.now().strftime("%Y%m%d")
    if custom_label:
        return custom_label
    return f"v{info['version']}_{int(info['score'])}_{today}"


def resolve_trace_dir(spec: str) -> Path:
    """Resolve a trace dir spec: exact name, substring match, or path."""
    # Exact match
    candidate = TRACES_DIR / spec
    if candidate.is_dir():
        return candidate
    # Absolute/relative path
    p = Path(spec)
    if p.is_dir():
        return p
    # Substring match
    matches = [d for d in TRACES_DIR.iterdir() if d.is_dir() and spec in d.name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = "\n  ".join(sorted(d.name for d in matches))
        sys.exit(f"Ambiguous trace dir '{spec}', matches:\n  {names}")
    sys.exit(f"No trace dir found matching '{spec}'. Available:\n  "
             + "\n  ".join(sorted(d.name for d in TRACES_DIR.iterdir() if d.is_dir())))


# ---------------------------------------------------------------------------
# Arena API helpers
# ---------------------------------------------------------------------------

async def get_submission_info(client, sub_id: str) -> dict:
    from arena_cli.client.submissions import get_submission
    sub = await get_submission(client, sub_id, slug=SLUG)
    version = sub.agent.version if sub.agent else "unknown"
    score = 0.0
    if sub.stages and sub.stages.execute:
        score = sub.stages.execute.score
    return {"id": sub_id, "status": sub.status, "version": version, "score": score}


async def get_latest_completed(client, n: int = 1) -> list[dict]:
    from arena_cli.client.submissions import list_submissions
    results = []
    offset = 0
    while len(results) < n:
        resp = await list_submissions(client, slug=SLUG, limit=50, offset=offset)
        for sub in resp.items:
            if sub.status == "completed":
                version = sub.agent.version if sub.agent else "unknown"
                score = 0.0
                if sub.stages and sub.stages.execute:
                    score = sub.stages.execute.score
                results.append({
                    "id": str(sub.id), "status": "completed",
                    "version": version, "score": score,
                })
                if len(results) >= n:
                    break
        if not resp.items or offset + len(resp.items) >= resp.total:
            break
        offset += len(resp.items)
    return results


async def wait_for_completion(client, sub_id: str, poll_interval: int = 30) -> dict:
    while True:
        info = await get_submission_info(client, sub_id)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        if info["status"] == "completed":
            print(f"  [{ts}] {sub_id[:8]}... COMPLETED  score={info['score']:.1f}")
            return info
        elif info["status"] == "failed":
            print(f"  [{ts}] {sub_id[:8]}... FAILED")
            return info
        else:
            print(f"  [{ts}] {sub_id[:8]}... {info['status']}  score={info['score']:.1f}")
            await asyncio.sleep(poll_interval)


async def pull_traces_for(client, sub_id: str, out_dir: Path) -> dict:
    from arena_cli.client.trajectories import get_trajectory, list_trajectories

    out_dir.mkdir(parents=True, exist_ok=True)

    all_items = []
    offset = 0
    while True:
        resp = await list_trajectories(
            client, submission_id=sub_id, slug=SLUG, limit=100, offset=offset
        )
        all_items.extend(resp.items)
        if len(all_items) >= resp.total or len(resp.items) == 0:
            break
        offset += 100

    passed = sum(1 for i in all_items if i.reward > 0)
    total = len(all_items)
    print(f"  Pulling {total} traces ({passed} passed) -> {out_dir.name}/")

    for idx, item in enumerate(all_items):
        out_path = out_dir / f"{item.task_id}.json"
        if out_path.exists():
            continue
        for attempt in range(3):
            try:
                detail = await get_trajectory(client, item.trajectory_id, slug=SLUG)
                with open(out_path, "w") as f:
                    json.dump(detail.model_dump(mode="json"), f)
                status = "PASS" if item.reward > 0 else "FAIL"
                print(f"    [{idx+1}/{total}] {item.task_id}: {status}")
                break
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(1)
                else:
                    print(f"    [{idx+1}/{total}] {item.task_id}: ERROR - {e}")

    downloaded = len(list(out_dir.glob("*.json")))
    print(f"  Done: {downloaded} traces in {out_dir}/")

    # Write metadata
    meta = {
        "submission_id": sub_id,
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "total": total, "passed": passed,
        "score": sum(i.reward for i in all_items),
    }
    with open(out_dir / "_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    return {"dir": out_dir, "total": total, "passed": passed,
            "failed": total - passed, "score": meta["score"]}


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def load_trace_results(trace_dir: Path) -> dict[str, dict]:
    tasks = {}
    for f in sorted(trace_dir.glob("officeqa-*.json")):
        with open(f) as fh:
            data = json.load(fh)
        task_id = f.stem
        reward = data.get("reward", 0)
        tasks[task_id] = {"task_id": task_id, "passed": reward > 0, "reward": reward}
    return tasks


def compare_trace_dirs(dir_a: Path, dir_b: Path, label_a: str = "", label_b: str = ""):
    label_a = label_a or dir_a.name
    label_b = label_b or dir_b.name

    tasks_a = load_trace_results(dir_a)
    tasks_b = load_trace_results(dir_b)

    if not tasks_a:
        print(f"  WARNING: no traces in {dir_a}")
    if not tasks_b:
        print(f"  WARNING: no traces in {dir_b}")

    all_ids = sorted(set(tasks_a) | set(tasks_b))
    gained, lost, stable_pass, stable_fail = [], [], [], []
    only_a, only_b = [], []

    for tid in all_ids:
        in_a, in_b = tid in tasks_a, tid in tasks_b
        if in_a and not in_b:
            only_a.append(tid); continue
        if in_b and not in_a:
            only_b.append(tid); continue
        pa, pb = tasks_a[tid]["passed"], tasks_b[tid]["passed"]
        if not pa and pb:     gained.append(tid)
        elif pa and not pb:   lost.append(tid)
        elif pa and pb:       stable_pass.append(tid)
        else:                 stable_fail.append(tid)

    passed_a = sum(1 for t in tasks_a.values() if t["passed"])
    passed_b = sum(1 for t in tasks_b.values() if t["passed"])
    total_a, total_b = len(tasks_a), len(tasks_b)
    score_a = sum(t["reward"] for t in tasks_a.values())
    score_b = sum(t["reward"] for t in tasks_b.values())

    w = max(len(label_a), len(label_b), 8) + 2

    print(f"\n{'=' * 60}")
    print(f"  COMPARISON: {label_a}  vs  {label_b}")
    print(f"{'=' * 60}\n")
    print(f"  {'':20}{label_a:<{w}}{label_b:<{w}}{'Delta'}")
    print(f"  {'-'*20}{'-'*w}{'-'*w}{'-'*10}")
    print(f"  {'Passed:':<20}{passed_a:<{w}}{passed_b:<{w}}{passed_b - passed_a:+d}")
    print(f"  {'Failed:':<20}{total_a - passed_a:<{w}}{total_b - passed_b:<{w}}{(total_b-passed_b)-(total_a-passed_a):+d}")
    print(f"  {'Total:':<20}{total_a:<{w}}{total_b:<{w}}{total_b - total_a:+d}")
    acc_a = passed_a / total_a if total_a else 0
    acc_b = passed_b / total_b if total_b else 0
    print(f"  {'Accuracy:':<20}{acc_a:<{w}.1%}{acc_b:<{w}.1%}{acc_b - acc_a:+.1%}")
    print(f"  {'Score:':<20}{score_a:<{w}.1f}{score_b:<{w}.1f}{score_b - score_a:+.1f}")

    print(f"\n  Gained (fail->pass): {len(gained)}")
    for tid in gained:
        print(f"    + {tid}")

    print(f"\n  Lost (pass->fail): {len(lost)}")
    for tid in lost:
        print(f"    - {tid}")

    print(f"\n  Stable pass: {len(stable_pass)}   Stable fail: {len(stable_fail)}")

    if only_a:
        print(f"\n  Only in {label_a}: {len(only_a)}")
    if only_b:
        print(f"\n  Only in {label_b}: {len(only_b)}")

    # Save comparison
    comp_file = TRACES_DIR / f"compare_{label_a}_vs_{label_b}.json"
    with open(comp_file, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "label_a": label_a, "dir_a": str(dir_a),
            "label_b": label_b, "dir_b": str(dir_b),
            "passed_a": passed_a, "passed_b": passed_b,
            "total_a": total_a, "total_b": total_b,
            "score_a": score_a, "score_b": score_b,
            "gained": gained, "lost": lost,
            "stable_pass": stable_pass, "stable_fail": stable_fail,
        }, f, indent=2)
    print(f"\n  Saved: {comp_file.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run():
    parser = argparse.ArgumentParser(
        description="Pull arena traces and compare runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("submissions", nargs="*", help="Submission ID(s) to pull")
    parser.add_argument("--latest", type=int, nargs="?", const=1, metavar="N",
                        help="Pull the N latest completed submissions (default: 1)")
    parser.add_argument("--before", metavar="DIR",
                        help="Existing trace dir to compare against (the 'before' baseline)")
    parser.add_argument("--label", metavar="NAME",
                        help="Custom label for the pulled traces dir")
    parser.add_argument("--labels", nargs="*",
                        help="Custom labels when pulling multiple submissions")
    parser.add_argument("--compare", nargs=2, metavar=("DIR_A", "DIR_B"),
                        help="Compare two existing trace dirs (no pulling)")
    parser.add_argument("--no-wait", action="store_true",
                        help="Don't wait for completion, pull whatever exists")
    parser.add_argument("--poll-interval", type=int, default=30)

    args = parser.parse_args()

    # Mode 1: compare two existing dirs, no API needed
    if args.compare:
        dir_a = resolve_trace_dir(args.compare[0])
        dir_b = resolve_trace_dir(args.compare[1])
        compare_trace_dirs(dir_a, dir_b)
        return

    # Modes 2+3 need the API
    if not args.submissions and args.latest is None:
        parser.error("Provide submission ID(s), --latest, or --compare")

    from arena_cli.client.base import ArenaClient

    async with ArenaClient() as client:
        # Resolve submissions
        sub_infos = []
        if args.latest:
            n = args.latest
            print(f"Finding {n} latest completed submission(s)...")
            sub_infos = await get_latest_completed(client, n)
        else:
            for sub_id in args.submissions:
                info = await get_submission_info(client, sub_id)
                sub_infos.append(info)

        for info in sub_infos:
            print(f"  {info['id'][:8]}... v{info['version']}  "
                  f"status={info['status']}  score={info['score']:.1f}")

        # Wait for completion
        if not args.no_wait:
            for i, info in enumerate(sub_infos):
                if info["status"] not in ("completed", "failed"):
                    print(f"\nWaiting for {info['id'][:8]}...")
                    sub_infos[i] = await wait_for_completion(
                        client, info["id"], args.poll_interval)

        # Build labels and pull
        custom_labels = args.labels or ([args.label] if args.label else [])
        pulled = []
        for i, info in enumerate(sub_infos):
            custom = custom_labels[i] if i < len(custom_labels) else ""
            label = make_label(info, custom)
            out_dir = unique_dir(label)
            print(f"\n--- Pulling {info['id'][:8]}... -> {out_dir.name}/ ---")
            stats = await pull_traces_for(client, info["id"], out_dir)
            pulled.append({"info": info, "dir": out_dir, "stats": stats,
                           "label": out_dir.name})

        # Compare
        if args.before and len(pulled) == 1:
            before_dir = resolve_trace_dir(args.before)
            compare_trace_dirs(before_dir, pulled[0]["dir"])
        elif len(pulled) == 2:
            compare_trace_dirs(pulled[0]["dir"], pulled[1]["dir"])
        else:
            for p in pulled:
                s = p["stats"]
                print(f"\n  {p['label']}: {s['passed']}/{s['total']} passed  "
                      f"(score {s['score']:.1f})")

        print(f"\n--- Trace directories ---")
        for p in pulled:
            print(f"  traces/{p['label']}/")


if __name__ == "__main__":
    asyncio.run(run())
