#!/usr/bin/env python3
"""MCP SSE server for OfficeQA Arena.

Fixes the three known bugs in the baked-in droplet server:
  1. extract_values now uses table_pk and cascades column_label -> row_label -> no filter
  2. search_tables/query_table_rows use the working table_first_* path (no broken corpus glob)
  3. All tools route through our db.py which queries table_first_table_cells (not empty document_elements)

Also adds get_time_series: single-query time-series extraction (replaces N separate extract_values calls).

Usage:
    python3 -m server.mcp_sse                     # default host=0.0.0.0 port=8081
    python3 server/mcp_sse.py --port 8081
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Bootstrap: add repo root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

from server.tools import OfficeQATools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("mcp_sse")

# ---------------------------------------------------------------------------
# Database + tools singleton
# ---------------------------------------------------------------------------

_tools: OfficeQATools | None = None


def _get_tools() -> OfficeQATools:
    global _tools
    if _tools is None:
        db_path = os.environ.get("OFFICEQA_SQLITE_DB", "")
        if not db_path:
            for candidate in [
                "/app/corpus/officeqa_corpus.sqlite3",
                str(ROOT / "data" / "officeqa_corpus.sqlite3"),
            ]:
                if Path(candidate).exists():
                    db_path = candidate
                    break
        if not db_path:
            raise RuntimeError(
                "No SQLite database found. Set OFFICEQA_SQLITE_DB env var."
            )
        logger.info("Opening database: %s", db_path)
        _tools = OfficeQATools(db_path)
    return _tools


# ---------------------------------------------------------------------------
# FastMCP app
# ---------------------------------------------------------------------------

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8081

mcp = FastMCP(
    "officeqa-arena",
    host=_DEFAULT_HOST,
    port=_DEFAULT_PORT,
)


# ---------------------------------------------------------------------------
# Tool: search_tables
# ---------------------------------------------------------------------------


@mcp.tool()
def search_tables(
    query: str,
    file_id: str = "",
    year_range: list[int] | None = None,
    limit: int = 10,
) -> str:
    """Find tables matching a keyword query. Returns ranked candidates with table_pk, columns_sample, and year_range.

    Start here when you need to discover which table contains your data.
    Use year_range=[start, end] to restrict to a time period.
    The response includes column names and year coverage so you can go straight to query_table_rows without calling get_table_profile.

    Args:
        query: Search terms (e.g. 'public works expenditures', 'national defense')
        file_id: Restrict to one bulletin file (e.g. '1941_01')
        year_range: [start_year, end_year] to filter by time period
        limit: Max results (default 10)
    """
    tools = _get_tools()
    result = tools.search_tables(
        query=query, file_id=file_id, year_range=year_range, limit=limit
    )

    # Add action_hint per ideal-tool-design.md section 2d
    candidates = result.get("candidates", [])
    if candidates:
        best = candidates[0]
        pk = best.get("table_pk", "?")
        result["action_hint"] = (
            f"Use query_table_rows(table_pk={pk}) to fetch values, "
            f"or extract_values() for a one-shot search+fetch."
        )
    else:
        result["action_hint"] = (
            "No tables found. Try broader keywords, remove year_range, "
            "or use get_file_structure on a specific bulletin."
        )
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: query_table_rows
# ---------------------------------------------------------------------------


@mcp.tool()
def query_table_rows(
    table_pk: int | None = None,
    file_id: str = "",
    table_title: str = "",
    row_label: str = "",
    column_label: str = "",
    year: int | None = None,
    year_range: list[int] | None = None,
    month: int | None = None,
    limit: int = 50,
) -> str:
    """Fetch cell values from a specific table. Filter by row_label, column_label, year, month.

    Always prefer table_pk (from search_tables) over file_id+table_title for precise lookups.
    Use column_label for metrics that appear as column headers (e.g. 'National defense').
    Use row_label for metrics that appear as row labels.

    Args:
        table_pk: Table primary key from search_tables (preferred)
        file_id: Bulletin file ID (e.g. '1941_01')
        table_title: Table title substring
        row_label: Filter rows containing this text
        column_label: Filter to this column name
        year: Single year filter
        year_range: [start, end] for multi-year queries
        month: Month filter (1-12)
        limit: Max rows returned (default 50)
    """
    tools = _get_tools()
    result = tools.query_table_rows(
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
    rows = result.get("rows", [])
    if rows:
        result["action_hint"] = (
            f"Got {len(rows)} rows. Use compute_expression() for any math."
        )
    else:
        result["action_hint"] = (
            "No rows matched. Try: 1) remove column_label/row_label filters, "
            "2) widen year_range, 3) use search_tables to find the right table."
        )
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: search_ledger  (GOLD PATH — Master Ledger lookup)
# ---------------------------------------------------------------------------


@mcp.tool()
def search_ledger(
    metric: str,
    year: int | None = None,
    period_basis: str = "",
    years: list[int] | None = None,
) -> str:
    """GOLD PATH — Search the Master Ledger for pre-computed values.

    The Master Ledger is a flat, deduplicated index of ALL values in the database,
    indexed by metric name and time period. It includes pre-computed calendar year (CY)
    and fiscal year (FY) totals, monthly values, and annual totals.

    START HERE for any question asking "what was the value of X in year Y".
    For change/diff questions, pass multiple years to get both values in one call.

    Args:
        metric: Metric name (e.g. 'customs', 'national defense', 'total receipts')
        year: Single year to look up
        period_basis: 'calendar' for CY, 'fiscal' for FY, 'monthly', 'annual', or '' for all
        years: List of years for multi-year comparison (e.g. [1940, 1941])
    """
    tools = _get_tools()
    result = tools.search_ledger(
        metric=metric, year=year, period_basis=period_basis, years=years
    )
    return json.dumps(result, default=str)


# Tool: extract_values  (SILVER PATH — full table search)
# ---------------------------------------------------------------------------


@mcp.tool()
def extract_values(
    query: str,
    metric: str = "",
    year: int | None = None,
    month: int | None = None,
    top_k: int = 2,
) -> str:
    """Search + fetch in ONE call. Finds tables matching query, fetches rows, returns compact results.

    This is the primary tool -- use it first for any data lookup question.
    It fixes the baked-in server bugs: uses table_pk for precise lookups and
    cascades metric matching (column_label -> row_label -> no filter).

    Returns best_match with values, plus alternatives. Includes confidence signal and action_hint.

    Args:
        query: What to search for (e.g. 'national defense expenditures')
        metric: Specific metric/column to extract (e.g. 'National defense')
        year: Target year
        month: Target month (1-12)
        top_k: Number of candidate tables to check (default 2)
    """
    tools = _get_tools()
    result = tools.extract_values(
        query=query, metric=metric, year=year, month=month, top_k=top_k
    )

    # Enhance response with confidence + action_hint per ideal-tool-design.md section 2a
    results_list = result.get("results", [])
    if results_list:
        best = results_list[0]
        row_count = len(best.get("rows", []))
        score = best.get("score", 0)

        # Confidence heuristic
        if score > 0.5 and row_count > 0:
            confidence = "high"
        elif score > 0.2 and row_count > 0:
            confidence = "medium"
        else:
            confidence = "low"
        result["confidence"] = confidence

        pk = best.get("table_pk", "?")
        if confidence == "high":
            result["action_hint"] = (
                f"High confidence match (table_pk={pk}). "
                "Proceed to compute_expression if math is needed, or write your answer."
            )
        else:
            result["action_hint"] = (
                f"Match confidence is {confidence} (table_pk={pk}). "
                "Consider query_table_rows with different filters or search_tables with broader terms."
            )
    else:
        result["confidence"] = "none"
        result["action_hint"] = (
            "No matching tables found. Try: "
            "1) search_tables with different keywords, "
            "2) get_file_structure on a specific bulletin file."
        )
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: get_time_series  (NEW -- single-query time-series)
# ---------------------------------------------------------------------------


@mcp.tool()
def get_time_series(
    metric: str,
    year_start: int,
    year_end: int,
    query: str = "",
    file_id: str = "",
    month_start: int | None = None,
    month_end: int | None = None,
    top_k: int = 3,
) -> str:
    """Fetch a time-series for a metric across a year range in ONE call. Returns {period: value} pairs.

    Much faster than calling extract_values per year. Does a single search + single DB query.
    Use for any question spanning multiple years or requiring many monthly data points.

    Returns series dict, count, coverage info, and action_hint.

    Args:
        metric: Metric to track (e.g. 'national defense expenditures', 'total budget receipts')
        year_start: First year of the range (inclusive)
        year_end: Last year of the range (inclusive)
        query: Additional search keywords (defaults to metric if empty)
        file_id: Restrict to a specific bulletin (e.g. '1950_02')
        month_start: First month if sub-annual granularity needed (1-12)
        month_end: Last month if sub-annual granularity needed (1-12)
        top_k: Number of candidate tables to check (default 3)
    """
    tools = _get_tools()
    result = tools.get_time_series(
        metric=metric,
        year_start=year_start,
        year_end=year_end,
        query=query,
        file_id=file_id,
        month_start=month_start,
        month_end=month_end,
        top_k=top_k,
    )
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: compute_expression
# ---------------------------------------------------------------------------


@mcp.tool()
def compute_expression(
    expression: str,
    variables: dict | None = None,
) -> str:
    """Safe arithmetic evaluator. Use for ALL math -- never do mental math.

    Supports: +, -, *, /, ** (power), abs(), round(), min(), max(), sum(),
    sqrt(), log(), exp(), geometric_mean(), mean(), prod(), stdev(), pow(), len().
    Use ** for power (^ also works). Pass numeric values as variables.

    Args:
        expression: Math expression (e.g. 'a - b', 'geometric_mean(1,2,3)')
        variables: Variable name->value mapping (e.g. {"a": 494, "b": 154})
    """
    tools = _get_tools()
    result = tools.compute_expression(expression=expression, variables=variables)
    # Echo the expression back per ideal-tool-design.md section 2c
    result["expression_echo"] = expression
    if variables:
        result["variable_count"] = len(variables)
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: get_file_structure
# ---------------------------------------------------------------------------


@mcp.tool()
def get_file_structure(file_id: str) -> str:
    """List all tables in a bulletin file with titles, row counts, and column counts.

    Use as a fallback when search_tables returns nothing -- browse the bulletin's contents directly.

    Args:
        file_id: Bulletin file ID (e.g. '1941_01' or 'treasury_bulletin_1941_01.txt')
    """
    tools = _get_tools()
    result = tools.get_file_structure(file_id=file_id)
    tables = result.get("tables", [])
    if tables:
        result["action_hint"] = (
            f"Found {len(tables)} tables. Use query_table_rows(table_pk=...) to fetch data from any of them."
        )
    else:
        result["action_hint"] = (
            "No tables found for this file_id. Check the file_id format (e.g. '1941_01')."
        )
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: get_table_profile
# ---------------------------------------------------------------------------


@mcp.tool()
def get_table_profile(table_pk: int) -> str:
    """Inspect a table's columns, year coverage, and row count. Use before query_table_rows to understand table structure.

    Args:
        table_pk: Table primary key (from search_tables results)
    """
    tools = _get_tools()
    result = tools.get_table_profile(table_pk=table_pk)
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: get_cpi_index
# ---------------------------------------------------------------------------


@mcp.tool()
def get_cpi_index(year: int, month: int | None = None) -> str:
    """Get CPI-U index value for inflation-adjusted calculations (base: 1982-84=100).

    Args:
        year: Calendar year
        month: Optional month (1-12) for monthly CPI. Omit for annual average.
    """
    tools = _get_tools()
    result = tools.get_cpi_index(year=year, month=month)
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: get_fiscal_year_bounds
# ---------------------------------------------------------------------------


@mcp.tool()
def get_fiscal_year_bounds(fiscal_year: int) -> str:
    """Get start/end dates for a U.S. federal fiscal year.

    Before 1977: Jul 1 (Y-1) to Jun 30 (Y). From 1977+: Oct 1 (Y-1) to Sep 30 (Y).

    Args:
        fiscal_year: The fiscal year number (e.g. 1955)
    """
    tools = _get_tools()
    result = tools.get_fiscal_year_bounds(fiscal_year=fiscal_year)
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="OfficeQA Arena MCP SSE Server")
    parser.add_argument(
        "--host", default=_DEFAULT_HOST, help=f"Bind address (default: {_DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_DEFAULT_PORT,
        help=f"Listen port (default: {_DEFAULT_PORT})",
    )
    parser.add_argument(
        "--transport",
        default="streamable-http",
        choices=["sse", "streamable-http", "stdio"],
        help="Transport type (default: streamable-http)",
    )
    args = parser.parse_args()

    # Apply CLI overrides to FastMCP settings (host/port are set at init, not run)
    mcp.settings.host = args.host
    mcp.settings.port = args.port

    # Eagerly open DB to fail fast on startup
    _get_tools()
    logger.info(
        "Starting MCP server on %s:%d with transport=%s",
        args.host,
        args.port,
        args.transport,
    )

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
