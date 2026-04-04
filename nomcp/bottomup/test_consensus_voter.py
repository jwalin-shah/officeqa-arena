"""Tests for ConsensusVoter component.

Tests all agreement scenarios, edge cases, and confidence boosting logic.
"""

import json
import sys
from consensus_voter import ConsensusVoter, vote_three_results


def test_full_agreement():
    """All 3 strategies agree on same value."""
    voter = ConsensusVoter()

    result = voter.vote(
        strict_result={
            "value": 1350576.0,
            "confidence": 0.99,
            "method": "strict",
            "row_source": "row_3",
        },
        fuzzy_result={
            "value": 1350576.0,
            "confidence": 0.85,
            "method": "fuzzy",
            "row_source": "row_3",
        },
        contextual_result={
            "value": 1350576.0,
            "confidence": 0.88,
            "method": "contextual",
            "row_source": "row_3",
        },
    )

    assert result["winning_value"] == 1350576.0
    assert result["winning_method"] == "strict"
    assert result["agreement_level"] == "full"
    assert result["num_agreeing"] == 3
    # Base confidence is 0.99 (max), boosted by 1.15 = 1.1385, capped at 0.99
    assert result["winning_confidence"] == 0.99
    assert len(result["risk_flags"]) == 0
    print("✓ test_full_agreement passed")


def test_partial_agreement_2v1():
    """Two strategies agree, one disagrees."""
    voter = ConsensusVoter()

    result = voter.vote(
        strict_result={
            "value": 1350576.0,
            "confidence": 0.99,
            "method": "strict",
        },
        fuzzy_result={
            "value": 1350576.0,
            "confidence": 0.85,
            "method": "fuzzy",
        },
        contextual_result={
            "value": 1400000.0,
            "confidence": 0.70,
            "method": "contextual",
        },
    )

    assert result["winning_value"] == 1350576.0
    assert result["agreement_level"] == "partial"
    assert result["num_agreeing"] == 2
    # Base confidence is 0.99 (from strict), boosted by 1.05 = 1.0395, capped at 0.99
    assert result["winning_confidence"] == 0.99
    assert "multiple_values_found" in str(result["risk_flags"])
    print("✓ test_partial_agreement_2v1 passed")


def test_no_agreement_all_differ():
    """All three strategies return significantly different values."""
    voter = ConsensusVoter()

    result = voter.vote(
        strict_result={"value": 1000000.0, "confidence": 0.99, "method": "strict"},
        fuzzy_result={"value": 2000000.0, "confidence": 0.85, "method": "fuzzy"},
        contextual_result={"value": 3000000.0, "confidence": 0.70, "method": "contextual"},
    )

    # Should pick the highest confidence result (strict at 0.99)
    assert result["winning_value"] == 1000000.0
    assert result["winning_method"] == "strict"
    assert result["agreement_level"] == "none"
    assert result["num_agreeing"] == 1
    # Base confidence 0.99, penalized by 0.95 = 0.9405
    assert result["winning_confidence"] == 0.9405
    assert "no_agreement_all_differ" in result["risk_flags"]
    print("✓ test_no_agreement_all_differ passed")


def test_close_match_within_tolerance():
    """Values are close (within 1% tolerance) - should be treated as agreement."""
    voter = ConsensusVoter()

    result = voter.vote(
        strict_result={"value": 1000000.0, "confidence": 0.95, "method": "strict"},
        fuzzy_result={"value": 1005000.0, "confidence": 0.80, "method": "fuzzy"},  # 0.5% diff, within 1%
        contextual_result={
            "value": 1000000.0,
            "confidence": 0.85,
            "method": "contextual",
        },
    )

    # All three values within 1% tolerance, so treated as full agreement
    assert result["agreement_level"] == "full"
    assert result["num_agreeing"] == 3
    # Base confidence is 0.95 (max), boosted by 1.15 = 1.0925, capped at 0.99
    assert result["winning_confidence"] == 0.99
    print("✓ test_close_match_within_tolerance passed")


def test_all_none():
    """All three strategies return None."""
    voter = ConsensusVoter()

    result = voter.vote(
        strict_result=None,
        fuzzy_result=None,
        contextual_result=None,
    )

    assert result["winning_value"] is None
    assert result["winning_confidence"] == 0.0
    assert result["winning_method"] is None
    assert result["agreement_level"] == "none"
    assert result["num_agreeing"] == 0
    assert "all_results_none" in result["risk_flags"]
    print("✓ test_all_none passed")


def test_one_valid_result():
    """Only one strategy returns a value, others are None."""
    voter = ConsensusVoter()

    result = voter.vote(
        strict_result={
            "value": 1350576.0,
            "confidence": 0.99,
            "method": "strict",
        },
        fuzzy_result=None,
        contextual_result=None,
    )

    assert result["winning_value"] == 1350576.0
    assert result["winning_method"] == "strict"
    assert result["agreement_level"] == "none"
    assert result["num_agreeing"] == 1
    # Base confidence 0.99, penalized by 0.95 = 0.9405
    assert result["winning_confidence"] == 0.9405
    print("✓ test_one_valid_result passed")


def test_two_valid_results():
    """Two strategies return values, one returns None."""
    voter = ConsensusVoter()

    result = voter.vote(
        strict_result={
            "value": 1350576.0,
            "confidence": 0.99,
            "method": "strict",
        },
        fuzzy_result={
            "value": 1350576.0,
            "confidence": 0.85,
            "method": "fuzzy",
        },
        contextual_result=None,
    )

    assert result["winning_value"] == 1350576.0
    assert result["agreement_level"] == "full"  # Both valid results agree
    assert result["num_agreeing"] == 2
    # Base confidence 0.99, boosted by 1.15 = 1.1385, capped at 0.99
    assert result["winning_confidence"] == 0.99
    print("✓ test_two_valid_results passed")


def test_confidence_boost_math():
    """Verify confidence boost calculations are correct."""
    voter = ConsensusVoter()

    # Full agreement: 0.80 * 1.15 = 0.92
    boosted = voter.boost_confidence_for_agreement("full", [0.80, 0.75, 0.70])
    assert boosted == 0.92

    # Partial agreement: 0.90 * 1.05 = 0.945
    boosted = voter.boost_confidence_for_agreement("partial", [0.90, 0.85])
    assert boosted == 0.945

    # No agreement: 0.99 * 0.95 = 0.9405
    boosted = voter.boost_confidence_for_agreement("none", [0.99])
    assert boosted == 0.9405

    # Capping at 0.99: 0.99 * 1.15 = 1.1385 -> 0.99
    boosted = voter.boost_confidence_for_agreement("full", [0.99, 0.95])
    assert boosted == 0.99

    print("✓ test_confidence_boost_math passed")


def test_check_agreement():
    """Test the check_agreement helper method."""
    voter = ConsensusVoter()

    # Exact match
    assert voter.check_agreement(1000.0, 1000.0) == "exact"

    # Close match (within 1%)
    assert voter.check_agreement(1000.0, 1005.0) == "close"  # 0.5% diff
    assert voter.check_agreement(1000.0, 990.0) == "close"  # 1% diff (at tolerance)

    # Disagree (beyond 1%)
    assert voter.check_agreement(1000.0, 1020.0) == "disagree"  # 2% diff

    # With None values
    assert voter.check_agreement(1000.0, None) == "disagree"
    assert voter.check_agreement(None, 1000.0) == "disagree"

    print("✓ test_check_agreement passed")


def test_rank_results():
    """Test result ranking by confidence."""
    voter = ConsensusVoter()

    results = [
        {"value": 1000.0, "confidence": 0.70},
        {"value": 2000.0, "confidence": 0.95},
        {"value": 3000.0, "confidence": 0.80},
        None,
    ]

    ranked = voter.rank_results(results)
    assert len(ranked) == 3
    assert ranked[0][0]["value"] == 2000.0
    assert ranked[0][1] == 0.95
    assert ranked[1][0]["value"] == 3000.0
    assert ranked[2][0]["value"] == 1000.0

    print("✓ test_rank_results passed")


def test_convenience_function():
    """Test the standalone vote_three_results function."""
    result = vote_three_results(
        strict_result={"value": 100.0, "confidence": 0.99, "method": "strict"},
        fuzzy_result={"value": 100.0, "confidence": 0.85, "method": "fuzzy"},
        contextual_result={"value": 100.0, "confidence": 0.88, "method": "contextual"},
    )

    assert result["winning_value"] == 100.0
    assert result["agreement_level"] == "full"
    print("✓ test_convenience_function passed")


def test_output_structure():
    """Verify output dictionary has all required fields."""
    voter = ConsensusVoter()

    result = voter.vote(
        strict_result={"value": 1000.0, "confidence": 0.99, "method": "strict"},
        fuzzy_result={"value": 1000.0, "confidence": 0.85, "method": "fuzzy"},
        contextual_result={"value": 1000.0, "confidence": 0.88, "method": "contextual"},
    )

    required_keys = {
        "winning_value",
        "winning_confidence",
        "winning_method",
        "agreement_level",
        "num_agreeing",
        "voting_details",
        "reasoning",
        "risk_flags",
    }
    assert set(result.keys()) == required_keys

    # Check voting_details structure
    assert "strict" in result["voting_details"]
    assert "fuzzy" in result["voting_details"]
    assert "contextual" in result["voting_details"]

    print("✓ test_output_structure passed")


def test_large_value_differences():
    """Test handling of significantly different values."""
    voter = ConsensusVoter()

    result = voter.vote(
        strict_result={
            "value": 1350576.0,
            "confidence": 0.99,
            "method": "strict",
        },
        fuzzy_result={
            "value": 1400000.0,
            "confidence": 0.70,
            "method": "fuzzy",
        },
        contextual_result={
            "value": 1350576.0,
            "confidence": 0.88,
            "method": "contextual",
        },
    )

    # Strict and contextual agree, fuzzy disagrees
    assert result["winning_value"] == 1350576.0
    assert result["agreement_level"] == "partial"
    assert result["num_agreeing"] == 2
    assert "multiple_values_found" in str(result["risk_flags"])
    print("✓ test_large_value_differences passed")


def run_all_tests():
    """Run all test cases."""
    tests = [
        test_full_agreement,
        test_partial_agreement_2v1,
        test_no_agreement_all_differ,
        test_close_match_within_tolerance,
        test_all_none,
        test_one_valid_result,
        test_two_valid_results,
        test_confidence_boost_math,
        test_check_agreement,
        test_rank_results,
        test_convenience_function,
        test_output_structure,
        test_large_value_differences,
    ]

    print("Running ConsensusVoter tests...\n")
    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test_fn.__name__} failed: {e}", file=sys.stderr)
            failed += 1
        except Exception as e:
            print(f"✗ {test_fn.__name__} error: {e}", file=sys.stderr)
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
