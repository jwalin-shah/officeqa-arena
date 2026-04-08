#!/usr/bin/env python3
"""Run the research (retrieval) stage using existing phase1 plans.

Reads phase1_all_plans.jsonl, executes each plan's search_queries against the
local SQLite DB, and writes two output files:
  - results/stages/plans_as_parse.jsonl   (synthetic parse format)
  - results/stages/plans_retrieval.jsonl  (retrieval format with top_tables)

Then you can run:
  python3 scripts/stage_runner.py extraction \\
      --parse-input results/stages/plans_as_parse.jsonl \\
      --retrieval-input results/stages/plans_retrieval.jsonl \\
      -o results/stages/plans_extraction.jsonl

  python3 scripts/stage_runner.py computation \\
      --parse-input results/stages/plans_as_parse.jsonl \\
      --extraction-input results/stages/plans_extraction.jsonl \\
      -o results/stages/plans_computation.jsonl

Usage:
  python3 scripts/run_research_from_plans.py
  python3 scripts/run_research_from_plans.py --plans results/phase1_all_plans.jsonl --limit 5
  python3 scripts/run_research_from_plans.py --uid UID0001
"""
from __future__ import annotations

import argparse
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

from server.tools import OfficeQATools

STAGES_DIR = ROOT / "results" / "stages"


def _init_tools() -> OfficeQATools:
    db_path = os.environ.get("OFFICEQA_SQLITE_DB", "")
    if not db_path:
        for cand in [
            str(ROOT / "data" / "officeqa_slim_v2.sqlite3"),
            str(ROOT / "data" / "officeqa_corpus.sqlite3"),
            str(ROOT / "data" / "officeqa_subset.sqlite3"),
            "/app/corpus/officeqa_corpus.sqlite3",
        ]:
            if Path(cand).exists():
                db_path = cand
                break
    if not db_path:
        raise RuntimeError("No DB found. Set OFFICEQA_SQLITE_DB")
    print(f"  DB: {db_path}")
    return OfficeQATools(db_path)


def _extract_years(data_needs: list) -> list[int]:
    years = []
    for dn in data_needs:
        for yr in dn.get("years", []) or []:
            if yr and isinstance(yr, int):
                years.append(yr)
    return sorted(set(years))


def _make_synthetic_parsed(plan_row: dict) -> dict:
    """Build a minimal 'parsed' dict from a plan row for extraction/computation stages."""
    plan = plan_row.get("plan", {})
    data_needs = plan.get("data_needs", [])
    years = _extract_years(data_needs)

    # Build time_scope string so stage_runner can extract year via regex
    if years:
        time_scope = " and ".join(str(y) for y in years)
    else:
        # Fall back: extract from question
        q = plan_row.get("question", "")
        yr_m = re.search(r"\b(1[89]\d{2}|20[0-2]\d)\b", q)
        time_scope = yr_m.group(1) if yr_m else ""

    # Target entity from first data_need metric
    target_entity = ""
    if data_needs:
        target_entity = data_needs[0].get("metric", "")

    return {
        "target_entity": target_entity,
        "time_scope": time_scope,
        "operation": plan.get("computation", {}).get("operation", ""),
        "expected_answer_type": plan_row.get("answer_format", ""),
        "fiscal_or_calendar": data_needs[0].get("period_basis", "") if data_needs else "",
        "multi_step": len(data_needs) > 1,
        "num_tables_needed": len(data_needs),
        "computation_notes": str(plan.get("computation", {})),
    }


def _execute_search_query(tools: OfficeQATools, sq: dict) -> dict:
    """Execute a single search_query dict and return extract_values-style result."""
    tool = sq.get("tool", "extract_values")
    args = sq.get("args", {})

    tools.reset_budgets()
    try:
        if tool == "extract_values":
            return tools.extract_values(**args)
        elif tool == "search_canonical":
            query = args.get("query", "")
            year = args.get("year")
            return tools.extract_values(query=query, year=year)
        elif tool == "search_ledger":
            metric = args.get("metric", "")
            year = args.get("year")
            period = args.get("period_basis", "")
            query = f"{metric} {period}".strip()
            return tools.extract_values(query=query, year=year)
        elif tool == "search_tables":
            query = args.get("query", "")
            year_range = args.get("year_range")
            year = year_range[0] if year_range else None
            return tools.extract_values(query=query, year=year)
        elif tool == "get_time_series":
            table_pk = args.get("table_pk")
            if table_pk:
                profile = tools.get_table_profile(table_pk)
                rows = tools.query_table_rows(table_pk=table_pk, limit=50)
                return {"count": len(rows.get("rows", [])), "results": [{"table_pk": table_pk, "rows": rows.get("rows", []), "table_title": profile.get("title", ""), "score": 50}]}
            return {"count": 0, "results": []}
        else:
            # Generic fallback: build query from args
            parts = []
            for k, v in args.items():
                if isinstance(v, str):
                    parts.append(v)
                elif isinstance(v, int):
                    parts.append(str(v))
            query = " ".join(parts[:3])
            year = None
            for k in ("year", "year_from", "year_start"):
                if k in args:
                    year = args[k]
                    break
            return tools.extract_values(query=query, year=year)
    except Exception as exc:
        return {"count": 0, "results": [], "error": str(exc)}


def _merge_results(ev_results: list[dict]) -> tuple[int, dict, list[dict]]:
    """Merge results from multiple search queries. Returns (count, merged_ev, top_tables).

    Preserves the order from the first query that returned each table (tools return
    results in ranked order already; score field is not always populated).
    """
    seen_pks: set = set()
    ordered: list[dict] = []

    # First query results get priority (highest relevance)
    for ev in ev_results:
        for r in ev.get("results", []):
            pk = r.get("table_pk")
            if pk is None:
                continue
            if pk not in seen_pks:
                seen_pks.add(pk)
                ordered.append(r)

    total_count = sum(len(r.get("rows", [])) for r in ordered)

    merged_ev = {
        "count": total_count,
        "results": ordered[:10],
    }

    top_tables = []
    for i, r in enumerate(ordered[:5]):
        top_tables.append({
            "table_pk": r.get("table_pk"),
            "table_title": r.get("table_title", ""),
            "units": r.get("units", ""),
            "rows": len(r.get("rows", [])),
            "score": r.get("score") or (100 - i * 10),  # synthetic rank score if absent
        })

    return total_count, merged_ev, top_tables


def run(plans_path: str, parse_out: Path, retrieval_out: Path,
        limit: int = 0, uid_filter: str = ""):
    tools = _init_tools()

    plans = []
    for line in Path(plans_path).read_text().strip().split("\n"):
        if line.strip():
            plans.append(json.loads(line))

    if uid_filter:
        plans = [p for p in plans if p["uid"] == uid_filter]
    if limit:
        plans = plans[:limit]

    # Skip failed plans (no 'question' field)
    plans = [p for p in plans if "question" in p]

    print(f"\n  RESEARCH FROM PLANS — {len(plans)} questions")
    print(f"  Plans: {plans_path}")
    print(f"  Parse out: {parse_out}")
    print(f"  Retrieval out: {retrieval_out}\n")

    parse_out.parent.mkdir(parents=True, exist_ok=True)
    retrieval_out.parent.mkdir(parents=True, exist_ok=True)

    found = 0
    with open(parse_out, "w") as pf, open(retrieval_out, "w") as rf:
        for i, plan_row in enumerate(plans):
            uid = plan_row["uid"]
            question = plan_row["question"]
            gold = plan_row.get("gold", "")
            difficulty = plan_row.get("difficulty", "")
            plan = plan_row.get("plan", {})
            search_queries = plan.get("search_queries", [])

            t0 = time.time()

            # Execute all search queries
            ev_results = []
            for sq in search_queries:
                ev = _execute_search_query(tools, sq)
                ev_results.append(ev)

            # If no search_queries, fall back to data_needs
            if not ev_results:
                data_needs = plan.get("data_needs", [])
                for dn in data_needs:
                    metric = dn.get("metric", "")
                    years = dn.get("years", [])
                    year = years[0] if years else None
                    tools.reset_budgets()
                    ev = tools.extract_values(query=metric, year=year)
                    ev_results.append(ev)

            elapsed = time.time() - t0
            count, merged_ev, top_tables = _merge_results(ev_results)

            # Synthetic parsed dict
            parsed = _make_synthetic_parsed(plan_row)

            parse_row = {
                "uid": uid,
                "question": question,
                "gold": gold,
                "difficulty": difficulty,
                "parsed": parsed,
            }

            retrieval_row = {
                "uid": uid,
                "question": question,
                "gold": gold,
                "difficulty": difficulty,
                "parsed": parsed,
                "extract_values_count": count,
                "extract_values_result": merged_ev,
                "top_tables": top_tables,
                "search_candidates": [],
                "ev_latency_s": round(elapsed, 3),
                "num_queries_run": len(ev_results),
            }

            pf.write(json.dumps(parse_row) + "\n")
            rf.write(json.dumps(retrieval_row) + "\n")

            if count > 0:
                found += 1
            top_title = top_tables[0]["table_title"][:50] if top_tables else "NONE"
            print(f"  [{i+1}/{len(plans)}] {uid} queries={len(ev_results)} rows={count} top={top_title}")

    print(f"\n  Done: {found}/{len(plans)} questions found data")
    print(f"  Next steps:")
    print(f"    python3 scripts/stage_runner.py extraction \\")
    print(f"      --parse-input {parse_out} \\")
    print(f"      --retrieval-input {retrieval_out} \\")
    print(f"      -o results/stages/plans_extraction.jsonl")
    print(f"    python3 scripts/stage_runner.py computation \\")
    print(f"      --parse-input {parse_out} \\")
    print(f"      --extraction-input results/stages/plans_extraction.jsonl \\")
    print(f"      -o results/stages/plans_computation.jsonl")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", default=str(ROOT / "results" / "phase1_all_plans.jsonl"),
                        help="Path to phase1 plans JSONL")
    parser.add_argument("--parse-out", default=str(STAGES_DIR / "plans_as_parse.jsonl"),
                        help="Output: synthetic parse format")
    parser.add_argument("--retrieval-out", default=str(STAGES_DIR / "plans_retrieval.jsonl"),
                        help="Output: retrieval format with top_tables")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N plans")
    parser.add_argument("--uid", default="", help="Only process this UID")
    args = parser.parse_args()

    run(
        plans_path=args.plans,
        parse_out=Path(args.parse_out),
        retrieval_out=Path(args.retrieval_out),
        limit=args.limit,
        uid_filter=args.uid,
    )


if __name__ == "__main__":
    main()
