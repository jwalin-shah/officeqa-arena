import json
import os
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

def post_telemetry(path: str, payload: dict) -> None:
    """POST payload to telemetry server. Fire-and-forget."""
    url = os.environ.get("TELEMETRY_URL", "").rstrip("/")
    if not url:
        return
    full_url = f"{url}/{path.lstrip('/')}"
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            full_url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

def send_telemetry_async(path: str, payload: dict) -> None:
    """Send telemetry in a background thread."""
    t = threading.Thread(target=post_telemetry, args=(path, payload), daemon=True)
    t.start()


def summarize_trajectory(
    trajectory_path: Path,
    *,
    task_id: str = "",
    harness: str = "",
) -> dict[str, Any] | None:
    """Parse a harbor trajectory.json into a compact telemetry summary."""
    if not trajectory_path.exists():
        return None

    try:
        data = json.loads(trajectory_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    steps = data.get("steps", [])
    metrics = data.get("final_metrics", {})

    iterations = 0
    tool_counts: dict[str, int] = {}
    tool_sequence: list[str] = []
    answer_preview = ""
    started_at = None
    ended_at = None

    for step in steps:
        ts = step.get("timestamp")
        if ts:
            started_at = started_at or ts
            ended_at = ts

        if step.get("source") == "agent":
            iterations += 1

        for tc in step.get("tool_calls", []):
            name = tc.get("function_name") or tc.get("name") or "unknown"
            tool_counts[name] = tool_counts.get(name, 0) + 1
            tool_sequence.append(name)

        obs = step.get("observation", {})
        if isinstance(obs, dict):
            for result in obs.get("results", []):
                content = result.get("content", "")
                if "answer.txt" in content and ">" in content:
                    answer_preview = content[-200:]

    used_delegate = "delegate" in tool_counts or "DelegateTool" in tool_counts

    answer_source = "unknown"
    for tool_name in reversed(tool_sequence):
        if tool_name in {
            "extract_values",
            "search_canonical",
            "search_tables",
            "compute_expression",
            "grep_corpus",
            "query_table_rows",
            "verify_answer",
            "submit_answer",
        }:
            answer_source = tool_name
            break

    wall_time_s = None
    if started_at and ended_at:
        try:
            wall_time_s = round(
                (
                    datetime.fromisoformat(ended_at) -
                    datetime.fromisoformat(started_at)
                ).total_seconds(),
                3,
            )
        except ValueError:
            wall_time_s = None

    summary: dict[str, Any] = {
        "task_id": task_id,
        "harness": harness,
        "session_id": data.get("session_id", ""),
        "agent": data.get("agent", ""),
        "iterations": iterations,
        "total_steps": len(steps),
        "total_tool_calls": sum(tool_counts.values()),
        "tool_counts": tool_counts,
        "tool_sequence": tool_sequence[-20:],
        "used_delegate": used_delegate,
        "answer_source": answer_source,
        "answer_preview": answer_preview[-100:],
        "started_at": started_at,
        "ended_at": ended_at,
        "wall_time_s": wall_time_s,
        "cost_usd": metrics.get("total_cost_usd", 0),
        "prompt_tokens": metrics.get("total_prompt_tokens", 0),
        "completion_tokens": metrics.get("total_completion_tokens", 0),
        "cached_tokens": metrics.get("total_cached_tokens", 0),
    }
    return summary

async def sync_project_to_container(environment, project_root: Path):
    """Upload core server files and setup scripts to /installed-agent/."""
    # Ensure target dir exists
    await environment.exec(command="mkdir -p /installed-agent/server")
    
    # Upload server/ directory
    server_dir = project_root / "server"
    if server_dir.is_dir():
        await environment.upload_dir(
            source_dir=str(server_dir),
            target_dir="/installed-agent/server",
        )
    
    # Upload setup and launch scripts
    for fname in ("run_mcp.sh", "install.sh", "requirements.txt", ".env"):
        f = project_root / fname
        if f.exists():
            await environment.upload_file(
                source_path=f,
                target_path=f"/installed-agent/{fname}",
            )
    
    await environment.exec(command="chmod +x /installed-agent/run_mcp.sh")
