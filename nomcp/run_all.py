#!/usr/bin/env python3
"""
Standalone runner for OfficeQA Arena — No Docker, No Arena CLI.

Calls OpenRouter API (MiniMax M2.5) with tool-use to simulate the Goose harness.
The model gets shell command execution as a tool. It runs solve.py, search.py,
python3 computations, and writes answers.

Usage:
    # Run all 246 tasks
    python3 nomcp/run_all.py --corpus /path/to/corpus

    # Run specific UIDs
    python3 nomcp/run_all.py --corpus /path/to/corpus --uids UID0001,UID0002

    # Run with concurrency
    python3 nomcp/run_all.py --corpus /path/to/corpus --concurrency 4

    # Dry run (show questions, don't call API)
    python3 nomcp/run_all.py --corpus /path/to/corpus --dry-run

Environment:
    OPENROUTER_API_KEY  — Required. Your OpenRouter API key.
    CORPUS_DIR          — Path to corpus (or use --corpus flag).
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
import jinja2

# ── Constants ──────────────────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "minimax/minimax-m2.5"
MAX_TURNS = 25
TIMEOUT_PER_TASK = 280  # seconds (leave margin for the 300s Arena timeout)
NOMCP_DIR = Path(__file__).parent
PROJECT_ROOT = NOMCP_DIR.parent

# ── Tool Definition (OpenAI function-calling format) ──────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Execute a shell command and return stdout+stderr. Use for: python3, grep, echo, cat. Max output: 8000 chars.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute (e.g., 'python3 /installed-agent/solve.py \"question\"')"
                    }
                },
                "required": ["command"]
            }
        }
    }
]


def load_system_prompt(instruction: str) -> str:
    """Render the Jinja2 system prompt with the given instruction."""
    template_path = NOMCP_DIR / "prompts" / "system.j2"
    template_str = template_path.read_text()
    template = jinja2.Template(template_str)
    return template.render(instruction=instruction)


def load_skills_context() -> str:
    """Load all skill files as additional context."""
    skills_dir = NOMCP_DIR / "skills"
    if not skills_dir.is_dir():
        return ""

    parts = ["\n\n# DOMAIN KNOWLEDGE (from skills/)\n"]
    for md_file in sorted(skills_dir.glob("*.md")):
        content = md_file.read_text().strip()
        parts.append(f"\n## {md_file.stem}\n{content}\n")
    return "\n".join(parts)


def load_questions(csv_path: str, uids: list[str] | None = None) -> list[dict]:
    """Load questions from the full CSV."""
    questions = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if uids and row["uid"].upper() not in [u.upper() for u in uids]:
                continue
            questions.append({
                "uid": row["uid"],
                "question": row["question"],
                "answer": row["answer"],
                "difficulty": row.get("difficulty", "unknown"),
                "source_files": row.get("source_files", ""),
            })
    return questions


def execute_shell(command: str, corpus_dir: str, work_dir: str, agent_dir: str) -> str:
    """Execute a shell command with path rewriting for local environment."""
    # Rewrite paths: /app/corpus -> actual corpus, /installed-agent -> nomcp dir
    cmd = command.replace("/app/corpus", corpus_dir)
    cmd = cmd.replace("/installed-agent/", agent_dir + "/")
    cmd = cmd.replace("/app/answer.txt", os.path.join(work_dir, "answer.txt"))

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=work_dir,
            env={
                **os.environ,
                "CORPUS_DIR": corpus_dir,
                "INDEX_PATH": os.path.join(work_dir, "table_index.jsonl"),
                "KEYWORD_INDEX_PATH": os.path.join(work_dir, "keyword_index.txt"),
                "BUILD_SCRIPT": os.path.join(agent_dir, "build_index.py"),
            }
        )
        output = result.stdout + result.stderr
        # Truncate to avoid token explosion
        if len(output) > 8000:
            output = output[:4000] + "\n\n... [TRUNCATED] ...\n\n" + output[-4000:]
        return output if output.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: Command timed out after 60 seconds."
    except Exception as e:
        return f"ERROR: {e}"


def call_openrouter(messages: list[dict], api_key: str) -> dict:
    """Call OpenRouter chat completions API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/officeqa-arena",
        "X-Title": "OfficeQA Arena Runner",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
        "temperature": 0.0,
        "max_tokens": 4096,
    }

    for attempt in range(4):
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            if attempt < 3:
                wait = 2 ** (attempt + 1)
                print(f"    API error: {e}, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("OpenRouter API failed after 4 retries")


def run_single_task(task: dict, api_key: str, corpus_dir: str, agent_dir: str,
                    shared_index_dir: str | None = None) -> dict:
    """Run a single question through the agentic loop."""
    uid = task["uid"]
    question = task["question"]
    expected = task["answer"]
    start_time = time.time()

    # Create work directory for this task
    work_dir = tempfile.mkdtemp(prefix=f"officeqa_{uid}_")

    # If shared index exists, symlink it to avoid rebuilding per task
    if shared_index_dir:
        idx_src = os.path.join(shared_index_dir, "table_index.jsonl")
        kw_src = os.path.join(shared_index_dir, "keyword_index.txt")
        if os.path.exists(idx_src):
            os.symlink(idx_src, os.path.join(work_dir, "table_index.jsonl"))
        if os.path.exists(kw_src):
            os.symlink(kw_src, os.path.join(work_dir, "keyword_index.txt"))

    # Build system prompt with skills context
    system_prompt = load_system_prompt(question)
    skills_ctx = load_skills_context()
    full_system = system_prompt + skills_ctx

    messages = [
        {"role": "system", "content": full_system},
        {"role": "user", "content": question},
    ]

    tool_calls_count = 0
    answer = None

    for turn in range(MAX_TURNS):
        elapsed = time.time() - start_time
        if elapsed > TIMEOUT_PER_TASK:
            print(f"  [{uid}] Timeout after {elapsed:.0f}s", file=sys.stderr)
            break

        try:
            response = call_openrouter(messages, api_key)
        except Exception as e:
            print(f"  [{uid}] API error: {e}", file=sys.stderr)
            break

        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})

        # Check for tool calls
        tool_calls = message.get("tool_calls")
        if tool_calls:
            # Add assistant message with tool calls
            messages.append(message)

            for tc in tool_calls:
                func = tc.get("function", {})
                func_name = func.get("name", "")
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                if func_name == "run_shell":
                    command = args.get("command", "")
                    tool_calls_count += 1
                    print(f"  [{uid}] T{tool_calls_count}: {command[:100]}", file=sys.stderr)

                    result = execute_shell(command, corpus_dir, work_dir, agent_dir)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })

                    # Check if answer was written
                    answer_path = os.path.join(work_dir, "answer.txt")
                    if os.path.exists(answer_path):
                        answer = Path(answer_path).read_text().strip()
                else:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": f"Unknown tool: {func_name}",
                    })

        else:
            # No tool calls — model gave a text response
            content = message.get("content", "")
            messages.append({"role": "assistant", "content": content})

            # Check if answer was written in a previous turn
            answer_path = os.path.join(work_dir, "answer.txt")
            if os.path.exists(answer_path):
                answer = Path(answer_path).read_text().strip()

            # If finish_reason is "stop", the model is done
            if choice.get("finish_reason") == "stop":
                # Try to extract answer from text if not yet written to file
                if not answer and content:
                    # Look for answer patterns in the response
                    m = re.search(r'echo\s+-n\s+"([^"]+)"\s*>\s*/app/answer\.txt', content)
                    if m:
                        answer = m.group(1)
                break

    elapsed = time.time() - start_time

    # Score: fuzzy 1% numeric match
    correct = score_answer(answer, expected) if answer else False

    result = {
        "uid": uid,
        "question": question[:100] + "...",
        "expected": expected,
        "answer": answer,
        "correct": correct,
        "tool_calls": tool_calls_count,
        "elapsed_s": round(elapsed, 1),
        "difficulty": task["difficulty"],
    }

    status = "PASS" if correct else "FAIL"
    print(f"  [{uid}] {status} | answer={answer} | expected={expected} | {tool_calls_count} calls | {elapsed:.1f}s",
          file=sys.stderr)

    # Cleanup work dir (but keep answer for debugging)
    return result


def score_answer(predicted: str | None, expected: str) -> bool:
    """Fuzzy numeric matching with 1% tolerance."""
    if predicted is None:
        return False

    # Normalize both
    pred_clean = re.sub(r"[,%$\s]", "", predicted.replace("−", "-").strip().rstrip("%"))
    exp_clean = re.sub(r"[,%$\s]", "", expected.replace("−", "-").strip().rstrip("%"))

    try:
        pred_val = float(pred_clean)
        exp_val = float(exp_clean)
    except (ValueError, TypeError):
        # Fall back to exact string match
        return predicted.strip().lower() == expected.strip().lower()

    if exp_val == 0:
        return abs(pred_val) < 0.01

    return abs(pred_val - exp_val) / abs(exp_val) <= 0.01


def pre_build_index(corpus_dir: str, agent_dir: str, index_dir: str):
    """Pre-build the search index once for all tasks."""
    idx_path = os.path.join(index_dir, "table_index.jsonl")
    kw_path = os.path.join(index_dir, "keyword_index.txt")

    if os.path.exists(idx_path) and os.path.getsize(idx_path) > 1000:
        print(f"Index already exists at {idx_path}", file=sys.stderr)
        return

    print(f"Pre-building index from {corpus_dir}...", file=sys.stderr)
    build_script = os.path.join(agent_dir, "build_index.py")

    result = subprocess.run(
        [sys.executable, build_script, corpus_dir, idx_path],
        capture_output=True, text=True, timeout=120,
        env={
            **os.environ,
            "CORPUS_DIR": corpus_dir,
            "INDEX_PATH": idx_path,
            "KEYWORD_INDEX_PATH": kw_path,
        }
    )
    print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        print(f"WARNING: Index build failed: {result.stderr}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="OfficeQA Arena standalone runner")
    parser.add_argument("--corpus", type=str, default=os.environ.get("CORPUS_DIR", "/app/corpus"),
                        help="Path to Treasury Bulletin corpus directory")
    parser.add_argument("--cases", type=str, default=str(PROJECT_ROOT / "data" / "officeqa_full.csv"),
                        help="Path to questions CSV")
    parser.add_argument("--uids", type=str, default=None,
                        help="Comma-separated UIDs to run (default: all)")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Number of concurrent tasks")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSONL file for results")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show questions without calling API")
    parser.add_argument("--skip-index", action="store_true",
                        help="Skip pre-building the index")
    args = parser.parse_args()

    # Validate
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key and not args.dry_run:
        print("ERROR: Set OPENROUTER_API_KEY environment variable", file=sys.stderr)
        sys.exit(1)

    corpus_dir = os.path.abspath(args.corpus)
    if not os.path.isdir(corpus_dir) and not args.dry_run:
        print(f"ERROR: Corpus directory not found: {corpus_dir}", file=sys.stderr)
        print(f"  Download the corpus and pass --corpus /path/to/corpus", file=sys.stderr)
        sys.exit(1)

    agent_dir = str(NOMCP_DIR)

    # Load questions
    uid_list = [u.strip() for u in args.uids.split(",")] if args.uids else None
    questions = load_questions(args.cases, uid_list)

    if not questions:
        print("ERROR: No questions loaded. Check --cases and --uids.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(questions)} questions", file=sys.stderr)
    print(f"Corpus: {corpus_dir}", file=sys.stderr)
    print(f"Model: {MODEL}", file=sys.stderr)
    print(f"Concurrency: {args.concurrency}", file=sys.stderr)

    if args.dry_run:
        for q in questions:
            print(f"  {q['uid']} [{q['difficulty']}] {q['question'][:80]}...")
        print(f"\nTotal: {len(questions)} questions")
        return

    # Pre-build shared index
    shared_index_dir = tempfile.mkdtemp(prefix="officeqa_index_")
    if not args.skip_index:
        pre_build_index(corpus_dir, agent_dir, shared_index_dir)

    # Output file
    output_path = args.output or f"results_nomcp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    print(f"Output: {output_path}", file=sys.stderr)
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Starting run: {len(questions)} tasks", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    results = []
    correct = 0
    total = 0

    if args.concurrency <= 1:
        # Sequential
        for task in questions:
            result = run_single_task(task, api_key, corpus_dir, agent_dir, shared_index_dir)
            results.append(result)
            total += 1
            if result["correct"]:
                correct += 1

            # Write incrementally
            with open(output_path, "a") as f:
                f.write(json.dumps(result) + "\n")

            print(f"  Progress: {correct}/{total} correct ({correct/total*100:.1f}%)\n",
                  file=sys.stderr)
    else:
        # Concurrent
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {
                executor.submit(run_single_task, task, api_key, corpus_dir, agent_dir, shared_index_dir): task
                for task in questions
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                total += 1
                if result["correct"]:
                    correct += 1

                with open(output_path, "a") as f:
                    f.write(json.dumps(result) + "\n")

                print(f"  Progress: {correct}/{total} correct ({correct/total*100:.1f}%)\n",
                      file=sys.stderr)

    # Final summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"FINAL RESULTS", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"Total:   {total}", file=sys.stderr)
    print(f"Correct: {correct} ({correct/total*100:.1f}%)", file=sys.stderr)
    print(f"Wrong:   {total - correct}", file=sys.stderr)

    easy = [r for r in results if r["difficulty"] == "easy"]
    hard = [r for r in results if r["difficulty"] == "hard"]
    if easy:
        easy_correct = sum(1 for r in easy if r["correct"])
        print(f"Easy:    {easy_correct}/{len(easy)} ({easy_correct/len(easy)*100:.1f}%)", file=sys.stderr)
    if hard:
        hard_correct = sum(1 for r in hard if r["correct"])
        print(f"Hard:    {hard_correct}/{len(hard)} ({hard_correct/len(hard)*100:.1f}%)", file=sys.stderr)

    avg_time = sum(r["elapsed_s"] for r in results) / len(results) if results else 0
    avg_calls = sum(r["tool_calls"] for r in results) / len(results) if results else 0
    print(f"Avg time: {avg_time:.1f}s", file=sys.stderr)
    print(f"Avg tool calls: {avg_calls:.1f}", file=sys.stderr)
    print(f"\nResults saved to: {output_path}", file=sys.stderr)

    # Estimate Arena score
    # Score = correct_tasks × (1.0 + cost_adj + time_adj), max 282.9
    # Rough estimate: cost_adj + time_adj ≈ 0.15 (best case)
    estimated_score = correct * 1.15
    print(f"\nEstimated Arena score: ~{estimated_score:.1f} (max 282.9)", file=sys.stderr)


if __name__ == "__main__":
    main()
