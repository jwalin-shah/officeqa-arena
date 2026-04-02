"""Grounding audit for OfficeQA Arena answers.

Runs AFTER the model proposes an answer, checking whether the answer is
grounded in the evidence the model used during its tool calls.

Ported from sentient-arena-officeqa/src/stages/verify.py (7-check system)
and sentient-arena-officeqa/src/pipeline.py (REASON_CODE_REPAIRS).
"""

from __future__ import annotations

import json

import re
from typing import Any


# ---------------------------------------------------------------------------
# Reason-code -> targeted repair messages
# ---------------------------------------------------------------------------

REASON_CODE_REPAIRS: dict[str, str] = {
    "source_file_not_present": (
        "No source file was identified in your tool calls. "
        "Use search_tables or query_table_rows to locate the relevant file first."
    ),
    "value_not_found_in_source": (
        "Your proposed answer does not appear in any tool result. "
        "Re-read the table rows and copy the exact value including commas "
        "and formatting (e.g., '2,602.5')."
    ),
    "row_label_mismatch": (
        "No retrieved row label matches the entity in the question. "
        "Copy the row label character-for-character from the table."
    ),
    "column_label_mismatch": (
        "No retrieved column header matches the metric in the question. "
        "Copy the column header exactly as it appears in the table."
    ),
    "snippet_not_grounded": (
        "There is no provenance snippet containing your answer value. "
        "Include a matched_snippet that is a verbatim copy-paste from the corpus."
    ),
    "year_not_aligned": (
        "The year in your evidence does not match the year asked about. "
        "Check the column headers and file names carefully."
    ),
    "topic_not_aligned": (
        "Your evidence rows do not relate to the metric asked about. "
        "The table title or row labels should contain keywords from the question."
    ),
}


# ---------------------------------------------------------------------------
# Text normalization helpers
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _norm_numeric(value: Any) -> str:
    """Strip financial formatting, return bare number string."""
    text = str(value or "").lower().replace(",", "").replace("$", "").strip()
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# Question parsing (lightweight regex / keyword extraction)
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")

_STOP_WORDS = frozenset({
    "what", "were", "from", "with", "that", "this", "using", "only",
    "reported", "values", "total", "calendar", "year", "the", "for",
    "and", "was", "how", "much", "many", "which", "does", "have",
    "been", "are", "million", "millions", "billion", "billions",
    "dollars", "percent", "about",
})


def _extract_years(question: str) -> list[str]:
    """Return all 4-digit years found in the question."""
    return _YEAR_RE.findall(question)


def _extract_keywords(question: str) -> set[str]:
    """Return non-stop content words (4+ chars) from the question."""
    tokens = re.findall(r"[a-zA-Z]{4,}", question.lower())
    return {t for t in tokens if t not in _STOP_WORDS}


# ---------------------------------------------------------------------------
# Tool-call log helpers
# ---------------------------------------------------------------------------

def _collect_tool_results(tool_call_log: list[dict]) -> list[dict]:
    """Flatten tool_call_log into a list of individual result dicts.

    Supports two log formats:
    - Agent format: {"tool_calls": [{"name": "...", "args": {...}, "result_preview": "...", "result_full": {...}}]}
    - Direct format: {"tool": "...", "result": {...}}
    """
    results: list[dict] = []
    for entry in tool_call_log:
        # Agent loop format: entries have "tool_calls" list
        tool_calls = entry.get("tool_calls") or []
        for tc in tool_calls:
            # Try full result first, then parse preview
            res = tc.get("result_full") or tc.get("result")
            if res is None and tc.get("result_preview"):
                try:
                    res = json.loads(tc["result_preview"])
                except (json.JSONDecodeError, ValueError):
                    res = {"text": tc["result_preview"]}
            if isinstance(res, list):
                results.extend(r for r in res if isinstance(r, dict))
            elif isinstance(res, dict):
                results.append(res)
        # Direct format: entry itself has "result"
        if not tool_calls:
            res = entry.get("result")
            if isinstance(res, list):
                results.extend(r for r in res if isinstance(r, dict))
            elif isinstance(res, dict):
                results.append(res)
    return results


def _all_result_text(results: list[dict]) -> str:
    """Concatenate all textual content from tool results into one haystack."""
    parts: list[str] = []
    for r in results:
        # Common shapes: {"rows": [...]}, {"text": "..."}, {"tables": [...]}
        for key in ("text", "content", "snippet", "matched_snippet"):
            val = r.get(key)
            if isinstance(val, str):
                parts.append(val)
        # Rows (from query_table_rows)
        rows = r.get("rows") or r.get("data") or []
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    parts.append(" | ".join(str(v) for v in row.values()))
                elif isinstance(row, str):
                    parts.append(row)
        # Tables list (from search_tables)
        tables = r.get("tables") or []
        if isinstance(tables, list):
            for t in tables:
                if isinstance(t, dict):
                    for tkey in ("title", "file", "source_file", "header", "preview"):
                        val = t.get(tkey)
                        if isinstance(val, str):
                            parts.append(val)
    return "\n".join(parts)


def _source_files_from_results(results: list[dict]) -> set[str]:
    """Extract all source file names mentioned in tool results."""
    files: set[str] = set()
    for r in results:
        for key in ("file", "source_file", "filename"):
            val = r.get(key)
            if isinstance(val, str) and val.strip():
                files.add(val.strip())
        # Also check table_info dict (from query_table_rows lean response)
        ti = r.get("table_info")
        if isinstance(ti, dict):
            val = ti.get("source_file")
            if isinstance(val, str) and val.strip():
                files.add(val.strip())
        for t in r.get("tables", []) or []:
            if isinstance(t, dict):
                for key in ("file", "source_file", "filename"):
                    val = t.get(key)
                    if isinstance(val, str) and val.strip():
                        files.add(val.strip())
    return files


def _row_labels_from_results(results: list[dict]) -> list[str]:
    """Collect all row-label-like strings from tool results."""
    labels: list[str] = []
    for r in results:
        for rows in (r.get("rows"), r.get("data"), []):
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict):
                    for key in ("row_label", "label", "item", "description", "name"):
                        val = row.get(key)
                        if isinstance(val, str) and val.strip():
                            labels.append(val.strip())
    return labels


def _column_labels_from_results(results: list[dict]) -> list[str]:
    """Collect all column headers from tool results."""
    labels: list[str] = []
    for r in results:
        for key in ("columns", "headers", "column_labels"):
            val = r.get(key)
            if isinstance(val, list):
                labels.extend(str(v) for v in val if v)
        # Also get keys from row dicts as implicit column names
        for rows in (r.get("rows"), r.get("data"), []):
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict):
                    labels.extend(str(k) for k in row.keys())
                    break  # one row is enough for column names
    return labels


def _table_titles_from_results(results: list[dict]) -> list[str]:
    """Collect table titles / section headers."""
    titles: list[str] = []
    for r in results:
        for key in ("title", "table_title", "section", "table_or_section"):
            val = r.get(key)
            if isinstance(val, str) and val.strip():
                titles.append(val.strip())
        for t in r.get("tables", []) or []:
            if isinstance(t, dict):
                for key in ("title", "table_title"):
                    val = t.get(key)
                    if isinstance(val, str) and val.strip():
                        titles.append(val.strip())
    return titles


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_source_file_present(source_files: set[str]) -> tuple[bool, str | None]:
    if source_files:
        return True, None
    return False, "No source file identified in any tool call."


def _check_value_found_in_source(
    proposed_answer: str, haystack: str,
) -> tuple[bool, str | None]:
    if not proposed_answer.strip():
        return False, "Proposed answer is empty."
    # Try exact match first
    raw = proposed_answer.strip()
    if raw in haystack:
        return True, None
    # Try normalized numeric match
    norm_answer = _norm_numeric(raw)
    if norm_answer and norm_answer in _norm_numeric(haystack):
        return True, None
    # Try without commas
    stripped = raw.replace(",", "")
    if stripped and stripped in haystack.replace(",", ""):
        return True, None
    return False, f"Value '{raw}' not found in any tool result."


def _check_row_label_match(
    question_keywords: set[str], row_labels: list[str],
) -> tuple[bool, str | None]:
    if not row_labels:
        return False, "No row labels found in tool results."
    for label in row_labels:
        label_norm = _norm(label)
        if any(kw in label_norm for kw in question_keywords):
            return True, None
    # Fuzzy: check if any question keyword is a substring of any label
    for label in row_labels:
        label_lower = label.lower()
        for kw in question_keywords:
            if kw in label_lower:
                return True, "fuzzy match only"
    return False, "No row label matches question entity."


def _check_column_label_match(
    question_keywords: set[str], column_labels: list[str],
) -> tuple[bool, str | None]:
    if not column_labels:
        return False, "No column labels found in tool results."
    col_text = " ".join(_norm(c) for c in column_labels)
    if any(kw in col_text for kw in question_keywords):
        return True, None
    return False, "No column header matches question metric."


def _check_snippet_grounded(
    proposed_answer: str, haystack: str,
) -> tuple[bool, str | None]:
    """Check that there is a contiguous snippet in the evidence containing the value."""
    raw = proposed_answer.strip()
    if not raw:
        return False, "No proposed answer to ground."
    norm_val = _norm_numeric(raw)
    if not norm_val:
        # Non-numeric answer: check text presence
        if _norm(raw) in _norm(haystack):
            return True, None
        return False, "Answer text not found in evidence snippets."
    # Look for the numeric value near other content (not isolated)
    # A snippet is grounded if the value appears in a line with other context
    for line in haystack.split("\n"):
        line_stripped = line.strip()
        if not line_stripped:
            continue
        if norm_val in line_stripped.replace(",", "").replace("$", ""):
            if len(line_stripped) > len(norm_val) + 2:
                return True, None
    # Value found anywhere is still acceptable
    if norm_val in haystack.replace(",", "").replace("$", ""):
        return True, "value present but not in a rich snippet context"
    return False, "No provenance snippet contains the answer value."


def _check_year_aligned(
    question_years: list[str], haystack: str, source_files: set[str],
) -> tuple[bool, str | None]:
    if not question_years:
        # No year in question, check passes vacuously
        return True, None
    combined = haystack + " " + " ".join(source_files)
    for year in question_years:
        if year in combined:
            return True, None
    return False, f"Year(s) {question_years} not found in evidence."


def _check_topic_aligned(
    question_keywords: set[str],
    table_titles: list[str],
    row_labels: list[str],
) -> tuple[bool, str | None]:
    if not question_keywords:
        return True, None
    topic_text = _norm(" ".join(table_titles + row_labels))
    if any(kw in topic_text for kw in question_keywords):
        return True, None
    return False, "Question keywords not found in table titles or row labels."


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def audit_answer(
    question: str,
    proposed_answer: str,
    tool_call_log: list[dict],
) -> dict:
    """Run grounding audit on proposed answer.

    Args:
        question: The original question text.
        proposed_answer: The model's proposed answer string.
        tool_call_log: List of dicts from the agent loop, each with
            "tool", "input", and "result" keys.

    Returns:
        {
            "grounded": True/False,
            "score": 5,       # out of 7
            "checks": {
                "source_file_present": True,
                "value_found_in_source": True,
                ...
            },
            "warnings": ["column_label_match: fuzzy match only"],
            "repair_brief": None or "Your answer may be wrong because: ..."
        }
    """
    results = _collect_tool_results(tool_call_log)
    haystack = _all_result_text(results)
    source_files = _source_files_from_results(results)
    row_labels = _row_labels_from_results(results)
    column_labels = _column_labels_from_results(results)
    table_titles = _table_titles_from_results(results)
    question_years = _extract_years(question)
    question_keywords = _extract_keywords(question)

    checks: dict[str, bool] = {}
    warnings: list[str] = []

    # 1. source_file_present
    ok, note = _check_source_file_present(source_files)
    checks["source_file_present"] = ok
    if note:
        warnings.append(f"source_file_present: {note}")

    # 2. value_found_in_source
    ok, note = _check_value_found_in_source(proposed_answer, haystack)
    checks["value_found_in_source"] = ok
    if note:
        warnings.append(f"value_found_in_source: {note}")

    # 3. row_label_match
    ok, note = _check_row_label_match(question_keywords, row_labels)
    checks["row_label_match"] = ok
    if note:
        warnings.append(f"row_label_match: {note}")

    # 4. column_label_match
    ok, note = _check_column_label_match(question_keywords, column_labels)
    checks["column_label_match"] = ok
    if note:
        warnings.append(f"column_label_match: {note}")

    # 5. snippet_grounded
    ok, note = _check_snippet_grounded(proposed_answer, haystack)
    checks["snippet_grounded"] = ok
    if note:
        warnings.append(f"snippet_grounded: {note}")

    # 6. year_aligned
    ok, note = _check_year_aligned(question_years, haystack, source_files)
    checks["year_aligned"] = ok
    if note:
        warnings.append(f"year_aligned: {note}")

    # 7. topic_aligned
    ok, note = _check_topic_aligned(question_keywords, table_titles, row_labels)
    checks["topic_aligned"] = ok
    if note:
        warnings.append(f"topic_aligned: {note}")

    score = sum(1 for v in checks.values() if v)
    grounded = score >= 5

    repair_brief = None
    if score < 5:
        repair_brief = _build_repair_brief_from_checks(checks)

    return {
        "grounded": grounded,
        "score": score,
        "checks": checks,
        "warnings": warnings,
        "repair_brief": repair_brief,
    }


# ---------------------------------------------------------------------------
# Repair message builders
# ---------------------------------------------------------------------------

_CHECK_TO_REASON: dict[str, str] = {
    "source_file_present": "source_file_not_present",
    "value_found_in_source": "value_not_found_in_source",
    "row_label_match": "row_label_mismatch",
    "column_label_match": "column_label_mismatch",
    "snippet_grounded": "snippet_not_grounded",
    "year_aligned": "year_not_aligned",
    "topic_aligned": "topic_not_aligned",
}


def _build_repair_brief_from_checks(checks: dict[str, bool]) -> str:
    """Build a repair brief string from failed checks."""
    lines: list[str] = ["Your answer may be wrong because:"]
    for check_name, passed in checks.items():
        if not passed:
            reason = _CHECK_TO_REASON.get(check_name, check_name)
            repair = REASON_CODE_REPAIRS.get(reason)
            if repair:
                lines.append(f"- {repair}")
    if len(lines) == 1:
        lines.append("- Multiple grounding checks failed. Re-examine your evidence.")
    return "\n".join(lines)


def build_repair_message(audit_result: dict) -> str:
    """Build a targeted retry message from a failed audit.

    This message is intended to be injected into the agent conversation
    to give the model specific guidance on what to fix.

    Args:
        audit_result: The dict returned by audit_answer().

    Returns:
        A human-readable repair message, or empty string if grounded.
    """
    if audit_result.get("grounded", False):
        return ""

    score = audit_result.get("score", 0)
    checks = audit_result.get("checks", {})
    repair_brief = audit_result.get("repair_brief", "")

    parts: list[str] = [
        f"[GROUNDING AUDIT FAILED] Score: {score}/7.",
    ]

    failed_names = [name for name, passed in checks.items() if not passed]
    if failed_names:
        parts.append(f"Failed checks: {', '.join(failed_names)}.")

    if repair_brief:
        parts.append("")
        parts.append(repair_brief)

    parts.append("")
    parts.append(
        "Please re-examine your evidence and try again. "
        "Use the tool results to find the exact values, row labels, "
        "and column headers from the source documents."
    )

    return "\n".join(parts)
