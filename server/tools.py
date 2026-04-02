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

_TOOL_REGISTRY: dict[str, dict[str, Any]] = {}

def tool(schema: dict[str, Any]):
    """Decorator to register an MCP tool schema."""
    def decorator(func):
        _TOOL_REGISTRY[func.__name__] = schema
        return func
    return decorator

class OfficeQATools:
    """Stateful tool bag backed by a single SQLite corpus DB."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection = db.open_db(db_path)
        self.reset_budgets()
        self._label_lookup_table = ""
        self._build_label_lookup()

    @staticmethod
    def get_tool_schemas() -> list[dict[str, Any]]:
        """Return the list of exposed MCP tool schemas.

        Only tools in this explicit list are registered with the MCP server.
        Underlying method implementations for hidden tools are preserved but
        not exposed to the agent directly.
        """
        _EXPOSED = [
            "route_question",
            "resolve_numeric_evidence",
            "search_data",
            "get_period_series",
            "get_time_series",
            "get_multi_year_series",
            "extract_values",
            "search_tables",
            "get_table_profile",
            "query_table_rows",
            "compute_expression",
            "submit_answer",
            "get_cpi_index",
            "get_exchange_rate",
        ]
        all_schemas = {s["name"]: s for s in _TOOL_REGISTRY.values()}
        return [all_schemas[name] for name in _EXPOSED if name in all_schemas]

    @staticmethod
    def _compact_result(result: dict, max_bytes: int = 8000) -> dict:
        """Truncate result dict if serialized size exceeds max_bytes."""
        serialized = json.dumps(result, default=str)
        if len(serialized) <= max_bytes:
            return result
        # Find the longest list field and truncate it
        list_fields = [(k, v) for k, v in result.items() if isinstance(v, list)]
        if not list_fields:
            return result
        list_fields.sort(key=lambda x: len(json.dumps(x[1], default=str)), reverse=True)
        for field_name, field_val in list_fields:
            if len(field_val) > 5:
                kept = field_val[:5]
                result[field_name] = kept
                result.setdefault("_truncation", {})[field_name] = {
                    "kept": len(kept),
                    "total": len(field_val),
                    "hint": "Use filters to narrow results"
                }
                serialized = json.dumps(result, default=str)
                if len(serialized) <= max_bytes:
                    return result
        return result

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
        self._best_verified_answer: str | None = None
        self._last_computed: str | None = None
        self._last_extracted_value: str | None = None
        
        self._path: str = "unknown"
        self._router_plan: dict = {}
        self._calls: dict[str, int] = defaultdict(int)
        self._budgets: dict[str, int] = {
            "search_tables": 4, 
            "get_table_profile": 4, 
            "query_table_rows": 6, 
            "total": 12
        }
        self._spin_signals: dict[str, int] = {
            "no_new_evidence_streak": 0,
            "repeated_table_family": 0
        }
        self._seen_evidence: set[str] = set()

    def _check_budget(self, tool_name: str) -> dict | None:
        self._calls[tool_name] += 1
        self._calls["total"] += 1
        
        if self._calls["total"] > self._budgets.get("total", 12):
            return {"error": "Total tool budget exceeded. Submit best answer now."}
            
        limit = self._budgets.get(tool_name)
        if limit is not None and self._calls[tool_name] > limit:
            return {"error": f"Budget for {tool_name} exceeded ({limit} max). Switch strategy."}
            
        return None

    @tool({
        "name": "route_question",
        "description": "DO THIS FIRST. Classify the question and pick a path (ledger, table, or unsupported) before searching.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question_type": {"type": "string", "enum": ["lookup", "comparison", "time_series", "aggregation", "table_structure", "visual"]},
                "preferred_path": {"type": "string", "enum": ["ledger", "table", "unsupported"]},
                "target_metric": {"type": "string"},
                "years": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["question_type", "preferred_path"]
        }
    })
    def route_question(self, question_type: str, preferred_path: str, target_metric: str = "", years: list[int] = None) -> dict:
        """Initialize the routing plan and enforce budgets."""
        self._router_plan = {
            "type": question_type,
            "path": preferred_path,
            "metric": target_metric,
            "years": years
        }
        self._path = preferred_path
        
        if preferred_path == "ledger":
            self._budgets = {"total": 6, "search_tables": 2, "get_table_profile": 1, "query_table_rows": 2}
            return {"status": "routed", "path": "ledger", "instruction": "Use search_ledger or get_time_series. DO NOT use search_tables unless ledger fails."}
        elif preferred_path == "table":
            self._budgets = {"total": 8, "search_tables": 2, "get_table_profile": 2, "query_table_rows": 3}
            return {"status": "routed", "path": "table", "instruction": "Use search_tables -> get_table_profile -> query_table_rows."}
        else:
            self._budgets = {"total": 1}
            return {"status": "aborted", "instruction": "Submit [UNANSWERABLE: VISUAL] immediately."}

    # ------------------------------------------------------------------
    # Retrieval tools
    # ------------------------------------------------------------------

    @tool({
        "name": "search_tables",
        "description": "Find tables by keyword. LAST RESORT — only after resolve_numeric_evidence and search_data fail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms (e.g., 'public works expenditures')"},
                "file_id": {"type": "string", "description": "Restrict to one bulletin file (e.g., '1941_01')"},
                "year_range": {"type": "array", "items": {"type": "integer"}, "description": "[start_year, end_year]"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["query"],
        },
    })
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
            if self._search_call_count > 4:
                return {
                    "candidates": [],
                    "count": 0,
                    "budget_exceeded": True,
                    "warning": (
                        f"search_tables called {self._search_call_count} times (budget: 4). "
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

    @tool({
        "name": "query_table_rows",
        "description": "Get specific cells from a table. Use exact labels from get_table_profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table_pk": {"type": "integer", "description": "Table primary key from search_tables"},
                "file_id": {"type": "string"},
                "table_title": {"type": "string"},
                "row_label": {"type": "string", "description": "Filter rows containing this text"},
                "column_label": {"type": "string", "description": "Filter to this column (use exact name from get_table_profile)"},
                "year": {"type": "integer", "description": "Single year filter"},
                "year_range": {"type": "array", "items": {"type": "integer"}, "description": "[start, end] for multi-year"},
                "month": {"type": "integer"},
                "limit": {"type": "integer", "description": "Max rows (default 50)"},
            },
        },
    })
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
        budget_err = self._check_budget("query_table_rows")
        if budget_err: return budget_err
        try:
            result = db.query_table_rows(
                self._conn, table_pk=table_pk, file_id=file_id,
                table_title=table_title, row_label=row_label,
                column_label=column_label, year=year,
                year_range=year_range, month=month, limit=limit,
            )
            rows = result.get("rows", [])

            # Detect tables where year/month are not indexed — guide agent to use row_label
            if isinstance(rows, list) and rows and (year is not None or month is not None):
                null_year_count = sum(1 for r in rows if r.get("year") is None)
                if null_year_count == len(rows):
                    return {
                        "error": "TEMPORAL METADATA MISSING",
                        "hint": "year/month are null for all rows in this table. Re-call using row_label to match the target date directly (e.g. row_label='December 1938')."
                    }

            compact_matches = []
            
            # Find the best unit scale and label from the table info if available
            tbl_info = result.get("table_info", {})
            unit_val = tbl_info.get("units", "")
            
            for r in rows:
                scale = r.get("unit_scale", 1)
                
                # Format date string
                y = r.get("year")
                m = r.get("month")
                date_str = ""
                if y:
                    date_str = str(y)
                    if m:
                        date_str += f"-{int(m):02d}"

                match_reason = []
                if row_label and row_label.lower() in str(r.get("row_label", "")).lower():
                    match_reason.append("row match")
                if column_label and column_label.lower() in str(r.get("column_label", "")).lower():
                    match_reason.append("column match")

                match_info = {
                    "row_label": r.get("row_label"),
                    "column": r.get("column_label"),
                    "raw_value": r.get("value_raw"),
                    "normalized_value": r.get("normalized_value"),
                    "unit": unit_val,
                    "scale": scale,
                    "date": date_str,
                    "match_reason": " + ".join(match_reason) if match_reason else "filter match"
                }
                compact_matches.append(match_info)

            # Cap rows directly to ensure it never blows up context
            if len(compact_matches) > 10:
                original_count = len(compact_matches)
                compact_matches = compact_matches[:10]
                return {
                    "table_id": f"tbl_{table_pk or result.get('table_info', {}).get('table_pk')}",
                    "matches": compact_matches,
                    "total_matches": original_count,
                    "truncation_warning": "Too many matches. Use row_label and column_label filters to narrow."
                }

            return {
                "table_id": f"tbl_{table_pk or result.get('table_info', {}).get('table_pk')}",
                "matches": compact_matches
            }
        except Exception as exc:
            return {"error": str(exc)}

    @tool({
        "name": "get_file_structure",
        "description": "List all tables in a bulletin file with titles and row/column counts. Use file_id like '1941_01'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Bulletin file ID (e.g., '1941_01' or 'treasury_bulletin_1941_01.txt')"},
            },
            "required": ["file_id"],
        },
    })
    def get_file_structure(self, file_id: str) -> dict:
        """Return all table titles and metadata for a bulletin issue."""
        try:
            result = db.get_file_structure(self._conn, file_id=file_id)
            tables = result.get("tables")
            if isinstance(tables, list) and len(tables) > 15:
                original_count = len(tables)
                result["tables"] = tables[:15]
                result["total_tables"] = original_count
                result["truncated"] = True
                result["hint"] = "Use search_tables(query=...) to find specific tables instead of browsing all."
            return self._compact_result(result)
        except Exception as exc:
            return {"error": str(exc)}

    @tool({
        "name": "get_table_profile",
        "description": "Check columns, units, year coverage for a table. Call to verify units before computing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table_pk": {"type": "integer", "description": "Table primary key"},
                "verbose": {"type": "boolean", "description": "If true, return all column labels and more row samples. Default false."},
            },
            "required": ["table_pk"],
        },
    })
    def get_table_profile(self, table_pk: int, verbose: bool = False) -> dict:
        """Inspect table schema, columns, and row/year coverage."""
        try:
            p = db.get_table_profile(self._conn, table_pk=table_pk)
            
            # Map db profile to the exact compact schema
            compact_profile = {
                "table_id": f"tbl_{table_pk}",
                "title": p.get("table_title", ""),
                "doc": p.get("file_id", ""),
                "unit": p.get("units", ""),
                "scale": p.get("unit_scale", 1),
                "row_count": p.get("row_count", 0),
                "column_headers": p.get("columns", []),
                "sample_row_labels": p.get("row_label_samples", []),
                "year_coverage": [p.get("min_year"), p.get("max_year")] if p.get("min_year") is not None else [],
                "granularity": "monthly" if p.get("has_month_rows") else "annual",
            }
            
            if not verbose:
                # Truncate aggressively for non-verbose calls to save context
                if len(compact_profile["column_headers"]) > 8:
                    compact_profile["column_headers"] = compact_profile["column_headers"][:8]
                    compact_profile["_column_truncation_hint"] = "Set verbose=True to see all column labels"
                
                if len(compact_profile["sample_row_labels"]) > 5:
                    compact_profile["sample_row_labels"] = compact_profile["sample_row_labels"][:5]

            return compact_profile
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------

    @tool({
        "name": "compute_expression",
        "description": "REQUIRED for ALL arithmetic. Never compute in your head. Supports sum, mean, cagr, stdev, correlation, linreg, geometric_mean, median, variance, percentile, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression (e.g., 'a - b', 'geometric_mean(1,2,3)')"},
                "variables": {"type": "object", "description": "Variable values (e.g., {\"a\": 494, \"b\": 154})"},
            },
            "required": ["expression"],
        },
    })
    def compute_expression(
        self,
        expression: str,
        variables: dict | None = None,
    ) -> dict:
        """Deterministic arithmetic evaluator."""
        try:
            clean_vars = {k: float(v) for k, v in (variables or {}).items()}
            result = safe_eval_finance(expression, clean_vars)
            self._last_computed = str(result)
            return {"ok": True, "result": result}
        except (ValueError, SyntaxError, TypeError, ZeroDivisionError) as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Reference data
    # ------------------------------------------------------------------

    @tool({
        "name": "get_cpi_index",
        "description": "CPI-U index (1982-84=100) for inflation adjustment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["year"],
        },
    })
    def get_cpi_index(self, year: int, month: int | None = None) -> dict:
        """CPI-U annual or monthly index value (1982-84=100)."""
        try:
            return db.get_cpi_index(self._conn, year=year, month=month)
        except Exception as exc:
            return {"error": str(exc)}

    @tool({
        "name": "get_exchange_rate",
        "description": "Historical FX rates for currency conversion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pair": {"type": "string", "description": "Currency pair, e.g. 'USD/JPY' (yen per dollar), 'USD/GBP' (dollars per pound)"},
                "year": {"type": "integer"},
                "month": {"type": "integer"},
                "day": {"type": "integer"},
            },
            "required": ["pair", "year"],
        },
    })
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

    @tool({
        "name": "get_fiscal_year_bounds",
        "description": "Get start/end dates for a U.S. federal fiscal year.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fiscal_year": {"type": "integer"},
            },
            "required": ["fiscal_year"],
        },
    })
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
                rows = []
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

    @tool({
        "name": "extract_values",
        "description": "Search and fetch with full table rows. Use when other tools return empty.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for (e.g., 'national defense expenditures')"},
                "metric": {"type": "string", "description": "Specific metric/column to extract (e.g., 'National defense')"},
                "year": {"type": "integer", "description": "Target year"},
                "month": {"type": "integer", "description": "Target month (1-12)"},
                "top_k": {"type": "integer", "description": "Number of candidate tables to check (default 2)"},
            },
            "required": ["query"],
        },
    })
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

            total_candidates = len(results)
            truncated_candidates = total_candidates > 3
            if truncated_candidates:
                results = results[:3]

            out: dict[str, Any] = {
                "results": results,
                "count": sum(len(r["rows"]) for r in results),
                "query": q,
            }
            if truncated_candidates:
                out["truncated"] = True
                out["total_candidates"] = total_candidates
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
                    # Track for fallback answer
                    if verdict_val is not None:
                        self._last_extracted_value = str(verdict_val)

            if not results:
                out["hint"] = (
                    "No matching tables found. Try: "
                    "1) search_tables with different keywords, "
                    "2) get_table_profile on a known table_pk, "
                    "3) grep_corpus(pattern='| keyword |', file_id='YYYY_MM') as last resort."
                )
            return self._compact_result(out)
        except Exception as exc:
            return {"results": [], "error": str(exc)}

    @tool({
        "name": "search_ledger",
        "description": "Search Master Ledger by metric slug. Returns pre-extracted time-series values. Good for known metric names like 'national defense', 'total receipts', 'customs'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "Metric name (e.g., 'customs', 'national defense', 'total receipts')"},
                "year": {"type": "integer", "description": "Single year to look up"},
                "period_basis": {"type": "string", "enum": ["calendar", "fiscal", "monthly", "annual", ""], "description": "Period type: 'calendar' for CY, 'fiscal' for FY, 'monthly' for individual months, 'annual' for FY totals. Leave empty for all."},
                "years": {"type": "array", "items": {"type": "integer"}, "description": "Multiple years for comparison (e.g., [1940, 1941])"},
            },
            "required": ["metric"],
        },
    })
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

            raw_results = sorted(seen.values(), key=lambda x: x["time_key"])

            # Get units from the source table
            units = ""
            scale = 1
            if raw_results:
                pk = raw_results[0]["table_pk"]
                ti = self._conn.execute(
                    "SELECT units_line FROM table_index WHERE table_pk = ?", (pk,)
                ).fetchone()
                units = ti["units_line"] if ti and ti["units_line"] else ""
                
                if "thousand" in str(units).lower():
                    scale = 1000
                elif "million" in str(units).lower():
                    scale = 1000000
                elif "billion" in str(units).lower():
                    scale = 1000000000

            # Capture first result value for fallback auto-submit
            if raw_results and raw_results[0].get("value") is not None:
                self._last_extracted_value = str(raw_results[0]["value"])

            compact_matches = []
            for r in raw_results[:5]: # Return only top matches
                # Extract year from time_key if possible
                year_match = re.search(r'\d{4}', r["time_key"])
                year_val = int(year_match.group(0)) if year_match else None
                
                compact_matches.append({
                    "metric": r["metric"],
                    "entity": None,
                    "year": year_val,
                    "time_key": r["time_key"],
                    "value": r["value"],
                    "unit": units,
                    "scale": scale,
                    "basis": r["period_basis"],
                    "source_table_id": f"tbl_{r['table_pk']}",
                    "source_doc": r["source"],
                    "match_score": 0.95 if metric_norm == r["metric"] else 0.8,
                    "match_reason": "exact metric match" if metric_norm == r["metric"] else "fuzzy match"
                })

            return {
                "matches": compact_matches,
                "count": len(compact_matches),
            }
        except Exception as exc:
            return {"matches": [], "error": str(exc)}

    @tool({
        "name": "search_canonical",
        "description": "SECONDARY — Search canonical fact store (935K deduplicated facts). Use SHORT queries (2-4 keywords). Include table_family when known for 75% hit rate. Falls back: if empty after 2 tries, switch to search_tables.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms (e.g., 'income tax', 'public debt outstanding', 'savings bonds sales')"},
                "year": {"type": "integer", "description": "Single year filter"},
                "years": {"type": "array", "items": {"type": "integer"}, "description": "Multiple years (e.g., [1938, 1939, 1940])"},
                "table_family": {"type": "string", "description": "Filter by family: public_debt, revenue_receipts, federal_securities, international_capital, monetary, cash_operations, budget_expenditures"},
                "limit": {"type": "integer", "description": "Max results (default 15)"},
            },
            "required": ["query"],
        },
    })
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

            total_results = len(results)
            truncated = total_results > 8
            if truncated:
                results = results[:8]

            out = {
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
            if truncated:
                out["truncated"] = True
                out["total_results"] = total_results

            # Capture first result value for fallback auto-submit
            if results and results[0].get("value") is not None:
                self._last_extracted_value = str(results[0]["value"])

            # ── Auto-fallback: if canonical returns nothing, try extract_values ──
            if not results:
                fb_year = yr_list[0] if yr_list else None
                fb = self.extract_values(
                    query=str(query or "").strip(),
                    metric="",
                    year=fb_year,
                    top_k=5,
                )
                fb_results = fb.get("results") or []
                if fb_results:
                    out["results"] = fb_results
                    out["count"] = len(fb_results)
                    out["fallback_path"] = "extract_values"
                    out["hint"] = (
                        "No canonical facts matched. These results come from "
                        "raw table search (extract_values fallback)."
                    )
                    # Capture first result for auto-submit
                    first_val = None
                    for fbr in fb_results:
                        for row in fbr.get("rows", []):
                            v = row.get("value_raw") or row.get("normalized_value")
                            if v is not None:
                                first_val = str(v)
                                break
                        if first_val:
                            break
                    if first_val:
                        self._last_extracted_value = first_val

            return self._compact_result(out)
        except Exception as exc:
            return {"results": [], "error": str(exc)}

    @tool({
        "name": "search_data",
        "description": "FALLBACK search — only use after resolve_numeric_evidence returns no_data. Searches canonical facts and master ledger.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms (e.g., 'national defense expenditures')"},
                "year": {"type": "integer", "description": "Single year filter"},
                "years": {"type": "array", "items": {"type": "integer"}, "description": "Multiple years (e.g., [1938, 1939, 1940])"},
                "period_basis": {"type": "string", "enum": ["calendar", "fiscal", "monthly", "annual", ""], "description": "Period type: 'calendar', 'fiscal', 'monthly', 'annual', or empty for all"},
                "table_family": {"type": "string", "description": "Filter by family: public_debt, revenue_receipts, federal_securities, international_capital, monetary, cash_operations, budget_expenditures"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["query"],
        },
    })
    def search_data(
        self,
        query: str,
        year: int | None = None,
        years: list[int] | None = None,
        period_basis: str = "",
        table_family: str = "",
        limit: int = 10,
    ) -> dict:
        """Unified search across canonical facts and master ledger.

        Tries canonical first, then ledger. Returns combined results with
        source labeled ("canonical" or "ledger").
        Use after resolve_numeric_evidence returns no_data.
        """
        canonical_results: list[dict] = []
        canonical_error: str = ""
        ledger_results: list[dict] = []
        ledger_error: str = ""

        # --- Try canonical first ---
        try:
            canon_out = self.search_canonical(
                query=query,
                year=year,
                years=years,
                table_family=table_family,
                limit=limit,
            )
            raw = canon_out.get("results") or []
            for r in raw:
                r["_source"] = "canonical"
            canonical_results = raw
            if canon_out.get("error"):
                canonical_error = str(canon_out["error"])
        except Exception as exc:
            canonical_error = str(exc)

        # --- Try ledger if canonical returned nothing ---
        if not canonical_results:
            try:
                ledger_out = self.search_ledger(
                    metric=query,
                    year=year,
                    period_basis=period_basis,
                    years=years,
                )
                raw = ledger_out.get("results") or []
                for r in raw:
                    r["_source"] = "ledger"
                ledger_results = raw
                if ledger_out.get("error"):
                    ledger_error = str(ledger_out["error"])
            except Exception as exc:
                ledger_error = str(exc)

        combined = canonical_results or ledger_results
        out: dict[str, Any] = {
            "results": combined,
            "count": len(combined),
            "query": query,
            "source": "canonical" if canonical_results else ("ledger" if ledger_results else "none"),
        }
        if canonical_error:
            out["canonical_error"] = canonical_error
        if ledger_error:
            out["ledger_error"] = ledger_error
        if not combined:
            out["hint"] = (
                "No results from canonical or ledger. Try extract_values or search_tables."
            )

        # Track first result value for fallback
        if combined and combined[0].get("value") is not None:
            self._last_extracted_value = str(combined[0]["value"])

        return self._compact_result(out)

    @tool({
        "name": "get_time_series",
        "description": "Contiguous multi-year series. Always specify period_basis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "Metric to track (e.g., 'total receipts')"},
                "year_start": {"type": "integer", "description": "Start year"},
                "year_end": {"type": "integer", "description": "End year"},
                "period_basis": {"type": "string", "enum": ["calendar", "fiscal"], "description": "CRITICAL: Set to 'calendar' or 'fiscal' based on the question context. Defaults to calendar."},
                "query": {"type": "string", "description": "Optional broader search terms"},
                "file_id": {"type": "string", "description": "Restrict to one bulletin file"},
                "month_start": {"type": "integer", "description": "Filter: start month (1-12)"},
                "month_end": {"type": "integer", "description": "Filter: end month (1-12)"},
                "top_k": {"type": "integer", "description": "Tables to check (default 3)"},
            },
            "required": ["metric", "year_start", "year_end"],
        },
    })
    def get_time_series(
        self,
        metric: str,
        year_start: int,
        year_end: int,
        period_basis: str = "calendar",
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
                # ── Fallback: try canonical_facts for the year range ──
                canon_series: dict[str, Any] = {}
                canon_source = ""
                try:
                    canon = self.search_canonical(
                        query=search_q,
                        years=list(range(yr_start, yr_end + 1)),
                        limit=50,
                    )
                    for cr in canon.get("results") or []:
                        yr_val = cr.get("year")
                        mo_val = cr.get("month")
                        val = cr.get("value")
                        if yr_val is not None and val is not None:
                            if mo_val:
                                pk = f"{yr_val}-{int(mo_val):02d}"
                            else:
                                pk = str(yr_val)
                            if pk not in canon_series:
                                canon_series[pk] = val
                    if canon_series and not canon_source:
                        first = (canon.get("results") or [{}])[0]
                        canon_source = first.get("table_title", "")
                except Exception:
                    pass

                if canon_series:
                    requested_years = list(range(yr_start, yr_end + 1))
                    found_years = set()
                    for k in canon_series:
                        yr_m = re.match(r"^(\d{4})", str(k))
                        if yr_m:
                            found_years.add(int(yr_m.group(1)))
                    return {
                        "metric": m,
                        "table_title": canon_source,
                        "series": canon_series,
                        "count": len(canon_series),
                        "fallback_path": "canonical_facts",
                        "coverage": {
                            "requested_years": requested_years,
                            "found": len(found_years),
                            "missing_years": [y for y in requested_years if y not in found_years],
                        },
                    }

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

            # Pick the candidate with the most year/key coverage as primary
            if all_candidate_series:
                def _coverage_score(item: tuple) -> int:
                    _, _, _, s = item
                    monthly = sum(1 for k in s if "-" in str(k))
                    # Monthly granularity beats annual: weight monthly keys higher
                    return monthly * 1000 + len(s)

                best_item = max(all_candidate_series, key=_coverage_score)
                best_table_pk, best_file_id, best_table_title, best_series = best_item

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

            compact_series = []
            for k, v in best_series.items():
                compact_series.append({"period": k, "value": v})

            out: dict[str, Any] = {
                "metric": m,
                "basis": period_basis,
                "unit": best_units,
                "scale": best_unit_scale,
                "series": compact_series,
                "source_summary": {
                    "source_count": len(all_candidate_series) if all_candidate_series else 1,
                    "confidence": 0.9 if len(found_years) == len(requested_years) else 0.5,
                    "missing_years": missing_years,
                }
            }

            return out
        except Exception as exc:
            return {"series": {}, "error": str(exc)}

    @tool({
        "name": "get_multi_year_series",
        "description": "Non-contiguous years. Always specify period_basis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "Metric to track (e.g., 'national defense expenditures')"},
                "years": {"type": "array", "items": {"type": "integer"}, "description": "List of years to fetch"},
                "period_basis": {"type": "string", "enum": ["calendar", "fiscal"], "description": "CRITICAL: Set to 'calendar' or 'fiscal' based on the question context. Defaults to calendar."},
                "top_k": {"type": "integer", "description": "Tables to check per year (default 2)"},
            },
            "required": ["metric", "years"],
        },
    })
    def get_multi_year_series(
        self,
        metric: str,
        years: list[int],
        top_k: int = 3,
        period_basis: str = "",
    ) -> dict:
        """Extract a time-series for a metric across multiple years in one call.

        Uses ONE search + ONE range query (does not burn search budget per year).
        If period_basis is "calendar" or "fiscal", queries master_ledger CY/FY
        totals directly for accurate period-specific values.
        """
        try:
            m = str(metric or "").strip()
            if not m:
                return {"series": {}, "error": "metric is required"}
            yrs = sorted({int(y) for y in years if str(y).strip()})
            if not yrs:
                return {"series": {}, "error": "years are required"}

            pb = str(period_basis or "").strip().lower()

            # --- Fast path: use master_ledger CY/FY totals directly ---
            if pb in ("calendar", "fiscal"):
                metric_norm = self._normalize_metric_slug(m)
                if pb == "calendar":
                    time_keys = [f"CY{y}" for y in yrs]
                    row_types = ('synthetic_cy_total',)
                else:
                    time_keys = [f"FY{y}" for y in yrs] + [str(y) for y in yrs]
                    row_types = ('synthetic_fy_total', 'annual_total')

                ledger_rows = self._broad_slug_search(metric_norm, time_keys, row_types)

                if ledger_rows:
                    # Group by table_title, pick latest bulletin per year
                    from collections import defaultdict
                    title_series: dict[str, dict] = {}  # title -> {year: {value, src}}

                    for r in ledger_rows:
                        ttitle = str(r["table_title"]) if "table_title" in r.keys() else ""
                        if not ttitle:
                            ts = self._conn.execute(
                                "SELECT table_title FROM table_summary WHERE table_pk = ?",
                                (r["table_pk"],)
                            ).fetchone()
                            ttitle = str(ts["table_title"]) if ts else ""

                        tk = str(r["time_key"])
                        src = str(r["source_file"] or "")
                        val = r["value"]

                        # Extract year from time_key (CY1940 -> 1940, FY1940 -> 1940)
                        yr_match = re.search(r'(\d{4})', tk)
                        if not yr_match:
                            continue
                        yr_val = int(yr_match.group(1))
                        if yr_val not in yrs:
                            continue

                        if ttitle not in title_series:
                            title_series[ttitle] = {}
                        existing = title_series[ttitle].get(yr_val)
                        if existing is None or src > existing["src"]:
                            title_series[ttitle][yr_val] = {"value": val, "src": src}

                    # Pick the table with most year coverage
                    if title_series:
                        best_title = max(title_series, key=lambda t: len(title_series[t]))
                        best = title_series[best_title]
                        series: dict[int, Any] = {}
                        for y in yrs:
                            if y in best:
                                series[y] = {"value": best[y]["value"]}

                        # Get units from one of the table_pks
                        sample_row = ledger_rows[0]
                        ts_meta = self._conn.execute(
                            "SELECT units_line FROM table_summary WHERE table_pk = ?",
                            (sample_row["table_pk"],)
                        ).fetchone()

                        out: dict[str, Any] = {
                            "metric": m,
                            "years": yrs,
                            "series": series,
                            "count": len(series),
                            "table_title": best_title,
                            "period_basis": pb,
                            "missing_years": [y for y in yrs if y not in series],
                        }
                        if ts_meta and ts_meta["units_line"]:
                            out["units"] = str(ts_meta["units_line"])
                        return out

            # --- Fallback: delegate to get_time_series ---
            yr_start, yr_end = min(yrs), max(yrs)
            ts_result = self.get_time_series(
                metric=m, year_start=yr_start, year_end=yr_end, top_k=top_k,
            )

            # Filter to only requested years
            full_series = ts_result.get("series", {})
            series = {}
            for y in yrs:
                # Check annual key (str(y)) or monthly keys (y-MM)
                if str(y) in full_series:
                    series[y] = {"value": full_series[str(y)]}
                else:
                    # Collect monthly values for this year
                    monthly = {k: v for k, v in full_series.items() if k.startswith(f"{y}-")}
                    if monthly:
                        series[y] = {"monthly_values": monthly}

            out = {
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
            cmd = f"grep -n {flag} -- {json.dumps(p)} {target} | head -{max(1, min(int(max_lines), 20))}"
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
            return self._compact_result(result)
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

    @tool({
        "name": "verify_answer",
        "description": "MANDATORY — call this BEFORE writing /app/answer.txt. Checks unit scale, value provenance, and common pitfalls. Returns warnings if answer likely has errors. Never skip this step.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The original question text"},
                "candidate_answer": {"type": "string", "description": "Your proposed answer (number or text)"},
                "evidence_table_pks": {"type": "array", "items": {"type": "integer"}, "description": "Table PKs you extracted data from"},
                "evidence_values": {"type": "array", "items": {"type": "string"}, "description": "Key values you extracted from tables"},
                "units_claimed": {"type": "string", "description": "What units you believe the answer is in"},
            },
            "required": ["question", "candidate_answer"],
        },
    })
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
            # NOTE: A table with period_basis="fiscal" can still contain
            # synthetic CY totals (and vice versa), so only warn if the table
            # has NO data at all for the requested basis.
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
                            if q_wants_calendar and pb == "fiscal":
                                # Check if this table actually has CY totals
                                has_cy = self._conn.execute(
                                    "SELECT 1 FROM master_ledger WHERE table_pk = ? "
                                    "AND row_type = 'synthetic_cy_total' LIMIT 1",
                                    (int(pk),)
                                ).fetchone()
                                if not has_cy:
                                    warnings.append(
                                        f"⚠ PERIOD MISMATCH: Question asks for calendar year "
                                        f"but table pk={pk} uses fiscal year data and has no CY totals."
                                    )
                            elif q_wants_fiscal and pb == "calendar":
                                has_fy = self._conn.execute(
                                    "SELECT 1 FROM master_ledger WHERE table_pk = ? "
                                    "AND row_type = 'synthetic_fy_total' LIMIT 1",
                                    (int(pk),)
                                ).fetchone()
                                if not has_fy:
                                    warnings.append(
                                        f"⚠ PERIOD MISMATCH: Question asks for fiscal year "
                                        f"but table pk={pk} uses calendar year data and has no FY totals."
                                    )
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

            # Check 9: Date match — verify evidence dates match question
            date_patterns = re.findall(
                r'(?:as of|on|for|ending|dated?)\s+'
                r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})',
                q, re.IGNORECASE
            )
            if date_patterns and evidence_table_pks:
                for pk in evidence_table_pks[:3]:
                    try:
                        row = self._conn.execute(
                            "SELECT source_file, bulletin_date FROM table_index WHERE table_pk = ?", (int(pk),)
                        ).fetchone()
                        if row:
                            # Extract month from source_file (e.g., "treasury_bulletin_1990_09")
                            sf = str(row["source_file"] or "")
                            match_sf = re.search(r'(\d{4})_(\d{2})', sf)
                            if match_sf:
                                src_month = int(match_sf.group(2))
                                # Check if requested date's month is plausibly in this bulletin
                                for dp in date_patterns:
                                    req_month_match = re.match(r'(January|February|March|April|May|June|July|August|September|October|November|December)', dp, re.IGNORECASE)
                                    if req_month_match:
                                        month_names = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
                                                     "july":7,"august":8,"september":9,"october":10,"november":11,"december":12}
                                        req_month = month_names.get(req_month_match.group(1).lower(), 0)
                                        # Bulletin typically contains data from its quarter or prior quarter
                                        # If requested month differs by >3 months from bulletin, warn
                                        diff = abs(req_month - src_month)
                                        if diff > 3 and diff < 9:  # allow wrapping (e.g., Dec bulletin has Dec data)
                                            warnings.append(
                                                f"DATE MISMATCH: Question asks for data as of {dp}, "
                                                f"but evidence table pk={pk} is from bulletin {sf}. "
                                                f"Verify this bulletin actually contains the requested date's data."
                                            )
                    except Exception:
                        pass

            # Check 10: Scope match — "within and outside" vs partial
            scope_keywords = {
                "within and outside": ["within", "outside"],
                "domestic and foreign": ["domestic", "foreign"],
                "total": [],
            }
            for scope_phrase, required_parts in scope_keywords.items():
                if scope_phrase in q and required_parts and evidence_table_pks:
                    for pk in evidence_table_pks[:3]:
                        try:
                            row = self._conn.execute(
                                "SELECT table_title FROM table_index WHERE table_pk = ?", (int(pk),)
                            ).fetchone()
                            if row and row["table_title"]:
                                title_lower = str(row["table_title"]).lower()
                                has_all = all(part in title_lower for part in required_parts)
                                has_partial = any(part in title_lower for part in required_parts) and not has_all
                                if has_partial:
                                    warnings.append(
                                        f"SCOPE MISMATCH: Question asks for '{scope_phrase}' but "
                                        f"table pk={pk} title '{row['table_title']}' appears to cover only "
                                        f"a partial scope. Find the combined table."
                                    )
                        except Exception:
                            pass

            # Check 11: Aggressive unit scaling detection for Treasury-scale questions
            if ans_num is not None and evidence_table_pks:
                for pk in evidence_table_pks[:3]:
                    try:
                        row = self._conn.execute(
                            "SELECT units_line, table_title FROM table_index WHERE table_pk = ?", (int(pk),)
                        ).fetchone()
                        if row and row["units_line"]:
                            ul = str(row["units_line"]).lower()
                            if "thousand" in ul and ans_num < 1_000_000:
                                # Treasury values in thousands that are < 1M likely need scaling
                                warnings.append(
                                    f"LIKELY UNIT ERROR: Table pk={pk} reports values in thousands, "
                                    f"but your answer ({ans}) is < 1,000,000. "
                                    f"Did you forget to multiply by 1,000? "
                                    f"Suggested fix: multiply answer by 1,000 → {ans_num * 1000:,.0f}"
                                )
                                checks["suggested_fix"] = f"multiply by 1000 → {ans_num * 1000:,.0f}"
                    except Exception:
                        pass

            # Check 12: Row hierarchy — warn if "Total" row used for sub-item question or vice versa
            if evidence_values:
                q_asks_total = any(w in q for w in ["total", "aggregate", "sum of all", "grand total"])
                q_asks_specific = not q_asks_total and any(w in q for w in [
                    "customs", "individual income", "corporation income", "estate", "gift tax",
                    "excise", "employment", "interest", "principal"
                ])
                # Check if evidence contains "Total" markers
                ev_has_total = any("total" in str(v).lower() for v in evidence_values if isinstance(v, str))
                if q_asks_specific and ev_has_total:
                    warnings.append(
                        "ROW HIERARCHY: Question asks for a specific sub-item, but evidence "
                        "may include a 'Total' row. Verify you selected the correct row."
                    )

            verified = len(warnings) == 0
            
            # Map string warnings to structured warnings
            structured_warnings = []
            max_severity = "low"
            for w in warnings:
                sev = "high" if ("⚠" in w or "MISMATCH" in w or "ERROR" in w) else "low"
                if sev == "high": max_severity = "high"
                
                w_type = "general"
                if "UNIT" in w or "SCALE" in w: w_type = "unit_mismatch"
                elif "PERIOD" in w or "DATE" in w: w_type = "period_mismatch"
                elif "HIERARCHY" in w or "SCOPE" in w: w_type = "scope_mismatch"
                
                structured_warnings.append({
                    "type": w_type,
                    "severity": sev,
                    "message": w.replace("⚠ ", "")
                })
            
            # Track best verified answer for fallback
            if max_severity == "low":
                self._best_verified_answer = ans
                
            return {
                "is_consistent": verified,
                "severity": max_severity if structured_warnings else "none",
                "checks": checks,
                "warnings": structured_warnings
            }
        except Exception as exc:
            return {"is_consistent": False, "severity": "high", "checks": {}, "warnings": [{"type": "error", "severity": "high", "message": str(exc)}]}

    @tool({
        "name": "submit_answer",
        "description": "FINAL STEP — submits answer and auto-verifies. Call when you have a computed value. If budget is exhausted, call this to auto-finalize best answer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "The final numeric answer to write (e.g., '494.32'). If empty, finalizer logic will pick the best available evidence."},
                "question": {"type": "string", "description": "The original question text (required for auto-verification)"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"], "description": "Confidence level (default: high)"},
            },
            "required": ["question"],
        },
    })
    def submit_answer(
        self, question: str, answer: str = "", confidence: str = "high"
    ) -> dict:
        """Write answer to /app/answer.txt with automatic verification."""
        try:
            ans = str(answer or "").strip()
            source = "explicit"
            if not ans or "unanswerable" in ans.lower() or "abstain" in ans.lower():
                # 1. Prefer compute_expression.result
                if getattr(self, '_last_computed', None) is not None:
                    ans = str(self._last_computed)
                    source = "compute"
                # 2. Else prefer best row extraction value
                elif getattr(self, '_last_extracted_value', None) is not None:
                    ans = str(self._last_extracted_value)
                    source = "extraction"
                # 3. Else prefer best previously verified answer
                elif getattr(self, '_best_verified_answer', None) is not None:
                    ans = str(self._best_verified_answer)
                    source = "fallback_verified"
                else:
                    ans = "[UNANSWERABLE: VISUAL]" if getattr(self, '_path', "") == "unsupported" else "0"
                    source = "abstain"

            # ── Internal Auto-Verification ──
            v_res = self.verify_answer(question=question, candidate_answer=ans)
            if source == "explicit" and v_res.get("warnings") and getattr(self, '_search_call_count', 0) < getattr(self, '_MAX_BUDGET', 12) - 2:
                has_severe = any(w.get("severity") == "high" for w in v_res.get("warnings", [])) if isinstance(v_res.get("warnings"), list) and isinstance(v_res.get("warnings", [{}])[0], dict) else True
                if has_severe:
                    return {
                        "status": "REJECTED_FOR_WARNINGS",
                        "message": "Answer not written. Please address these warnings and try again.",
                        "warnings": v_res["warnings"],
                        "hint": "Check if you double-counted, used wrong units (thousands vs millions), or matched the wrong row/year.",
                    }

            answer_path = Path("/app/answer.txt")
            # Also try local path for testing
            if not answer_path.parent.exists():
                answer_path = _ROOT / "answer.txt"

            answer_path.write_text(ans)
            self._best_verified_answer = ans
            return {
                "status": "SUCCESS" if source != "abstain" else "ABSTAINED",
                "path": str(answer_path),
                "answer": ans,
                "source": source,
                "message": "Answer written successfully. You may now end the session.",
            }
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Composite evidence tools
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_metric_slug(metric: str) -> str:
        """Normalize a metric string for ledger lookup."""
        s = metric.lower().strip()
        s = re.sub(r'\s*\d+/', '', s)        # remove footnote numbers like "1/"
        s = re.sub(r'[^\w\s\-]', '', s).strip()  # remove punctuation, preserve hyphens (matches ingestion)
        s = re.sub(r'\s+', ' ', s)            # collapse whitespace
        return s

    def _broad_slug_search(self, metric_norm: str, time_keys: list[str],
                           row_types: tuple[str, ...]) -> list[sqlite3.Row]:
        """Search master_ledger broadly for all matching slugs.

        Strategy: collect results from multiple LIKE patterns (full phrase,
        then progressively fewer trailing words). Returns the UNION of all
        hits so the caller sees every possible candidate — the model picks.
        """
        if not time_keys:
            return []
        ph = ",".join("?" * len(time_keys))
        rt_ph = ",".join("?" * len(row_types))

        all_rows: list[sqlite3.Row] = []
        seen_keys: set[tuple] = set()  # (slug, time_key, source_file) dedup

        def _add_rows(rows: list[sqlite3.Row]) -> None:
            for r in rows:
                key = (r["metric_slug"], r["time_key"], r["source_file"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_rows.append(r)

        # 1. Exact match
        rows = self._conn.execute(
            f"""SELECT metric_slug, time_key, period_basis, value, value_raw,
                       table_pk, source_file, table_title, row_type
                FROM master_ledger
                WHERE metric_slug = ? AND time_key IN ({ph})
                  AND row_type IN ({rt_ph})
                ORDER BY source_file DESC""",
            (metric_norm, *time_keys, *row_types),
        ).fetchall()
        _add_rows(rows)

        # 2. LIKE with progressively fewer words — collect ALL results
        words = metric_norm.split()
        if len(words) >= 2:
            # Try from all words down to 2 words
            for n_words in range(len(words), 1, -1):
                subset = words[:n_words]
                like_pattern = "%" + "%".join(subset) + "%"
                rows = self._conn.execute(
                    f"""SELECT metric_slug, time_key, period_basis, value, value_raw,
                               table_pk, source_file, table_title, row_type
                        FROM master_ledger
                        WHERE metric_slug LIKE ? AND time_key IN ({ph})
                          AND row_type IN ({rt_ph})
                        ORDER BY source_file DESC
                        LIMIT 200""",
                    (like_pattern, *time_keys, *row_types),
                ).fetchall()
                _add_rows(rows)

        return all_rows

    @tool({
        "name": "find_metric",
        "description": "DISCOVERY — Broad search for all metric slugs matching a query in a given year. Returns candidates with CY total, FY total, annual total, and monthly availability. Does NOT pick a winner — use this to see what data exists, then pick the candidate that best matches your question.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Metric keywords to search for (e.g., 'national defense expenditures')"},
                "year": {"type": "integer", "description": "Target year"},
                "period_basis": {"type": "string", "enum": ["calendar", "fiscal", ""], "description": "Hint for which totals to prioritize"},
            },
            "required": ["query", "year"],
        },
    })
    def find_metric(
        self,
        query: str,
        year: int,
        period_basis: str = "",
    ) -> dict:
        """Broad candidate discovery at the TABLE level.

        Returns distinct (metric_slug, table_pk) candidates with table context
        (title, units, period_basis) so the model can pick the right table.
        Does NOT pre-aggregate or pre-compute sums — shows what's reported.
        """
        try:
            yr = int(year)
            metric_norm = self._normalize_metric_slug(query)

            # Build time keys for all possible types
            all_time_keys = [
                f"CY{yr}", f"FY{yr}", str(yr),
                *[f"{yr}-{m:02d}" for m in range(1, 13)],
            ]
            all_row_types = (
                'annual_total', 'synthetic_cy_total', 'synthetic_fy_total',
                'month_row', 'monthly_total', '',
            )

            rows = self._broad_slug_search(metric_norm, all_time_keys, all_row_types)

            if not rows:
                return {
                    "status": "no_data",
                    "query": query,
                    "year": yr,
                    "candidates": [],
                    "hint": "No matching metrics found. Try different keywords or use search_tables.",
                }

            # Group by (slug, table_title) — logical table candidates
            # Merges copies of the same table across bulletins
            table_cands: dict[tuple[str, str], dict] = {}

            for r in rows:
                slug = r["metric_slug"]
                tpk = r["table_pk"]
                tk = str(r["time_key"])
                val = r["value"]
                rt = r["row_type"]
                src = r["source_file"]

                # Get table title
                ttitle = r["table_title"] if "table_title" in r.keys() else None
                if ttitle is None:
                    ts = self._conn.execute(
                        "SELECT table_title, units_line, period_basis, frequency "
                        "FROM table_summary WHERE table_pk = ?", (tpk,)
                    ).fetchone()
                    ttitle = str(ts["table_title"]) if ts else f"unknown_{tpk}"
                else:
                    ttitle = str(ttitle)
                    ts = None

                key = (slug, ttitle)

                if key not in table_cands:
                    if ts is None:
                        ts = self._conn.execute(
                            "SELECT table_title, units_line, period_basis, frequency "
                            "FROM table_summary WHERE table_pk = ?", (tpk,)
                        ).fetchone()
                    table_cands[key] = {
                        "metric_slug": slug,
                        "table_title": ttitle,
                        "table_pks": [],
                        "units": str(ts["units_line"]) if ts else "",
                        "table_period_basis": str(ts["period_basis"]) if ts else "",
                        "table_frequency": str(ts["frequency"]) if ts else "",
                        "source_file": src,
                        "has_cy_total": False,
                        "has_fy_total": False,
                        "has_annual_total": False,
                        "monthly_count": 0,
                        "_months_seen": set(),
                    }
                tc = table_cands[key]
                if tpk not in tc["table_pks"]:
                    tc["table_pks"].append(tpk)
                # Keep latest source
                if src > tc["source_file"]:
                    tc["source_file"] = src

                if rt == "synthetic_cy_total":
                    tc["has_cy_total"] = True
                    if src >= tc.get("_cy_src", ""):
                        tc["cy_value"] = val
                        tc["_cy_src"] = src
                elif rt == "synthetic_fy_total":
                    tc["has_fy_total"] = True
                    if src >= tc.get("_fy_src", ""):
                        tc["fy_value"] = val
                        tc["_fy_src"] = src
                elif rt == "annual_total":
                    tc["has_annual_total"] = True
                    if src >= tc.get("_at_src", ""):
                        tc["annual_value"] = val
                        tc["_at_src"] = src
                elif rt in ("month_row", "monthly_total", ""):
                    m_match = re.match(r'\d{4}-(\d{2})', tk)
                    if m_match:
                        tc["_months_seen"].add(int(m_match.group(1)))
                        tc["monthly_count"] = len(tc["_months_seen"])

            # Build clean output — prioritize candidates with data
            candidates = []
            for (slug, ttitle), tc in table_cands.items():
                cand: dict = {
                    "metric_slug": slug,
                    "table_title": tc["table_title"],
                    "table_pks": tc["table_pks"],
                    "units": tc["units"],
                    "period_basis": tc["table_period_basis"],
                    "frequency": tc["table_frequency"],
                    "source_file": tc["source_file"],
                    "monthly_count": tc["monthly_count"],
                    "complete_12_months": tc["monthly_count"] == 12,
                }
                if tc.get("has_cy_total"):
                    cand["cy_value"] = tc["cy_value"]
                if tc.get("has_fy_total"):
                    cand["fy_value"] = tc["fy_value"]
                if tc.get("has_annual_total"):
                    cand["annual_value"] = tc["annual_value"]
                candidates.append(cand)
                del tc["_months_seen"]  # clean up internal tracking

            # Sort: tables with CY/FY totals first, then by monthly completeness
            pb = str(period_basis or "").strip().lower()
            def _sort_key(c: dict) -> tuple:
                has_target = 0
                if pb == "calendar" and "cy_value" in c:
                    has_target = 2
                elif pb == "fiscal" and ("fy_value" in c or "annual_value" in c):
                    has_target = 2
                elif "cy_value" in c or "fy_value" in c:
                    has_target = 1
                return (has_target, c["complete_12_months"], c["monthly_count"])

            candidates.sort(key=_sort_key, reverse=True)

            # Limit to top candidates to avoid overwhelming the model
            candidates = candidates[:8]

            return self._compact_result({
                "status": "ok",
                "query": query,
                "year": yr,
                "total_candidates": len(candidates),
                "candidates": candidates,
                "hint": "Pick the table whose title best matches your question. "
                        "Use get_period_series(metric=..., year=..., table_pk=table_pks[0]) "
                        "to get values from a specific table.",
            }, max_bytes=6000)

        except Exception as exc:
            return {"error": str(exc)}

    @tool({
        "name": "resolve_numeric_evidence",
        "description": "START HERE for any numeric question. Searches all bulletin vintages and data sources. Returns ranked candidates with recommended_value. If status is high_confidence, use recommended_value directly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Full question text"},
                "metric": {"type": "string", "description": "Metric to look up (e.g., 'national defense expenditures', 'customs receipts')"},
                "year": {"type": "integer", "description": "Target year"},
                "period_basis": {"type": "string", "enum": ["calendar", "fiscal", ""], "description": "Required period type — 'calendar' for CY, 'fiscal' for FY. Leave empty if unspecified."},
            },
            "required": ["question", "metric"],
        },
    })
    def resolve_numeric_evidence(
        self,
        question: str,
        metric: str,
        year: int | None = None,
        period_basis: str = "",
    ) -> dict:
        """Multi-bulletin evidence resolver. Queries the master ledger across all
        bulletin vintages, scores by recency, and returns ranked candidates.

        Primary path: master_ledger (fast, pre-indexed, handles CY/FY time keys).
        Fallback: table_index search + query_table_rows.

        Use this instead of search_tables + get_table_profile + query_table_rows
        when you need the *best* value across multiple bulletin vintages.
        """
        try:
            metric_clean = str(metric or question or "").strip()
            yr = int(year) if year is not None else None
            pb_want = str(period_basis or "").strip().lower()

            # --- 0. Agency alias resolution ---
            # Try to resolve agency/entity aliases before searching
            try:
                alias_res = self.resolve_agency_alias(query=metric_clean)
                alias_matches = alias_res.get("matches") or []
                if alias_matches:
                    # Use the canonical term from the best match
                    metric_clean = alias_matches[0]["canonical"]
            except Exception:
                pass  # alias resolution is best-effort

            # --- Helper: extract bulletin vintage year from source_file ---
            def _vintage(source_file: str) -> int:
                m = re.search(r'(\d{4})_(\d{2})', source_file)
                return int(m.group(1)) * 100 + int(m.group(2)) if m else 0

            # --- Helper: keyword overlap score against question ---
            q_words = set(re.sub(r'[^\w\s]', '', (question or "").lower()).split())
            _stopwords = {"the", "and", "for", "was", "what", "how", "total", "value",
                          "amount", "from", "with", "that", "this", "a", "an", "of",
                          "in", "to", "is", "are", "were", "be"}
            q_keywords = q_words - _stopwords

            def _title_overlap(title: str) -> int:
                title_words = set(re.sub(r'[^\w\s]', '', title.lower()).split())
                return len(title_words & q_keywords)

            # --- Helper: get units_line for a table_pk ---
            def _get_units(table_pk: int) -> str:
                try:
                    row = self._conn.execute(
                        "SELECT units_line FROM table_index WHERE table_pk = ?",
                        (table_pk,)
                    ).fetchone()
                    return str(row["units_line"]).strip() if row and row["units_line"] else ""
                except Exception:
                    return ""

            # --- 1. Primary path: query master_ledger directly ---
            # Build time_key list: try all period bases if unspecified
            if yr:
                if pb_want == "calendar":
                    time_keys = [f"CY{yr}"]
                elif pb_want == "fiscal":
                    time_keys = [f"FY{yr}", str(yr)]
                else:
                    # Try all: calendar year, fiscal year, plain year, and adjacent
                    time_keys = [f"CY{yr}", f"FY{yr}", str(yr)]
            else:
                time_keys = []

            metric_norm = self._normalize_metric_slug(metric_clean)

            ledger_rows: list[sqlite3.Row] = []
            if time_keys:
                ledger_rows = self._broad_slug_search(
                    metric_norm, time_keys,
                    row_types=('annual_total', 'point_estimate',
                               'synthetic_cy_total', 'synthetic_fy_total', ''),
                )

            # --- 2. Build candidates grouped by logical table (table_title) ---
            # Within each logical table, keep only the latest bulletin's value.
            title_best: dict[str, dict] = {}  # table_title -> best candidate

            for r in ledger_rows:
                val_raw = str(r["value_raw"] or r["value"] or "").strip()
                if not val_raw:
                    continue
                src = str(r["source_file"] or "")
                ttitle = str(r["table_title"] or "") if "table_title" in r.keys() else ""
                if not ttitle:
                    ts = self._conn.execute(
                        "SELECT table_title FROM table_summary WHERE table_pk = ?",
                        (r["table_pk"],)
                    ).fetchone()
                    ttitle = str(ts["table_title"]) if ts else f"unknown_{r['table_pk']}"

                # Parse numeric value
                numeric_str = re.sub(r'[^\d.\-]', '', val_raw.replace(',', ''))
                try:
                    norm_val: float | None = float(numeric_str) if numeric_str else None
                except ValueError:
                    norm_val = None

                pb_row = str(r["period_basis"] or r["time_key"] or "").lower()
                pb_match = (not pb_want) or pb_want in pb_row or pb_want in str(r["time_key"]).lower()
                vin = _vintage(src)
                title_score = _title_overlap(ttitle)
                confidence = round(min(0.95, 0.5 + (vin / 200000.0) + (0.15 if pb_match else 0.0) + (0.05 * min(title_score, 2))), 2)

                # Keep latest bulletin per logical table
                existing = title_best.get(ttitle)
                if existing is None or vin > existing["bulletin_vintage"]:
                    title_best[ttitle] = {
                        "value": val_raw,
                        "normalized_value": norm_val,
                        "table_title": ttitle,
                        "table_pk": r["table_pk"],
                        "source_file": src,
                        "time_key": str(r["time_key"] or ""),
                        "period_basis": pb_row,
                        "bulletin_vintage": vin,
                        "confidence": confidence,
                        "title_keyword_overlap": title_score,
                        "units": _get_units(r["table_pk"]),
                    }

            best_candidates = list(title_best.values())

            # Sort: prefer period_basis match + title keyword overlap, then latest bulletin
            best_candidates.sort(
                key=lambda c: (
                    int(pb_want in c["period_basis"]) if pb_want else 0,
                    c.get("title_keyword_overlap", 0),
                    c["bulletin_vintage"],
                ),
                reverse=True,
            )
            best_candidates = best_candidates[:6]

            # --- 3. Fallback A: canonical_facts search if ledger gave nothing ---
            if not best_candidates and yr:
                try:
                    canon_out = self.search_canonical(
                        query=metric_clean,
                        year=yr,
                        limit=10,
                    )
                    for cr in (canon_out.get("results") or []):
                        val = cr.get("value")
                        if val is None:
                            continue
                        val_raw_c = str(val)
                        numeric_str = re.sub(r'[^\d.\-]', '', val_raw_c.replace(',', ''))
                        try:
                            norm_val_c: float | None = float(numeric_str) if numeric_str else None
                        except ValueError:
                            norm_val_c = None
                        ttitle_c = str(cr.get("table_title") or "")
                        src_c = str(cr.get("source") or "")
                        vin_c = _vintage(src_c)
                        title_score_c = _title_overlap(ttitle_c)
                        pk_c = cr.get("table_pk") or 0
                        best_candidates.append({
                            "value": val_raw_c,
                            "normalized_value": norm_val_c,
                            "table_title": ttitle_c,
                            "table_pk": pk_c,
                            "source_file": src_c,
                            "time_key": str(cr.get("time_key") or yr),
                            "period_basis": str(cr.get("period_basis") or ""),
                            "bulletin_vintage": vin_c,
                            "confidence": 0.45,
                            "title_keyword_overlap": title_score_c,
                            "units": str(cr.get("unit") or ""),
                            "_fallback_source": "canonical",
                        })
                    best_candidates = best_candidates[:6]
                except Exception:
                    pass  # canonical fallback is best-effort

            # --- 4. Fallback B: table_index search if still nothing ---
            if not best_candidates and yr:
                saved_count = self._search_call_count
                res = db.search_tables(self._conn, query=metric_clean, year_range=[yr, yr], limit=6)
                self._search_call_count = saved_count
                for cand in res.get("candidates", []):
                    pk = cand.get("table_pk")
                    if not pk:
                        continue
                    profile = db.get_table_profile(self._conn, table_pk=pk)
                    actual_pb = str(profile.get("period_basis") or "").lower()
                    row_res = db.query_table_rows(self._conn, table_pk=pk, year=yr, limit=10)
                    rows_fb = row_res.get("rows", [])
                    total_rows_fb = [r for r in rows_fb if "total" in str(r.get("column_label", "")).lower()] or rows_fb[:2]
                    for row in total_rows_fb[:2]:
                        val_raw = row.get("value_raw") or row.get("value", "")
                        if not val_raw:
                            continue
                        src = cand.get("file_id", "")
                        ttitle_fb = cand.get("table_title", "")
                        best_candidates.append({
                            "value": str(val_raw),
                            "normalized_value": row.get("normalized_value"),
                            "table_pk": pk,
                            "source_file": src,
                            "table_title": ttitle_fb,
                            "time_key": str(yr),
                            "period_basis": actual_pb,
                            "bulletin_vintage": _vintage(src),
                            "confidence": 0.4,
                            "title_keyword_overlap": _title_overlap(ttitle_fb),
                            "units": _get_units(pk),
                        })
                best_candidates = best_candidates[:6]

            if not best_candidates:
                return {"status": "no_data", "best_candidates": [], "recommended_value": None}

            top = best_candidates[0]
            all_norm = [c["normalized_value"] for c in best_candidates if c.get("normalized_value") is not None]
            unique_vals = set(round(v, 1) for v in all_norm) if all_norm else set()
            has_disagreement = len(unique_vals) > 1

            self._last_extracted_value = str(top["value"])

            result: dict[str, Any] = {
                "status": "ambiguous_candidates" if has_disagreement else "high_confidence",
                "recommended_value": top["value"],
                "recommended_table_pk": top["table_pk"],
                "best_candidates": best_candidates,
            }
            if has_disagreement:
                result["ambiguity_reason"] = (
                    "Same metric appears in multiple bulletin vintages with different values. "
                    "Use the highest bulletin_vintage (most recently revised data)."
                )
            return result

        except Exception as exc:
            return {"error": str(exc)}

    @tool({
        "name": "get_period_series",
        "description": "Monthly breakdown for a single year. Returns 12 month values plus sum.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "Metric to aggregate (e.g., 'national defense expenditures')"},
                "year": {"type": "integer", "description": "Target year"},
                "granularity": {"type": "string", "enum": ["monthly"], "description": "Time granularity (default: monthly)"},
                "basis_preference": {"type": "string", "enum": ["calendar", "fiscal", ""], "description": "Preferred period basis"},
            },
            "required": ["metric", "year"],
        },
    })
    def get_period_series(
        self,
        metric: str,
        year: int,
        table_pk: int | None = None,
        granularity: str = "monthly",
        basis_preference: str = "calendar",
    ) -> dict:
        """Fetch monthly series grouped by TABLE, not just by slug.

        Each table is a separate data source (e.g. "Budget Expenditures" vs
        "Cash Income and Outgo") and may report different values for the same
        metric slug. Within each table, deduplicates across bulletin vintages
        (picks latest revision per month).

        If table_pk is given, returns values from that specific table only.
        Otherwise returns candidates from all matching tables so the model
        can pick the right one based on table title context.

        Does NOT pre-compute sums — returns the individual monthly values
        so the model can verify and compute itself.
        """
        try:
            yr = int(year)
            metric_clean = str(metric or "").strip()
            metric_norm = self._normalize_metric_slug(metric_clean)
            MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

            # --- 1. Broad search for monthly rows ---
            monthly_keys = [f"{yr}-{m:02d}" for m in range(1, 13)]
            total_keys = [f"CY{yr}", f"FY{yr}", str(yr)]
            all_keys = monthly_keys + total_keys

            all_row_types = (
                'month_row', 'monthly_total', '',
                'synthetic_cy_total', 'synthetic_fy_total', 'annual_total',
            )

            if table_pk is not None:
                # Direct table query — skip broad search
                ph = ",".join("?" * len(all_keys))
                rt_ph = ",".join("?" * len(all_row_types))
                ledger_rows = self._conn.execute(
                    f"""SELECT metric_slug, time_key, period_basis, value, value_raw,
                               table_pk, source_file, table_title, row_type
                        FROM master_ledger
                        WHERE table_pk = ? AND metric_slug LIKE ?
                          AND time_key IN ({ph}) AND row_type IN ({rt_ph})
                        ORDER BY source_file DESC""",
                    (table_pk, f"%{metric_norm.split()[0]}%",
                     *all_keys, *all_row_types),
                ).fetchall()
            else:
                ledger_rows = self._broad_slug_search(metric_norm, all_keys, all_row_types)

            if not ledger_rows:
                return {
                    "status": "no_monthly_data",
                    "year": yr,
                    "metric": metric_clean,
                    "candidates": [],
                    "hint": "No matching metrics found. Try find_metric or search_tables.",
                }

            # --- 2. Group by (slug, table_title) — LOGICAL table grouping ---
            # Copies of the same table across bulletins share the same title,
            # so grouping by title merges them into one logical table.
            # Within each logical table, dedup months by latest bulletin.
            TableKey = tuple[str, str]  # (slug, table_title)
            table_months: dict[TableKey, dict[int, dict]] = {}
            table_totals: dict[TableKey, dict] = {}
            table_title_meta: dict[str, dict] = {}  # table_title -> metadata
            table_title_pks: dict[str, list[int]] = {}  # table_title -> list of table_pks

            for r in ledger_rows:
                slug = r["metric_slug"]
                tpk = r["table_pk"]
                tk = str(r["time_key"])
                rt = r["row_type"]
                src = str(r["source_file"] or "")
                val = r["value"]

                # Look up table title for this table_pk
                ttitle = r["table_title"] if "table_title" in r.keys() else None
                if ttitle is None:
                    ts = self._conn.execute(
                        "SELECT table_title, units_line, period_basis "
                        "FROM table_summary WHERE table_pk = ?", (tpk,)
                    ).fetchone()
                    ttitle = str(ts["table_title"]) if ts else f"unknown_{tpk}"
                else:
                    ttitle = str(ttitle)
                    ts = None

                tkey: TableKey = (slug, ttitle)

                # Cache metadata per logical table (use latest bulletin's metadata)
                if ttitle not in table_title_meta:
                    if ts is None:
                        ts = self._conn.execute(
                            "SELECT table_title, units_line, period_basis "
                            "FROM table_summary WHERE table_pk = ?", (tpk,)
                        ).fetchone()
                    table_title_meta[ttitle] = {
                        "table_title": ttitle,
                        "units": str(ts["units_line"]) if ts else "",
                        "period_basis": str(ts["period_basis"]) if ts else "",
                    }
                if ttitle not in table_title_pks:
                    table_title_pks[ttitle] = []
                if tpk not in table_title_pks[ttitle]:
                    table_title_pks[ttitle].append(tpk)

                # Totals — pick latest bulletin across all table_pks for this title
                if rt in ("synthetic_cy_total", "synthetic_fy_total", "annual_total"):
                    if tkey not in table_totals:
                        table_totals[tkey] = {}
                    tt = table_totals[tkey]
                    if rt == "synthetic_cy_total":
                        if src > tt.get("_cy_src", ""):
                            tt["cy_value"] = val
                            tt["_cy_src"] = src
                    elif rt == "synthetic_fy_total":
                        if src > tt.get("_fy_src", ""):
                            tt["fy_value"] = val
                            tt["_fy_src"] = src
                    elif rt == "annual_total":
                        if src > tt.get("_at_src", ""):
                            tt["annual_value"] = val
                            tt["_at_src"] = src
                    continue

                # Monthly rows — dedup within logical table by latest bulletin
                m_match = re.match(r'(\d{4})-(\d{2})', tk)
                if not m_match:
                    continue
                month_num = int(m_match.group(2))

                if tkey not in table_months:
                    table_months[tkey] = {}
                existing = table_months[tkey].get(month_num)
                if existing is None or src > existing["source_file"]:
                    try:
                        fval = float(str(val or "").replace(',', '')) if val is not None else None
                    except ValueError:
                        fval = None
                    table_months[tkey][month_num] = {
                        "month": month_num,
                        "label": MONTH_ABBR[month_num - 1] if 1 <= month_num <= 12 else "?",
                        "value": fval,
                        "source_file": src,
                    }

            # --- 3. Build candidates per logical table ---
            candidates = []
            all_tkeys = set(list(table_months.keys()) + list(table_totals.keys()))

            for tkey in all_tkeys:
                slug, ttitle = tkey
                months = table_months.get(tkey, {})
                totals = table_totals.get(tkey, {})
                meta = table_title_meta.get(ttitle, {})
                months_found = len(months)
                complete = months_found == 12

                cand: dict = {
                    "metric_slug": slug,
                    "table_title": meta.get("table_title", ttitle),
                    "table_pks": table_title_pks.get(ttitle, []),
                    "units": meta.get("units", ""),
                    "period_basis": meta.get("period_basis", ""),
                    "months_found": months_found,
                    "complete_12_months": complete,
                }

                # Include totals if present
                if "cy_value" in totals:
                    cand["cy_value"] = totals["cy_value"]
                if "fy_value" in totals:
                    cand["fy_value"] = totals["fy_value"]
                if "annual_value" in totals:
                    cand["annual_value"] = totals["annual_value"]

                # Include monthly values (let model see + verify)
                if months_found > 0:
                    series = [months[mn] for mn in sorted(months)]
                    cand["values"] = [
                        {"month": r["label"], "value": r["value"]}
                        for r in series
                    ]
                    # Source bulletin for traceability
                    cand["source_file"] = series[-1]["source_file"]

                candidates.append(cand)

            # Sort: complete series first, then tables with CY/FY totals
            candidates.sort(key=lambda c: (
                c["complete_12_months"],
                "cy_value" in c or "fy_value" in c,
                c["months_found"],
            ), reverse=True)

            # Limit
            candidates = candidates[:6]

            if not candidates:
                return {
                    "status": "no_monthly_data",
                    "year": yr,
                    "metric": metric_clean,
                    "candidates": [],
                    "hint": "No matching data found.",
                }

            return self._compact_result({
                "status": "ok",
                "year": yr,
                "metric": metric_clean,
                "total_candidates": len(candidates),
                "candidates": candidates,
                "hint": "Each candidate is from a DIFFERENT table. Pick the table whose title "
                        "matches the question. Values are the reported monthly figures — verify "
                        "units with the 'units' field before computing.",
            }, max_bytes=8000)

        except Exception as exc:
            return {"error": str(exc)}
