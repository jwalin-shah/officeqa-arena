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
# Failure classification
# ---------------------------------------------------------------------------

def classify_failure(result: dict) -> str:
    """Classify a failed result into a structured failure bucket.

    Buckets:
        retrieval_wrong_table - search found wrong table
        wrong_row_col - right table, wrong row/column extracted
        year_month_scope - wrong time period
        units_scale - off by 1000x/1000000x (unit conversion error)
        math_compute - arithmetic or formula error
        over_filter - query_table_rows returned 0 rows due to filters
        context_blowup - too many tokens consumed (>1.5M input tokens)
        timeout - agent didn't write answer in time
        impossible - question requires visual/chart analysis
        unknown - can't classify
    """
    if result.get("score", 0) >= 1.0:
        return "correct"

    rationale = str(result.get("rationale", "")).lower()
    predicted = str(result.get("predicted", "")).strip()
    expected = str(result.get("expected", "")).strip()
    log = result.get("log", [])

    # No answer written
    if not predicted:
        # Check if agent errored
        if "agent error" in rationale:
            return "timeout"
        return "timeout"

    # Parse numeric values for scale comparison
    import re
    pred_num = exp_num = None
    try:
        pred_num = float(re.sub(r"[,$%]", "", predicted))
    except (ValueError, TypeError):
        pass
    try:
        exp_num = float(re.sub(r"[,$%]", "", expected))
    except (ValueError, TypeError):
        pass

    # Unit scale error: off by ~1000x or ~1000000x
    if pred_num is not None and exp_num is not None and exp_num != 0:
        ratio = pred_num / exp_num
        if 900 < ratio < 1100 or 0.0009 < ratio < 0.0011:
            return "units_scale"  # off by ~1000x
        if 9e5 < ratio < 1.1e6 or 9e-7 < ratio < 1.1e-6:
            return "units_scale"  # off by ~1000000x

    # Check tool call patterns in log
    total_tool_calls = 0
    empty_query_rows = 0
    search_calls = 0
    total_input_tokens = 0

    for entry in log:
        tool_calls = entry.get("tool_calls", [])
        total_tool_calls += len(tool_calls)
        for tc in tool_calls:
            name = tc.get("name", "")
            result_full = tc.get("result_full", {})
            if isinstance(result_full, str):
                try:
                    result_full = json.loads(result_full)
                except (json.JSONDecodeError, TypeError):
                    result_full = {}

            if name == "query_table_rows" and isinstance(result_full, dict):
                if result_full.get("count", -1) == 0:
                    empty_query_rows += 1
            if name == "search_tables":
                search_calls += 1

        # Sum input tokens if available
        metrics = entry.get("metrics", {})
        total_input_tokens += metrics.get("prompt_tokens", 0)

    # Context blowup
    if total_input_tokens > 1_500_000:
        return "context_blowup"

    # Over-filter: mostly empty query_table_rows
    if empty_query_rows >= 3 and total_tool_calls > 0:
        if empty_query_rows / max(total_tool_calls, 1) > 0.3:
            return "over_filter"

    # Math/compute error: values are close but not exact
    if pred_num is not None and exp_num is not None and exp_num != 0:
        pct_diff = abs(pred_num - exp_num) / abs(exp_num) * 100
        if pct_diff < 20:
            return "math_compute"  # close but wrong — likely arithmetic error
        if pct_diff < 50:
            return "wrong_row_col"  # moderately off — wrong data extracted

    # If we got here with a numeric mismatch, likely wrong table
    if pred_num is not None and exp_num is not None:
        return "retrieval_wrong_table"

    return "unknown"


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

    # Reset per-case budgets to prevent state leakage across cases
    if hasattr(tools_obj, "reset_budgets"):
        tools_obj.reset_budgets()

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

    result = {
        "uid": uid,
        "predicted": predicted,
        "expected": expected,
        "score": score,
        "rationale": rationale,
        "elapsed_s": round(elapsed, 1),
        "log": log,
    }
    if score == 0.0:
        bucket = classify_failure(result)
        result["failure_bucket"] = bucket
        print(f"  Bucket: {bucket}")
    return result


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

    # Failure bucket summary
    buckets: dict[str, list[str]] = {}
    for r in results:
        b = r.get("failure_bucket")
        if b:
            buckets.setdefault(b, []).append(r["uid"])
    if buckets:
        print(f"\nFailure Buckets:")
        for bucket, uids in sorted(buckets.items(), key=lambda x: -len(x[1])):
            print(f"  {bucket:25s} {len(uids):3d}  {', '.join(uids[:5])}")
        print()

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
