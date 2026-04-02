"""Goose harness using unified utilities."""
from __future__ import annotations
import os
import json
from pathlib import Path
from typing import TYPE_CHECKING
import yaml

from arena_sdk.harness.goose import GooseAgent
from scripts.harness_utils import sync_project_to_container, send_telemetry_async

if TYPE_CHECKING:
    from harbor.environments.base import BaseEnvironment

_PROJECT_ROOT = Path(__file__).parent

class OfficeQAGooseHarness(GooseAgent):
    async def setup(self, environment: "BaseEnvironment") -> None:
        await super().setup(environment)
        await sync_project_to_container(environment, _PROJECT_ROOT)

    def _create_recipe_yaml(self, instruction: str) -> str:
        instructions_path = _PROJECT_ROOT / "prompts" / "goose_instructions.md"
        domain_instructions = instructions_path.read_text().strip() if instructions_path.exists() else "Treasury Data Analyst"
        
        recipe = {
            "version": "1.0.0",
            "title": "officeqa-task",
            "instructions": domain_instructions,
            "prompt": instruction,
            "extensions": [{"type": "builtin", "name": "developer"}] + self._build_mcp_extensions(),
        }
        return yaml.dump(recipe, default_flow_style=False, sort_keys=False)

    def populate_context_post_run(self, context):
        super().populate_context_post_run(context)
        traj_file = self.logs_dir / "trajectory.json"
        if traj_file.exists():
            try:
                data = json.loads(traj_file.read_text())
                steps = data.get("steps", [])
                summary = {
                    "task_id": os.environ.get("ARENA_TASK_ID", ""),
                    "harness": "goose",
                    "total_steps": len(steps),
                }
                send_telemetry_async("/trajectory", summary)
            except Exception: pass
