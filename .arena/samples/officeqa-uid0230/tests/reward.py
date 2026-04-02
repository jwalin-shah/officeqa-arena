"""Scoring / reward function for OfficeQA.

Numeric fuzzy-match with configurable tolerance (default 1%).
"""
from __future__ import annotations

import re


def extract_final_answer(text: str) -> str:
    """Return content inside <FINAL_ANSWER> tags, or the original text."""
    if not text:
        return text
    m = re.search(
        r"<FINAL_ANSWER>\s*(.*?)\s*</FINAL_ANSWER>", text, re.DOTALL | re.IGNORECASE
    )
    return m.group(1).strip() if m else text


def _parse_numbers(text: str) -> list[float]:
    """Extract all numbers from *text*, handling commas and Unicode minus."""
    text = text.replace("\u2212", "-").replace("\u2013", "-")
    # Remove thousands separators inside numbers
    text = re.sub(
        r"\d{1,3}(?:,\d{3})+(?:\.\d+)?",
        lambda m: m.group().replace(",", ""),
        text,
    )
    nums: list[float] = []
    for tok in re.findall(r"-?\d+\.?\d*%?", text):
        try:
            nums.append(float(tok.rstrip("%")))
        except ValueError:
            continue
    return nums


def fuzzy_match_answer(
    ground_truth: str,
    predicted: str,
    tolerance: float = 0.01,
) -> tuple[bool, str]:
    """Return (is_correct, rationale).

    Tries numeric comparison first (relative tolerance); falls back to
    case-insensitive substring match for text answers.
    """
    if not ground_truth or not predicted:
        return False, "Empty ground_truth or predicted"

    gt_nums = _parse_numbers(ground_truth)
    pred_nums = _parse_numbers(predicted)

    if gt_nums and pred_nums:
        # Multi-value elementwise comparison when counts match
        if len(gt_nums) > 1 and len(gt_nums) == len(pred_nums):
            all_ok = True
            details = []
            for gv, pv in zip(gt_nums, pred_nums):
                if gv == 0:
                    ok = pv == 0
                else:
                    ok = abs(gv - pv) / abs(gv) <= tolerance
                details.append(f"GT={gv} Pred={pv} {'ok' if ok else 'FAIL'}")
                if not ok:
                    all_ok = False
            if all_ok:
                return True, f"Elementwise match: {'; '.join(details)}"
            return False, f"Elementwise mismatch: {'; '.join(details)}"

        # Single-value comparison (original behavior)
        gt_val = gt_nums[0]
        best_diff = float("inf")
        best_pred = None
        for pv in pred_nums:
            if gt_val == 0:
                if pv == 0:
                    return True, "Both zero"
                continue
            diff = abs(gt_val - pv) / abs(gt_val)
            if diff < best_diff:
                best_diff = diff
                best_pred = pv
            if diff <= tolerance:
                return True, f"Match: GT={gt_val}, Pred={pv}, diff={diff*100:.2f}%"
        if best_pred is not None:
            return False, f"No match: GT={gt_val}, closest={best_pred}, diff={best_diff*100:.2f}%"

    # Text fallback
    gt_c = ground_truth.strip().lower()
    pr_c = predicted.strip().lower()
    if gt_c in pr_c or pr_c in gt_c:
        return True, "Text substring match"
    if gt_c == pr_c:
        return True, "Exact text match"

    return False, f"No match. GT='{ground_truth[:80]}', Pred='{predicted[:80]}'"


def score_answer(
    ground_truth: str,
    predicted: str,
    tolerance: float = 0.01,
) -> float:
    """Return 1.0 if correct, 0.0 otherwise."""
    ok, _ = fuzzy_match_answer(ground_truth, predicted, tolerance)
    return 1.0 if ok else 0.0
