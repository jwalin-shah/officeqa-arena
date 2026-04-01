"""
Custom arena harness that uploads project source to /installed-agent/.

The arena competition platform copies our project to /installed-agent/ before
running the agent. `arena test` (local Docker) skips this step. This harness
replicates it, making `arena test` identical to submission.

Same principle as daytona_sandbox.py's _discover_upload_files() — we explicitly
push the files we need rather than relying on the platform to do it.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from arena_sdk.harness.openhands_sdk import OpenHandsSDKAgent

if TYPE_CHECKING:
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext

_PROJECT_ROOT = Path(__file__).parent
_TELEMETRY_URL = os.environ.get("TELEMETRY_URL", "")


def _post_trajectory_summary(payload: dict) -> None:
    """POST trajectory summary to telemetry server. Fire-and-forget."""
    url = _TELEMETRY_URL.rstrip("/") + "/trajectory"
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _summarize_trajectory(trajectory_path: Path, task_name: str = "") -> dict | None:
    """Parse trajectory.json and build a compact summary."""
    if not trajectory_path.exists():
        return None
    try:
        data = json.load(open(trajectory_path))
    except (json.JSONDecodeError, OSError):
        return None

    steps = data.get("steps", [])
    metrics = data.get("final_metrics", {})

    # Count iterations (agent messages) and tool calls
    iterations = 0
    tool_counts: dict[str, int] = {}
    tool_sequence: list[str] = []
    answer_preview = ""

    for step in steps:
        source = step.get("source", "")
        if source == "agent":
            iterations += 1
        for tc in step.get("tool_calls", []):
            name = tc.get("function_name") or tc.get("name") or "unknown"
            tool_counts[name] = tool_counts.get(name, 0) + 1
            tool_sequence.append(name)
        # Check if agent wrote an answer via terminal
        obs = step.get("observation", {})
        if isinstance(obs, dict):
            for r in obs.get("results", []):
                content = r.get("content", "")
                if "answer.txt" in content and ">" in content:
                    # Grab the last answer write
                    answer_preview = content[-200:]

    # Detect delegation
    used_delegate = "delegate" in tool_counts or "DelegateTool" in tool_counts

    # Detect answer source from tool sequence (last MCP tool before terminal writes)
    answer_source = "unknown"
    for t in reversed(tool_sequence):
        if t in ("extract_values", "search_canonical", "search_tables",
                 "compute_expression", "grep_corpus", "query_table_rows"):
            answer_source = t
            break

    return {
        "task_id": task_name,
        "iterations": iterations,
        "total_steps": len(steps),
        "total_tool_calls": sum(tool_counts.values()),
        "tool_counts": tool_counts,
        "tool_sequence": tool_sequence[-20:],  # last 20 calls
        "cost_usd": metrics.get("total_cost_usd", 0),
        "prompt_tokens": metrics.get("total_prompt_tokens", 0),
        "completion_tokens": metrics.get("total_completion_tokens", 0),
        "cached_tokens": metrics.get("total_cached_tokens", 0),
        "used_delegate": used_delegate,
        "answer_source": answer_source,
        "answer_preview": answer_preview[-100:],
    }


class OfficeQALocalHarness(OpenHandsSDKAgent):
    """OpenHandsSDKAgent + uploads project source to /installed-agent/.

    Directories uploaded: server/, prompts/, overrides/
    Files uploaded:       run_mcp.sh, install.sh, requirements.txt

    Post-run: parses trajectory.json and POSTs a summary to TELEMETRY_URL.
    """

    async def setup(self, environment: "BaseEnvironment") -> None:
        # Step 1: install OpenHands SDK and generate run_agent.py (same as default)
        await super().setup(environment)

        # Step 2: upload our project source — what the competition platform does
        # automatically but arena test (local Docker) skips.
        for dir_name in ("server", "prompts", "overrides"):
            d = _PROJECT_ROOT / dir_name
            if d.is_dir():
                await environment.exec(command=f"mkdir -p /installed-agent/{dir_name}")
                await environment.upload_dir(
                    source_dir=str(d),
                    target_dir=f"/installed-agent/{dir_name}",
                )

        for fname in ("run_mcp.sh", "install.sh", "requirements.txt"):
            f = _PROJECT_ROOT / fname
            if f.exists():
                await environment.upload_file(
                    source_path=f,
                    target_path=f"/installed-agent/{fname}",
                )

        # Upload sub-agent definitions for DelegateTool
        agents_dir = _PROJECT_ROOT / ".openhands" / "agents"
        if agents_dir.is_dir():
            for target_base in ("/installed-agent/.openhands/agents", "/workspace/.openhands/agents"):
                await environment.exec(command=f"mkdir -p {target_base}")
                await environment.upload_dir(
                    source_dir=str(agents_dir),
                    target_dir=target_base,
                )

        await environment.exec(command="chmod +x /installed-agent/run_mcp.sh")

    def populate_context_post_run(self, context: "AgentContext") -> None:
        """Extract metrics from trajectory + POST summary to telemetry server."""
        # Let the parent extract cost/tokens into context
        super().populate_context_post_run(context)

        # Send trajectory summary to telemetry server
        if not _TELEMETRY_URL:
            return

        trajectory_file = self.logs_dir / "trajectory.json"
        task_name = os.environ.get("ARENA_TASK_ID", "") or getattr(context, "task_name", "")
        summary = _summarize_trajectory(trajectory_file, task_name)
        if summary:
            t = threading.Thread(target=_post_trajectory_summary, args=(summary,), daemon=True)
            t.start()
