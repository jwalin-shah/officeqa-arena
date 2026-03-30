"""Tool wrapper class for OfficeQA Arena.

Each method maps 1:1 to an MCP tool, returns a compact dict, and never raises.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from server.safe_eval import safe_eval_finance
from server import db

_LOG = logging.getLogger(__name__)


class OfficeQATools:
    """Stateful tool bag backed by a single SQLite corpus DB."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection = db.open_db(db_path)

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
