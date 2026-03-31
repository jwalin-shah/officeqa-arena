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
    """Extract best numeric answer from tool results in conversation history.

    Priority order:
    1. compute_expression result (most reliable — model did the math)
    2. verdict value from extract_values (pre-scored best match)
    3. First value_scaled/value from query_table_rows rows
    4. First value from time series
    """
    import json as _json

    # Pass 1: compute_expression results (highest priority)
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content") or ""
        if not isinstance(content, str):
            continue
        if '"result"' in content:
            try:
                parsed = _json.loads(content)
                if isinstance(parsed, dict) and parsed.get("ok") and parsed.get("result") is not None:
                    return str(parsed["result"])
            except (ValueError, _json.JSONDecodeError):
                pass
            # Fallback regex on compute_expression output
            pattern = re.compile(r"-?\d[\d,]*\.?\d*%?")
            matches = pattern.findall(content)
            if matches:
                return matches[-1].replace(",", "")

    # Pass 2: verdict from extract_values
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content") or ""
        if not isinstance(content, str) or '"verdict"' not in content:
            continue
        try:
            parsed = _json.loads(content)
            verdict = parsed.get("verdict") if isinstance(parsed, dict) else None
            if isinstance(verdict, dict) and verdict.get("value") is not None:
                return str(verdict["value"])
        except (ValueError, _json.JSONDecodeError):
            pass

    # Pass 3: first row value from query_table_rows / extract_values rows
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content") or ""
        if not isinstance(content, str) or '"rows"' not in content:
            continue
        try:
            parsed = _json.loads(content)
            rows = None
            if isinstance(parsed, dict):
                rows = parsed.get("rows")
                # Also check nested results (extract_values format)
                if not rows:
                    for res in parsed.get("results", []):
                        if isinstance(res, dict) and res.get("rows"):
                            rows = res["rows"]
                            break
            if rows and isinstance(rows, list) and len(rows) > 0:
                row = rows[0]
                val = row.get("value_scaled") or row.get("normalized_value") or row.get("value")
                if val is not None and str(val).strip() not in ("", "...", "—", "-"):
                    return str(val)
        except (ValueError, _json.JSONDecodeError):
            pass

    # Pass 4: time series values
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content") or ""
        if not isinstance(content, str) or '"series"' not in content:
            continue
        try:
            parsed = _json.loads(content)
            series = parsed.get("series") if isinstance(parsed, dict) else None
            if isinstance(series, dict) and series:
                # Return the last value in the series (most recent)
                last_key = sorted(series.keys())[-1]
                return str(series[last_key])
        except (ValueError, _json.JSONDecodeError):
            pass

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
