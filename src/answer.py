"""Answer extraction utilities for the OfficeQA agent loop."""
from __future__ import annotations

import re


def extract_final_answer(text: str) -> str | None:
    """Extract content from <FINAL_ANSWER>...</FINAL_ANSWER> tags."""
    if not text:
        return None
    m = re.search(
        r"<FINAL_ANSWER>\s*(.*?)\s*</FINAL_ANSWER>",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def extract_echo_answer(text: str) -> str | None:
    """Extract answer from an echo-to-/app/answer.txt shell command."""
    if not text:
        return None
    m = re.search(
        r"""echo(?:\s+-n)?\s+["']?([^"'>]+)["']?\s*>\s*/app/answer\.txt""",
        text,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def extract_from_history(messages: list[dict]) -> str | None:
    """Extract answer from compute_expression tool results only."""
    pattern = re.compile(r"-?\d[\d,]*\.?\d*%?")
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content") or ""
        if not isinstance(content, str):
            continue
        if '"result"' in content:
            matches = pattern.findall(content)
            if matches:
                return matches[-1].replace(",", "")
    return None


def clean_answer(raw: str) -> str:
    """Normalize whitespace and preserve percentage formatting when present."""
    raw = raw.strip()

    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        raw = raw[1:-1].strip()

    percent_match = re.match(
        r"^(-?\d[\d,]*\.?\d*)\s*(percent|%)$",
        raw,
        re.IGNORECASE,
    )
    if percent_match:
        return percent_match.group(1).replace(",", "") + "%"

    scaled_number_match = re.match(
        r"^(-?\d[\d,]*\.?\d*)\s*(million|billion|trillion|thousand)?$",
        raw,
        re.IGNORECASE,
    )
    if scaled_number_match:
        return scaled_number_match.group(1).replace(",", "")

    return raw
