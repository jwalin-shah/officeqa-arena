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
_MAX_BUDGET = 22

# ── Remote telemetry ────────────────────────────────────────────────
TELEMETRY_URL = os.environ.get("TELEMETRY_URL", "")
_TASK_ID = os.environ.get("TASK_ID", "") or os.environ.get("ARENA_TASK_ID", "")
_RUN_ID = os.environ.get("RUN_ID", "") or os.environ.get("ARENA_RUN_ID", "")
_SOURCE = os.environ.get("TELEMETRY_SOURCE", "arena")


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
    payload["source"] = _SOURCE
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
            "result": {"tools": tools.get_tool_schemas()},
        }

    # Call a tool
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        # ── Last-resort auto-submit at budget limit ──────────────
        call_num = len(_call_history) + 1
        if call_num >= _MAX_BUDGET and tool_name != "submit_answer":
            fallback = getattr(tools, '_best_verified_answer', None) or getattr(tools, '_last_computed', None) or getattr(tools, '_last_extracted_value', None)
            if fallback:
                answer_path = Path("/app/answer.txt")
                try:
                    answer_path.write_text(str(fallback).strip())
                    _send_telemetry({"event": "auto_submit", "answer": str(fallback)[:200],
                                     "reason": "budget_exhausted"})
                except Exception:
                    pass
                warn_text = json.dumps({
                    "warning": (
                        f"BUDGET EXHAUSTED (call {call_num}/{_MAX_BUDGET}). "
                        f"Auto-submitted your best answer: '{str(fallback)[:50]}'. "
                        "Call submit_answer if you want to change it."
                    ),
                    "_meta": {"call_number": call_num, "auto_submitted": True},
                })
            else:
                warn_text = json.dumps({
                    "warning": (
                        f"BUDGET EXHAUSTED (call {call_num}/{_MAX_BUDGET}). "
                        "No answer found. Call submit_answer NOW with your best guess. "
                        "A wrong answer scores higher than no answer."
                    ),
                    "_meta": {"call_number": call_num},
                })
            _call_history.append({"tool": f"BUDGET:{tool_name}", "args_key": "", "ts": time.time()})
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

        # ── Execute the tool ──────────────────────────────────────────
        t0 = time.time()
        result_text = _call_tool(tools, tool_name, arguments)
        latency = round(time.time() - t0, 3)

        # ── Inject _meta (and optional spin warning) into result ──────
        try:
            result_obj = json.loads(result_text)
            remaining = _MAX_BUDGET - call_num
            budget_hint = f"Tool call {call_num} of {_MAX_BUDGET}. {remaining} calls remaining."
            result_obj["_meta"] = {
                "call_number": call_num,
                "budget_hint": budget_hint,
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
