#!/usr/bin/env python3
"""Direct runner: Question → solve_v14 → DeepSeek v3.2 → Answer"""
import subprocess
import sys
import os
from pathlib import Path

# Load env
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_API_BASE = os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1")

if not NVIDIA_API_KEY:
    print("❌ NVIDIA_API_KEY not set. Check .env")
    sys.exit(1)

# Set local paths for solve_v14
REPO_ROOT = Path(__file__).parent
os.environ["RESOURCES_DIR"] = str(REPO_ROOT / "resources")
os.environ["CORPUS_DIR"] = str(REPO_ROOT / "resources")
os.environ["ANSWER_PATH"] = str(REPO_ROOT / "answer.txt")

def solve(question: str) -> str:
    """Run solve_v14 to get briefing, then ask DeepSeek to finalize."""

    # Step 1: Get research briefing from solve_v14
    print(f"🔍 Researching: {question}\n")
    result = subprocess.run(
        ["python3", "v14/solve_v14.py", question],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent)
    )
    briefing = result.stdout
    if result.returncode != 0:
        print(f"⚠️  solve_v14 stderr: {result.stderr}")

    print("📋 Briefing from solve_v14:")
    print(briefing[:500] + "..." if len(briefing) > 500 else briefing)
    print()

    # Step 2: Ask DeepSeek to review & finalize
    print("🧠 Asking DeepSeek v3.2 to finalize answer...\n")

    try:
        from openai import OpenAI
    except ImportError:
        print("❌ openai package not installed. Run: pip install openai")
        sys.exit(1)

    client = OpenAI(
        api_key=NVIDIA_API_KEY,
        base_url=NVIDIA_API_BASE
    )

    prompt = f"""You are a Treasury Data Expert. Review the research briefing below and provide a final numeric answer.

QUESTION: {question}

RESEARCH BRIEFING:
{briefing}

TASK:
1. Review the evidence provided above
2. Extract the numeric answer (no units, no commas unless question asks)
3. Write ONLY the final answer value, nothing else

ANSWER:"""

    response = client.chat.completions.create(
        model="deepseek-ai/deepseek-v3.2",
        messages=[
            {"role": "system", "content": "You are a Treasury data expert. Respond with only a numeric answer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0,
        max_tokens=100
    )

    answer = response.choices[0].message.content.strip()

    # Step 3: Write to answer.txt
    answer_file = Path("/app/answer.txt")
    answer_file.parent.mkdir(parents=True, exist_ok=True)
    answer_file.write_text(answer)

    print(f"✅ Answer written to /app/answer.txt")
    print(f"📌 Value: {answer}\n")

    return answer

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 run.py 'Your question here'")
        sys.exit(1)

    question = sys.argv[1]
    solve(question)
