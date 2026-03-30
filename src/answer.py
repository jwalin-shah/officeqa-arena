"""Answer extraction utilities for the OfficeQA agent loop."""
from __future__ import annotations

import re


def extract_final_answer(text: str) -> str | None:
    """Extract content from <FINAL_ANSWER>...</FINAL_ANSWER> tags.

    Returns the stripped content or None if no tags found.
    """
    if not text:
        return None
    m = re.search(
        r"<FINAL_ANSWER>\s*(.*?)\s*</FINAL_ANSWER>",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def extract_echo_answer(text: str) -> str | None:
    """Extract answer from ``echo ... > /app/answer.txt`` pattern.

    Arena sandboxes expect the agent to write a file; this catches the
    simulated variant where the model emits an echo command instead.
    """
    if not text:
        return None
    m = re.search(r'echo\s+-?n?\s*"?([^">]+)"?\s*>\s*/app/answer\.txt', text)
    return m.group(1).strip() if m else None


def extract_from_history(messages: list[dict]) -> str | None:
    """Scan conversation history for the last mentioned numeric value.

    Walks assistant messages in reverse and returns the last token that
    looks like a number (with optional commas, decimals, sign, percent).
    """
    pattern = re.compile(r"-?\d[\d,]*\.?\d*%?")
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content") or ""
        if not isinstance(content, str):
            continue
        matches = pattern.findall(content)
        if matches:
            return matches[-1].replace(",", "")
    return None


def clean_answer(raw: str) -> str:
    """Strip whitespace; if the value is purely numeric drop trailing units."""
    raw = raw.strip()
    # Remove enclosing quotes
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        raw = raw[1:-1].strip()
    # If it looks like "123.45 million", keep only the number
    m = re.match(r"^(-?\d[\d,]*\.?\d*)\s*(million|billion|trillion|thousand|percent|%)?$", raw, re.IGNORECASE)
    if m:
        return m.group(1).replace(",", "")
    return raw
