"""
Custom arena harness for Goose: injects domain-specific recipe instructions
and uploads project source to /installed-agent/.

Replaces the generic harbor recipe instructions with our Treasury Data Analyst
system prompt from prompts/goose_instructions.md.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from arena_sdk.harness.goose import GooseAgent

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


class OfficeQAGooseHarness(GooseAgent):
    """GooseAgent with domain-specific recipe instructions + file upload.

    Directories uploaded: server/, skills_goose/
    Files uploaded:       run_mcp.sh, install.sh, requirements.txt

    Overrides _create_recipe_yaml to replace harbor's generic instructions
    with our Treasury Data Analyst domain prompt.
    """

    async def setup(self, environment: "BaseEnvironment") -> None:
        # Step 1: standard Goose setup (installs Goose CLI)
        await super().setup(environment)

        # Step 2: upload project source to /installed-agent/
        for dir_name in ("server",):
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

        await environment.exec(command="chmod +x /installed-agent/run_mcp.sh")

    def _create_recipe_yaml(self, instruction: str) -> str:
        """Override to inject domain-specific instructions from goose_instructions.md."""
        # Load domain instructions
        instructions_path = _PROJECT_ROOT / "prompts" / "goose_instructions.md"
        if instructions_path.exists():
            domain_instructions = instructions_path.read_text().strip()
        else:
            domain_instructions = (
                "You are a Treasury Data Analyst. "
                "Answer questions about U.S. Treasury Bulletin data "
                "by querying the database and computing answers."
            )

        # Build extensions list
        extensions: list[dict[str, Any]] = [
            {"type": "builtin", "name": "developer"},
        ]
        extensions.extend(self._build_mcp_extensions())

        recipe: dict[str, Any] = {
            "version": "1.0.0",
            "title": "officeqa-task",
            "description": "OfficeQA Treasury data question answering",
            "instructions": domain_instructions,
            "prompt": instruction,
            "extensions": extensions,
        }
        return yaml.dump(recipe, default_flow_style=False, sort_keys=False)

    def populate_context_post_run(self, context: "AgentContext") -> None:
        """Extract trajectory and POST summary to telemetry server."""
        super().populate_context_post_run(context)

        if not _TELEMETRY_URL:
            return

        # Goose logs are in goose.txt, trajectory.json is built by harbor
        trajectory_file = self.logs_dir / "trajectory.json"
        if not trajectory_file.exists():
            return

        try:
            data = json.loads(trajectory_file.read_text())
            steps = data.get("steps", [])
            tool_counts: dict[str, int] = {}
            tool_sequence: list[str] = []

            for step in steps:
                for tc in step.get("tool_calls", []):
                    name = tc.get("function_name", "unknown")
                    tool_counts[name] = tool_counts.get(name, 0) + 1
                    tool_sequence.append(name)

            summary = {
                "task_id": os.environ.get("ARENA_TASK_ID", ""),
                "harness": "goose",
                "total_steps": len(steps),
                "total_tool_calls": sum(tool_counts.values()),
                "tool_counts": tool_counts,
                "tool_sequence": tool_sequence[-20:],
            }
            t = threading.Thread(
                target=_post_trajectory_summary, args=(summary,), daemon=True
            )
            t.start()
        except Exception:
            pass
