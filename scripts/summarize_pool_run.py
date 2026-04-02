#!/usr/bin/env python3
"""Build a compact summary for a runner-pool Arena run.

Usage:
    python3 scripts/summarize_pool_run.py --run-label pool-20260402T063912Z
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
POOL_ROOT = ROOT / "results" / "runner_pool"
ARENA_RUNS = ROOT / ".arena" / "runs"

RESULT_RE = re.compile(r"\s+(PASS|FAIL)\s+(officeqa-uid\d+)\s+\(reward=([0-9.]+)\)")
EXIT_RE = re.compile(r"exit code (\d+)", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-label", required=True, help="Pool run label under results/runner_pool/")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def classify_failure(exception_text: str, lane_log_text: str) -> str:
    text = f"{exception_text}\n{lane_log_text}"
    if "SyntaxError: unmatched ')'" in text:
        return "mcp_bundle_syntax_error"
    if "Failed to start extension 'officeqa-arena'" in text:
        return "mcp_extension_start_failed"
    exit_match = EXIT_RE.search(text)
    if exit_match and exit_match.group(1) == "137":
        return "agent_exit_137"
    if "AgentTimeoutError" in text:
        return "agent_timeout"
    return "wrong_answer_or_verifier_fail"


def find_task_run_dir(run_label: str, task_id: str) -> Path | None:
    pattern = f"run-*/{run_label}-*/result.json"
    for result_json in ARENA_RUNS.glob(pattern):
        if task_id in result_json.as_posix():
            return result_json.parent
    return None


def parse_goose_total_tokens(task_run_dir: Path) -> int | None:
    goose_files = list(task_run_dir.glob("*/agent/goose.txt"))
    if not goose_files:
        return None

    total = 0
    saw_complete = False
    for line in goose_files[0].read_text(errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "complete" and isinstance(obj.get("total_tokens"), int):
            total += obj["total_tokens"]
            saw_complete = True
    return total if saw_complete else None


def summarize_run(run_label: str) -> dict:
    run_root = POOL_ROOT / run_label
    if not run_root.exists():
        raise FileNotFoundError(f"Run directory not found: {run_root}")

    task_records: dict[str, dict] = {}

    for lane_jsonl in run_root.glob("*/results/lane*.jsonl"):
        for row in load_jsonl(lane_jsonl):
            task_records[row["task_id"]] = {
                "task_id": row["task_id"],
                "runner": row["runner"],
                "lane": row["lane"],
                "elapsed_s": row["elapsed_s"],
                "cost_usd": row["cost_usd"],
                "exit_code": row["exit_code"],
                "tag": row["tag"],
                "reward": None,
                "status": None,
                "trace_dir": None,
                "goose_total_tokens": None,
                "exception_path": None,
                "failure_reason": None,
            }

    for lane_log in run_root.glob("*/logs/lane*.log"):
        text = lane_log.read_text()
        for match in RESULT_RE.finditer(text):
            status, task_id, reward_str = match.groups()
            if task_id not in task_records:
                task_records[task_id] = {
                    "task_id": task_id,
                    "runner": None,
                    "lane": None,
                    "elapsed_s": None,
                    "cost_usd": None,
                    "exit_code": None,
                    "tag": None,
                    "reward": None,
                    "status": None,
                    "trace_dir": None,
                    "goose_total_tokens": None,
                    "exception_path": None,
                    "failure_reason": None,
                }
            task_records[task_id]["status"] = "passed" if status == "PASS" else "failed"
            task_records[task_id]["reward"] = float(reward_str)

    for task_id, record in task_records.items():
        task_run_dir = find_task_run_dir(run_label, task_id)
        if not task_run_dir:
            continue
        record["trace_dir"] = str(task_run_dir)
        record["goose_total_tokens"] = parse_goose_total_tokens(task_run_dir)
        exception_files = list(task_run_dir.glob("*/exception.txt"))
        if exception_files:
            record["exception_path"] = str(exception_files[0])
            if record["status"] == "failed":
                record["failure_reason"] = classify_failure(
                    exception_files[0].read_text(),
                    "",
                )
        elif record["status"] == "failed":
            record["failure_reason"] = "wrong_answer_or_verifier_fail"

    records = sorted(task_records.values(), key=lambda r: r["task_id"])
    passed = [r for r in records if r["status"] == "passed"]
    failed = [r for r in records if r["status"] == "failed"]

    failure_reasons = Counter(r["failure_reason"] for r in failed if r["failure_reason"])
    cost_values = [r["cost_usd"] for r in records if r["cost_usd"] is not None]
    elapsed_values = [r["elapsed_s"] for r in records if r["elapsed_s"] is not None]
    token_values = [r["goose_total_tokens"] for r in records if r["goose_total_tokens"] is not None]

    return {
        "run_label": run_label,
        "tasks_total": len(records),
        "tasks_passed": len(passed),
        "tasks_failed": len(failed),
        "pass_rate": round(len(passed) / len(records), 4) if records else 0.0,
        "total_cost_usd": round(sum(cost_values), 6),
        "avg_elapsed_s": round(sum(elapsed_values) / len(elapsed_values), 2) if elapsed_values else 0.0,
        "total_goose_tokens": sum(token_values),
        "avg_goose_tokens": round(sum(token_values) / len(token_values), 2) if token_values else 0.0,
        "fastest_tasks": sorted(records, key=lambda r: r["elapsed_s"] or 0)[:5],
        "slowest_tasks": sorted(records, key=lambda r: r["elapsed_s"] or 0)[-5:],
        "failure_reasons": dict(failure_reasons),
        "tasks": records,
    }


def write_outputs(summary: dict) -> None:
    run_root = POOL_ROOT / summary["run_label"]
    summary_json = run_root / "summary.json"
    summary_md = run_root / "summary.md"

    summary_json.write_text(json.dumps(summary, indent=2) + "\n")

    lines: list[str] = []
    lines.append(f"# Pool Run Summary: {summary['run_label']}")
    lines.append("")
    lines.append(f"- Tasks: `{summary['tasks_passed']}` passed / `{summary['tasks_failed']}` failed / `{summary['tasks_total']}` total")
    lines.append(f"- Pass rate: `{summary['pass_rate']:.1%}`")
    lines.append(f"- Total cost: `${summary['total_cost_usd']:.3f}`")
    lines.append(f"- Avg elapsed: `{summary['avg_elapsed_s']:.2f}s`")
    lines.append(f"- Goose tokens seen: `{summary['total_goose_tokens']}` total / `{summary['avg_goose_tokens']:.2f}` avg per task")
    lines.append("")

    if summary["failure_reasons"]:
        lines.append("## Failure Reasons")
        for reason, count in sorted(summary["failure_reasons"].items()):
            lines.append(f"- `{reason}`: `{count}`")
        lines.append("")

    lines.append("## Task Table")
    lines.append("")
    lines.append("| Task | Status | Reward | Elapsed (s) | Cost ($) | Goose Tokens | Runner | Lane | Failure Reason |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- |")
    for row in summary["tasks"]:
        lines.append(
            f"| {row['task_id']} | {row['status'] or 'unknown'} | "
            f"{row['reward'] if row['reward'] is not None else ''} | "
            f"{row['elapsed_s'] if row['elapsed_s'] is not None else ''} | "
            f"{row['cost_usd'] if row['cost_usd'] is not None else ''} | "
            f"{row['goose_total_tokens'] if row['goose_total_tokens'] is not None else ''} | "
            f"{row['runner'] or ''} | {row['lane'] or ''} | "
            f"{row['failure_reason'] or ''} |"
        )
    lines.append("")

    lines.append("## Slowest Tasks")
    for row in summary["slowest_tasks"]:
        lines.append(
            f"- `{row['task_id']}` on `{row['runner']}` lane `{row['lane']}`: "
            f"`{row['elapsed_s']:.2f}s`, `${row['cost_usd']:.3f}`, `{row['status']}`"
        )
    lines.append("")

    summary_md.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    summary = summarize_run(args.run_label)
    write_outputs(summary)
    print(json.dumps({
        "run_label": summary["run_label"],
        "tasks_passed": summary["tasks_passed"],
        "tasks_failed": summary["tasks_failed"],
        "summary_json": str((POOL_ROOT / summary["run_label"] / "summary.json").relative_to(ROOT)),
        "summary_md": str((POOL_ROOT / summary["run_label"] / "summary.md").relative_to(ROOT)),
    }, indent=2))


if __name__ == "__main__":
    main()
