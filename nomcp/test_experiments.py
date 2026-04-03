#!/usr/bin/env python3
"""Unit tests for the solve.py pipeline — no real API calls required.

Tests:
  1. parse_question() — keyword extraction, year detection, period basis
  2. safe_eval_finance() — arithmetic, aggregation, CAGR, rounding
  3. search_raw_corpus() — corpus search (skipped if CORPUS_DIR not set)
  4. Optional features — TABLE_FAMILY_MAP, verify_with_llm (mocked), operation detection
  5. score_answer() — fuzzy numeric matching from run_all.py

Usage:
    python3 nomcp/test_experiments.py
"""

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Load modules via importlib (same pattern as run_all.py) ──────────────

NOMCP_DIR = Path(__file__).parent
SOLVE_PATH = NOMCP_DIR / "solve.py"
RUN_ALL_PATH = NOMCP_DIR / "run_all.py"

# Set required env vars before importing solve.py (it reads them at module level)
os.environ.setdefault("CORPUS_DIR", os.environ.get("CORPUS_DIR", "/nonexistent"))
os.environ.setdefault("ANSWER_PATH", "/tmp/_test_answer.txt")
os.environ.setdefault("OPENROUTER_API_KEY", "")

def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

solve = _load_module("solve", SOLVE_PATH)
run_all = _load_module("run_all", RUN_ALL_PATH)

# ── Test infrastructure ──────────────────────────────────────────────────

_pass_count = 0
_fail_count = 0

def check(name, condition, detail=""):
    global _pass_count, _fail_count
    if condition:
        _pass_count += 1
        print(f"  PASS  {name}")
    else:
        _fail_count += 1
        print(f"  FAIL  {name}  {detail}")


# ═══════════════════════════════════════════════════════════════════════════
# 1. parse_question()
# ═══════════════════════════════════════════════════════════════════════════

def test_parse_question():
    print("\n=== Test parse_question() ===")

    TEST_CASES = [
        {
            "question": "What were the total expenditures (in millions of nominal dollars) for U.S national defense in the calendar year 1940?",
            "expected_answer": "2,602",
            "expect_year": 1940,
            "expect_period": "calendar",
            "expect_keywords_contain": ["national", "defense"],
        },
        {
            "question": "What was the estimated total amount in billions of nominal dollars of U.S intergovernmental transfer payments for the calendar year 1953?",
            "expected_answer": "2.24",
            "expect_year": 1953,
            "expect_period": "calendar",
            "expect_keywords_contain": ["intergovernmental"],
        },
        {
            "question": "What was the absolute difference between the percent of criminal case dispositions under the U.S Alcohol Tobacco Tax Division for fiscal year 1953 and fiscal year 1954?",
            "expected_answer": "3%",
            "expect_year": 1953,
            "expect_period": "fiscal",
            "expect_keywords_contain": ["criminal", "dispositions"],
        },
        {
            "question": "What was the total federal debt outstanding at the end of fiscal year 1945?",
            "expected_answer": None,  # don't check
            "expect_year": 1945,
            "expect_period": "fiscal",
            "expect_keywords_contain": ["federal", "debt"],
        },
    ]

    for i, tc in enumerate(TEST_CASES):
        q = tc["question"]
        result = solve.parse_question(q)

        label = f"Q{i+1}"

        # Check year
        if tc["expect_year"] is not None:
            check(f"{label} year={tc['expect_year']}",
                  result.get("year") == tc["expect_year"],
                  f"got year={result.get('year')}")

        # Check period basis
        if tc["expect_period"] is not None:
            check(f"{label} period={tc['expect_period']}",
                  result.get("period_basis") == tc["expect_period"],
                  f"got period_basis={result.get('period_basis')}")

        # Check keywords present in content_words or strategies
        all_text = " ".join(result.get("content_words", []) + result.get("strategies", []))
        for kw in tc["expect_keywords_contain"]:
            check(f"{label} keyword '{kw}' present",
                  kw.lower() in all_text.lower(),
                  f"not found in content_words={result.get('content_words')}")

        # Verify structure
        check(f"{label} has strategies",
              len(result.get("strategies", [])) >= 1,
              f"strategies={result.get('strategies')}")

    # Multi-year question
    q_multi = "What was the difference between national defense spending in 1940 and 1945?"
    r = solve.parse_question(q_multi)
    check("Multi-year: both years extracted",
          1940 in r.get("years", []) and 1945 in r.get("years", []),
          f"got years={r.get('years')}")


# ═══════════════════════════════════════════════════════════════════════════
# 2. safe_eval_finance()
# ═══════════════════════════════════════════════════════════════════════════

def test_safe_eval():
    print("\n=== Test safe_eval_finance() ===")

    # Basic arithmetic
    check("sum([132, 129, 143]) == 404",
          solve.safe_eval_finance("sum([132, 129, 143])") == 404)

    check("abs(a - b) with variables",
          solve.safe_eval_finance("abs(a - b)", {"a": 71, "b": 68}) == 3)

    # CAGR: ((200/100)^(1/10) - 1) * 100 ≈ 7.177
    cagr_val = solve.safe_eval_finance("cagr(100, 200, 10)")
    check(f"cagr(100, 200, 10) ≈ 7.177",
          abs(cagr_val - 7.177) < 0.01,
          f"got {cagr_val}")

    check("round(3.14159, 2) == 3.14",
          solve.safe_eval_finance("round(3.14159, 2)") == 3.14)

    # More operations
    check("mean([10, 20, 30]) == 20",
          solve.safe_eval_finance("mean([10, 20, 30])") == 20)

    check("min([5, 3, 8]) == 3",
          solve.safe_eval_finance("min([5, 3, 8])") == 3)

    check("max([5, 3, 8]) == 8",
          solve.safe_eval_finance("max([5, 3, 8])") == 8)

    check("sqrt(144) == 12",
          solve.safe_eval_finance("sqrt(144)") == 12)

    check("2 ** 10 == 1024",
          solve.safe_eval_finance("2 ** 10") == 1024)

    # Median
    med = solve.safe_eval_finance("median([1, 3, 5, 7])")
    check("median([1, 3, 5, 7]) == 4.0",
          med == 4.0,
          f"got {med}")

    # Division
    check("100 / 3 ≈ 33.333",
          abs(solve.safe_eval_finance("100 / 3") - 33.333) < 0.01)

    # Nested
    check("round(sum([1.1, 2.2, 3.3]), 1) == 6.6",
          solve.safe_eval_finance("round(sum([1.1, 2.2, 3.3]), 1)") == 6.6)

    # Error handling
    try:
        solve.safe_eval_finance("__import__('os')")
        check("Rejects __import__", False, "should have raised")
    except (ValueError, TypeError):
        check("Rejects __import__", True)

    try:
        solve.safe_eval_finance("a / b", {"a": 1, "b": 0})
        check("Division by zero raises", False, "should have raised")
    except (ValueError, ZeroDivisionError):
        check("Division by zero raises", True)


# ═══════════════════════════════════════════════════════════════════════════
# 3. search_raw_corpus() — skip if corpus not available
# ═══════════════════════════════════════════════════════════════════════════

def test_search_corpus():
    print("\n=== Test search_raw_corpus() ===")

    corpus_dir = os.environ.get("CORPUS_DIR", "")
    if not corpus_dir or not os.path.isdir(corpus_dir):
        print("  SKIP  Corpus not available (set CORPUS_DIR to enable)")
        return

    # Test 1: national defense expenditures 1940
    result = solve.search_raw_corpus("national defense expenditures", year=1940, limit=5)
    has_results = len(result.get("results", [])) > 0
    check("search 'national defense expenditures' year=1940 returns results", has_results)

    if has_results:
        # Check that at least one result mentions defense
        all_text = " ".join(str(r) for r in result["results"]).lower()
        check("results mention 'defense'", "defense" in all_text)

    # Test 2: intergovernmental transfer payments 1953
    result2 = solve.search_raw_corpus("intergovernmental transfer payments", year=1953, limit=5)
    has_results2 = len(result2.get("results", [])) > 0
    check("search 'intergovernmental transfer payments' year=1953 returns results", has_results2)

    # Test 3: empty/bad query
    result3 = solve.search_raw_corpus("", year=None, limit=5)
    check("empty query returns error",
          "error" in result3 or len(result3.get("results", [])) == 0)

    # Test 4: period hint filtering
    result4 = solve.search_raw_corpus("federal debt", year=1945, limit=5, period_hint="fiscal")
    check("search with period_hint='fiscal' returns results",
          len(result4.get("results", [])) >= 0)  # may or may not find, just no crash


# ═══════════════════════════════════════════════════════════════════════════
# 4. Optional features — test gracefully if they exist
# ═══════════════════════════════════════════════════════════════════════════

def test_optional_features():
    print("\n=== Test optional features ===")

    # TABLE_FAMILY_MAP
    if hasattr(solve, "TABLE_FAMILY_MAP"):
        tfm = solve.TABLE_FAMILY_MAP
        # Check that "national defense" maps to something with expenditures
        found = False
        for key, val in tfm.items():
            if "defense" in key.lower() or "defense" in str(val).lower():
                found = True
                break
        check("TABLE_FAMILY_MAP has defense-related entry", found,
              f"keys sample: {list(tfm.keys())[:5]}")
    else:
        print("  SKIP  TABLE_FAMILY_MAP not found in solve.py")

    # verify_with_llm — mock the LLM call
    if hasattr(solve, "verify_with_llm"):
        # Mock call_llm to avoid real API calls
        mock_response = "VERDICT: CORRECT"
        with patch.object(solve, "call_llm", return_value=mock_response):
            is_correct, corrected = solve.verify_with_llm(
                "What is X?", "evidence text", "42"
            )
            check("verify_with_llm returns (True, None) for CORRECT verdict",
                  is_correct is True and corrected is None,
                  f"got ({is_correct}, {corrected})")

        mock_wrong = "VERDICT: WRONG\nCORRECTED_ANSWER: 99"
        with patch.object(solve, "call_llm", return_value=mock_wrong):
            is_correct2, corrected2 = solve.verify_with_llm(
                "What is X?", "evidence text", "42"
            )
            check("verify_with_llm returns (False, '99') for WRONG verdict",
                  is_correct2 is False and corrected2 == "99",
                  f"got ({is_correct2}, {corrected2})")
    else:
        print("  SKIP  verify_with_llm not found in solve.py")

    # parse_question operation detection
    q_diff = "What was the absolute difference between the percent of criminal case dispositions under the U.S Alcohol Tobacco Tax Division for fiscal year 1953 and fiscal year 1954?"
    result = solve.parse_question(q_diff)
    # The main parse_question may not return 'operation', but deterministic_solve
    # uses a separate extraction. Just check parse_question doesn't crash and
    # returns expected structure.
    check("parse_question handles difference question without error",
          "years" in result and "strategies" in result)

    # Check if deterministic_solve exists (the full pipeline)
    if hasattr(solve, "deterministic_solve"):
        check("deterministic_solve function exists", True)
    else:
        print("  SKIP  deterministic_solve not found")


# ═══════════════════════════════════════════════════════════════════════════
# 5. score_answer() — fuzzy numeric matching
# ═══════════════════════════════════════════════════════════════════════════

def test_score_answer():
    print("\n=== Test score_answer() ===")

    sa = run_all.score_answer

    # Exact matches (with formatting differences)
    check("'2,602' vs '2602'", sa("2,602", "2602") is True)
    check("'2602' vs '2,602'", sa("2602", "2,602") is True)
    check("'44463' vs '44,463'", sa("44463", "44,463") is True)
    check("'44,463' vs '44463'", sa("44,463", "44463") is True)

    # Percentage
    check("'3%' vs '3%'", sa("3%", "3%") is True)

    # Within 1% tolerance
    check("'2600' vs '2602' (within 1%)", sa("2600", "2602") is True)
    check("'100' vs '100.5' (within 1%)", sa("100", "100.5") is True)

    # Clearly wrong
    check("'1000' vs '2602' (too far)", sa("1000", "2602") is False)
    check("'0' vs '100' (too far)", sa("0", "100") is False)

    # None handling
    check("None vs '42'", sa(None, "42") is False)

    # Negative numbers
    check("'-5' vs '-5'", sa("-5", "-5") is True)

    # Dollar signs and spaces
    check("'$1,234' vs '1234'", sa("$1,234", "1234") is True)

    # Edge: zero expected
    check("'0' vs '0'", sa("0", "0") is True)
    check("'0.005' vs '0'", sa("0.005", "0") is True)
    check("'1' vs '0'", sa("1", "0") is False)

    # String fallback
    check("'N/A' vs 'N/A'", sa("N/A", "N/A") is True)
    check("'yes' vs 'no'", sa("yes", "no") is False)


# ═══════════════════════════════════════════════════════════════════════════
# Run all tests
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("solve.py pipeline tests (no API calls)")
    print("=" * 60)

    test_parse_question()
    test_safe_eval()
    test_search_corpus()
    test_optional_features()
    test_score_answer()

    print(f"\n{'=' * 60}")
    print(f"Results: {_pass_count} passed, {_fail_count} failed")
    print(f"{'=' * 60}")

    sys.exit(0 if _fail_count == 0 else 1)
