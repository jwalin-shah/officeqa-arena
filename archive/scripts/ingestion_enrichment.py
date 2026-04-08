"""Ingestion-time enrichment: computed once while building the DB.

These functions run on each table's cells BEFORE packing into blobs.
They produce metadata for table_index and a metric_aliases registry.

Used by reingest_from_json.py during blob construction.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any


# ---------------------------------------------------------------------------
# 1. Table fingerprinting (item 9)
# ---------------------------------------------------------------------------

def compute_table_fingerprint(cells: list[dict]) -> dict[str, Any]:
    """Compute structural fingerprint for a table's cells.

    Args:
        cells: list of cell dicts with keys like rl, cl, nv, vr, rt, etc.

    Returns dict with:
        - cell_count, numeric_count, sparsity
        - has_total_row, total_sums_correctly
        - has_footnotes, footnote_count
        - has_pct_values
        - year_span
    """
    if not cells:
        return {"cell_count": 0, "sparsity": 1.0}

    total = len(cells)
    numeric = sum(1 for c in cells if c.get("nv") is not None)
    sparsity = 1.0 - (numeric / total) if total > 0 else 1.0

    # Footnote stats
    fn_count = sum(1 for c in cells if c.get("fn"))

    # Detect % values
    has_pct = any("%" in str(c.get("vr", "")) for c in cells)

    # Year span
    years = [c["y"] for c in cells if c.get("y") is not None]
    year_span = (min(years), max(years)) if years else None

    # Detect total row and check if it sums correctly
    total_check = _check_additive_totals(cells)

    fp: dict[str, Any] = {
        "cell_count": total,
        "numeric_count": numeric,
        "sparsity": round(sparsity, 3),
        "has_footnotes": fn_count > 0,
        "footnote_count": fn_count,
        "has_pct_values": has_pct,
    }
    if year_span:
        fp["year_span"] = list(year_span)
    fp.update(total_check)
    return fp


def _check_additive_totals(cells: list[dict]) -> dict[str, Any]:
    """Check if 'Total' rows sum correctly from preceding rows.

    Groups cells by column, looks for rows labeled 'total' or 'grand total',
    and checks if the sum of non-total rows in that column matches.
    """
    result: dict[str, Any] = {"has_total_row": False, "total_sums_correctly": None}

    # Group by (column_label, year) → list of (row_label, normalized_value)
    col_groups: dict[tuple, list[tuple[str, float | None]]] = defaultdict(list)
    for c in cells:
        key = (c.get("cl", ""), c.get("y"))
        col_groups[key].append((c.get("rl", ""), c.get("nv")))

    checks = 0
    correct = 0
    for key, rows in col_groups.items():
        total_val = None
        non_total_sum = 0.0
        has_non_total = False

        for rl, nv in rows:
            rl_lower = (rl or "").lower().strip().rstrip(".")
            if rl_lower in ("total", "grand total", "total all", "totals"):
                if nv is not None:
                    total_val = nv
                    result["has_total_row"] = True
            else:
                if nv is not None:
                    non_total_sum += nv
                    has_non_total = True

        if total_val is not None and has_non_total and total_val != 0:
            checks += 1
            # Allow 1% tolerance for rounding
            if abs(non_total_sum - total_val) / abs(total_val) < 0.01:
                correct += 1

    if checks > 0:
        result["total_sums_correctly"] = correct == checks
        result["total_check_ratio"] = f"{correct}/{checks}"

    return result


# ---------------------------------------------------------------------------
# 2. Formula/operator hints (item 8)
# ---------------------------------------------------------------------------

def compute_structure_hints(
    cells: list[dict],
    table_title: str = "",
    column_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Infer likely operators/structure from table content.

    Returns hints like has_additive_total, has_pct_column, has_change_column, etc.
    """
    hints: dict[str, Any] = {}

    # Collect unique row and column labels
    row_labels = {c.get("rl", "").lower().strip() for c in cells}
    col_labels = set(column_labels or [])
    if not col_labels:
        col_labels = {c.get("cl", "").lower().strip() for c in cells}

    all_labels = row_labels | col_labels
    title_lower = table_title.lower()

    # Additive total
    hints["has_additive_total"] = any(
        l in ("total", "grand total", "totals", "total all")
        for l in row_labels
    )

    # Percentage columns/rows
    hints["has_pct_column"] = any(
        "percent" in l or "%" in l or "share" in l or "ratio" in l
        for l in all_labels
    )

    # Change/difference columns
    hints["has_change_column"] = any(
        "change" in l or "difference" in l or "increase" in l or "decrease" in l
        for l in all_labels
    )

    # Per capita
    hints["has_per_capita"] = any("per capita" in l for l in all_labels) or "per capita" in title_lower

    # Net vs Gross
    hints["has_net_gross"] = any(
        l.startswith("net ") or l.startswith("gross ") or " net" in l
        for l in all_labels
    )

    # Cumulative / YTD
    hints["has_cumulative"] = any(
        "cumulative" in l or "year to date" in l or "ytd" in l
        for l in all_labels
    ) or "cumulative" in title_lower

    # Likely operation family
    if hints["has_pct_column"] and hints["has_change_column"]:
        hints["likely_ops"] = ["percent_change", "difference"]
    elif hints["has_change_column"]:
        hints["likely_ops"] = ["difference"]
    elif hints["has_additive_total"]:
        hints["likely_ops"] = ["sum", "lookup"]
    else:
        hints["likely_ops"] = ["lookup"]

    return hints


# ---------------------------------------------------------------------------
# 3. Metric alias collection (item 1)
# ---------------------------------------------------------------------------

class MetricAliasCollector:
    """Collects unique row/column labels across all tables for alias registry.

    Call .add() for each table during ingestion, then .build_registry() at the end.
    """

    def __init__(self) -> None:
        # canonical_key → set of (alias, source_file, decade)
        self._raw: dict[str, set[tuple[str, str, int]]] = defaultdict(set)

    def add(
        self,
        row_labels: list[str],
        column_labels: list[str],
        source_file: str,
    ) -> None:
        """Register labels from one table."""
        # Extract decade from source_file (e.g. "treasury_bulletin_1941_01.txt" → 1940)
        m = re.search(r"(\d{4})", source_file)
        decade = (int(m.group(1)) // 10) * 10 if m else 0

        for label in row_labels + column_labels:
            label = label.strip()
            if not label or len(label) < 3:
                continue
            # Skip pure numbers/dates
            if re.fullmatch(r"[\d.,\-/\s]+", label):
                continue
            if re.fullmatch(r"(?:19|20)\d{2}(?:-\w+)?", label):
                continue

            key = _normalize_metric_key(label)
            if key and len(key) >= 3:
                self._raw[key].add((label, source_file, decade))

    def build_registry(self) -> list[dict[str, Any]]:
        """Build the final metric_aliases table rows.

        Returns list of dicts with: canonical, alias, first_source, decade, count.
        Only includes metrics seen in 3+ tables (filters noise).
        """
        rows: list[dict[str, Any]] = []
        for key, entries in self._raw.items():
            if len(entries) < 3:
                continue

            # Pick the most common alias as canonical
            alias_counts: dict[str, int] = defaultdict(int)
            for alias, _sf, _dec in entries:
                alias_counts[alias] += 1

            canonical = max(alias_counts, key=alias_counts.get)  # type: ignore[arg-type]
            decades = sorted({dec for _, _, dec in entries})
            sources = {sf for _, sf, _ in entries}

            for alias, sf, dec in entries:
                if alias != canonical:
                    rows.append({
                        "canonical": canonical,
                        "alias": alias,
                        "decade": dec,
                        "count": alias_counts[alias],
                    })

            # Also add the canonical itself
            rows.append({
                "canonical": canonical,
                "alias": canonical,
                "decade": decades[0] if decades else 0,
                "count": alias_counts[canonical],
            })

        return rows


def _normalize_metric_key(label: str) -> str:
    """Normalize a label to a canonical key for deduplication."""
    s = label.lower().strip()
    # Remove footnote markers
    s = re.sub(r"\s*\d+/\s*$", "", s)
    # Remove trailing punctuation
    s = s.rstrip(".:,;")
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # Remove common prefixes/suffixes that vary
    s = re.sub(r"^(total\s+)", "", s)
    return s
