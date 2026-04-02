#!/usr/bin/env python3
"""Build deep per-trial reports for a rescued runner-pool run."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
POOL_ROOT = ROOT / "results" / "runner_pool"
SAMPLE_ROOT = ROOT / ".arena" / "samples"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-label", required=True)
    return parser.parse_args()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def normalize_uid(task_id: str) -> str:
    m = re.search(r"uid(\d+)", task_id, re.IGNORECASE)
    if not m:
        return task_id.upper()
    return f"UID{int(m.group(1)):04d}"


def iter_trial_result_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("result.json"):
        if "/officeqa-uid" not in path.as_posix():
            continue
        if path.parent.name.startswith("pool-"):
            continue
        paths.append(path)
    return sorted(paths)


def safe_read(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(errors="replace")


def sample_question(task_id: str) -> dict[str, Any]:
    uid = normalize_uid(task_id)
    config_path = SAMPLE_ROOT / f"officeqa-{uid.lower()}" / "tests" / "config.json"
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text())


def load_stream_events(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    events = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def compact(value: Any, limit: int = 500) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    text = " ".join(text.split())
    return text[:limit]


def detect_answer_from_shell(command: str) -> str | None:
    patterns = [
        r'echo\s+"([^"]+)"\s*>\s*/app/answer\.txt',
        r"echo\s+'([^']+)'\s*>\s*/app/answer\.txt",
    ]
    for pattern in patterns:
        m = re.search(pattern, command)
        if m:
            return m.group(1)
    return None


def build_trial_report(trial_result: Path) -> dict[str, Any]:
    result = json.loads(trial_result.read_text())
    task_id = result["task_name"]
    uid = normalize_uid(task_id)
    sample_cfg = sample_question(task_id)
    trial_dir = trial_result.parent
    runner = next((part for part in trial_result.parts if part.startswith("officeqa-big-runner-")), "")
    pool_seg = next((part for part in trial_result.parts if part.startswith("pool-")), "")
    lane_match = re.search(r"-lane(\d+)-", pool_seg)
    lane = int(lane_match.group(1)) if lane_match else None

    goose_path = trial_dir / "agent" / "goose.txt"
    stdout_path = trial_dir / "agent" / "command-1" / "stdout.txt"
    config_path = trial_dir / "config.json"
    exception_path = trial_dir / "exception.txt"
    reward_path = trial_dir / "verifier" / "reward.txt"
    verifier_stdout_path = trial_dir / "verifier" / "test-stdout.txt"
    command0_path = trial_dir / "agent" / "command-0" / "command.txt"
    command1_path = trial_dir / "agent" / "command-1" / "command.txt"
    trial_log_path = trial_dir / "trial.log"

    parse_path = stdout_path if stdout_path.exists() else goose_path
    events = load_stream_events(parse_path)

    event_rows: list[dict[str, Any]] = []
    tool_counts: Counter[str] = Counter()
    shell_verbs: Counter[str] = Counter()
    generation_ids: list[str] = []
    seen_generation_ids: set[str] = set()
    submit_answers: list[dict[str, Any]] = []
    answer_write_candidates: list[str] = []
    assistant_text_chunks: list[str] = []
    thinking_chars = 0
    total_tokens = None
    event_index = 0

    for obj in events:
        if obj.get("type") == "complete" and isinstance(obj.get("total_tokens"), int):
            total_tokens = obj["total_tokens"]
            continue
        if obj.get("type") != "message":
            continue
        msg = obj.get("message") or {}
        msg_id = msg.get("id")
        if isinstance(msg_id, str) and msg_id.startswith("gen-") and msg_id not in seen_generation_ids:
            generation_ids.append(msg_id)
            seen_generation_ids.add(msg_id)
        for item in msg.get("content") or []:
            item_type = item.get("type")
            if item_type == "thinking":
                thinking_chars += len(item.get("thinking") or "")
                continue
            if item_type == "text":
                text = item.get("text") or ""
                if text.strip():
                    assistant_text_chunks.append(text)
                    event_rows.append(
                        {
                            "event_index": event_index,
                            "kind": "assistant_text",
                            "message_id": msg_id,
                            "preview": compact(text, 700),
                        }
                    )
                    event_index += 1
                continue
            if item_type == "toolRequest":
                value = (((item.get("toolCall") or {}).get("value")) or {})
                tool_name = value.get("name") or "unknown"
                args = value.get("arguments") or {}
                tool_counts[tool_name] += 1
                row = {
                    "event_index": event_index,
                    "kind": "tool_request",
                    "message_id": msg_id,
                    "tool_name": tool_name,
                    "arguments": args,
                    "preview": compact(args, 700),
                }
                if tool_name == "shell":
                    command = args.get("command") or args.get("cmd") or args.get("input") or ""
                    command = str(command)
                    row["command"] = command
                    first = command.split()[0] if command.split() else ""
                    if first:
                        shell_verbs[first] += 1
                    answer_candidate = detect_answer_from_shell(command)
                    if answer_candidate:
                        answer_write_candidates.append(answer_candidate)
                if tool_name.endswith("submit_answer"):
                    submit_answers.append(args)
                event_rows.append(row)
                event_index += 1
                continue
            if item_type == "toolResponse":
                payload = item.get("toolResult") or {}
                event_rows.append(
                    {
                        "event_index": event_index,
                        "kind": "tool_response",
                        "message_id": msg_id,
                        "preview": compact(payload, 900),
                        "is_error": bool(isinstance(payload, dict) and payload.get("isError")),
                    }
                )
                event_index += 1

    reward_text = (safe_read(reward_path) or "").strip()
    verifier_stdout = safe_read(verifier_stdout_path) or ""
    reward = (((result.get("verifier_result") or {}).get("rewards") or {}).get("reward"))
    status = "passed" if reward == 1.0 else "failed"
    agent_execution = result.get("agent_execution") or {}
    agent_start = parse_dt(agent_execution.get("started_at"))
    agent_end = parse_dt(agent_execution.get("finished_at"))
    elapsed_s = round((agent_end - agent_start).total_seconds(), 3) if agent_start and agent_end else None

    assistant_tail = "\n".join(chunk.strip() for chunk in assistant_text_chunks[-8:] if chunk.strip())

    return {
        "task_id": task_id,
        "uid": uid,
        "runner": runner,
        "lane": lane,
        "trial_name": result.get("trial_name"),
        "status": status,
        "reward": reward,
        "reward_text": reward_text,
        "question": sample_cfg.get("question"),
        "expected_answer": sample_cfg.get("expected_answer"),
        "difficulty": sample_cfg.get("difficulty"),
        "agent_execution_start": agent_execution.get("started_at"),
        "agent_execution_end": agent_execution.get("finished_at"),
        "elapsed_s": elapsed_s,
        "goose_total_tokens": total_tokens,
        "thinking_chars": thinking_chars,
        "generation_ids": generation_ids,
        "tool_counts": dict(tool_counts),
        "shell_command_count": tool_counts.get("shell", 0),
        "shell_verbs": dict(shell_verbs),
        "submit_answers": submit_answers,
        "answer_write_candidates": answer_write_candidates,
        "assistant_tail": assistant_tail,
        "verifier_stdout": verifier_stdout,
        "exception_preview": (safe_read(exception_path) or "")[:3000] if exception_path.exists() else None,
        "raw_paths": {
            "trial_dir": str(trial_dir),
            "result_json": str(trial_result),
            "config_json": str(config_path) if config_path.exists() else None,
            "goose_txt": str(goose_path) if goose_path.exists() else None,
            "stdout_txt": str(stdout_path) if stdout_path.exists() else None,
            "command0_txt": str(command0_path) if command0_path.exists() else None,
            "command1_txt": str(command1_path) if command1_path.exists() else None,
            "trial_log": str(trial_log_path) if trial_log_path.exists() else None,
            "exception_txt": str(exception_path) if exception_path.exists() else None,
            "verifier_reward_txt": str(reward_path) if reward_path.exists() else None,
            "verifier_stdout_txt": str(verifier_stdout_path) if verifier_stdout_path.exists() else None,
        },
        "event_rows": event_rows,
    }


def write_trial_markdown(out_path: Path, report: dict[str, Any]) -> None:
    raw = report["raw_paths"]
    lines = [
        f"# {report['task_id']}",
        "",
        f"- Status: `{report['status']}`",
        f"- Reward: `{report['reward']}`",
        f"- Runner/Lane: `{report['runner']}` / `{report['lane']}`",
        f"- Elapsed seconds: `{report['elapsed_s']}`",
        f"- Goose total tokens: `{report['goose_total_tokens']}`",
        f"- Shell commands: `{report['shell_command_count']}`",
        f"- Question: {report.get('question') or ''}",
        f"- Expected answer: `{report.get('expected_answer')}`",
        "",
        "## Raw Paths",
        f"- Trial dir: `{raw['trial_dir']}`",
        f"- Result: `{raw['result_json']}`",
        f"- Goose stream: `{raw['goose_txt']}`",
        f"- Stream stdout: `{raw['stdout_txt']}`",
        f"- Exception: `{raw['exception_txt']}`",
        "",
        "## Tool Counts",
    ]
    for name, count in sorted(report["tool_counts"].items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- `{name}`: `{count}`")

    lines.extend(["", "## Shell Verbs"])
    for name, count in sorted(report["shell_verbs"].items(), key=lambda kv: (-kv[1], kv[0]))[:20]:
        lines.append(f"- `{name}`: `{count}`")

    if report["submit_answers"]:
        lines.extend(["", "## submit_answer Calls"])
        for item in report["submit_answers"][:10]:
            lines.append(f"- `{compact(item, 300)}`")

    if report["answer_write_candidates"]:
        lines.extend(["", "## /app/answer.txt Writes"])
        for value in report["answer_write_candidates"][:10]:
            lines.append(f"- `{value}`")

    if report["assistant_tail"]:
        lines.extend(["", "## Assistant Tail", "", "```text", report["assistant_tail"][:4000], "```"])

    if report["verifier_stdout"]:
        lines.extend(["", "## Verifier Output", "", "```text", report["verifier_stdout"][:2000], "```"])

    if report["exception_preview"]:
        lines.extend(["", "## Exception Preview", "", "```text", report["exception_preview"][:2500], "```"])

    lines.extend(["", "## Event Sequence"])
    for row in report["event_rows"][:120]:
        if row["kind"] == "tool_request":
            lines.append(f"- `{row['event_index']}` request `{row['tool_name']}`: {row['preview']}")
        elif row["kind"] == "tool_response":
            lines.append(f"- `{row['event_index']}` response: {row['preview']}")
        else:
            lines.append(f"- `{row['event_index']}` assistant: {row['preview']}")

    out_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    run_root = POOL_ROOT / args.run_label
    trace_root = run_root / "full_traces"
    out_root = run_root / "deep_trials"
    reports_root = out_root / "reports"
    events_root = out_root / "events"
    reports_root.mkdir(parents=True, exist_ok=True)
    events_root.mkdir(parents=True, exist_ok=True)

    reports = [build_trial_report(path) for path in iter_trial_result_paths(trace_root)]
    reports.sort(key=lambda r: r["task_id"])

    for report in reports:
        uid = report["uid"]
        json_path = reports_root / f"{uid}.json"
        md_path = reports_root / f"{uid}.md"
        events_path = events_root / f"{uid}.jsonl"
        json_path.write_text(json.dumps(report, indent=2) + "\n")
        write_trial_markdown(md_path, report)
        with events_path.open("w") as f:
            for row in report["event_rows"]:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    index_rows = []
    for report in reports:
        index_rows.append(
            {
                "task_id": report["task_id"],
                "uid": report["uid"],
                "status": report["status"],
                "runner": report["runner"],
                "lane": report["lane"],
                "elapsed_s": report["elapsed_s"],
                "goose_total_tokens": report["goose_total_tokens"],
                "shell_command_count": report["shell_command_count"],
                "submit_answer_count": len(report["submit_answers"]),
                "answer_write_count": len(report["answer_write_candidates"]),
                "has_exception": bool(report["exception_preview"]),
                "report_json": str(reports_root / f"{report['uid']}.json"),
                "report_md": str(reports_root / f"{report['uid']}.md"),
                "events_jsonl": str(events_root / f"{report['uid']}.jsonl"),
            }
        )

    with (out_root / "index.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "task_id",
                "uid",
                "status",
                "runner",
                "lane",
                "elapsed_s",
                "goose_total_tokens",
                "shell_command_count",
                "submit_answer_count",
                "answer_write_count",
                "has_exception",
                "report_json",
                "report_md",
                "events_jsonl",
            ],
        )
        writer.writeheader()
        writer.writerows(index_rows)

    summary = {
        "run_label": args.run_label,
        "tasks": len(reports),
        "passed": sum(1 for r in reports if r["status"] == "passed"),
        "failed": sum(1 for r in reports if r["status"] == "failed"),
        "with_exception": sum(1 for r in reports if r["exception_preview"]),
        "with_stdout_stream": sum(1 for r in reports if r["raw_paths"]["stdout_txt"]),
        "with_submit_answer": sum(1 for r in reports if r["submit_answers"]),
        "with_answer_write": sum(1 for r in reports if r["answer_write_candidates"]),
    }
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
