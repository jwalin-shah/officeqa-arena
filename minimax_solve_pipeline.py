#!/usr/bin/env python3
"""
MiniMax Solve Pipeline - Optimized for arena execution
======================================================
A self-contained wrapper around solve_decompose with:
- Caching
- Confidence gating
- Better error recovery
- Multiple modes
"""

import argparse
import json
import os
import sys
import time
import hashlib
from pathlib import Path
from functools import lru_cache

# == Config ==
DEFAULT_CORPUS = "/app/corpus"
CORPUS_DIR = os.environ.get("CORPUS_DIR", DEFAULT_CORPUS)
ANSWER_PATH = os.environ.get("ANSWER_PATH", "/app/answer.txt")
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = os.environ.get("SOLVER_MODEL", "minimax/minimax-m2.5")
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/solve_cache")
MAX_RETRIES = 3

# Ensure cache dir exists
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)

# == Import solve_decompose ==
# Add path to solve_decompose

# == Import solve_decompose ==
# Add path to solve_decompose
SOLVE_DECOMPOSE_PATH = Path(__file__).parent / "bottomup" / "solve_decompose.py"
if SOLVE_DECOMPOSE_PATH.exists():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "solve_decompose", SOLVE_DECOMPOSE_PATH
    )
    sd = importlib.util.module_from_spec(spec)
    sys.modules["solve_decompose"] = sd
    spec.loader.exec_module(sd)
else:
    print(
        f"ERROR: solve_decompose.py not found at {SOLVE_DECOMPOSE_PATH}",
        file=sys.stderr,
    )
    sys.exit(1)


# == Caching ==
def get_question_hash(question):
    """Create hash for caching."""
    return hashlib.sha256(question.encode()).hexdigest()[:16]


def get_cached_result(question_hash):
    """Get cached result if exists."""
    cache_file = Path(CACHE_DIR) / f"{question_hash}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except:
            pass
    return None


def save_cached_result(question_hash, result, mode):
    """Save result to cache."""
    cache_file = Path(CACHE_DIR) / f"{question_hash}.json"
    try:
        cache_file.write_text(
            json.dumps({"result": result, "mode": mode, "timestamp": time.time()})
        )
    except:
        pass


# == Confidence Gating ==
def check_confidence(extracted_values, confidence, threshold="high"):
    """Check if extraction meets confidence threshold."""
    if confidence == "high":
        return True
    if confidence == "medium" and threshold != "high":
        return True
    return False


# == Main Solve Function ==
def solve(question, mode="solve", use_cache=True, confidence_threshold="high"):
    """
    Solve a question using the pipeline.

    Args:
        question: The question to answer
        mode: solve, consensus, or stochastic
        use_cache: Whether to use caching
        confidence_threshold: high, medium, or low

    Returns:
        str: The answer
    """
    question = question.strip()
    if not question:
        return "N/A"

    q_hash = get_question_hash(question)

    # Check cache
    global CORPUS_DIR
    if use_cache:
        cached = get_cached_result(q_hash)
        if cached and cached.get("mode") == mode:
            print(f"  [CACHE] Using cached result", file=sys.stderr)
            return cached.get("result", "N/A")

    # Set corpus dir
    os.environ["CORPUS_DIR"] = CORPUS_DIR

    t0 = time.time()
    answer = "N/A"
    attempts = 0

    while attempts < MAX_RETRIES and answer == "N/A":
        attempts += 1
        print(f"  [Attempt {attempts}/{MAX_RETRIES}]", file=sys.stderr)

        try:
            if mode == "consensus":
                answer = sd.solve_consensus(question)
            elif mode == "stochastic":
                answer = sd.solve_stochastic(question, n_paths=3)
            else:
                answer = sd.solve(question)

            # Check if answer is valid
            if answer and answer != "N/A" and answer != "":
                # Basic validation
                answer_str = str(answer).strip()
                if len(answer_str) > 0:
                    answer = answer_str
                    break
        except Exception as e:
            print(f"  [Error] {e}", file=sys.stderr)
            time.sleep(1)

    elapsed = time.time() - t0
    print(f"  [Result] {answer} ({elapsed:.1f}s)", file=sys.stderr)

    # Cache result
    if use_cache and answer != "N/A":
        save_cached_result(q_hash, answer, mode)

    return answer if answer else "N/A"


# == CLI ==
def main():
    parser = argparse.ArgumentParser(description="MiniMax Solve Pipeline")
    parser.add_argument("question", nargs="?", help="Question to answer")
    parser.add_argument(
        "--mode", choices=["solve", "consensus", "stochastic"], default="solve"
    )
    parser.add_argument("--no-cache", action="store_true", help="Disable caching")
    parser.add_argument(
        "--confidence", default="high", choices=["high", "medium", "low"]
    )
    parser.add_argument("--corpus", default=None, help="Corpus directory")
    parser.add_argument("--output", default=None, help="Output file path")

    args = parser.parse_args()

    if not args.question:
        print(
            "Usage: python3 solve_pipeline.py 'QUESTION' [--mode solve|consensus|stochastic]"
        )
        sys.exit(1)

    # Set corpus dir
    global CORPUS_DIR
    if args.corpus:
        CORPUS_DIR = args.corpus
    os.environ["CORPUS_DIR"] = CORPUS_DIR

    print(f"[Pipeline] Mode: {args.mode}, Corpus: {CORPUS_DIR}", file=sys.stderr)
    print(f"[Question] {args.question}", file=sys.stderr)

    answer = solve(
        args.question,
        mode=args.mode,
        use_cache=not args.no_cache,
        confidence_threshold=args.confidence,
    )

    # Write answer
    output_path = args.output or ANSWER_PATH
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(str(answer))

    print(f"[Answer] {answer}", file=sys.stderr)
    print(f"[Written to] {output_path}", file=sys.stderr)

    return 0 if answer != "N/A" else 1


if __name__ == "__main__":
    sys.exit(main())
