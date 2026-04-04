#!/usr/bin/env python3
"""Lightweight MCP server for goose harness — zero external dependencies.

Parses Treasury Bulletin files from /app/resources/ on startup.
Exposes tools over stdio JSON-RPC 2.0 for goose to call.
No DB required — works directly with the task's resource files.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path

# ── Resource parsing ──────────────────────────────────────────────────

RESOURCES_DIR = os.environ.get("RESOURCES_DIR", "/app/resources")

_tables: list[dict] = []         # parsed tables from resource files
_manifest: dict = {}             # manifest.json contents
_raw_texts: dict[str, str] = {}  # filename -> full text content
_page_texts: dict[str, str] = {} # filename -> page text content


def _parse_manifest():
    """Load manifest.json if present."""
    global _manifest
    mpath = Path(RESOURCES_DIR) / "manifest.json"
    if mpath.exists():
        try:
            _manifest = json.loads(mpath.read_text())
        except Exception:
            _manifest = {}


def _parse_table_from_text(text: str, source_file: str) -> list[dict]:
    """Extract tables from a page text file. Returns list of table dicts."""
    tables = []
    # Split on <table> tags if present
    if "<table>" in text:
        parts = text.split("<table>")
        preamble = parts[0]
        for i, part in enumerate(parts[1:], 1):
            end = part.find("</table>")
            table_html = part[:end] if end >= 0 else part
            # Parse rows
            rows = []
            for tr_match in re.finditer(r"<tr>(.*?)</tr>", table_html, re.DOTALL):
                cells = re.findall(r"<t[hd]>(.*?)</t[hd]>", tr_match.group(1))
                if cells:
                    rows.append([c.strip() for c in cells])
            if rows:
                # First row is usually header
                header = rows[0] if rows else []
                title = ""
                # Look for title in preamble (last non-empty line before table)
                pre_lines = [l.strip() for l in preamble.strip().split("\n") if l.strip()]
                if pre_lines:
                    title = pre_lines[-1]
                tables.append({
                    "source": source_file,
                    "table_idx": i,
                    "title": title,
                    "header": header,
                    "rows": rows[1:] if len(rows) > 1 else rows,
                    "raw_text": table_html[:2000],
                })
                preamble = part[end+len("</table>"):] if end >= 0 else ""
    return tables


def _load_resources():
    """Parse all resource files on startup."""
    global _tables, _raw_texts, _page_texts
    rdir = Path(RESOURCES_DIR)
    if not rdir.exists():
        return

    _parse_manifest()

    for fpath in sorted(rdir.iterdir()):
        if fpath.name.startswith("."):
            continue
        if fpath.suffix == ".txt":
            text = fpath.read_text(errors="replace")
            if "_page_" in fpath.name:
                _page_texts[fpath.name] = text
                tables = _parse_table_from_text(text, fpath.name)
                _tables.extend(tables)
            else:
                _raw_texts[fpath.name] = text
        elif fpath.suffix == ".json" and fpath.name != "manifest.json":
            try:
                data = json.loads(fpath.read_text())
                # JSON files often have structured table data
                if isinstance(data, dict) and "pages" in data:
                    for page in data["pages"]:
                        for tbl in page.get("tables", []):
                            _tables.append({
                                "source": fpath.name,
                                "table_idx": tbl.get("table_index", 0),
                                "title": tbl.get("title", ""),
                                "header": tbl.get("header", []),
                                "rows": tbl.get("rows", []),
                                "raw_text": json.dumps(tbl)[:2000],
                            })
            except Exception:
                pass


# ── Tool implementations ──────────────────────────────────────────────

def tool_list_resources() -> dict:
    """List all available resource files and parsed tables."""
    return {
        "status": "success",
        "manifest": _manifest,
        "text_files": list(_raw_texts.keys()),
        "page_files": list(_page_texts.keys()),
        "tables_found": len(_tables),
        "table_summaries": [
            {"idx": i, "source": t["source"], "title": t["title"][:100],
             "columns": len(t["header"]), "rows": len(t["rows"])}
            for i, t in enumerate(_tables)
        ],
    }


def tool_search_tables(query: str) -> dict:
    """Search tables by keyword in title, header, or content."""
    query_lower = query.lower()
    terms = query_lower.split()
    results = []
    for i, t in enumerate(_tables):
        # Score based on matches in title, header, and content
        score = 0
        searchable = (
            t["title"].lower() + " " +
            " ".join(t["header"]).lower() + " " +
            " ".join(" ".join(str(c) for c in row) for row in t["rows"][:5]).lower()
        )
        for term in terms:
            if term in searchable:
                score += 1
            if term in t["title"].lower():
                score += 2  # title match worth more
        if score > 0:
            results.append({
                "table_idx": i,
                "source": t["source"],
                "title": t["title"][:150],
                "header": t["header"],
                "num_rows": len(t["rows"]),
                "score": score,
                "preview_rows": t["rows"][:3],
            })
    results.sort(key=lambda x: x["score"], reverse=True)
    return {
        "status": "success" if results else "no_results",
        "count": len(results),
        "tables": results[:5],
    }


def tool_get_table(table_idx: int) -> dict:
    """Get full table data by index."""
    if table_idx < 0 or table_idx >= len(_tables):
        return {"status": "error", "message": f"Invalid table_idx {table_idx}. Valid range: 0-{len(_tables)-1}"}
    t = _tables[table_idx]
    return {
        "status": "success",
        "source": t["source"],
        "title": t["title"],
        "header": t["header"],
        "rows": t["rows"],
        "num_rows": len(t["rows"]),
    }


def tool_search_rows(table_idx: int, query: str) -> dict:
    """Search rows in a specific table by keyword."""
    if table_idx < 0 or table_idx >= len(_tables):
        return {"status": "error", "message": f"Invalid table_idx {table_idx}"}
    t = _tables[table_idx]
    query_lower = query.lower()
    terms = query_lower.split()
    matches = []
    for row_i, row in enumerate(t["rows"]):
        row_text = " ".join(str(c) for c in row).lower()
        if any(term in row_text for term in terms):
            matches.append({"row_idx": row_i, "cells": row})
    return {
        "status": "success" if matches else "no_results",
        "header": t["header"],
        "matches": matches[:20],
        "total_matches": len(matches),
    }


def tool_get_value(table_idx: int, row_label: str, column_label: str = "") -> dict:
    """Extract a specific value from a table by row and column labels."""
    if table_idx < 0 or table_idx >= len(_tables):
        return {"status": "error", "message": f"Invalid table_idx {table_idx}"}
    t = _tables[table_idx]
    row_lower = row_label.lower()
    col_lower = column_label.lower() if column_label else ""

    # Find column index
    col_idx = -1
    if col_lower:
        for ci, h in enumerate(t["header"]):
            if col_lower in h.lower():
                col_idx = ci
                break

    # Find matching rows
    matches = []
    for row_i, row in enumerate(t["rows"]):
        row_text = " ".join(str(c) for c in row).lower()
        if row_lower in row_text or any(row_lower in str(c).lower() for c in row):
            if col_idx >= 0 and col_idx < len(row):
                matches.append({
                    "row_idx": row_i,
                    "row_label": row[0] if row else "",
                    "column": t["header"][col_idx] if col_idx < len(t["header"]) else "",
                    "value": row[col_idx],
                    "full_row": row,
                })
            else:
                matches.append({
                    "row_idx": row_i,
                    "row_label": row[0] if row else "",
                    "full_row": row,
                    "header": t["header"],
                })
    return {
        "status": "success" if matches else "no_results",
        "matches": matches[:10],
    }


def tool_grep_files(pattern: str) -> dict:
    """Search all resource text files for a pattern (case-insensitive)."""
    pattern_lower = pattern.lower()
    results = []
    for fname, text in {**_raw_texts, **_page_texts}.items():
        lines = text.split("\n")
        matches = []
        for line_i, line in enumerate(lines):
            if pattern_lower in line.lower():
                # Include context
                start = max(0, line_i - 1)
                end = min(len(lines), line_i + 2)
                context = "\n".join(lines[start:end])
                matches.append({"line": line_i + 1, "context": context[:300]})
        if matches:
            results.append({
                "file": fname,
                "match_count": len(matches),
                "matches": matches[:5],
            })
    return {
        "status": "success" if results else "no_results",
        "files_searched": len(_raw_texts) + len(_page_texts),
        "files_matched": len(results),
        "results": results[:5],
    }


def tool_read_file(filename: str, start_line: int = 0, num_lines: int = 100) -> dict:
    """Read lines from a resource file."""
    text = _page_texts.get(filename) or _raw_texts.get(filename)
    if text is None:
        # Try finding by partial match
        for k in {**_raw_texts, **_page_texts}:
            if filename in k:
                text = (_page_texts.get(k) or _raw_texts.get(k))
                filename = k
                break
    if text is None:
        return {"status": "error", "message": f"File not found: {filename}",
                "available": list(_raw_texts.keys()) + list(_page_texts.keys())}
    lines = text.split("\n")
    chunk = lines[start_line:start_line + num_lines]
    return {
        "status": "success",
        "file": filename,
        "start_line": start_line,
        "lines_returned": len(chunk),
        "total_lines": len(lines),
        "content": "\n".join(chunk),
    }


def tool_compute(expression: str, variables: dict = None) -> dict:
    """Evaluate a mathematical expression safely. Supports +, -, *, /, **, sqrt, log, abs, round, sum, min, max."""
    variables = variables or {}
    try:
        # Build safe namespace
        safe_ns = {
            "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
            "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
            "exp": math.exp, "pow": pow, "pi": math.pi, "e": math.e,
            "len": len,
        }
        safe_ns.update(variables)
        # Sanitize expression
        expr = expression.strip()
        # Block dangerous operations
        for blocked in ["import", "exec", "eval", "open", "__", "os.", "sys."]:
            if blocked in expr:
                return {"status": "error", "message": f"Blocked operation: {blocked}"}
        result = eval(expr, {"__builtins__": {}}, safe_ns)
        return {
            "status": "success",
            "expression": expr,
            "variables": {k: v for k, v in variables.items() if not callable(v)},
            "result": result,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc), "expression": expression}


def tool_submit_answer(answer: str) -> dict:
    """Write the final answer to /app/answer.txt."""
    try:
        answer_path = Path("/app/answer.txt")
        answer_path.write_text(str(answer).strip())
        return {"status": "success", "answer": str(answer).strip(),
                "message": "Answer written to /app/answer.txt"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# ── Tool registry ─────────────────────────────────────────────────────

TOOLS = {
    "list_resources": {
        "fn": lambda **kw: tool_list_resources(),
        "schema": {
            "name": "list_resources",
            "description": "List all available resource files and parsed tables. Call this FIRST to understand what data is available.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "search_tables": {
        "fn": lambda **kw: tool_search_tables(**kw),
        "schema": {
            "name": "search_tables",
            "description": "Search tables by keyword in title, header, or cell content. Returns matching tables ranked by relevance.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords (e.g. 'national defense expenditures')"},
                },
                "required": ["query"],
            },
        },
    },
    "get_table": {
        "fn": lambda **kw: tool_get_table(**kw),
        "schema": {
            "name": "get_table",
            "description": "Get full table data (all rows and columns) by table index.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "table_idx": {"type": "integer", "description": "Table index from search_tables or list_resources"},
                },
                "required": ["table_idx"],
            },
        },
    },
    "search_rows": {
        "fn": lambda **kw: tool_search_rows(**kw),
        "schema": {
            "name": "search_rows",
            "description": "Search rows within a specific table by keyword. Useful for finding specific metrics or time periods.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "table_idx": {"type": "integer", "description": "Table index"},
                    "query": {"type": "string", "description": "Search keywords for row content"},
                },
                "required": ["table_idx", "query"],
            },
        },
    },
    "get_value": {
        "fn": lambda **kw: tool_get_value(**kw),
        "schema": {
            "name": "get_value",
            "description": "Extract a specific value from a table by matching row label and optional column label.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "table_idx": {"type": "integer", "description": "Table index"},
                    "row_label": {"type": "string", "description": "Row label to match (e.g. 'National defense', 'January')"},
                    "column_label": {"type": "string", "description": "Column label to match (e.g. '1940', 'Total')", "default": ""},
                },
                "required": ["table_idx", "row_label"],
            },
        },
    },
    "grep_files": {
        "fn": lambda **kw: tool_grep_files(**kw),
        "schema": {
            "name": "grep_files",
            "description": "Search all resource text files for a pattern (case-insensitive). Returns matching lines with context.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Text pattern to search for"},
                },
                "required": ["pattern"],
            },
        },
    },
    "read_file": {
        "fn": lambda **kw: tool_read_file(**kw),
        "schema": {
            "name": "read_file",
            "description": "Read lines from a resource file. Use to examine raw data when table parsing isn't sufficient.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename (or partial match) in /app/resources/"},
                    "start_line": {"type": "integer", "description": "Starting line number (0-based)", "default": 0},
                    "num_lines": {"type": "integer", "description": "Number of lines to read", "default": 100},
                },
                "required": ["filename"],
            },
        },
    },
    "compute": {
        "fn": lambda **kw: tool_compute(**kw),
        "schema": {
            "name": "compute",
            "description": "Evaluate a mathematical expression. Use for ALL arithmetic. Supports variables, sqrt, log, abs, round, sum, min, max.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression (e.g. 'a + b', 'sum(values) / len(values)')"},
                    "variables": {"type": "object", "description": "Variable bindings (e.g. {\"a\": 100, \"b\": 200})", "default": {}},
                },
                "required": ["expression"],
            },
        },
    },
    "submit_answer": {
        "fn": lambda **kw: tool_submit_answer(**kw),
        "schema": {
            "name": "submit_answer",
            "description": "Submit the final answer. Writes to /app/answer.txt. A wrong answer scores higher than no answer — always submit something.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string", "description": "The final numeric answer"},
                },
                "required": ["answer"],
            },
        },
    },
}

# ── MCP JSON-RPC 2.0 protocol ────────────────────────────────────────

_call_count = 0
_MAX_CALLS = 30


def _send(msg: dict) -> None:
    line = json.dumps(msg)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _handle(msg: dict) -> dict | None:
    global _call_count
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "officeqa-lite", "version": "1.0.0"},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        schemas = [t["schema"] for t in TOOLS.values()]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": schemas}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        _call_count += 1

        # Budget enforcement
        if _call_count > _MAX_CALLS and tool_name != "submit_answer":
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({
                        "status": "budget_exhausted",
                        "message": "Tool budget exhausted. Call submit_answer with your best answer.",
                    })}],
                    "isError": False,
                },
            }

        tool = TOOLS.get(tool_name)
        if not tool:
            result_text = json.dumps({"status": "error", "message": f"Unknown tool: {tool_name}"})
        else:
            try:
                result = tool["fn"](**arguments)
                result["_meta"] = {"call_number": _call_count, "budget_remaining": _MAX_CALLS - _call_count}
                result_text = json.dumps(result, default=str)
            except Exception as exc:
                result_text = json.dumps({"status": "error", "message": str(exc)})

        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": result_text}],
                "isError": False,
            },
        }

    # Unknown method
    if msg_id is not None:
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        }
    return None


def main():
    # Load resources on startup
    _load_resources()
    print(f"Loaded: {len(_tables)} tables, {len(_raw_texts)} text files, {len(_page_texts)} page files", file=sys.stderr)

    # stdio JSON-RPC loop
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = _handle(msg)
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
