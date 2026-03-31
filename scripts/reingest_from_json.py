#!/usr/bin/env python3
"""Re-ingest OfficeQA Treasury Bulletin parsed JSONs into a slim SQLite DB.

Self-contained script — no imports from the legacy codebase.  Ports the
essential parsing logic from normalized_treasury_rows.py inline and builds
a compressed SQLite database with msgpack+zstd cell blobs that include
series_label.

Usage:
    python3 scripts/reingest_from_json.py \
        --json-dir /path/to/jsons \
        --output /path/to/output.sqlite3
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

try:
    import msgpack
except ImportError:
    sys.exit("ERROR: msgpack not installed.  pip install msgpack")

try:
    import zstandard as zstd
except ImportError:
    sys.exit("ERROR: zstandard not installed.  pip install zstandard")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ZSTD_LEVEL = 3
COMMIT_EVERY = 50
PROGRESS_EVERY = 50

_MONTH_NAME_TO_NUM: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_MONTH_PATTERN = (
    r"january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)


# ---------------------------------------------------------------------------
# HTML table parser
# ---------------------------------------------------------------------------

class _HTMLTableRowParser(HTMLParser):
    """Parse HTML tables, expanding colspan so column indices align."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._cur: list[str] = []
        self._cell: list[str] = []
        self._in_cell = False
        self._colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._cur = []
        elif tag in {"td", "th"}:
            self._in_cell = True
            self._cell = []
            self._colspan = 1
            for name, value in attrs:
                if name == "colspan" and value is not None:
                    try:
                        self._colspan = max(1, int(value))
                    except ValueError:
                        pass

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            text = " ".join("".join(self._cell).split())
            self._cur.append(text)
            for _ in range(self._colspan - 1):
                self._cur.append(text)
            self._in_cell = False
            self._colspan = 1
        elif tag == "tr" and self._cur:
            self.rows.append(self._cur)


def _extract_table_rows(table_html: str) -> list[list[str]]:
    parser = _HTMLTableRowParser()
    try:
        parser.feed(table_html or "")
    except Exception:
        return []
    return parser.rows


# ---------------------------------------------------------------------------
# Dataclass for normalized rows
# ---------------------------------------------------------------------------

@dataclass
class NormalizedRow:
    source_file: str
    table_id: str
    table_group_id: str
    table_title: str
    units_line: str
    row_ordinal: int
    row_label: str
    column_ordinal: int
    column_label: str
    time_scope: str
    year: int | None
    month: int | None
    value_raw: str
    normalized_value: float | None
    row_type: str
    section_path: str
    page: int | None
    bbox: list[float] | None
    footnotes: list[str]
    provenance_snippet: str
    parse_flags: list[str]
    confidence: float
    series_label: str = ""
    context_text: str = ""
    table_type: str = "unknown"
    data_category: str = "other"
    frequency: str = "unknown"
    has_revisions: bool = False
    period_basis: str = "unknown"
    revision_status: str = "unknown"
    temporal_granularity: str = "unknown"
    has_month_rows: bool = False
    has_calendar_year_total: bool = False


# ---------------------------------------------------------------------------
# Numeric parsing helpers
# ---------------------------------------------------------------------------

def _clean_numeric_text(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace(",", "")
    text = re.sub(r"\s+\d+/$", "", text)
    text = re.sub(r"\s+\d+/\s*\d+/$", "", text)
    return text.strip()


def _parse_numeric(value: str) -> float | None:
    text = _clean_numeric_text(value)
    if not text or text in {"-", "*", "nan", "n.a."}:
        return None
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _row_to_snippet(row: list[str]) -> str:
    return " | ".join(str(cell or "").strip() for cell in row)


# ---------------------------------------------------------------------------
# Date/month parsing
# ---------------------------------------------------------------------------

def _parse_month_label(label: str) -> tuple[int | None, int | None]:
    text = str(label or "").strip().lower().rstrip(".")
    m = re.match(
        r"^((?:19|20)\d{2})[-/](" + _MONTH_PATTERN + r")$", text,
    )
    if m:
        return int(m.group(1)), _MONTH_NAME_TO_NUM.get(m.group(2))
    m = re.match(r"^(" + _MONTH_PATTERN + r")$", text)
    if m:
        return None, _MONTH_NAME_TO_NUM.get(m.group(1))
    return None, None


def _parse_annual_scope(label: str, active_year: int | None) -> tuple[str, int | None, list[str]]:
    raw = str(label or "").strip()
    flags: list[str] = []
    m = re.match(r"^((?:19|20)\d{2})\b", raw)
    if m:
        year = int(m.group(1))
        if raw != m.group(1):
            flags.append("annual_scope_from_estimated_label")
        return str(year), year, flags
    if raw.lower().startswith("calendar yr") and active_year is not None:
        flags.append("annual_scope_from_calendar_year_row")
        return str(active_year), active_year, flags
    return "", None, flags


def _parse_column_header_date(header: str) -> tuple[int | None, int | None]:
    """Parse date from column header.  Returns (year, month)."""
    text = str(header or "").strip()
    # Strip trailing revision markers
    text = re.sub(r"\s*[pre]\s*$", "", text, flags=re.IGNORECASE)
    # Strip trailing footnote markers
    text = re.sub(r"\s*\d*/\s*$", "", text)
    text = re.sub(r"\s*[½¼¾⅓⅔]+\s*$", "", text)
    text = text.strip().rstrip(".")

    # "Month DD, YYYY" or "Month YYYY"
    m = re.match(
        r"^(" + _MONTH_PATTERN + r")\.?\s+(?:\d{1,2},?\s+)?((?:19|20)\d{2})$",
        text, re.IGNORECASE,
    )
    if m:
        return int(m.group(2)), _MONTH_NAME_TO_NUM.get(m.group(1).lower().rstrip("."))

    # "YYYY-MonthName"
    m = re.match(
        r"^((?:19|20)\d{2})[-/]\s*(" + _MONTH_PATTERN + r")\.?",
        text, re.IGNORECASE,
    )
    if m:
        return int(m.group(1)), _MONTH_NAME_TO_NUM.get(m.group(2).lower().rstrip("."))

    # "YYYY" alone
    m = re.fullmatch(r"((?:19|20)\d{2})", text)
    if m:
        return int(m.group(1)), None

    # Prefix + YYYY (e.g. "Actual 1938", "Fiscal year 1953")
    m = re.search(r"\b((?:19|20)\d{2})\s*$", text)
    if m:
        return int(m.group(1)), None

    # Month name alone
    cleaned = text.lower().rstrip(".")
    month_num = _MONTH_NAME_TO_NUM.get(cleaned)
    if month_num is not None:
        return None, month_num

    return None, None


# ---------------------------------------------------------------------------
# Multi-row header merging
# ---------------------------------------------------------------------------

def _merge_multi_row_headers(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    if len(rows) < 3:
        return (
            [str(c or "").strip() for c in rows[0]] if rows else [],
            rows[1:] if rows else [],
        )

    first_row = [str(c or "").strip() for c in rows[0]]
    second_row = [str(c or "").strip() for c in rows[1]]

    data_cells = first_row[1:] if len(first_row) > 1 else first_row
    empty_count = sum(1 for c in data_cells if not c or c.startswith("col_"))

    if len(data_cells) == 0:
        return first_row, rows[1:]

    empty_ratio = empty_count / len(data_cells)

    # Case 1: >50% empty header cells -> merge with second row
    if empty_ratio > 0.5 and len(second_row) >= len(first_row):
        merged = []
        for i in range(max(len(first_row), len(second_row))):
            top = first_row[i] if i < len(first_row) else ""
            bottom = second_row[i] if i < len(second_row) else ""
            if top and bottom:
                merged.append(f"{top} {bottom}")
            elif top:
                merged.append(top)
            else:
                merged.append(bottom)
        return merged, rows[2:]

    # Case 2: Colspan-expanded years + month row
    if len(first_row) == len(second_row):
        year_count = 0
        month_count = 0
        for c in data_cells:
            if re.fullmatch(r"(?:19|20)\d{2}", c):
                year_count += 1
        second_data = second_row[1:] if len(second_row) > 1 else second_row
        for c in second_data:
            cleaned = str(c or "").strip().lower().rstrip(".")
            if _MONTH_NAME_TO_NUM.get(cleaned) is not None:
                month_count += 1

        if (len(data_cells) > 0 and year_count / len(data_cells) > 0.5
                and len(second_data) > 0 and month_count / len(second_data) > 0.3):
            merged = []
            for i in range(len(first_row)):
                top = first_row[i]
                bottom = second_row[i] if i < len(second_row) else ""
                if top and bottom and re.fullmatch(r"(?:19|20)\d{2}", top):
                    merged.append(f"{bottom} {top}")
                elif top and bottom:
                    merged.append(f"{top} {bottom}")
                elif top:
                    merged.append(top)
                else:
                    merged.append(bottom)
            return merged, rows[2:]

    return first_row, rows[1:]


# ---------------------------------------------------------------------------
# Table classification
# ---------------------------------------------------------------------------

def _classify_table(headers: list[str], data_rows: list[list[str]]) -> str:
    if not headers or not data_rows:
        return "unknown"

    row_date_count = 0
    for row in data_rows[:20]:
        if not row:
            continue
        label = str(row[0] or "").strip()
        _, row_month = _parse_month_label(label)
        if row_month is not None:
            row_date_count += 1
        elif re.fullmatch(r"(?:19|20)\d{2}", label):
            row_date_count += 1

    col_date_count = 0
    for h in headers[1:]:
        hy, hm = _parse_column_header_date(h)
        if hy is not None or hm is not None:
            col_date_count += 1

    data_col_count = max(len(headers) - 1, 1)
    sample_row_count = min(len(data_rows), 20)

    header_text = " ".join(h.lower() for h in headers)
    if any(kw in header_text for kw in ("issue date", "maturity date", "maturity", "yield", "coupon")):
        return "securities_listing"

    if sample_row_count > 0 and row_date_count / sample_row_count > 0.5:
        return "time_series"

    if data_col_count > 0 and col_date_count / data_col_count > 0.5:
        full_date_count = 0
        for h in headers[1:]:
            hy, hm = _parse_column_header_date(h)
            if hy is not None and hm is not None:
                full_date_count += 1
        if full_date_count > 0:
            return "balance_sheet"
        return "cross_tab"

    numeric_cells = 0
    total_cells = 0
    for row in data_rows[:10]:
        for cell in row[1:]:
            total_cells += 1
            if _parse_numeric(str(cell or "")) is not None:
                numeric_cells += 1
    if total_cells > 0 and numeric_cells / total_cells < 0.3 and len(data_rows) < 10:
        return "summary"

    return "unknown"


# ---------------------------------------------------------------------------
# Revision / category / inference helpers
# ---------------------------------------------------------------------------

def _detect_revision_markers(value: str) -> list[str]:
    markers: list[str] = []
    text = str(value or "").strip()
    if re.search(r"\bp\b|\bp$", text, re.IGNORECASE):
        markers.append("preliminary")
    if re.search(r"\br\b|\br$", text, re.IGNORECASE):
        markers.append("revised")
    if re.search(r"\be\b|\be$", text, re.IGNORECASE):
        markers.append("estimated")
    return markers


def _infer_data_category(title: str) -> str:
    t = str(title or "").lower()
    if any(kw in t for kw in ("public debt", "debt outstanding")):
        return "public_debt"
    if any(kw in t for kw in ("international capital", "foreign", "capital movements")):
        return "international_capital"
    if any(kw in t for kw in ("tax", "revenue", "receipts", "internal revenue")):
        return "tax_revenue"
    if any(kw in t for kw in ("securities", "bonds", "notes", "bills", "obligations")):
        return "federal_securities"
    if any(kw in t for kw in ("budget", "expenditure", "outlay", "spending")):
        return "budget"
    if any(kw in t for kw in ("cash", "income", "outgo", "balance")):
        return "cash_operations"
    if any(kw in t for kw in ("monetary", "money", "currency", "bank note")):
        return "monetary"
    if any(kw in t for kw in ("customs", "import", "export", "trade")):
        return "trade"
    return "other"


def _infer_frequency(time_scopes: list[str]) -> str:
    if not time_scopes:
        return "unknown"
    monthly = sum(1 for s in time_scopes if re.fullmatch(r"\d{4}-\d{2}", s))
    annual = sum(1 for s in time_scopes if re.fullmatch(r"\d{4}", s))
    if monthly > annual and monthly > 0:
        return "monthly"
    if annual > 0 and monthly == 0:
        return "annual"
    if monthly > 0 and annual > 0:
        return "mixed"
    return "unknown"


def _infer_period_basis(title: str, text: str, bulletin_month: int | None = None) -> str:
    hay = f"{title}\n{text[:500]}".lower()
    if "fiscal year" in hay or "fiscal years" in hay:
        return "fiscal"
    if "calendar year" in hay or "calendar years" in hay:
        return "calendar"
    if "month ended" in hay or "months ended" in hay:
        return "monthly_reporting"
    if bulletin_month is not None and bulletin_month in {1, 2, 3} and re.search(r"\b(19|20)\d{2}\b", hay):
        return "mixed_or_year_end"
    return "unknown"


def _infer_revision_status(title: str, text: str) -> str:
    hay = f"{title}\n{text[:500]}".lower()
    if "preliminary" in hay:
        return "preliminary"
    if "revised" in hay:
        return "revised"
    if "estimated" in hay or "estimate" in hay:
        return "estimated"
    if "final" in hay:
        return "final"
    return "unknown"


def _infer_temporal_granularity(text: str, has_month_rows: bool, has_calendar_year_total: bool) -> str:
    if has_month_rows and has_calendar_year_total:
        return "mixed"
    if has_month_rows:
        return "monthly"
    if has_calendar_year_total:
        return "annual"
    hay = text[:500].lower()
    if any(m in hay for m in ["january", "february", "march", "april", "monthly"]):
        return "monthly"
    if "quarter" in hay:
        return "quarterly"
    if re.search(r"\b(19|20)\d{2}\b", hay):
        return "annual"
    return "unknown"


def _confidence_for_flags(flags: list[str], time_scope: str) -> float:
    if not time_scope:
        return 0.50
    flag_set = set(flags)
    if "time_scope_from_row_label" in flag_set:
        return 0.95
    if "time_scope_from_column_header_date" in flag_set:
        return 0.90
    if "time_scope_from_column_header_year" in flag_set:
        return 0.85
    if "time_scope_from_column_month_active_year" in flag_set:
        return 0.80
    if "time_scope_from_active_year" in flag_set or "time_scope_from_header_month" in flag_set:
        return 0.75
    return 0.75


def _parse_source_bulletin_month(source_file: str) -> int | None:
    match = re.search(r"treasury_bulletin_(?:\d{4})_(\d{2})", str(source_file or ""))
    if match is None:
        return None
    try:
        month = int(match.group(1))
    except ValueError:
        return None
    return month if 1 <= month <= 12 else None


def _parse_source_bulletin_year(source_file: str) -> int | None:
    match = re.search(r"treasury_bulletin_(\d{4})_\d{2}", str(source_file or ""))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _has_calendar_year_total(
    *, table_title: str, headers: list[str], data_rows: list[list[str]],
) -> bool:
    hay = " ".join([
        str(table_title or ""),
        " ".join(str(cell or "") for cell in headers),
        " ".join(str(row[0] or "") for row in data_rows if row),
    ]).lower()
    if "calendar year" in hay or "calendar yr" in hay:
        return True
    for row in data_rows:
        if not row:
            continue
        row_label = str(row[0] or "").strip().lower()
        if re.fullmatch(r"(?:19|20)\d{2}", row_label):
            return True
        if row_label.startswith("calendar yr"):
            return True
    return False


def _table_bbox(element: dict[str, Any]) -> tuple[int | None, list[float] | None]:
    boxes = element.get("bbox") or []
    if not boxes:
        return None, None
    first = boxes[0] if boxes else {}
    if not isinstance(first, dict):
        return None, None
    page = first.get("page_id")
    coord = first.get("coord")
    return (
        int(page) if isinstance(page, int) else None,
        coord if isinstance(coord, list) else None,
    )


# ---------------------------------------------------------------------------
# Core normalization: per-table
# ---------------------------------------------------------------------------

def _normalize_table_records(
    *,
    source_file: str,
    table_id: str,
    table_title: str,
    units_line: str,
    footnotes: list[str],
    table_group_id: str,
    page: int | None,
    bbox: list[float] | None,
    rows: list[list[str]],
    context_text: str = "",
) -> list[NormalizedRow]:
    if not rows or len(rows[0]) < 2:
        return []

    headers, data_rows = _merge_multi_row_headers(rows)
    table_type = _classify_table(headers, data_rows)
    data_category = _infer_data_category(table_title)
    has_revisions = False
    bulletin_month = _parse_source_bulletin_month(source_file)
    has_month_rows_flag = False

    col_header_dates: list[tuple[int | None, int | None]] = []
    for h in headers:
        col_header_dates.append(_parse_column_header_date(h))
    for h in headers:
        if _detect_revision_markers(h):
            has_revisions = True
            break

    out: list[NormalizedRow] = []
    active_year: int | None = None
    active_series_label: str = ""
    collected_scopes: list[str] = []
    table_text_lines = [table_title, units_line]
    table_text_lines.extend(_row_to_snippet(row) for row in rows)

    for row_idx, row in enumerate(data_rows, start=1):
        if len(row) < 2:
            continue
        row_label = str(row[0] or "").strip()
        if not row_label:
            continue

        # Detect sub-header rows (series_label setters)
        data_cells = [str(c or "").strip() for c in row[1:]]
        unique_data = set(data_cells) - {""}
        is_sub_header = (
            len(unique_data) <= 1
            and len(data_cells) >= 3
            and _parse_numeric(row_label) is None
            and not re.fullmatch(r"(?:19|20)\d{2}", row_label)
        )
        if is_sub_header:
            cleaned = re.sub(r"\s+\d+/\s*$", "", row_label).strip()
            if cleaned:
                active_series_label = cleaned
            continue

        row_year, row_month = _parse_month_label(row_label)
        if row_year is not None:
            active_year = row_year
        elif re.fullmatch(r"(?:19|20)\d{2}", row_label):
            active_year = int(row_label)
        else:
            m = re.match(r"^((?:19|20)\d{2})\b", row_label)
            if m:
                active_year = int(m.group(1))

        if not has_revisions:
            for cell in row[1:]:
                if _detect_revision_markers(str(cell or "")):
                    has_revisions = True
                    break

        for col_idx, raw_value in enumerate(row[1:], start=1):
            value_raw = str(raw_value or "").strip()
            normalized_value = _parse_numeric(value_raw)
            if normalized_value is None:
                continue
            column_label = headers[col_idx] if col_idx < len(headers) else f"col_{col_idx}"
            flags: list[str] = []
            time_scope = ""
            year: int | None = None
            month: int | None = None
            row_type = "value"

            col_year, col_month = col_header_dates[col_idx] if col_idx < len(col_header_dates) else (None, None)
            header_year_match = re.search(r"\b((?:19|20)\d{2})\b", column_label)
            header_month_match = _parse_month_label(column_label)

            if row_month is not None and row_year is not None:
                year, month = row_year, row_month
                time_scope = f"{year}-{month:02d}"
                row_type = "month_row"
                flags.append("time_scope_from_row_label")
            elif row_month is not None and active_year is not None:
                year, month = active_year, row_month
                time_scope = f"{year}-{month:02d}"
                row_type = "month_row"
                flags.append("time_scope_from_active_year")
            elif header_year_match and row_month is not None:
                year = int(header_year_match.group(1))
                month = row_month
                time_scope = f"{year}-{month:02d}"
                row_type = "month_row"
                flags.append("time_scope_from_header_year")
            elif col_year is not None and col_month is not None and row_month is None:
                year, month = col_year, col_month
                time_scope = f"{year}-{month:02d}"
                row_type = "month_row"
                flags.append("time_scope_from_column_header_date")
            elif col_year is not None and col_month is None and row_month is None:
                year = col_year
                time_scope = str(year)
                row_type = "annual_total"
                flags.append("time_scope_from_column_header_year")
            elif col_month is not None and col_year is None and active_year is not None:
                year, month = active_year, col_month
                time_scope = f"{year}-{month:02d}"
                row_type = "month_row"
                flags.append("time_scope_from_column_month_active_year")
            elif header_month_match[1] is not None and active_year is not None:
                year = active_year
                month = header_month_match[1]
                time_scope = f"{year}-{month:02d}"
                row_type = "month_row"
                flags.append("time_scope_from_header_month")
            else:
                annual_scope, annual_year, annual_flags = _parse_annual_scope(row_label, active_year)
                if annual_scope:
                    time_scope = annual_scope
                    year = annual_year
                    row_type = "annual_total"
                    flags.extend(annual_flags)

            if time_scope:
                collected_scopes.append(time_scope)
            if row_type == "month_row" or (
                time_scope and re.fullmatch(r"(?:19|20)\d{2}-(0[1-9]|1[0-2])", time_scope)
            ):
                has_month_rows_flag = True

            out.append(NormalizedRow(
                source_file=source_file,
                table_id=table_id,
                table_group_id=table_group_id,
                table_title=table_title,
                units_line=units_line,
                row_ordinal=row_idx,
                row_label=row_label,
                column_ordinal=col_idx,
                column_label=column_label,
                time_scope=time_scope,
                year=year,
                month=month,
                value_raw=value_raw,
                normalized_value=normalized_value,
                row_type=row_type,
                section_path=table_title,
                page=page,
                bbox=bbox,
                footnotes=list(footnotes),
                provenance_snippet=_row_to_snippet(row),
                parse_flags=flags,
                confidence=_confidence_for_flags(flags, time_scope),
                table_type=table_type,
                data_category=data_category,
                frequency=_infer_frequency(collected_scopes),
                has_revisions=has_revisions,
                series_label=active_series_label,
                context_text=context_text,
            ))

    cal_year_total = _has_calendar_year_total(
        table_title=table_title, headers=headers, data_rows=data_rows,
    )
    table_text = "\n".join(part for part in table_text_lines if part.strip())
    period_basis = _infer_period_basis(table_title, table_text, bulletin_month)
    if period_basis == "mixed_or_year_end" and cal_year_total:
        period_basis = "calendar"
    revision_status = _infer_revision_status(table_title, table_text)
    temporal_granularity = _infer_temporal_granularity(
        table_text,
        has_month_rows=has_month_rows_flag,
        has_calendar_year_total=cal_year_total,
    )
    for r in out:
        r.period_basis = period_basis
        r.revision_status = revision_status
        r.temporal_granularity = temporal_granularity
        r.has_month_rows = has_month_rows_flag
        r.has_calendar_year_total = cal_year_total
    return out


# ---------------------------------------------------------------------------
# Main entry: walk elements in a JSON payload
# ---------------------------------------------------------------------------

def build_normalized_rows_from_payload(
    *, source_file: str, payload: dict[str, Any],
) -> list[NormalizedRow]:
    elements = (payload.get("document") or {}).get("elements") or []
    out: list[NormalizedRow] = []
    current_title = ""
    current_units = ""
    pending_footnotes: list[str] = []

    pending_text_paragraphs: list[str] = []

    for element_idx, element in enumerate(elements):
        etype = str(element.get("type") or "")
        content = str(element.get("content") or "").strip()

        if etype == "section_header":
            current_title = content
            current_units = ""
            pending_footnotes = []
            pending_text_paragraphs = []
            continue
        if etype == "text" and current_title and re.match(r"^\(.*\)$", content):
            current_units = content
            continue
        if etype == "text" and current_title and not current_units:
            units_match = re.search(
                r"\b[Ii]n\s+(millions|billions|thousands)\s+of\s+dollars\b", content,
            )
            if units_match:
                current_units = f"(In {units_match.group(1)} of dollars)"
                continue
        if etype == "text" and current_title:
            # Collect narrative paragraphs preceding the table
            pending_text_paragraphs.append(content)
            continue
        if etype == "footnote" and current_title:
            pending_footnotes.append(content)
            if not current_units:
                units_match = re.search(
                    r"\b[Ii]n\s+(millions|billions|thousands)\s+of\s+dollars\b", content,
                )
                if units_match:
                    current_units = f"(In {units_match.group(1)} of dollars)"
            continue
        if etype != "table" or not current_title:
            continue

        table_rows = _extract_table_rows(content)
        page, bbox_val = _table_bbox(element)
        element_id = element.get("id")
        table_group_id = f"t{element_idx}"
        if element_id is not None:
            table_group_id = f"{table_group_id}:{element_id}"
        source_stem = Path(source_file).stem or source_file
        table_group_id = f"{source_stem}:{table_group_id}"
        table_id = str(element_id) if element_id is not None else table_group_id

        # Capture narrative context (text paragraphs before this table)
        context_text = "\n".join(pending_text_paragraphs).strip()[:2000] if pending_text_paragraphs else ""
        pending_text_paragraphs = []

        out.extend(_normalize_table_records(
            source_file=source_file,
            table_id=table_id,
            table_title=current_title,
            units_line=current_units,
            footnotes=pending_footnotes,
            table_group_id=table_group_id,
            page=page,
            bbox=bbox_val,
            rows=table_rows,
            context_text=context_text,
        ))
        pending_footnotes = []
    return out


# ---------------------------------------------------------------------------
# SQLite schema creation
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS table_index (
    table_pk INTEGER PRIMARY KEY AUTOINCREMENT,
    table_group_id TEXT NOT NULL,
    source_file TEXT NOT NULL,
    table_id TEXT,
    table_title TEXT NOT NULL,
    table_title_norm TEXT,
    section_path TEXT,
    units_line TEXT,
    table_type TEXT,
    data_category TEXT,
    frequency TEXT,
    period_basis TEXT,
    revision_status TEXT,
    temporal_granularity TEXT,
    has_revisions INTEGER,
    has_month_rows INTEGER,
    has_calendar_year_total INTEGER,
    row_count INTEGER,
    column_count INTEGER,
    cell_count INTEGER,
    numeric_cell_count INTEGER,
    min_year INTEGER,
    max_year INTEGER,
    page INTEGER,
    context_text TEXT,
    structure_hints TEXT,
    fingerprint TEXT
);

CREATE TABLE IF NOT EXISTS table_cell_blobs (
    table_pk INTEGER PRIMARY KEY,
    data BLOB NOT NULL,
    cell_count INTEGER NOT NULL,
    raw_bytes INTEGER NOT NULL,
    compressed_bytes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    source_file TEXT PRIMARY KEY,
    bulletin_year INTEGER,
    bulletin_month INTEGER,
    page_count INTEGER,
    table_count INTEGER
);

CREATE TABLE IF NOT EXISTS table_scope_index (
    table_pk INTEGER NOT NULL,
    scope_code TEXT,
    year INTEGER,
    month INTEGER,
    cell_count INTEGER,
    PRIMARY KEY (table_pk, scope_code)
);
"""


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    conn.commit()


# ---------------------------------------------------------------------------
# Blob packing
# ---------------------------------------------------------------------------

_ZSTD_COMPRESSOR = zstd.ZstdCompressor(level=ZSTD_LEVEL)


def _pack_cell_blob(cells: list[dict[str, Any]]) -> tuple[bytes, int, int]:
    """Pack cells into msgpack+zstd blob.  Returns (blob, raw_bytes, compressed_bytes)."""
    payload = {"rows": cells}
    raw = msgpack.packb(payload, use_bin_type=True)
    compressed = _ZSTD_COMPRESSOR.compress(raw)
    return compressed, len(raw), len(compressed)


def _cell_to_slim_dict(row: NormalizedRow) -> dict[str, Any]:
    """Convert a NormalizedRow to a slim dict for blob packing, omitting empty fields."""
    d: dict[str, Any] = {
        "ro": row.row_ordinal,
        "rl": row.row_label,
        "rn": re.sub(r"[/.]", "", row.row_label.lower().strip()),
        "co": row.column_ordinal,
        "cl": row.column_label,
        "cn": re.sub(r"[/.]", "", row.column_label.lower().strip()),
        "vr": row.value_raw,
    }
    if row.time_scope:
        d["ts"] = row.time_scope
    if row.year is not None:
        d["y"] = row.year
    if row.month is not None:
        d["m"] = row.month
    if row.normalized_value is not None:
        d["nv"] = row.normalized_value
    if row.row_type:
        d["rt"] = row.row_type
    if row.confidence is not None:
        d["cf"] = row.confidence
    if row.series_label:
        d["sl"] = row.series_label
    if row.page is not None:
        d["pg"] = row.page
    if row.bbox:
        d["bb"] = row.bbox
    if row.footnotes:
        d["fn"] = row.footnotes
    if row.provenance_snippet:
        d["ps"] = row.provenance_snippet
    return d


# ---------------------------------------------------------------------------
# Per-file ingestion
# ---------------------------------------------------------------------------

def _ingest_file(
    conn: sqlite3.Connection,
    json_path: Path,
    source_file: str,
) -> int:
    """Ingest one JSON file.  Returns number of tables inserted."""
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    all_rows = build_normalized_rows_from_payload(
        source_file=source_file, payload=payload,
    )

    # Group rows by table_group_id
    tables: dict[str, list[NormalizedRow]] = {}
    for r in all_rows:
        tables.setdefault(r.table_group_id, []).append(r)

    # Determine page count from payload
    elements = (payload.get("document") or {}).get("elements") or []
    max_page: int | None = None
    for el in elements:
        for bb in (el.get("bbox") or []):
            if isinstance(bb, dict):
                pg = bb.get("page_id")
                if isinstance(pg, int):
                    if max_page is None or pg > max_page:
                        max_page = pg
    page_count = (max_page + 1) if max_page is not None else None

    bulletin_year = _parse_source_bulletin_year(source_file)
    bulletin_month = _parse_source_bulletin_month(source_file)

    # Insert document record
    conn.execute(
        "INSERT OR REPLACE INTO documents (source_file, bulletin_year, bulletin_month, page_count, table_count) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_file, bulletin_year, bulletin_month, page_count, len(tables)),
    )

    for tgid in sorted(tables):
        trows = tables[tgid]
        if not trows:
            continue
        first = trows[0]

        # Compute aggregates
        years_seen: set[int] = set()
        scope_buckets: dict[str, dict[str, Any]] = {}
        row_ordinals: set[int] = set()
        col_ordinals: set[int] = set()
        numeric_count = 0

        cells_slim: list[dict[str, Any]] = []
        for r in trows:
            row_ordinals.add(r.row_ordinal)
            col_ordinals.add(r.column_ordinal)
            if r.normalized_value is not None:
                numeric_count += 1
            if r.year is not None:
                years_seen.add(r.year)
            if r.time_scope:
                bucket = scope_buckets.setdefault(r.time_scope, {
                    "year": r.year,
                    "month": r.month,
                    "cell_count": 0,
                })
                bucket["cell_count"] += 1
            cells_slim.append(_cell_to_slim_dict(r))

        # Pack blob
        blob_data, raw_bytes, compressed_bytes = _pack_cell_blob(cells_slim)
        cell_count = len(trows)

        # Compute enrichment metadata
        from ingestion_enrichment import (
            compute_table_fingerprint,
            compute_structure_hints,
        )
        fp = compute_table_fingerprint(cells_slim)
        col_labels_for_hints = sorted({c.get("cl", "") for c in cells_slim if c.get("cl")})
        hints = compute_structure_hints(cells_slim, table_title=first.table_title, column_labels=col_labels_for_hints)

        # Insert table_index
        cur = conn.execute(
            """INSERT INTO table_index (
                table_group_id, source_file, table_id, table_title,
                table_title_norm, section_path, units_line,
                table_type, data_category, frequency,
                period_basis, revision_status, temporal_granularity,
                has_revisions, has_month_rows, has_calendar_year_total,
                row_count, column_count, cell_count, numeric_cell_count,
                min_year, max_year, page,
                context_text, structure_hints, fingerprint
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                tgid,
                first.source_file,
                first.table_id,
                first.table_title,
                _normalize_text(first.table_title),
                first.section_path,
                first.units_line,
                first.table_type,
                first.data_category,
                first.frequency,
                first.period_basis,
                first.revision_status,
                first.temporal_granularity,
                1 if first.has_revisions else 0,
                1 if first.has_month_rows else 0,
                1 if first.has_calendar_year_total else 0,
                len(row_ordinals),
                len(col_ordinals),
                cell_count,
                numeric_count,
                min(years_seen) if years_seen else None,
                max(years_seen) if years_seen else None,
                first.page,
                first.context_text or None,
                json.dumps(hints) if hints else None,
                json.dumps(fp) if fp else None,
            ),
        )
        table_pk = cur.lastrowid

        # Insert blob
        conn.execute(
            "INSERT INTO table_cell_blobs (table_pk, data, cell_count, raw_bytes, compressed_bytes) "
            "VALUES (?, ?, ?, ?, ?)",
            (table_pk, blob_data, cell_count, raw_bytes, compressed_bytes),
        )

        # Insert scope records
        for scope_code, bucket in sorted(scope_buckets.items()):
            conn.execute(
                "INSERT OR REPLACE INTO table_scope_index (table_pk, scope_code, year, month, cell_count) "
                "VALUES (?, ?, ?, ?, ?)",
                (table_pk, scope_code, bucket["year"], bucket["month"], bucket["cell_count"]),
            )

    return len(tables)


# ---------------------------------------------------------------------------
# Lookup index builders (step 4)
# ---------------------------------------------------------------------------

def _build_lookup_indexes(conn: sqlite3.Connection) -> None:
    """Build col/row label lookups and summary tables from blob data."""
    print("  Building lookup indexes from blob data...")

    # We iterate through all blobs to extract distinct labels per table
    conn.execute("DROP TABLE IF EXISTS col_label_lookup")
    conn.execute("DROP TABLE IF EXISTS row_label_lookup")

    conn.execute("""
        CREATE TABLE col_label_lookup (
            table_pk INTEGER NOT NULL,
            column_ordinal INTEGER NOT NULL,
            column_label TEXT NOT NULL,
            column_label_norm TEXT NOT NULL,
            PRIMARY KEY (table_pk, column_ordinal)
        )
    """)
    conn.execute("""
        CREATE TABLE row_label_lookup (
            table_pk INTEGER NOT NULL,
            row_ordinal INTEGER NOT NULL,
            row_label TEXT NOT NULL,
            row_label_norm TEXT NOT NULL,
            PRIMARY KEY (table_pk, row_ordinal)
        )
    """)

    decompressor = zstd.ZstdDecompressor()
    cursor = conn.execute(
        "SELECT b.table_pk, b.data FROM table_cell_blobs b"
    )

    col_rows: list[tuple[int, int, str, str]] = []
    row_rows: list[tuple[int, int, str, str]] = []

    for table_pk, blob_data in cursor:
        try:
            raw = decompressor.decompress(blob_data)
            payload = msgpack.unpackb(raw, raw=False)
        except Exception:
            continue

        seen_cols: dict[int, tuple[str, str]] = {}
        seen_rows: dict[int, tuple[str, str]] = {}

        for cell in payload.get("rows", []):
            co = cell.get("co")
            cl = cell.get("cl", "")
            cn = cell.get("cn", "")
            if co is not None and co not in seen_cols:
                seen_cols[co] = (cl, cn)

            ro = cell.get("ro")
            rl = cell.get("rl", "")
            rn = cell.get("rn", "")
            if ro is not None and ro not in seen_rows:
                seen_rows[ro] = (rl, rn)

        for co, (cl, cn) in sorted(seen_cols.items()):
            col_rows.append((table_pk, co, cl, cn))
        for ro, (rl, rn) in sorted(seen_rows.items()):
            row_rows.append((table_pk, ro, rl, rn))

    conn.executemany(
        "INSERT OR IGNORE INTO col_label_lookup VALUES (?,?,?,?)",
        col_rows,
    )
    conn.executemany(
        "INSERT OR IGNORE INTO row_label_lookup VALUES (?,?,?,?)",
        row_rows,
    )

    # Table summary
    conn.execute("DROP TABLE IF EXISTS table_summary")
    conn.execute("""
        CREATE TABLE table_summary AS
        SELECT
            ti.table_pk,
            ti.table_group_id,
            ti.table_title,
            ti.table_title_norm,
            ti.source_file,
            ti.table_type,
            ti.data_category,
            ti.frequency,
            ti.period_basis,
            ti.cell_count,
            ti.numeric_cell_count,
            ti.min_year,
            ti.max_year,
            ti.row_count,
            ti.column_count,
            GROUP_CONCAT(DISTINCT cl.column_label, ' | ') AS column_labels,
            GROUP_CONCAT(DISTINCT cl.column_label_norm, ' ') AS column_labels_norm
        FROM table_index ti
        LEFT JOIN col_label_lookup cl ON cl.table_pk = ti.table_pk
        GROUP BY ti.table_pk
    """)

    # File year coverage
    conn.execute("DROP TABLE IF EXISTS file_year_coverage")
    conn.execute("""
        CREATE TABLE file_year_coverage AS
        SELECT
            ti.source_file,
            ts.year AS data_year,
            COUNT(*) AS table_count
        FROM table_index ti
        JOIN table_scope_index ts ON ts.table_pk = ti.table_pk
        WHERE ts.year IS NOT NULL
        GROUP BY ti.source_file, ts.year
    """)

    # Dedup groups
    conn.execute("DROP TABLE IF EXISTS table_dedup_groups")
    conn.execute("""
        CREATE TABLE table_dedup_groups AS
        SELECT
            table_title_norm,
            COUNT(*) AS copies,
            GROUP_CONCAT(DISTINCT source_file) AS source_files,
            MIN(min_year) AS min_year,
            MAX(max_year) AS max_year
        FROM table_index
        GROUP BY table_title_norm
        HAVING COUNT(*) > 1
    """)

    # Add useful indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ti_source ON table_index(source_file)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ti_title_norm ON table_index(table_title_norm)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ti_group ON table_index(table_group_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scope_year ON table_scope_index(year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_col_norm ON col_label_lookup(column_label_norm)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_row_norm ON row_label_lookup(row_label_norm)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fyc_year ON file_year_coverage(data_year)")

    conn.commit()
    print("  Lookup indexes built.")


def _build_metric_aliases(conn: sqlite3.Connection) -> None:
    """Build metric_aliases table from row/column labels in blobs."""
    from ingestion_enrichment import MetricAliasCollector

    collector = MetricAliasCollector()
    decompressor = zstd.ZstdDecompressor()

    cursor = conn.execute(
        "SELECT b.table_pk, b.data, ti.source_file "
        "FROM table_cell_blobs b JOIN table_index ti ON ti.table_pk = b.table_pk"
    )
    for table_pk, blob_data, source_file in cursor:
        try:
            raw = decompressor.decompress(blob_data)
            payload = msgpack.unpackb(raw, raw=False)
        except Exception:
            continue

        row_labels = []
        col_labels = []
        seen_rl: set[str] = set()
        seen_cl: set[str] = set()
        for cell in payload.get("rows", []):
            rl = cell.get("rl", "")
            if rl and rl not in seen_rl:
                seen_rl.add(rl)
                row_labels.append(rl)
            cl = cell.get("cl", "")
            if cl and cl not in seen_cl:
                seen_cl.add(cl)
                col_labels.append(cl)

        collector.add(row_labels, col_labels, source_file)

    registry = collector.build_registry()

    conn.execute("DROP TABLE IF EXISTS metric_aliases")
    conn.execute("""
        CREATE TABLE metric_aliases (
            canonical TEXT NOT NULL,
            alias TEXT NOT NULL,
            decade INTEGER,
            count INTEGER
        )
    """)
    conn.executemany(
        "INSERT INTO metric_aliases VALUES (?,?,?,?)",
        [(r["canonical"], r["alias"], r["decade"], r["count"]) for r in registry],
    )
    conn.execute("CREATE INDEX idx_alias_canonical ON metric_aliases(canonical)")
    conn.execute("CREATE INDEX idx_alias_alias ON metric_aliases(alias)")
    conn.commit()
    print(f"    {len(registry):,} alias entries")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-ingest OfficeQA Treasury Bulletin JSONs into a slim SQLite DB.",
    )
    parser.add_argument(
        "--json-dir", required=True,
        help="Directory containing treasury_bulletin_YYYY_MM.json files",
    )
    parser.add_argument(
        "--output", required=True,
        help="Path for the output SQLite3 database",
    )
    args = parser.parse_args()

    json_dir = Path(args.json_dir)
    if not json_dir.is_dir():
        sys.exit(f"ERROR: --json-dir {json_dir} is not a directory")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing DB for clean rebuild
    if output_path.exists():
        output_path.unlink()
        print(f"Removed existing {output_path}")

    # Discover JSON files
    json_files = sorted(json_dir.glob("treasury_bulletin_*.json"))
    if not json_files:
        # Fallback: try all .json files
        json_files = sorted(json_dir.glob("*.json"))
    if not json_files:
        sys.exit(f"ERROR: No JSON files found in {json_dir}")

    print(f"Found {len(json_files)} JSON files in {json_dir}")
    print(f"Output: {output_path}")
    print()

    conn = sqlite3.connect(str(output_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
    _create_schema(conn)

    total_tables = 0
    total_files = 0
    errors: list[str] = []
    t0 = time.time()

    for idx, json_path in enumerate(json_files):
        source_file = json_path.stem  # e.g. treasury_bulletin_1940_03
        try:
            n_tables = _ingest_file(conn, json_path, source_file)
            total_tables += n_tables
            total_files += 1
        except Exception as exc:
            errors.append(f"{json_path.name}: {exc}")
            continue

        if (idx + 1) % PROGRESS_EVERY == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            print(
                f"  [{idx + 1:>4}/{len(json_files)}] "
                f"{total_tables:,} tables | "
                f"{elapsed:.1f}s | "
                f"{rate:.1f} files/s"
            )

        if (idx + 1) % COMMIT_EVERY == 0:
            conn.commit()

    conn.commit()
    elapsed = time.time() - t0
    print()
    print(f"Parsing complete: {total_files} files, {total_tables:,} tables in {elapsed:.1f}s")

    if errors:
        print(f"\n  {len(errors)} file(s) had errors:")
        for e in errors[:20]:
            print(f"    - {e}")
        if len(errors) > 20:
            print(f"    ... and {len(errors) - 20} more")
    print()

    # Step 4: build lookup indexes
    print("Step 4: Building lookup indexes...")
    t1 = time.time()
    _build_lookup_indexes(conn)
    print(f"  Done in {time.time() - t1:.1f}s")
    print()

    # Step 5: Build metric alias registry
    print("Step 5: Building metric alias registry...")
    t2 = time.time()
    _build_metric_aliases(conn)
    print(f"  Done in {time.time() - t2:.1f}s")
    print()

    # Step 6: VACUUM
    print("Step 6: VACUUM...")
    t3 = time.time()
    conn.execute("VACUUM")
    print(f"  Done in {time.time() - t3:.1f}s")

    conn.close()

    # Final stats
    db_size = output_path.stat().st_size
    print()
    print("=" * 60)
    print(f"  Files ingested:  {total_files}")
    print(f"  Tables:          {total_tables:,}")
    print(f"  Errors:          {len(errors)}")
    print(f"  DB size:         {db_size / (1024 * 1024):.1f} MB")
    print(f"  Total time:      {time.time() - t0:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
