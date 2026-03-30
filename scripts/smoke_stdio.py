#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rpc(proc: subprocess.Popen[str], message: dict) -> dict:
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("No response from MCP server")
    return json.loads(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test the stdio MCP server")
    parser.add_argument("--db", required=True, help="Path to SQLite DB")
    args = parser.parse_args()

    env = os.environ.copy()
    env["OFFICEQA_SQLITE_DB"] = args.db
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [sys.executable, "-m", "server.mcp_stdio"],
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        init_resp = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {},
            },
        )
        print("initialize ok:", init_resp.get("result", {}).get("serverInfo", {}))

        assert proc.stdin is not None
        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }
            )
            + "\n"
        )
        proc.stdin.flush()

        tools_resp = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        tools = tools_resp.get("result", {}).get("tools", [])
        tool_names = [t["name"] for t in tools]
        print("tool count:", len(tool_names))
        print("tools:", ", ".join(tool_names))

        required = {
            "search_tables",
            "query_table_rows",
            "get_file_structure",
            "get_table_profile",
            "compute_expression",
            "get_cpi_index",
            "get_exchange_rate",
            "get_fiscal_year_bounds",
            "extract_values",
            "get_time_series",
            "get_multi_year_series",
            "grep_corpus",
            "web_lookup",
            "resolve_agency_alias",
            "verify_answer",
        }
        missing = sorted(required - set(tool_names))
        if missing:
            raise RuntimeError(f"Missing required tools: {missing}")

        fy_resp = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "get_fiscal_year_bounds",
                    "arguments": {"fiscal_year": 1941},
                },
            },
        )
        print("fiscal-year smoke ok:", fy_resp.get("result", {}))

        math_resp = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "compute_expression",
                    "arguments": {"expression": "sum([1,2,3])"},
                },
            },
        )
        print("compute smoke ok:", math_resp.get("result", {}))

        print("STDIO MCP smoke test: PASS")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
