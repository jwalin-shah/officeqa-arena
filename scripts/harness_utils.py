import json
import os
import threading
import urllib.request
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
