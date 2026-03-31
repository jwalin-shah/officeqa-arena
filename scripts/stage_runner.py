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
import concurrent.futures
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


# ── Stage: PARSE V2 (typed ParseSpec) ──────────────────────────────

PARSE_V2_PROMPT = """You are a Treasury bulletin QA analyst. Given a question, produce a detailed structured parse that will drive an automated retrieval and computation pipeline.

Return ONLY valid JSON with these exact fields:

{{
  "target_entity": "the primary entity/metric being asked about",
  "primary_series": [
    {{"metric": "exact name of metric/series", "entity_filter": "any sub-filter (e.g. specific department, country, category)", "granularity": "annual|monthly|weekly|daily|quarterly"}}
  ],
  "comparison_series": [
    {{"metric": "second metric if comparison needed", "entity_filter": "", "granularity": "annual|monthly|weekly|daily|quarterly"}}
  ],
  "time_constraints": [
    {{"start": "earliest date/year needed", "end": "latest date/year needed", "granularity": "year|month|week|day|quarter", "note": "any special time instruction"}}
  ],
  "date_resolution_kind": "direct|relative|event_anchor|historical_anchor|document_anchor|cross_calendar",
  "calendar_basis": "calendar|fiscal|mixed|unknown",
  "retrieval_ops": ["lookup", "filter", "join", "page_locate", "chart_read", "series_extract"],
  "compute_ops": ["sum", "difference", "percent_change", "CAGR", "OLS", "geometric_mean", "weighted_average", "VaR", "ES", "std_dev", "CV", "Theil", "Zipf", "Box_Cox", "HP_filter", "kurtosis", "skewness", "exponential_smoothing", "Winsorized_range", "KL_divergence", "Pareto_Hill", "interpolate", "none"],
  "output_format": {{
    "type": "number|percent|list|text|date",
    "unit": "millions|billions|nominal_dollars|thousands|percent|yen|ratio|fine_pounds|other",
    "rounding": "nearest whole|tenths|hundredths|thousandths|4dp|5dp|6dp|none",
    "list_format": "comma_separated_brackets|single_value|none"
  }},
  "external_sources": ["none", "BLS_CPI", "FRED", "Macrotrends", "WorldBank", "IMF", "exchange_rate_USD_JPY", "exchange_rate_USD_GBP", "exchange_rate_USD_DEM", "exchange_rate_other", "event_date_lookup"],
  "visual_required": {{
    "needed": false,
    "subtype": "none|chart_read|page_number|table_image|count_marks|layout_navigation"
  }},
  "world_knowledge_anchor": {{
    "needed": false,
    "phrase": "",
    "expected_resolution": ""
  }},
  "document_anchor": {{
    "needed": false,
    "bulletin_date": "",
    "specific_table": "",
    "specific_page": ""
  }},
  "num_hops": 1,
  "num_tables_needed": 1,
  "confidence": 0.9,
  "notes": []
}}

IMPORTANT RULES:
- "retrieval_ops" should list ONLY the retrieval steps needed (e.g. ["lookup"] for a single value, ["series_extract", "filter"] for time series with conditions)
- "compute_ops" should list ONLY the computation steps needed IN ORDER (e.g. ["sum", "percent_change"] means sum first, then percent change). Use ["none"] for simple lookups.
- "external_sources" must be ["none"] unless the question explicitly requires data from outside the Treasury bulletin corpus (CPI adjustments, exchange rates from Macrotrends, FRED data, etc.)
- "world_knowledge_anchor.needed" is true ONLY when the question references a real-world event to determine a date (e.g. "year of Black Monday", "when Germany invaded Poland", "year Amazon stock was lowest")
- "visual_required.needed" is true ONLY when the question asks about charts, figures, plots, page layouts, or counting visual elements
- "document_anchor.needed" is true when the question specifies a particular bulletin issue or page number
- "date_resolution_kind" must be one of: "direct" (explicit year/date), "relative" (last day of, end of quarter), "event_anchor" (WHO pandemic, Black Monday), "historical_anchor" (year X happened), "document_anchor" (June 1970 bulletin), "cross_calendar" (calendar months in fiscal year context)
- "num_tables_needed" must be an integer: 1, 2, or 3
- "confidence" is your confidence (0.0-1.0) that this parse is complete and correct

Question: {question}"""


def _route_question(parsed: dict) -> str:
    """Deterministic router: returns lane based on ParseSpec fields."""
    # Visual lane
    vis = parsed.get("visual_required", {})
    if isinstance(vis, dict) and vis.get("needed"):
        return "visual"

    # External data lane (CPI, FX, FRED, etc. — not just event dates)
    ext = parsed.get("external_sources", ["none"])
    has_external_data = any(
        s not in ("none", "event_date_lookup") for s in ext
    )

    # World knowledge / event anchor lane
    wk = parsed.get("world_knowledge_anchor", {})
    has_event_date = (isinstance(wk, dict) and wk.get("needed")) or "event_date_lookup" in ext
    date_kind = parsed.get("date_resolution_kind", "direct")
    has_indirect_date = date_kind in ("event_anchor", "historical_anchor")

    # Hybrid: Treasury data + external source
    if has_external_data:
        return "hybrid"

    # External date resolution needed before Treasury lookup
    if has_event_date or has_indirect_date:
        return "external_date"

    # Default: pure table/text retrieval
    return "table"


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


def _parse_one_v2(case: dict, model: str) -> dict:
    """Parse a single question with V2 schema. Thread-safe (creates own client)."""
    client = _get_client()
    uid = case["uid"]
    question = case["question"]
    gold = case["gold"]

    prompt = PARSE_V2_PROMPT.format(question=question)
    t0 = time.time()
    try:
        result = _chat(client, [{"role": "user", "content": prompt}], model=model)
        parsed = _extract_json(result["content"])
    except Exception as exc:
        parsed = {}
        result = {"content": "", "latency_s": time.time() - t0, "tokens": {}, "error": str(exc)}

    lane = _route_question(parsed) if parsed else "unknown"

    return {
        "uid": uid,
        "question": question,
        "gold": gold,
        "difficulty": case.get("difficulty", ""),
        "parsed": parsed,
        "lane": lane,
        "raw_response": result["content"][:800],
        "latency_s": result["latency_s"],
        "tokens": result.get("tokens", {}),
    }


def run_parse_v2(cases: list[dict], output: Path, model: str, workers: int = 1):
    """Parse with the new typed ParseSpec schema + router. Supports parallel workers."""
    print(f"\n  STAGE: PARSE_V2 — {len(cases)} questions, {workers} workers")
    print(f"  Output: {output}\n")

    lane_counts: dict[str, int] = {}
    completed = 0

    with open(output, "w") as f:
        if workers <= 1:
            # Sequential
            for i, case in enumerate(cases):
                row = _parse_one_v2(case, model)
                _write_result(f, row)
                lane = row["lane"]
                lane_counts[lane] = lane_counts.get(lane, 0) + 1
                completed += 1
                parsed = row["parsed"]
                entity = parsed.get("target_entity", "?")[:40] if parsed else "?"
                ops = parsed.get("compute_ops", ["?"]) if parsed else ["?"]
                ok = "OK" if parsed and parsed.get("target_entity") else "EMPTY"
                print(
                    f"  [{completed}/{len(cases)}] {row['uid']} [{ok}] [{lane:13s}] "
                    f"entity={entity} ops={ops[:3]}"
                )
        else:
            # Parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_parse_one_v2, case, model): case["uid"]
                    for case in cases
                }
                for future in concurrent.futures.as_completed(futures):
                    uid = futures[future]
                    try:
                        row = future.result()
                    except Exception as exc:
                        row = {
                            "uid": uid, "question": "", "gold": "", "difficulty": "",
                            "parsed": {}, "lane": "error",
                            "raw_response": str(exc)[:800],
                            "latency_s": 0, "tokens": {},
                        }
                    _write_result(f, row)
                    lane = row["lane"]
                    lane_counts[lane] = lane_counts.get(lane, 0) + 1
                    completed += 1
                    parsed = row.get("parsed", {})
                    entity = parsed.get("target_entity", "?")[:40] if parsed else "?"
                    ok = "OK" if parsed and parsed.get("target_entity") else "EMPTY"
                    print(f"  [{completed}/{len(cases)}] {row['uid']} [{ok}] [{lane:13s}] entity={entity}")

    # Summary
    results = list(load_stage_output(str(output)).values())
    has_parse = sum(1 for r in results if r.get("parsed", {}).get("target_entity"))
    print(f"\n  Parse V2 complete: {has_parse}/{len(results)} have target_entity")
    print(f"  Lane distribution: {json.dumps(lane_counts, indent=2)}")
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


# ── Stage: RETRIEVAL V2 (routed) ──────────────────────────────────

def _extract_years_from_parse(parsed: dict) -> list[int]:
    """Extract all years from ParseSpec time_constraints."""
    years = []
    for tc in parsed.get("time_constraints", []):
        for field in ("start", "end"):
            val = str(tc.get(field, ""))
            for m in re.finditer(r"\b(1[89]\d{2}|20[0-2]\d)\b", val):
                y = int(m.group(1))
                if y not in years:
                    years.append(y)
    # Fallback: scan target_entity and notes
    if not years:
        for text in [parsed.get("target_entity", ""), *parsed.get("notes", [])]:
            for m in re.finditer(r"\b(1[89]\d{2}|20[0-2]\d)\b", str(text)):
                y = int(m.group(1))
                if y not in years:
                    years.append(y)
    return sorted(years)


def _retrieve_table_lane(tools: OfficeQATools, parsed: dict, question: str) -> dict:
    """Retrieval for table lane: use ParseSpec primary_series + time_constraints."""
    # Build query from primary_series if available, else target_entity
    series = parsed.get("primary_series", [])
    if series and isinstance(series[0], dict):
        metric = series[0].get("metric", "")
        entity_filter = series[0].get("entity_filter", "")
        query = f"{metric} {entity_filter}".strip() or parsed.get("target_entity", question[:100])
    else:
        query = parsed.get("target_entity", question[:100])

    years = _extract_years_from_parse(parsed)
    year = years[0] if years else None

    # extract_values with better query
    t0 = time.time()
    ev_result = tools.extract_values(query=query, year=year)
    ev_latency = time.time() - t0

    # If no results and we have multiple years, try year range
    if ev_result.get("count", 0) == 0 and len(years) >= 2:
        tools.reset_budgets()
        ev_result = tools.extract_values(query=query, year=years[0])
        ev_latency = time.time() - t0

    # Search candidates as backup
    tools.reset_budgets()
    search_result = tools.search_tables(
        query=query, year_range=[years[0], years[-1]] if years else None
    )
    tools.reset_budgets()

    return {
        "extract_values_result": ev_result,
        "extract_values_count": ev_result.get("count", 0),
        "search_candidates": search_result.get("candidates", [])[:5],
        "ev_latency_s": round(ev_latency, 3),
        "query_used": query,
        "years_used": years,
    }


def _retrieve_external_date_lane(
    tools: OfficeQATools, parsed: dict, question: str
) -> dict:
    """Retrieval for external_date lane: resolve dates first, then Treasury lookup."""
    from server.date_resolver import resolve_from_parse

    resolved = resolve_from_parse(parsed)
    resolved_year = resolved.get("resolved_year") if resolved else None

    # Use resolved year for Treasury lookup
    query = parsed.get("target_entity", question[:100])
    years = _extract_years_from_parse(parsed)

    # Inject resolved year if we got one
    if resolved_year and resolved_year not in years:
        years.append(resolved_year)
        years.sort()

    year = resolved_year or (years[0] if years else None)

    t0 = time.time()
    ev_result = tools.extract_values(query=query, year=year)
    ev_latency = time.time() - t0

    tools.reset_budgets()
    search_result = tools.search_tables(
        query=query, year_range=[year, year] if year else None
    )
    tools.reset_budgets()

    return {
        "extract_values_result": ev_result,
        "extract_values_count": ev_result.get("count", 0),
        "search_candidates": search_result.get("candidates", [])[:5],
        "ev_latency_s": round(ev_latency, 3),
        "date_resolved": resolved,
        "query_used": query,
        "years_used": years,
    }


def _retrieve_hybrid_lane(
    tools: OfficeQATools, parsed: dict, question: str
) -> dict:
    """Retrieval for hybrid lane: Treasury data + external reference data."""
    # Treasury part (same as table lane)
    table_result = _retrieve_table_lane(tools, parsed, question)

    # External data part — gather what's needed
    external_sources = parsed.get("external_sources", ["none"])
    external_data: dict = {}

    for src in external_sources:
        if src == "none":
            continue
        elif src == "BLS_CPI":
            # Get CPI for all years in scope
            years = _extract_years_from_parse(parsed)
            for y in years:
                cpi = tools.get_cpi_index(year=y)
                external_data[f"cpi_{y}"] = cpi
        elif src.startswith("exchange_rate_"):
            # Parse currency pair from source name
            pair = src.replace("exchange_rate_", "")  # e.g. "USD_JPY"
            years = _extract_years_from_parse(parsed)
            for y in years:
                fx = tools.get_exchange_rate(pair=pair, year=y)
                external_data[f"fx_{pair}_{y}"] = fx
        elif src == "FRED":
            # FRED data would need web_lookup — flag for agent
            external_data["fred_needed"] = True

    return {
        **table_result,
        "external_data": external_data,
        "external_sources_requested": external_sources,
    }


def _retrieve_visual_lane(parsed: dict, question: str) -> dict:
    """Retrieval for visual lane: skip DB retrieval, flag for visual processing."""
    vis = parsed.get("visual_required", {})
    doc = parsed.get("document_anchor", {})

    return {
        "extract_values_result": {},
        "extract_values_count": 0,
        "search_candidates": [],
        "ev_latency_s": 0,
        "visual_task": {
            "subtype": vis.get("subtype", "unknown") if isinstance(vis, dict) else "unknown",
            "bulletin_date": doc.get("bulletin_date", "") if isinstance(doc, dict) else "",
            "specific_page": doc.get("specific_page", "") if isinstance(doc, dict) else "",
        },
        "note": "Visual lane — requires chart/page rendering, not DB retrieval",
    }


def run_retrieval_v2(parse_input: str, output: Path, model: str):
    """Routed retrieval: uses ParseSpec V2 lane to choose retrieval strategy."""
    tools = _init_tools()
    parses = load_stage_output(parse_input)
    cases = list(parses.values())
    print(f"\n  STAGE: RETRIEVAL_V2 — {len(cases)} questions")
    print(f"  Parse input: {parse_input}")
    print(f"  Output: {output}\n")

    lane_counts: dict[str, int] = {}

    with open(output, "w") as f:
        for i, case in enumerate(cases):
            uid = case["uid"]
            question = case["question"]
            gold = case["gold"]
            parsed = case.get("parsed", {})
            lane = case.get("lane", _route_question(parsed) if parsed else "unknown")

            tools.reset_budgets()
            lane_counts[lane] = lane_counts.get(lane, 0) + 1

            # Route to appropriate retrieval strategy
            if lane == "visual":
                retrieval = _retrieve_visual_lane(parsed, question)
            elif lane == "external_date":
                retrieval = _retrieve_external_date_lane(tools, parsed, question)
            elif lane == "hybrid":
                retrieval = _retrieve_hybrid_lane(tools, parsed, question)
            else:  # table or unknown
                retrieval = _retrieve_table_lane(tools, parsed, question)

            # Build top_tables from extract_values result
            top_tables = []
            ev_result = retrieval.get("extract_values_result", {})
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
                "lane": lane,
                "extract_values_count": retrieval.get("extract_values_count", 0),
                "extract_values_result": ev_result,
                "top_tables": top_tables,
                "search_candidates": retrieval.get("search_candidates", []),
                "ev_latency_s": retrieval.get("ev_latency_s", 0),
                # Lane-specific extras
                "date_resolved": retrieval.get("date_resolved"),
                "external_data": retrieval.get("external_data"),
                "visual_task": retrieval.get("visual_task"),
            }
            _write_result(f, row)

            ev_count = retrieval.get("extract_values_count", 0)
            top_title = top_tables[0]["table_title"][:40] if top_tables else "NONE"
            print(f"  [{i+1}/{len(cases)}] {uid} [{lane:13s}] ev={ev_count} table={top_title}")

    # Summary
    results = list(load_stage_output(str(output)).values())
    has_results = sum(1 for r in results if r.get("extract_values_count", 0) > 0)
    print(f"\n  Retrieval V2 complete: {has_results}/{len(results)} found rows")
    print(f"  Lane distribution: {json.dumps(lane_counts, indent=2)}")


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
                units = profile.get("units", "") or profile.get("units_line", "") or ""

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
    parser.add_argument("stage", choices=["parse", "parse_v2", "retrieval", "retrieval_v2", "extraction", "computation", "replay"],
                        help="Which stage to run")
    parser.add_argument("--cases", type=str, help="Input cases (CSV/JSON/JSONL)")
    parser.add_argument("--subset", type=str, default="", help="'arena' for 20 sample tasks, or comma-separated UIDs")
    parser.add_argument("--difficulty", type=str, default="", help="Filter: easy or hard")
    parser.add_argument("--limit", type=int, default=0, help="Max cases (0=all)")
    parser.add_argument("--output", type=str, default="", help="Output JSONL (default: results/stages/<stage>.jsonl)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--max-iterations", type=int, default=15, help="For replay mode")
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers for parse_v2 (default: 1)")

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

    elif args.stage == "parse_v2":
        if not args.cases:
            parser.error("parse_v2 requires --cases")
        cases = load_cases(args.cases, subset=subset, uid_filter=uid_filter,
                           difficulty=args.difficulty, limit=args.limit)
        run_parse_v2(cases, output, args.model, workers=args.workers)

    elif args.stage == "retrieval":
        parse_input = args.parse_input or str(STAGES_DIR / "parse.jsonl")
        if not Path(parse_input).exists():
            parser.error(f"Parse output not found: {parse_input}. Run parse stage first.")
        run_retrieval(parse_input, output, args.model)

    elif args.stage == "retrieval_v2":
        parse_input = args.parse_input or str(STAGES_DIR / "parse_v2_all.jsonl")
        if not Path(parse_input).exists():
            parser.error(f"Parse V2 output not found: {parse_input}. Run parse_v2 stage first.")
        run_retrieval_v2(parse_input, output, args.model)

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
