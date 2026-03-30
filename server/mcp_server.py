#!/usr/bin/env python3
"""OfficeQA Arena MCP server (stdio).

Usage::

    OFFICEQA_DB=path/to/corpus.db python -m server.mcp_server

Environment:
    OFFICEQA_DB  — path to the SQLite corpus database (required).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

from server.tools import OfficeQATools

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_TOOLS: OfficeQATools | None = None


def _tools() -> OfficeQATools:
    global _TOOLS
    if _TOOLS is None:
        db_path = os.environ.get("OFFICEQA_SQLITE_DB") or os.environ.get("OFFICEQA_DB", "")
        if not db_path:
            raise SystemExit("OFFICEQA_DB env var must point to the corpus SQLite database.")
        _TOOLS = OfficeQATools(db_path)
    return _TOOLS


mcp = FastMCP(
    "officeqa-arena",
    instructions="OfficeQA Treasury corpus tools. Use search_tables first, then query_table_rows for data.",
)

# ---------------------------------------------------------------------------
# Tool registrations
# ---------------------------------------------------------------------------


@mcp.tool(name="search_tables")
def search_tables(
    query: str,
    file_id: str = "",
    year_range: list[int] | None = None,
    limit: int = 10,
) -> dict:
    """Search table metadata across the Treasury corpus. Use as the first discovery step."""
    return _tools().search_tables(query=query, file_id=file_id, year_range=year_range, limit=limit)


@mcp.tool(name="query_table_rows")
def query_table_rows(
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
    """Fetch rows from a known table by filters. Use after search_tables identifies a target."""
    return _tools().query_table_rows(
        table_pk=table_pk,
        file_id=file_id,
        table_title=table_title,
        row_label=row_label,
        column_label=column_label,
        year=year,
        year_range=year_range,
        month=month,
        limit=limit,
    )


@mcp.tool(name="get_file_structure")
def get_file_structure(file_id: str) -> dict:
    """Return all table titles and metadata (titles, years, row counts) for a bulletin issue."""
    return _tools().get_file_structure(file_id=file_id)


@mcp.tool(name="get_table_profile")
def get_table_profile(table_pk: int) -> dict:
    """Inspect table schema, columns, and year coverage by table_pk."""
    return _tools().get_table_profile(table_pk=table_pk)


@mcp.tool(name="compute_expression")
def compute_expression(expression: str, variables: dict[str, float] | None = None) -> dict:
    """Deterministic arithmetic evaluator. Use instead of model-side math."""
    return _tools().compute_expression(expression=expression, variables=variables)


@mcp.tool(name="get_cpi_index")
def get_cpi_index(year: int, month: int | None = None) -> dict:
    """Bundled CPI-U annual or monthly index (1982-84=100)."""
    return _tools().get_cpi_index(year=year, month=month)


@mcp.tool(name="get_fiscal_year_bounds")
def get_fiscal_year_bounds(fiscal_year: int) -> dict:
    """U.S. federal fiscal year start/end dates (ISO format)."""
    return _tools().get_fiscal_year_bounds(fiscal_year=fiscal_year)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
