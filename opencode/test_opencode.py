"""Test opencode harness locally via Daytona sandbox.

Simulates what harbor does:
1. Create sandbox (4 CPU, 8GB RAM, 10GB disk)
2. Install opencode (via nvm + npm)
3. Write opencode.json config (MCP, agents, permissions)
4. Write INSTRUCTIONS.md via base64 decode (MCP bootstrap simulation)
5. Put sample task files in /app/resources/
6. Run opencode --model=... run --format=json -- "question"
7. Check /app/answer.txt
"""

import json
import os
import sys
from pathlib import Path

from daytona_sdk import Daytona, DaytonaConfig, CreateSandboxParams

OPENROUTER_API_KEY = os.environ.get(
    "OPENROUTER_API_KEY",
    "REDACTED",
)

MODEL = "openrouter/minimax/minimax-m2.5"

# Sample question (UID0005 - a known easy one)
DEFAULT_QUESTION = "What was the total public debt outstanding at the end of fiscal year 1940, in millions of dollars?"

# The opencode.json config that harbor would write
OPENCODE_CONFIG = {
    "mcp": {
        "bootstrap": {
            "type": "local",
            "command": ["/bin/bash", "-c", "sleep infinity"],
        }
    },
    "provider": {
        "openrouter": {
            "models": {
                "minimax/minimax-m2.5": {}
            }
        }
    },
    "instructions": ["/app/resources/INSTRUCTIONS.md"],
    "agents": {
        "build": {
            "maxTokens": 8000,
            "reasoningEffort": "high",
            "steps": 30,
        }
    },
    "permission": {
        "bash": "allow",
        "write": "allow",
        "edit": "allow",
        "read": "allow",
        "grep": "allow",
        "glob": "allow",
        "list": "allow",
        "todowrite": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "question": "deny",
    },
    "snapshot": False,
}

INSTRUCTIONS_MD = Path(__file__).parent / "INSTRUCTIONS.md"


def main():
    question = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUESTION

    print("Creating Daytona sandbox...")
    config = DaytonaConfig()
    daytona = Daytona(config)

    sandbox = daytona.create(
        CreateSandboxParams(
            language="python",
            resources={
                "cpu": 4,
                "memory": 8,
                "disk": 10,
            },
        ),
        timeout=120,
    )
    print(f"Sandbox created: {sandbox.id}")

    try:
        _run_test(sandbox, question)
    finally:
        print(f"\nSandbox ID: {sandbox.id} (not auto-deleted)")
        print("To delete: daytona sandbox delete " + sandbox.id)


def _run_test(sandbox, question):
    def run(cmd, timeout=60):
        r = sandbox.process.exec(cmd, timeout=timeout)
        if r.exit_code != 0:
            print(f"FAIL [{r.exit_code}]: {cmd[:80]}")
            print(f"  stdout: {r.result[:500] if r.result else 'None'}")
        return r

    # 1. Install opencode via nvm + npm
    print("\n--- Installing opencode ---")
    run(
        "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash",
        timeout=60,
    )
    r = run(
        'export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && '
        "nvm install 22 && npm install -g opencode-ai@latest && opencode --version",
        timeout=120,
    )
    print(f"  opencode version: {r.result.strip()[-40:]}")

    # 2. Create /app/resources/ and write INSTRUCTIONS.md
    print("\n--- Setting up files ---")
    run("mkdir -p /app/resources")

    instructions_b64 = INSTRUCTIONS_MD.read_bytes()
    import base64
    b64 = base64.b64encode(instructions_b64).decode()
    run(f"echo '{b64}' | base64 -d > /app/resources/INSTRUCTIONS.md")
    r = run("wc -l /app/resources/INSTRUCTIONS.md")
    print(f"  INSTRUCTIONS.md: {r.result.strip()}")

    # 3. Write sample task data (you'd replace this with real page files)
    # For now, create a minimal test file
    run("""cat > /app/resources/treasury_bulletin_1941_page_5.txt << 'TASKEOF'
TABLE 1.—PUBLIC DEBT OUTSTANDING AT END OF FISCAL YEARS
(In millions of dollars)

Fiscal year    |  Total public debt
1935           |  28,701
1936           |  33,779
1937           |  36,425
1938           |  37,165
1939           |  40,440
1940           |  42,968
1941           |  48,961
TASKEOF""")

    # 4. Write opencode.json config
    print("\n--- Writing opencode config ---")
    config_json = json.dumps(OPENCODE_CONFIG, indent=2)
    run(f"mkdir -p ~/.config/opencode && cat > ~/.config/opencode/opencode.json << 'CFGEOF'\n{config_json}\nCFGEOF")
    r = run("cat ~/.config/opencode/opencode.json | head -5")
    print(f"  config: {r.result.strip()[:100]}")

    # 5. Set env and run opencode
    print(f"\n--- Running opencode with question ---")
    print(f"  Q: {question[:80]}...")

    import shlex
    escaped_q = shlex.quote(question)

    r = run(
        f'export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && '
        f"export OPENROUTER_API_KEY={OPENROUTER_API_KEY} && "
        f"export OPENCODE_FAKE_VCS=git && "
        f"cd /app && "
        f"opencode --model={MODEL} run --format=json -- {escaped_q} "
        f"2>&1 | tee /tmp/opencode_output.txt",
        timeout=300,
    )
    print(f"  Output (last 500 chars): ...{r.result[-500:] if r.result else 'None'}")

    # 6. Check answer
    print("\n--- Checking answer ---")
    r = run("cat /app/answer.txt 2>/dev/null || echo 'NO ANSWER FILE'")
    print(f"  Answer: {r.result.strip()}")
    print(f"  Expected: 42968 (or 42,968)")

    # 7. Show opencode output summary
    r = run("wc -l /tmp/opencode_output.txt 2>/dev/null")
    print(f"  Output lines: {r.result.strip()}")


if __name__ == "__main__":
    main()
