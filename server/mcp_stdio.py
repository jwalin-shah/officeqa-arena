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
import time
import threading
import urllib.request
import urllib.error
from pathlib import Path

# Bootstrap: add repo root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.tools import OfficeQATools

# ── Anti-spin call-history tracking ─────────────────────────────────
_call_history: list[dict] = []          # [{tool, args_key, ts}, ...]
_tool_call_counts: dict[str, int] = {}  # tool_name -> total calls
_file_structure_cache: dict[str, str] = {}  # file_id -> cached result
_per_key_counts: dict[str, int] = {}    # "(tool, specific_key)" -> count
_consecutive_blocks: int = 0             # consecutive phase-blocked calls

# ── Phase-based tool gating (state machine) ──────────────────────
_PHASE_BOUNDARIES = {
    "search": (1, 8),    # calls 1-8: all tools allowed
    "compute": (9, 12),  # calls 9-12: compute/verify only
    "submit": (13, 99),  # calls 13+: submit only
}

_COMPUTE_TOOLS = frozenset({
    "compute_expression", "verify_answer", "get_table_profile",
    "get_cpi_index", "get_exchange_rate", "get_fiscal_year_bounds",
    "submit_answer", "query_table_rows",
})

_SUBMIT_TOOLS = frozenset({
    "submit_answer", "verify_answer", "compute_expression",
})

# ── Remote telemetry ────────────────────────────────────────────────
TELEMETRY_URL = os.environ.get("TELEMETRY_URL", "")
_TASK_ID = os.environ.get("TASK_ID", "") or os.environ.get("ARENA_TASK_ID", "")
_RUN_ID = os.environ.get("RUN_ID", "") or os.environ.get("ARENA_RUN_ID", "")


def _post_telemetry(payload: dict) -> None:
    """Fire-and-forget POST to TELEMETRY_URL. Silently ignores errors."""
    if not TELEMETRY_URL:
        return
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            TELEMETRY_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass  # never block the agent


def _send_telemetry(payload: dict) -> None:
    """Send telemetry in a background thread so it never blocks."""
    payload["task_id"] = _TASK_ID
    payload["run_id"] = _RUN_ID
    payload["ts"] = time.time()
    t = threading.Thread(target=_post_telemetry, args=(payload,), daemon=True)
    t.start()


def _load_tools() -> OfficeQATools:
    db_path = (
        os.environ.get("OFFICEQA_SQLITE_DB")
        or os.environ.get("OFFICEQA_DB", "")
    )
    if not db_path:
        # Auto-detect — enriched DB first, then fall back
        for candidate in [
            "/app/corpus/officeqa_enriched.sqlite3",
            "/app/corpus/officeqa_corpus.sqlite3",
            str(ROOT / "data" / "officeqa_slim_v2.sqlite3"),
            str(ROOT / "data" / "officeqa_corpus.sqlite3"),
        ]:
            if Path(candidate).exists():
                db_path = candidate
                break
    if not db_path:
        raise SystemExit("No SQLite database found. Set OFFICEQA_SQLITE_DB env var.")

    # DB contract check — log which retrieval paths are available
    import sqlite3 as _sql
    _conn = _sql.connect(db_path)
    _tables = {r[0] for r in _conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    _conn.close()
    _checks = {
        "canonical_facts": "canonical_facts" in _tables,
        "master_ledger": "master_ledger" in _tables,
        "table_cell_blobs": "table_cell_blobs" in _tables,
        "table_index": "table_index" in _tables,
        "table_scope_index": "table_scope_index" in _tables,
    }
    print(f"DB: {db_path}", file=sys.stderr)
    print(f"DB contract: {_checks}", file=sys.stderr)
    if not _checks["canonical_facts"] and not _checks["master_ledger"]:
        print("WARNING: Neither canonical_facts nor master_ledger found — "
              "gold/fallback retrieval paths will fail!", file=sys.stderr)

    return OfficeQATools(db_path)


# Tool schemas for MCP registration
TOOL_SCHEMAS = [
    {
        "name": "search_tables",
        "description": "SECONDARY: Find candidate tables by keyword and year. Use ONLY when extract_values returned empty or ambiguous results. Do not start here.",
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
        "description": "SECONDARY: Get cell values from a table. Only use AFTER get_table_profile confirms exact labels. Do NOT pass both row_label and column_label unless both are confirmed from profile. Relax filters one at a time if 0 rows returned.",
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
        "name": "search_canonical",
        "description": "GOLD PATH — START HERE. Searches the hierarchical canonical fact store (935K deduplicated facts from the full corpus). Returns facts organized by canonical_key (table_family > table_title > metric). Each result is a distinct data series with full provenance. Use for any 'what was the value of X in year Y' question. If multiple canonical_keys match, use table_family to disambiguate.",
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
    },
    {
        "name": "search_ledger",
        "description": "FALLBACK — Searches the old flat Master Ledger by metric slug. Use search_canonical first; fall back here only if canonical_facts table is unavailable.",
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
    },
    {
        "name": "extract_values",
        "description": "SILVER PATH — Use when search_ledger returns empty or when you need full table context (units, footnotes, row structure). Search + fetch in ONE call.",
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
        "description": "PRIMARY for contiguous year ranges: Fetch a time-series for a metric across a contiguous year range in ONE query. Use this instead of extract_values when the question spans multiple consecutive years. Returns {period: value} pairs with coverage info.",
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
        "description": "PRIMARY for sparse/non-contiguous years: Extract values for a metric across specific years in one call. Returns {year: value} pairs. Use instead of extract_values when the question names specific non-consecutive years.",
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
        "description": "EMERGENCY ONLY — grep raw bulletin files. Only use after ALL structured DB tools (extract_values, search_tables, query_table_rows) have failed at least twice. Output capped at 40 lines. Do NOT use this as a shortcut.",
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
        "description": "EMERGENCY ONLY — fetch a URL for external data. Only use when get_cpi_index, get_exchange_rate, and other bundled reference tools cannot answer the question. Do NOT use for Treasury data — that is always in the database.",
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
    },
    {
        "name": "submit_answer",
        "description": "Write your final answer to /app/answer.txt. Call this AFTER verify_answer passes. Preferred over using echo in terminal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "The final numeric answer to write"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"], "description": "Confidence level (default: high)"},
            },
            "required": ["answer"],
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

        # ── Phase gating: block tools outside current phase ──────────
        call_num = len(_call_history) + 1
        if call_num <= _PHASE_BOUNDARIES["search"][1]:
            current_phase = "search"
        elif call_num <= _PHASE_BOUNDARIES["compute"][1]:
            current_phase = "compute"
        else:
            current_phase = "submit"

        block_text: str = ""
        phase_blocked = False
        if current_phase == "compute" and tool_name not in _COMPUTE_TOOLS:
            remaining = _PHASE_BOUNDARIES["compute"][1] - call_num + 1
            block_text = (
                f"PHASE CHANGE: Search phase ended at call 8. You have data — use it now.\n"
                f"ALLOWED TOOLS: compute_expression, verify_answer, get_table_profile, submit_answer\n"
                f"BLOCKED: {tool_name} is no longer available.\n"
                f"Remaining budget: {remaining} calls. Compute your answer and submit."
            )
            phase_blocked = True
        elif current_phase == "submit" and tool_name not in _SUBMIT_TOOLS:
            remaining = 15 - call_num + 1
            block_text = (
                f"FINAL PHASE: Submit your answer NOW.\n"
                f"ALLOWED: submit_answer, verify_answer, compute_expression\n"
                f"BLOCKED: {tool_name}. You have {remaining} calls left — submit immediately.\n"
                f"A wrong answer scores higher than no answer."
            )
            phase_blocked = True

        if phase_blocked:
            global _consecutive_blocks
            _consecutive_blocks += 1
            # Record blocked call in history so iteration counter advances
            _call_history.append({"tool": f"BLOCKED:{tool_name}", "args_key": "", "ts": time.time()})
            _send_telemetry({"event": "phase_blocked", "tool": tool_name, "phase": current_phase,
                             "call_number": call_num, "consecutive_blocks": _consecutive_blocks})

            # After 2 consecutive blocks, auto-submit the best available answer
            if _consecutive_blocks >= 2:
                fallback = tools._best_verified_answer or tools._last_computed or tools._last_extracted_value
                if fallback:
                    answer_path = Path("/app/answer.txt")
                    try:
                        answer_path.write_text(str(fallback).strip())
                        _send_telemetry({"event": "auto_submit", "answer": str(fallback)[:200],
                                         "reason": "consecutive_phase_blocks"})
                    except Exception:
                        pass
                    warn_text = json.dumps({
                        "warning": (
                            f"AUTO-SUBMITTED: After {_consecutive_blocks} blocked attempts, your best "
                            f"answer '{str(fallback)[:50]}' has been written to /app/answer.txt.\n"
                            "You may verify with: cat /app/answer.txt\n"
                            "To change it, call submit_answer with a different value."
                        ),
                        "_meta": {"call_number": len(_call_history), "phase": current_phase,
                                  "auto_submitted": True},
                    })
                else:
                    warn_text = json.dumps({
                        "warning": (
                            f"BLOCKED {_consecutive_blocks}x: {tool_name} is not available in {current_phase} phase.\n"
                            "You have NO computed answer yet. Call compute_expression NOW, then submit_answer.\n"
                            "ALLOWED: compute_expression, verify_answer, submit_answer\n"
                            "A wrong answer scores higher than no answer."
                        ),
                        "_meta": {"call_number": len(_call_history), "phase": current_phase},
                    })
            else:
                warn_text = json.dumps({
                    "warning": block_text,
                    "_meta": {
                        "call_number": call_num,
                        "budget_hint": f"Tool call {call_num} of ~15. Phase: {current_phase}.",
                    },
                })
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": warn_text}],
                    "isError": False,
                },
            }

        # ── Anti-spin: normalize args to a hashable key ───────────────
        args_key = json.dumps(sorted(arguments.items()), default=str)

        # ── Anti-spin: exact-duplicate check (last 3 calls) ──────────
        last_3 = _call_history[-3:]
        for entry in last_3:
            if entry["tool"] == tool_name and entry["args_key"] == args_key:
                warn_text = json.dumps({
                    "warning": (
                        f"DUPLICATE CALL: You already called {tool_name} with identical "
                        "arguments. Use the previous result or try a DIFFERENT tool/query."
                    ),
                    "_meta": {
                        "call_number": len(_call_history),
                        "budget_hint": f"Tool call {len(_call_history)} of ~15. Plan remaining calls carefully.",
                    },
                })
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": warn_text}],
                        "isError": False,
                    },
                }

        # ── Anti-spin: tool-specific budget checks ────────────────────
        budget_warning: str | None = None

        if tool_name == "search_canonical":
            if _tool_call_counts.get("search_canonical", 0) >= 6:
                budget_warning = (
                    "Budget exceeded for search_canonical (max 6). "
                    "Use extract_values or search_ledger instead."
                )
        elif tool_name == "get_file_structure":
            file_id_key = arguments.get("file_id", "")
            pk = f"get_file_structure:{file_id_key}"
            if file_id_key and pk in _file_structure_cache:
                cached_text = _file_structure_cache[pk]
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": cached_text}],
                        "isError": False,
                    },
                }
        elif tool_name == "query_table_rows":
            tpk_key = str(arguments.get("table_pk", ""))
            pk = f"query_table_rows:{tpk_key}"
            if _per_key_counts.get(pk, 0) >= 4:
                budget_warning = (
                    f"Budget exceeded for query_table_rows on table_pk={tpk_key} (max 4). "
                    "Try a different table or relax filters."
                )
        elif tool_name == "search_ledger":
            if _tool_call_counts.get("search_ledger", 0) >= 5:
                budget_warning = (
                    "Budget exceeded for search_ledger (max 5). "
                    "Use search_canonical or extract_values instead."
                )
        elif tool_name == "extract_values":
            if _tool_call_counts.get("extract_values", 0) >= 5:
                budget_warning = (
                    "Budget exceeded for extract_values (max 5). "
                    "Use search_canonical or query_table_rows instead."
                )

        if budget_warning is not None:
            warn_text = json.dumps({
                "warning": budget_warning,
                "_meta": {
                    "call_number": len(_call_history),
                    "budget_hint": f"Tool call {len(_call_history)} of ~15. Plan remaining calls carefully.",
                },
            })
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": warn_text}],
                    "isError": False,
                },
            }

        # ── Anti-spin: spinning-pattern check (same tool 3+ of last 5) ─
        recent_5 = _call_history[-5:]
        recent_tool_count = sum(1 for e in recent_5 if e["tool"] == tool_name)
        spin_warning: str | None = None
        if recent_tool_count >= 3:
            spin_warning = (
                f"WARNING: You've called {tool_name} {recent_tool_count} times recently. "
                "Consider switching to a different retrieval strategy."
            )

        # ── Reset consecutive block counter on successful dispatch ────
        _consecutive_blocks = 0

        # ── Execute the tool ──────────────────────────────────────────
        t0 = time.time()
        result_text = _call_tool(tools, tool_name, arguments)
        latency = round(time.time() - t0, 3)

        # ── Inject _meta (and optional spin warning) into result ──────
        try:
            result_obj = json.loads(result_text)
            # call_num already computed above for phase gating
            if current_phase == "submit":
                budget_hint = (
                    f"URGENT: Tool call {call_num} of ~15. SUBMIT phase. "
                    "Call submit_answer NOW. A wrong answer > no answer."
                )
            elif current_phase == "compute":
                budget_hint = (
                    f"Tool call {call_num} of ~15. COMPUTE phase — search is disabled. "
                    "Use compute_expression, verify_answer, then submit_answer."
                )
            else:
                budget_hint = f"Tool call {call_num} of ~15. SEARCH phase — {8 - call_num + 1} search calls remaining."
            result_obj["_meta"] = {
                "call_number": call_num,
                "budget_hint": budget_hint,
                "phase": current_phase,
            }
            if spin_warning:
                result_obj["_spin_warning"] = spin_warning
            result_text = json.dumps(result_obj, default=str)
        except Exception:
            # result_text is not a JSON object (e.g. a plain string); leave as-is
            pass

        # ── Cache get_file_structure result ──────────────────────────
        if tool_name == "get_file_structure":
            file_id_key = arguments.get("file_id", "")
            if file_id_key:
                pk = f"get_file_structure:{file_id_key}"
                _file_structure_cache[pk] = result_text

        # ── Record call in history ────────────────────────────────────
        _call_history.append({"tool": tool_name, "args_key": args_key, "ts": time.time()})
        _tool_call_counts[tool_name] = _tool_call_counts.get(tool_name, 0) + 1

        # Per-key counters for query_table_rows
        if tool_name == "query_table_rows":
            tpk_key = str(arguments.get("table_pk", ""))
            pk = f"query_table_rows:{tpk_key}"
            _per_key_counts[pk] = _per_key_counts.get(pk, 0) + 1

        # ── Surface errors via isError so the model can self-correct ──
        is_error = '"error"' in result_text[:200]
        # Send telemetry
        _send_telemetry({
            "event": "tool_call",
            "tool": tool_name,
            "args": {k: (v if isinstance(v, (int, float, bool)) else str(v)[:200]) for k, v in arguments.items()},
            "latency_s": latency,
            "result_len": len(result_text),
            "is_error": is_error,
            "result_preview": result_text[:500],
        })
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": result_text}],
                "isError": is_error,
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
    _send_telemetry({"event": "mcp_started", "db_path": tools.db_path})
    # NOTE: Do NOT write to stderr during MCP operation.
    # OpenCode reads stderr and non-JSON output causes "Connection closed" errors.

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = _handle_message(msg, tools)
        if response is not None:
            _send(response)

    # ── Fallback: write best answer if agent didn't ──────────────────
    answer_path = Path("/app/answer.txt")
    if not answer_path.exists() or answer_path.stat().st_size == 0:
        fallback = tools._best_verified_answer or tools._last_computed or tools._last_extracted_value
        if fallback:
            try:
                answer_path.write_text(str(fallback).strip())
                _send_telemetry({"event": "fallback_answer_write", "answer": str(fallback)[:200]})
            except Exception:
                pass


if __name__ == "__main__":
    main()
