"""Read-only SQLite database layer for OfficeQA Arena MCP tools.

Ported from officeqa/src/ingestion_db.py — search/scoring logic only, no writes.
All functions take an open sqlite3.Connection; use open_db() to get one.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from server import cell_blobs

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_KNOWN_ENTITY_PHRASES = (
    "national defense",
    "miscellaneous internal revenue",
    "internal revenue",
    "public debt",
    "budget expenditures",
    "budget receipts",
    "customs",
    "employment taxes",
    "income taxes",
    "corporation income taxes",
    "excise taxes",
    "estate and gift taxes",
    "interest on the public debt",
    "major functions",
    # Added based on question corpus analysis
    "judiciary",
    "agriculture",
    "highway trust fund",
    "public works",
    "foreign exchange",
    "currency in circulation",
    "corporate bonds",
    "railroad retirement",
    "tariff",
    "treasury bonds",
    "liquidity ratio",
    "trust receipts",
    "fiscal service",
)

_GENERIC_ROW_LABEL_PHRASES = {
    "calendar year", "calendar years", "calendar yr", "calendar yrs",
    "end of calendar year or month", "end of year or month",
    "period", "periods", "month", "months", "year", "years",
    "total", "totals", "all other", "other", "subtotal", "subtotals",
    "grand total",
}

_MONTH_LABEL_PATTERN = (
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
    r"january|february|march|april|june|july|august|september|october|november|december)"
)

_TREASURY_BULLETIN_TXT = re.compile(
    r"^treasury_bulletin_((?:19|20)\d{2})_(0[1-9]|1[0-2])\.txt$",
    re.IGNORECASE,
)

_YEAR_SCOPE_RE = re.compile(r"^(?:19|20)\d{2}$")
_MONTH_SCOPE_RE = re.compile(r"^((?:19|20)\d{2})-(0[1-9]|1[0-2])$")

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


import sys

def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Open a read-only SQLite connection to the corpus database.

    Raises FileNotFoundError if the database does not exist.
    """
    p = Path(db_path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Database not found: {p}")
    uri = f"file:{p}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass
    return conn


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    return row is not None


def _table_column_names(conn: sqlite3.Connection, name: str) -> set[str]:
    if not _table_exists(conn, name):
        return set()
    return {
        str(r["name"])
        for r in conn.execute(f"PRAGMA table_info({name})").fetchall()
    }


def _table_index_available(conn: sqlite3.Connection) -> bool:
    return _table_exists(conn, "table_index") and _table_exists(conn, "table_scope_index")


def _table_term_index_available(conn: sqlite3.Connection) -> bool:
    return _table_exists(conn, "table_term_index")


def _table_first_available(conn: sqlite3.Connection) -> bool:
    return _table_exists(conn, "table_first_tables")


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _decode_json(value: str | None, *, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        decoded = _decode_json(value, fallback=[])
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]
    return []


def _stable_unique(values: list[str], *, limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        n = str(v or "").strip()
        if not n or n in seen:
            continue
        seen.add(n)
        out.append(n)
        if limit is not None and len(out) >= int(limit):
            break
    return out


def _detect_entity_terms(*texts: str) -> list[str]:
    hay = " ".join(_normalize_text(t) for t in texts if str(t or "").strip())
    return [phrase for phrase in _KNOWN_ENTITY_PHRASES if phrase in hay]


def _informative_profile_tokens(value: str) -> list[str]:
    return [
        tok
        for tok in re.findall(r"[a-z0-9]+", _normalize_text(value))
        if len(tok) >= 3 and not re.fullmatch(r"(?:19|20)\d{2}", tok)
    ]


def _phrase_windows(tokens: list[str], *, min_size: int = 2, max_size: int = 3) -> list[str]:
    out: list[str] = []
    for size in range(min_size, max_size + 1):
        if len(tokens) < size:
            continue
        for idx in range(len(tokens) - size + 1):
            phrase = " ".join(tokens[idx : idx + size]).strip()
            if phrase:
                out.append(phrase)
    return out


# --- File ID canonicalization ---


def _safe_corpus_file_id(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw or "\x00" in raw:
        return None
    if any(sep in raw for sep in ("/", "\\")):
        return None
    if Path(raw).name != raw or raw in {".", ".."}:
        return None
    m = _TREASURY_BULLETIN_TXT.fullmatch(raw)
    if not m:
        return None
    return f"treasury_bulletin_{m.group(1)}_{m.group(2)}.txt"


def _canonical_source_file(value: str) -> str:
    text = Path(str(value or "").strip()).name
    if not text:
        return ""
    # Accept short formats like "1941_01", "1941-01", "YYYY_MM"
    short = re.fullmatch(r"(\d{4})[_-](\d{2})", text)
    if short:
        text = f"treasury_bulletin_{short.group(1)}_{short.group(2)}.txt"
    elif text.endswith(".json"):
        text = f"{text[:-5]}.txt"
    elif not text.endswith(".txt"):
        text = f"{text}.txt"
    return _safe_corpus_file_id(text) or ""


def _parse_source_year_month(source_file: str) -> tuple[int | None, int | None]:
    m = re.search(r"treasury_bulletin_(\d{4})_(\d{2})", _canonical_source_file(source_file))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


# --- Scope helpers ---


def _normalize_required_scopes(value: list[str] | None) -> list[str]:
    if not value:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        code = str(item or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return sorted(out)


def _annual_scope_years(required_scopes: list[str] | None) -> list[int]:
    years: list[int] = []
    seen: set[int] = set()
    for scope in _normalize_required_scopes(required_scopes):
        if not _YEAR_SCOPE_RE.fullmatch(scope):
            continue
        year = int(scope)
        if year in seen:
            continue
        seen.add(year)
        years.append(year)
    return years


def _compute_scope_diagnostics(
    *, required_scopes: list[str] | None, observed_scopes: list[str] | None,
) -> dict[str, Any]:
    required = _normalize_required_scopes(required_scopes)
    observed = {str(s or "").strip() for s in (observed_scopes or []) if str(s or "").strip()}
    months_by_year: dict[str, set[str]] = {}
    for scope in observed:
        m = _MONTH_SCOPE_RE.fullmatch(scope)
        if m:
            months_by_year.setdefault(m.group(1), set()).add(scope)
    matched: list[str] = []
    missing: list[str] = []
    avm_complete: list[str] = []
    avm_missing: dict[str, list[str]] = {}
    for scope in required:
        if scope in observed:
            matched.append(scope)
            continue
        if _YEAR_SCOPE_RE.fullmatch(scope):
            obs_months = months_by_year.get(scope, set())
            if len(obs_months) == 12:
                matched.append(scope)
                avm_complete.append(scope)
                continue
            if obs_months:
                wanted = [f"{scope}-{mo:02d}" for mo in range(1, 13)]
                avm_missing[scope] = [ms for ms in wanted if ms not in obs_months]
        missing.append(scope)
    return {
        "required_scopes": required,
        "observed_scopes": sorted(observed),
        "matched_scopes": matched,
        "missing_scopes": missing,
        "annual_via_monthly": {"complete_years": avm_complete, "missing_months_by_year": avm_missing},
        "exact_scope_match": bool(required) and not missing,
        "matched_scope_count": len(matched),
        "required_scope_count": len(required),
    }


def _infer_query_period_basis(query: str) -> str:
    q = str(query or "").strip().lower()
    if "fiscal year" in q:
        return "fiscal"
    if "calendar year" in q:
        return "calendar"
    if "month ended" in q or "months ended" in q:
        return "monthly_reporting"
    return "unknown"


def _infer_query_revision_status(query: str) -> str:
    q = str(query or "").strip().lower()
    if "preliminary" in q or re.search(r"\bprelim\b", q):
        return "preliminary"
    if "revised" in q:
        return "revised"
    if "estimated" in q or "estimate" in q:
        return "estimated"
    if "final" in q:
        return "final"
    return "unknown"


def _compute_table_compat(
    *, query: str, required_scopes: list[str] | None,
    observed_scopes: list[str] | None, period_basis: str, revision_status: str,
) -> dict[str, Any]:
    scope = _compute_scope_diagnostics(required_scopes=required_scopes, observed_scopes=observed_scopes)
    exp_pb = _infer_query_period_basis(query)
    obs_pb = str(period_basis or "unknown").strip().lower() or "unknown"
    if exp_pb == "unknown" or obs_pb == "unknown":
        pb_fit = "unknown"
    elif exp_pb == obs_pb:
        pb_fit = "exact"
    elif exp_pb == "calendar" and obs_pb == "mixed_or_year_end":
        pb_fit = "compatible"
    else:
        pb_fit = "mismatch"
    exp_rs = _infer_query_revision_status(query)
    obs_rs = str(revision_status or "unknown").strip().lower() or "unknown"
    if exp_rs == "unknown" or obs_rs == "unknown":
        rs_fit = "unknown"
    elif exp_rs == obs_rs:
        rs_fit = "exact"
    else:
        rs_fit = "mismatch"
    return {
        **scope,
        "period_basis_fit": {"expected": exp_pb, "observed": obs_pb, "fit": pb_fit},
        "revision_status_fit": {"expected": exp_rs, "observed": obs_rs, "fit": rs_fit},
    }


# --- Query parsing ---


def _query_search_terms(query: str) -> tuple[list[str], list[str]]:
    tokens = re.findall(r"[a-z0-9]+", _normalize_text(query))
    stopwords = {
        "a", "an", "and", "by", "calendar", "data", "for", "in",
        "of", "on", "table", "the", "to", "total", "with", "year",
    }
    text_terms: list[str] = []
    year_terms: list[str] = []
    seen_text: set[str] = set()
    seen_years: set[str] = set()
    for tok in tokens:
        if tok.isdigit() and len(tok) == 4:
            if tok not in seen_years:
                seen_years.add(tok)
                year_terms.append(tok)
            continue
        if len(tok) < 3 or tok in stopwords or tok in seen_text:
            continue
        seen_text.add(tok)
        text_terms.append(tok)
    return text_terms, year_terms


def _query_match_terms(query: str) -> list[str]:
    normalized = _normalize_text(query)
    tokens = _informative_profile_tokens(normalized)
    return [
        t for t in _stable_unique([
            *_detect_entity_terms(normalized),
            *_phrase_windows(tokens, min_size=2, max_size=3),
            *tokens,
        ])
        if t
    ]


# --- Table family classification ---


def _canonicalize_row_label(label: str) -> dict[str, str]:
    raw = str(label or "").strip()
    normalized = _strip_row_label_noise(raw)
    out = {"raw_label": raw, "normalized_label": normalized, "time_prefix": "", "series_core": "", "row_role": "series"}
    if not normalized:
        out["row_role"] = "empty"
        return out
    if normalized in _GENERIC_ROW_LABEL_PHRASES:
        out["row_role"] = "generic"
        return out
    if normalized.startswith("calendar year") or normalized.startswith("calendar yr"):
        out["row_role"] = "calendar_marker"
        return out
    if re.fullmatch(r"(?:19|20)\d{2}", normalized):
        out["time_prefix"] = normalized
        out["row_role"] = "year_marker"
        return out
    if re.fullmatch(rf"{_MONTH_LABEL_PATTERN}\.?", normalized):
        out["time_prefix"] = normalized.rstrip(".")
        out["row_role"] = "month_marker"
        return out
    if normalized in {"total", "totals", "grand total", "net total", "subtotal", "subtotals"}:
        out["row_role"] = "total"
        return out
    year_prefixed = re.match(rf"^((?:19|20)\d{{2}})(?:\s*[-/]\s*|\s+)(.+)$", normalized)
    if year_prefixed:
        out["time_prefix"] = year_prefixed.group(1)
        tail = year_prefixed.group(2).strip(" .-/:;,")
        if re.fullmatch(rf"{_MONTH_LABEL_PATTERN}\.?", tail):
            out["row_role"] = "year_month_marker"
            return out
        if tail and tail not in _GENERIC_ROW_LABEL_PHRASES:
            out["series_core"] = tail
            out["row_role"] = "series_with_time_prefix"
            return out
        out["row_role"] = "year_marker"
        return out
    if normalized.startswith("end of "):
        out["row_role"] = "structural"
        return out
    out["series_core"] = normalized
    return out


def _strip_row_label_noise(value: str) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    text = re.sub(r"\s+\d+/\s*$", "", text)
    text = re.sub(r"(?:\s+|[-/])(?:p|r|e)\.?$", "", text)
    text = re.sub(r"[.\-:,;/]+$", "", text).strip()
    return re.sub(r"\s+", " ", text)


def _coarse_table_family(*, title: str, row_labels: list[str], data_category: str) -> str:
    label_hay: list[str] = []
    for lb in row_labels:
        c = _canonicalize_row_label(lb)
        label_hay.append(c["series_core"] or c["normalized_label"] or "")
    title_norm = _normalize_text(title)
    hay = " ".join([title_norm, *label_hay]).strip()
    if any(t in title_norm for t in ("cash income and outgo", "cash income", "cash outgo", "cash budget")):
        return "cash_flow"
    if any(t in title_norm for t in ("budget receipts and expenditures", "total budget receipts and expenditures", "budget expenditures", "major classifications")):
        return "budget_expenditures"
    if any(t in title_norm for t in ("national defense", "defense and related activities", "war activities")):
        return "defense_expenditures"
    if "public debt" in hay or "interest on the public debt" in hay:
        return "public_debt"
    if any(t in hay for t in ("internal revenue", "income taxes", "excise taxes", "customs")):
        return "revenue_receipts"
    if any(t in hay for t in ("budget expenditures", "outlays", "major functions", "expenditures")):
        return "budget_expenditures"
    if data_category == "budget":
        return "budget_expenditures"
    if data_category == "tax_revenue":
        return "revenue_receipts"
    if data_category == "public_debt":
        return "public_debt"
    return str(data_category or "other").strip() or "other"


def _query_table_family(query: str) -> str:
    return _coarse_table_family(title=query, row_labels=[], data_category="")


def _query_intent(query: str) -> dict[str, bool]:
    tokens = set(re.findall(r"[a-z0-9]+", _normalize_text(query)))
    return {
        "wants_budget": "budget" in tokens,
        "wants_expenditures": "expenditures" in tokens or "outlays" in tokens,
        "wants_receipts": "receipts" in tokens or "revenue" in tokens,
        "wants_cash": "cash" in tokens or "outgo" in tokens or "income" in tokens,
        "wants_debt": "debt" in tokens or "securities" in tokens,
        "wants_national_defense": {"national", "defense"} <= tokens,
    }


def _family_alignment_tier(*, query: str, family: str, table_title: str = "") -> tuple[int, str]:
    intent = _query_intent(query)
    nf = _normalize_text(family)
    tn = _normalize_text(table_title)
    wants_spending = bool(intent["wants_budget"] or intent["wants_expenditures"] or intent["wants_national_defense"])
    if any(t in tn for t in ("cash income and outgo", "cash income", "cash outgo", "cash budget")):
        nf = "cash_flow"
    elif any(t in tn for t in ("public debt", "securities")):
        nf = "public_debt"
    elif any(t in tn for t in ("budget expenditures", "budget receipts and expenditures")):
        nf = "budget_expenditures"
    if nf == "cash_flow":
        if wants_spending and not intent["wants_cash"]:
            return (0, "cash_flow_mismatch")
        if intent["wants_cash"]:
            return (3, "cash_flow_match")
    if nf == "revenue_receipts":
        if wants_spending and not intent["wants_receipts"]:
            return (0, "receipts_mismatch")
        if intent["wants_receipts"]:
            return (3, "receipts_match")
    if nf == "public_debt":
        if wants_spending and not intent["wants_debt"]:
            return (0, "debt_mismatch")
        if intent["wants_debt"]:
            return (3, "debt_match")
    if nf == "defense_expenditures":
        if intent["wants_national_defense"]:
            return (3, "defense_match")
        if wants_spending:
            return (2, "defense_spending_compatible")
    if nf == "budget_expenditures":
        if intent["wants_budget"] or intent["wants_expenditures"]:
            return (3, "budget_match")
        if wants_spending:
            return (2, "budget_spending_compatible")
    return (1, "unknown_or_generic")


# --- Supplemental cell-level term matching ---


def _supplement_table_pks_from_cells(
    conn: sqlite3.Connection, *, query_match_terms: list[str], source_file: str, limit: int,
) -> dict[int, dict[str, float]]:
    terms = [_normalize_text(t) for t in query_match_terms if _normalize_text(t)]
    if not terms:
        return {}

    # Prefer precomputed lookup tables (much smaller than scanning 18M cells)
    has_col_lookup = _table_exists(conn, "col_label_lookup")
    has_row_lookup = _table_exists(conn, "row_label_lookup")

    if not has_col_lookup and not has_row_lookup:
        if not _table_exists(conn, "table_first_table_cells") or not _table_exists(conn, "table_first_tables"):
            return {}

    scores: dict[int, dict[str, float]] = {}
    max_rows = max(1000, min(int(limit) * 40, 20000))

    for term in terms:
        like = f"%{term}%"
        is_phrase = len(_informative_profile_tokens(term)) >= 2

        # Search column labels
        if has_col_lookup:
            col_sql = "SELECT table_pk, col_norm FROM col_label_lookup WHERE col_norm LIKE ? LIMIT ?"
            col_params: list[Any] = [like, max_rows]
            col_rows = conn.execute(col_sql, tuple(col_params)).fetchall()
        elif _table_exists(conn, "table_first_table_cells"):
            col_sql = "SELECT DISTINCT table_pk, column_label_norm AS col_norm FROM table_first_table_cells WHERE column_label_norm LIKE ? LIMIT ?"
            col_rows = conn.execute(col_sql, (like, max_rows)).fetchall()
        else:
            col_rows = []

        for row in col_rows:
            tpk = int(row["table_pk"])
            bucket = scores.setdefault(tpk, {
                "column_phrase_score": 0.0, "row_phrase_score": 0.0,
                "column_token_score": 0.0, "row_token_score": 0.0, "matched_term_count": 0.0,
            })
            bucket["column_phrase_score" if is_phrase else "column_token_score"] += 5.0 if is_phrase else 1.5
            bucket["matched_term_count"] += 1.0

        # Search row labels
        if has_row_lookup:
            row_sql = "SELECT table_pk, row_label_norm FROM row_label_lookup WHERE row_label_norm LIKE ? LIMIT ?"
            rl_rows = conn.execute(row_sql, (like, max_rows)).fetchall()
        elif _table_exists(conn, "table_first_table_cells"):
            row_sql = "SELECT DISTINCT table_pk, row_label_norm FROM table_first_table_cells WHERE row_label_norm LIKE ? LIMIT ?"
            rl_rows = conn.execute(row_sql, (like, max_rows)).fetchall()
        else:
            rl_rows = []

        for row in rl_rows:
            tpk = int(row["table_pk"])
            bucket = scores.setdefault(tpk, {
                "column_phrase_score": 0.0, "row_phrase_score": 0.0,
                "column_token_score": 0.0, "row_token_score": 0.0, "matched_term_count": 0.0,
            })
            bucket["row_phrase_score" if is_phrase else "row_token_score"] += 3.0 if is_phrase else 1.0
            bucket["matched_term_count"] += 1.0

    return scores


# --- PK resolution helpers ---


def _resolve_table_first_pk(
    conn: sqlite3.Connection, *, table_pk: int | None = None,
    source_file: str = "", table_title: str = "",
) -> int | None:
    if table_pk is not None:
        row = conn.execute("SELECT table_pk FROM table_first_tables WHERE table_pk = ?", (int(table_pk),)).fetchone()
        return int(row["table_pk"]) if row else None
    sf = _canonical_source_file(source_file)
    tn = _normalize_text(table_title) if table_title else ""
    if sf and tn:
        exact = conn.execute(
            "SELECT table_pk FROM table_first_tables WHERE source_file = ? AND table_title_norm = ? ORDER BY table_pk LIMIT 1",
            (sf, tn),
        ).fetchone()
        if exact:
            return int(exact["table_pk"])
        contains = conn.execute(
            "SELECT table_pk FROM table_first_tables WHERE source_file = ? AND table_title_norm LIKE ? ORDER BY table_pk LIMIT 1",
            (sf, f"%{tn}%"),
        ).fetchone()
        if contains:
            return int(contains["table_pk"])
    if sf:
        row = conn.execute(
            "SELECT table_pk FROM table_first_tables WHERE source_file = ? ORDER BY table_pk LIMIT 1",
            (sf,),
        ).fetchone()
        return int(row["table_pk"]) if row else None
    return None


def _resolve_table_index_pk(
    conn: sqlite3.Connection, *, table_pk: int | None = None,
    source_file: str = "", table_title: str = "",
) -> int | None:
    if table_pk is not None:
        row = conn.execute("SELECT table_pk FROM table_index WHERE table_pk = ?", (int(table_pk),)).fetchone()
        return int(row["table_pk"]) if row else None
    sf = _canonical_source_file(source_file)
    tn = _normalize_text(table_title) if table_title else ""
    if sf and tn:
        exact = conn.execute(
            "SELECT table_pk FROM table_index WHERE source_file = ? AND table_title_norm = ? ORDER BY table_pk LIMIT 1",
            (sf, tn),
        ).fetchone()
        if exact:
            return int(exact["table_pk"])
        contains = conn.execute(
            "SELECT table_pk FROM table_index WHERE source_file = ? AND table_title_norm LIKE ? ORDER BY table_pk LIMIT 1",
            (sf, f"%{tn}%"),
        ).fetchone()
        if contains:
            return int(contains["table_pk"])
    return None


# ===========================================================================
# Public API — 7 functions for MCP tools
# ===========================================================================


def search_tables(
    conn: sqlite3.Connection,
    query: str,
    file_id: str = "",
    year_range: list[int] | tuple[int, ...] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Search the table index for tables matching *query*.

    Returns compact results: file_id, table_title, table_pk, score,
    year_range, columns_sample (top 5 column names).
    """
    logger.info("search_tables called: query=%r file_id=%r year_range=%r limit=%r", query, file_id, year_range, limit)
    warnings: list[str] = []
    normalized_source_file = _canonical_source_file(file_id)
    lim = max(1, min(int(limit), 50))

    if not _table_index_available(conn):
        # Fallback: try table_first_tables
        return _search_tables_first_fallback(conn, query, normalized_source_file, year_range, lim)

    available_columns = _table_column_names(conn, "table_index")
    max_rows = max(50, min(max(lim * 25, 250), 2000))
    where: list[str] = []
    params: list[Any] = []

    if normalized_source_file:
        where.append("source_file = ?")
        params.append(normalized_source_file)

    query_terms, query_years = _query_search_terms(query)
    query_match_terms = _query_match_terms(query)
    query_family = _query_table_family(query)
    q_lower = _normalize_text(query)

    query_requests_monthly = any(
        t in q_lower for t in (" monthly", " month", " jan", " feb", " mar", " apr", " may",
                               " jun", " jul", " aug", " sep", " oct", " nov", " dec")
    ) or q_lower.startswith("monthly ")
    query_requests_annual = "calendar year" in q_lower or "annual" in q_lower or "year end" in q_lower or q_lower.endswith(" total")
    wants_complete_year_rollup = (
        query_requests_annual
        or "all individual calendar months" in q_lower
        or "all months" in q_lower
        or ("sum" in q_lower and query_requests_monthly)
    )

    query_years_set: set[int] = {int(y) for y in query_years}
    if year_range and len(year_range) >= 2:
        for y in range(int(year_range[0]), int(year_range[1]) + 1):
            query_years_set.add(y)

    # Temporal completeness filter
    if wants_complete_year_rollup and query_years_set:
        for yr in query_years_set:
            where.append(
                "table_pk IN (SELECT table_pk FROM table_scope_index WHERE year = ? AND (scope_code = ? OR cell_count >= 12))"
            )
            params.extend([yr, str(yr)])

    # Year-range overlap filter: exclude tables whose [min_year, max_year] doesn't
    # overlap the query year range at all.  Only applied when year_range is explicit
    # (not just years extracted from query text) to avoid over-filtering.
    if year_range and len(year_range) >= 2:
        yr_lo = min(int(year_range[0]), int(year_range[1]))
        yr_hi = max(int(year_range[0]), int(year_range[1]))
        where.append(
            "(min_year IS NULL OR max_year IS NULL OR (min_year <= ? AND max_year >= ?))"
        )
        params.extend([yr_hi, yr_lo])

    searchable_columns = ["table_title_norm", "section_path", "units_line"]
    for opt in ("row_label_terms", "row_label_aliases", "entity_terms", "table_family", "distinctive_terms"):
        if opt in available_columns:
            searchable_columns.append(opt)

    # --- Term index scoring ---
    table_pk_filter: list[int] = []
    term_scores_by_pk: dict[int, dict[str, float]] = {}

    if query_match_terms and _table_term_index_available(conn):
        year_overlap_selects: list[str] = []
        year_overlap_params: list[Any] = []
        for yr in query_years_set:
            year_overlap_selects.append(
                "MAX(CASE WHEN ti.min_year IS NOT NULL AND ti.max_year IS NOT NULL AND ? BETWEEN ti.min_year AND ti.max_year THEN 1 ELSE 0 END)"
            )
            year_overlap_params.append(int(yr))
        source_year_selects: list[str] = []
        source_year_params: list[Any] = []
        for yr_str in query_years:
            source_year_selects.append("MAX(CASE WHEN ti.source_file LIKE ? THEN 1 ELSE 0 END)")
            source_year_params.append(f"%{yr_str}%")

        term_where = ["tti.term_norm IN (" + ", ".join("?" for _ in query_match_terms) + ")"]
        term_params: list[Any] = list(query_match_terms)
        if normalized_source_file:
            term_where.append("ti.source_file = ?")
            term_params.append(normalized_source_file)

        yo_sql = " + ".join(year_overlap_selects) if year_overlap_selects else "0"
        sy_sql = " + ".join(source_year_selects) if source_year_selects else "0"

        term_rows = conn.execute(
            f"""
            SELECT ti.table_pk AS table_pk,
                   ({yo_sql}) AS year_overlap_score,
                   ({sy_sql}) AS source_year_score,
                   SUM(CASE WHEN tti.term_type = 'entity_phrase' THEN tti.weight ELSE 0 END) AS entity_score,
                   SUM(CASE WHEN tti.term_type = 'series_core' THEN tti.weight ELSE 0 END) AS series_score,
                   SUM(CASE WHEN tti.term_type = 'header_phrase' THEN tti.weight ELSE 0 END) AS header_score,
                   SUM(CASE WHEN tti.term_type = 'family' THEN tti.weight ELSE 0 END) AS family_score,
                   SUM(CASE WHEN tti.term_type IN ('row_label_phrase','alias_phrase') THEN tti.weight ELSE 0 END) AS phrase_score,
                   SUM(CASE WHEN tti.term_type = 'row_label_token' THEN tti.weight ELSE 0 END) AS token_score,
                   COUNT(*) AS matched_term_count
            FROM table_term_index tti
            JOIN table_index ti ON ti.table_pk = tti.table_pk
            WHERE {' AND '.join(term_where)}
            GROUP BY ti.table_pk
            ORDER BY year_overlap_score DESC, source_year_score DESC, entity_score DESC, series_score DESC, phrase_score DESC, token_score DESC
            LIMIT ?
            """,
            tuple(year_overlap_params + source_year_params + term_params + [max_rows]),
        ).fetchall()

        term_scores_by_pk = {
            int(r["table_pk"]): {
                "year_overlap_score": float(r["year_overlap_score"] or 0),
                "source_year_score": float(r["source_year_score"] or 0),
                "entity_score": float(r["entity_score"] or 0),
                "series_score": float(r["series_score"] or 0),
                "header_score": float(r["header_score"] or 0),
                "family_score": float(r["family_score"] or 0),
                "phrase_score": float(r["phrase_score"] or 0),
                "token_score": float(r["token_score"] or 0),
                "matched_term_count": float(r["matched_term_count"] or 0),
            }
            for r in term_rows
        }

        # NOTE: Cell-level supplement removed for speed.
        # The term_index already includes column names as alias_phrases.

        if term_scores_by_pk:
            ranked = sorted(
                term_scores_by_pk,
                key=lambda pk: (
                    float(term_scores_by_pk[pk].get("year_overlap_score") or 0),
                    float(term_scores_by_pk[pk].get("source_year_score") or 0),
                    float(term_scores_by_pk[pk].get("entity_score") or 0) + float(term_scores_by_pk[pk].get("column_phrase_score") or 0),
                    float(term_scores_by_pk[pk].get("series_score") or 0) + float(term_scores_by_pk[pk].get("row_phrase_score") or 0),
                    float(term_scores_by_pk[pk].get("phrase_score") or 0) + float(term_scores_by_pk[pk].get("row_token_score") or 0),
                    float(term_scores_by_pk[pk].get("token_score") or 0) + float(term_scores_by_pk[pk].get("column_token_score") or 0),
                ),
                reverse=True,
            )
            table_pk_filter = ranked[:max_rows]

    if table_pk_filter:
        where.append("table_pk IN (" + ", ".join("?" for _ in table_pk_filter) + ")")
        params.extend(table_pk_filter)
    elif query_terms:
        # OR-based matching: find tables matching ANY query term, then rank by match count.
        # Old AND logic required ALL terms → failed for multi-word queries like
        # "receipts expenditures surplus deficit" where no single table has all 4 in its title.
        or_parts: list[str] = []
        for term in query_terms:
            or_parts.append("(" + " OR ".join(f"{col} LIKE ?" for col in searchable_columns) + ")")
            params.extend(f"%{term}%" for _ in searchable_columns)
        where.append("(" + " OR ".join(or_parts) + ")")

    # Build column list with optional columns
    selected_columns = [
        "table_pk", "source_file", "table_group_id", "table_id", "table_title",
        "section_path", "units_line", "table_type", "data_category", "frequency",
        "has_revisions", "period_basis", "revision_status", "temporal_granularity",
        "has_month_rows", "has_calendar_year_total",
        "row_count", "column_count", "cell_count", "numeric_cell_count",
        ("scope_count" if "scope_count" in available_columns else "0 AS scope_count"),
        ("monthly_scope_count" if "monthly_scope_count" in available_columns else "0 AS monthly_scope_count"),
        ("annual_scope_count" if "annual_scope_count" in available_columns else "0 AS annual_scope_count"),
        "min_year", "max_year", "page",
        ("row_label_terms" if "row_label_terms" in available_columns else "'[]' AS row_label_terms"),
        ("row_label_aliases" if "row_label_aliases" in available_columns else "'[]' AS row_label_aliases"),
        ("entity_terms" if "entity_terms" in available_columns else "'[]' AS entity_terms"),
        ("table_family" if "table_family" in available_columns else "'other' AS table_family"),
        ("distinctive_terms" if "distinctive_terms" in available_columns else "'[]' AS distinctive_terms"),
        ("series_labels_sample" if "series_labels_sample" in available_columns else "'[]' AS series_labels_sample"),
    ]

    # Build a match-score expression: count how many query terms match (for OR-based search ranking)
    score_expr = "0"
    score_params: list[Any] = []
    if query_terms and not table_pk_filter:
        score_parts: list[str] = []
        for term in query_terms:
            case_expr = "CASE WHEN " + " OR ".join(f"{col} LIKE ?" for col in searchable_columns) + " THEN 1 ELSE 0 END"
            score_parts.append(case_expr)
            score_params.extend(f"%{term}%" for _ in searchable_columns)
        score_expr = " + ".join(score_parts)

    sql = "SELECT " + ", ".join(selected_columns) + f", ({score_expr}) AS _match_score FROM table_index"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY _match_score DESC, source_file DESC, table_pk LIMIT ?"
    # Merge params: score params (in SELECT) come before WHERE params
    all_params = score_params + params + [max_rows]

    rows = conn.execute(sql, tuple(all_params)).fetchall()

    # Supplement from source_file if needed
    if rows and normalized_source_file and len(rows) < max_rows:
        seen_pks = {int(r["table_pk"]) for r in rows}
        supp_rows = conn.execute(
            "SELECT " + ", ".join(selected_columns) + " FROM table_index WHERE source_file = ? ORDER BY table_title, table_pk LIMIT ?",
            (normalized_source_file, max_rows),
        ).fetchall()
        for r in supp_rows:
            if int(r["table_pk"]) not in seen_pks:
                rows.append(r)
                seen_pks.add(int(r["table_pk"]))
                if len(rows) >= max_rows:
                    break

    if not rows and normalized_source_file and query_terms:
        rows = conn.execute(
            "SELECT " + ", ".join(selected_columns) + " FROM table_index WHERE source_file = ? ORDER BY table_title, table_pk LIMIT ?",
            (normalized_source_file, max_rows),
        ).fetchall()

    # --- Lightweight scoring and candidate building ---
    candidates: list[dict[str, Any]] = []
    if rows:
        table_pks = [int(r["table_pk"]) for r in rows]
        ph = ", ".join("?" for _ in table_pks)

        # Fetch column labels for all candidates in one query
        col_labels_by_pk: dict[int, list[str]] = {}
        if _table_exists(conn, "col_label_lookup"):
            col_rows = conn.execute(
                f"SELECT table_pk, column_label FROM col_label_lookup WHERE table_pk IN ({ph})",
                tuple(table_pks),
            ).fetchall()
            for cr in col_rows:
                col_labels_by_pk.setdefault(int(cr["table_pk"]), []).append(str(cr["column_label"]))
        elif _table_exists(conn, "table_first_table_cells"):
            col_rows = conn.execute(
                f"SELECT DISTINCT table_pk, column_label FROM table_first_table_cells WHERE table_pk IN ({ph}) AND column_label != ''",
                tuple(table_pks),
            ).fetchall()
            for cr in col_rows:
                col_labels_by_pk.setdefault(int(cr["table_pk"]), []).append(str(cr["column_label"]))

        # Fetch monthly coverage info per year
        monthly_months_by_pk: dict[int, dict[int, int]] = {}  # pk -> {year: month_count}
        scope_rows = conn.execute(
            f"SELECT table_pk, year, month FROM table_scope_index WHERE table_pk IN ({ph}) AND month IS NOT NULL",
            tuple(table_pks),
        ).fetchall()
        for sr in scope_rows:
            tpk = int(sr["table_pk"])
            yr = int(sr["year"]) if sr["year"] is not None else None
            if yr is not None:
                monthly_months_by_pk.setdefault(tpk, {}).setdefault(yr, 0)
                monthly_months_by_pk[tpk][yr] += 1

        for row in rows:
            tpk = int(row["table_pk"])
            title = str(row["table_title"] or "")
            title_lower = title.lower()
            mn = int(row["min_year"]) if row["min_year"] is not None else None
            mx = int(row["max_year"]) if row["max_year"] is not None else None
            has_month_rows = bool(int(row["has_month_rows"] or 0))
            period_basis = str(row["period_basis"] or "unknown") if "period_basis" in available_columns else "unknown"
            issue_year, issue_month = _parse_source_year_month(str(row["source_file"] or ""))

            # Hard reject: year range mismatch
            if query_years_set and mn is not None and mx is not None:
                if not any(mn <= yr <= mx for yr in query_years_set):
                    continue

            # --- Simple transparent scoring ---
            score = 0.0
            match_signals: list[str] = []
            term_scores = term_scores_by_pk.get(tpk, {})

            # 1. Title/keyword match (3 pts per matching term)
            title_hits = sum(1 for t in query_terms if t in title_lower)
            score += 3.0 * title_hits
            if title_hits:
                match_signals.append(f"title:{title_hits}_terms")

            # 2. Entity match (10 pts — strong signal)
            entity_terms = _json_list(row["entity_terms"])
            entity_hits = sum(1 for p in entity_terms if p and p in q_lower)
            score += 10.0 * entity_hits
            if entity_hits:
                match_signals.append("entity_match")

            # 3. Column match (8 pts — metric might be a column)
            cols = col_labels_by_pk.get(tpk, [])
            col_hits = sum(1 for t in query_terms if any(t in c.lower() for c in cols))
            score += 8.0 * col_hits
            if col_hits:
                match_signals.append(f"column:{col_hits}_terms")

            # 4. Year coverage (4 pts per matching year)
            year_hits = 0
            if query_years_set and mn is not None and mx is not None:
                year_hits = sum(1 for yr in query_years_set if mn <= yr <= mx)
            score += 4.0 * year_hits
            if year_hits:
                match_signals.append(f"year:{year_hits}_hits")

            # 5. Monthly data bonus (6 pts if query needs monthly and table has it)
            monthly_coverage = monthly_months_by_pk.get(tpk, {})
            monthly_years_for_query = sum(1 for yr in query_years_set if monthly_coverage.get(yr, 0) >= 6) if query_years_set else 0
            if query_requests_monthly and has_month_rows:
                score += 6.0
                match_signals.append("has_monthly")
                if monthly_years_for_query:
                    score += 12.0 * monthly_years_for_query
                    match_signals.append(f"monthly_years:{monthly_years_for_query}")

            # 6. Bulletin proximity scoring
            if query_years and issue_year is not None:
                best_proximity = None
                for target_year_str in query_years:
                    target_year = int(target_year_str)
                    # Y+1 Jan-Mar bulletins contain final annual data → strongest boost
                    if issue_year == target_year + 1 and issue_month is not None and issue_month <= 3:
                        score += 15.0
                        match_signals.append("y+1_bulletin")
                        best_proximity = 0
                        break
                    dist = abs(issue_year - target_year)
                    if best_proximity is None or dist < best_proximity:
                        best_proximity = dist
                if best_proximity is not None and best_proximity > 0:
                    # Same-year bulletin: +8, 1 year away: +4, 2+ years: penalty
                    if best_proximity == 0:
                        score += 8.0
                        match_signals.append("same_year_bulletin")
                    elif best_proximity == 1:
                        score += 4.0
                        match_signals.append("adjacent_year_bulletin")
                    elif best_proximity >= 3:
                        penalty = min(best_proximity * 3.0, 20.0)
                        score -= penalty
                        match_signals.append(f"distant_bulletin:-{penalty:.0f}")

            # 7. Term index score (already computed by SQL, add directly)
            term_total = sum(float(v) for v in term_scores.values())
            score += term_total
            if term_total > 5:
                match_signals.append(f"term_index:{term_total:.0f}")

            # 8. Family alignment
            family = _coarse_table_family(title=title, row_labels=[], data_category=str(row["data_category"] or ""))
            if query_family != "other" and family == query_family:
                score += 5.0
                match_signals.append(f"family:{family}")

            col_sample = _stable_unique(cols, limit=5)
            # Include units from table_index for early confidence
            units_line = str(row["units_line"] or "").strip() if "units_line" in available_columns else ""
            
            reason_parts = []
            if title_hits: reason_parts.append(f"title matched {title_hits} terms")
            if col_hits: reason_parts.append(f"columns matched {col_hits} terms")
            if entity_hits: reason_parts.append("entity match")
            
            cand: dict[str, Any] = {
                "table_id": f"tbl_{tpk}",
                "table_pk": tpk,
                "title": title,
                "doc": str(row["source_file"]),
                "year_coverage": [mn, mx],
                "granularity": "monthly" if has_month_rows else "annual",
                "unit": units_line,
                "match_score": round(score, 2),
                "reason": ", ".join(reason_parts) if reason_parts else "fuzzy/term match"
            }
            candidates.append(cand)

        candidates.sort(key=lambda c: c["match_score"], reverse=True)
        candidates = candidates[:lim]

    if not candidates:
        warnings.append("0 results returned. Try broader query terms or remove file_id filter.")
    logger.info("search_tables returning %d candidates, %d warnings", len(candidates), len(warnings))
    return {
        "candidates": candidates,
        "count": len(candidates),
        "warnings": warnings,
        "source": "ingestion_db",
    }


def _search_tables_first_fallback(
    conn: sqlite3.Connection, query: str, source_file: str,
    year_range: list[int] | tuple[int, ...] | None, limit: int,
) -> dict[str, Any]:
    """Fallback search using table_first_tables when table_index is absent."""
    if not _table_first_available(conn):
        return {"candidates": [], "count": 0, "warnings": ["table_first_tables not available"], "source": "empty_db"}

    available = _table_column_names(conn, "table_first_tables")
    query_terms, query_years = _query_search_terms(query)
    where: list[str] = []
    params: list[Any] = []
    if source_file:
        where.append("source_file = ?")
        params.append(source_file)
    searchable_cols = ["table_title_norm", "section_path", "units_line"]
    for opt in ("row_label_terms", "row_label_aliases", "entity_terms"):
        if opt in available:
            searchable_cols.append(opt)
    if query_terms:
        for term in query_terms:
            where.append("(" + " OR ".join(f"{c} LIKE ?" for c in searchable_cols) + ")")
            params.extend(f"%{term}%" for _ in searchable_cols)

    # Year-range overlap filter (when min_year/max_year columns exist)
    if year_range and len(year_range) >= 2 and "min_year" in available and "max_year" in available:
        yr_lo = min(int(year_range[0]), int(year_range[1]))
        yr_hi = max(int(year_range[0]), int(year_range[1]))
        where.append(
            "(min_year IS NULL OR max_year IS NULL OR (min_year <= ? AND max_year >= ?))"
        )
        params.extend([yr_hi, yr_lo])

    cols = [
        "table_pk", "source_file", "table_title",
        ("row_count" if "row_count" in available else "0 AS row_count"),
        ("column_count" if "column_count" in available else "0 AS column_count"),
    ]
    sql = "SELECT " + ", ".join(cols) + " FROM table_first_tables"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY source_file, table_title LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, tuple(params)).fetchall()
    fallback_warnings: list[str] = []
    if not rows:
        fallback_warnings.append("0 results returned. Try broader query terms or remove file_id filter.")
    return {
        "candidates": [
            {
                "file_id": str(r["source_file"]),
                "table_title": str(r["table_title"]),
                "table_pk": int(r["table_pk"]),
                "score": 0.0,
                "year_range": [None, None],
                "columns_sample": [],
            }
            for r in rows
        ],
        "count": len(rows),
        "warnings": fallback_warnings,
        "source": "table_first_fallback",
    }


def query_table_rows(
    conn: sqlite3.Connection,
    *,
    table_pk: int | None = None,
    file_id: str = "",
    table_title: str = "",
    row_label: str = "",
    column_label: str = "",
    year: int | None = None,
    year_range: list[int] | tuple[int, ...] | None = None,
    month: int | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Fetch cell data from table_first_table_cells.

    Returns a ``table_info`` dict (table_pk, table_title, source_file, units)
    plus compact ``rows`` with: row_label, column_label, value_raw,
    normalized_value, year, month, time_scope.
    Accepts year_range=[start, end] to filter by a year span.
    """
    logger.info(
        "query_table_rows called: table_pk=%r file_id=%r table_title=%r "
        "row_label=%r column_label=%r year=%r year_range=%r month=%r limit=%r",
        table_pk, file_id, table_title, row_label, column_label, year, year_range, month, limit,
    )
    warnings: list[str] = []

    if not _table_first_available(conn):
        return {"rows": [], "count": 0, "warnings": [], "error": "table_first_tables not available"}

    sf = _canonical_source_file(file_id)
    resolved_pk = _resolve_table_first_pk(conn, table_pk=table_pk, source_file=sf, table_title=table_title)
    if resolved_pk is None:
        return {"rows": [], "count": 0, "warnings": [], "error": "table_not_found"}

    # Look up table-level metadata for grounding fields
    _tbl_row = conn.execute(
        "SELECT source_file, table_title FROM table_first_tables WHERE table_pk = ?",
        (resolved_pk,),
    ).fetchone()
    tbl_source_file = str(_tbl_row["source_file"]) if _tbl_row else ""
    tbl_table_title = str(_tbl_row["table_title"]) if _tbl_row else ""

    # Resolve actual units from table metadata (units_line in table_index)
    tbl_units = ""
    if _table_index_available(conn):
        _idx_row = conn.execute(
            "SELECT units_line FROM table_index WHERE table_pk = ?",
            (resolved_pk,),
        ).fetchone()
        if _idx_row and _idx_row["units_line"]:
            tbl_units = str(_idx_row["units_line"]).strip()
    # Fallback: check table_first_tables for units_line if available
    if not tbl_units and _tbl_row:
        tft_cols = _table_column_names(conn, "table_first_tables")
        if "units_line" in tft_cols:
            _u_row = conn.execute(
                "SELECT units_line FROM table_first_tables WHERE table_pk = ?",
                (resolved_pk,),
            ).fetchone()
            if _u_row and _u_row["units_line"]:
                tbl_units = str(_u_row["units_line"]).strip()

    lim = max(1, min(int(limit), 200))

    # -- Pre-compute filter values (used by both blob and SQL paths, and by diagnostics) --
    rl_norm = _normalize_text(row_label) if row_label else ""
    cl_norm = _normalize_text(column_label) if column_label else ""
    year_values: list[int] = []
    if year is not None:
        year_values.append(int(year))
    if year_range and len(year_range) >= 2:
        yr_start, yr_end = min(year_range[0], year_range[1]), max(year_range[0], year_range[1])
        if int(year_range[0]) > int(year_range[1]):
            warnings.append(f"year_range was reversed, using [{yr_start}, {yr_end}]")
        for y in range(int(yr_start), int(yr_end) + 1):
            if y not in year_values:
                year_values.append(y)

    # -- Determine unit scale from units_line (needed for both paths) --
    unit_scale: int = 1
    unit_scale_label: str = "units"
    if tbl_units:
        _ul = tbl_units.lower()
        if "thousand" in _ul:
            unit_scale = 1_000
            unit_scale_label = "thousands"
        elif "billion" in _ul:
            unit_scale = 1_000_000_000
            unit_scale_label = "billions"
        elif "million" in _ul or "in million" in _ul:
            unit_scale = 1_000_000
            unit_scale_label = "millions"

    # ---- Blob-first path: use compressed cell blobs when available ----
    blob_match_info: dict[str, Any] = {}
    cl_match_type = ""
    rl_match_type = ""
    rl_exact_attempted = False
    _use_blobs = cell_blobs.blob_table_available(conn)
    if _use_blobs:
        yr_tuple = None
        if year_range and len(year_range) >= 2:
            yr_tuple = (int(year_range[0]), int(year_range[1]))
        elif year is not None:
            yr_tuple = (int(year), int(year))

        blob_rows, blob_warnings, blob_match_info = cell_blobs.query_cells(
            conn, resolved_pk,
            row_label=row_label, column_label=column_label,
            year=year, year_range=yr_tuple, month=month, limit=lim,
        )
        warnings.extend(blob_warnings)

        # Add scaled values
        compact: list[dict[str, Any]] = []
        for r in blob_rows:
            nv = r.get("normalized_value")
            row_out = dict(r)
            if unit_scale > 1 and nv is not None:
                row_out["value_scaled"] = nv * unit_scale
                row_out["unit_scale"] = unit_scale
            compact.append(row_out)

        rl_match_type = blob_match_info.get("row_match_mode", "")
        rl_exact_attempted = rl_match_type == "exact"

    else:
        # ---- Fallback: SQL path against table_first_table_cells ----
        sql = """
            SELECT row_ordinal, row_label, row_label_norm, column_label, time_scope, year, month,
                   value_raw, normalized_value, row_type, provenance_snippet
            FROM table_first_table_cells
            WHERE table_pk = ?
        """
        params: list[Any] = [resolved_pk]

        # -- row_label filter: try exact first, fall back to LIKE --
        rl_match_type = ""
        rl_exact_attempted = False
        if rl_norm:
            exact_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM table_first_table_cells WHERE table_pk = ? AND row_label_norm = ?",
                (resolved_pk, rl_norm),
            ).fetchone()
            if int(exact_count["cnt"]) > 0:
                sql += " AND row_label_norm = ?"
                params.append(rl_norm)
                rl_match_type = "exact"
                rl_exact_attempted = True
            else:
                sql += " AND row_label_norm LIKE ?"
                params.append(f"%{rl_norm}%")
                rl_match_type = "fuzzy"
                warnings.append(f"row_label '{row_label}' matched via fuzzy LIKE, not exact match")

        cl_match_type = ""
        if cl_norm:
            cl_exact_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM table_first_table_cells WHERE table_pk = ? AND column_label_norm = ?",
                (resolved_pk, cl_norm),
            ).fetchone()
            if int(cl_exact_count["cnt"]) > 0:
                sql += " AND column_label_norm = ?"
                params.append(cl_norm)
                cl_match_type = "exact"
            else:
                sql += " AND column_label_norm LIKE ?"
                params.append(f"%{cl_norm}%")
                cl_match_type = "fuzzy"
                warnings.append(f"column_label '{column_label}' matched via fuzzy LIKE, not exact match")

        if year_values:
            scope_filter = _normalize_required_scopes([str(y) for y in year_values])
            scope_clauses: list[str] = []
            ph = ", ".join("?" for _ in scope_filter)
            scope_clauses.append(f"time_scope IN ({ph})")
            params.extend(scope_filter)
            ann_years = _annual_scope_years(scope_filter)
            if ann_years:
                ph2 = ", ".join("?" for _ in ann_years)
                scope_clauses.append(f"year IN ({ph2})")
                params.extend(ann_years)
            sql += " AND (" + " OR ".join(scope_clauses) + ")"

        if month is not None:
            sql += " AND month = ?"
            params.append(int(month))

        sql += " ORDER BY row_ordinal, column_label LIMIT ?"
        params.append(lim)

        rows = conn.execute(sql, tuple(params)).fetchall()

        compact = []
        for r in rows:
            nv_raw = r["normalized_value"]
            try:
                nv = float(nv_raw) if nv_raw is not None else None
            except (TypeError, ValueError):
                nv = None
            row_out: dict[str, Any] = {
                "row_label": str(r["row_label"]),
                "column_label": str(r["column_label"]),
                "value_raw": str(r["value_raw"] or ""),
                "normalized_value": nv,
                "year": int(r["year"]) if r["year"] is not None else None,
                "month": int(r["month"]) if r["month"] is not None else None,
                "time_scope": str(r["time_scope"] or ""),
            }
            if unit_scale > 1 and nv is not None:
                row_out["value_scaled"] = nv * unit_scale
                row_out["unit_scale"] = unit_scale
            compact.append(row_out)

    if not compact:
        warnings.append("0 rows returned. IMMEDIATELY retry without filters: query_table_rows(table_pk=...) with NO year, month, row_label, or column_label.")

    # Detect incomplete monthly coverage per year
    if compact and year_values:
        months_by_year: dict[int, set[int]] = {}
        for row in compact:
            ry = row.get("year")
            rm = row.get("month")
            if ry is not None and rm is not None:
                months_by_year.setdefault(ry, set()).add(rm)
        for yr, months in months_by_year.items():
            if 1 <= len(months) < 12:
                missing = sorted(set(range(1, 13)) - months)
                _month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                missing_names = [_month_names[m - 1] for m in missing]
                warnings.append(
                    f"Only {len(months)}/12 months returned for {yr} "
                    f"(missing: {', '.join(missing_names)}). "
                    f"Try get_file_structure on bulletin {yr + 1}_01 for complete data."
                )

    logger.info("query_table_rows returning %d rows, %d warnings", len(compact), len(warnings))
    table_info: dict[str, Any] = {
        "table_pk": resolved_pk,
        "table_title": tbl_table_title,
        "source_file": tbl_source_file,
    }
    if tbl_units:
        table_info["units"] = tbl_units
        table_info["unit_scale"] = unit_scale
        table_info["unit_scale_label"] = unit_scale_label
        # Make unit info impossible to miss — add a warning if values need scaling
        if unit_scale > 1:
            warnings.append(
                f"⚠ UNITS: Values are in {unit_scale_label.upper()}. "
                f"Each row includes value_scaled = normalized_value × {unit_scale:,}. "
                f"Use value_scaled when the question asks for nominal/actual dollars."
            )

    # -- Match diagnostics --
    if _use_blobs:
        match_info = dict(blob_match_info)
    else:
        match_info = {}
        if rl_norm:
            match_info["row_match_mode"] = "exact" if (rl_exact_attempted and rl_match_type == "exact") else "fuzzy"
            if compact:
                match_info["matched_row_labels"] = sorted({r["row_label"] for r in compact})[:10]
        if cl_norm:
            match_info["column_match_mode"] = cl_match_type
            if compact:
                match_info["matched_column_labels"] = sorted({r["column_label"] for r in compact})[:10]

    result: dict[str, Any] = {
        "table_info": table_info,
        "rows": compact,
        "count": len(compact),
        "warnings": warnings,
        "was_truncated": len(compact) >= lim,
    }
    if match_info:
        result["match_info"] = match_info

    # -- Suggest relaxation on empty results --
    if not compact:
        filters_used = []
        if rl_norm:
            filters_used.append(f"row_label='{row_label}'")
        if cl_norm:
            filters_used.append(f"column_label='{column_label}'")
        if year_values:
            filters_used.append(f"year(s)={year_values}")
        if month is not None:
            filters_used.append(f"month={month}")
        relaxation_order = []
        if month is not None:
            relaxation_order.append("drop month")
        if cl_norm:
            relaxation_order.append("drop column_label")
        if rl_norm:
            relaxation_order.append("drop row_label")
        if year_values:
            relaxation_order.append("widen year_range or drop year")
        result["suggest_relaxation"] = {
            "filters_used": filters_used,
            "try_dropping_in_order": relaxation_order,
            "hint": f"Try: query_table_rows(table_pk={resolved_pk}) with no filters first, then add back one filter at a time.",
        }

    return result


def get_file_structure(conn: sqlite3.Connection, file_id: str) -> dict[str, Any]:
    """List all tables in a bulletin file by file_id."""
    sf = _canonical_source_file(file_id)
    if not sf:
        return {"error": "invalid_file_id", "file_id": file_id, "tables": []}

    tables: list[dict[str, Any]] = []

    # Try table_index first (richer metadata)
    if _table_index_available(conn):
        available = _table_column_names(conn, "table_index")
        cols = ["table_pk", "table_title", "table_type", "data_category", "row_count", "column_count", "min_year", "max_year", "page"]
        cols = [c for c in cols if c in available or c in ("table_pk", "table_title")]
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM table_index WHERE source_file = ? ORDER BY table_pk",
            (sf,),
        ).fetchall()
        for r in rows:
            entry: dict[str, Any] = {
                "table_pk": int(r["table_pk"]),
                "table_title": str(r["table_title"]),
            }
            if "table_type" in cols and r["table_type"]:
                entry["table_type"] = str(r["table_type"])
            if "data_category" in cols and r["data_category"]:
                entry["data_category"] = str(r["data_category"])
            if "row_count" in cols:
                entry["row_count"] = int(r["row_count"] or 0)
            if "column_count" in cols:
                entry["column_count"] = int(r["column_count"] or 0)
            if "min_year" in cols and r["min_year"] is not None:
                entry["year_range"] = [int(r["min_year"]), int(r["max_year"]) if r["max_year"] is not None else int(r["min_year"])]
            if "page" in cols and r["page"] is not None:
                entry["page"] = int(r["page"])
            tables.append(entry)

    elif _table_first_available(conn):
        rows = conn.execute(
            "SELECT table_pk, table_title, row_count, column_count FROM table_first_tables WHERE source_file = ? ORDER BY table_pk",
            (sf,),
        ).fetchall()
        for r in rows:
            tables.append({
                "table_pk": int(r["table_pk"]),
                "table_title": str(r["table_title"]),
                "row_count": int(r["row_count"] or 0),
                "column_count": int(r["column_count"] or 0),
            })

    return {
        "file_id": sf,
        "tables": tables,
        "table_count": len(tables),
    }


def get_table_profile(conn: sqlite3.Connection, table_pk: int) -> dict[str, Any]:
    """Return table columns, coverage, and metadata for a single table."""
    tpk = int(table_pk)

    # Try table_index first
    if _table_index_available(conn):
        available = _table_column_names(conn, "table_index")
        row = conn.execute("SELECT * FROM table_index WHERE table_pk = ?", (tpk,)).fetchone()
        if row is not None:
            profile: dict[str, Any] = {
                "table_pk": tpk,
                "file_id": str(row["source_file"]),
                "table_title": str(row["table_title"]),
                "table_type": str(row["table_type"] or ""),
                "data_category": str(row["data_category"] or ""),
                "frequency": str(row["frequency"] or ""),
                "period_basis": str(row["period_basis"] or "unknown") if "period_basis" in available else "unknown",
                "row_count": int(row["row_count"] or 0),
                "column_count": int(row["column_count"] or 0),
                "cell_count": int(row["cell_count"] or 0),
                "min_year": int(row["min_year"]) if row["min_year"] is not None else None,
                "max_year": int(row["max_year"]) if row["max_year"] is not None else None,
            }

            # Units (critical for correct answers)
            units_line = ""
            if "units_line" in available and row["units_line"]:
                units_line = str(row["units_line"]).strip()
            if units_line:
                profile["units"] = units_line
                ul = units_line.lower()
                if "thousand" in ul:
                    profile["unit_scale"] = 1_000
                    profile["unit_scale_label"] = "thousands"
                elif "billion" in ul:
                    profile["unit_scale"] = 1_000_000_000
                    profile["unit_scale_label"] = "billions"
                elif "million" in ul:
                    profile["unit_scale"] = 1_000_000
                    profile["unit_scale_label"] = "millions"

            # Column labels — prefer col_label_lookup, then blobs, then raw cells
            columns: list[str] = []
            if _table_exists(conn, "col_label_lookup"):
                col_rows = conn.execute(
                    "SELECT column_label FROM col_label_lookup WHERE table_pk = ? ORDER BY column_label",
                    (tpk,),
                ).fetchall()
                columns = [str(cr["column_label"]) for cr in col_rows]
            elif cell_blobs.blob_table_available(conn):
                columns = cell_blobs.get_distinct_column_labels(conn, tpk)
            elif _table_exists(conn, "table_first_table_cells"):
                col_rows = conn.execute(
                    "SELECT DISTINCT column_label FROM table_first_table_cells WHERE table_pk = ? AND column_label != '' ORDER BY column_label",
                    (tpk,),
                ).fetchall()
                columns = [str(cr["column_label"]) for cr in col_rows]
            profile["columns"] = columns

            # Duplicate column detection
            if len(columns) != len(set(c.lower().strip() for c in columns)):
                seen: dict[str, int] = {}
                dupes: list[str] = []
                for c in columns:
                    key = c.lower().strip()
                    seen[key] = seen.get(key, 0) + 1
                for k, v in seen.items():
                    if v > 1:
                        dupes.append(f"'{k}' appears {v} times")
                if dupes:
                    profile["duplicate_columns"] = dupes

            # Row label samples — prefer row_label_lookup, then blobs, then raw cells
            if _table_exists(conn, "row_label_lookup"):
                rl_rows = conn.execute(
                    "SELECT DISTINCT row_label FROM row_label_lookup WHERE table_pk = ? LIMIT 15",
                    (tpk,),
                ).fetchall()
                profile["row_label_samples"] = [str(r["row_label"]) for r in rl_rows]
            elif cell_blobs.blob_table_available(conn):
                profile["row_label_samples"] = cell_blobs.get_distinct_row_labels(conn, tpk, limit=15)
            elif _table_exists(conn, "table_first_table_cells"):
                rl_rows = conn.execute(
                    "SELECT DISTINCT row_label FROM table_first_table_cells "
                    "WHERE table_pk = ? AND row_label != '' ORDER BY row_ordinal LIMIT 15",
                    (tpk,),
                ).fetchall()
                profile["row_label_samples"] = [str(r["row_label"]) for r in rl_rows]

            # Scope coverage
            scope_rows = conn.execute(
                "SELECT scope_code, year, month, cell_count FROM table_scope_index WHERE table_pk = ?",
                (tpk,),
            ).fetchall()
            scopes = [str(sr["scope_code"]) for sr in scope_rows if sr["scope_code"]]
            years = sorted({int(sr["year"]) for sr in scope_rows if sr["year"] is not None})
            profile["scopes"] = scopes[:20]
            profile["years"] = years

            # Coverage warnings
            diagnostics: list[str] = []
            if profile.get("row_count", 0) == 0:
                diagnostics.append("Table has 0 rows — may be empty or header-only.")
            if years and (max(years) - min(years) + 1) > len(years):
                diagnostics.append(f"Gaps in year coverage: {len(years)} years out of {min(years)}-{max(years)} range.")
            if diagnostics:
                profile["diagnostics"] = diagnostics

            return profile

    # Fallback to table_first_tables
    if _table_first_available(conn):
        row = conn.execute("SELECT * FROM table_first_tables WHERE table_pk = ?", (tpk,)).fetchone()
        if row is not None:
            profile = {
                "table_pk": tpk,
                "file_id": str(row["source_file"]),
                "table_title": str(row["table_title"]),
                "row_count": int(row["row_count"] or 0),
                "column_count": int(row["column_count"] or 0),
            }
            columns = []
            if _table_exists(conn, "col_label_lookup"):
                col_rows = conn.execute(
                    "SELECT column_label FROM col_label_lookup WHERE table_pk = ? ORDER BY column_label",
                    (tpk,),
                ).fetchall()
                columns = [str(cr["column_label"]) for cr in col_rows]
            elif cell_blobs.blob_table_available(conn):
                columns = cell_blobs.get_distinct_column_labels(conn, tpk)
            elif _table_exists(conn, "table_first_table_cells"):
                col_rows = conn.execute(
                    "SELECT DISTINCT column_label FROM table_first_table_cells WHERE table_pk = ? AND column_label != '' ORDER BY column_label",
                    (tpk,),
                ).fetchall()
                columns = [str(cr["column_label"]) for cr in col_rows]
            profile["columns"] = columns

            scope_rows = conn.execute(
                "SELECT scope_code, year, month, cell_count FROM table_first_table_scopes WHERE table_pk = ?",
                (tpk,),
            ).fetchall()
            scopes = [str(sr["scope_code"]) for sr in scope_rows if sr["scope_code"]]
            years = sorted({int(sr["year"]) for sr in scope_rows if sr["year"] is not None})
            profile["scopes"] = scopes[:20]
            profile["years"] = years
            return profile

    return {"error": "table_not_found", "table_pk": tpk}


# ---------------------------------------------------------------------------
# CPI index — reads from bundled CSV, not from DB
# ---------------------------------------------------------------------------

_cpi_cache: dict[str, Any] | None = None


def get_cpi_index(
    conn: sqlite3.Connection,  # unused, kept for uniform API
    year: int,
    month: int | None = None,
    *,
    csv_path: str | Path | None = None,
) -> dict[str, Any]:
    """Look up CPI-U index for *year* (and optional *month*).

    If *csv_path* is not provided, looks for ``data/reference/cpi_series.csv``
    relative to this file's grandparent directory.
    """
    global _cpi_cache

    if csv_path is not None:
        path = Path(csv_path).expanduser().resolve()
    else:
        # Prefer monthly file (has 673 data points), fall back to annual-only
        monthly_path = Path(__file__).resolve().parents[1] / "data" / "reference" / "cpi_monthly.csv"
        annual_path = Path(__file__).resolve().parents[1] / "data" / "reference" / "cpi_series.csv"
        path = monthly_path if monthly_path.is_file() else annual_path

    rp = str(path)
    if _cpi_cache is None or _cpi_cache.get("path") != rp:
        _cpi_cache = _load_cpi_csv(path)
        # Also merge annual-only file if we loaded monthly
        if "cpi_monthly" in rp:
            annual_only = _load_cpi_csv(Path(__file__).resolve().parents[1] / "data" / "reference" / "cpi_series.csv")
            for y, v in (annual_only.get("annual") or {}).items():
                _cpi_cache["annual"].setdefault(y, v)

    annual = _cpi_cache.get("annual") or {}
    monthly = _cpi_cache.get("monthly") or {}

    if month is None or month == 0:
        idx = annual.get(int(year))
        if idx is None:
            return {
                "ok": False,
                "error": "annual_cpi_not_found",
                "year": year,
                "available_years_sample": sorted(annual.keys())[:8],
            }
        return {
            "ok": True, "year": year, "month": None, "index": idx,
            "basis": "CPI-U All Items U.S. city average; annual average (1982-84=100)",
            "source": "bundled:data/reference/cpi_series.csv",
        }

    if month < 1 or month > 12:
        return {"ok": False, "error": "month_out_of_range", "year": year, "month": month}

    key = (int(year), int(month))
    if key in monthly:
        return {
            "ok": True, "year": year, "month": month, "index": monthly[key],
            "basis": "CPI-U All Items U.S. city average; monthly (1982-84=100)",
            "source": "bundled:data/reference/cpi_series.csv",
        }

    a = annual.get(int(year))
    if a is not None:
        return {
            "ok": False, "error": "monthly_cpi_not_found", "year": year, "month": month,
            "annual_average_fallback": a,
            "hint": "No monthly row in CSV; use annual average or extend cpi_series.csv.",
        }
    return {"ok": False, "error": "cpi_not_found", "year": year, "month": month}


def _load_cpi_csv(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "error": "cpi_csv_missing", "annual": {}, "monthly": {}}
    annual: dict[int, float] = {}
    monthly: dict[tuple[int, int], float] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {"path": str(path), "error": "cpi_csv_empty", "annual": {}, "monthly": {}}
        fields = {re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_"): h for h in reader.fieldnames}
        yk = fields.get("year") or "year"
        mk = fields.get("month") or "month"
        ik = fields.get("index") or fields.get("cpi") or "index"
        for row in reader:
            try:
                y = int(str(row.get(yk, "")).strip())
            except (TypeError, ValueError):
                continue
            try:
                mo = int(str(row.get(mk, "0")).strip() or "0")
            except (TypeError, ValueError):
                mo = 0
            try:
                idx = float(str(row.get(ik, "")).replace(",", "").strip())
            except (TypeError, ValueError):
                continue
            if mo <= 0:
                annual[y] = idx
            elif 1 <= mo <= 12:
                monthly[(y, mo)] = idx
    return {"path": str(path), "error": None, "annual": annual, "monthly": monthly}


# ---------------------------------------------------------------------------
# Exchange rate lookup
# ---------------------------------------------------------------------------

_fx_cache: dict[str, Any] | None = None


def get_exchange_rate(
    conn: sqlite3.Connection,  # unused, kept for uniform API
    pair: str,
    year: int,
    month: int | None = None,
    day: int | None = None,
    *,
    csv_path: str | Path | None = None,
) -> dict[str, Any]:
    """Look up an exchange rate from the bundled reference CSV.

    *pair*: e.g. "USD/JPY", "USD/GBP", "USD/INR", "USD/DEM", "USD/CAD"
    Returns the best matching rate: spot > monthly_avg > annual_avg.
    """
    global _fx_cache

    if csv_path is not None:
        path = Path(csv_path).expanduser().resolve()
    else:
        path = Path(__file__).resolve().parents[1] / "data" / "reference" / "exchange_rates.csv"

    rp = str(path)
    if _fx_cache is None or _fx_cache.get("path") != rp:
        _fx_cache = _load_fx_csv(path)

    entries = _fx_cache.get("entries") or []
    p = str(pair).strip().upper()
    y = int(year)
    m = int(month) if month else 0
    d = int(day) if day else 0

    # Find best match: exact day > monthly > annual
    best = None
    best_score = -1
    for e in entries:
        if e["pair"] != p:
            continue
        if e["year"] != y:
            continue
        score = 0
        if d and e["day"] == d and e["month"] == m:
            score = 3  # exact day match
        elif m and e["month"] == m and e["day"] == 0:
            score = 2  # monthly match
        elif m and e["month"] == m and e["day"] > 0:
            score = 2  # daily rate in the right month
        elif e["month"] == 0:
            score = 1  # annual match
        else:
            continue
        if score > best_score:
            best_score = score
            best = e

    if best is None:
        available_pairs = sorted({e["pair"] for e in entries})
        return {
            "ok": False,
            "error": "exchange_rate_not_found",
            "pair": p, "year": y, "month": m, "day": d,
            "available_pairs": available_pairs,
            "hint": "Try a different pair or check available data.",
        }

    return {
        "ok": True,
        "pair": best["pair"],
        "year": best["year"],
        "month": best["month"] or None,
        "day": best["day"] or None,
        "rate": best["rate"],
        "type": best["type"],
        "source": best["source"],
    }


def _load_fx_csv(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "error": "fx_csv_missing", "entries": []}
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("pair,"):
                continue  # header
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
                    "source": parts[6].strip() if len(parts) > 6 else "",
                })
            except (ValueError, IndexError):
                continue
    return {"path": str(path), "error": None, "entries": entries}


# ---------------------------------------------------------------------------
# Fiscal year bounds — pure logic, no DB needed
# ---------------------------------------------------------------------------


def get_fiscal_year_bounds(year: int) -> dict[str, Any]:
    """Return the start/end dates for U.S. federal fiscal year *year*.

    U.S. fiscal years run Oct 1 of the prior calendar year through Sep 30.
    For FY 1976 and earlier, FY started Jul 1 (changed by Congressional Budget Act of 1974).
    """
    fy = int(year)
    if fy <= 0:
        return {"ok": False, "error": "invalid_fiscal_year", "fiscal_year": fy}

    if fy <= 1976:
        # Pre-1976: Jul 1 through Jun 30
        return {
            "ok": True,
            "fiscal_year": fy,
            "period_start": f"{fy - 1}-07-01",
            "period_end": f"{fy}-06-30",
            "basis": "U.S. federal fiscal year (Jul 1 - Jun 30, pre-1977)",
        }

    # Modern: Oct 1 through Sep 30
    return {
        "ok": True,
        "fiscal_year": fy,
        "period_start": f"{fy - 1}-10-01",
        "period_end": f"{fy}-09-30",
        "basis": "U.S. federal fiscal year (Oct 1 - Sep 30)",
    }
