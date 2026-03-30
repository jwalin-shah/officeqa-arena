#!/usr/bin/env python3
"""Minimal MCP server over stdio — zero external dependencies.

Implements just enough of the MCP JSON-RPC 2.0 protocol to register tools
and handle tool calls from OpenCode/Claude Code/Codex harnesses.

Usage:
    python3 -m server.mcp_stdio
"""
from __future__ import annotations

import json
import sys
import os
from pathlib import Path

# Bootstrap: add repo root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.tools import OfficeQATools


def _load_tools() -> OfficeQATools:
    db_path = (
        os.environ.get("OFFICEQA_SQLITE_DB")
        or os.environ.get("OFFICEQA_DB", "")
    )
    if not db_path:
        # Auto-detect
        for candidate in [
            "/app/corpus/officeqa_corpus.sqlite3",
            str(ROOT / "data" / "officeqa_corpus.sqlite3"),
        ]:
            if Path(candidate).exists():
                db_path = candidate
                break
    if not db_path:
        raise SystemExit("No SQLite database found. Set OFFICEQA_SQLITE_DB env var.")
    return OfficeQATools(db_path)


# Tool schemas for MCP registration
TOOL_SCHEMAS = [
    {
        "name": "search_tables",
        "description": "Find tables by keyword and year. Returns ranked candidates with column samples. Start here for every question.",
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
    },
    {
        "name": "query_table_rows",
        "description": "Get cell values from a table. Filter by row label, column, year, month. Use column_label for metrics that are columns.",
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
    },
    {
        "name": "get_file_structure",
        "description": "List all tables in a bulletin file with titles and row/column counts. Use file_id like '1941_01'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Bulletin file ID (e.g., '1941_01' or 'treasury_bulletin_1941_01.txt')"},
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "get_table_profile",
        "description": "Inspect a table's columns, year coverage, and row count. Use before query_table_rows.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table_pk": {"type": "integer", "description": "Table primary key"},
            },
            "required": ["table_pk"],
        },
    },
    {
        "name": "compute_expression",
        "description": "Safe arithmetic evaluator. Use for ALL math. Supports: +, -, *, /, ** (power), abs(), round(), min(), max(), sum(), sqrt(), log(), exp(), geometric_mean(), mean(), median(), stdev(), variance(), correlation(), cagr(), theil_index(), cv(), linreg(), percentile(), interpolate(), boxcox(). Use ** for power, not ^.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression (e.g., 'a - b', 'geometric_mean(1,2,3)')"},
                "variables": {"type": "object", "description": "Variable values (e.g., {\"a\": 494, \"b\": 154})"},
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_cpi_index",
        "description": "Get CPI-U index value (1982-84=100) for inflation adjustment. Supports monthly lookups (1930-2026). Formula: real = nominal × (target_CPI / source_CPI).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["year"],
        },
    },
    {
        "name": "get_exchange_rate",
        "description": "Look up a historical exchange rate (USD/JPY, USD/GBP, USD/INR, USD/DEM, USD/CAD). Returns rate for the closest matching date.",
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
    },
    {
        "name": "get_fiscal_year_bounds",
        "description": "Get start/end dates for a U.S. federal fiscal year.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fiscal_year": {"type": "integer"},
            },
            "required": ["fiscal_year"],
        },
    },
    {
        "name": "extract_values",
        "description": "Mega-tool: search + fetch in ONE call. Finds tables matching query, fetches rows, returns compact results. Saves 3-4 tool calls vs doing search_tables + get_table_profile + query_table_rows manually.",
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
    },
    {
        "name": "get_time_series",
        "description": "Fetch a time-series for a metric across a contiguous year range in ONE query. More efficient than get_multi_year_series for contiguous ranges. Returns {period: value} pairs with coverage info.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "Metric to track (e.g., 'total receipts')"},
                "year_start": {"type": "integer", "description": "Start year"},
                "year_end": {"type": "integer", "description": "End year"},
                "query": {"type": "string", "description": "Optional broader search terms"},
                "file_id": {"type": "string", "description": "Restrict to one bulletin file"},
                "month_start": {"type": "integer", "description": "Filter: start month (1-12)"},
                "month_end": {"type": "integer", "description": "Filter: end month (1-12)"},
                "top_k": {"type": "integer", "description": "Tables to check (default 3)"},
            },
            "required": ["metric", "year_start", "year_end"],
        },
    },
    {
        "name": "get_multi_year_series",
        "description": "Extract a time-series for a metric across multiple years in one call. Returns {year: value} pairs. Use for questions spanning multiple years.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "Metric to track (e.g., 'national defense expenditures')"},
                "years": {"type": "array", "items": {"type": "integer"}, "description": "List of years to fetch"},
                "top_k": {"type": "integer", "description": "Tables to check per year (default 2)"},
            },
            "required": ["metric", "years"],
        },
    },
    {
        "name": "grep_corpus",
        "description": "LAST RESORT grep over raw bulletin files. Only use after search_tables and query_table_rows fail. Output capped at 40 lines. Prefer structured DB tools first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search pattern. Use '| keyword |' for table cells, or plain text for headings."},
                "file_id": {"type": "string", "description": "Restrict to one bulletin (e.g., '1941_01'). Omit to search all files."},
                "max_lines": {"type": "integer", "description": "Max output lines (default 40, max 60)"},
                "case_insensitive": {"type": "boolean", "description": "Case-insensitive search (default true)"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "web_lookup",
        "description": "Fetch a URL and return text content (max 10KB). Use for external data like exchange rates, CPI, GDP when bundled data is insufficient. The container has internet access.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch (must start with http:// or https://)"},
                "extract": {"type": "string", "description": "Hint about what to look for in the response"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "resolve_agency_alias",
        "description": "Map historical/colloquial agency names to canonical phrases. Use when search_tables returns nothing for an agency name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Agency name to look up (e.g., 'war department', 'va')"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "verify_answer",
        "description": "CALL THIS BEFORE writing /app/answer.txt. Checks unit scale, value provenance, and common pitfalls. Returns warnings if answer likely has errors.",
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
    },
]


def _call_tool(tools: OfficeQATools, name: str, arguments: dict) -> str:
    """Dispatch a tool call and return JSON result."""
    method = getattr(tools, name, None)
    if method is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = method(**arguments)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc), "tool": name})


def _send(msg: dict) -> None:
    """Send a JSON-RPC message to stdout."""
    line = json.dumps(msg)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _handle_message(msg: dict, tools: OfficeQATools) -> dict | None:
    """Handle a single JSON-RPC 2.0 message."""
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {})

    # Initialization
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "officeqa-arena", "version": "0.7.0"},
            },
        }

    # Notifications (no response needed)
    if method == "notifications/initialized":
        return None

    # List tools
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": TOOL_SCHEMAS},
        }

    # Call a tool
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result_text = _call_tool(tools, tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": result_text}],
                "isError": False,
            },
        }

    # Ping
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    # Unknown method
    if msg_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return None


def main() -> None:
    """Run the MCP server over stdio."""
    tools = _load_tools()
    sys.stderr.write(f"[mcp_stdio] Server started, DB={tools.db_path}\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stderr.write(f"[mcp_stdio] Invalid JSON: {line[:100]}\n")
            sys.stderr.flush()
            continue

        response = _handle_message(msg, tools)
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
