"""Read-only helpers for the compressed table_cell_blobs table.

Replaces direct SQL queries against table_first_table_cells with
blob decompression + Python filtering.
"""

import sqlite3
from typing import Any

try:
    import msgpack
    import zstandard
    _dctx = zstandard.ZstdDecompressor()
    _HAS_DEPS = True
except ImportError:
    _HAS_DEPS = False
    _dctx = None  # type: ignore[assignment]


def _unpack_blob(conn: sqlite3.Connection, table_pk: int) -> list[dict] | None:
    """Decompress and unpack the cell blob for a table_pk.

    Returns list of cell dicts with short keys
    (ro, rl, rn, co, cl, cn, ts, y, m, vr, nv, rt, cf, ps, pf).
    Returns None if table_pk not found.
    """
    row = conn.execute(
        "SELECT data FROM table_cell_blobs WHERE table_pk = ?", (table_pk,)
    ).fetchone()
    if row is None:
        return None
    raw = _dctx.decompress(row[0] if isinstance(row, tuple) else row["data"])
    obj = msgpack.unpackb(raw, raw=False)
    return obj["rows"]


def _normalize_text_simple(s: str) -> str:
    """Simple normalization matching db.py's _normalize_text."""
    if not s:
        return ""
    return s.lower().replace("/", "").replace(".", "").strip()


def query_cells(
    conn: sqlite3.Connection,
    table_pk: int,
    *,
    row_label: str = "",
    column_label: str = "",
    year: int | None = None,
    year_range: tuple[int, int] | None = None,
    month: int | None = None,
    limit: int = 20,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Query cells from blob storage with filtering.

    Returns (rows, warnings, match_info) where rows are in the same format
    as query_table_rows returns (expanded keys, not short keys).
    """
    cells = _unpack_blob(conn, table_pk)
    if cells is None:
        return [], ["table_not_found in cell_blobs"], {}

    warnings: list[str] = []
    match_info: dict[str, Any] = {}

    # Normalize filter inputs
    rl_norm = _normalize_text_simple(row_label) if row_label else ""
    cl_norm = _normalize_text_simple(column_label) if column_label else ""

    # Build year set
    year_values: set[int] = set()
    if year is not None:
        year_values.add(int(year))
    if year_range and len(year_range) >= 2:
        yr_start, yr_end = min(year_range[0], year_range[1]), max(
            year_range[0], year_range[1]
        )
        if year_range[0] > year_range[1]:
            warnings.append(
                f"year_range was reversed, using [{yr_start}, {yr_end}]"
            )
        year_values.update(range(yr_start, yr_end + 1))

    # Filter cells
    # For row_label: try exact first, fall back to fuzzy
    rl_match_type = ""
    if rl_norm:
        exact_matches = [c for c in cells if c.get("rn", "") == rl_norm]
        if exact_matches:
            rl_match_type = "exact"
        else:
            rl_match_type = "fuzzy"
            warnings.append(
                f"row_label '{row_label}' matched via fuzzy contains, not exact match"
            )

    cl_match_type = ""
    if cl_norm:
        exact_cl = [c for c in cells if c.get("cn", "") == cl_norm]
        if exact_cl:
            cl_match_type = "exact"
        else:
            cl_match_type = "fuzzy"
            warnings.append(
                f"column_label '{column_label}' matched via fuzzy contains, not exact match"
            )

    # Apply filters
    filtered: list[dict] = []
    for c in cells:
        # Row label filter
        if rl_norm:
            cell_rn = c.get("rn", "")
            if rl_match_type == "exact":
                if cell_rn != rl_norm:
                    continue
            else:
                if rl_norm not in cell_rn:
                    continue

        # Column label filter
        if cl_norm:
            cell_cn = c.get("cn", "")
            if cl_match_type == "exact":
                if cell_cn != cl_norm:
                    continue
            else:
                if cl_norm not in cell_cn:
                    continue

        # Year filter
        if year_values:
            cell_year = c.get("y")
            cell_ts = c.get("ts", "")
            # Match by year column OR time_scope string
            year_match = False
            if cell_year is not None and cell_year in year_values:
                year_match = True
            elif cell_ts:
                for yv in year_values:
                    if str(yv) in cell_ts:
                        year_match = True
                        break
            if not year_match:
                continue

        # Month filter
        if month is not None:
            if c.get("m") != int(month):
                continue

        filtered.append(c)
        if len(filtered) >= limit:
            break

    # Convert short keys to full format for compatibility
    compact: list[dict[str, Any]] = []
    for c in filtered:
        nv = c.get("nv")
        try:
            nv = float(nv) if nv is not None else None
        except (TypeError, ValueError):
            nv = None
        compact.append(
            {
                "row_label": c.get("rl", ""),
                "column_label": c.get("cl", ""),
                "value_raw": c.get("vr", ""),
                "normalized_value": nv,
                "year": c.get("y"),
                "month": c.get("m"),
                "time_scope": c.get("ts", ""),
            }
        )

    # Build match_info
    if rl_norm:
        match_info["row_match_mode"] = rl_match_type
        if compact:
            match_info["matched_row_labels"] = sorted(
                {r["row_label"] for r in compact}
            )[:10]
    if cl_norm:
        match_info["column_match_mode"] = cl_match_type
        if compact:
            match_info["matched_column_labels"] = sorted(
                {r["column_label"] for r in compact}
            )[:10]

    return compact, warnings, match_info


def get_distinct_column_labels(
    conn: sqlite3.Connection, table_pk: int
) -> list[str]:
    """Get distinct column labels for a table from blob storage."""
    cells = _unpack_blob(conn, table_pk)
    if cells is None:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for c in cells:
        cl = c.get("cl", "")
        if cl and cl not in seen:
            seen.add(cl)
            result.append(cl)
    return sorted(result)


def get_distinct_row_labels(
    conn: sqlite3.Connection, table_pk: int, limit: int = 15
) -> list[str]:
    """Get distinct row labels for a table from blob storage, ordered by row_ordinal."""
    cells = _unpack_blob(conn, table_pk)
    if cells is None:
        return []
    # Sort by row_ordinal, deduplicate
    sorted_cells = sorted(cells, key=lambda c: c.get("ro", 0))
    seen: set[str] = set()
    result: list[str] = []
    for c in sorted_cells:
        rl = c.get("rl", "")
        if rl and rl not in seen:
            seen.add(rl)
            result.append(rl)
            if len(result) >= limit:
                break
    return result


def blob_table_available(conn: sqlite3.Connection) -> bool:
    """Check if table_cell_blobs exists and deps are installed."""
    if not _HAS_DEPS:
        return False
    row = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='table_cell_blobs'"
    ).fetchone()
    return (row[0] if isinstance(row, tuple) else row[0]) > 0


def supplement_search_from_blobs(
    conn: sqlite3.Connection,
    table_pks: list[int],
) -> dict[int, list[str]]:
    """Get column labels for multiple table_pks efficiently (for search_tables).

    Returns {table_pk: [column_labels]}.
    """
    result: dict[int, list[str]] = {}
    for pk in table_pks:
        cols = get_distinct_column_labels(conn, pk)
        if cols:
            result[pk] = cols
    return result
