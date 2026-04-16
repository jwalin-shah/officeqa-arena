#!/usr/bin/env python3
"""Oracle mode solver: v14 intern + LLM mentor."""
import os
import subprocess
import sys
import re
import json
from pathlib import Path

# Load .env
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().split('\n'):
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: pip install openai")
    sys.exit(1)

# Init LLM client
api_key = os.environ.get("NVIDIA_API_KEY")
api_base = os.environ.get("NVIDIA_API_BASE")
model = os.environ.get("OFFICEQA_MODEL", "deepseek-ai/deepseek-v3.2")

if not api_key or not api_base:
    print("ERROR: Need NVIDIA_API_KEY and NVIDIA_API_BASE in .env")
    sys.exit(1)

client = OpenAI(api_key=api_key, base_url=api_base)

def oracle_solve(question: str) -> str:
    """Run v14 intern, get evidence, send to LLM mentor."""

    # Phase 1: Run v14 to get evidence briefing
    print(f"[INTERN] Analyzing: {question[:60]}...", file=sys.stderr)
    result = subprocess.run(
        ["python3", "v14/solve_v14.py", question],
        capture_output=True,
        text=True,
        timeout=30
    )
    briefing = result.stdout

    # Extract evidence lines from v14 output
    evidence_lines = [line for line in briefing.split('\n') if line.startswith('Evidence')]
    evidence_summary = '\n'.join(evidence_lines[:5]) if evidence_lines else "(no evidence found)"

    # Phase 2: Send to LLM mentor with evidence
    print(f"[MENTOR] Extracting answer...", file=sys.stderr)
    mentor_prompt = f"""You are a financial analyst answering questions about U.S. Treasury Bulletin data.

QUESTION: {question}

INTERN BRIEFING:
{briefing}

TASK: Extract a specific numeric answer or value from the evidence above.
- If you find a clear answer, return ONLY the numeric value or list of values.
- If you cannot find an answer, return "NO_ANSWER".
- Do not include units or explanations.

ANSWER:"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": mentor_prompt}],
            max_tokens=256,
            temperature=0.1,
        )
        answer = response.choices[0].message.content.strip()
        return answer
    except Exception as e:
        return f"ERROR: {e}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: oracle_solve.py 'question'")
        sys.exit(1)

    question = sys.argv[1]
    answer = oracle_solve(question)
    print(answer)
