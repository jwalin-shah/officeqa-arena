"""Tool wrapper class for OfficeQA Arena.

Each method maps 1:1 to an MCP tool, returns a compact dict, and never raises.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from server.safe_eval import safe_eval_finance
from server import db

_ROOT = Path(__file__).resolve().parent.parent


class OfficeQATools:
    """Stateful tool bag backed by a single SQLite corpus DB."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection = db.open_db(db_path)
        self.reset_budgets()
        self._label_lookup_table = ""
        self._build_label_lookup()

    def _build_label_lookup(self) -> None:
        """Ensure fast column-label lookup is available.

        Prefers the permanent ``col_label_lookup`` table (created by
        ``scripts/precompute_indexes.py``).  Falls back to building a
        permanent table in the DB if possible, or a temp table.
        """
        try:
            exists = self._conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='col_label_lookup'"
            ).fetchone()[0]
            if exists:
                self._label_lookup_table = "col_label_lookup"
                return
            # Build permanent table (will persist across MCP calls within same task)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS col_label_lookup AS
                SELECT DISTINCT table_pk, column_label,
                       LOWER(REPLACE(REPLACE(column_label, '/', ''), '.', '')) as col_norm
                FROM table_first_table_cells
                WHERE column_label != ''
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_col_lookup_norm ON col_label_lookup(col_norm)")
            self._conn.commit()
            self._label_lookup_table = "col_label_lookup"
        except Exception:
            self._label_lookup_table = ""

    def reset_budgets(self) -> None:
        """Reset per-case call counters. Call before each eval case."""
        self._grep_call_count: int = 0
        self._search_call_count: int = 0

    # ------------------------------------------------------------------
    # Retrieval tools
    # ------------------------------------------------------------------

    def search_tables(
        self,
        query: str,
        file_id: str = "",
        year_range: list[int] | None = None,
        limit: int = 10,
    ) -> dict:
        """Full-text search over table metadata. Auto-widens year range if 0 results."""
        try:
            self._search_call_count += 1
            if self._search_call_count > 2:
                return {
                    "candidates": [],
                    "count": 0,
                    "budget_exceeded": True,
                    "warning": (
                        f"search_tables called {self._search_call_count} times (budget: 2). "
                        "STOP searching. Use get_table_profile on the best table you already found, "
                        "then query_table_rows to extract data. Write your answer."
                    ),
                }
            result = db.search_tables(
                self._conn, query=query, file_id=file_id,
                year_range=year_range, limit=limit,
            )
            # Auto-widen: if 0 results and year_range was specified, retry ±3 years
            if not result.get("candidates") and year_range and len(year_range) >= 2 and not file_id:
                widened = [year_range[0] - 3, year_range[1] + 3]
                result = db.search_tables(
                    self._conn, query=query, file_id=file_id,
                    year_range=widened, limit=limit,
                )
                if result.get("candidates"):
                    result.setdefault("warnings", []).append(
                        f"No results for year_range {year_range}, widened to {widened}"
                    )
            result["search_call_number"] = self._search_call_count
            result["searches_remaining"] = max(0, 2 - self._search_call_count)
            return result
        except Exception as exc:
            return {"error": str(exc)}

    def query_table_rows(
        self,
        table_pk: int | None = None,
        file_id: str = "",
        table_title: str = "",
        row_label: str = "",
        column_label: str = "",
        year: int | None = None,
        year_range: list[int] | None = None,
        month: int | None = None,
        limit: int = 20,
    ) -> dict:
        """Fetch rows from a known table by filters."""
        try:
            return db.query_table_rows(
                self._conn, table_pk=table_pk, file_id=file_id,
                table_title=table_title, row_label=row_label,
                column_label=column_label, year=year,
                year_range=year_range, month=month, limit=limit,
            )
        except Exception as exc:
            return {"error": str(exc)}

    def get_file_structure(self, file_id: str) -> dict:
        """Return all table titles and metadata for a bulletin issue."""
        try:
            return db.get_file_structure(self._conn, file_id=file_id)
        except Exception as exc:
            return {"error": str(exc)}

    def get_table_profile(self, table_pk: int) -> dict:
        """Inspect table schema, columns, and row/year coverage."""
        try:
            return db.get_table_profile(self._conn, table_pk=table_pk)
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------

    def compute_expression(
        self,
        expression: str,
        variables: dict | None = None,
    ) -> dict:
        """Deterministic arithmetic evaluator."""
        try:
            clean_vars = {k: float(v) for k, v in (variables or {}).items()}
            result = safe_eval_finance(expression, clean_vars)
            return {"ok": True, "result": result}
        except (ValueError, SyntaxError, TypeError, ZeroDivisionError) as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Reference data
    # ------------------------------------------------------------------

    def get_cpi_index(self, year: int, month: int | None = None) -> dict:
        """CPI-U annual or monthly index value (1982-84=100)."""
        try:
            return db.get_cpi_index(self._conn, year=year, month=month)
        except Exception as exc:
            return {"error": str(exc)}

    def get_exchange_rate(
        self,
        pair: str,
        year: int,
        month: int | None = None,
        day: int | None = None,
    ) -> dict:
        """Look up a historical exchange rate (e.g. USD/JPY, USD/GBP, USD/INR, USD/DEM, USD/CAD)."""
        try:
            return db.get_exchange_rate(
                self._conn, pair=pair, year=year, month=month, day=day,
            )
        except Exception as exc:
            return {"error": str(exc)}

    def get_fiscal_year_bounds(self, fiscal_year: int) -> dict:
        """U.S. federal fiscal year start/end dates."""
        try:
            return db.get_fiscal_year_bounds(year=fiscal_year)
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Mega tools (multi-step)
    # ------------------------------------------------------------------

    def _direct_label_search(
        self,
        terms: list[str],
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search column_label and row_label directly via LIKE.

        Returns deduplicated table candidates with matching labels.
        This is the simplest, most reliable search — no scoring, no term index.
        """
        if not terms:
            return []

        # Search column labels in table_first_table_cells
        # Filter by year via source_file when we know the target year
        col_matches: dict[int, dict[str, Any]] = {}

        # Build year filter on source_file (bulletin from year Y or Y+1)
        year_file_clauses: list[str] = []
        year_file_params: list[str] = []
        if year is not None:
            # Data for year Y typically appears in bulletins from Y and Y+1
            for y in [year, year + 1]:
                year_file_clauses.append("ti.source_file LIKE ?")
                year_file_params.append(f"%{y}%")
            # Also allow tables with NULL year range (they might still be relevant)

        # Track which terms each table matched (for ranking)
        term_hits: dict[int, set[str]] = defaultdict(set)

        for term in terms:
            if len(term) < 3:
                continue

            # Use fast lookup table if available, fall back to direct scan
            try:
                tbl = self._label_lookup_table or "_col_label_lookup"
                yr_where = ""
                yr_params: list[Any] = []
                if year_file_clauses:
                    yr_where = f" AND ({' OR '.join(year_file_clauses)} OR ti.min_year IS NULL)"
                    yr_params = list(year_file_params)
                lookup_rows = self._conn.execute(
                    f"""SELECT cl.table_pk, cl.column_label,
                              ti.table_title, ti.source_file, ti.units_line,
                              ti.min_year, ti.max_year
                       FROM {tbl} cl
                       JOIN table_index ti ON ti.table_pk = cl.table_pk
                       WHERE cl.col_norm LIKE ?{yr_where}
                       LIMIT 200""",
                    (f"%{term}%", *yr_params),
                ).fetchall()
                rows = lookup_rows
            except Exception:
                # Fallback: direct scan (slow but works)
                where_parts = ["fc.column_label LIKE ?"]
                params: list[Any] = [f"%{term}%"]
                if year_file_clauses:
                    where_parts.append(f"({' OR '.join(year_file_clauses)} OR ti.min_year IS NULL)")
                    params.extend(year_file_params)
                rows = self._conn.execute(
                    f"""SELECT DISTINCT fc.table_pk, fc.column_label,
                              ti.table_title, ti.source_file, ti.units_line,
                              ti.min_year, ti.max_year
                       FROM table_first_table_cells fc
                       JOIN table_index ti ON ti.table_pk = fc.table_pk
                       WHERE {' AND '.join(where_parts)}
                       LIMIT 200""",
                    tuple(params),
                ).fetchall()
            for r in rows:
                pk = int(r["table_pk"])
                term_hits[pk].add(term)
                if pk not in col_matches:
                    col_matches[pk] = {
                        "table_pk": pk,
                        "table_title": r["table_title"],
                        "source_file": r["source_file"],
                        "units": r["units_line"] or "",
                        "year_range": [r["min_year"], r["max_year"]],
                        "matched_columns": [],
                        "matched_rows": [],
                        "match_source": "column_label",
                    }
                col_label = r["column_label"]
                if col_label not in col_matches[pk]["matched_columns"]:
                    col_matches[pk]["matched_columns"].append(col_label)

        # Search row labels in normalized_rows (only if column search found little)
        if len(col_matches) < 5:
            for term in terms:
                if len(term) < 4:
                    continue
                row_yr_where = ""
                row_yr_params: list[Any] = []
                if year_file_clauses:
                    row_yr_where = f" AND ({' OR '.join(year_file_clauses)} OR ti.min_year IS NULL)"
                    row_yr_params = list(year_file_params)
                rows = self._conn.execute(
                    f"""SELECT DISTINCT nr.table_group_id, nr.row_label,
                              ti.table_pk, ti.table_title, ti.source_file,
                              ti.units_line, ti.min_year, ti.max_year
                       FROM normalized_rows nr
                       JOIN table_index ti ON ti.table_group_id = nr.table_group_id
                       WHERE nr.row_label_norm LIKE ?{row_yr_where}
                       LIMIT 200""",
                    (f"%{term}%", *row_yr_params),
                ).fetchall()
                for r in rows:
                    pk = int(r["table_pk"])
                    term_hits[pk].add(term)
                    if pk not in col_matches:
                        col_matches[pk] = {
                            "table_pk": pk,
                            "table_title": r["table_title"],
                            "source_file": r["source_file"],
                            "units": r["units_line"] or "",
                            "year_range": [r["min_year"], r["max_year"]],
                            "matched_columns": [],
                            "matched_rows": [],
                            "match_source": "row_label",
                        }
                    row_label = r["row_label"]
                    if row_label not in col_matches[pk]["matched_rows"]:
                        col_matches[pk]["matched_rows"].append(row_label[:60])

        if not col_matches:
            return []

        # When year is provided, filter out tables that can't match:
        # - If year_range is known and doesn't cover query year → drop
        # - If year_range is NULL and source_file doesn't contain year or year+1 → drop
        if year is not None:
            filtered: dict[int, dict[str, Any]] = {}
            for pk, cand in col_matches.items():
                mn, mx = cand["year_range"]
                sf = cand.get("source_file", "")
                if mn is not None and mx is not None:
                    if mn <= year <= mx:
                        filtered[pk] = cand
                    # Also accept if source bulletin is from year or year+1
                    elif str(year) in sf or str(year + 1) in sf:
                        filtered[pk] = cand
                else:
                    # NULL year range: only keep if source file is from nearby era
                    if str(year) in sf or str(year + 1) in sf or str(year - 1) in sf:
                        filtered[pk] = cand
            col_matches = filtered

        if not col_matches:
            return []

        # Deduplicate: group by normalized table_title, keep one representative per title
        by_title: dict[str, list[dict]] = {}
        for cand in col_matches.values():
            # Normalize: strip footnote markers (1/, 2/, etc.) and trailing whitespace
            title = re.sub(r'\s*\d+/\s*', ' ', cand["table_title"]).strip()
            by_title.setdefault(title, []).append(cand)

        deduped: list[dict[str, Any]] = []
        for title, group in by_title.items():
            # Pick representative: most term hits, year coverage,
            # then bulletin closest to target year (year+1 ideal for complete data)
            def _rep_key(g: dict) -> tuple:
                hits = len(term_hits.get(g["table_pk"], set()))
                yr_ok = 1 if (year and g["year_range"][0] and g["year_range"][1]
                              and g["year_range"][0] <= year <= g["year_range"][1]) else 0
                sf = g.get("source_file", "")
                sf_match = re.search(r'(\d{4})_(\d{2})', sf)
                if sf_match and year:
                    # Prefer bulletin from year+1 (has full year data + revisions)
                    # Proximity: closer to year+1 = better
                    sf_ym = int(sf_match.group(1)) * 12 + int(sf_match.group(2))
                    target_ym = (year + 1) * 12 + 1  # Jan of year+1 is ideal
                    proximity = -abs(sf_ym - target_ym)
                else:
                    proximity = 0
                return (hits, yr_ok, proximity)
            best = max(group, key=_rep_key)

            entry = {
                "table_pk": best["table_pk"],
                "table_title": best["table_title"],
                "file_id": best["source_file"],
                "units": best["units"],
                "year_range": best["year_range"],
                "matched_columns": best["matched_columns"][:5],
                "matched_rows": best["matched_rows"][:5],
                "match_source": best["match_source"],
                "copies_across_bulletins": len(group),
                "_term_hits": len(term_hits.get(best["table_pk"], set())),
            }
            deduped.append(entry)

        # Rank by number of query terms matched (column/row hits + title hits)
        for entry in deduped:
            title_lower = entry["table_title"].lower()
            title_bonus = sum(1 for t in terms if t in title_lower)
            entry["_term_hits"] += title_bonus
        deduped.sort(key=lambda d: -d["_term_hits"])
        return deduped[:15]

    def extract_values(
        self,
        query: str,
        metric: str = "",
        year: int | None = None,
        month: int | None = None,
        top_k: int = 5,
    ) -> dict:
        """Search + fetch in one call. Finds tables matching query, fetches rows, returns compact results."""
        try:
            q = str(query or "").strip()
            if not q:
                return {"results": [], "error": "query is required"}
            m = str(metric or "").strip()
            mo = int(month) if month is not None else None
            k = max(1, min(int(top_k), 8))

            # --- Phase 1: Direct label search (simple LIKE on column/row labels) ---
            # Extract distinctive terms (3+ chars, skip stopwords)
            _stopwords = {"the", "and", "for", "was", "what", "how", "total", "value", "amount", "from", "with", "that", "this"}
            all_terms = list(dict.fromkeys(w for w in re.sub(r'[^a-z0-9\s]', '', f"{q} {m}".lower()).split() if len(w) >= 3 and w not in _stopwords))
            # Prefer longer/rarer terms first
            all_terms.sort(key=lambda t: -len(t))
            # Use top distinctive terms for direct search
            search_terms = all_terms[:5]

            direct_candidates = self._direct_label_search(search_terms, year=int(year) if year else None)

            # Boost candidates where metric matches a column label exactly
            if m:
                m_lower = m.lower()
                for cand in direct_candidates:
                    matched_cols = [c.lower() for c in cand.get("matched_columns", [])]
                    if any(m_lower in c or c in m_lower for c in matched_cols):
                        cand["_term_hits"] = cand.get("_term_hits", 0) + 3
                # Re-sort after boosting
                direct_candidates.sort(key=lambda d: -d.get("_term_hits", 0))

            # --- Phase 2: Merge direct + term-index candidates ---
            # Always run both searches, merge results, deduplicate by table_pk
            search_query = f"{q} {m}".strip() if m and m.lower() not in q.lower() else q
            yr_range = [int(year), int(year)] if year is not None else None
            saved_count = self._search_call_count
            table_result = self.search_tables(query=search_query, year_range=yr_range, limit=k * 3)
            self._search_call_count = saved_count
            term_candidates = (table_result.get("candidates") or [])[:k]

            # Merge both sources, interleaving: take 1 from each alternately,
            # then fill remaining from whichever has more.
            # Dedup by normalized title across both sources
            _fn_strip = re.compile(r'\s*\d+/\s*')
            seen_pks: set[int] = set()
            seen_titles: set[str] = set()
            candidates: list[dict] = []

            def _add_candidate(cand: dict) -> bool:
                pk = cand.get("table_pk")
                title_norm = _fn_strip.sub(' ', str(cand.get("table_title") or "")).strip().lower()
                if pk in seen_pks or title_norm in seen_titles:
                    return False
                seen_pks.add(pk)
                seen_titles.add(title_norm)
                candidates.append(cand)
                return True

            # Direct candidates first (better ranked), then fill from term-index
            for cand in direct_candidates:
                if len(candidates) >= k:
                    break
                _add_candidate(cand)
            for cand in term_candidates:
                if len(candidates) >= k:
                    break
                _add_candidate(cand)

            targets = [
                (c.get("table_pk"), str(c.get("file_id") or c.get("source_file") or ""), str(c.get("table_title") or ""))
                for c in candidates
            ]

            fetched: dict[int, dict] = {}
            for i, (pk, fid, title) in enumerate(targets):
                kwargs: dict[str, Any] = {"limit": 20}
                if pk:
                    kwargs["table_pk"] = pk
                else:
                    kwargs["file_id"] = fid
                    kwargs["table_title"] = title
                if year is not None:
                    kwargs["year"] = int(year)
                if mo is not None:
                    kwargs["month"] = mo
                # Try with metric as column_label first, fall back to no filter
                if m:
                    kwargs["column_label"] = m
                result = self.query_table_rows(**kwargs)
                if not (result.get("rows")) and m:
                    kwargs.pop("column_label", None)
                    kwargs["row_label"] = m
                    result = self.query_table_rows(**kwargs)
                if not (result.get("rows")) and m:
                    kwargs.pop("row_label", None)
                    result = self.query_table_rows(**kwargs)
                # If year filter returned nothing, note it but do NOT silently
                # drop the year — returning wrong-era data is worse than empty.
                if not (result.get("rows")) and year is not None:
                    result = {"rows": [], "warning": f"No rows found for year {year} in table {pk}. Year may be encoded differently in this table."}
                # Supplement: if query asks for "total", also fetch the plain
                # "Total" column which the metric filter would miss.
                _q_has_total = "total" in (q or "").lower()
                existing_cls = {r.get("column_label", "").lower() for r in (result.get("rows") or [])}
                if _q_has_total and "total" not in existing_cls:
                    total_kwargs = {"table_pk": pk}
                    if year is not None:
                        total_kwargs["year"] = int(year)
                    if mo is not None:
                        total_kwargs["month"] = mo
                    total_kwargs["column_label"] = "Total"
                    total_result = self.query_table_rows(**total_kwargs)
                    total_rows = total_result.get("rows") or []
                    if total_rows:
                        existing_rows = result.get("rows") or []
                        result["rows"] = existing_rows + total_rows
                fetched[i] = result

            # --- Phase 3: Assemble results ---
            results = []
            for i, (pk, fid, title) in enumerate(targets):
                row_result = fetched.get(i, {"rows": []})
                rows = row_result.get("rows") or []
                table_info = row_result.get("table_info", {})
                if rows:
                    # Sort: CY/FY synthetic rows first (they're pre-computed answers),
                    # then annual totals, then monthly detail
                    rows.sort(key=lambda r: (
                        0 if str(r.get("row_label", "")).startswith("CY") or
                             str(r.get("row_label", "")).startswith("FY") else
                        1 if r.get("month") is None else 2
                    ))
                    compact_rows = []
                    for r in rows[:10]:
                        cr: dict[str, Any] = {
                            "row_label": r.get("row_label"),
                            "value": r.get("value_raw") or r.get("normalized_value") or r.get("value"),
                            "year": r.get("year"),
                            "column_label": r.get("column_label"),
                            "time_scope": r.get("time_scope"),
                        }
                        if r.get("value_scaled") is not None:
                            cr["value_scaled"] = r["value_scaled"]
                            cr["unit_scale"] = r.get("unit_scale", 1)
                        # Enriched evidence fields
                        if r.get("series_label"):
                            cr["series_label"] = r["series_label"]
                        if r.get("footnote"):
                            cr["footnote"] = r["footnote"]
                        compact_rows.append(cr)
                    entry: dict[str, Any] = {
                        "file_id": fid,
                        "table_title": title,
                        "table_pk": pk,
                        "rows": compact_rows,
                        "rows_returned": len(compact_rows),
                        "was_truncated": len(rows) > 10,
                    }
                    # Include matched column/row info from direct search
                    cand = candidates[i] if i < len(candidates) else {}
                    if cand.get("matched_columns"):
                        entry["matched_columns"] = cand["matched_columns"]
                    if cand.get("matched_rows"):
                        entry["matched_rows"] = cand["matched_rows"]
                    if table_info.get("units"):
                        entry["units"] = table_info["units"]
                        entry["unit_scale"] = table_info.get("unit_scale", 1)
                    if cand.get("units"):
                        entry.setdefault("units", cand["units"])
                    # Add period_basis from table_index
                    try:
                        _ti = self._conn.execute(
                            "SELECT period_basis FROM table_index WHERE table_pk = ?",
                            (pk,),
                        ).fetchone()
                        if _ti and _ti["period_basis"]:
                            entry["period_basis"] = _ti["period_basis"]
                    except Exception:
                        pass
                    # structure_hints only in slim_v2 DB
                    try:
                        _sh = self._conn.execute(
                            "SELECT structure_hints FROM table_index WHERE table_pk = ?",
                            (pk,),
                        ).fetchone()
                        if _sh and _sh["structure_hints"]:
                            hints = json.loads(_sh["structure_hints"])
                            if hints.get("has_additive_total"):
                                entry["has_additive_total"] = True
                            if hints.get("likely_ops"):
                                entry["likely_ops"] = hints["likely_ops"]
                    except Exception:
                        pass
                    results.append(entry)

            out: dict[str, Any] = {
                "results": results,
                "count": sum(len(r["rows"]) for r in results),
                "query": q,
            }
            if year is not None:
                out["year"] = year

            # --- Phase 4: Compute verdict (best single-value answer) ---
            if results:
                best_row = None
                best_score = -1
                best_table_title = ""
                best_units = ""
                q_lower = f"{q} {m}".lower()

                # Clean-string normalization for label matching
                def _clean_label(s: str) -> str:
                    if not s:
                        return ""
                    s = s.lower()
                    s = re.sub(r"[',.\-]", "", s)  # Remove punctuation noise
                    s = re.sub(r"\d+\s*/", "", s)   # Remove footnote markers (2/, 3/)
                    return " ".join(s.split())

                # Extract specific sub-series name from metric or query (normalized)
                metric_clean = _clean_label(m)

                # Detect calendar vs fiscal preference
                query_wants_calendar = "calendar year" in q_lower or "calendar" in q_lower
                query_wants_fiscal = "fiscal year" in q_lower or "fiscal" in q_lower

                # Detect if query asks for a specific sub-category vs total/aggregate
                _total_words = {"total", "aggregate", "sum", "all", "combined", "overall"}
                _specific_indicators = {"series", "type", "class", "category", "classified", "administration"}
                query_wants_total = any(w in q_lower for w in _total_words)
                query_wants_specific = any(w in q_lower for w in _specific_indicators) or bool(m)
                # If query asks for "total X" and the metric matches a table title,
                # it's asking for the aggregate, not a specific sub-series.
                if query_wants_total and metric_clean:
                    query_wants_specific = any(w in q_lower for w in _specific_indicators)

                for res in results:
                    t_title = (res.get("table_title") or "").lower()
                    t_units = res.get("units", "")
                    # Compute bulletin proximity for this result
                    fid = res.get("file_id") or ""
                    bulletin_year_match = re.search(r'(\d{4})', fid)
                    bulletin_year = int(bulletin_year_match.group(1)) if bulletin_year_match else None
                    for row in res.get("rows", []):
                        score = 0
                        val = row.get("value_scaled") or row.get("value")
                        if val is None or str(val).strip() in ("", "...", "—", "-"):
                            continue
                        # Year match: strong signal when query specifies year
                        if year is not None:
                            row_year = row.get("year")
                            if row_year == year:
                                score += 5  # exact year match
                            elif row_year is not None and row_year != year:
                                score -= 3  # wrong year data
                            else:
                                score -= 2  # no year info — unreliable
                        # Bulletin proximity: mild preference, not hard penalty
                        # (Historical compilations in later bulletins are common in Treasury data)
                        if year is not None and bulletin_year is not None:
                            dist = abs(bulletin_year - year)
                            if dist <= 1:
                                score += 3  # same year or adjacent
                            elif dist >= 5:
                                score -= 2  # mild penalty for very distant bulletins
                        # Metric match: +2 for each query term found in row_label
                        rl = (row.get("row_label") or "").lower()
                        rl_clean = _clean_label(row.get("row_label") or "")
                        for term in all_terms[:3]:
                            if term in rl:
                                score += 2
                            if term in t_title:
                                score += 1
                        # Column match: +3 if metric in column_label (normalized)
                        cl_clean = _clean_label(row.get("column_label") or "")
                        if metric_clean and (metric_clean in cl_clean or metric_clean in rl_clean):
                            score += 3  # normalized metric match
                        # Prefer non-footnoted values
                        if not row.get("footnote"):
                            score += 1

                        # --- Hierarchy awareness ---
                        # Check both row_label AND column_label for "Total" —
                        # in many Treasury tables, years are rows and categories are columns,
                        # so "Total" appears as a column header, not a row label.
                        rl_stripped = rl.strip().rstrip(".")
                        cl_stripped = cl_clean.strip().rstrip(".")
                        is_pure_total = (
                            rl_stripped in ("total", "grand total", "net total", "summary", "total all")
                            or cl_stripped in ("total", "grand total", "net total", "summary", "total all")
                        )
                        is_total_prefix = (
                            rl_stripped.startswith("total ") or rl_stripped.startswith("grand total")
                            or cl_stripped.startswith("total ") or cl_stripped.startswith("grand total")
                        )
                        is_total_row = is_pure_total or is_total_prefix
                        # Series label gives hierarchy info
                        series_label = (row.get("series_label") or "").lower()
                        # Does this "Total" row also contain our search terms?
                        combined_label = f"{rl} {cl_clean}"
                        total_has_query_terms = is_total_row and any(t in combined_label for t in all_terms[:3])

                        # When query wants BOTH total AND a specific metric
                        # (e.g., "total national defense expenditures"), a pure "Total"
                        # column/row in a table whose TITLE contains the metric IS the answer.
                        # The table title already narrows to the topic; "Total" = the aggregate.
                        title_has_metric = metric_clean and metric_clean in t_title
                        if query_wants_total and is_pure_total and title_has_metric:
                            # "Total" column in "Analysis of National Defense Expenditures"
                            # = total national defense. Dominant boost — beats sub-totals.
                            score += 8
                        elif query_wants_specific:
                            # Query asks for specific sub-series
                            if is_pure_total and not title_has_metric:
                                score -= 3
                            elif is_total_prefix and not total_has_query_terms:
                                score -= 2
                            # Boost rows matching the specific metric/sub-series
                            if metric_clean and (metric_clean in rl_clean or metric_clean in cl_clean):
                                score += 4
                            if metric_clean and metric_clean in _clean_label(series_label):
                                score += 3
                        elif query_wants_total:
                            if is_total_row:
                                score += 3
                        else:
                            # Neutral: slight preference for Total if query is generic
                            if is_total_row:
                                score += 1

                        # CY/FY synthetic row bonus: when query asks for calendar year,
                        # strongly prefer pre-computed CY rows over raw fiscal year data.
                        # Handle both "cy1940" and "cy1940 — national defense" formats.
                        is_cy_synthetic = rl.startswith("cy")
                        is_fy_synthetic = rl.startswith("fy") and not rl.startswith("fy19")  # avoid matching "fy1940" as a year
                        if query_wants_calendar and is_cy_synthetic:
                            score += 10  # dominant — CY rows are the direct answer
                            # Extra boost if the CY row label contains the metric
                            if metric_clean and " — " in rl and metric_clean in rl:
                                score += 5  # exact category match in synthetic row
                        elif query_wants_fiscal and is_fy_synthetic:
                            score += 10  # dominant — FY rows are the direct answer
                            if metric_clean and " — " in rl and metric_clean in rl:
                                score += 5  # exact category match in synthetic row
                        elif query_wants_calendar and not is_cy_synthetic:
                            # Check if this is a period_basis=fiscal row (penalize)
                            pb = (res.get("period_basis") or "").lower()
                            if pb == "fiscal":
                                score -= 3

                        if score > best_score:
                            best_score = score
                            best_row = row
                            best_table_title = res.get("table_title", "")
                            best_units = t_units

                if best_row and best_score >= 3:
                    # Return raw table value (not scaled) — the model needs the
                    # number as it appears in the table, with units context.
                    # value_scaled can be misleading: a "99" in a "millions" table
                    # becomes 99000000 which confuses the question "in millions".
                    verdict_val = best_row.get("value_raw") or best_row.get("value") or best_row.get("value_scaled")
                    verdict_entry: dict[str, Any] = {
                        "value": verdict_val,
                        "row_label": best_row.get("row_label"),
                        "column_label": best_row.get("column_label"),
                        "table_title": best_table_title,
                        "units": best_units,
                        "confidence": "high" if best_score >= 6 else "medium",
                        "note": "SUGGESTED best match — review the rows above to confirm this is the right row/column for your question. Check units and period_basis before using.",
                    }
                    # Detect fiscal/calendar mismatch (skip if verdict is a CY/FY synthetic row)
                    rl_lower = str(best_row.get("row_label", "")).lower()
                    is_cy_row = rl_lower.startswith("cy")
                    is_fy_row = rl_lower.startswith("fy")
                    for res in results:
                        if res.get("table_title", "") == best_table_title:
                            pb = (res.get("period_basis") or "").lower()
                            if is_cy_row:
                                verdict_entry["period_basis"] = "calendar"
                            elif is_fy_row:
                                verdict_entry["period_basis"] = "fiscal"
                            else:
                                verdict_entry["period_basis"] = pb
                                if query_wants_calendar and pb == "fiscal":
                                    verdict_entry["warning"] = (
                                        "FISCAL/CALENDAR MISMATCH: This table uses fiscal year data, "
                                        "but your question asks for calendar year. "
                                        "To get calendar year totals, sum the 12 monthly values (Jan-Dec) "
                                        "from this table, or search for a calendar-year table."
                                    )
                                    verdict_entry["confidence"] = "low"
                                elif query_wants_fiscal and pb == "calendar":
                                    verdict_entry["warning"] = (
                                        "CALENDAR/FISCAL MISMATCH: This table uses calendar year data, "
                                        "but your question asks for fiscal year."
                                    )
                                    verdict_entry["confidence"] = "low"
                            break
                    out["verdict"] = verdict_entry

            if not results:
                out["hint"] = (
                    "No matching tables found. Try: "
                    "1) search_tables with different keywords, "
                    "2) get_table_profile on a known table_pk, "
                    "3) grep_corpus(pattern='| keyword |', file_id='YYYY_MM') as last resort."
                )
            return out
        except Exception as exc:
            return {"results": [], "error": str(exc)}

    def search_ledger(
        self,
        metric: str,
        year: int | None = None,
        period_basis: str = "",
        years: list[int] | None = None,
    ) -> dict:
        """Search the Master Ledger — a flat index of all values by metric and time.

        Returns deduplicated values (latest bulletin wins) for the given metric.
        Much faster and more reliable than search_tables + extract_values for
        known metrics.

        Args:
            metric: The metric/category name (e.g. "customs", "national defense")
            year: Single year to look up
            period_basis: "calendar", "fiscal", "monthly", or "annual"
            years: List of years for multi-year lookups (e.g. [1940, 1941])
        """
        try:
            # Check if master_ledger table exists
            has_ledger = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='master_ledger'"
            ).fetchone()
            if not has_ledger:
                return {"error": "master_ledger table not found. Run enrich script first."}

            metric_norm = metric.lower().strip()
            metric_norm = re.sub(r'\s*\d+/', '', metric_norm)
            metric_norm = re.sub(r'[^\w\s]', '', metric_norm).strip()
            metric_norm = re.sub(r'\s+', ' ', metric_norm)

            # Build year list
            yr_list = []
            if years:
                yr_list = [int(y) for y in years]
            elif year is not None:
                yr_list = [int(year)]

            # Build time_key patterns
            time_keys = []
            for y in yr_list:
                if period_basis == "calendar":
                    time_keys.append(f"CY{y}")
                elif period_basis == "fiscal":
                    time_keys.append(f"FY{y}")
                elif period_basis == "monthly":
                    for m in range(1, 13):
                        time_keys.append(f"{y}-{m:02d}")
                elif period_basis == "annual":
                    time_keys.append(str(y))
                else:
                    # Return all period types for this year
                    time_keys.extend([f"CY{y}", f"FY{y}", str(y)])

            # Query: exact metric match first, then LIKE fallback
            results = []
            if time_keys:
                placeholders = ",".join("?" * len(time_keys))
                rows = self._conn.execute(
                    f"""SELECT metric_slug, time_key, period_basis, value, value_raw,
                               table_pk, source_file, table_title, row_type
                        FROM master_ledger
                        WHERE metric_slug = ? AND time_key IN ({placeholders})
                        ORDER BY time_key, source_file DESC""",
                    (metric_norm, *time_keys),
                ).fetchall()
                if not rows:
                    # Fuzzy fallback: LIKE match
                    rows = self._conn.execute(
                        f"""SELECT metric_slug, time_key, period_basis, value, value_raw,
                                   table_pk, source_file, table_title, row_type
                            FROM master_ledger
                            WHERE metric_slug LIKE ? AND time_key IN ({placeholders})
                            ORDER BY time_key, source_file DESC
                            LIMIT 50""",
                        (f"%{metric_norm}%", *time_keys),
                    ).fetchall()
            else:
                # No year specified — return all time keys for this metric
                rows = self._conn.execute(
                    """SELECT metric_slug, time_key, period_basis, value, value_raw,
                              table_pk, source_file, table_title, row_type
                       FROM master_ledger
                       WHERE metric_slug = ?
                       ORDER BY time_key
                       LIMIT 50""",
                    (metric_norm,),
                ).fetchall()
                if not rows:
                    rows = self._conn.execute(
                        """SELECT metric_slug, time_key, period_basis, value, value_raw,
                                  table_pk, source_file, table_title, row_type
                           FROM master_ledger
                           WHERE metric_slug LIKE ?
                           ORDER BY time_key
                           LIMIT 50""",
                        (f"%{metric_norm}%",),
                    ).fetchall()

            # Deduplicate: for each (metric, time_key), keep the latest bulletin
            seen: dict[tuple[str, str], dict] = {}
            for r in rows:
                key = (r["metric_slug"], r["time_key"])
                entry = {
                    "metric": r["metric_slug"],
                    "time_key": r["time_key"],
                    "period_basis": r["period_basis"],
                    "value": r["value"],
                    "value_raw": r["value_raw"],
                    "table_pk": r["table_pk"],
                    "source": r["source_file"],
                    "table_title": r["table_title"],
                    "row_type": r["row_type"],
                }
                # Prefer synthetic CY/FY rows, then latest bulletin
                if key not in seen:
                    seen[key] = entry
                elif entry["row_type"] and not seen[key]["row_type"]:
                    seen[key] = entry  # synthetic beats raw

            results = sorted(seen.values(), key=lambda x: x["time_key"])

            # Get units from the source table
            if results:
                pk = results[0]["table_pk"]
                ti = self._conn.execute(
                    "SELECT units_line FROM table_index WHERE table_pk = ?", (pk,)
                ).fetchone()
                units = ti["units_line"] if ti and ti["units_line"] else ""
            else:
                units = ""

            return {
                "results": results,
                "count": len(results),
                "metric_query": metric_norm,
                "units": units,
            }
        except Exception as exc:
            return {"results": [], "error": str(exc)}

    def search_canonical(
        self,
        query: str,
        year: int | None = None,
        years: list[int] | None = None,
        table_family: str = "",
        limit: int = 15,
    ) -> dict:
        """Search the hierarchical canonical fact store.

        Built from the full 11GB corpus with 935K deduplicated facts organized
        by hierarchical keys (table_family > table_title > row_label > metric).
        Searches directly on canonical_facts columns — no alias table needed.

        This is the PREFERRED first-hop retrieval tool. Use search_tables as
        fallback only if results are insufficient.

        Args:
            query: Search terms (e.g. "income tax", "public debt outstanding",
                   "savings bonds sales"). Matches against canonical_key,
                   entity_key, table_title, row_label, and column_label.
            year: Single year filter (e.g. 1938)
            years: List of years for multi-year lookup (e.g. [1938, 1939, 1940])
            table_family: Filter by family (e.g. "public_debt", "revenue_receipts",
                         "federal_securities", "international_capital", "monetary",
                         "cash_operations", "budget_expenditures")
            limit: Max results to return (default 15)

        Returns:
            results: List of canonical facts with hierarchical keys, values,
                     units, provenance, and variant counts
        """
        try:
            has_table = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='canonical_facts'"
            ).fetchone()
            if not has_table:
                return {"error": "canonical_facts table not found. Run build_master_ledger_v2.py first."}

            # Normalize query
            q_norm = query.lower().strip()
            q_norm = re.sub(r'\s*\d+/', '', q_norm)
            q_norm = re.sub(r'[^\w\s\-]', '', q_norm)
            q_norm = re.sub(r'\s+', ' ', q_norm).strip()

            words = q_norm.split()
            if not words:
                return {"results": [], "count": 0, "query": q_norm}

            # Build year filter
            yr_list = []
            if years:
                yr_list = [int(y) for y in years]
            elif year is not None:
                yr_list = [int(year)]

            # Search directly on canonical_facts columns
            # Strategy: search entity_key (has most context) with OR between words,
            # then rank by how many words matched
            # Build a single search string that matches ANY word in entity_key or canonical_key
            or_clauses = []
            params: list = []
            for w in words[:6]:
                or_clauses.append("(entity_key LIKE ? OR canonical_key LIKE ? OR row_label LIKE ?)")
                pat = f"%{w}%"
                params.extend([pat, pat, pat])

            # Require at least half the words to match (rounded up)
            # For 1-2 words: all must match. For 3+: at least ceil(n/2).
            min_match = max(1, (len(words[:6]) + 1) // 2)
            if min_match >= len(or_clauses):
                # All words required
                where_parts = [" AND ".join(or_clauses)]
            else:
                # Use a subquery approach: OR all, then filter by match count
                # Simpler: just AND all words but search a concatenated field
                # Fastest approach: concatenate searchable fields into one LIKE check
                concat_clauses = []
                params = []
                for w in words[:6]:
                    concat_clauses.append(
                        "(entity_key || ' ' || canonical_key || ' ' || row_label || ' ' || "
                        "COALESCE(column_label,'') || ' ' || COALESCE(table_title,'')) LIKE ?"
                    )
                    params.append(f"%{w}%")
                where_parts = [" AND ".join(concat_clauses)]

            if yr_list:
                yr_ph = ",".join("?" * len(yr_list))
                where_parts.append(f"year IN ({yr_ph})")
                params.extend(yr_list)

            if table_family:
                where_parts.append("table_family = ?")
                params.append(table_family)

            where_sql = " AND ".join(where_parts)

            rows = self._conn.execute(f"""
                SELECT canonical_key, entity_key, metric_key, metric_type,
                       time_key, year, month, value,
                       unit_type, unit_raw, table_family,
                       table_title, section_path, row_label, column_label,
                       period_basis, source_file, bulletin_date,
                       variant_count
                FROM canonical_facts
                WHERE {where_sql}
                ORDER BY
                    variant_count DESC,
                    bulletin_date DESC,
                    canonical_key,
                    time_key
                LIMIT ?
            """, (*params, limit)).fetchall()

            results = []
            for r in rows:
                results.append({
                    "canonical_key": r["canonical_key"],
                    "time_key": r["time_key"],
                    "value": r["value"],
                    "unit": r["unit_raw"] or r["unit_type"] or "",
                    "table_family": r["table_family"],
                    "metric_type": r["metric_type"],
                    "period_basis": r["period_basis"] or "",
                    "source": r["source_file"],
                    "bulletin_date": r["bulletin_date"],
                    "table_title": r["table_title"],
                    "row_label": r["row_label"],
                    "column_label": r["column_label"],
                    "variant_count": r["variant_count"],
                })

            distinct_keys = list(set(r["canonical_key"] for r in results))
            distinct_families = list(set(r["table_family"] for r in results if r["table_family"]))

            return {
                "results": results,
                "count": len(results),
                "query": q_norm,
                "distinct_fact_families": distinct_families,
                "distinct_canonical_keys": distinct_keys[:20],
                "hint": (
                    "Each canonical_key represents a distinct data series. "
                    "Use table_family to disambiguate if multiple contexts match."
                ) if len(distinct_keys) > 1 else "",
            }
        except Exception as exc:
            return {"results": [], "error": str(exc)}

    def get_time_series(
        self,
        metric: str,
        year_start: int,
        year_end: int,
        query: str = "",
        file_id: str = "",
        month_start: int | None = None,
        month_end: int | None = None,
        top_k: int = 3,
    ) -> dict:
        """Fetch a time-series for a metric across a year range in one DB query.

        Unlike get_multi_year_series (which calls extract_values per year),
        this does ONE search_tables + ONE query_table_rows for the whole range.
        """
        try:
            m = str(metric or "").strip()
            if not m:
                return {"series": {}, "error": "metric is required"}
            yr_start = int(year_start)
            yr_end = int(year_end)
            if yr_start > yr_end:
                yr_start, yr_end = yr_end, yr_start
            search_q = str(query or "").strip() or m
            # Combine search_q and metric if metric not already in search_q
            if m.lower() not in search_q.lower():
                search_q = f"{search_q} {m}"

            # Step 1: Find the best table(s) covering this year range
            search_kwargs: dict[str, Any] = {
                "query": search_q,
                "year_range": [yr_start, yr_end],
                "limit": top_k * 3,
            }
            if file_id:
                search_kwargs["file_id"] = file_id
            # Internal search — does NOT count against user's search budget
            saved_count = self._search_call_count
            table_result = self.search_tables(**search_kwargs)
            self._search_call_count = saved_count  # restore
            candidates = (table_result.get("candidates") or [])[:top_k]

            if not candidates:
                return {
                    "metric": m,
                    "series": {},
                    "count": 0,
                    "coverage": {"requested_years": list(range(yr_start, yr_end + 1)), "found": 0, "missing": list(range(yr_start, yr_end + 1))},
                    "action_hint": "No tables found. Try broader keywords or remove file_id constraint.",
                }

            # Step 2: Query rows from the best candidate across the full year range
            best_series: dict[str, Any] = {}
            best_table_pk = None
            best_table_title = ""
            best_file_id = ""

            # Collect series from ALL candidates, then pick the best
            # or merge across candidates if none has complete coverage.
            all_candidate_series: list[tuple[int | None, str, str, dict[str, Any]]] = []

            for cand in candidates:
                pk = cand.get("table_pk")
                fid = str(cand.get("file_id") or "")
                title = str(cand.get("table_title") or "")

                kwargs: dict[str, Any] = {
                    "year_range": [yr_start, yr_end],
                    "limit": 500,  # grab all rows for the range
                }
                if pk:
                    kwargs["table_pk"] = pk
                else:
                    kwargs["file_id"] = fid
                    kwargs["table_title"] = title

                # Try column_label first, then row_label, then no filter (cascade)
                if m:
                    kwargs["column_label"] = m
                result = self.query_table_rows(**kwargs)

                if not result.get("rows") and m:
                    kwargs.pop("column_label", None)
                    kwargs["row_label"] = m
                    result = self.query_table_rows(**kwargs)

                if not result.get("rows") and m:
                    kwargs.pop("row_label", None)
                    result = self.query_table_rows(**kwargs)

                rows = result.get("rows") or []
                if not rows:
                    continue

                # Build series from rows
                series: dict[str, Any] = {}
                for r in rows:
                    yr = r.get("year")
                    mo = r.get("month")
                    ts = r.get("time_scope", "")
                    val = r.get("value_raw") or r.get("normalized_value") or r.get("value")

                    # Determine period key
                    if mo:
                        period_key = f"{yr}-{int(mo):02d}"
                    elif ts and re.match(r"^\d{4}-\d{2}$", str(ts)):
                        period_key = str(ts)
                    else:
                        period_key = str(yr) if yr else None

                    if period_key and val is not None:
                        if period_key not in series:
                            series[period_key] = val

                if series:
                    all_candidate_series.append((pk, fid, title, series))

                # Count only monthly keys for quality comparison
                monthly_keys = [k for k in series if "-" in str(k)]
                best_monthly = [k for k in best_series if "-" in str(k)]
                if len(monthly_keys) > len(best_monthly) or (
                    len(monthly_keys) == len(best_monthly) and len(series) > len(best_series)
                ):
                    best_series = series
                    best_table_pk = pk
                    best_table_title = title
                    best_file_id = fid

            # Merge: if best series has gaps, fill from other candidates
            if all_candidate_series and best_series:
                for _pk, _fid, _title, cand_series in all_candidate_series:
                    for k, v in cand_series.items():
                        if k not in best_series:
                            best_series[k] = v

            # Step 3: Compute coverage
            requested_years = list(range(yr_start, yr_end + 1))
            found_years = set()
            for k in best_series:
                # Extract year from period key
                yr_match = re.match(r"^(\d{4})", str(k))
                if yr_match:
                    found_years.add(int(yr_match.group(1)))
            missing_years = [y for y in requested_years if y not in found_years]

            # Filter by month range if specified
            if month_start is not None or month_end is not None:
                ms = int(month_start) if month_start else 1
                me = int(month_end) if month_end else 12
                filtered: dict[str, Any] = {}
                for k, v in best_series.items():
                    mo_match = re.match(r"^\d{4}-(\d{2})$", str(k))
                    if mo_match:
                        mo_val = int(mo_match.group(1))
                        yr_val = int(k.split("-")[0])
                        # For first year, start from month_start; for last year, end at month_end
                        if yr_val == yr_start and mo_val < ms:
                            continue
                        if yr_val == yr_end and mo_val > me:
                            continue
                        filtered[k] = v
                    else:
                        # Annual data, keep it
                        filtered[k] = v
                best_series = filtered

            # Determine granularity
            has_monthly = any("-" in str(k) for k in best_series)
            granularity = "monthly" if has_monthly else "annual"

            # Get unit metadata from the best table
            best_units = ""
            best_unit_scale = 1
            if best_table_pk:
                try:
                    _u = self._conn.execute(
                        "SELECT units_line FROM table_index WHERE table_pk = ?",
                        (best_table_pk,),
                    ).fetchone()
                    if _u and _u["units_line"]:
                        best_units = str(_u["units_line"]).strip()
                        ul = best_units.lower()
                        if "thousand" in ul:
                            best_unit_scale = 1_000
                        elif "billion" in ul:
                            best_unit_scale = 1_000_000_000
                        elif "million" in ul:
                            best_unit_scale = 1_000_000
                except Exception:
                    pass

            out: dict[str, Any] = {
                "metric": m,
                "table_pk": best_table_pk,
                "table_title": best_table_title,
                "file_id": best_file_id,
                "granularity": granularity,
                "series": best_series,
                "count": len(best_series),
                "coverage": {
                    "requested_years": requested_years,
                    "found": len(found_years),
                    "missing_years": missing_years,
                },
            }
            if best_units:
                out["units"] = best_units
                out["unit_scale"] = best_unit_scale
                if best_unit_scale > 1:
                    out["warning"] = f"⚠ Series values are in {best_units}. Multiply by {best_unit_scale:,} for nominal dollars."

            if best_series:
                # Check monthly coverage completeness
                monthly_keys = sorted(k for k in best_series if "-" in str(k))
                n_years = yr_end - yr_start + 1
                expected_monthly = n_years * 12
                coverage_note = ""
                if monthly_keys and len(monthly_keys) < expected_monthly:
                    coverage_note = (
                        f" ⚠ Only {len(monthly_keys)} of {expected_monthly} expected "
                        f"monthly values found. Data may be incomplete — check if "
                        f"additional bulletins have the missing months."
                    )

                out["action_hint"] = (
                    f"Got {len(best_series)} values ({granularity}). "
                    f"Use compute_expression() with these values "
                    f"(e.g. geometric_mean, mean, sum, linreg).{coverage_note}"
                )
            else:
                out["action_hint"] = (
                    "No values found for this metric+range. "
                    "Try search_tables with broader keywords."
                )

            return out
        except Exception as exc:
            return {"series": {}, "error": str(exc)}

    def get_multi_year_series(
        self,
        metric: str,
        years: list[int],
        top_k: int = 3,
    ) -> dict:
        """Extract a time-series for a metric across multiple years in one call.

        Uses ONE search + ONE range query (does not burn search budget per year).
        """
        try:
            m = str(metric or "").strip()
            if not m:
                return {"series": {}, "error": "metric is required"}
            yrs = sorted({int(y) for y in years if str(y).strip()})
            if not yrs:
                return {"series": {}, "error": "years are required"}

            # Delegate to get_time_series for contiguous range
            yr_start, yr_end = min(yrs), max(yrs)
            ts_result = self.get_time_series(
                metric=m, year_start=yr_start, year_end=yr_end, top_k=top_k,
            )

            # Filter to only requested years
            full_series = ts_result.get("series", {})
            series: dict[int, Any] = {}
            for y in yrs:
                # Check annual key (str(y)) or monthly keys (y-MM)
                if str(y) in full_series:
                    series[y] = {"value": full_series[str(y)]}
                else:
                    # Collect monthly values for this year
                    monthly = {k: v for k, v in full_series.items() if k.startswith(f"{y}-")}
                    if monthly:
                        series[y] = {"monthly_values": monthly}

            out: dict[str, Any] = {
                "metric": m,
                "years": yrs,
                "series": series,
                "count": len(series),
                "table_pk": ts_result.get("table_pk"),
                "table_title": ts_result.get("table_title"),
            }
            if ts_result.get("units"):
                out["units"] = ts_result["units"]
                out["unit_scale"] = ts_result.get("unit_scale", 1)
            return out
        except Exception as exc:
            return {"series": {}, "error": str(exc)}

    def grep_corpus(
        self,
        pattern: str,
        file_id: str = "",
        max_lines: int = 40,
        case_insensitive: bool = True,
    ) -> dict:
        """LAST RESORT grep over raw corpus files. Prefer search_tables + query_table_rows first."""
        import subprocess
        try:
            self._grep_call_count += 1
            p = str(pattern or "").strip()
            if not p:
                return {"error": "pattern is required", "lines": []}

            # Build file target
            corpus_dir = Path("/app/corpus")
            if not corpus_dir.exists():
                corpus_dir = _ROOT / "data" / "corpus"
            if file_id:
                sf = file_id.strip()
                if not sf.startswith("treasury_bulletin_"):
                    sf = f"treasury_bulletin_{sf}.txt"
                target = str(corpus_dir / sf)
            else:
                target = str(corpus_dir / "*.txt")

            # Run grep with hard cap
            flag = "-i" if case_insensitive else ""
            cmd = f"grep -n {flag} -- {json.dumps(p)} {target} | head -{max(1, min(int(max_lines), 60))}"
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=10,
            )
            lines = [l for l in proc.stdout.strip().split("\n") if l]
            total_hint = len(lines)
            truncated = total_hint >= max_lines

            # Count total matches if truncated
            if truncated:
                count_cmd = f"grep -c {flag} -- {json.dumps(p)} {target} 2>/dev/null | awk -F: '{{s+=$NF}}END{{print s}}'"
                count_result = subprocess.run(
                    count_cmd, shell=True, capture_output=True, text=True, timeout=5,
                )
                try:
                    total_hint = int(count_result.stdout.strip())
                except ValueError:
                    pass

            result: dict[str, Any] = {
                "lines": lines,
                "count": len(lines),
                "total_matches": total_hint,
                "truncated": truncated,
                "pattern": p,
                "grep_call_number": self._grep_call_count,
            }
            if self._grep_call_count >= 3:
                result["warning"] = (
                    f"You have called grep_corpus {self._grep_call_count} times. "
                    "STOP grepping. Use the data you already have, or try: "
                    "search_tables → get_table_profile → query_table_rows. "
                    "Write your best answer NOW."
                )
            else:
                result["tip"] = "Data is in pipe-delimited tables. Use '| keyword |' for precise matches."
            return result
        except subprocess.TimeoutExpired:
            return {"error": "grep timed out after 10s — pattern too broad", "lines": []}
        except Exception as exc:
            return {"error": str(exc), "lines": []}

    def web_lookup(
        self,
        url: str,
        extract: str = "",
    ) -> dict:
        """Fetch a URL and return its text content (max 10KB). Use for external data lookups.

        For exchange rates, try these URLs:
          - https://api.exchangerate-api.com/v4/latest/USD (current rates)
          - Use bash: python3 -c "..." for more complex fetching
        """
        import urllib.request
        try:
            u = str(url or "").strip()
            if not u:
                return {"error": "url is required"}
            if not u.startswith("http"):
                return {"error": "url must start with http:// or https://"}
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read(10240).decode("utf-8", errors="replace")
            return {
                "ok": True,
                "url": u,
                "status": resp.status,
                "content": raw,
                "truncated": len(raw) >= 10240,
                "hint": extract or "Parse the returned content for the data you need.",
            }
        except Exception as exc:
            return {"error": str(exc), "url": url}

    def resolve_agency_alias(self, query: str) -> dict:
        """Map historical agency names to canonical phrases for better search."""
        try:
            q = str(query or "").strip().lower()
            if not q:
                return {"matches": [], "error": "query is required"}
            alias_path = _ROOT / "data" / "reference" / "agency_alias.json"
            if not alias_path.exists():
                return {"matches": [], "error": "agency_alias.json not found"}
            data = json.loads(alias_path.read_text())
            matches = []
            for entry in data.get("entries", []):
                canonical = entry.get("canonical", "")
                aliases = entry.get("aliases", [])
                for alias in aliases:
                    if q in alias.lower() or alias.lower() in q:
                        matches.append({
                            "canonical": canonical,
                            "matched_alias": alias,
                            "all_aliases": aliases,
                        })
                        break
            return {"query": query, "matches": matches, "count": len(matches)}
        except Exception as exc:
            return {"matches": [], "error": str(exc)}

    def verify_answer(
        self,
        question: str,
        candidate_answer: str,
        evidence_table_pks: list[int] | None = None,
        evidence_values: list[str] | None = None,
        units_claimed: str = "",
        units: str = "",  # alias for units_claimed (models sometimes use shorter name)
    ) -> dict:
        """Pre-write verification. Checks unit scale, value provenance, and common pitfalls.

        Call this BEFORE writing to /app/answer.txt. Returns pass/fail with specific repair guidance.
        """
        try:
            warnings: list[str] = []
            checks: dict[str, bool | str] = {}
            q = str(question or "").strip().lower()
            ans = str(candidate_answer or "").strip()
            claimed = str(units_claimed or units or "").strip().lower()

            if not ans:
                return {"verified": False, "checks": {}, "warnings": ["No candidate answer provided."]}

            # Parse numeric answer (single value or list)
            ans_num = None
            ans_is_list = bool(ans.startswith("[") and ans.endswith("]") and "," in ans)
            ans_list_nums: list[float] = []

            if ans_is_list:
                # Parse each element of the bracket list
                inner = ans[1:-1]
                for elem in inner.split(","):
                    elem = elem.strip()
                    try:
                        ans_list_nums.append(float(re.sub(r"[,$%]", "", elem)))
                    except (ValueError, TypeError):
                        pass
                checks["is_list_answer"] = True
                checks["list_element_count"] = len(ans_list_nums)

                # Infer expected count from year ranges in the question
                year_range = re.search(r"(?:from|between)\s+(\d{4})\s+(?:to|and|through)\s+(\d{4})", q)
                if year_range:
                    start_yr, end_yr = int(year_range.group(1)), int(year_range.group(2))
                    expected = end_yr - start_yr + 1
                    checks["expected_element_count"] = expected
                    if len(ans_list_nums) != expected:
                        warnings.append(
                            f"⚠ LIST COUNT: answer has {len(ans_list_nums)} elements "
                            f"but year range {start_yr}-{end_yr} implies {expected}."
                        )

                # Validate each element is a plausible number (not NaN/inf)
                bad_elems = [v for v in ans_list_nums if not (-1e18 < v < 1e18)]
                if bad_elems:
                    warnings.append(f"⚠ LIST: some elements look invalid: {bad_elems[:3]}")
            else:
                try:
                    ans_clean = re.sub(r"[,$%]", "", ans)
                    ans_num = float(ans_clean)
                except (ValueError, TypeError):
                    pass

            # Check 1: Unit scale verification
            if evidence_table_pks:
                for pk in evidence_table_pks[:3]:
                    try:
                        _ = db.get_table_profile(self._conn, table_pk=int(pk))  # validate pk exists
                        units_line = ""
                        # Get units from table_index
                        row = self._conn.execute(
                            "SELECT units_line FROM table_index WHERE table_pk = ?", (int(pk),)
                        ).fetchone()
                        if row and row["units_line"]:
                            units_line = str(row["units_line"]).strip()
                        if units_line:
                            ul = units_line.lower()
                            table_scale = 1
                            scale_name = "units"
                            if "thousand" in ul:
                                table_scale = 1_000
                                scale_name = "thousands"
                            elif "billion" in ul:
                                table_scale = 1_000_000_000
                                scale_name = "billions"
                            elif "million" in ul:
                                table_scale = 1_000_000
                                scale_name = "millions"

                            if table_scale > 1:
                                checks[f"unit_scale_pk{pk}"] = f"Table values are in {scale_name} ({units_line})"
                                # Check if question asks for different units
                                q_wants_nominal = any(w in q for w in ["nominal", "actual dollar", "in dollar"])
                                q_wants_same = any(w in q for w in [f"in {scale_name}", f"in {scale_name[:-1]}"])
                                # If user explicitly claimed units, cross-check
                                if claimed and claimed != scale_name and scale_name not in claimed:
                                    warnings.append(f"You claimed units='{units_claimed}' but table says '{units_line}'.")
                                if q_wants_nominal and not q_wants_same:
                                    warnings.append(
                                        f"⚠ Table pk={pk} values are in {scale_name}, "
                                        f"but question may ask for nominal dollars. "
                                        f"Multiply by {table_scale:,} before answering."
                                    )
                                    if ans_num is not None and ans_num < table_scale:
                                        warnings.append(
                                            f"⚠ LIKELY UNIT ERROR: answer={ans} looks unscaled. "
                                            f"Expected answer ≈ {ans_num * table_scale:,.0f} if in nominal dollars."
                                        )
                    except Exception:
                        pass

            # Check 2: Value provenance — is the answer traceable to evidence?
            if evidence_values:
                ev_nums = []
                for ev in evidence_values:
                    try:
                        ev_nums.append(float(re.sub(r"[,$%]", "", str(ev))))
                    except (ValueError, TypeError):
                        pass
                if ans_is_list and ans_list_nums and ev_nums:
                    # For list answers, check what fraction of elements appear in evidence
                    matched = sum(1 for a in ans_list_nums if any(abs(a - e) < 0.01 for e in ev_nums))
                    checks["list_values_in_evidence"] = f"{matched}/{len(ans_list_nums)}"
                    if matched < len(ans_list_nums) * 0.5:
                        warnings.append(
                            f"Only {matched}/{len(ans_list_nums)} list elements found in evidence. "
                            f"This may be correct if computed, but double-check."
                        )
                elif ans_num is not None and ev_nums:
                    # Check if answer equals or is derived from evidence
                    exact_match = any(abs(ans_num - ev) < 0.01 for ev in ev_nums)
                    checks["value_in_evidence"] = exact_match
                    if not exact_match:
                        warnings.append(
                            f"Answer {ans} not found directly in evidence values {evidence_values[:5]}. "
                            f"This may be correct if you computed it, but double-check."
                        )

            # Check 3: Sanity — answer should not be 0 or empty for numeric questions
            if ans_num is not None and ans_num == 0:
                warnings.append("Answer is 0 — verify this is actually correct, not a default.")

            # Check 4: Common period mistakes
            if "fiscal year" in q and "calendar" in q:
                warnings.append("Question mentions both fiscal and calendar year — verify which period you used.")
            if "end of" in q and "average" not in q and "mean" not in q:
                checks["period_type"] = "end-of-period (not average)"

            # Check 5: Period basis mismatch
            if evidence_table_pks:
                q_wants_fiscal = "fiscal" in q and "calendar" not in q
                q_wants_calendar = "calendar" in q and "fiscal" not in q
                for pk in evidence_table_pks[:3]:
                    try:
                        _pb = self._conn.execute(
                            "SELECT period_basis FROM table_index WHERE table_pk = ?", (int(pk),)
                        ).fetchone()
                        if _pb and _pb["period_basis"]:
                            pb = _pb["period_basis"]
                            if q_wants_fiscal and pb == "calendar":
                                warnings.append(f"⚠ PERIOD MISMATCH: Question asks for fiscal year but table pk={pk} uses calendar year data.")
                            elif q_wants_calendar and pb == "fiscal":
                                warnings.append(f"⚠ PERIOD MISMATCH: Question asks for calendar year but table pk={pk} uses fiscal year data.")
                    except Exception:
                        pass

            # Check 6: Footnote/revision awareness
            if evidence_values:
                has_preliminary = any("p" in str(v).lower() for v in evidence_values if isinstance(v, str))
                if has_preliminary and ("revised" in q or "final" in q):
                    warnings.append("⚠ REVISION: Evidence contains preliminary (p) values but question asks for revised/final data.")

            # Check 7: Magnitude sanity — catch obvious unit errors
            if ans_num is not None and evidence_values:
                ev_nums_check = []
                for ev in evidence_values:
                    try:
                        ev_nums_check.append(float(re.sub(r"[,$%]", "", str(ev))))
                    except (ValueError, TypeError):
                        pass
                if ev_nums_check:
                    # If answer is >1000x or <0.001x any evidence value, likely unit error
                    for ev_n in ev_nums_check:
                        if ev_n != 0:
                            ratio = abs(ans_num / ev_n) if ev_n != 0 else 0
                            if ratio > 1000 or (ratio > 0 and ratio < 0.001):
                                warnings.append(
                                    f"⚠ MAGNITUDE: answer={ans} vs evidence={ev_n} — "
                                    f"ratio={ratio:.1f}. Likely unit scaling error."
                                )
                                break

            # Check 8: Cross-table unit consistency
            if evidence_table_pks and len(evidence_table_pks) > 1:
                units_seen: dict[str, list[int]] = {}
                for pk in evidence_table_pks[:5]:
                    try:
                        row = self._conn.execute(
                            "SELECT units_line FROM table_index WHERE table_pk = ?", (int(pk),)
                        ).fetchone()
                        if row and row["units_line"]:
                            ul = row["units_line"].strip().lower()
                            units_seen.setdefault(ul, []).append(pk)
                    except Exception:
                        pass
                if len(units_seen) > 1:
                    warnings.append(
                        f"⚠ CROSS-TABLE UNITS: Evidence tables use different units: "
                        f"{list(units_seen.keys())}. Normalize before computing."
                    )

            verified = len(warnings) == 0
            return {
                "verified": verified,
                "checks": checks,
                "warnings": warnings,
                "action": "Write answer now." if verified else "Review warnings before writing.",
            }
        except Exception as exc:
            return {"verified": False, "checks": {}, "warnings": [str(exc)]}
