"""
Custom arena harness that uploads project source to /installed-agent/.

The arena competition platform copies our project to /installed-agent/ before
running the agent. `arena test` (local Docker) skips this step. This harness
replicates it, making `arena test` identical to submission.

Same principle as daytona_sandbox.py's _discover_upload_files() — we explicitly
push the files we need rather than relying on the platform to do it.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from arena_sdk.harness.openhands_sdk import OpenHandsSDKAgent

if TYPE_CHECKING:
    from harbor.environments.base import BaseEnvironment

_PROJECT_ROOT = Path(__file__).parent


class OfficeQALocalHarness(OpenHandsSDKAgent):
    """OpenHandsSDKAgent + uploads project source to /installed-agent/.

    Directories uploaded: server/, prompts/, overrides/
    Files uploaded:       run_mcp.sh, install.sh, requirements.txt
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
