#!/usr/bin/env python3
"""Staged trace debugger for MiniMax M2.5 on OfficeQA.

Replaces missing Arena traces with local step-by-step trajectory analysis.
Runs the EXACT same tooling/prompt stack as the Arena submission path.

Three modes:
  1. interactive  — single question, pause at each stage, human inspects
  2. batch        — many questions, auto-score each stage, dump results
  3. replay       — full agent loop (identical to Arena), capture trace

Supports all data formats:
  - officeqa_full.csv   (all 246 questions)
  - *.jsonl             (dev.jsonl, smoke.jsonl)
  - *.json              (sample.json)

Usage:
  # Interactive single question from full set
  python3 scripts/trace_debugger.py --uid UID0001 --cases data/officeqa_full.csv

  # Interactive with inline question
  python3 scripts/trace_debugger.py --question "What were total budget receipts in FY 1950?" --gold "39443"

  # Batch staged analysis over all 246 questions
  python3 scripts/trace_debugger.py --cases data/officeqa_full.csv --batch --output results/trace_all.jsonl

  # Full agent replay (matches Arena exactly)
  python3 scripts/trace_debugger.py --cases data/officeqa_full.csv --replay --output results/replay.jsonl

  # Replay subset: 5 easy + 10 hard failures
  python3 scripts/trace_debugger.py --cases data/officeqa_full.csv --replay --subset UID0001,UID0002,UID0005

  # Filter by difficulty
  python3 scripts/trace_debugger.py --cases data/officeqa_full.csv --replay --difficulty easy --output results/easy.jsonl

Env vars:
  OPENROUTER_API_KEY   — required
  OFFICEQA_SQLITE_DB   — path to corpus SQLite (auto-detected if absent)
  OFFICEQA_MODEL       — model override (default: minimax/minimax-m2.5)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI
from server.tools import OfficeQATools
from server.mcp_stdio import TOOL_SCHEMAS
from src.agent import (
    _render_system_prompt,
    _load_skills,
    _call_tool,
    TOOL_DEFINITIONS,
    run_agent_loop,
)
from src.answer import extract_final_answer, extract_echo_answer, clean_answer
from src.reward import fuzzy_match_answer, score_answer

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("OFFICEQA_MODEL", "minimax/minimax-m2.5")

# ── OpenRouter client ───────────────────────────────────────────────

def _get_client() -> OpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("Set OPENROUTER_API_KEY")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


def _chat(
    client: OpenAI,
    messages: list[dict],
    tools: list | None = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Single LLM call — same params as Arena agent loop."""
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 4096,
    }
    # Match arena.yaml: reasoning_effort medium
    kwargs["extra_body"] = {"reasoning_effort": "medium"}
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
        "usage": {
            "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
            "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
        },
    }


# ── Stage prompts (isolated probes) ────────────────────────────────

PARSE_PROMPT = """You are a Treasury bulletin QA analyst. Given a question, extract the structured parse. Return ONLY valid JSON:

{{
  "target_entity": "the entity/metric being asked about",
  "time_scope": "the time period (year, month, date range)",
  "operation": "what operation is needed (lookup, sum, difference, geometric_mean, regression, etc.)",
  "expected_answer_type": "number | percent | list | text",
  "unit_expectation": "millions | billions | nominal dollars | percent | etc.",
  "fiscal_or_calendar": "fiscal | calendar | unclear",
  "multi_step": true or false,
  "complexity_notes": "any special handling needed"
}}

Question: {question}"""

RETRIEVAL_PROMPT = """You are a Treasury bulletin QA analyst deciding which table to inspect.

Question: {question}
Parse: {parse}

Below are the candidate tables returned by search. Pick the best table(s) and explain why.

Candidates:
{candidates}

Return JSON:
{{
  "chosen_tables": [{{"table_pk": ..., "table_title": "...", "reason": "..."}}],
  "confidence": "high | medium | low",
  "fallback_strategy": "what to try if this table doesn't have the data"
}}"""

EXTRACTION_PROMPT = """You are a Treasury bulletin QA analyst extracting evidence.

Question: {question}
Parse: {parse}
Table: {table_title} (pk={table_pk})

Here are the rows from the table:
{rows}

Table units: {units}

Extract the relevant values. Return JSON:
{{
  "relevant_values": [
    {{"label": "...", "value": ..., "year": ..., "column": "...", "unit_scale": ...}}
  ],
  "units_confirmed": "...",
  "notes": "anything unusual about the data"
}}"""

COMPUTE_PROMPT = """You are a Treasury bulletin QA analyst computing the final answer.

Question: {question}
Parse: {parse}
Extracted evidence:
{evidence}

Compute the answer step by step. Show your work, then return JSON:
{{
  "computation_steps": ["step1", "step2", ...],
  "raw_result": ...,
  "formatted_answer": "...",
  "confidence": "high | medium | low"
}}"""


# ── Failure classification (from archived eval.py) ──────────────────

def classify_failure(predicted: str, expected: str, log: list[dict]) -> str:
    """Classify a failure into a bucket."""
    if not predicted:
        return "timeout"

    pred_num = exp_num = None
    try:
        pred_num = float(re.sub(r"[,$%]", "", predicted))
    except (ValueError, TypeError):
        pass
    try:
        exp_num = float(re.sub(r"[,$%]", "", expected))
    except (ValueError, TypeError):
        pass

    # Unit scale error: off by ~1000x or ~1000000x
    if pred_num is not None and exp_num is not None and exp_num != 0:
        ratio = pred_num / exp_num
        if 900 < ratio < 1100 or 0.0009 < ratio < 0.0011:
            return "units_scale"
        if 9e5 < ratio < 1.1e6 or 9e-7 < ratio < 1.1e-6:
            return "units_scale"

    # Check tool patterns
    total_tool_calls = 0
    empty_query_rows = 0
    for entry in log:
        tcs = entry.get("tool_calls", [])
        total_tool_calls += len(tcs)
        for tc in tcs:
            if tc.get("name") == "query_table_rows":
                rf = tc.get("result_full", {})
                if isinstance(rf, dict) and rf.get("count", -1) == 0:
                    empty_query_rows += 1

    if empty_query_rows >= 3 and total_tool_calls > 0:
        if empty_query_rows / max(total_tool_calls, 1) > 0.3:
            return "over_filter"

    if pred_num is not None and exp_num is not None and exp_num != 0:
        pct_diff = abs(pred_num - exp_num) / abs(exp_num) * 100
        if pct_diff < 20:
            return "math_compute"
        if pct_diff < 50:
            return "wrong_row_col"
        return "retrieval_wrong_table"

    return "unknown"


# ── Staged pipeline ─────────────────────────────────────────────────

class TracedRun:
    """One traced run through the staged pipeline."""

    def __init__(self, uid: str, question: str, gold: str,
                 tools: OfficeQATools, client: OpenAI, model: str = DEFAULT_MODEL):
        self.uid = uid
        self.question = question
        self.gold = gold
        self.tools = tools
        self.client = client
        self.model = model
        self.trace: dict = {
            "uid": uid,
            "question": question,
            "gold_answer": gold,
            "stages": {},
            "error_stage": None,
            "final_answer": None,
            "is_correct": None,
        }

    def run_parse(self) -> dict:
        """Stage A: Parse the question."""
        prompt = PARSE_PROMPT.format(question=self.question)
        result = _chat(self.client, [{"role": "user", "content": prompt}], model=self.model)
        parsed = self._extract_json(result["content"])
        stage = {
            "raw_response": result["content"],
            "parsed": parsed,
            "latency_s": result["latency_s"],
            "tokens": result["usage"],
        }
        self.trace["stages"]["parse"] = stage
        return stage

    def run_retrieval(self, parse_result: dict) -> dict:
        """Stage B: Find candidate tables using the real tools."""
        self.tools.reset_budgets()

        parsed = parse_result.get("parsed", {})
        query = parsed.get("target_entity", self.question[:100])
        year = None
        time_scope = parsed.get("time_scope", "")
        yr_match = re.search(r"\b(1[89]\d{2}|20[0-2]\d)\b", str(time_scope))
        if yr_match:
            year = int(yr_match.group(1))

        # Call extract_values (same first action as real agent)
        t0 = time.time()
        ev_result = self.tools.extract_values(query=query, year=year)
        ev_latency = time.time() - t0

        # Also get raw candidates for inspection
        self.tools.reset_budgets()
        search_result = self.tools.search_tables(
            query=query, year_range=[year, year] if year else None
        )
        self.tools.reset_budgets()

        # Ask MiniMax which table it would pick
        candidates_text = json.dumps(
            search_result.get("candidates", [])[:8], indent=2, default=str
        )
        retrieval_prompt = RETRIEVAL_PROMPT.format(
            question=self.question,
            parse=json.dumps(parsed, indent=2),
            candidates=candidates_text,
        )
        llm_result = _chat(
            self.client, [{"role": "user", "content": retrieval_prompt}], model=self.model
        )
        llm_choice = self._extract_json(llm_result["content"])

        stage = {
            "extract_values_result": ev_result,
            "extract_values_latency_s": round(ev_latency, 3),
            "search_candidates": search_result.get("candidates", [])[:8],
            "llm_table_choice": llm_choice,
            "llm_raw": llm_result["content"],
            "llm_latency_s": llm_result["latency_s"],
            "llm_tokens": llm_result["usage"],
        }
        self.trace["stages"]["retrieval"] = stage
        return stage

    def run_extraction(self, parse_result: dict, retrieval_result: dict) -> dict:
        """Stage C: Extract evidence from chosen table."""
        parsed = parse_result.get("parsed", {})
        table_pk = None
        table_title = ""
        units = ""

        ev = retrieval_result.get("extract_values_result", {})
        if ev.get("results"):
            best = ev["results"][0]
            table_pk = best.get("table_pk")
            table_title = best.get("table_title", "")
            units = best.get("units", "")

        llm_choice = retrieval_result.get("llm_table_choice", {})
        chosen = llm_choice.get("chosen_tables") or [{}]
        if chosen and chosen[0].get("table_pk"):
            table_pk = chosen[0]["table_pk"]

        if not table_pk:
            stage = {"error": "No table found", "rows": []}
            self.trace["stages"]["extraction"] = stage
            self.trace["error_stage"] = "retrieval"
            return stage

        profile = self.tools.get_table_profile(table_pk)
        if not units:
            units = profile.get("units_line", "") or profile.get("units", "")

        year = None
        time_scope = parsed.get("time_scope", "")
        yr_match = re.search(r"\b(1[89]\d{2}|20[0-2]\d)\b", str(time_scope))
        if yr_match:
            year = int(yr_match.group(1))

        rows_result = self.tools.query_table_rows(table_pk=table_pk, year=year, limit=50)
        rows = rows_result.get("rows", [])

        rows_text = json.dumps(rows[:20], indent=2, default=str)
        extraction_prompt = EXTRACTION_PROMPT.format(
            question=self.question,
            parse=json.dumps(parsed, indent=2),
            table_title=table_title,
            table_pk=table_pk,
            rows=rows_text,
            units=units,
        )
        llm_result = _chat(
            self.client, [{"role": "user", "content": extraction_prompt}], model=self.model
        )
        llm_extracted = self._extract_json(llm_result["content"])

        stage = {
            "table_pk": table_pk,
            "table_title": table_title,
            "profile": profile,
            "units": units,
            "rows_returned": len(rows),
            "rows_sample": rows[:10],
            "llm_extracted": llm_extracted,
            "llm_raw": llm_result["content"],
            "llm_latency_s": llm_result["latency_s"],
            "llm_tokens": llm_result["usage"],
        }
        self.trace["stages"]["extraction"] = stage
        return stage

    def run_computation(self, parse_result: dict, extraction_result: dict) -> dict:
        """Stage D: Compute the answer."""
        parsed = parse_result.get("parsed", {})
        evidence = extraction_result.get("llm_extracted", {})

        compute_prompt = COMPUTE_PROMPT.format(
            question=self.question,
            parse=json.dumps(parsed, indent=2),
            evidence=json.dumps(evidence, indent=2, default=str),
        )

        compute_tool = [
            t for t in TOOL_DEFINITIONS if t["function"]["name"] == "compute_expression"
        ]
        llm_result = _chat(
            self.client,
            [{"role": "user", "content": compute_prompt}],
            tools=compute_tool,
            model=self.model,
        )

        compute_results = []
        for tc in llm_result.get("tool_calls", []):
            if tc["name"] == "compute_expression":
                cr = self.tools.compute_expression(**tc["args"])
                compute_results.append({"expression": tc["args"], "result": cr})

        llm_computed = self._extract_json(llm_result["content"])

        # Extract final answer
        final = None
        if llm_computed and llm_computed.get("formatted_answer"):
            final = str(llm_computed["formatted_answer"])
        elif compute_results:
            last = compute_results[-1].get("result", {})
            if last.get("ok"):
                final = str(last["result"])
        if not final:
            fa = extract_final_answer(llm_result["content"])
            if fa:
                final = clean_answer(fa)
            else:
                nums = re.findall(r"-?\d[\d,]*\.?\d*%?", llm_result["content"])
                if nums:
                    final = nums[-1].replace(",", "")

        is_correct = False
        match_detail = ""
        if final and self.gold:
            is_correct, match_detail = fuzzy_match_answer(self.gold, final)

        stage = {
            "llm_raw": llm_result["content"],
            "llm_computed": llm_computed,
            "compute_tool_calls": compute_results,
            "final_answer": final,
            "is_correct": is_correct,
            "match_detail": match_detail,
            "llm_latency_s": llm_result["latency_s"],
            "llm_tokens": llm_result["usage"],
        }
        self.trace["stages"]["computation"] = stage
        self.trace["final_answer"] = final
        self.trace["is_correct"] = is_correct
        return stage

    def run_full_staged(self, interactive: bool = False) -> dict:
        """Run all stages sequentially."""
        print(f"\n{'='*70}")
        print(f"  {self.uid}: {self.question[:90]}...")
        print(f"  Gold: {self.gold}")
        print(f"{'='*70}")

        # Stage A: Parse
        print("\n-- Stage A: PARSE --")
        parse = self.run_parse()
        parsed = parse.get("parsed", {})
        print(f"  Entity: {parsed.get('target_entity', '?')}")
        print(f"  Time:   {parsed.get('time_scope', '?')}")
        print(f"  Op:     {parsed.get('operation', '?')}")
        print(f"  Type:   {parsed.get('expected_answer_type', '?')}")
        print(f"  Units:  {parsed.get('unit_expectation', '?')}")
        print(f"  Tokens: {parse['tokens']}")
        if interactive:
            _pause("Parse OK?")

        # Stage B: Retrieval
        print("\n-- Stage B: RETRIEVAL --")
        retrieval = self.run_retrieval(parse)
        ev = retrieval.get("extract_values_result", {})
        print(f"  extract_values found {ev.get('count', 0)} rows")
        if ev.get("results"):
            for r in ev["results"][:3]:
                print(f"    table: {r.get('table_title', '?')[:60]}  pk={r.get('table_pk')}")
        llm_choice = retrieval.get("llm_table_choice", {})
        for ct in (llm_choice.get("chosen_tables") or []):
            print(f"  LLM chose: pk={ct.get('table_pk')} -- {ct.get('reason', '')[:60]}")
        if interactive:
            _pause("Retrieval OK?")

        # Stage C: Evidence extraction
        print("\n-- Stage C: EXTRACTION --")
        extraction = self.run_extraction(parse, retrieval)
        if extraction.get("error"):
            print(f"  ERROR: {extraction['error']}")
            self.trace["error_stage"] = "retrieval"
        else:
            print(f"  Table: {extraction.get('table_title', '?')} (pk={extraction.get('table_pk')})")
            print(f"  Units: {extraction.get('units', '?')}")
            print(f"  Rows returned: {extraction.get('rows_returned', 0)}")
            llm_ev = extraction.get("llm_extracted", {})
            for rv in (llm_ev.get("relevant_values") or [])[:5]:
                print(f"    {rv.get('label', '?')}: {rv.get('value', '?')} ({rv.get('year', '?')})")
        if interactive:
            _pause("Extraction OK?")

        # Stage D: Computation
        print("\n-- Stage D: COMPUTATION --")
        computation = self.run_computation(parse, extraction)
        print(f"  Final answer: {computation.get('final_answer', 'NONE')}")
        print(f"  Gold:         {self.gold}")
        print(f"  Correct:      {computation.get('is_correct')}")
        print(f"  Detail:       {computation.get('match_detail', '')[:80]}")
        for cc in computation.get("compute_tool_calls", []):
            print(f"  compute_expression: {cc['expression']} -> {cc['result']}")

        if not self.trace["is_correct"] and not self.trace.get("error_stage"):
            self.trace["error_stage"] = self._diagnose_error()

        # Token summary
        total_tokens = sum(
            s.get("tokens", s.get("llm_tokens", {})).get("completion_tokens", 0)
            + s.get("tokens", s.get("llm_tokens", {})).get("prompt_tokens", 0)
            for s in self.trace["stages"].values()
        )
        self.trace["total_tokens"] = total_tokens

        print(f"\n  Total tokens: {total_tokens}")
        if self.trace.get("error_stage"):
            print(f"  Error stage:  {self.trace['error_stage']}")
        print()
        return self.trace

    def _diagnose_error(self) -> str:
        """Heuristic: which stage caused failure?"""
        stages = self.trace["stages"]
        parsed = stages.get("parse", {}).get("parsed", {})
        if not parsed or not parsed.get("target_entity"):
            return "parse"
        ev = stages.get("retrieval", {}).get("extract_values_result", {})
        if not ev.get("results"):
            return "retrieval"
        extracted = stages.get("extraction", {}).get("llm_extracted", {})
        if not extracted or not extracted.get("relevant_values"):
            return "extraction"
        return "computation"

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Best-effort JSON extraction from LLM output."""
        if not text:
            return {}
        # Try ```json``` block
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # Try raw JSON
        m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return {}


# ── Full agent replay (matches Arena exactly) ───────────────────────

def run_replay(
    question: str,
    gold: str,
    tools: OfficeQATools,
    uid: str = "",
    max_iterations: int = 15,
    model: str = DEFAULT_MODEL,
    verbose: bool = True,
) -> dict:
    """Run the EXACT same agent loop as Arena. No staging — full trajectory capture."""
    tools.reset_budgets()
    t0 = time.time()
    try:
        answer, log = run_agent_loop(
            instruction=question,
            tools_obj=tools,
            model=model,
            max_iterations=max_iterations,
            verbose=verbose,
        )
    except Exception as exc:
        elapsed = time.time() - t0
        return {
            "uid": uid,
            "question": question,
            "gold_answer": gold,
            "predicted_answer": "",
            "is_correct": False,
            "match_detail": f"Agent error: {exc}",
            "failure_bucket": "timeout",
            "iterations": 0,
            "tool_calls_total": 0,
            "tool_histogram": {},
            "elapsed_s": round(elapsed, 2),
            "log": [],
        }

    elapsed = time.time() - t0

    is_correct = False
    detail = ""
    if answer and gold:
        is_correct, detail = fuzzy_match_answer(gold, answer)

    total_tool_calls = sum(len(e.get("tool_calls", [])) for e in log)

    tool_histogram: dict[str, int] = {}
    for entry in log:
        for tc in entry.get("tool_calls", []):
            name = tc.get("name", "?")
            tool_histogram[name] = tool_histogram.get(name, 0) + 1

    failure_bucket = ""
    if not is_correct:
        failure_bucket = classify_failure(answer, gold, log)

    result = {
        "uid": uid,
        "question": question,
        "gold_answer": gold,
        "predicted_answer": answer,
        "is_correct": is_correct,
        "match_detail": detail,
        "failure_bucket": failure_bucket,
        "iterations": len(log),
        "tool_calls_total": total_tool_calls,
        "tool_histogram": tool_histogram,
        "elapsed_s": round(elapsed, 2),
        "log": log,
    }

    marker = "PASS" if is_correct else "FAIL"
    print(f"  {uid}: {marker}  pred={answer}  gold={gold}  "
          f"iters={len(log)}  tools={total_tool_calls}  {elapsed:.1f}s")
    if failure_bucket:
        print(f"    bucket: {failure_bucket}")

    return result


# ── Helpers ─────────────────────────────────────────────────────────

def _pause(msg: str = "Continue?"):
    try:
        resp = input(f"  >>> {msg} [Enter to continue, q to quit] ")
        if resp.strip().lower() == "q":
            print("  Aborted.")
            sys.exit(0)
    except (EOFError, KeyboardInterrupt):
        print("\n  Aborted.")
        sys.exit(0)


def load_cases(path: str, uid_filter: str = "", difficulty_filter: str = "") -> list[dict]:
    """Load test cases from CSV, JSON, or JSONL."""
    p = Path(path)
    cases: list[dict] = []

    if p.suffix == ".csv":
        with open(p, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cases.append({
                    "uid": row.get("uid", ""),
                    "question": row.get("question", ""),
                    "expected_answer": row.get("answer", row.get("expected_answer", "")),
                    "difficulty": row.get("difficulty", ""),
                    "source_files": row.get("source_files", ""),
                })
    elif p.suffix == ".json":
        data = json.loads(p.read_text())
        if isinstance(data, list):
            cases = data
        else:
            cases = [data]
    elif p.suffix == ".jsonl":
        for line in p.read_text().strip().split("\n"):
            if line.strip():
                cases.append(json.loads(line))
    else:
        raise ValueError(f"Unknown format: {p.suffix}")

    # Normalize field names
    for c in cases:
        if "question_id" in c and "uid" not in c:
            c["uid"] = c["question_id"]
        if "expected_answer" not in c:
            c["expected_answer"] = c.get("answer", c.get("gold", ""))

    # Apply filters
    if uid_filter:
        uids = {u.strip().upper() for u in uid_filter.split(",")}
        cases = [c for c in cases if c.get("uid", "").upper() in uids]
        if not cases:
            raise ValueError(f"No cases found matching uid={uid_filter}")

    if difficulty_filter:
        cases = [c for c in cases if c.get("difficulty", "").lower() == difficulty_filter.lower()]
        if not cases:
            raise ValueError(f"No cases with difficulty={difficulty_filter}")

    return cases


def _init_tools() -> OfficeQATools:
    db_path = os.environ.get("OFFICEQA_SQLITE_DB", "")
    if not db_path:
        for cand in [
            "/app/corpus/officeqa_corpus.sqlite3",
            str(ROOT / "data" / "officeqa_corpus.sqlite3"),
            str(ROOT / "data" / "officeqa_subset.sqlite3"),
        ]:
            if Path(cand).exists():
                db_path = cand
                break
    if not db_path:
        raise RuntimeError(
            "No SQLite DB found. Set OFFICEQA_SQLITE_DB or place DB in data/\n"
            "  e.g. export OFFICEQA_SQLITE_DB=/path/to/officeqa_corpus.sqlite3"
        )
    print(f"  DB: {db_path}")
    return OfficeQATools(db_path)


def print_summary(results: list[dict], mode: str):
    """Print aggregate results."""
    total = len(results)
    correct = sum(1 for r in results if r.get("is_correct"))
    print(f"\n{'='*70}")
    print(f"  SUMMARY ({mode}): {correct}/{total} correct ({correct/total*100:.1f}%)")

    if mode == "replay":
        # Failure buckets
        buckets: dict[str, list[str]] = {}
        for r in results:
            b = r.get("failure_bucket", "")
            if b:
                buckets.setdefault(b, []).append(r.get("uid", "?"))
        if buckets:
            print(f"\n  Failure Buckets:")
            for bucket, uids in sorted(buckets.items(), key=lambda x: -len(x[1])):
                print(f"    {bucket:25s} {len(uids):3d}  {', '.join(uids[:8])}")

        # Tool usage stats
        all_histograms: dict[str, int] = {}
        for r in results:
            for tool, count in r.get("tool_histogram", {}).items():
                all_histograms[tool] = all_histograms.get(tool, 0) + count
        if all_histograms:
            print(f"\n  Tool Usage (total across all cases):")
            for tool, count in sorted(all_histograms.items(), key=lambda x: -x[1]):
                print(f"    {tool:30s} {count:5d}")

        # Timing
        times = [r.get("elapsed_s", 0) for r in results]
        if times:
            avg_time = sum(times) / len(times)
            print(f"\n  Avg time/case: {avg_time:.1f}s  Total: {sum(times):.0f}s")

    else:
        # Staged: error stage breakdown
        error_stages: dict[str, int] = {}
        for r in results:
            es = r.get("error_stage")
            if es:
                error_stages[es] = error_stages.get(es, 0) + 1
        if error_stages:
            print(f"\n  Error Stage Breakdown:")
            for stage, count in sorted(error_stages.items(), key=lambda x: -x[1]):
                print(f"    {stage:20s} {count:3d}")

    # Difficulty breakdown
    by_diff: dict[str, dict[str, int]] = {}
    for r in results:
        d = r.get("difficulty", "?") or "?"
        if d not in by_diff:
            by_diff[d] = {"total": 0, "correct": 0}
        by_diff[d]["total"] += 1
        if r.get("is_correct"):
            by_diff[d]["correct"] += 1
    if len(by_diff) > 1:
        print(f"\n  By Difficulty:")
        for d, counts in sorted(by_diff.items()):
            pct = counts["correct"] / counts["total"] * 100 if counts["total"] else 0
            print(f"    {d:10s} {counts['correct']}/{counts['total']} ({pct:.0f}%)")

    print(f"{'='*70}\n")


# ── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="MiniMax M2.5 trace debugger for OfficeQA Arena",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cases", type=str, help="Path to test cases (CSV/JSON/JSONL)")
    parser.add_argument("--uid", type=str, default="", help="Filter to UID(s), comma-separated")
    parser.add_argument("--difficulty", type=str, default="", help="Filter by difficulty (easy/hard)")
    parser.add_argument("--question", type=str, default="", help="Inline question")
    parser.add_argument("--gold", type=str, default="", help="Gold answer for inline question")
    parser.add_argument("--batch", action="store_true", help="Batch mode (no pausing)")
    parser.add_argument("--replay", action="store_true", help="Full agent replay (matches Arena)")
    parser.add_argument("--output", type=str, default="", help="Output JSONL path")
    parser.add_argument("--max-iterations", type=int, default=15, help="Max iterations for replay")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model ID")
    parser.add_argument("--verbose", action="store_true", help="Verbose tool call logging")
    parser.add_argument("--limit", type=int, default=0, help="Max cases to process (0=all)")
    args = parser.parse_args()

    client = _get_client()
    tools = _init_tools()

    # Build case list
    if args.question:
        cases = [{"uid": "INLINE", "question": args.question, "expected_answer": args.gold}]
    elif args.cases:
        cases = load_cases(args.cases, uid_filter=args.uid, difficulty_filter=args.difficulty)
    else:
        parser.error("Provide --cases or --question")

    if args.limit > 0:
        cases = cases[:args.limit]

    interactive = not args.batch and not args.replay
    mode = "replay" if args.replay else ("batch" if args.batch else "interactive")

    print(f"\n  Mode: {mode}")
    print(f"  Model: {args.model}")
    print(f"  Cases: {len(cases)}")
    if args.difficulty:
        print(f"  Difficulty filter: {args.difficulty}")
    print()

    results = []
    for i, case in enumerate(cases):
        uid = case.get("uid", "?")
        question = case["question"]
        gold = case.get("expected_answer", "")

        if args.replay:
            result = run_replay(
                question, gold, tools, uid=uid,
                max_iterations=args.max_iterations,
                model=args.model,
                verbose=args.verbose or interactive,
            )
            # Carry over difficulty for summary
            result["difficulty"] = case.get("difficulty", "")
        else:
            run = TracedRun(uid, question, gold, tools, client, model=args.model)
            result = run.run_full_staged(interactive=interactive)
            result["difficulty"] = case.get("difficulty", "")

        results.append(result)

        # Append to output incrementally (crash-safe)
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "a") as f:
                f.write(json.dumps(result, default=str) + "\n")

    # Summary
    if len(results) > 0:
        print_summary(results, mode)

    if args.output:
        print(f"  Results written to {args.output}")


if __name__ == "__main__":
    main()
