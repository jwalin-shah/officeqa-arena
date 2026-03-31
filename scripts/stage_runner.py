#!/usr/bin/env python3
"""Per-stage batch runner for MiniMax M2.5 trajectory analysis.

Run one stage at a time across ALL questions, review results, then proceed.

Usage:
  # Step 1: Parse all 20 arena samples
  python3 scripts/stage_runner.py parse --cases data/officeqa_full.csv --subset arena

  # Step 1b: Parse all 246
  python3 scripts/stage_runner.py parse --cases data/officeqa_full.csv

  # Step 2: Review parse results, then run retrieval (uses parse output)
  python3 scripts/stage_runner.py retrieval --parse-input results/stages/parse.jsonl

  # Step 3: Extraction (uses parse + retrieval outputs)
  python3 scripts/stage_runner.py extraction --parse-input results/stages/parse.jsonl --retrieval-input results/stages/retrieval.jsonl

  # Step 4: Computation (uses all prior outputs)
  python3 scripts/stage_runner.py computation --parse-input results/stages/parse.jsonl --extraction-input results/stages/extraction.jsonl

  # Or: full replay (same as Arena agent loop)
  python3 scripts/stage_runner.py replay --cases data/officeqa_full.csv --subset arena

Output goes to results/stages/<stage>.jsonl by default.

Env vars:
  OPENROUTER_API_KEY   — required for parse/retrieval-llm/extraction-llm/computation
  OFFICEQA_SQLITE_DB   — path to corpus SQLite (auto-detected in data/)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI
from server.tools import OfficeQATools
from src.agent import TOOL_DEFINITIONS, run_agent_loop
from src.answer import extract_final_answer, clean_answer
from src.reward import fuzzy_match_answer

DEFAULT_MODEL = os.environ.get("OFFICEQA_MODEL", "minimax/minimax-m2.5")
STAGES_DIR = ROOT / "results" / "stages"

# 20 arena sample UIDs
ARENA_UIDS = {
    "UID0004", "UID0023", "UID0030", "UID0033", "UID0041", "UID0048",
    "UID0057", "UID0097", "UID0111", "UID0127", "UID0136", "UID0167",
    "UID0192", "UID0194", "UID0199", "UID0217", "UID0220", "UID0230",
    "UID0241", "UID0246",
}


# ── LLM call ────────────────────────────────────────────────────────

def _get_client() -> OpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("Set OPENROUTER_API_KEY")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


def _chat(client: OpenAI, messages: list[dict], tools=None, model=DEFAULT_MODEL) -> dict:
    kwargs: dict = {
        "model": model,
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
    latency = time.time() - t0
    choice = resp.choices[0]
    return {
        "content": choice.message.content or "",
        "tool_calls": [
            {"name": tc.function.name, "args": json.loads(tc.function.arguments or "{}")}
            for tc in (choice.message.tool_calls or [])
        ],
        "finish_reason": choice.finish_reason,
        "latency_s": round(latency, 2),
        "tokens": {
            "prompt": resp.usage.prompt_tokens if resp.usage else 0,
            "completion": resp.usage.completion_tokens if resp.usage else 0,
        },
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
    # Find outermost { ... }
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


# ── Data loading ────────────────────────────────────────────────────

def load_cases(path: str, subset: str = "", uid_filter: str = "",
               difficulty: str = "", limit: int = 0) -> list[dict]:
    p = Path(path)
    cases: list[dict] = []

    if p.suffix == ".csv":
        with open(p, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cases.append({
                    "uid": row.get("uid", ""),
                    "question": row.get("question", ""),
                    "gold": row.get("answer", row.get("expected_answer", "")),
                    "difficulty": row.get("difficulty", ""),
                    "source_files": row.get("source_files", ""),
                })
    elif p.suffix == ".jsonl":
        for line in p.read_text().strip().split("\n"):
            if line.strip():
                c = json.loads(line)
                cases.append({
                    "uid": c.get("uid", c.get("question_id", "")),
                    "question": c["question"],
                    "gold": c.get("expected_answer", c.get("answer", "")),
                    "difficulty": c.get("metadata", {}).get("difficulty", c.get("difficulty", "")),
                    "source_files": c.get("metadata", {}).get("source_files", ""),
                })
    elif p.suffix == ".json":
        data = json.loads(p.read_text())
        if not isinstance(data, list):
            data = [data]
        for c in data:
            cases.append({
                "uid": c.get("uid", c.get("question_id", "")),
                "question": c["question"],
                "gold": c.get("expected_answer", c.get("answer", "")),
                "difficulty": c.get("difficulty", ""),
            })

    if subset == "arena":
        cases = [c for c in cases if c["uid"] in ARENA_UIDS]
    if uid_filter:
        uids = {u.strip().upper() for u in uid_filter.split(",")}
        cases = [c for c in cases if c["uid"].upper() in uids]
    if difficulty:
        cases = [c for c in cases if c.get("difficulty", "").lower() == difficulty.lower()]
    if limit > 0:
        cases = cases[:limit]

    return cases


def load_stage_output(path: str) -> dict[str, dict]:
    """Load a stage JSONL keyed by uid. Skips malformed lines."""
    out = {}
    for i, line in enumerate(Path(path).read_text().strip().split("\n")):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            out[r["uid"]] = r
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  WARN: skipping line {i+1} in {path}: {e}")
    return out


def _init_tools() -> OfficeQATools:
    db_path = os.environ.get("OFFICEQA_SQLITE_DB", "")
    if not db_path:
        for cand in [
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


def _write_result(f, result: dict):
    f.write(json.dumps(result, default=str) + "\n")
    f.flush()


# ── Stage: PARSE ────────────────────────────────────────────────────

PARSE_PROMPT = """You are a Treasury bulletin QA analyst. Given a question, extract the structured parse. Return ONLY valid JSON with these exact fields:

{{
  "target_entity": "the entity/metric being asked about",
  "time_scope": "the exact time period (specific years, months, date ranges)",
  "operation": "lookup | sum | difference | percent_change | geometric_mean | regression | weighted_average | count | other",
  "expected_answer_type": "number | percent | list | text | date",
  "unit_expectation": "millions | billions | nominal dollars | percent | yen | ratio | other",
  "fiscal_or_calendar": "fiscal | calendar | both | unclear",
  "multi_step": true or false,
  "num_tables_needed": 1 or 2 or more,
  "complexity_notes": "any special handling (inflation adjustment, FX conversion, multi-table join, etc.)"
}}

Question: {question}"""


def run_parse(cases: list[dict], output: Path, model: str):
    client = _get_client()
    print(f"\n  STAGE: PARSE — {len(cases)} questions")
    print(f"  Output: {output}\n")

    with open(output, "w") as f:
        for i, case in enumerate(cases):
            uid = case["uid"]
            question = case["question"]
            gold = case["gold"]

            prompt = PARSE_PROMPT.format(question=question)
            t0 = time.time()
            try:
                result = _chat(client, [{"role": "user", "content": prompt}], model=model)
                parsed = _extract_json(result["content"])
            except Exception as exc:
                parsed = {}
                result = {"content": "", "latency_s": time.time() - t0, "tokens": {}, "error": str(exc)}

            row = {
                "uid": uid,
                "question": question,
                "gold": gold,
                "difficulty": case.get("difficulty", ""),
                "parsed": parsed,
                "raw_response": result["content"][:500],
                "latency_s": result["latency_s"],
                "tokens": result.get("tokens", {}),
            }
            _write_result(f, row)

            # Print progress
            entity = parsed.get("target_entity", "?")[:50]
            op = parsed.get("operation", "?")
            ts = parsed.get("time_scope", "?")[:30]
            ok = "OK" if parsed.get("target_entity") else "EMPTY"
            print(f"  [{i+1}/{len(cases)}] {uid} [{ok}] entity={entity} op={op} time={ts}")

    # Summary
    results = list(load_stage_output(str(output)).values())
    has_parse = sum(1 for r in results if r.get("parsed", {}).get("target_entity"))
    print(f"\n  Parse complete: {has_parse}/{len(results)} have target_entity")
    total_tokens = sum(r.get("tokens", {}).get("completion", 0) for r in results)
    print(f"  Total completion tokens: {total_tokens}")


# ── Stage: RETRIEVAL ────────────────────────────────────────────────

def run_retrieval(parse_input: str, output: Path, model: str):
    tools = _init_tools()
    client = _get_client()
    parses = load_stage_output(parse_input)
    cases = list(parses.values())
    print(f"\n  STAGE: RETRIEVAL — {len(cases)} questions")
    print(f"  Parse input: {parse_input}")
    print(f"  Output: {output}\n")

    with open(output, "w") as f:
        for i, case in enumerate(cases):
            uid = case["uid"]
            question = case["question"]
            gold = case["gold"]
            parsed = case.get("parsed", {})

            tools.reset_budgets()

            # Build query from parse
            query = parsed.get("target_entity", question[:100])
            year = None
            time_scope = parsed.get("time_scope", "")
            yr_match = re.search(r"\b(1[89]\d{2}|20[0-2]\d)\b", str(time_scope))
            if yr_match:
                year = int(yr_match.group(1))

            # Call extract_values — same first tool as real agent
            t0 = time.time()
            ev_result = tools.extract_values(query=query, year=year)
            ev_latency = time.time() - t0

            # Also get raw search candidates
            tools.reset_budgets()
            search_result = tools.search_tables(
                query=query, year_range=[year, year] if year else None
            )
            tools.reset_budgets()

            ev_count = ev_result.get("count", 0)
            candidates = search_result.get("candidates", [])[:5]
            top_tables = []
            if ev_result.get("results"):
                for r in ev_result["results"][:3]:
                    top_tables.append({
                        "table_pk": r.get("table_pk"),
                        "table_title": r.get("table_title", ""),
                        "units": r.get("units", ""),
                        "rows": len(r.get("rows", [])),
                        "score": r.get("score", 0),
                    })

            row = {
                "uid": uid,
                "question": question,
                "gold": gold,
                "difficulty": case.get("difficulty", ""),
                "parsed": parsed,
                "extract_values_count": ev_count,
                "extract_values_result": ev_result,
                "top_tables": top_tables,
                "search_candidates": candidates,
                "ev_latency_s": round(ev_latency, 3),
            }
            _write_result(f, row)

            top_title = top_tables[0]["table_title"][:50] if top_tables else "NONE"
            print(f"  [{i+1}/{len(cases)}] {uid} ev_rows={ev_count} top_table={top_title}")

    # Summary
    results = list(load_stage_output(str(output)).values())
    has_results = sum(1 for r in results if r.get("extract_values_count", 0) > 0)
    print(f"\n  Retrieval complete: {has_results}/{len(results)} found rows via extract_values")


# ── Stage: EXTRACTION ───────────────────────────────────────────────

EXTRACTION_PROMPT = """You are a Treasury bulletin QA analyst extracting evidence from a table.

Question: {question}
Parse: {parse}
Table: {table_title} (pk={table_pk})
Units: {units}

Rows from the table:
{rows}

Extract ONLY the values needed to answer the question. Return valid JSON:
{{
  "relevant_values": [
    {{"label": "row/item name", "value": numeric_value, "year": YYYY, "column": "column name", "unit_scale": 1}}
  ],
  "units_confirmed": "the unit scale of these values",
  "notes": "anything unusual"
}}"""


def run_extraction(parse_input: str, retrieval_input: str, output: Path, model: str):
    tools = _init_tools()
    client = _get_client()
    parses = load_stage_output(parse_input)
    retrievals = load_stage_output(retrieval_input)
    uids = [uid for uid in retrievals if uid in parses]
    print(f"\n  STAGE: EXTRACTION — {len(uids)} questions")
    print(f"  Output: {output}\n")

    with open(output, "w") as f:
        for i, uid in enumerate(uids):
            p = parses[uid]
            r = retrievals[uid]
            question = p["question"]
            gold = p["gold"]
            parsed = p.get("parsed", {})

            # Find best table from retrieval
            table_pk = None
            table_title = ""
            units = ""
            if r.get("top_tables"):
                best = r["top_tables"][0]
                table_pk = best.get("table_pk")
                table_title = best.get("table_title", "")
                units = best.get("units", "")

            if not table_pk:
                row = {
                    "uid": uid, "question": question, "gold": gold,
                    "difficulty": p.get("difficulty", ""),
                    "parsed": parsed,
                    "error": "no_table_found",
                    "llm_extracted": {},
                }
                _write_result(f, row)
                print(f"  [{i+1}/{len(uids)}] {uid} ERROR: no table found")
                continue

            # Get profile and rows
            profile = tools.get_table_profile(table_pk)
            if not units:
                units = profile.get("units_line", "") or ""

            year = None
            yr_match = re.search(r"\b(1[89]\d{2}|20[0-2]\d)\b", str(parsed.get("time_scope", "")))
            if yr_match:
                year = int(yr_match.group(1))

            rows_result = tools.query_table_rows(table_pk=table_pk, year=year, limit=50)
            rows = rows_result.get("rows", [])

            # Ask MiniMax to extract
            rows_text = json.dumps(rows[:25], indent=2, default=str)
            prompt = EXTRACTION_PROMPT.format(
                question=question,
                parse=json.dumps(parsed, indent=2),
                table_title=table_title,
                table_pk=table_pk,
                rows=rows_text,
                units=units,
            )
            try:
                llm = _chat(client, [{"role": "user", "content": prompt}], model=model)
                extracted = _extract_json(llm["content"])
            except Exception as exc:
                extracted = {}
                llm = {"content": "", "latency_s": 0, "tokens": {}, "error": str(exc)}

            n_values = len(extracted.get("relevant_values", []))
            row = {
                "uid": uid, "question": question, "gold": gold,
                "difficulty": p.get("difficulty", ""),
                "parsed": parsed,
                "table_pk": table_pk,
                "table_title": table_title,
                "units": units,
                "rows_returned": len(rows),
                "llm_extracted": extracted,
                "llm_raw": llm["content"][:500],
                "latency_s": llm["latency_s"],
                "tokens": llm.get("tokens", {}),
            }
            _write_result(f, row)
            print(f"  [{i+1}/{len(uids)}] {uid} table={table_title[:40]} values={n_values}")

    results = list(load_stage_output(str(output)).values())
    has_values = sum(1 for r in results if r.get("llm_extracted", {}).get("relevant_values"))
    print(f"\n  Extraction complete: {has_values}/{len(results)} have relevant_values")


# ── Stage: COMPUTATION ──────────────────────────────────────────────

COMPUTE_PROMPT = """You are a Treasury bulletin QA analyst. Compute the final answer.

Question: {question}

Extracted evidence:
{evidence}

Use the compute_expression tool for ALL arithmetic. Then return JSON:
{{
  "computation_steps": ["step1", "step2"],
  "formatted_answer": "final answer value only",
  "confidence": "high | medium | low"
}}"""


def run_computation(parse_input: str, extraction_input: str, output: Path, model: str):
    tools = _init_tools()
    client = _get_client()
    parses = load_stage_output(parse_input)
    extractions = load_stage_output(extraction_input)
    uids = [uid for uid in extractions if uid in parses]
    print(f"\n  STAGE: COMPUTATION — {len(uids)} questions")
    print(f"  Output: {output}\n")

    correct = 0
    total = 0

    with open(output, "w") as f:
        for i, uid in enumerate(uids):
            p = parses[uid]
            e = extractions[uid]
            question = p["question"]
            gold = p["gold"]
            evidence = e.get("llm_extracted", {})

            if e.get("error") or not evidence.get("relevant_values"):
                row = {
                    "uid": uid, "question": question, "gold": gold,
                    "difficulty": p.get("difficulty", ""),
                    "final_answer": None, "is_correct": False,
                    "error": "no_evidence",
                }
                _write_result(f, row)
                total += 1
                print(f"  [{i+1}/{len(uids)}] {uid} SKIP (no evidence)")
                continue

            prompt = COMPUTE_PROMPT.format(
                question=question,
                evidence=json.dumps(evidence, indent=2, default=str),
            )
            compute_tool = [
                t for t in TOOL_DEFINITIONS if t["function"]["name"] == "compute_expression"
            ]

            try:
                llm = _chat(client, [{"role": "user", "content": prompt}], tools=compute_tool, model=model)
            except Exception as exc:
                row = {
                    "uid": uid, "question": question, "gold": gold,
                    "difficulty": p.get("difficulty", ""),
                    "final_answer": None, "is_correct": False,
                    "error": str(exc),
                }
                _write_result(f, row)
                total += 1
                print(f"  [{i+1}/{len(uids)}] {uid} ERROR: {exc}")
                continue

            # Execute any compute_expression calls
            compute_results = []
            for tc in llm.get("tool_calls", []):
                if tc["name"] == "compute_expression":
                    cr = tools.compute_expression(**tc["args"])
                    compute_results.append({"expression": tc["args"], "result": cr})

            computed = _extract_json(llm["content"])

            # Extract final answer
            final = None
            if computed and computed.get("formatted_answer"):
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

            is_correct = False
            detail = ""
            if final and gold:
                is_correct, detail = fuzzy_match_answer(gold, final)

            total += 1
            if is_correct:
                correct += 1

            row = {
                "uid": uid, "question": question, "gold": gold,
                "difficulty": p.get("difficulty", ""),
                "final_answer": final,
                "is_correct": is_correct,
                "match_detail": detail,
                "compute_tool_calls": compute_results,
                "llm_computed": computed,
                "llm_raw": llm["content"][:500],
                "latency_s": llm["latency_s"],
                "tokens": llm.get("tokens", {}),
            }
            _write_result(f, row)
            marker = "PASS" if is_correct else "FAIL"
            print(f"  [{i+1}/{len(uids)}] {uid} {marker} pred={final} gold={gold}")

    print(f"\n  Computation complete: {correct}/{total} correct ({correct/total*100:.1f}%)" if total else "")


# ── Stage: REPLAY (full agent loop, matches Arena) ──────────────────

def run_replay_stage(cases: list[dict], output: Path, model: str, max_iter: int):
    tools = _init_tools()
    print(f"\n  STAGE: REPLAY (full agent loop) — {len(cases)} questions")
    print(f"  Model: {model}  Max iterations: {max_iter}")
    print(f"  Output: {output}\n")

    correct = 0

    with open(output, "w") as f:
        for i, case in enumerate(cases):
            uid = case["uid"]
            question = case["question"]
            gold = case["gold"]

            tools.reset_budgets()
            t0 = time.time()
            try:
                answer, log = run_agent_loop(
                    instruction=question, tools_obj=tools,
                    model=model, max_iterations=max_iter, verbose=True,
                )
            except Exception as exc:
                answer = ""
                log = [{"error": str(exc)}]

            elapsed = time.time() - t0
            is_correct = False
            detail = ""
            if answer and gold:
                is_correct, detail = fuzzy_match_answer(gold, answer)
            if is_correct:
                correct += 1

            tool_hist: dict[str, int] = {}
            total_tools = 0
            for entry in log:
                for tc in entry.get("tool_calls", []):
                    n = tc.get("name", "?")
                    tool_hist[n] = tool_hist.get(n, 0) + 1
                    total_tools += 1

            row = {
                "uid": uid, "question": question, "gold": gold,
                "difficulty": case.get("difficulty", ""),
                "predicted": answer,
                "is_correct": is_correct,
                "match_detail": detail,
                "iterations": len(log),
                "tool_calls": total_tools,
                "tool_histogram": tool_hist,
                "elapsed_s": round(elapsed, 2),
                "log": log,
            }
            _write_result(f, row)
            marker = "PASS" if is_correct else "FAIL"
            print(f"  [{i+1}/{len(cases)}] {uid} {marker} pred={answer} gold={gold} "
                  f"iters={len(log)} tools={total_tools} {elapsed:.1f}s\n")

    total = len(cases)
    print(f"\n  Replay complete: {correct}/{total} ({correct/total*100:.1f}%)" if total else "")


# ── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Per-stage batch runner for MiniMax trajectory analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("stage", choices=["parse", "retrieval", "extraction", "computation", "replay"],
                        help="Which stage to run")
    parser.add_argument("--cases", type=str, help="Input cases (CSV/JSON/JSONL)")
    parser.add_argument("--subset", type=str, default="", help="'arena' for 20 sample tasks, or comma-separated UIDs")
    parser.add_argument("--difficulty", type=str, default="", help="Filter: easy or hard")
    parser.add_argument("--limit", type=int, default=0, help="Max cases (0=all)")
    parser.add_argument("--output", type=str, default="", help="Output JSONL (default: results/stages/<stage>.jsonl)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--max-iterations", type=int, default=15, help="For replay mode")

    # Stage inputs (for stages that depend on prior stage output)
    parser.add_argument("--parse-input", type=str, default="", help="Path to parse.jsonl (for retrieval/extraction/computation)")
    parser.add_argument("--retrieval-input", type=str, default="", help="Path to retrieval.jsonl (for extraction)")
    parser.add_argument("--extraction-input", type=str, default="", help="Path to extraction.jsonl (for computation)")

    args = parser.parse_args()

    STAGES_DIR.mkdir(parents=True, exist_ok=True)
    output = Path(args.output) if args.output else STAGES_DIR / f"{args.stage}.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)

    # Determine subset filter
    uid_filter = ""
    subset = args.subset
    if subset and subset != "arena":
        uid_filter = subset
        subset = ""

    if args.stage == "parse":
        if not args.cases:
            parser.error("parse requires --cases")
        cases = load_cases(args.cases, subset=subset, uid_filter=uid_filter,
                           difficulty=args.difficulty, limit=args.limit)
        run_parse(cases, output, args.model)

    elif args.stage == "retrieval":
        parse_input = args.parse_input or str(STAGES_DIR / "parse.jsonl")
        if not Path(parse_input).exists():
            parser.error(f"Parse output not found: {parse_input}. Run parse stage first.")
        run_retrieval(parse_input, output, args.model)

    elif args.stage == "extraction":
        parse_input = args.parse_input or str(STAGES_DIR / "parse.jsonl")
        retrieval_input = args.retrieval_input or str(STAGES_DIR / "retrieval.jsonl")
        if not Path(parse_input).exists():
            parser.error(f"Parse output not found: {parse_input}")
        if not Path(retrieval_input).exists():
            parser.error(f"Retrieval output not found: {retrieval_input}")
        run_extraction(parse_input, retrieval_input, output, args.model)

    elif args.stage == "computation":
        parse_input = args.parse_input or str(STAGES_DIR / "parse.jsonl")
        extraction_input = args.extraction_input or str(STAGES_DIR / "extraction.jsonl")
        if not Path(parse_input).exists():
            parser.error(f"Parse output not found: {parse_input}")
        if not Path(extraction_input).exists():
            parser.error(f"Extraction output not found: {extraction_input}")
        run_computation(parse_input, extraction_input, output, args.model)

    elif args.stage == "replay":
        if not args.cases:
            parser.error("replay requires --cases")
        cases = load_cases(args.cases, subset=subset, uid_filter=uid_filter,
                           difficulty=args.difficulty, limit=args.limit)
        run_replay_stage(cases, output, args.model, args.max_iterations)

    print(f"\n  Output: {output}")


if __name__ == "__main__":
    main()
