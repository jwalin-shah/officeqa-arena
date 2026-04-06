#!/bin/bash
# Deploy v12 prompt and run A/B test on Daytona sandboxes
# Usage: ./deploy_and_test.sh
set -euo pipefail

SB1=b300439b-d280-4636-acda-0490f1cb0f1e
SB2=a29635ff-ac47-4fe1-a10a-484fd7cf5c14

TASKS="UID0004 UID0013 UID0040 UID0102 UID0030 UID0034 UID0046 UID0069 UID0075 UID0086 UID0099 UID0113 UID0121 UID0149 UID0159 UID0171 UID0204 UID0220 UID0239 UID0246"

# Step 1: Upload v12 prompt via SSH
echo "=== Uploading v12 prompt to SB1 ==="
daytona ssh $SB1 << 'SSHEOF'
cp /home/daytona/prompt.txt /home/daytona/prompt_v12.txt

python3 << 'PYEOF'
t = open("/home/daytona/prompt_v12.txt").read()
eff = """
EFFICIENCY RULES:
- After your FIRST grep, read the matching page file. Do not grep more than 3 times.
- If a python3 -c script fails, read the raw data and compute by hand. Do NOT rewrite the script.
- By step 15 you MUST have written answer.txt. If unsure, write your best guess NOW.
- Never cat the full .txt or .json file. Use grep or page files only.
"""
t = t.replace("A wrong answer beats no answer.\n", "A wrong answer beats no answer.\n" + eff)
open("/home/daytona/prompt_v12.txt", "w").write(t)
print(f"v12 prompt: {len(t.splitlines())} lines")
PYEOF
SSHEOF

echo "=== Running v12 (anti-spiral) on SB1 ==="
daytona ssh $SB1 << SSHEOF
/home/daytona/run_ab_v11.sh /home/daytona/prompt_v12.txt 2>&1 | tee /home/daytona/v12_results.log
SSHEOF

echo ""
echo "=== SB1 (v12) done ==="
