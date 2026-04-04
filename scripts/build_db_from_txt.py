#!/usr/bin/env python3
"""Build a SQLite database directly from Treasury Bulletin TXT files.

Parses pipe-delimited markdown tables (and rare HTML tables) from the 697
TXT files in corpus/, deduplicates by content hash, and produces a SQLite DB
with table_index, table_cells, documents, and master_ledger tables.

Uses ONLY Python stdlib.  No external dependencies.

Usage:
    python3 scripts/build_db_from_txt.py [--corpus CORPUS_DIR] [--output OUTPUT_DB]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import re
import shutil
import sqlite3
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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

COMMIT_EVERY = 200

# ---------------------------------------------------------------------------
# HTML table parser (for the ~3 files with HTML tables)
# ---------------------------------------------------------------------------

class _HTMLTableRowParser(HTMLParser):
    """Parse HTML tables, expanding colspan."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._rows: list[list[str]] = []
        self._cur: list[str] = []
        self._cell: list[str] = []
        self._in_cell = False
        self._colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._rows = []
        elif tag == "tr":
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
        elif tag == "tr" and self._cur:
            self._rows.append(self._cur)
        elif tag == "table" and self._rows:
            self.tables.append(self._rows)
            self._rows = []


def _extract_html_tables(text: str) -> list[list[list[str]]]:
    """Extract HTML tables from text, returning list of tables (each a list of rows)."""
    if "<table" not in text.lower():
        return []
    parser = _HTMLTableRowParser()
    try:
        parser.feed(text)
    except Exception:
        pass
    return parser.tables


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

def _parse_numeric(value: str) -> float | None:
    text = str(value or "").strip().replace(",", "")
    text = re.sub(r"\s+\d+/$", "", text)  # strip footnote markers
    text = text.strip()
    if not text or text in {"-", "*", "nan", "n.a.", "n.a", "(*)"}:
        return None
    # Handle parenthesized negatives: (1234) -> -1234
    m_paren = re.fullmatch(r"\((\d[\d,.]*)\)", text)
    if m_paren:
        try:
            return -float(m_paren.group(1).replace(",", ""))
        except ValueError:
            pass
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _slug(text: str) -> str:
    """Create a search-friendly slug from text."""
    s = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return re.sub(r"\s+", "_", s).strip("_")[:120]


# ---------------------------------------------------------------------------
# Publication metadata from filename
# ---------------------------------------------------------------------------

def _pub_year_month(filename: str) -> tuple[int, int]:
    m = re.search(r"treasury_bulletin_(\d{4})_(\d{2})", filename)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


# ---------------------------------------------------------------------------
# Date parsing from column headers
# ---------------------------------------------------------------------------

def _parse_column_header_date(header: str) -> tuple[int | None, int | None]:
    """Parse date from column header. Returns (year, month)."""
    text = str(header or "").strip()
    # Strip trailing revision markers
    text = re.sub(r"\s*[pre]\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\d*/\s*$", "", text)
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

    # Prefix + YYYY
    m = re.search(r"\b((?:19|20)\d{2})\s*$", text)
    if m:
        return int(m.group(1)), None

    # Month name alone
    cleaned = text.lower().rstrip(".")
    month_num = _MONTH_NAME_TO_NUM.get(cleaned)
    if month_num is not None:
        return None, month_num

    return None, None


def _parse_month_from_row_label(label: str) -> tuple[int | None, int | None]:
    """Parse month from row label. Returns (year, month)."""
    text = str(label or "").strip().lower().rstrip(".")
    # "YYYY-MonthName" or "YYYY/MonthName"
    m = re.match(r"^((?:19|20)\d{2})[-/](" + _MONTH_PATTERN + r")$", text)
    if m:
        return int(m.group(1)), _MONTH_NAME_TO_NUM.get(m.group(2))
    # Month name alone
    m = re.match(r"^(" + _MONTH_PATTERN + r")\.?$", text)
    if m:
        return None, _MONTH_NAME_TO_NUM.get(m.group(1))
    return None, None


# ---------------------------------------------------------------------------
# Period basis detection
# ---------------------------------------------------------------------------

def _detect_period_basis(title: str, raw_text: str) -> str:
    combined = (title + " " + raw_text[:500]).lower()
    has_fiscal = bool(re.search(r"fiscal\s+year", combined))
    has_calendar = bool(re.search(r"calendar\s+year", combined))

    # Check for month names in row labels
    month_row_count = 0
    for line in raw_text.split("\n"):
        if not line.strip().startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) >= 2:
            label = cells[1].strip().lower().rstrip(".")
            if label in _MONTH_NAME_TO_NUM:
                month_row_count += 1

    if has_calendar:
        return "calendar"
    if has_fiscal:
        return "fiscal"
    if month_row_count >= 3:
        return "monthly"
    return "unknown"


# ---------------------------------------------------------------------------
# Detect month rows
# ---------------------------------------------------------------------------

def _detect_has_month_rows(raw_text: str) -> bool:
    count = 0
    for line in raw_text.split("\n"):
        if not line.strip().startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) >= 2:
            label = cells[1].strip().lower().rstrip(".")
            if label in _MONTH_NAME_TO_NUM:
                count += 1
    return count >= 3


# ---------------------------------------------------------------------------
# Clean header cell (strip multi-level "Unnamed" prefixes)
# ---------------------------------------------------------------------------

def _clean_header(h: str) -> str:
    """Clean a header cell, stripping Unnamed prefixes from multi-level headers."""
    parts = [p.strip() for p in h.split(">")]
    for p in reversed(parts):
        if "unnamed" not in p.lower() and p.strip():
            return p.strip()
    return h.strip()


# ---------------------------------------------------------------------------
# Merge multi-row headers
# ---------------------------------------------------------------------------

def _merge_multi_row_headers(
    header_row: list[str], data_rows: list[list[str]]
) -> tuple[list[str], list[list[str]]]:
    """If the second row looks like a sub-header, merge it into the header."""
    if not data_rows:
        return header_row, data_rows

    second_row = data_rows[0]
    if len(second_row) != len(header_row):
        return header_row, data_rows

    # Count how many header cells are empty/unnamed
    data_cells = header_row[1:] if len(header_row) > 1 else header_row
    empty_count = sum(
        1 for c in data_cells
        if not c or c.startswith("col_") or "unnamed" in c.lower()
    )
    if len(data_cells) == 0:
        return header_row, data_rows
    empty_ratio = empty_count / len(data_cells)

    # If >50% empty, merge
    if empty_ratio > 0.5:
        merged = []
        for i in range(len(header_row)):
            top = header_row[i] if i < len(header_row) else ""
            bottom = second_row[i] if i < len(second_row) else ""
            if top and bottom and "unnamed" not in top.lower():
                merged.append(f"{top} {bottom}")
            elif bottom:
                merged.append(bottom)
            else:
                merged.append(top)
        return merged, data_rows[1:]

    # Check for year+month pattern (year headers with month sub-row)
    year_count = sum(
        1 for c in data_cells if re.fullmatch(r"(?:19|20)\d{2}", c.strip())
    )
    second_data = second_row[1:] if len(second_row) > 1 else second_row
    month_count = sum(
        1 for c in second_data
        if c.strip().lower().rstrip(".") in _MONTH_NAME_TO_NUM
    )

    if (len(data_cells) > 0 and year_count / len(data_cells) > 0.5
            and len(second_data) > 0 and month_count / len(second_data) > 0.3):
        merged = []
        for i in range(len(header_row)):
            top = header_row[i]
            bottom = second_row[i] if i < len(second_row) else ""
            if top and bottom and re.fullmatch(r"(?:19|20)\d{2}", top.strip()):
                merged.append(f"{bottom} {top}")
            elif top and bottom:
                merged.append(f"{top} {bottom}")
            elif top:
                merged.append(top)
            else:
                merged.append(bottom)
        return merged, data_rows[1:]

    return header_row, data_rows


# ---------------------------------------------------------------------------
# Extract markdown tables from TXT
# ---------------------------------------------------------------------------

def _extract_markdown_tables(filepath: Path) -> list[dict[str, Any]]:
    """Extract pipe-delimited markdown tables from a TXT file."""
    lines = filepath.read_text(errors="replace").splitlines()
    fname = filepath.name
    pub_year, pub_month = _pub_year_month(fname)
    tables = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("|"):
            i += 1
            continue

        # Scan backward for title and units
        title = ""
        units = ""
        for j in range(max(0, i - 10), i):
            ctx = lines[j].strip()
            if re.search(r"\(.*(?:millions|thousands|dollars|percent|billions).*\)", ctx, re.I):
                units = ctx
            elif ctx and not ctx.startswith("|") and not ctx.startswith("---") and len(ctx) > 8:
                if not re.match(r"^\d+$", ctx.strip()) and not ctx.startswith("Source:"):
                    title = ctx

        # Collect table rows
        table_start = i
        table_lines: list[str] = []
        while i < len(lines):
            row = lines[i].strip()
            if row.startswith("|") or (row.startswith("---") and i == table_start + 1):
                table_lines.append(row)
                i += 1
            elif not row:
                # Allow one blank line within a table
                if i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
                    i += 1
                    continue
                break
            else:
                break

        if len(table_lines) < 2:
            continue

        # Separate header, separator, and data
        header_cells = [_clean_header(c.strip()) for c in table_lines[0].split("|") if c.strip() != ""]

        # Skip separator rows
        data_lines = []
        for tl in table_lines[1:]:
            stripped = tl.strip()
            if stripped.startswith("| ---") or stripped.startswith("|---"):
                continue
            if re.fullmatch(r"[\|\s\-:]+", stripped):
                continue
            data_lines.append(stripped)

        # Parse data rows
        data_rows: list[list[str]] = []
        for dl in data_lines:
            cells = [c.strip() for c in dl.split("|")]
            # Remove empty first/last from pipe split
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]
            if cells:
                data_rows.append(cells)

        if not data_rows:
            continue

        # Merge multi-row headers
        header_cells_padded = header_cells
        # Pad to match data row width
        max_cols = max((len(r) for r in data_rows), default=0)
        max_cols = max(max_cols, len(header_cells_padded))
        while len(header_cells_padded) < max_cols:
            header_cells_padded.append(f"col_{len(header_cells_padded)}")

        header_cells_padded, data_rows = _merge_multi_row_headers(
            header_cells_padded, data_rows
        )

        raw_text = "\n".join(table_lines)

        # Extract years from data
        years: set[int] = set()
        for h in header_cells_padded:
            for ym in re.finditer(r"\b(19\d{2}|20\d{2})\b", h):
                years.add(int(ym.group()))
        for row in data_rows:
            for cell in row:
                for ym in re.finditer(r"\b(19\d{2}|20\d{2})\b", cell):
                    years.add(int(ym.group()))

        period_basis = _detect_period_basis(title, raw_text)
        has_month_rows = _detect_has_month_rows(raw_text)

        tables.append({
            "file": fname,
            "line": table_start + 1,
            "title": title[:200],
            "units": units[:100],
            "headers": header_cells_padded,
            "data_rows": data_rows,
            "years": sorted(years),
            "pub_year": pub_year,
            "pub_month": pub_month,
            "period_basis": period_basis,
            "has_month_rows": has_month_rows,
            "raw": raw_text,
        })

    return tables


def _extract_html_tables_from_file(filepath: Path) -> list[dict[str, Any]]:
    """Extract HTML tables from a TXT file (rare, ~3 files)."""
    text = filepath.read_text(errors="replace")
    if "<table" not in text.lower():
        return []

    fname = filepath.name
    pub_year, pub_month = _pub_year_month(fname)
    html_tables = _extract_html_tables(text)
    results = []

    for ht in html_tables:
        if len(ht) < 2:
            continue

        header_cells = [str(c or "").strip() for c in ht[0]]
        data_rows = [[str(c or "").strip() for c in row] for row in ht[1:]]

        # Build raw text for analysis
        raw_lines = []
        for row in ht:
            raw_lines.append("| " + " | ".join(str(c or "") for c in row) + " |")
        raw_text = "\n".join(raw_lines)

        years: set[int] = set()
        for row in ht:
            for cell in row:
                for ym in re.finditer(r"\b(19\d{2}|20\d{2})\b", str(cell)):
                    years.add(int(ym.group()))

        period_basis = _detect_period_basis("", raw_text)
        has_month_rows = _detect_has_month_rows(raw_text)

        results.append({
            "file": fname,
            "line": 0,
            "title": "",
            "units": "",
            "headers": header_cells,
            "data_rows": data_rows,
            "years": sorted(years),
            "pub_year": pub_year,
            "pub_month": pub_month,
            "period_basis": period_basis,
            "has_month_rows": has_month_rows,
            "raw": raw_text,
        })

    return results


# ---------------------------------------------------------------------------
# DB Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS table_index (
    table_pk INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    title TEXT NOT NULL,
    title_norm TEXT,
    units TEXT,
    min_year INTEGER,
    max_year INTEGER,
    row_count INTEGER,
    col_count INTEGER,
    period_basis TEXT,
    has_month_rows INTEGER,
    content_hash TEXT,
    pub_year INTEGER,
    pub_month INTEGER,
    line_number INTEGER
);

CREATE TABLE IF NOT EXISTS table_cells (
    table_pk INTEGER NOT NULL,
    row_ordinal INTEGER NOT NULL,
    row_label TEXT,
    row_label_norm TEXT,
    column_label TEXT,
    column_label_norm TEXT,
    value_raw TEXT,
    normalized_value REAL,
    year INTEGER,
    month INTEGER,
    row_type TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    source_file TEXT PRIMARY KEY,
    bulletin_year INTEGER,
    bulletin_month INTEGER,
    table_count INTEGER
);

CREATE TABLE IF NOT EXISTS master_ledger (
    metric_slug TEXT,
    time_key TEXT,
    period_basis TEXT,
    value REAL,
    table_pk INTEGER,
    source_file TEXT,
    table_title TEXT
);
"""

_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_ti_source ON table_index(source_file);
CREATE INDEX IF NOT EXISTS idx_ti_title_norm ON table_index(title_norm);
CREATE INDEX IF NOT EXISTS idx_ti_hash ON table_index(content_hash);
CREATE INDEX IF NOT EXISTS idx_ti_years ON table_index(min_year, max_year);

CREATE INDEX IF NOT EXISTS idx_tc_pk ON table_cells(table_pk);
CREATE INDEX IF NOT EXISTS idx_tc_row_label ON table_cells(row_label_norm);
CREATE INDEX IF NOT EXISTS idx_tc_col_label ON table_cells(column_label_norm);
CREATE INDEX IF NOT EXISTS idx_tc_year ON table_cells(year);

CREATE INDEX IF NOT EXISTS idx_ml_slug ON master_ledger(metric_slug);
CREATE INDEX IF NOT EXISTS idx_ml_time ON master_ledger(time_key);
CREATE INDEX IF NOT EXISTS idx_ml_pk ON master_ledger(table_pk);
"""


# ---------------------------------------------------------------------------
# Classify row type
# ---------------------------------------------------------------------------

def _classify_row(label: str) -> str:
    low = label.lower().strip()
    if not low:
        return "empty"
    if low in _MONTH_NAME_TO_NUM:
        return "month"
    if re.fullmatch(r"(?:19|20)\d{2}", low):
        return "year"
    if "total" in low or "grand total" in low:
        return "total"
    if re.search(r"^(net|gross|subtotal|sub-total)", low):
        return "subtotal"
    return "data"


# ---------------------------------------------------------------------------
# Determine year/month for a cell
# ---------------------------------------------------------------------------

def _resolve_cell_year_month(
    row_label: str,
    col_label: str,
    active_year: int | None,
) -> tuple[int | None, int | None]:
    """Determine year and month for a cell from row/column context."""
    year = None
    month = None

    # Try column header first
    col_year, col_month = _parse_column_header_date(col_label)
    if col_year is not None:
        year = col_year
    if col_month is not None:
        month = col_month

    # Try row label
    row_year, row_month = _parse_month_from_row_label(row_label)
    if row_year is not None and year is None:
        year = row_year
    if row_month is not None and month is None:
        month = row_month

    # Check for year in row label
    if year is None:
        m = re.match(r"^((?:19|20)\d{2})\b", row_label.strip())
        if m:
            year = int(m.group(1))

    # Use active_year as fallback
    if year is None and active_year is not None:
        year = active_year

    return year, month


# ---------------------------------------------------------------------------
# Process one table into DB rows
# ---------------------------------------------------------------------------

def _process_table(
    table: dict[str, Any],
    table_pk: int,
) -> tuple[list[tuple], list[tuple]]:
    """Process a table dict into cell rows and master_ledger rows.

    Returns (cell_rows, ledger_rows).
    """
    headers = table["headers"]
    data_rows = table["data_rows"]
    title = table["title"]
    source_file = table["file"]
    period_basis = table["period_basis"]

    cell_rows: list[tuple] = []
    ledger_rows: list[tuple] = []
    active_year: int | None = None

    for row_idx, row in enumerate(data_rows):
        if not row:
            continue

        row_label = row[0] if row else ""
        row_type = _classify_row(row_label)

        # Update active year
        if re.fullmatch(r"(?:19|20)\d{2}", row_label.strip()):
            active_year = int(row_label.strip())
        else:
            m = re.match(r"^((?:19|20)\d{2})\b", row_label.strip())
            if m:
                active_year = int(m.group(1))

        for col_idx in range(1, len(row)):
            col_label = headers[col_idx] if col_idx < len(headers) else f"col_{col_idx}"
            value_raw = row[col_idx] if col_idx < len(row) else ""

            year, month = _resolve_cell_year_month(
                row_label, col_label, active_year
            )
            normalized_value = _parse_numeric(value_raw)

            cell_rows.append((
                table_pk,
                row_idx,
                row_label,
                _normalize_text(row_label),
                col_label,
                _normalize_text(col_label),
                value_raw,
                normalized_value,
                year,
                month,
                row_type,
            ))

            # Master ledger entry for numeric cells
            if normalized_value is not None and row_label.strip():
                metric = _slug(row_label)
                if month is not None and year is not None:
                    time_key = f"{year}-{month:02d}"
                elif year is not None:
                    time_key = str(year)
                else:
                    time_key = ""

                if metric and time_key:
                    ledger_rows.append((
                        metric,
                        time_key,
                        period_basis,
                        normalized_value,
                        table_pk,
                        source_file,
                        title[:200],
                    ))

    return cell_rows, ledger_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build SQLite DB from Treasury Bulletin TXT files.",
    )
    parser.add_argument(
        "--corpus",
        default=str(Path(__file__).resolve().parent.parent / "corpus"),
        help="Directory containing TXT files",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent.parent / "treasury_bulletins.sqlite3"),
        help="Output SQLite DB path",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Process only first N files (0=all)",
    )
    args = parser.parse_args()

    corpus = Path(args.corpus)
    output = Path(args.output)

    if not corpus.exists():
        print(f"ERROR: Corpus directory not found: {corpus}", file=sys.stderr)
        sys.exit(1)

    # Process files in REVERSE order (newest first) so dedup keeps newest
    files = sorted(corpus.glob("treasury_bulletin_*.txt"), reverse=True)
    if args.limit > 0:
        files = files[:args.limit]

    print(f"Scanning {len(files)} files (newest first for dedup)...", file=sys.stderr)

    # -----------------------------------------------------------------------
    # Pass 1: Extract and deduplicate tables
    # -----------------------------------------------------------------------
    t0 = time.time()
    seen_hashes: dict[str, dict[str, Any]] = {}
    total_raw = 0
    dupes = 0
    doc_table_counts: dict[str, int] = {}

    for fi, fpath in enumerate(files):
        tables = _extract_markdown_tables(fpath)
        # Also extract HTML tables (rare)
        tables.extend(_extract_html_tables_from_file(fpath))

        doc_table_counts[fpath.name] = len(tables)
        total_raw += len(tables)

        for table in tables:
            # Content hash for dedup
            normalized = re.sub(r"\s+", "", table["raw"].lower())
            content_hash = hashlib.md5(normalized.encode()).hexdigest()[:16]
            table["content_hash"] = content_hash

            if content_hash in seen_hashes:
                existing = seen_hashes[content_hash]
                if (table["pub_year"], table["pub_month"]) > (
                    existing["pub_year"], existing["pub_month"]
                ):
                    seen_hashes[content_hash] = table
                dupes += 1
            else:
                seen_hashes[content_hash] = table

        if (fi + 1) % 100 == 0:
            print(
                f"  Extracted {fi + 1}/{len(files)} files, "
                f"{total_raw} tables ({dupes} dupes)...",
                file=sys.stderr,
            )

    unique_tables = list(seen_hashes.values())
    t1 = time.time()
    print(
        f"Extraction done in {t1 - t0:.1f}s: {total_raw} raw tables, "
        f"{len(unique_tables)} unique ({dupes} duplicates removed)",
        file=sys.stderr,
    )

    # -----------------------------------------------------------------------
    # Pass 2: Build SQLite DB
    # -----------------------------------------------------------------------
    if output.exists():
        output.unlink()

    conn = sqlite3.connect(str(output))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
    conn.executescript(_SCHEMA_SQL)

    # Insert documents
    for fname, count in doc_table_counts.items():
        py, pm = _pub_year_month(fname)
        conn.execute(
            "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?)",
            (fname, py, pm, count),
        )
    conn.commit()

    # Insert tables and cells
    total_cells = 0
    total_ledger = 0

    for ti, table in enumerate(unique_tables):
        # Insert table_index
        years = table["years"]
        min_year = min(years) if years else None
        max_year = max(years) if years else None

        conn.execute(
            """INSERT INTO table_index
               (source_file, title, title_norm, units,
                min_year, max_year, row_count, col_count,
                period_basis, has_month_rows, content_hash,
                pub_year, pub_month, line_number)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                table["file"],
                table["title"],
                _normalize_text(table["title"]),
                table["units"],
                min_year,
                max_year,
                len(table["data_rows"]),
                len(table["headers"]),
                table["period_basis"],
                1 if table["has_month_rows"] else 0,
                table["content_hash"],
                table["pub_year"],
                table["pub_month"],
                table.get("line", 0),
            ),
        )
        table_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Process cells and ledger
        cell_rows, ledger_rows = _process_table(table, table_pk)

        if cell_rows:
            conn.executemany(
                """INSERT INTO table_cells
                   (table_pk, row_ordinal, row_label, row_label_norm,
                    column_label, column_label_norm, value_raw,
                    normalized_value, year, month, row_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                cell_rows,
            )
            total_cells += len(cell_rows)

        if ledger_rows:
            conn.executemany(
                """INSERT INTO master_ledger
                   (metric_slug, time_key, period_basis, value,
                    table_pk, source_file, table_title)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ledger_rows,
            )
            total_ledger += len(ledger_rows)

        if (ti + 1) % COMMIT_EVERY == 0:
            conn.commit()
            if (ti + 1) % 1000 == 0:
                print(
                    f"  Inserted {ti + 1}/{len(unique_tables)} tables, "
                    f"{total_cells} cells, {total_ledger} ledger rows...",
                    file=sys.stderr,
                )

    conn.commit()

    # Build indexes
    print("Building indexes...", file=sys.stderr)
    conn.executescript(_INDEX_SQL)
    conn.commit()

    # Build helper views
    conn.execute("DROP VIEW IF EXISTS table_first_tables")
    conn.execute("""
        CREATE VIEW table_first_tables AS
        SELECT
            table_pk, source_file, title AS table_title,
            title_norm AS table_title_norm, units AS units_line,
            period_basis, has_month_rows,
            row_count, col_count AS column_count,
            min_year, max_year, pub_year, pub_month
        FROM table_index
    """)

    # Column label lookup
    conn.execute("DROP TABLE IF EXISTS col_label_lookup")
    conn.execute("""
        CREATE TABLE col_label_lookup AS
        SELECT DISTINCT
            table_pk,
            column_label,
            column_label_norm,
            column_label_norm AS col_norm
        FROM table_cells
        WHERE column_label IS NOT NULL
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cll_pk ON col_label_lookup(table_pk)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cll_norm ON col_label_lookup(col_norm)")

    # Row label lookup
    conn.execute("DROP TABLE IF EXISTS row_label_lookup")
    conn.execute("""
        CREATE TABLE row_label_lookup AS
        SELECT DISTINCT
            table_pk,
            row_label,
            row_label_norm
        FROM table_cells
        WHERE row_label IS NOT NULL AND row_label != ''
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rll_pk ON row_label_lookup(table_pk)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rll_norm ON row_label_lookup(row_label_norm)")

    conn.commit()

    # VACUUM for compact file
    print("Vacuuming...", file=sys.stderr)
    conn.execute("VACUUM")
    conn.close()

    t2 = time.time()

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    db_size = output.stat().st_size
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Database built in {t2 - t0:.1f}s", file=sys.stderr)
    print(f"  Files processed:  {len(files)}", file=sys.stderr)
    print(f"  Raw tables:       {total_raw}", file=sys.stderr)
    print(f"  Unique tables:    {len(unique_tables)} ({dupes} dupes removed)", file=sys.stderr)
    print(f"  Total cells:      {total_cells:,}", file=sys.stderr)
    print(f"  Ledger entries:   {total_ledger:,}", file=sys.stderr)
    print(f"  Documents:        {len(doc_table_counts)}", file=sys.stderr)
    print(f"  DB size:          {db_size / 1024 / 1024:.1f} MB", file=sys.stderr)

    # -----------------------------------------------------------------------
    # Gzip compress
    # -----------------------------------------------------------------------
    gz_path = Path(str(output) + ".gz")
    print(f"\nCompressing to {gz_path.name}...", file=sys.stderr)
    with open(output, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)

    gz_size = gz_path.stat().st_size
    print(f"  Compressed size:  {gz_size / 1024 / 1024:.1f} MB", file=sys.stderr)
    print(f"  Compression ratio: {db_size / gz_size:.1f}x", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)


if __name__ == "__main__":
    main()
