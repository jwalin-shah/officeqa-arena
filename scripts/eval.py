#!/usr/bin/env python3
"""OfficeQA Arena evaluation harness.

Usage:
    python scripts/eval.py --cases data/test_cases.json --db data/officeqa_corpus.sqlite3
    python scripts/eval.py --cases data/test_cases.json --db data/officeqa_corpus.sqlite3 --verbose
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent import run_agent_loop  # noqa: E402
from src.reward import extract_final_answer, fuzzy_match_answer, score_answer  # noqa: E402


# ---------------------------------------------------------------------------
# Case loading
# ---------------------------------------------------------------------------

def load_cases(path: Path) -> list[dict[str, str]]:
    """Load test cases from JSON (list of objects).

    Supports column names: uid/case_id/id, instruction/question/input,
    expected_answer/expected/answer.
    """
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    # Support both JSON array and JSONL formats
    if text.startswith("["):
        raw = json.loads(text)
    else:
        raw = [json.loads(line) for line in text.splitlines() if line.strip()]
    cases: list[dict[str, str]] = []
    for item in raw:
        uid = item.get("uid") or item.get("question_id") or item.get("case_id") or item.get("id") or ""
        instruction = (
            item.get("instruction") or item.get("question") or item.get("input") or ""
        )
        expected = (
            item.get("expected_answer") or item.get("expected") or item.get("answer") or ""
        )
        if instruction:
            cases.append(
                {"uid": uid, "instruction": instruction, "expected_answer": expected}
            )
    return cases


# ---------------------------------------------------------------------------
# MCP tools loader
# ---------------------------------------------------------------------------

def load_mcp_tools(db_path: str):
    """Import and instantiate the MCP tool object from the server package."""
    from server import load_tools

    return load_tools(db_path=db_path)


# ---------------------------------------------------------------------------
# Single-case evaluator
# ---------------------------------------------------------------------------

def evaluate_case(
    case: dict[str, str],
    tools_obj: object,
    model: str,
    max_iterations: int,
    verbose: bool,
) -> dict:
    uid = case.get("uid", "unknown")
    instruction = case["instruction"]
    expected = case.get("expected_answer", "")

    print(f"\n{'=' * 60}")
    print(f"Case: {uid}")
    print(f"Q:    {instruction[:120]}...")
    print(f"Exp:  {expected}")

    t0 = time.time()
    try:
        raw_answer, log = run_agent_loop(
            instruction=instruction,
            tools_obj=tools_obj,
            model=model,
            max_iterations=max_iterations,
            verbose=verbose,
        )
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  ERROR: {exc}")
        return {
            "uid": uid,
            "predicted": "",
            "expected": expected,
            "score": 0.0,
            "rationale": f"Agent error: {exc}",
            "elapsed_s": round(elapsed, 1),
        }

    elapsed = time.time() - t0
    predicted = extract_final_answer(raw_answer) if raw_answer else ""

    if expected:
        score = score_answer(expected, predicted)
        _, rationale = fuzzy_match_answer(expected, predicted)
    else:
        score = -1.0  # no ground truth
        rationale = "No expected answer provided"

    marker = "PASS" if score == 1.0 else ("SKIP" if score < 0 else "FAIL")
    print(f"  Ans:  {predicted}")
    print(f"  {marker}  score={score}  ({rationale})  [{elapsed:.1f}s]")

    return {
        "uid": uid,
        "predicted": predicted,
        "expected": expected,
        "score": score,
        "rationale": rationale,
        "elapsed_s": round(elapsed, 1),
        "log": log,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="OfficeQA Arena eval harness")
    parser.add_argument("--cases", required=True, help="Path to JSON test cases")
    parser.add_argument("--db", required=True, help="Path to SQLite corpus DB")
    parser.add_argument(
        "--model",
        default="minimax/minimax-m2.7",
        help="OpenRouter model ID (default: minimax/minimax-m2.7)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=15,
        help="Max agent loop iterations (default: 15)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print tool calls")
    parser.add_argument("--output", default="", help="Path to write results JSON")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    if not cases:
        print("No cases loaded. Check --cases path.")
        sys.exit(1)

    print(f"Loaded {len(cases)} case(s).  Model: {args.model}")

    tools_obj = load_mcp_tools(args.db)

    results: list[dict] = []
    for case in cases:
        result = evaluate_case(
            case, tools_obj, args.model, args.max_iterations, args.verbose
        )
        results.append(result)

    # Summary
    scored = [r for r in results if r["score"] >= 0]
    total = len(scored)
    correct = sum(1 for r in scored if r["score"] == 1.0)

    print(f"\n{'=' * 60}")
    print(f"Results: {correct}/{total} correct")
    if total:
        print(f"Accuracy: {correct / total * 100:.1f}%")

    # Write output
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                {"model": args.model, "total": total, "correct": correct, "results": results},
                f,
                indent=2,
                default=str,
            )
        print(f"Results written to {out_path}")


if __name__ == "__main__":
    main()
