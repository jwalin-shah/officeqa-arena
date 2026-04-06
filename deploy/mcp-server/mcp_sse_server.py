#!/usr/bin/env python3
"""Corpus-powered MCP SSE server for OfficeQA Arena.

Single self-contained file.  Parses all Treasury Bulletin TXT files at startup
into an in-memory index, then exposes search, extraction, and compute tools
via FastMCP over streamable-http.

Tools:
  - get_table          Find and return a full table as structured rows/columns
  - search_corpus      FTS5 keyword search with structured results
  - get_bulletin_index Manifest of bulletins and their tables
  - compute_expression Safe arithmetic evaluator
  - get_cpi_index      CPI-U lookup from bundled CSV
  - get_fiscal_year_bounds  Fiscal year date computation
  - get_exchange_rate  Historical FX rates (USD/GBP, USD/JPY, USD/CAD, etc.)

Usage:
    OFFICEQA_CORPUS_DIR=./corpus python3 mcp_sse_server.py
    python3 mcp_sse_server.py --corpus /app/corpus --port 8081
"""
from __future__ import annotations

import argparse
import ast
import bisect
import builtins
import csv
import difflib
import heapq
import json
import logging
import math
import os
import re
import sqlite3
import statistics
import time
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional high-performance dependencies (graceful fallback to stdlib)
# ---------------------------------------------------------------------------

try:
    from rapidfuzz import fuzz as rf_fuzz, process as rf_process
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False

try:
    import plotext as plt_text
    _HAS_PLOTEXT = True
except ImportError:
    _HAS_PLOTEXT = False

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("mcp_sse")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8081

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
# Temporal alias map — resolves historical name changes with bisect
# Each entry: (start_year, canonical_name, [aliases])
# Sorted by start_year for bisect lookup
# ---------------------------------------------------------------------------

_TEMPORAL_ALIASES: list[tuple[int, str, list[str]]] = [
    (1789, "war department", ["war dept", "department of war", "military"]),
    (1947, "department of defense", ["defense department", "dod", "national military establishment"]),
    (1949, "department of defense", ["war department", "war dept", "department of war"]),
    (1789, "treasury department", ["dept of treasury", "treasury dept"]),
    (1789, "national defense", ["military expenditures", "defense expenditures", "war expenditures"]),
    (1935, "social security", ["old-age benefits", "old age and survivors insurance", "oasi"]),
    (1965, "social security", ["social security and medicare", "oasdi"]),
    (1789, "public debt", ["national debt", "government debt", "federal debt", "gross debt"]),
    (1789, "internal revenue", ["tax receipts", "tax revenue", "income tax"]),
    (1913, "income tax", ["income and profits taxes", "individual income taxes"]),
    (1789, "customs", ["customs duties", "tariff", "import duties"]),
]

# Pre-sort by start_year and build lookup structures
_ALIAS_YEARS = [a[0] for a in _TEMPORAL_ALIASES]


def _expand_temporal_aliases(term: str, doc_year: int = 0) -> list[str]:
    """Expand a search term using temporal aliases. Returns additional terms to search."""
    term_lower = term.lower().strip()
    expansions: list[str] = []
    for start_yr, canonical, aliases in _TEMPORAL_ALIASES:
        if doc_year and doc_year < start_yr:
            continue
        all_names = [canonical] + aliases
        if any(term_lower in name or name in term_lower for name in all_names):
            for name in all_names:
                if name != term_lower:
                    expansions.append(name)
    return expansions


# ---------------------------------------------------------------------------
# Hierarchy / subtotal detection
# ---------------------------------------------------------------------------


def _detect_row_level(label: str) -> int:
    """Detect indentation level of a row label. 0=top, 1=indented, 2=deeply indented.

    Treasury tables use leading spaces/dots for hierarchy.
    """
    if not label:
        return 0
    # Count leading whitespace
    stripped = label.lstrip()
    indent = len(label) - len(stripped)
    # Also check for leading dots/dashes (common in Treasury)
    dot_indent = len(label) - len(label.lstrip(".").lstrip())
    level = max(indent // 2, dot_indent // 4)
    return min(level, 3)


def _is_subtotal_row(label: str) -> bool:
    """Check if a row label is likely a subtotal/total row."""
    l = label.strip().lower().rstrip(".")
    return bool(re.match(
        r"^(total|subtotal|grand total|net total|gross total|"
        r"total.*expenditures|total.*receipts|total.*assets|"
        r"total.*liabilities|aggregate|sum)",
        l
    ))


# ---------------------------------------------------------------------------
# Precise numeric parsing with Decimal
# ---------------------------------------------------------------------------


def _parse_treasury_number(s: str) -> tuple[float | None, str]:
    """Parse a Treasury Bulletin number. Returns (value, status).

    Handles: parenthetical negatives, footnote markers, dashes, asterisks.
    status: 'ok', 'null', 'zero', 'error'
    """
    if not s or not isinstance(s, str):
        return None, "null"
    s = s.strip()
    if s.lower() in ("nan", "-", "...", "*", "—", "–", ""):
        return None, "null"
    if s == "0" or s == "0.0":
        return 0.0, "zero"

    # Strip footnote markers (e.g., "123 1/" or "123 2/")
    cleaned = re.sub(r"\s+\d+/\s*$", "", s)
    # Strip commas, dollar signs, percent signs
    cleaned = cleaned.replace(",", "").replace("$", "").replace("%", "")
    # Handle parenthetical negatives: (123) -> -123
    m = re.match(r"^\(([0-9.]+)\)$", cleaned)
    if m:
        cleaned = "-" + m.group(1)
    cleaned = cleaned.strip()
    if not cleaned:
        return None, "null"
    try:
        val = float(Decimal(cleaned))
        return val, "ok"
    except (InvalidOperation, ValueError):
        return None, "error"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: Corpus parsing helpers
# ═══════════════════════════════════════════════════════════════════════════


def _normalize_text(s: str) -> str:
    """Normalize text for search: NFKC, lowercase, strip punctuation."""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    s = re.sub(r"[–—−‐]", "-", s)
    s = re.sub(r"[^\w\s%\-.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _pub_year_month(fname: str) -> tuple[int, int]:
    """Extract (year, month) from treasury_bulletin_YYYY_MM.txt filename."""
    m = re.search(r"(\d{4})_(\d{2})", fname)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def _clean_header(h: str) -> str:
    """Clean a header cell, stripping Unnamed prefixes from multi-level headers.

    For 'Budget receipts > Net receipts 2/' returns 'Net receipts 2/'.
    For 'Unnamed: 0_level_0 > Unnamed: 0_level_1' walks backward for a real label.
    """
    parts = [p.strip() for p in h.split(">")]
    for p in reversed(parts):
        if "unnamed" not in p.lower() and p.strip():
            return p.strip()
    return h.strip()


def _detect_units(text: str) -> str:
    """Detect unit scale from table text."""
    t = text.lower()
    if "in millions" in t or "(millions)" in t:
        return "millions"
    if "in thousands" in t or "(thousands)" in t:
        return "thousands"
    if "in billions" in t or "(billions)" in t:
        return "billions"
    if "percent" in t or "%" in t:
        return "percent"
    return ""


def _detect_period_basis(title: str, raw_text: str) -> str:
    """Detect fiscal vs calendar vs monthly from title and raw text."""
    combined = (title + " " + raw_text[:500]).lower()
    has_fiscal = bool(re.search(r"fiscal\s+year", combined))
    has_calendar = bool(re.search(r"calendar\s+year", combined))

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


def _merge_multi_row_headers(
    header_row: list[str], data_rows: list[list[str]]
) -> tuple[list[str], list[list[str]]]:
    """If the second row looks like a sub-header, merge it into the header."""
    if not data_rows:
        return header_row, data_rows

    second_row = data_rows[0]
    if len(second_row) != len(header_row):
        return header_row, data_rows

    data_cells = header_row[1:] if len(header_row) > 1 else header_row
    empty_count = sum(
        1 for c in data_cells
        if not c or c.startswith("col_") or "unnamed" in c.lower()
    )
    if len(data_cells) == 0:
        return header_row, data_rows
    empty_ratio = empty_count / len(data_cells)

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

    # Year+month pattern
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


def _extract_markdown_tables(filepath: Path) -> list[dict]:
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
        units_line = ""
        for j in range(max(0, i - 10), i):
            ctx = lines[j].strip()
            if re.search(r"\(.*(?:millions|thousands|dollars|percent|billions).*\)", ctx, re.I):
                units_line = ctx
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

        # Parse header
        header_raw = [c.strip() for c in table_lines[0].split("|") if c.strip() != ""]
        header_cells = [_clean_header(c) for c in header_raw]

        # Skip separator rows, parse data
        data_lines = []
        for tl in table_lines[1:]:
            stripped = tl.strip()
            if stripped.startswith("| ---") or stripped.startswith("|---"):
                continue
            if re.fullmatch(r"[\|\s\-:]+", stripped):
                continue
            data_lines.append(stripped)

        data_rows: list[list[str]] = []
        for dl in data_lines:
            cells = [c.strip() for c in dl.split("|")]
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]
            if cells:
                data_rows.append(cells)

        if not data_rows:
            continue

        # Pad headers to match data width
        max_cols = max((len(r) for r in data_rows), default=0)
        max_cols = max(max_cols, len(header_cells))
        while len(header_cells) < max_cols:
            header_cells.append(f"col_{len(header_cells)}")
        while len(header_raw) < max_cols:
            header_raw.append(f"col_{len(header_raw)}")

        # Merge multi-row headers
        header_cells, data_rows = _merge_multi_row_headers(header_cells, data_rows)

        raw_text = "\n".join(table_lines)

        # Extract years mentioned in data
        years: set[int] = set()
        for h in header_cells:
            for ym in re.finditer(r"\b(19\d{2}|20\d{2})\b", h):
                years.add(int(ym.group()))
        for row in data_rows:
            for cell in row:
                for ym in re.finditer(r"\b(19\d{2}|20\d{2})\b", cell):
                    years.add(int(ym.group()))

        period_basis = _detect_period_basis(title, raw_text)
        units = _detect_units(units_line or title)

        tables.append({
            "file": fname,
            "file_id": f"{pub_year}_{pub_month:02d}" if pub_year else fname,
            "pub_year": pub_year,
            "pub_month": pub_month,
            "line": table_start + 1,
            "title": title[:300],
            "units_line": units_line[:200],
            "units": units,
            "headers_raw": header_raw,
            "headers": header_cells,
            "data_rows": data_rows,
            "years": sorted(years),
            "period_basis": period_basis,
        })

    return tables


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: Corpus Index (in-memory, built at startup)
# ═══════════════════════════════════════════════════════════════════════════


class CorpusIndex:
    """In-memory index of all parsed tables, with FTS5 search."""

    def __init__(self, corpus_dir: str) -> None:
        self.corpus_dir = corpus_dir
        self.tables: list[dict] = []
        self.by_file: dict[str, list[int]] = defaultdict(list)
        self._fts_conn: sqlite3.Connection | None = None
        self._vocab: list[str] = []

        t0 = time.time()
        self._parse_all()
        t1 = time.time()
        logger.info("Parsed %d tables from %d bulletins in %.1fs",
                     len(self.tables), len(self.by_file), t1 - t0)

        self._build_fts_index()
        t2 = time.time()
        logger.info("FTS5 index built in %.1fs (%d vocabulary words)",
                     t2 - t1, len(self._vocab))

    def _parse_all(self) -> None:
        """Parse all TXT files in corpus_dir."""
        cdir = Path(self.corpus_dir)
        files = sorted(cdir.glob("treasury_bulletin_*.txt"))
        if not files:
            logger.warning("No treasury_bulletin_*.txt files found in %s", cdir)
            return

        for fpath in files:
            file_tables = _extract_markdown_tables(fpath)
            for idx, tbl in enumerate(file_tables):
                tbl["table_idx"] = idx
                global_idx = len(self.tables)
                tbl["global_idx"] = global_idx
                self.tables.append(tbl)
                self.by_file[tbl["file_id"]].append(global_idx)

    def _build_fts_index(self) -> None:
        """Build in-memory FTS5 index for keyword search."""
        self._fts_conn = sqlite3.connect(":memory:")
        try:
            self._fts_conn.execute(
                'CREATE VIRTUAL TABLE fts USING fts5('
                'text, global_idx, row_idx, label_type, '
                'tokenize="porter unicode61")'
            )
        except Exception:
            logger.warning("FTS5 not available, search will be limited")
            self._fts_conn = None
            return

        rows_to_insert = []
        label_set: set[str] = set()

        for tbl in self.tables:
            gi = tbl["global_idx"]
            # Index title
            if tbl["title"]:
                norm = _normalize_text(tbl["title"])
                rows_to_insert.append((norm, str(gi), "-1", "title"))
                label_set.add(norm)
            # Index column headers
            for h in tbl["headers"]:
                if h and len(h) > 1 and not h.startswith("col_"):
                    norm = _normalize_text(h)
                    rows_to_insert.append((norm, str(gi), "-1", "header"))
                    label_set.add(norm)
            # Index row labels (first cell of each data row)
            for ri, row in enumerate(tbl["data_rows"]):
                if row and row[0] and len(str(row[0])) > 1:
                    norm = _normalize_text(str(row[0]))
                    rows_to_insert.append((norm, str(gi), str(ri), "row"))
                    label_set.add(norm)

        self._fts_conn.executemany("INSERT INTO fts VALUES (?, ?, ?, ?)", rows_to_insert)
        self._fts_conn.commit()

        # Build word vocabulary for difflib fuzzy expansion
        word_set: set[str] = set()
        for label in label_set:
            for w in re.findall(r'[a-z]+', label):
                if len(w) > 2:
                    word_set.add(w)
        self._vocab = list(word_set)

    def _sanitize_fts_token(self, token: str) -> str:
        """Sanitize a token for safe FTS5 MATCH query insertion.

        Strips punctuation that breaks FTS5 syntax (dots, slashes, etc).
        This is critical — difflib can return 'natl.' which is invalid in MATCH.
        """
        # Keep only alphanumeric chars
        clean = re.sub(r'[^a-z0-9]', '', token.lower())
        return clean

    def fts_search(self, query: str, limit: int = 30, doc_year: int = 0) -> list[tuple[int, int, float, str, str]]:
        """Search FTS5 index with sanitized difflib expansion and temporal aliases.

        Returns [(global_idx, row_idx, rank, text, label_type)].
        Uses heapq for strict top-k pruning instead of unbounded sorting.
        """
        if not self._fts_conn:
            return []

        query_norm = _normalize_text(query)
        terms: set[str] = set()
        for word in re.findall(r'[a-z0-9]+', query_norm):
            if len(word) > 1:
                terms.add(word)

        # Temporal alias expansion
        alias_terms = _expand_temporal_aliases(query, doc_year)
        for alias in alias_terms:
            for w in re.findall(r'[a-z]+', _normalize_text(alias)):
                if len(w) > 2:
                    terms.add(w)

        # Fuzzy expand — use RapidFuzz if available (10-100x faster, better scoring)
        # then SANITIZE before FTS5 to prevent syntax errors
        if _HAS_RAPIDFUZZ:
            for word in list(terms):
                # token_set_ratio handles word order differences
                results = rf_process.extract(
                    word, self._vocab, scorer=rf_fuzz.WRatio,
                    score_cutoff=55, limit=3
                )
                for match_str, score, _ in results:
                    clean = self._sanitize_fts_token(match_str)
                    if len(clean) > 2:
                        terms.add(clean)
        else:
            for word in list(terms):
                matches = difflib.get_close_matches(word, self._vocab, n=3, cutoff=0.55)
                for m in matches:
                    for w in re.findall(r'[a-z]+', m.lower()):
                        clean = self._sanitize_fts_token(w)
                        if len(clean) > 2:
                            terms.add(clean)

        if not terms:
            return []

        # Build FTS5 query with sanitized tokens
        safe_terms = [self._sanitize_fts_token(t) for t in terms]
        safe_terms = [t for t in safe_terms if len(t) > 1]
        if not safe_terms:
            return []

        fts_query = " OR ".join(f'"{t}"' for t in safe_terms)
        try:
            rows = self._fts_conn.execute(
                "SELECT text, global_idx, row_idx, rank, label_type FROM fts "
                "WHERE fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, limit * 3),  # over-fetch for heapq pruning
            ).fetchall()

            # Use heapq.nsmallest for strict top-k (rank is negative, more negative = better)
            all_hits = [(r[3], int(r[1]), int(r[2]), r[0], r[4]) for r in rows]
            top_k = heapq.nsmallest(limit, all_hits, key=lambda x: x[0])
            return [(h[1], h[2], h[0], h[3], h[4]) for h in top_k]
        except Exception:
            return []

    def _normalize_file_id(self, bulletin: str) -> str:
        """Normalize bulletin input to a file_id like '1950_06'."""
        s = bulletin.strip()
        s = s.replace("treasury_bulletin_", "").replace(".txt", "")
        return s

    def _score_table_match(self, tbl: dict, keyword: str) -> float:
        """Score how well a table matches a keyword. Higher = better.

        Uses RapidFuzz WRatio when available (handles partial matches,
        token reordering, and abbreviations much better than difflib).
        """
        kw_lower = keyword.lower()
        title_lower = (tbl.get("title") or "").lower()

        score = 0.0
        # Exact substring in title
        if kw_lower in title_lower:
            score += 10.0
        # Word overlap
        kw_words = set(re.findall(r'[a-z]+', kw_lower))
        title_words = set(re.findall(r'[a-z]+', title_lower))
        if kw_words and title_words:
            overlap = len(kw_words & title_words) / len(kw_words)
            score += overlap * 5.0
        # Fuzzy ratio — RapidFuzz WRatio is much better at partial + token-reordered matches
        if _HAS_RAPIDFUZZ:
            score += rf_fuzz.WRatio(kw_lower, title_lower) / 100.0 * 5.0
        else:
            score += difflib.SequenceMatcher(None, kw_lower, title_lower).ratio() * 3.0
        # Header overlap
        for h in tbl.get("headers", []):
            if kw_lower in h.lower():
                score += 2.0
                break
        return score

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def get_table(self, bulletin: str, keyword: str, row_filter: str = "") -> dict:
        """Find and return a full table as structured rows/columns."""
        file_id = self._normalize_file_id(bulletin)
        indices = self.by_file.get(file_id, [])

        if not indices:
            # Try fuzzy file_id match
            candidates = [fid for fid in self.by_file if file_id in fid]
            if candidates:
                file_id = candidates[0]
                indices = self.by_file[file_id]

        if not indices:
            return {
                "ok": False,
                "error": f"No bulletin found for '{bulletin}'",
                "available_sample": sorted(self.by_file.keys())[:20],
                "action_hint": "Check file_id format: use YYYY_MM (e.g. '1950_06').",
            }

        # Score tables with heapq — strict top-1 pick
        scored = []
        for gi in indices:
            tbl = self.tables[gi]
            score = self._score_table_match(tbl, keyword)
            scored.append((score, gi))
        best_gi = heapq.nlargest(1, scored, key=lambda x: x[0])[0][1]
        tbl = self.tables[best_gi]

        # Determine scale factor from units
        scale_factor = 1
        units = tbl.get("units", "")
        if units == "millions":
            scale_factor = 1_000_000
        elif units == "thousands":
            scale_factor = 1_000
        elif units == "billions":
            scale_factor = 1_000_000_000

        # Build structured rows with hierarchy and parsed numbers
        headers = tbl["headers"]
        rows_out = []
        section_headers = []

        for data_row in tbl["data_rows"]:
            padded = data_row + [""] * (len(headers) - len(data_row))
            label = padded[0] if padded else ""

            # Detect section-header rows (all non-label cells are nan/empty)
            non_label = padded[1:]
            if all(c.strip().lower() in ("nan", "-", "", "...", "*") for c in non_label):
                if label.strip() and label.strip().lower() != "nan":
                    section_headers.append(label.strip())
                continue

            # Apply row_filter
            if row_filter and row_filter.lower() not in label.lower():
                continue

            row_dict: dict = {"label": label}
            # Hierarchy detection
            level = _detect_row_level(label)
            if level > 0:
                row_dict["_indent"] = level
            if _is_subtotal_row(label):
                row_dict["_is_total"] = True

            for ci in range(1, len(headers)):
                col_name = headers[ci]
                val_raw = padded[ci] if ci < len(padded) else ""
                row_dict[col_name] = val_raw
            rows_out.append(row_dict)

        # Build columns list (skip first which is the label column)
        columns = [h for h in headers[1:] if not h.startswith("col_")]
        columns_raw = [h for h in tbl["headers_raw"][1:]] if len(tbl["headers_raw"]) > 1 else columns

        # Also list other tables in this bulletin for context
        other_tables = []
        for gi2 in indices:
            if gi2 != best_gi:
                t2 = self.tables[gi2]
                other_tables.append({
                    "table_idx": t2["table_idx"],
                    "title": t2["title"][:100],
                    "row_count": len(t2["data_rows"]),
                })

        result: dict = {
            "ok": True,
            "file_id": file_id,
            "table_title": tbl["title"],
            "units": tbl["units"],
            "units_line": tbl["units_line"],
            "scale_factor": scale_factor,
            "period_basis": tbl["period_basis"],
            "columns": columns,
            "columns_raw": columns_raw[:len(columns)],
            "row_count": len(rows_out),
            "rows": rows_out,
        }
        if section_headers:
            result["section_headers"] = section_headers
        if other_tables:
            result["other_tables_in_bulletin"] = other_tables[:5]

        # Action hint with scale factor warning
        if tbl["units"] and scale_factor > 1:
            result["action_hint"] = (
                f"WARNING: Values are in {tbl['units']} (multiply by {scale_factor:,} for actual dollars). "
                "Use compute_expression() for math."
            )
        else:
            result["action_hint"] = "Use compute_expression() for any math needed."

        return result

    def search_corpus(self, query: str, bulletin: str = "", limit: int = 20) -> dict:
        """FTS5 search with structured results."""
        hits = self.fts_search(query, limit=limit * 3)  # over-fetch for dedup

        if bulletin:
            file_id = self._normalize_file_id(bulletin)
            hits = [h for h in hits if self.tables[h[0]].get("file_id", "") == file_id]

        # Deduplicate by global_idx (keep best rank per table)
        seen: dict[int, tuple] = {}
        for gi, ri, rank, text, label_type in hits:
            if gi not in seen or rank < seen[gi][2]:
                seen[gi] = (gi, ri, rank, text, label_type)

        sorted_hits = sorted(seen.values(), key=lambda x: x[2])[:limit]

        matches = []
        for gi, ri, rank, text, label_type in sorted_hits:
            tbl = self.tables[gi]
            # Get sample rows (first 5 data rows)
            sample_rows = []
            headers = tbl["headers"]
            for dr in tbl["data_rows"][:5]:
                padded = dr + [""] * (len(headers) - len(dr))
                row_dict = {"label": padded[0]}
                for ci in range(1, min(len(headers), len(padded))):
                    row_dict[headers[ci]] = padded[ci]
                sample_rows.append(row_dict)

            matches.append({
                "file_id": tbl["file_id"],
                "table_idx": tbl["table_idx"],
                "table_title": tbl["title"],
                "units": tbl["units"],
                "period_basis": tbl["period_basis"],
                "match_type": label_type,
                "matched_text": text,
                "columns": [h for h in headers[1:] if not h.startswith("col_")][:10],
                "sample_rows": sample_rows,
                "total_rows": len(tbl["data_rows"]),
                "years": tbl["years"][:10] if tbl["years"] else [],
            })

        return {
            "matches": matches,
            "total_matches": len(seen),
            "shown": len(matches),
            "action_hint": (
                "Use get_table(bulletin='FILE_ID', keyword='TITLE') to fetch full table data."
                if matches else
                "No matches found. Try broader keywords or different terms."
            ),
        }

    def get_bulletin_index(self, bulletin: str = "") -> dict:
        """Return manifest of bulletins and their tables."""
        if bulletin:
            file_id = self._normalize_file_id(bulletin)
            indices = self.by_file.get(file_id, [])
            if not indices:
                return {
                    "ok": False,
                    "error": f"No bulletin '{file_id}' found",
                    "available_sample": sorted(self.by_file.keys())[:20],
                }
            tables_info = []
            for gi in indices:
                tbl = self.tables[gi]
                tables_info.append({
                    "table_idx": tbl["table_idx"],
                    "title": tbl["title"],
                    "units": tbl["units"],
                    "row_count": len(tbl["data_rows"]),
                    "col_count": len(tbl["headers"]),
                    "period_basis": tbl["period_basis"],
                    "years": tbl["years"][:10] if tbl["years"] else [],
                })
            return {
                "ok": True,
                "file_id": file_id,
                "table_count": len(tables_info),
                "tables": tables_info,
                "action_hint": "Use get_table(bulletin='...', keyword='TITLE') to fetch any table.",
            }

        # Summary of all bulletins
        bulletins = []
        for file_id in sorted(self.by_file.keys()):
            indices = self.by_file[file_id]
            all_years: set[int] = set()
            for gi in indices:
                all_years.update(self.tables[gi].get("years", []))
            pub_year, pub_month = _pub_year_month(file_id)
            bulletins.append({
                "file_id": file_id,
                "pub_year": pub_year,
                "pub_month": pub_month,
                "table_count": len(indices),
                "year_range": [min(all_years), max(all_years)] if all_years else [],
            })

        all_years_global: set[int] = set()
        for tbl in self.tables:
            all_years_global.update(tbl.get("years", []))

        return {
            "ok": True,
            "bulletin_count": len(bulletins),
            "total_tables": len(self.tables),
            "year_range": [min(all_years_global), max(all_years_global)] if all_years_global else [],
            "bulletins": bulletins,
            "action_hint": "Use get_bulletin_index(bulletin='YYYY_MM') for table details, or search_corpus(query='...') to find data.",
        }

    def find_values(self, query: str, year: str = "", month: str = "") -> dict:
        """One-shot search: find specific values across all tables.

        More targeted than search_corpus — uses year/month to pick the right
        column and returns individual cell values with provenance.
        """
        if not query or not query.strip():
            return {"status": "error", "msg": "query cannot be empty"}
        year_str = str(year).strip() if year else ""
        month_str = month.strip().lower() if month else ""

        # FTS search
        search_query = query
        if year_str:
            search_query += " " + year_str
        if month_str:
            search_query += " " + month_str

        fts_hits = self.fts_search(search_query, limit=30)

        # Score tables and rows
        table_scores: dict[int, float] = {}
        row_hits: dict[tuple[int, int], float] = {}

        for tbl_idx, row_idx, rank, text, label_type in fts_hits:
            score = -rank
            table_scores[tbl_idx] = table_scores.get(tbl_idx, 0) + score
            if row_idx >= 0:
                key = (tbl_idx, row_idx)
                row_hits[key] = row_hits.get(key, 0) + score
            else:
                # Title/header match — include all rows
                if tbl_idx < len(self.tables):
                    for ri in range(len(self.tables[tbl_idx]["data_rows"])):
                        key = (tbl_idx, ri)
                        row_hits[key] = row_hits.get(key, 0) + score * 0.5

        # Also do direct keyword matching
        query_lower = query.lower()
        terms = query_lower.split()
        for tbl in self.tables:
            gi = tbl["global_idx"]
            title_lower = tbl["title"].lower()
            header_lower = " ".join(tbl["headers"]).lower()
            kw_score = 0
            for term in terms:
                if term in title_lower:
                    kw_score += 3
                elif term in header_lower:
                    kw_score += 2
            if kw_score > 0:
                table_scores[gi] = table_scores.get(gi, 0) + kw_score
                for ri, row in enumerate(tbl["data_rows"]):
                    if row and any(term in str(row[0]).lower() for term in terms):
                        key = (gi, ri)
                        row_hits[key] = row_hits.get(key, 0) + 2

        # Extract values from top-scoring rows
        scored_results = []
        for (tbl_idx, row_idx), row_score in sorted(row_hits.items(), key=lambda x: -x[1]):
            if tbl_idx >= len(self.tables):
                continue
            tbl = self.tables[tbl_idx]
            if row_idx >= len(tbl["data_rows"]):
                continue
            row = tbl["data_rows"][row_idx]
            combined_score = table_scores.get(tbl_idx, 0) + row_score
            headers = tbl["headers"]

            # Find target column by year or month
            col_idx = -1
            if year_str:
                for ci, h in enumerate(headers):
                    if year_str in h:
                        col_idx = ci
                        break
            if month_str and col_idx < 0:
                for ci, h in enumerate(headers):
                    if month_str in h.lower():
                        col_idx = ci
                        break

            if col_idx >= 0 and col_idx < len(row):
                val_raw = str(row[col_idx])
                scored_results.append({
                    "value": val_raw,
                    "numeric": _clean_numeric(val_raw),
                    "row_label": row[0] if row else "",
                    "column": headers[col_idx] if col_idx < len(headers) else "",
                    "file_id": tbl["file_id"],
                    "title": tbl["title"][:120],
                    "units": tbl["units"],
                    "period_basis": tbl["period_basis"],
                    "score": round(combined_score, 2),
                })
            else:
                # Return full row mapped to headers
                row_data = {}
                for ci, h in enumerate(headers):
                    if ci < len(row):
                        row_data[h] = row[ci]
                scored_results.append({
                    "value": row_data,
                    "row_label": row[0] if row else "",
                    "file_id": tbl["file_id"],
                    "title": tbl["title"][:120],
                    "units": tbl["units"],
                    "period_basis": tbl["period_basis"],
                    "columns": headers,
                    "score": round(combined_score, 2),
                })

        scored_results.sort(key=lambda x: x["score"], reverse=True)
        top = scored_results[:5]

        return {
            "status": "ok" if top else "no_results",
            "count": len(scored_results),
            "results": top,
            "action_hint": (
                "Use compute_expression() for any math on these values."
                if top else
                "No results. Try broader terms or use search_corpus() first."
            ),
        }


def _clean_numeric(s: str) -> float | None:
    """Try to parse a string as a number. Returns None if not numeric."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip().replace(",", "").replace("$", "").replace("%", "")
    # Handle parenthetical negatives: (123) -> -123
    m = re.match(r"^\(([0-9.]+)\)$", s)
    if m:
        s = "-" + m.group(1)
    # Handle footnote markers: 123 1/ -> 123
    s = re.sub(r"\s+\d+/\s*$", "", s)
    s = s.strip()
    if not s or s.lower() in ("nan", "-", "...", "*"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def verify_answer_impl(answer: str, question_type: str = "") -> dict:
    """Sanity-check an answer before submitting."""
    warnings = []
    clean = str(answer).strip().replace(",", "").replace("$", "").replace("%", "")

    try:
        val = float(clean)
    except ValueError:
        return {"status": "warn", "warnings": ["Answer is not numeric"], "answer": answer}

    if math.isnan(val) or math.isinf(val):
        warnings.append("Answer is NaN or Inf")

    qtype = (question_type or "").lower()
    if qtype == "percentage":
        if abs(val) > 10000:
            warnings.append(f"Percentage {val}% seems too large")
        if abs(val) < 0.0001 and val != 0:
            warnings.append(f"Percentage {val}% seems too small")
    if qtype in ("dollar_amount", "amount"):
        if val < 0:
            warnings.append("Negative dollar amount — verify sign")

    if val == int(val) and abs(val) < 1e15:
        formatted = str(int(val))
    else:
        formatted = f"{val:.2f}"

    return {
        "status": "ok" if not warnings else "warn",
        "answer": formatted,
        "numeric": val,
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: Safe arithmetic evaluator
# ═══════════════════════════════════════════════════════════════════════════


def safe_eval_finance(expression: str, variables: dict[str, float] | None = None) -> float | list[float]:
    """Safe AST-based arithmetic evaluator with financial functions."""
    variables = variables or {}

    def _eval_list(node: ast.AST) -> list[float]:
        if isinstance(node, ast.List):
            return [_eval(elt) for elt in node.elts]
        return [_eval(node)]

    def _collect_args(args: list[ast.AST]) -> list[float]:
        result: list[float] = []
        for a in args:
            if isinstance(a, ast.List):
                result.extend(_eval(elt) for elt in a.elts)
            else:
                result.append(_eval(a))
        return result

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return float(node.value)
            raise ValueError("only_numeric_constants_allowed")
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"unknown_variable:{node.id}")
            return float(variables[node.id])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -_eval(node.operand)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
            return _eval(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = _eval(node.left), _eval(node.right)
            op = node.op
            if isinstance(op, ast.Add): return left + right
            if isinstance(op, ast.Sub): return left - right
            if isinstance(op, ast.Mult): return left * right
            if isinstance(op, ast.Div):
                if right == 0: raise ValueError("division_by_zero")
                return left / right
            if isinstance(op, ast.Pow): return left ** right
            if isinstance(op, ast.Mod): return left % right
            if isinstance(op, ast.BitXor): return left ** right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn == "abs":
                return float(builtins.abs(*[_eval(a) for a in node.args]))
            if fn == "round":
                args = [_eval(a) for a in node.args]
                return float(builtins.round(args[0], int(args[1])) if len(args) == 2 else builtins.round(args[0]))
            if fn in ("min", "max"):
                vals = _collect_args(node.args)
                return float(min(vals) if fn == "min" else max(vals))
            if fn == "sqrt" and len(node.args) == 1:
                return math.sqrt(_eval(node.args[0]))
            if fn == "log":
                args = [_eval(a) for a in node.args]
                return math.log(*args)
            if fn == "ln" and len(node.args) == 1:
                return math.log(_eval(node.args[0]))
            if fn == "exp" and len(node.args) == 1:
                return math.exp(_eval(node.args[0]))
            if fn == "sum":
                return float(math.fsum(_collect_args(node.args)))
            if fn == "fsum":
                return float(math.fsum(_collect_args(node.args)))
            if fn == "isclose" and len(node.args) >= 2:
                args = [_eval(a) for a in node.args]
                rtol = args[2] if len(args) > 2 else 1e-9
                return 1.0 if math.isclose(args[0], args[1], rel_tol=rtol) else 0.0
            if fn == "pow" and len(node.args) == 2:
                return _eval(node.args[0]) ** _eval(node.args[1])
            if fn == "prod":
                return float(math.prod(_collect_args(node.args)))
            if fn == "geometric_mean":
                vals = _collect_args(node.args)
                return float(math.prod(vals) ** (1.0 / len(vals)))
            if fn == "mean":
                vals = _collect_args(node.args)
                return float(math.fsum(vals) / len(vals))
            if fn == "stdev":
                vals = _collect_args(node.args)
                if len(vals) < 2: raise ValueError("stdev requires at least 2 values")
                return float(statistics.stdev(vals))
            if fn == "len":
                return float(len(_collect_args(node.args)))
            if fn == "linreg" and len(node.args) == 2:
                x_vals = _eval_list(node.args[0])
                y_vals = _eval_list(node.args[1])
                n = len(x_vals)
                if n != len(y_vals) or n < 2:
                    raise ValueError("linreg requires two equal-length lists of 2+ values")
                x_mean = sum(x_vals) / n
                y_mean = sum(y_vals) / n
                num = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
                den = sum((x - x_mean) ** 2 for x in x_vals)
                if den == 0: raise ValueError("linreg: all x values are identical")
                slope = num / den
                intercept = y_mean - slope * x_mean
                return [float(slope), float(intercept)]
            if fn == "cagr" and len(node.args) == 3:
                args = [_eval(a) for a in node.args]
                return ((args[1] / args[0]) ** (1.0 / args[2]) - 1) * 100
            if fn == "median":
                vals = sorted(_collect_args(node.args))
                n = len(vals)
                if n == 0: raise ValueError("median requires at least 1 value")
                mid = n // 2
                return float(vals[mid]) if n % 2 else float((vals[mid - 1] + vals[mid]) / 2)
            if fn == "variance":
                vals = _collect_args(node.args)
                if len(vals) < 2: raise ValueError("variance requires at least 2 values")
                m = sum(vals) / len(vals)
                return float(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
            if fn == "theil":
                vals = _collect_args(node.args)
                if len(vals) < 2: raise ValueError("theil requires at least 2 values")
                if any(v <= 0 for v in vals): raise ValueError("theil requires all positive values")
                m = sum(vals) / len(vals)
                return float(sum((v / m) * math.log(v / m) for v in vals) / len(vals))
            if fn == "theil_l":
                vals = _collect_args(node.args)
                if len(vals) < 2: raise ValueError("theil_l requires at least 2 values")
                if any(v <= 0 for v in vals): raise ValueError("theil_l requires all positive values")
                m = sum(vals) / len(vals)
                return float(sum(math.log(m / v) for v in vals) / len(vals))
            if fn == "gini":
                vals = sorted(_collect_args(node.args))
                n = len(vals)
                if n < 2: raise ValueError("gini requires at least 2 values")
                s = sum(vals)
                if s == 0: raise ValueError("gini: sum of values is zero")
                return float(sum((2 * (i + 1) - n - 1) * vals[i] for i in range(n)) / (n * s))
            if fn in ("pct_change", "pct_diff"):
                args = [_eval(a) for a in node.args]
                if len(args) != 2: raise ValueError("pct_change(old, new) requires 2 args")
                if args[0] == 0: raise ValueError("division_by_zero")
                return float((args[1] - args[0]) / args[0] * 100)
            if fn == "abs_pct_diff":
                args = [_eval(a) for a in node.args]
                if len(args) != 2: raise ValueError("abs_pct_diff(a, b) requires 2 args")
                if (args[0] + args[1]) == 0: raise ValueError("division_by_zero")
                return float(abs(args[0] - args[1]) / ((args[0] + args[1]) / 2) * 100)
            if fn == "herfindahl":
                vals = _collect_args(node.args)
                total = sum(vals)
                if total == 0: raise ValueError("herfindahl: sum is zero")
                return float(sum((v / total) ** 2 for v in vals))
        if isinstance(node, ast.List):
            if len(node.elts) == 1:
                return _eval(node.elts[0])
            raise ValueError("list_at_top_level_use_a_function")
        raise ValueError("unsupported_expression")

    expr = expression.strip()
    if "=" in expr and not any(op in expr for op in ["==", "!=", ">=", "<="]):
        parts = expr.split("=", 1)
        if parts[0].strip().isidentifier():
            raise ValueError(f"Assignment not supported. Use just the expression: {parts[1].strip()}")
    expr = expr.replace("^", "**")
    tree = ast.parse(expr, mode="eval")
    return _eval(tree)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: HP filter
# ═══════════════════════════════════════════════════════════════════════════


def _hp_whittaker(y: list[float], lam: float) -> list[float]:
    """Pure Python Whittaker-Henderson smoother (HP filter for d=2)."""
    n = len(y)

    def d2td2(i, j, n):
        result = 0.0
        for k in range(max(0, i - 2), min(n - 2, i + 1)):
            di = [1, -2, 1][i - k] if 0 <= i - k <= 2 else 0
            dj = [1, -2, 1][j - k] if 0 <= j - k <= 2 else 0
            result += di * dj
        return result

    A = [[0.0] * n for _ in range(n)]
    for i in range(n):
        A[i][i] += 1.0
        for j in range(max(0, i - 2), min(n, i + 3)):
            A[i][j] += lam * d2td2(i, j, n)

    b = list(y)
    for col in range(n):
        pivot = col
        for row in range(col + 1, min(col + 3, n)):
            if abs(A[row][col]) > abs(A[pivot][col]):
                pivot = row
        A[col], A[pivot] = A[pivot], A[col]
        b[col], b[pivot] = b[pivot], b[col]
        if abs(A[col][col]) < 1e-15:
            continue
        for row in range(col + 1, min(col + 5, n)):
            if row >= n:
                break
            factor = A[row][col] / A[col][col]
            for k in range(col, min(col + 5, n)):
                A[row][k] -= factor * A[col][k]
            b[row] -= factor * b[col]

    z = [0.0] * n
    for i in range(n - 1, -1, -1):
        z[i] = b[i]
        for j in range(i + 1, min(i + 5, n)):
            z[i] -= A[i][j] * z[j]
        if abs(A[i][i]) > 1e-15:
            z[i] /= A[i][i]
    return z


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: CPI data
# ═══════════════════════════════════════════════════════════════════════════

_CPI_DATA: dict | None = None


def _load_cpi() -> dict:
    global _CPI_DATA
    if _CPI_DATA is not None:
        return _CPI_DATA

    csv_path = _SCRIPT_DIR / "cpi_monthly.csv"
    if not csv_path.exists():
        _CPI_DATA = {"annual": {}, "monthly": {}}
        return _CPI_DATA

    annual: dict[int, float] = {}
    monthly: dict[str, float] = {}

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yr = int(row.get("year") or row.get("Year") or 0)
            mo = row.get("month") or row.get("Month") or row.get("period") or ""
            val_str = (row.get("value") or row.get("Value") or
                       row.get("index") or row.get("Index") or row.get("CPI") or "")
            if not val_str or not yr:
                continue
            val = float(val_str)
            if mo and mo not in ("", "0", "Annual", "annual", "Avg"):
                try:
                    m = int(mo)
                    if 1 <= m <= 12:
                        monthly[f"{yr}-{m:02d}"] = val
                except ValueError:
                    pass
            else:
                annual[yr] = val

    if not annual and monthly:
        by_year: dict[int, list[float]] = defaultdict(list)
        for key, val in monthly.items():
            y = int(key.split("-")[0])
            by_year[y].append(val)
        for y, vals in by_year.items():
            annual[y] = sum(vals) / len(vals)

    _CPI_DATA = {"annual": annual, "monthly": monthly}
    return _CPI_DATA


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6: FastMCP app and tool definitions
# ═══════════════════════════════════════════════════════════════════════════

mcp = FastMCP(
    "officeqa-arena",
    host=_DEFAULT_HOST,
    port=_DEFAULT_PORT,
)

_corpus: CorpusIndex | None = None


def _get_corpus() -> CorpusIndex:
    global _corpus
    if _corpus is None:
        raise RuntimeError("Corpus not loaded yet — call _init_corpus() first")
    return _corpus


def _init_corpus(corpus_dir: str) -> None:
    global _corpus
    _corpus = CorpusIndex(corpus_dir)


# ---------------------------------------------------------------------------
# Tool call logging — wraps every @mcp.tool() to log name, args, latency
# ---------------------------------------------------------------------------

_tool_call_count = 0


def _log_tool_call(func):
    """Decorator that logs every MCP tool call with args, latency, and result size."""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        global _tool_call_count
        _tool_call_count += 1
        call_num = _tool_call_count
        name = func.__name__

        # Summarize args (truncate long values)
        arg_parts = []
        for k, v in kwargs.items():
            sv = str(v)
            if len(sv) > 80:
                sv = sv[:77] + "..."
            arg_parts.append(f"{k}={sv}")
        args_str = ", ".join(arg_parts) or "(no args)"

        logger.info("[CALL #%d] %s(%s)", call_num, name, args_str)
        t0 = time.time()
        try:
            result = func(*args, **kwargs)
            latency = time.time() - t0
            result_len = len(result) if isinstance(result, str) else 0
            # Log a preview of the result
            preview = result[:150] + "..." if isinstance(result, str) and len(result) > 150 else result
            logger.info("[DONE #%d] %s -> %d bytes in %.2fs | %s",
                        call_num, name, result_len, latency, preview)
            return result
        except Exception as exc:
            latency = time.time() - t0
            logger.error("[FAIL #%d] %s -> %s in %.2fs", call_num, name, exc, latency)
            raise

    return wrapper


# ---------------------------------------------------------------------------
# Tool: get_table
# ---------------------------------------------------------------------------


@mcp.tool()
@_log_tool_call
def get_table(
    bulletin: str,
    keyword: str,
    row_filter: str = "",
) -> str:
    """Find and return a full table from a Treasury Bulletin as structured data.

    This is the primary data extraction tool. Pass the bulletin ID and a keyword
    to match the table title. Returns structured rows with column names as keys.

    The server parses the raw corpus files and returns clean JSON — no need
    for grep or manual extraction.

    Args:
        bulletin: Bulletin ID (e.g. '1950_06' or 'treasury_bulletin_1950_06.txt')
        keyword: Keyword to match table title (e.g. 'Exchange Stabilization Fund')
        row_filter: Optional substring filter on row labels (e.g. '1945' to only get 1945 rows)
    """
    corpus = _get_corpus()
    result = corpus.get_table(bulletin=bulletin, keyword=keyword, row_filter=row_filter)
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: search_corpus
# ---------------------------------------------------------------------------


@mcp.tool()
@_log_tool_call
def search_corpus(
    query: str,
    bulletin: str = "",
    limit: int = 20,
) -> str:
    """Search across all Treasury Bulletins for tables matching a query.

    Uses full-text search with fuzzy matching to find tables by title,
    column headers, or row labels. Returns structured results with sample data.

    Start here when you don't know which bulletin contains the data you need.

    Args:
        query: Search terms (e.g. 'national defense expenditures', 'gold reserves')
        bulletin: Optional bulletin ID to restrict search (e.g. '1950_06')
        limit: Max results to return (default 20)
    """
    corpus = _get_corpus()
    result = corpus.search_corpus(query=query, bulletin=bulletin, limit=limit)
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: get_bulletin_index
# ---------------------------------------------------------------------------


@mcp.tool()
@_log_tool_call
def get_bulletin_index(
    bulletin: str = "",
) -> str:
    """List all available Treasury Bulletins and their tables.

    Without a bulletin ID, returns a summary of all 697 bulletins with table counts.
    With a bulletin ID, returns detailed table list for that specific bulletin.

    Args:
        bulletin: Optional bulletin ID for details (e.g. '1950_06'). Omit for full index.
    """
    corpus = _get_corpus()
    result = corpus.get_bulletin_index(bulletin=bulletin)
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: find_values
# ---------------------------------------------------------------------------


@mcp.tool()
@_log_tool_call
def find_values(
    query: str,
    year: str = "",
    month: str = "",
) -> str:
    """One-shot search: find specific cell values across all tables.

    More targeted than search_corpus — uses year/month to locate the exact
    column and returns individual cell values with provenance (table title,
    units, file_id, period_basis).

    Use this when you know what metric and year you need.

    Args:
        query: What to search for (e.g. 'national defense expenditures')
        year: Target year to find in column headers (e.g. '1945')
        month: Target month (e.g. 'june', 'september')
    """
    corpus = _get_corpus()
    result = corpus.find_values(query=query, year=year, month=month)
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: verify_answer
# ---------------------------------------------------------------------------


@mcp.tool()
@_log_tool_call
def verify_answer(
    answer: str,
    question_type: str = "",
) -> str:
    """Sanity-check an answer before submitting. Checks if numeric, reasonable magnitude, correct sign.

    Args:
        answer: The answer to verify (e.g. '12345.67')
        question_type: Optional hint: 'percentage', 'dollar_amount', 'count', 'ratio'
    """
    result = verify_answer_impl(answer=answer, question_type=question_type)
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: compute_expression
# ---------------------------------------------------------------------------


@mcp.tool()
@_log_tool_call
def compute_expression(
    expression: str,
    variables: dict | None = None,
) -> str:
    """Safe arithmetic evaluator. Use for ALL math — never do mental math.

    Supports: +, -, *, /, ** (power), abs(), round(), min(), max(), sum(),
    sqrt(), log(), exp(), geometric_mean(), mean(), prod(), stdev(), pow(), len(),
    pct_change(old, new), cagr(start, end, years), median(), variance(),
    gini(), herfindahl(), theil(), linreg([x], [y]).

    Use ** for power (^ also works). Pass numeric values as variables.

    Args:
        expression: Math expression (e.g. 'pct_change(a, b)', 'geometric_mean(1,2,3)')
        variables: Variable name→value mapping (e.g. {"a": 494, "b": 154})
    """
    try:
        clean_vars = {k: float(v) for k, v in (variables or {}).items()}
        result = safe_eval_finance(expression, clean_vars)
        return json.dumps({"ok": True, "result": result, "expression_echo": expression})
    except (ValueError, SyntaxError, TypeError, ZeroDivisionError) as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Tool: get_cpi_index
# ---------------------------------------------------------------------------


@mcp.tool()
@_log_tool_call
def get_cpi_index(year: int, month: int | None = None) -> str:
    """Get CPI-U index value for inflation-adjusted calculations (base: 1982-84=100).

    Args:
        year: Calendar year
        month: Optional month (1-12) for monthly CPI. Omit for annual average.
    """
    data = _load_cpi()
    annual = data["annual"]
    monthly = data["monthly"]

    if month is None or month == 0:
        idx = annual.get(int(year))
        if idx is None:
            return json.dumps({
                "ok": False, "error": "annual_cpi_not_found", "year": year,
                "available_years_sample": sorted(annual.keys())[:8],
            })
        return json.dumps({
            "ok": True, "year": year, "month": None, "index": idx,
            "basis": "CPI-U All Items U.S. city average; annual average (1982-84=100)",
        })

    if month < 1 or month > 12:
        return json.dumps({"ok": False, "error": "invalid_month", "month": month})

    key = f"{year}-{month:02d}"
    idx = monthly.get(key)
    if idx is None:
        return json.dumps({
            "ok": False, "error": "monthly_cpi_not_found", "year": year, "month": month,
        })
    return json.dumps({
        "ok": True, "year": year, "month": month, "index": idx,
        "basis": "CPI-U All Items U.S. city average; monthly (1982-84=100)",
    })


# ---------------------------------------------------------------------------
# Tool: get_fiscal_year_bounds
# ---------------------------------------------------------------------------


@mcp.tool()
@_log_tool_call
def get_fiscal_year_bounds(fiscal_year: int) -> str:
    """Get start/end dates for a U.S. federal fiscal year.

    Before 1977: Jul 1 (Y-1) to Jun 30 (Y). From 1977+: Oct 1 (Y-1) to Sep 30 (Y).

    Args:
        fiscal_year: The fiscal year number (e.g. 1955)
    """
    fy = int(fiscal_year)
    if fy <= 0:
        return json.dumps({"ok": False, "error": "invalid_fiscal_year", "fiscal_year": fy})

    if fy <= 1976:
        return json.dumps({
            "ok": True, "fiscal_year": fy,
            "period_start": f"{fy - 1}-07-01",
            "period_end": f"{fy}-06-30",
            "basis": "U.S. federal fiscal year (Jul 1 - Jun 30, pre-1977)",
        })

    return json.dumps({
        "ok": True, "fiscal_year": fy,
        "period_start": f"{fy - 1}-10-01",
        "period_end": f"{fy}-09-30",
        "basis": "U.S. federal fiscal year (Oct 1 - Sep 30)",
    })


# ---------------------------------------------------------------------------
# Tool: get_exchange_rate
# ---------------------------------------------------------------------------

_fx_cache: dict | None = None


def _load_fx_csv(path: Path) -> dict:
    if not path.is_file():
        return {"path": str(path), "entries": []}
    entries = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("pair,"):
                continue
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                entries.append({
                    "pair": parts[0].strip().upper(),
                    "year": int(parts[1].strip()),
                    "month": int(parts[2].strip()),
                    "day": int(parts[3].strip()),
                    "rate": float(parts[4].strip()),
                    "type": parts[5].strip(),
                })
            except (ValueError, IndexError):
                continue
    return {"path": str(path), "entries": entries}


@mcp.tool()
@_log_tool_call
def get_exchange_rate(
    pair: str,
    year: int,
    month: int | None = None,
    day: int | None = None,
) -> str:
    """Look up a historical exchange rate for currency conversion questions.

    Covers USD/GBP, USD/JPY, USD/CAD, USD/DEM, USD/INR and others.
    Returns best available precision: spot > monthly_avg > annual_avg.

    Args:
        pair: Currency pair e.g. 'USD/GBP' (dollars per pound), 'USD/JPY' (yen per dollar)
        year: Calendar year
        month: Optional month (1-12) for monthly rate
        day: Optional day for spot rate
    """
    global _fx_cache
    csv_path = _SCRIPT_DIR / "exchange_rates.csv"
    rp = str(csv_path)
    if _fx_cache is None or _fx_cache.get("path") != rp:
        _fx_cache = _load_fx_csv(csv_path)

    entries = _fx_cache.get("entries", [])
    p = str(pair).strip().upper()
    y = int(year)
    m = int(month) if month else 0
    d = int(day) if day else 0

    best = None
    best_score = -1
    for e in entries:
        if e["pair"] != p or e["year"] != y:
            continue
        if d and e["month"] == m and e["day"] == d:
            score = 3
        elif m and e["month"] == m and e["day"] == 0:
            score = 2
        elif m and e["month"] == m:
            score = 2
        elif e["month"] == 0:
            score = 1
        else:
            continue
        if score > best_score:
            best_score = score
            best = e

    if best is None:
        available = sorted({e["pair"] for e in entries})
        return json.dumps({
            "ok": False,
            "error": "exchange_rate_not_found",
            "pair": p, "year": y,
            "available_pairs": available,
            "hint": "Check available_pairs for supported currencies.",
        })

    return json.dumps({
        "ok": True,
        "pair": best["pair"],
        "year": best["year"],
        "month": best["month"] or None,
        "day": best["day"] or None,
        "rate": best["rate"],
        "type": best["type"],
    })


# ---------------------------------------------------------------------------
# Tool: fuzzy_match (expose RapidFuzz directly for ad-hoc label matching)
# ---------------------------------------------------------------------------


@mcp.tool()
@_log_tool_call
def fuzzy_match(
    query: str,
    candidates: list[str],
    limit: int = 5,
    score_cutoff: float = 50.0,
) -> str:
    """Find the best fuzzy matches for a query string against a list of candidates.

    Uses RapidFuzz WRatio scoring (handles partial matches, token reordering,
    abbreviations). Useful for matching messy row/column labels to clean names.

    Args:
        query: The string to match (e.g. 'Natl. defense expenditures')
        candidates: List of strings to match against
        limit: Max results (default 5)
        score_cutoff: Minimum score 0-100 (default 50)
    """
    if not query or not candidates:
        return json.dumps({"error": "query and candidates required"})

    if _HAS_RAPIDFUZZ:
        results = rf_process.extract(
            query, candidates, scorer=rf_fuzz.WRatio,
            score_cutoff=score_cutoff, limit=limit
        )
        matches = [{"match": m[0], "score": round(m[1], 1), "index": m[2]} for m in results]
    else:
        # Fallback to difflib
        close = difflib.get_close_matches(query, candidates, n=limit, cutoff=score_cutoff / 100)
        matches = [
            {"match": m, "score": round(difflib.SequenceMatcher(None, query.lower(), m.lower()).ratio() * 100, 1)}
            for m in close
        ]

    return json.dumps({
        "ok": True,
        "query": query,
        "matches": matches,
        "engine": "rapidfuzz" if _HAS_RAPIDFUZZ else "difflib",
    })


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7: Entrypoint
# ═══════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(description="OfficeQA Arena MCP SSE Server")
    parser.add_argument("--host", default=_DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT)
    parser.add_argument(
        "--corpus",
        default=os.environ.get("OFFICEQA_CORPUS_DIR", ""),
        help="Path to corpus directory with treasury_bulletin_*.txt files",
    )
    parser.add_argument(
        "--transport",
        default="streamable-http",
        choices=["sse", "streamable-http", "stdio"],
        help="Transport type (default: streamable-http)",
    )
    args = parser.parse_args()

    # Find corpus directory
    corpus_dir = args.corpus
    if not corpus_dir:
        for candidate in ["/app/corpus", str(_SCRIPT_DIR / "corpus"), "./corpus"]:
            if Path(candidate).exists():
                corpus_dir = candidate
                break
    if not corpus_dir or not Path(corpus_dir).exists():
        logger.error("No corpus directory found. Use --corpus or set OFFICEQA_CORPUS_DIR.")
        raise SystemExit(1)

    # Load corpus
    logger.info("Loading corpus from: %s", corpus_dir)
    _init_corpus(corpus_dir)

    # Load CPI
    _load_cpi()

    # Configure and start server
    mcp.settings.host = args.host
    mcp.settings.port = args.port

    logger.info(
        "Starting MCP server on %s:%d (transport=%s) — %d tables indexed",
        args.host, args.port, args.transport, len(_get_corpus().tables),
    )
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
