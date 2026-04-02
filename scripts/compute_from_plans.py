#!/usr/bin/env python3
"""Compute answers directly from plans — skip the extraction stage.

For each plan in phase1_all_plans.jsonl:
  1. Execute all search_queries locally against the SQLite DB
  2. Collect ALL raw rows from ALL tables found
  3. Pass everything to the LLM as evidence
  4. LLM computes the final answer

This avoids the extraction bottleneck (which only looks at 1 table and uses a
separate LLM call per question just to select values).

Usage:
  python3 scripts/compute_from_plans.py                      # all 246 plans
  python3 scripts/compute_from_plans.py --limit 20           # first 20
  python3 scripts/compute_from_plans.py --uid UID0001        # single question
  python3 scripts/compute_from_plans.py --workers 4          # parallel
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

from openai import OpenAI
from server.tools import OfficeQATools
from src.agent import TOOL_DEFINITIONS
from src.answer import extract_final_answer, clean_answer
from src.reward import fuzzy_match_answer

DEFAULT_MODEL = os.environ.get("OFFICEQA_MODEL", "minimax/minimax-m2.5")
STAGES_DIR = ROOT / "results" / "stages"

COMPUTE_PROMPT = """You are a Treasury bulletin QA analyst. Compute the final answer.

Question: {question}

Search plan:
{plan_summary}

Raw data retrieved from the database (ALL tables found across all search queries):
{raw_data}

Use the compute_expression tool for ALL arithmetic. Then return JSON:
{{
  "computation_steps": ["step1", "step2"],
  "formatted_answer": "final answer value only (no units, just the number/string)",
  "confidence": "high | medium | low"
}}"""


def _get_client() -> OpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("Set OPENROUTER_API_KEY")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


def _init_tools() -> OfficeQATools:
    db_path = os.environ.get("OFFICEQA_SQLITE_DB", "")
    if not db_path:
        for cand in [
            str(ROOT / "data" / "officeqa_slim_v2.sqlite3"),
            str(ROOT / "data" / "officeqa_corpus.sqlite3"),
            "/app/corpus/officeqa_corpus.sqlite3",
        ]:
            if Path(cand).exists():
                db_path = cand
                break
    if not db_path:
        raise RuntimeError("No DB found. Set OFFICEQA_SQLITE_DB")
    return OfficeQATools(db_path)


def _chat(client: OpenAI, messages: list[dict], tools=None) -> dict:
    kwargs: dict = {
        "model": DEFAULT_MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 4096,
        "extra_body": {"reasoning_effort": "medium"},
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
        kwargs["parallel_tool_calls"] = False
    t0 = time.time()
    resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0]
    return {
        "content": choice.message.content or "",
        "tool_calls": [
            {"name": tc.function.name, "args": json.loads(tc.function.arguments or "{}")}
            for tc in (choice.message.tool_calls or [])
        ],
        "finish_reason": choice.finish_reason,
        "latency_s": round(time.time() - t0, 2),
    }


def _extract_json(text: str) -> dict:
    if not text:
        return {}
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    start = None
    return {}


def _execute_search_queries(tools: OfficeQATools, plan: dict) -> list[dict]:
    """Execute all search_queries from a plan, return list of table dicts with rows."""
    search_queries = plan.get("search_queries", [])
    data_needs = plan.get("data_needs", [])

    # Fallback: build queries from data_needs if no search_queries
    if not search_queries and data_needs:
        for dn in data_needs:
            metric = dn.get("metric", "")
            years = dn.get("years", [])
            year = years[0] if years else None
            search_queries.append({
                "tool": "extract_values",
                "args": {"query": metric, "year": year},
            })

    table_results: dict[int, dict] = {}  # table_pk → result

    for sq in search_queries:
        tool = sq.get("tool", "extract_values")
        args = sq.get("args", {})
        tools.reset_budgets()

        try:
            if tool in ("extract_values", "search_canonical"):
                query = args.get("query", "")
                year = args.get("year")
                ev = tools.extract_values(query=query, year=year)
            elif tool == "search_ledger":
                metric = args.get("metric", "")
                year = args.get("year")
                period = args.get("period_basis", "")
                ev = tools.extract_values(query=f"{metric} {period}".strip(), year=year)
            elif tool == "search_tables":
                query = args.get("query", "")
                year_range = args.get("year_range")
                year = year_range[0] if year_range else None
                ev = tools.extract_values(query=query, year=year)
            elif tool == "get_time_series":
                table_pk = args.get("table_pk")
                if table_pk:
                    rows = tools.query_table_rows(table_pk=table_pk, limit=100)
                    profile = tools.get_table_profile(table_pk)
                    ev = {"results": [{
                        "table_pk": table_pk,
                        "table_title": profile.get("title", ""),
                        "units": profile.get("units", ""),
                        "rows": rows.get("rows", []),
                    }]}
                else:
                    continue
            else:
                parts = [str(v) for v in args.values() if isinstance(v, (str, int))]
                ev = tools.extract_values(query=" ".join(parts[:3]))

            for r in ev.get("results", [])[:3]:  # take top 3 per query
                pk = r.get("table_pk")
                if pk and pk not in table_results:
                    table_results[pk] = r

        except Exception:
            continue

    return list(table_results.values())


def _format_raw_data(tables: list[dict], max_rows_per_table: int = 40) -> str:
    """Format table data as text for the LLM prompt."""
    if not tables:
        return "No data found."

    parts = []
    for i, t in enumerate(tables[:6]):  # max 6 tables
        title = t.get("table_title", f"Table {i+1}")
        units = t.get("units", "")
        rows = t.get("rows", [])[:max_rows_per_table]
        pk = t.get("table_pk", "?")

        header = f"TABLE {i+1}: {title} (pk={pk})"
        if units:
            header += f" [{units}]"
        parts.append(header)
        if rows:
            parts.append(json.dumps(rows, default=str))
        parts.append("")

    return "\n".join(parts)


def process_one(plan_row: dict, tools: OfficeQATools, client: OpenAI) -> dict:
    uid = plan_row["uid"]
    question = plan_row["question"]
    gold = plan_row.get("gold", "")
    difficulty = plan_row.get("difficulty", "")
    plan = plan_row.get("plan", {})

    t0 = time.time()

    # Step 1: execute search queries
    tables = _execute_search_queries(tools, plan)
    retrieval_elapsed = time.time() - t0

    if not tables:
        return {
            "uid": uid, "question": question, "gold": gold, "difficulty": difficulty,
            "final_answer": None, "is_correct": False,
            "error": "no_data_found",
            "tables_found": 0,
            "elapsed_s": round(time.time() - t0, 2),
        }

    # Step 2: compute directly from raw data
    plan_summary = json.dumps({
        "data_needs": plan.get("data_needs", []),
        "computation": plan.get("computation", {}),
        "answer_format": plan.get("answer_format", ""),
    }, indent=2)

    raw_data = _format_raw_data(tables)

    prompt = COMPUTE_PROMPT.format(
        question=question,
        plan_summary=plan_summary,
        raw_data=raw_data[:8000],  # truncate to fit context
    )

    compute_tool = [t for t in TOOL_DEFINITIONS if t["function"]["name"] == "compute_expression"]

    try:
        llm = _chat(client, [{"role": "user", "content": prompt}], tools=compute_tool)
    except Exception as exc:
        return {
            "uid": uid, "question": question, "gold": gold, "difficulty": difficulty,
            "final_answer": None, "is_correct": False,
            "error": str(exc),
            "tables_found": len(tables),
            "elapsed_s": round(time.time() - t0, 2),
        }

    # Execute any compute_expression calls
    compute_results = []
    for tc in llm.get("tool_calls", []):
        if tc["name"] == "compute_expression":
            try:
                cr = tools.compute_expression(**tc["args"])
                compute_results.append({"expression": tc["args"], "result": cr})
            except Exception:
                pass

    # Extract final answer
    computed = _extract_json(llm["content"])
    final = None
    if computed.get("formatted_answer"):
        final = str(computed["formatted_answer"])
    elif compute_results:
        last = compute_results[-1].get("result", {})
        if last.get("ok"):
            final = str(last["result"])
    if not final:
        fa = extract_final_answer(llm["content"])
        if fa:
            final = clean_answer(fa)
        else:
            nums = re.findall(r"-?\d[\d,]*\.?\d*%?", llm["content"])
            if nums:
                final = nums[-1].replace(",", "")

    is_correct = fuzzy_match_answer(final or "", gold)[0] if final else False

    return {
        "uid": uid, "question": question, "gold": gold, "difficulty": difficulty,
        "final_answer": final,
        "is_correct": is_correct,
        "tables_found": len(tables),
        "retrieval_s": round(retrieval_elapsed, 2),
        "elapsed_s": round(time.time() - t0, 2),
        "llm_raw": llm["content"][:300],
        "compute_results": compute_results,
    }


def run(plans_path: str, output: Path, limit: int = 0, uid_filter: str = "",
        workers: int = 1):
    db_path = os.environ.get("OFFICEQA_SQLITE_DB", "")
    if not db_path:
        for cand in [
            str(ROOT / "data" / "officeqa_slim_v2.sqlite3"),
            str(ROOT / "data" / "officeqa_corpus.sqlite3"),
            "/app/corpus/officeqa_corpus.sqlite3",
        ]:
            if Path(cand).exists():
                db_path = cand
                break

    client = _get_client()

    plans = []
    for line in Path(plans_path).read_text().strip().split("\n"):
        if line.strip():
            p = json.loads(line)
            if "question" in p:
                plans.append(p)

    if uid_filter:
        plans = [p for p in plans if p["uid"] == uid_filter]
    if limit:
        plans = plans[:limit]

    print(f"\n  COMPUTE FROM PLANS — {len(plans)} questions")
    print(f"  Model: {DEFAULT_MODEL}")
    print(f"  Output: {output}\n")

    output.parent.mkdir(parents=True, exist_ok=True)

    correct = 0
    total = 0

    def _process(plan_row: dict):
        # Each worker gets its own tools instance (not thread-safe to share)
        tools = OfficeQATools(db_path)
        return process_one(plan_row, tools, client)

    with open(output, "w") as f:
        if workers > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_process, p): p["uid"] for p in plans}
                results_map = {}
                for fut in concurrent.futures.as_completed(futures):
                    uid = futures[fut]
                    try:
                        results_map[uid] = fut.result()
                    except Exception as exc:
                        results_map[uid] = {"uid": uid, "error": str(exc)}
            # Write in original order
            for i, p in enumerate(plans):
                row = results_map.get(p["uid"], {"uid": p["uid"], "error": "unknown"})
                f.write(json.dumps(row) + "\n")
                is_c = row.get("is_correct", False)
                if is_c:
                    correct += 1
                total += 1
                print(f"  [{i+1}/{len(plans)}] {p['uid']} tables={row.get('tables_found',0)} "
                      f"ans={row.get('final_answer','?')!r} gold={p.get('gold','?')} {'✓' if is_c else '✗'}")
        else:
            for i, plan_row in enumerate(plans):
                row = _process(plan_row)
                f.write(json.dumps(row) + "\n")
                is_c = row.get("is_correct", False)
                if is_c:
                    correct += 1
                total += 1
                print(f"  [{i+1}/{len(plans)}] {plan_row['uid']} tables={row.get('tables_found',0)} "
                      f"ans={row.get('final_answer','?')!r} gold={plan_row.get('gold','?')} {'✓' if is_c else '✗'}")

    pct = 100 * correct / total if total else 0
    print(f"\n  Done: {correct}/{total} correct ({pct:.1f}%)")
    print(f"  Output: {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", default=str(ROOT / "results" / "phase1_all_plans.jsonl"))
    parser.add_argument("--output", default=str(STAGES_DIR / "plans_direct_compute.jsonl"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--uid", default="")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    run(
        plans_path=args.plans,
        output=Path(args.output),
        limit=args.limit,
        uid_filter=args.uid,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
