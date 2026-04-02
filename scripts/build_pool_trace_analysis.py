#!/usr/bin/env python3
"""Build a local analysis dataset for a rescued runner-pool run.

Outputs under results/runner_pool/<run_label>/analysis/:
  - trace_index.json
  - trace_index.jsonl
  - trace_index.csv
  - summary.json
  - summary.md

This parser mines:
  - per-task trial/result metadata
  - model stream + tool events from agent/command-1/stdout.txt
  - fallback token totals from goose.txt
  - approximate OpenRouter export joins by agent execution time window
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import tomllib
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
POOL_ROOT = ROOT / "results" / "runner_pool"
SAMPLE_ROOT = ROOT / ".arena" / "samples"
PHASE1_RETRY_PATH = ROOT / "results" / "phase1_retry.jsonl"
OPENROUTER_EXPORT_TZ = ZoneInfo("America/Los_Angeles")

TOOL_HINTS = [
    "route_question",
    "search_ledger",
    "get_time_series",
    "search_tables",
    "extract_values",
    "search_canonical",
    "grep_corpus",
    "resolve_numeric_evidence",
    "search_data",
    "get_table_profile",
    "get_table_context",
    "query_table_rows",
    "compute_expression",
    "get_cpi_index",
    "get_exchange_rate",
    "get_multi_year_series",
    "submit_answer",
]


@dataclass
class ExportRow:
    generation_id: str
    created_at: datetime
    raw: dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-label", required=True)
    parser.add_argument(
        "--openrouter-csv",
        action="append",
        default=[],
        help="Optional OpenRouter activity CSV path. Can be passed multiple times.",
    )
    return parser.parse_args()


def parse_dt(s: str) -> datetime:
    if s.endswith("Z"):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    return datetime.fromisoformat(s)


def parse_export_dt(s: str) -> datetime:
    # OpenRouter export timestamps are emitted in the user's local timezone.
    naive = datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")
    return naive.replace(tzinfo=OPENROUTER_EXPORT_TZ).astimezone(timezone.utc)


def normalize_uid(task_id: str) -> str:
    m = re.search(r"uid(\d+)", task_id, re.IGNORECASE)
    if not m:
        return task_id.upper()
    return f"UID{int(m.group(1)):04d}"


def classify_domain(question: str) -> str:
    q = question.lower()
    if any(term in q for term in ["exchange rate", "cad", "euro", "yen", "currency", "foreign exchange", "usd-"]):
        return "fx"
    if any(term in q for term in ["yield", "bond", "treasury bill", "security", "securities", "coupon", "tips"]):
        return "rates_and_securities"
    if any(term in q for term in ["receipts", "outlays", "budget", "deficit", "surplus", "expenditures"]):
        return "budget_and_receipts"
    if any(term in q for term in ["debt", "holdings", "liabilities", "claims", "capital movements", "reserve assets"]):
        return "debt_and_international"
    if any(term in q for term in ["gold", "silver", "money in circulation", "gdp", "cpi"]):
        return "macro_and_monetary"
    return "other"


def classify_operation(question: str, computation_type: str | None) -> str:
    if computation_type:
        ct = computation_type.lower()
        if any(term in ct for term in ["variance", "standard_deviation", "stdev", "kurtosis", "mean", "regression", "var"]):
            return "statistical"
        if any(term in ct for term in ["difference", "change", "growth", "share", "percentage"]):
            return "comparison"
        if any(term in ct for term in ["sum", "total", "lookup", "extraction"]):
            return "lookup_or_aggregation"
        if any(term in ct for term in ["convert", "exchange", "ratio"]):
            return "conversion"
    q = question.lower()
    if any(term in q for term in ["variance", "standard deviation", "kurtosis", "geometric mean", "ols", "regression", "value-at-risk", "var "]):
        return "statistical"
    if any(term in q for term in ["absolute difference", "change", "difference", "growth rate"]):
        return "comparison"
    if any(term in q for term in ["using the monthly average exchange rate", "expressed in millions of cad", "usd-cad", "convert"]):
        return "conversion"
    return "lookup_or_aggregation"


def load_phase1_retry_metadata() -> dict[str, dict]:
    if not PHASE1_RETRY_PATH.exists():
        return {}
    out: dict[str, dict] = {}
    with PHASE1_RETRY_PATH.open() as f:
        for line in f:
            obj = json.loads(line)
            uid = obj.get("uid")
            if not uid:
                continue
            out[uid] = obj
    return out


def load_sample_metadata(task_id: str) -> dict:
    uid = normalize_uid(task_id)
    sample_dir = SAMPLE_ROOT / f"officeqa-{uid.lower()}"
    config_path = sample_dir / "tests" / "config.json"
    task_toml_path = sample_dir / "task.toml"
    instruction_path = sample_dir / "instruction.md"
    out = {
        "uid": uid,
        "question": None,
        "expected_answer": None,
        "difficulty": None,
        "source_docs": [],
        "instruction_path": str(instruction_path) if instruction_path.exists() else None,
        "task_toml_path": str(task_toml_path) if task_toml_path.exists() else None,
    }
    if config_path.exists():
        cfg = json.loads(config_path.read_text())
        out["question"] = cfg.get("question")
        out["expected_answer"] = cfg.get("expected_answer")
        out["difficulty"] = cfg.get("difficulty")
        out["source_docs"] = cfg.get("source_docs") or []
    if task_toml_path.exists():
        data = tomllib.loads(task_toml_path.read_text())
        meta = data.get("metadata") or {}
        out["benchmark_category"] = meta.get("category")
        out["benchmark_mode"] = meta.get("mode")
        out["benchmark_tags"] = meta.get("tags") or []
    if instruction_path.exists() and not out["question"]:
        out["question"] = instruction_path.read_text().splitlines()[0].strip()
    return out


def read_openrouter_exports(paths: list[Path]) -> list[ExportRow]:
    rows: list[ExportRow] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open(newline="") as f:
            for raw in csv.DictReader(f):
                if raw.get("app_name") != "Goose":
                    continue
                gid = raw.get("generation_id") or ""
                created_at = raw.get("created_at") or ""
                if not gid or not created_at:
                    continue
                rows.append(ExportRow(generation_id=gid, created_at=parse_export_dt(created_at), raw=raw))
    rows.sort(key=lambda r: r.created_at)
    return rows


def iter_trial_result_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("result.json"):
        if "/officeqa-uid" not in path.as_posix():
            continue
        if path.parent.name.startswith("pool-"):
            continue
        paths.append(path)
    return sorted(paths)


def load_stream_events(path: Path) -> list[dict]:
    events: list[dict] = []
    if not path.exists():
        return events
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def extract_tool_name_from_response(item: dict) -> str | None:
    payload = item.get("toolResult") or {}
    if not isinstance(payload, dict):
        return None
    text = json.dumps(payload)[:4000]
    for hint in TOOL_HINTS:
        full = f"officeqa-arena__{hint}"
        if full in text:
            return full
        if hint in text:
            return hint
    return None


def parse_trial(trial_result: Path, phase1_retry: dict[str, dict]) -> dict:
    result = json.loads(trial_result.read_text())
    task_id = result["task_name"]
    uid = normalize_uid(task_id)
    trial_dir = trial_result.parent
    runner = next((part for part in trial_result.parts if part.startswith("officeqa-big-runner-")), "")
    pool_seg = next((part for part in trial_result.parts if part.startswith("pool-")), "")
    lane_match = re.search(r"-lane(\d+)-", pool_seg)
    lane = int(lane_match.group(1)) if lane_match else None

    goose_path = trial_dir / "agent" / "goose.txt"
    stdout_path = trial_dir / "agent" / "command-1" / "stdout.txt"
    traj_path = trial_dir / "agent" / "trajectory.json"
    exc_path = trial_dir / "exception.txt"

    parse_path = stdout_path if stdout_path.exists() else goose_path
    events = load_stream_events(parse_path)

    generation_ids: list[str] = []
    seen_generation_ids: set[str] = set()
    total_tokens = None
    tool_requests: Counter[str] = Counter()
    tool_responses: Counter[str] = Counter()
    tool_response_errors = 0
    message_count = 0
    thinking_chars = 0
    text_chars = 0

    for obj in events:
        if obj.get("type") == "complete" and isinstance(obj.get("total_tokens"), int):
            total_tokens = obj["total_tokens"]
            continue
        if obj.get("type") != "message":
            continue
        message_count += 1
        msg = obj.get("message") or {}
        msg_id = msg.get("id")
        if isinstance(msg_id, str) and msg_id.startswith("gen-") and msg_id not in seen_generation_ids:
            seen_generation_ids.add(msg_id)
            generation_ids.append(msg_id)
        for item in msg.get("content") or []:
            item_type = item.get("type")
            if item_type == "thinking":
                thinking_chars += len(item.get("thinking") or "")
            elif item_type == "text":
                text_chars += len(item.get("text") or "")
            elif item_type == "toolRequest":
                name = (((item.get("toolCall") or {}).get("value") or {}).get("name")) or "unknown"
                tool_requests[name] += 1
            elif item_type == "toolResponse":
                name = extract_tool_name_from_response(item)
                if name:
                    tool_responses[name] += 1
                payload = item.get("toolResult") or {}
                if isinstance(payload, dict) and payload.get("isError"):
                    tool_response_errors += 1

    reward = (((result.get("verifier_result") or {}).get("rewards") or {}).get("reward"))
    status = "passed" if reward == 1.0 else "failed"

    agent_execution = result.get("agent_execution") or {}
    agent_start = parse_dt(agent_execution["started_at"]) if agent_execution.get("started_at") else None
    agent_end = parse_dt(agent_execution["finished_at"]) if agent_execution.get("finished_at") else None

    sample_meta = load_sample_metadata(task_id)
    phase1 = phase1_retry.get(uid, {})
    question = sample_meta.get("question") or phase1.get("question")
    mcp_tool_requests = {k: v for k, v in tool_requests.items() if k.startswith("officeqa-arena__")}
    non_mcp_tool_requests = {k: v for k, v in tool_requests.items() if not k.startswith("officeqa-arena__")}

    return {
        "task_id": task_id,
        "uid": uid,
        "uid_num": int(uid[3:]),
        "runner": runner,
        "lane": lane,
        "status": status,
        "reward": reward,
        "question": question,
        "expected_answer": sample_meta.get("expected_answer"),
        "difficulty": sample_meta.get("difficulty"),
        "benchmark_category": sample_meta.get("benchmark_category"),
        "benchmark_mode": sample_meta.get("benchmark_mode"),
        "benchmark_tags": sample_meta.get("benchmark_tags"),
        "source_docs": sample_meta.get("source_docs"),
        "phase1_has_plan": bool(phase1.get("plan")),
        "phase1_feasibility": phase1.get("feasibility"),
        "phase1_computation_type": phase1.get("computation_type"),
        "phase1_answer_format": phase1.get("answer_format"),
        "phase1_estimated_calls": phase1.get("estimated_calls"),
        "phase1_num_data_needs": phase1.get("num_data_needs"),
        "phase1_num_search_queries": phase1.get("num_search_queries"),
        "phase1_functions_needed": phase1.get("functions_needed") or [],
        "domain_family": classify_domain(question or ""),
        "operation_family": classify_operation(question or "", phase1.get("computation_type")),
        "trial_dir": str(trial_dir),
        "goose_path": str(goose_path) if goose_path.exists() else None,
        "stdout_path": str(stdout_path) if stdout_path.exists() else None,
        "trajectory_path": str(traj_path) if traj_path.exists() else None,
        "exception_path": str(exc_path) if exc_path.exists() else None,
        "exception_preview": exc_path.read_text(errors="replace")[:500] if exc_path.exists() else None,
        "agent_execution_start": agent_start.isoformat().replace("+00:00", "Z") if agent_start else None,
        "agent_execution_end": agent_end.isoformat().replace("+00:00", "Z") if agent_end else None,
        "goose_total_tokens": total_tokens,
        "message_count": message_count,
        "thinking_chars": thinking_chars,
        "text_chars": text_chars,
        "generation_ids": generation_ids,
        "tool_requests": dict(tool_requests),
        "tool_request_total": sum(tool_requests.values()),
        "mcp_tool_requests": mcp_tool_requests,
        "mcp_tool_request_total": sum(mcp_tool_requests.values()),
        "non_mcp_tool_requests": non_mcp_tool_requests,
        "tool_sequence_preview": list(tool_requests.elements())[:25],
        "tool_responses_detected": dict(tool_responses),
        "tool_response_error_count": tool_response_errors,
    }


def assign_exports(records: list[dict], export_rows: list[ExportRow]) -> None:
    rows_by_generation_id: dict[str, ExportRow] = {}
    for row in export_rows:
        rows_by_generation_id.setdefault(row.generation_id, row)

    windows: list[tuple[int, datetime, datetime, datetime]] = []
    for idx, rec in enumerate(records):
        if not rec["agent_execution_start"] or not rec["agent_execution_end"]:
            continue
        start = parse_dt(rec["agent_execution_start"])
        end = parse_dt(rec["agent_execution_end"])
        mid = start + (end - start) / 2
        windows.append((idx, start, end, mid))

    assigned: defaultdict[int, list[ExportRow]] = defaultdict(list)
    used_generation_ids: set[str] = set()
    for idx, rec in enumerate(records):
        for gid in rec.get("generation_ids") or []:
            row = rows_by_generation_id.get(gid)
            if not row or gid in used_generation_ids:
                continue
            assigned[idx].append(row)
            used_generation_ids.add(gid)

    unmatched = 0
    for row in export_rows:
        if row.generation_id in used_generation_ids:
            continue
        candidates = []
        for idx, start, end, mid in windows:
            if start <= row.created_at <= end:
                candidates.append((abs((row.created_at - mid).total_seconds()), idx))
        if not candidates:
            unmatched += 1
            continue
        _, idx = min(candidates)
        assigned[idx].append(row)

    for idx, rec in enumerate(records):
        rows = assigned.get(idx, [])
        rec["openrouter_rows_matched"] = len(rows)
        rec["openrouter_generation_ids"] = [r.generation_id for r in rows]
        rec["openrouter_cost_total"] = round(sum(float(r.raw.get("cost_total") or 0) for r in rows), 6)
        rec["openrouter_tokens_prompt"] = sum(int(r.raw.get("tokens_prompt") or 0) for r in rows)
        rec["openrouter_tokens_completion"] = sum(int(r.raw.get("tokens_completion") or 0) for r in rows)
        rec["openrouter_tokens_reasoning"] = sum(int(r.raw.get("tokens_reasoning") or 0) for r in rows)
        rec["openrouter_tokens_cached"] = sum(int(r.raw.get("tokens_cached") or 0) for r in rows)
        rec["openrouter_finish_reasons"] = dict(Counter(r.raw.get("finish_reason_normalized") or "" for r in rows))
        rec["openrouter_users"] = dict(Counter(r.raw.get("user") or "" for r in rows))
        rec["openrouter_providers"] = dict(Counter(r.raw.get("provider_name") or "" for r in rows))
        if rec["goose_total_tokens"]:
            rec["usd_per_1k_goose_tokens"] = round(1000 * rec["openrouter_cost_total"] / rec["goose_total_tokens"], 6)
        else:
            rec["usd_per_1k_goose_tokens"] = None
    return unmatched


def write_outputs(run_root: Path, records: list[dict], unmatched_exports: int) -> None:
    out_dir = run_root / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "trace_index.json").write_text(json.dumps(records, indent=2) + "\n")
    with (out_dir / "trace_index.jsonl").open("w") as f:
        for row in records:
            f.write(json.dumps(row) + "\n")

    fieldnames = [
        "task_id",
        "uid",
        "uid_num",
        "runner",
        "lane",
        "status",
        "reward",
        "difficulty",
        "domain_family",
        "operation_family",
        "phase1_feasibility",
        "phase1_computation_type",
        "goose_total_tokens",
        "tool_request_total",
        "mcp_tool_request_total",
        "message_count",
        "thinking_chars",
        "text_chars",
        "openrouter_rows_matched",
        "openrouter_cost_total",
        "openrouter_tokens_prompt",
        "openrouter_tokens_completion",
        "openrouter_tokens_reasoning",
        "openrouter_tokens_cached",
        "usd_per_1k_goose_tokens",
        "exception_path",
        "trial_dir",
    ]
    with (out_dir / "trace_index.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            writer.writerow({k: row.get(k) for k in fieldnames})

    tool_totals: Counter[str] = Counter()
    mcp_tool_totals: Counter[str] = Counter()
    for row in records:
        tool_totals.update(row["tool_requests"])
        mcp_tool_totals.update(row["mcp_tool_requests"])

    tool_rows = []
    by_tool_status: dict[str, Counter[str]] = defaultdict(Counter)
    for row in records:
        for tool, count in row["tool_requests"].items():
            by_tool_status[tool]["tasks"] += 1
            by_tool_status[tool][row["status"]] += 1
            by_tool_status[tool]["calls"] += count
    for tool, counts in sorted(by_tool_status.items(), key=lambda kv: (-kv[1]["calls"], kv[0])):
        task_count = counts["tasks"] or 1
        tool_rows.append(
            {
                "tool": tool,
                "calls": counts["calls"],
                "tasks": counts["tasks"],
                "passed_tasks": counts["passed"],
                "failed_tasks": counts["failed"],
                "task_pass_rate": round(counts["passed"] / task_count, 4),
                "is_mcp": tool.startswith("officeqa-arena__"),
            }
        )
    with (out_dir / "tool_summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["tool", "is_mcp", "calls", "tasks", "passed_tasks", "failed_tasks", "task_pass_rate"],
        )
        writer.writeheader()
        writer.writerows(tool_rows)

    family_rows = []
    for group_key in ("domain_family", "operation_family", "phase1_computation_type", "phase1_feasibility"):
        buckets: dict[str, list[dict]] = defaultdict(list)
        for row in records:
            buckets[str(row.get(group_key) or "unknown")].append(row)
        for value, bucket in sorted(buckets.items()):
            family_rows.append(
                {
                    "group": group_key,
                    "value": value,
                    "tasks": len(bucket),
                    "passed": sum(1 for r in bucket if r["status"] == "passed"),
                    "failed": sum(1 for r in bucket if r["status"] == "failed"),
                    "pass_rate": round(sum(1 for r in bucket if r["status"] == "passed") / len(bucket), 4),
                    "avg_goose_tokens": round(sum(r["goose_total_tokens"] or 0 for r in bucket) / len(bucket), 2),
                    "avg_tool_calls": round(sum(r["tool_request_total"] for r in bucket) / len(bucket), 2),
                    "avg_mcp_tool_calls": round(sum(r["mcp_tool_request_total"] for r in bucket) / len(bucket), 2),
                    "avg_openrouter_cost": round(sum(r["openrouter_cost_total"] for r in bucket) / len(bucket), 6),
                }
            )
    with (out_dir / "question_family_summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "group",
                "value",
                "tasks",
                "passed",
                "failed",
                "pass_rate",
                "avg_goose_tokens",
                "avg_tool_calls",
                "avg_mcp_tool_calls",
                "avg_openrouter_cost",
            ],
        )
        writer.writeheader()
        writer.writerows(family_rows)

    exception_rows = []
    for row in records:
        if not row["exception_path"]:
            continue
        exception_rows.append(
            {
                "task_id": row["task_id"],
                "uid": row["uid"],
                "status": row["status"],
                "runner": row["runner"],
                "tool_request_total": row["tool_request_total"],
                "openrouter_cost_total": row["openrouter_cost_total"],
                "goose_total_tokens": row["goose_total_tokens"],
                "exception_preview": (row["exception_preview"] or "").replace("\n", " ")[:300],
            }
        )
    with (out_dir / "exceptions.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "task_id",
                "uid",
                "status",
                "runner",
                "tool_request_total",
                "openrouter_cost_total",
                "goose_total_tokens",
                "exception_preview",
            ],
        )
        writer.writeheader()
        writer.writerows(exception_rows)

    def top_tasks(rows: list[dict], key: str, n: int = 15) -> list[dict]:
        filtered = [r for r in rows if r.get(key) not in (None, 0, 0.0)]
        return sorted(filtered, key=lambda r: r[key], reverse=True)[:n]

    summary = {
        "tasks": len(records),
        "passed": sum(1 for r in records if r["status"] == "passed"),
        "failed": sum(1 for r in records if r["status"] == "failed"),
        "with_goose_tokens": sum(1 for r in records if r["goose_total_tokens"] is not None),
        "with_openrouter_join": sum(1 for r in records if r["openrouter_rows_matched"] > 0),
        "unmatched_openrouter_rows": unmatched_exports,
        "total_openrouter_cost_joined": round(sum(r["openrouter_cost_total"] for r in records), 6),
        "total_goose_tokens": sum(r["goose_total_tokens"] or 0 for r in records),
        "top_tools": tool_totals.most_common(25),
        "top_mcp_tools": mcp_tool_totals.most_common(25),
        "tasks_with_exceptions": len(exception_rows),
        "exact_generation_id_matches": sum(1 for r in records if set(r.get("generation_ids") or []) & set(r.get("openrouter_generation_ids") or [])),
        "top_cost_tasks": [
            {
                "task_id": r["task_id"],
                "status": r["status"],
                "openrouter_cost_total": r["openrouter_cost_total"],
                "goose_total_tokens": r["goose_total_tokens"],
                "tool_request_total": r["tool_request_total"],
                "domain_family": r["domain_family"],
                "operation_family": r["operation_family"],
            }
            for r in top_tasks(records, "openrouter_cost_total")
        ],
        "top_token_tasks": [
            {
                "task_id": r["task_id"],
                "status": r["status"],
                "goose_total_tokens": r["goose_total_tokens"],
                "openrouter_cost_total": r["openrouter_cost_total"],
                "tool_request_total": r["tool_request_total"],
            }
            for r in top_tasks(records, "goose_total_tokens")
        ],
        "top_tool_heavy_tasks": [
            {
                "task_id": r["task_id"],
                "status": r["status"],
                "tool_request_total": r["tool_request_total"],
                "mcp_tool_request_total": r["mcp_tool_request_total"],
                "openrouter_cost_total": r["openrouter_cost_total"],
            }
            for r in top_tasks(records, "tool_request_total")
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    family_lookup: dict[tuple[str, str], dict] = {}
    for row in family_rows:
        family_lookup[(row["group"], row["value"])] = row
    top_domain_rows = sorted(
        [r for r in family_rows if r["group"] == "domain_family"],
        key=lambda r: (-r["tasks"], r["value"]),
    )[:10]
    top_op_rows = sorted(
        [r for r in family_rows if r["group"] == "operation_family"],
        key=lambda r: (-r["tasks"], r["value"]),
    )[:10]

    lines = [
        f"# Trace Analysis: {run_root.name}",
        "",
        f"- Tasks: `{summary['passed']}` passed / `{summary['failed']}` failed / `{summary['tasks']}` total",
        f"- Tasks with goose token totals: `{summary['with_goose_tokens']}`",
        f"- Tasks with OpenRouter row assignment: `{summary['with_openrouter_join']}`",
        f"- Tasks with exact generation-id provider matches: `{summary['exact_generation_id_matches']}`",
        f"- Unmatched OpenRouter rows: `{summary['unmatched_openrouter_rows']}`",
        f"- Joined OpenRouter cost: `${summary['total_openrouter_cost_joined']:.3f}`",
        f"- Total goose tokens: `{summary['total_goose_tokens']}`",
        f"- Tasks with exceptions: `{summary['tasks_with_exceptions']}`",
        "",
        "## Top Tools",
    ]
    for name, count in summary["top_tools"][:20]:
        lines.append(f"- `{name}`: `{count}`")
    lines.extend(["", "## Top MCP Tools"])
    for name, count in summary["top_mcp_tools"][:15]:
        lines.append(f"- `{name}`: `{count}`")
    lines.extend(["", "## Domain Families"])
    for row in top_domain_rows:
        lines.append(
            f"- `{row['value']}`: `{row['passed']}/{row['tasks']}` passed, avg cost `${row['avg_openrouter_cost']:.4f}`, avg tools `{row['avg_tool_calls']}`"
        )
    lines.extend(["", "## Operation Families"])
    for row in top_op_rows:
        lines.append(
            f"- `{row['value']}`: `{row['passed']}/{row['tasks']}` passed, avg cost `${row['avg_openrouter_cost']:.4f}`, avg MCP tools `{row['avg_mcp_tool_calls']}`"
        )
    lines.extend(["", "## Most Expensive Tasks"])
    for row in summary["top_cost_tasks"][:10]:
        lines.append(
            f"- `{row['task_id']}` `{row['status']}` `${row['openrouter_cost_total']:.4f}` tools `{row['tool_request_total']}` tokens `{row['goose_total_tokens']}`"
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    run_root = POOL_ROOT / args.run_label
    trace_root = run_root / "full_traces"
    export_paths = [Path(p) for p in args.openrouter_csv]
    if not export_paths:
        downloads = Path.home() / "Downloads"
        export_paths = [
            downloads / "openrouter_activity_2026-04-02.csv",
            downloads / "openrouter_activity_2026-04-02 (1).csv",
        ]

    export_rows = read_openrouter_exports(export_paths)
    phase1_retry = load_phase1_retry_metadata()
    records = [parse_trial(path, phase1_retry) for path in iter_trial_result_paths(trace_root)]
    records.sort(key=lambda r: r["task_id"])
    unmatched = assign_exports(records, export_rows)
    write_outputs(run_root, records, unmatched)
    print(
        json.dumps(
            {
                "run_label": args.run_label,
                "tasks": len(records),
                "with_openrouter_join": sum(1 for r in records if r["openrouter_rows_matched"] > 0),
                "total_openrouter_cost_joined": round(sum(r["openrouter_cost_total"] for r in records), 6),
                "analysis_dir": str((run_root / "analysis").relative_to(ROOT)),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
