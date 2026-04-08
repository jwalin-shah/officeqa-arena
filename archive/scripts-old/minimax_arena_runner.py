#!/usr/bin/env python3
"""
MiniMax Arena Harness Runner
============================
Runner for OfficeQA Arena - designed for Goose/OpenHands

Usage:
    python3 minimax_arena_runner.py --questions questions.csv
    python3 minimax_arena_runner.py --uids UID0001,UID0002

Environment:
    OPENROUTER_API_KEY - Required
    CORPUS_DIR - Path to corpus (default: ./corpus)
    CACHE_DIR - Path to cache (default: /tmp/minimax_cache)
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add current dir to path
sys.path.insert(0, str(Path(__file__).parent))

# == Config ==
CORPUS_DIR = os.environ.get("CORPUS_DIR", "./corpus")
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/minimax_cache")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = os.environ.get("SOLVER_MODEL", "minimax/minimax-m2.5")
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "4"))
TIMEOUT = int(os.environ.get("TIMEOUT", "300"))


# == Load Questions ==
def load_questions_from_csv(csv_path, uids=None):
    """Load questions from CSV file."""
    questions = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = row.get("uid", "")
            if uids is None or uid in uids:
                questions[uid] = {
                    "question": row.get("question", ""),
                    "answer": row.get("answer", ""),  # For validation
                    "difficulty": row.get("difficulty", ""),
                }
    return questions


def load_questions_from_json(json_path, uids=None):
    """Load questions from JSON file."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    questions = {}
    for item in data:
        uid = item.get("uid", "")
        if uids is None or uid in uids:
            questions[uid] = {
                "question": item.get("question", ""),
                "answer": item.get("answer", ""),
                "difficulty": item.get("difficulty", ""),
            }
    return questions


# == Run Single Question ==
def run_single_question(uid, question_data, pipeline_path):
    """Run a single question through the pipeline."""
    question = question_data.get("question", "")
    expected = question_data.get("answer", "")

    if not question:
        return {
            "uid": uid,
            "status": "skip",
            "error": "No question",
            "answer": None,
            "expected": expected,
            "elapsed": 0,
        }

    t0 = time.time()

    # Import pipeline
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("pipeline", pipeline_path)
        pipeline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pipeline)
    except Exception as e:
        return {
            "uid": uid,
            "status": "error",
            "error": f"Failed to load pipeline: {e}",
            "answer": None,
            "expected": expected,
            "elapsed": time.time() - t0,
        }

    # Run pipeline
    try:
        # Set corpus
        os.environ["CORPUS_DIR"] = CORPUS_DIR
        os.environ["CACHE_DIR"] = CACHE_DIR

        # Run
        answer = pipeline.solve(question, mode="solve")

        elapsed = time.time() - t0

        # Check result
        correct = _check_answer(answer, expected)

        return {
            "uid": uid,
            "status": "success" if correct else "wrong",
            "correct": correct,
            "answer": str(answer),
            "expected": expected,
            "elapsed": f"{elapsed:.1f}s",
        }
    except Exception as e:
        return {
            "uid": uid,
            "status": "error",
            "error": str(e),
            "answer": None,
            "expected": expected,
            "elapsed": f"{time.time() - t0:.1f}s",
        }


def _check_answer(got, expected):
    """Check if answer is correct."""
    if not got or not expected:
        return got == expected

    # Normalize
    def norm(s):
        s = str(s).strip()
        s = s.replace(",", "").replace("$", "").replace("%", "")
        s = s.replace(" million", "").replace(" billions", "")
        try:
            return float(s)
        except:
            return s

    g, e = norm(got), norm(expected)

    if isinstance(g, float) and isinstance(e, float):
        if e == 0:
            return abs(g) < 1
        return abs(g - e) / max(abs(e), 1) < 0.05

    return str(g) == str(e)


# == Main Runner ==
def main():
    parser = argparse.ArgumentParser(description="MiniMax Arena Runner")
    parser.add_argument("--questions", help="Path to questions CSV/JSON")
    parser.add_argument("--uids", help="Comma-separated UIDs to run")
    parser.add_argument("--corpus", default=CORPUS_DIR, help="Corpus directory")
    parser.add_argument("--pipeline", default=None, help="Path to solve pipeline")
    parser.add_argument("--output", default="results.json", help="Output results file")
    parser.add_argument("--concurrency", type=int, default=MAX_WORKERS)
    parser.add_argument(
        "--dry-run", action="store_true", help="Show questions, don't run"
    )

    args = parser.parse_args()

    # Find pipeline
    if args.pipeline:
        pipeline_path = args.pipeline
    else:
        # Look for pipeline in standard locations
        for candidate in [
            "./minimax_solve_pipeline.py",
            "./nomcp/bottomup/solve_decompose.py",
            "./solve_decompose.py",
        ]:
            if Path(candidate).exists():
                pipeline_path = candidate
                break
        else:
            print("ERROR: Could not find solve pipeline", file=sys.stderr)
            sys.exit(1)

    print(f"[Config]", file=sys.stderr)
    print(f"  Corpus: {args.corpus}", file=sys.stderr)
    print(f"  Pipeline: {pipeline_path}", file=sys.stderr)
    print(f"  Output: {args.output}", file=sys.stderr)
    print(f"  Concurrency: {args.concurrency}", file=sys.stderr)

    # Load questions
    if not args.questions:
        print("ERROR: --questions required", file=sys.stderr)
        sys.exit(1)

    q_path = Path(args.questions)
    if not q_path.exists():
        print(f"ERROR: Questions file not found: {q_path}", file=sys.stderr)
        sys.exit(1)

    uids = None
    if args.uids:
        uids = set(args.uids.split(","))

    if q_path.suffix == ".json":
        questions = load_questions_from_json(q_path, uids)
    else:
        questions = load_questions_from_csv(q_path, uids)

    print(f"[Questions] Loaded {len(questions)} questions", file=sys.stderr)

    if args.dry_run:
        print("[Dry Run] Questions:", file=sys.stderr)
        for uid, data in list(questions.items())[:5]:
            print(f"  {uid}: {data['question'][:80]}...", file=sys.stderr)
        return 0

    # Run questions
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = {
            ex.submit(run_single_question, uid, data, pipeline_path): uid
            for uid, data in questions.items()
        }

        for future in as_completed(futures):
            uid = futures[future]
            try:
                result = future.result()
                results.append(result)

                status_icon = {
                    "success": "✅",
                    "wrong": "❌",
                    "error": "⚠️",
                    "skip": "⏭️",
                }.get(result["status"], "❓")

                print(
                    f"  {status_icon} {uid}: {result.get('answer', 'N/A')[:30]} "
                    f"(expected: {result.get('expected', '?')[:20]}) "
                    f"[{result.get('elapsed', '?')}]",
                    file=sys.stderr,
                )
            except Exception as e:
                print(f"  ⚠️ {uid}: Exception: {e}", file=sys.stderr)

    # Summary
    results.sort(key=lambda r: r["uid"])

    correct = sum(1 for r in results if r.get("correct"))
    wrong = sum(1 for r in results if r.get("status") == "wrong")
    errors = sum(1 for r in results if r.get("status") == "error")
    total = len(results)

    print(f"\n[SUMMARY]", file=sys.stderr)
    print(
        f"  Correct: {correct}/{total} ({100 * correct / total:.0f}%)", file=sys.stderr
    )
    print(f"  Wrong: {wrong}", file=sys.stderr)
    print(f"  Errors: {errors}", file=sys.stderr)

    # Save results
    output_path = Path(args.output)
    output_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n[Saved] Results to {output_path}", file=sys.stderr)

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
