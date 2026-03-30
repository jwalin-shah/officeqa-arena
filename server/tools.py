"""Tool wrapper class for OfficeQA Arena.

Each method maps 1:1 to an MCP tool, returns a compact dict, and never raises.
"""

from __future__ import annotations

import json
import re
import sqlite3
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

    def get_fiscal_year_bounds(self, fiscal_year: int) -> dict:
        """U.S. federal fiscal year start/end dates."""
        try:
            return db.get_fiscal_year_bounds(year=fiscal_year)
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Mega tools (multi-step)
    # ------------------------------------------------------------------

    def extract_values(
        self,
        query: str,
        metric: str = "",
        year: int | None = None,
        month: int | None = None,
        top_k: int = 2,
    ) -> dict:
        """Search + fetch in one call. Finds tables matching query, fetches rows, returns compact results."""
        try:
            q = str(query or "").strip()
            if not q:
                return {"results": [], "error": "query is required"}
            m = str(metric or "").strip()
            mo = int(month) if month is not None else None
            k = max(1, min(int(top_k), 8))
            search_query = f"{q} {m}".strip() if m and m.lower() not in q.lower() else q
            yr_range = [int(year), int(year)] if year is not None else None

            # Step 1: Find tables (internal call — does NOT count against user's search budget)
            saved_count = self._search_call_count
            table_result = self.search_tables(query=search_query, year_range=yr_range, limit=k * 3)
            self._search_call_count = saved_count  # restore — mega-tool searches are free
            candidates = (table_result.get("candidates") or [])[:k]

            # Step 2: Query rows from each candidate in parallel
            targets = [
                (c.get("table_pk"), str(c.get("file_id") or ""), str(c.get("table_title") or ""), float(c.get("score") or 0.0))
                for c in candidates
            ]

            fetched: dict[int, dict] = {}
            for i, (pk, fid, title, _) in enumerate(targets):
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
                    # Column filter too strict — try row_label instead
                    kwargs.pop("column_label", None)
                    kwargs["row_label"] = m
                    result = self.query_table_rows(**kwargs)
                if not (result.get("rows")) and m:
                    # Both too strict — try without metric filter
                    kwargs.pop("row_label", None)
                    result = self.query_table_rows(**kwargs)
                fetched[i] = result

            # Step 3: Assemble results (preserve value_scaled + unit metadata)
            results = []
            for i, (pk, fid, title, score) in enumerate(targets):
                row_result = fetched.get(i, {"rows": []})
                rows = row_result.get("rows") or []
                table_info = row_result.get("table_info", {})
                if rows:
                    compact_rows = []
                    for r in rows[:5]:
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
                        compact_rows.append(cr)
                    entry: dict[str, Any] = {
                        "file_id": fid,
                        "table_title": title,
                        "table_pk": pk,
                        "score": score,
                        "rows": compact_rows,
                        "rows_returned": len(compact_rows),
                        "was_truncated": len(rows) > 5,
                    }
                    if table_info.get("units"):
                        entry["units"] = table_info["units"]
                        entry["unit_scale"] = table_info.get("unit_scale", 1)
                    results.append(entry)

            out: dict[str, Any] = {
                "results": results,
                "count": sum(len(r["rows"]) for r in results),
                "query": q,
            }
            if year is not None:
                out["year"] = year
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

                if len(series) > len(best_series):
                    best_series = series
                    best_table_pk = pk
                    best_table_title = title
                    best_file_id = fid

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
                out["action_hint"] = (
                    f"Got {len(best_series)} values ({granularity}). "
                    f"Use compute_expression() with these values (e.g. geometric_mean, mean, sum, linreg)."
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
        top_k: int = 2,
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
    ) -> dict:
        """Pre-write verification. Checks unit scale, value provenance, and common pitfalls.

        Call this BEFORE writing to /app/answer.txt. Returns pass/fail with specific repair guidance.
        """
        try:
            warnings: list[str] = []
            checks: dict[str, bool | str] = {}
            q = str(question or "").strip().lower()
            ans = str(candidate_answer or "").strip()
            claimed = str(units_claimed or "").strip().lower()

            if not ans:
                return {"verified": False, "checks": {}, "warnings": ["No candidate answer provided."]}

            # Parse numeric answer
            ans_num = None
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
                if ans_num is not None and ev_nums:
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

            verified = len(warnings) == 0
            return {
                "verified": verified,
                "checks": checks,
                "warnings": warnings,
                "action": "Write answer now." if verified else "Review warnings before writing.",
            }
        except Exception as exc:
            return {"verified": False, "checks": {}, "warnings": [str(exc)]}
