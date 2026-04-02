"""Goose harness using unified utilities."""
from __future__ import annotations
import os
from pathlib import Path
from typing import TYPE_CHECKING
import yaml

from arena_sdk.harness.goose import GooseAgent
from scripts.harness_utils import send_telemetry_async, summarize_trajectory, sync_project_to_container

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
        
        # Inject skills into instructions
        skills_dir = _PROJECT_ROOT / "skills_goose"
        if skills_dir.is_dir():
            domain_instructions += "\n\n# ADDITIONAL DOMAIN KNOWLEDGE\n"
            for skill_path in sorted(skills_dir.glob("*/SKILL.md")):
                skill_content = skill_path.read_text().strip()
                domain_instructions += f"\n## {skill_path.parent.name}\n{skill_content}\n"

        # Use literal block scalar for instructions to avoid YAML escaping issues
        # (em-dashes, brackets in function signatures, etc.)
        class _LiteralStr(str):
            pass
        def _literal_representer(dumper, data):
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        dumper = yaml.Dumper
        dumper.add_representer(_LiteralStr, _literal_representer)

        recipe = {
            "version": "1.0.0",
            "title": "officeqa-task",
            "instructions": _LiteralStr(domain_instructions),
            "prompt": _LiteralStr(instruction),
            "extensions": self._build_mcp_extensions(),
        }
        return yaml.dump(recipe, Dumper=dumper, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def populate_context_post_run(self, context):
        super().populate_context_post_run(context)
        traj_file = self.logs_dir / "trajectory.json"
        if traj_file.exists():
            try:
                summary = summarize_trajectory(
                    traj_file,
                    task_id=os.environ.get("ARENA_TASK_ID", ""),
                    harness="goose",
                )
                if summary:
                    summary["run_id"] = os.environ.get("ARENA_RUN_ID", "")
                    summary["source"] = os.environ.get("TELEMETRY_SOURCE", "goose")
                    send_telemetry_async("/trajectory", summary)
            except Exception:
                pass
