#!/usr/bin/env python3
"""Run planner phase directly via OpenRouter API — no sandbox needed.

The planner doesn't use tools, so we can call the LLM directly.
Much faster than spinning up Daytona sandboxes.

Usage:
  python3 scripts/run_planner.py                         # all 246 from full CSV
  python3 scripts/run_planner.py --subset dev             # 20 dev questions
  python3 scripts/run_planner.py --limit 5                # first 5
  python3 scripts/run_planner.py --workers 20             # 20 parallel requests
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Load .env
_env_file = ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# Import the validator from orchestrator (path hack for local run)
sys.path.insert(0, str(ROOT / "src"))

# Inline the validation since we can't import openhands locally
VALID_FAMILIES = {
    "public_debt", "revenue_receipts", "federal_securities",
    "international_capital", "monetary", "cash_operations",
    "budget_expenditures", "defense_expenditures", "trade",
    "cash_flow", "other", "unknown",
}
VALID_TOOLS = {
    "search_canonical", "search_ledger", "extract_values",
    "get_time_series", "get_multi_year_series", "search_tables",
    "query_table_rows", "get_table_profile", "get_file_structure",
    "compute_expression", "get_cpi_index", "get_exchange_rate",
    "get_fiscal_year_bounds", "resolve_agency_alias", "grep_corpus",
    "verify_answer", "submit_answer",
}
VALID_COMPUTE_FUNCS = {
    "sum", "mean", "stdev", "geometric_mean", "cagr", "linreg",
    "correlation", "theil_index", "boxcox", "gini", "percentile",
    "iqr", "mad", "cv", "median", "variance", "skewness", "kurtosis",
    "hhi", "local_maxima", "local_minima", "exp_smooth", "abs",
    "round", "min", "max", "sqrt", "log", "ln", "exp", "prod", "pow",
    "len", "zscore", "kl_divergence", "interpolate",
}


def validate_plan(plan: dict, question: str) -> dict:
    warnings = []
    fixes = {}
    q_lower = question.lower()

    for field in ("data_needs", "search_queries", "computation", "answer_format"):
        if field not in plan:
            warnings.append(f"missing:{field}")

    for i, dn in enumerate(plan.get("data_needs", [])):
        for yr in dn.get("years", []):
            if isinstance(yr, (int, float)) and not (1900 <= yr <= 2030):
                warnings.append(f"bad_year:{yr}")
        family = dn.get("table_family", "unknown")
        if family and family not in VALID_FAMILIES:
            warnings.append(f"bad_family:{family}")
            dn["table_family"] = "unknown"
            fixes[f"data_needs[{i}].table_family"] = "unknown"
        pb = dn.get("period_basis", "")
        if pb == "fiscal" and "calendar year" in q_lower:
            warnings.append("fiscal_calendar_mismatch")
        if pb == "calendar" and "fiscal year" in q_lower and "calendar" not in q_lower:
            warnings.append("calendar_fiscal_mismatch")

    for i, sq in enumerate(plan.get("search_queries", [])):
        tool = sq.get("tool", "")
        if tool and tool not in VALID_TOOLS:
            warnings.append(f"bad_tool:{tool}")

    comp = plan.get("computation", {})
    for func in comp.get("functions_needed", []):
        if func not in VALID_COMPUTE_FUNCS:
            warnings.append(f"missing_func:{func}")

    if plan.get("data_needs") and not plan.get("search_queries"):
        warnings.append("no_search_queries")

    return {"valid": not any(w.startswith("missing:") for w in warnings), "warnings": warnings, "plan": plan}


# Read the planner system prompt
PLANNER_PROMPT = (ROOT / "prompts" / "planner_system.j2").read_text()
# Remove the {{ instruction }} placeholder — we'll add the question separately
PLANNER_PROMPT = PLANNER_PROMPT.replace("{{ instruction }}", "").strip()


async def plan_one(session, uid: str, question: str, gold: str, api_key: str,
                   model: str, sem: asyncio.Semaphore) -> dict:
    import aiohttp

    async with sem:
        t0 = time.time()
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": f"QUESTION: {question}"},
                {"role": "assistant", "content": "{"},
            ],
            "temperature": 0.0,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                data = await resp.json()

            if "error" in data:
                return {"uid": uid, "question": question, "error": str(data["error"]), "elapsed_s": round(time.time() - t0, 2)}

            raw_content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            if raw_content is None:
                return {
                    "uid": uid, "gold": gold, "question": question,
                    "error": "null_content", "raw": "",
                    "elapsed_s": round(time.time() - t0, 2),
                    "tokens": {"prompt": usage.get("prompt_tokens", 0), "completion": usage.get("completion_tokens", 0)},
                }

            # Re-attach the prefill '{' if the model returned the continuation only
            content = raw_content if raw_content.lstrip().startswith("{") else "{" + raw_content

            # Extract JSON plan
            plan = None
            try:
                plan = json.loads(content.strip())
            except json.JSONDecodeError:
                # Try inside markdown
                m = re.search(r'```(?:json)?\s*\n?(\{.*?\})\s*\n?```', content, re.DOTALL)
                if m:
                    try:
                        plan = json.loads(m.group(1))
                    except json.JSONDecodeError:
                        pass
                if not plan:
                    start = content.find('{')
                    if start >= 0:
                        depth = 0
                        for i in range(start, len(content)):
                            if content[i] == '{': depth += 1
                            elif content[i] == '}':
                                depth -= 1
                                if depth == 0:
                                    try:
                                        plan = json.loads(content[start:i+1])
                                    except json.JSONDecodeError:
                                        pass
                                    break

            # If model wrapped the object in an array, unwrap it
            if isinstance(plan, list) and plan and isinstance(plan[0], dict):
                plan = plan[0]

            if not plan or not isinstance(plan, dict):
                return {
                    "uid": uid, "gold": gold, "question": question,
                    "error": "no_json", "raw": raw_content[:500],
                    "elapsed_s": round(time.time() - t0, 2),
                    "tokens": {"prompt": usage.get("prompt_tokens", 0), "completion": usage.get("completion_tokens", 0)},
                }

            # Validate
            validation = validate_plan(plan, question)

            return {
                "uid": uid,
                "gold": gold,
                "question": question,
                "plan": validation["plan"],
                "valid": validation["valid"],
                "warnings": validation["warnings"],
                "feasibility": plan.get("feasibility", "?"),
                "computation_type": plan.get("computation", {}).get("type", "?"),
                "answer_format": plan.get("answer_format", "?"),
                "estimated_calls": plan.get("estimated_tool_calls", 0),
                "num_data_needs": len(plan.get("data_needs", [])),
                "num_search_queries": len(plan.get("search_queries", [])),
                "functions_needed": plan.get("computation", {}).get("functions_needed", []),
                "elapsed_s": round(time.time() - t0, 2),
                "tokens": {"prompt": usage.get("prompt_tokens", 0), "completion": usage.get("completion_tokens", 0)},
            }

        except Exception as e:
            return {"uid": uid, "question": question, "error": str(e) or repr(e), "elapsed_s": round(time.time() - t0, 2)}


def load_cases(path: str) -> list[dict]:
    cases = []
    with open(path) as f:
        for row in csv.DictReader(f):
            cases.append({
                "uid": row.get("uid", ""),
                "question": row.get("question", ""),
                "gold": row.get("answer", row.get("expected_answer", "")),
            })
    return cases


async def run_all(cases: list[dict], model: str, api_key: str, workers: int, output: Path):
    import aiohttp

    sem = asyncio.Semaphore(workers)
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Planner: {len(cases)} questions, {workers} parallel, model={model}")
    print(f"Output: {output}\n")

    async with aiohttp.ClientSession() as session:
        tasks = [
            plan_one(session, c["uid"], c["question"], c["gold"], api_key, model, sem)
            for c in cases
        ]

        results = []
        with open(output, "w") as f:
            for coro in asyncio.as_completed(tasks):
                r = await coro
                results.append(r)
                f.write(json.dumps(r, default=str) + "\n")
                f.flush()

                uid = r.get("uid", "?")
                err = r.get("error", "")
                if err:
                    print(f"  [{len(results)}/{len(cases)}] {uid}: ERROR — {err[:60]}")
                else:
                    feas = r.get("feasibility", "?")
                    comp = r.get("computation_type", "?")
                    valid = "✓" if r.get("valid") else "✗"
                    warns = len(r.get("warnings", []))
                    print(f"  [{len(results)}/{len(cases)}] {uid}: {valid} {feas:10s} | {comp:20s} | warns={warns}")

    # Summary
    print(f"\n{'='*60}")
    print(f"PLANNER SUMMARY ({len(results)} questions)")
    print(f"{'='*60}")

    valid_count = sum(1 for r in results if r.get("valid"))
    error_count = sum(1 for r in results if r.get("error"))
    print(f"\nValid plans: {valid_count}/{len(results)} ({100*valid_count/max(len(results),1):.0f}%)")
    print(f"Errors: {error_count}")

    # Feasibility
    feas = {}
    for r in results:
        f = r.get("feasibility", "error" if r.get("error") else "?")
        feas[f] = feas.get(f, 0) + 1
    print("\nFeasibility:")
    for f, c in sorted(feas.items(), key=lambda x: -x[1]):
        print(f"  {f:15s}: {c:3d}")

    # Computation types
    comps = {}
    for r in results:
        ct = r.get("computation_type", "?")
        comps[ct] = comps.get(ct, 0) + 1
    print("\nComputation types:")
    for ct, c in sorted(comps.items(), key=lambda x: -x[1]):
        print(f"  {ct:25s}: {c:3d}")

    # Functions needed
    funcs = {}
    for r in results:
        for fn in r.get("functions_needed", []):
            funcs[fn] = funcs.get(fn, 0) + 1
    if funcs:
        print("\nCompute functions needed:")
        for fn, c in sorted(funcs.items(), key=lambda x: -x[1]):
            print(f"  {fn:25s}: {c:3d}")

    # Warnings
    all_warns = {}
    for r in results:
        for w in r.get("warnings", []):
            all_warns[w] = all_warns.get(w, 0) + 1
    if all_warns:
        print("\nWarnings:")
        for w, c in sorted(all_warns.items(), key=lambda x: -x[1]):
            print(f"  {w:40s}: {c:3d}")

    # Cost
    total_prompt = sum(r.get("tokens", {}).get("prompt", 0) for r in results)
    total_comp = sum(r.get("tokens", {}).get("completion", 0) for r in results)
    total_time = sum(r.get("elapsed_s", 0) for r in results)
    print(f"\nTokens: {total_prompt:,} prompt + {total_comp:,} completion")
    print(f"Time: {total_time:.1f}s total, {total_time/max(len(results),1):.1f}s avg")

    return results


DEV_UIDS = {
    "UID0005", "UID0007", "UID0009", "UID0010", "UID0012", "UID0013",
    "UID0015", "UID0017", "UID0018", "UID0019", "UID0022", "UID0025",
    "UID0027", "UID0028", "UID0029", "UID0030", "UID0031", "UID0032",
    "UID0035", "UID0036",
}


def main():
    parser = argparse.ArgumentParser(description="Run planner phase via API")
    parser.add_argument("--cases", default=str(ROOT / "data" / "officeqa_full.csv"))
    parser.add_argument("--output", default=str(ROOT / "results" / "phase1_plans.jsonl"))
    parser.add_argument("--model", default="minimax/minimax-m2.5")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--subset", default="", help="'dev' or comma-separated UIDs")
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("ERROR: Set OPENROUTER_API_KEY"); return

    cases = load_cases(args.cases)

    if args.subset == "dev":
        cases = [c for c in cases if c["uid"] in DEV_UIDS]
    elif args.subset:
        uids = {u.strip().upper() for u in args.subset.split(",")}
        cases = [c for c in cases if c["uid"].upper() in uids]

    if args.limit > 0:
        cases = cases[:args.limit]

    asyncio.run(run_all(cases, args.model, api_key, args.workers, Path(args.output)))


if __name__ == "__main__":
    main()
