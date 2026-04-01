#!/usr/bin/env python3
"""Orchestrator: chains sub-agent phases with validation between each step.

Replaces the flat single-agent loop (run_agent.py) with staged execution:
  Phase 1: Planner   — analyze question, output structured plan (1 iter, no tools)
  Phase 2: Researcher — execute searches per the plan (8 iter, MCP search tools)
  Phase 3: Calculator — compute the answer from retrieved data (3 iter, MCP compute tools)
  Phase 4: Submit     — format and write answer via terminal

Each phase is a separate OpenHands SDK Conversation with:
  - Its own system prompt (replaces the 12K OpenHands default)
  - Its own max_iterations budget
  - Full MCP tool access (tool restriction via prompt, not code)

Usage (inside Daytona sandbox or arena):
  python3 src/orchestrator.py --instruction "What was..." --logs-dir /tmp/logs \
      --trajectory-path /tmp/logs/trajectory.json

Env vars (same as run_agent.py):
  LLM_MODEL, LLM_API_KEY, LLM_BASE_URL, LLM_TEMPERATURE,
  MCP_SERVERS_JSON, OFFICEQA_SQLITE_DB, SKILL_PATHS, MAX_ITERATIONS
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from openhands.sdk import (
    LLM,
    Agent,
    AgentContext,
    Conversation,
    Tool,
    get_logger,
)
from openhands.sdk.event import (
    ActionEvent,
    MessageEvent,
    ObservationEvent,
)
from openhands.tools.terminal import TerminalTool

logger = get_logger(__name__)


# ── Helpers ────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    """Try to extract a JSON object from text."""
    text = text.strip()
    # Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Inside markdown code block
    m = re.search(r'```(?:json)?\s*\n?(\{.*?\})\s*\n?```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    # First balanced { ... }
    start = text.find('{')
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break
    return None


def _collect_output(conversation: Conversation) -> tuple[str, list[dict], int]:
    """Collect text output and structured events from a completed conversation."""
    output_parts: list[str] = []
    events: list[dict] = []
    iterations = 0

    for event in conversation.state.events:
        if isinstance(event, MessageEvent):
            if event.source == "agent":
                iterations += 1
                content = ""
                if event.llm_message:
                    msg = getattr(event.llm_message, "content", None)
                    if isinstance(msg, list):
                        content = "\n".join(
                            getattr(c, "text", str(c)) for c in msg
                            if getattr(c, "text", None)
                        )
                    elif msg:
                        content = str(msg)
                output_parts.append(content)
                events.append({"type": "message", "source": "agent", "content": content})

        elif isinstance(event, ActionEvent):
            args = {}
            if event.tool_call and hasattr(event.tool_call, "function"):
                raw = getattr(event.tool_call.function, "arguments", None)
                if isinstance(raw, str):
                    try:
                        args = json.loads(raw)
                    except json.JSONDecodeError:
                        args = {"raw": raw}
                elif isinstance(raw, dict):
                    args = raw

            # Capture thought/text that accompanies tool calls
            thought_text = ""
            thought_list = getattr(event, "thought", [])
            if thought_list:
                for t in thought_list:
                    txt = getattr(t, "text", None) or str(t)
                    if txt:
                        thought_text += txt + "\n"
            if thought_text.strip():
                output_parts.append(thought_text.strip())

            events.append({
                "type": "tool_call",
                "tool": event.tool_name,
                "args": args,
                "id": event.tool_call_id,
                "thought": thought_text.strip()[:500] if thought_text.strip() else "",
            })

        elif isinstance(event, ObservationEvent):
            obs = ""
            if event.observation:
                raw = getattr(event.observation, "content", None)
                if isinstance(raw, list):
                    obs = "\n".join(
                        getattr(c, "text", str(c)) for c in raw
                        if getattr(c, "text", None)
                    )
                elif raw:
                    obs = str(raw)
            events.append({
                "type": "tool_result",
                "id": event.tool_call_id,
                "content": obs[:4000],
            })

    return "\n".join(output_parts), events, iterations


def _build_mcp_config() -> dict | None:
    """Build MCP config from environment (same as run_agent.py)."""
    raw = os.environ.get("MCP_SERVERS_JSON")
    if not raw:
        return None
    servers = json.loads(raw)
    config: dict[str, Any] = {"mcpServers": {}}
    for s in servers:
        name = s.get("name", "mcp-server")
        cfg: dict[str, Any] = {}
        if s.get("command"):
            cfg["command"] = s["command"]
        if s.get("args"):
            cfg["args"] = s["args"]
        elif s.get("url"):
            cfg["url"] = s["url"]
        config["mcpServers"][name] = cfg
    return config


def _build_llm() -> LLM:
    """Build LLM from environment (same as run_agent.py)."""
    model = os.environ.get("LLM_MODEL", "openrouter/minimax/minimax-m2.5")
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    if not api_key:
        print("Error: LLM_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    kwargs: dict[str, Any] = {"model": model, "api_key": api_key, "base_url": base_url}
    temp = os.environ.get("LLM_TEMPERATURE")
    if temp:
        kwargs["temperature"] = float(temp)
    return LLM(**kwargs)


# ── Phase runner ───────────────────────────────────────────────────

def run_phase(
    llm: LLM,
    system_prompt_path: str,
    instruction: str,
    phase_name: str,
    max_iterations: int = 1,
    mcp_config: dict | None = None,
    include_terminal: bool = False,
    workspace: str = "/opt/officeqa",
    template_kwargs: dict | None = None,
) -> dict:
    """Run one orchestration phase as its own Conversation.

    Args:
        system_prompt_path: Absolute path to .j2 system prompt template.
        instruction: The text to inject as {{ instruction }} in the template.
        max_iterations: Max agent iterations for this phase.
        mcp_config: MCP server config (for tool-using phases).
        include_terminal: Whether to include TerminalTool (for writing answer.txt).
        template_kwargs: Extra kwargs for the jinja2 template (e.g. max_calls).
    """
    t0 = time.time()

    # Build tools list
    tools = []
    if include_terminal:
        tools.append(Tool(name=TerminalTool.name))

    # Build agent with custom system prompt (replaces OpenHands default)
    agent_kwargs: dict[str, Any] = {
        "llm": llm,
        "tools": tools,
        "agent_context": AgentContext(skills=[]),
        "system_prompt_filename": system_prompt_path,
    }
    if template_kwargs:
        agent_kwargs["system_prompt_kwargs"] = template_kwargs
    if mcp_config:
        agent_kwargs["mcp_config"] = mcp_config

    agent = Agent(**agent_kwargs)

    conversation = Conversation(
        agent=agent,
        workspace=workspace,
        max_iteration_per_run=max_iterations,
    )

    logger.info(f"[{phase_name}] Starting (max_iter={max_iterations})")
    conversation.send_message(instruction)
    conversation.run()

    raw_output, events, iterations = _collect_output(conversation)
    cost = llm.metrics.accumulated_cost
    elapsed = round(time.time() - t0, 2)

    logger.info(f"[{phase_name}] Done: {iterations} iter, ${cost:.4f}, {elapsed}s")

    return {
        "phase": phase_name,
        "raw_output": raw_output,
        "events": events,
        "iterations": iterations,
        "cost_usd": cost,
        "elapsed_s": elapsed,
    }


# ── Plan Validator ─────────────────────────────────────────────────

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
    """Validate planner output and return fixes/warnings.

    Returns dict with:
      - valid: bool
      - warnings: list of strings
      - fixes: dict of fields that were auto-corrected
      - plan: the (possibly corrected) plan
    """
    warnings: list[str] = []
    fixes: dict[str, Any] = {}
    q_lower = question.lower()

    # 1. Required fields
    for field in ("data_needs", "search_queries", "computation", "answer_format"):
        if field not in plan:
            warnings.append(f"Missing required field: {field}")

    # 2. Validate data_needs
    for i, dn in enumerate(plan.get("data_needs", [])):
        # Year sanity
        for yr in dn.get("years", []):
            if isinstance(yr, (int, float)) and not (1900 <= yr <= 2030):
                warnings.append(f"data_needs[{i}]: suspicious year {yr}")

        # Table family
        family = dn.get("table_family", "unknown")
        if family and family not in VALID_FAMILIES:
            warnings.append(f"data_needs[{i}]: unknown table_family '{family}'")
            dn["table_family"] = "unknown"
            fixes[f"data_needs[{i}].table_family"] = "unknown"

        # Period basis vs question
        pb = dn.get("period_basis", "")
        if pb == "fiscal" and ("calendar year" in q_lower or "calendar month" in q_lower):
            warnings.append(f"data_needs[{i}]: plan says fiscal but question says calendar")
        if pb == "calendar" and "fiscal year" in q_lower and "calendar" not in q_lower:
            warnings.append(f"data_needs[{i}]: plan says calendar but question says fiscal")

    # 3. Validate search queries
    for i, sq in enumerate(plan.get("search_queries", [])):
        tool = sq.get("tool", "")
        if tool and tool not in VALID_TOOLS:
            # Try stripping MCP prefix
            clean = tool.split("_", 2)[-1] if "officeqa" in tool else tool
            if clean in VALID_TOOLS:
                sq["tool"] = clean
                fixes[f"search_queries[{i}].tool"] = clean
            else:
                warnings.append(f"search_queries[{i}]: unknown tool '{tool}'")

    # 4. Validate computation
    comp = plan.get("computation", {})
    for func in comp.get("functions_needed", []):
        if func not in VALID_COMPUTE_FUNCS:
            warnings.append(f"computation: unknown function '{func}' — may need to be added to safe_eval")

    # 5. Check if search queries exist for all data needs
    data_needs = plan.get("data_needs", [])
    queries = plan.get("search_queries", [])
    if data_needs and not queries:
        warnings.append("No search_queries provided for data_needs — will use defaults")
        # Auto-generate default queries from data_needs
        default_queries = []
        for dn in data_needs:
            metric = dn.get("metric", "")
            years = dn.get("years", [])
            family = dn.get("table_family", "")
            if metric:
                q: dict[str, Any] = {"tool": "search_canonical", "args": {"query": metric}}
                if years and len(years) == 1:
                    q["args"]["year"] = years[0]
                elif years:
                    q["args"]["years"] = years
                if family and family != "unknown":
                    q["args"]["table_family"] = family
                default_queries.append(q)
        if default_queries:
            plan["search_queries"] = default_queries
            fixes["search_queries"] = "auto-generated from data_needs"

    # 6. Budget sanity
    est_calls = plan.get("estimated_tool_calls", 0)
    if est_calls > 15:
        warnings.append(f"Estimated {est_calls} tool calls exceeds budget of 15")

    valid = len([w for w in warnings if "Missing required" in w or "unknown tool" in w]) == 0

    return {
        "valid": valid,
        "warnings": warnings,
        "fixes": fixes,
        "plan": plan,
    }


# ── Deterministic Compute ──────────────────────────────────────────

def _parse_researcher_values(data_text: str) -> list[tuple[float, int, float]]:
    """Parse DATA_FOUND entries from researcher output.

    Returns list of (value, year, unit_multiplier) tuples, in order found.
    """
    entries: list[tuple[float, int, float]] = []

    # Focus on DATA_FOUND section if present
    sec = re.search(r'DATA_FOUND:(.*?)(?=\n\nRAW TOOL|\Z)', data_text, re.DOTALL | re.IGNORECASE)
    search_text = sec.group(1) if sec else data_text

    # Split on bullet entries (lines starting with "- metric:")
    blocks = re.split(r'\n\s*-\s+metric:', '\n' + search_text)
    for block in blocks[1:]:
        value_m = re.search(r'\bvalue:\s*([-\d,.]+(?:[eE][+-]?\d+)?)', block)
        year_m  = re.search(r'\byear:\s*(\d{4})', block)
        mult_m  = re.search(r'\bunit_multiplier:\s*([\d.eE+\-]+)', block)
        if not value_m:
            continue
        try:
            v    = float(value_m.group(1).replace(',', ''))
            yr   = int(year_m.group(1))   if year_m  else 0
            mult = float(mult_m.group(1)) if mult_m  else 1.0
            entries.append((v, yr, mult))
        except (ValueError, TypeError):
            pass

    # Fallback: scrape "value_scaled": N or "value": N from raw JSON tool results
    if not entries:
        for m in re.finditer(r'"value(?:_scaled)?"\s*:\s*([-\d.eE+]+)', data_text):
            try:
                entries.append((float(m.group(1)), 0, 1.0))
            except ValueError:
                pass

    return entries


# Canonical mapping: planner function name → safe_eval function name
# "multi-value" means pass the whole list; "two-value" means first two entries
_FUNC_ALIASES: dict[str, str] = {
    "arithmetic_mean": "mean", "average": "mean", "avg": "mean",
    "geometric_mean": "geometric_mean",
    "median": "median",
    "stdev": "stdev", "standard_deviation": "stdev",
    "sample_standard_deviation": "stdev",
    "population_stddev": "stdev",   # best approximation in safe_eval
    "variance": "variance",
    "cv": "cv", "coefficient_of_variation": "cv",
    "theil_index": "theil_index",
    "mad": "mad",
    "sum": "sum",
    "prod": "prod",
    "percentile": "percentile",
    "cagr": "cagr",
    "linreg": "linreg", "ols_linear_regression": "linreg",
    "linear_regression": "linreg",
    "correlation": "correlation", "pearson_correlation": "correlation",
}
_MULTI_VALUE_FUNCS = {
    "mean", "geometric_mean", "median", "stdev", "variance",
    "cv", "theil_index", "mad", "sum", "prod",
}


def _deterministic_compute(data_text: str, plan: dict, question: str) -> str:
    """Compute answer directly from structured researcher output — no LLM needed.

    Returns the answer string, or '' if deterministic compute isn't possible.
    """
    # Import safe_eval from the project root (works both locally and in sandbox)
    _root = str(Path(__file__).resolve().parents[1])
    if _root not in sys.path:
        sys.path.insert(0, _root)
    try:
        from server.safe_eval import safe_eval_finance  # type: ignore
    except ImportError:
        return ""

    entries = _parse_researcher_values(data_text)
    if not entries:
        return ""

    values  = [e[0] for e in entries]
    years   = [e[1] for e in entries]

    comp  = plan.get("computation", {})
    funcs = comp.get("functions_needed", [])
    comp_type = comp.get("type", "").lower().replace(" ", "_")

    # Resolve function name
    raw_func = (funcs[0].lower() if funcs else comp_type).replace(" ", "_")
    func = _FUNC_ALIASES.get(raw_func, raw_func)

    try:
        # ── Multi-value aggregates ──────────────────────────────────
        if func in _MULTI_VALUE_FUNCS:
            result = safe_eval_finance(f"{func}({values!r})", {})
            return str(result)

        # ── CAGR: first value=start, last=end, n=count-1 ───────────
        if func == "cagr" and len(values) >= 2:
            n = len(values) - 1
            result = safe_eval_finance(f"cagr({values[0]}, {values[-1]}, {n})", {})
            return str(result)

        # ── Linear regression: x=years, y=values ───────────────────
        if func == "linreg" and len(values) >= 2:
            xs = years if all(y > 0 for y in years) else list(range(len(values)))
            result = safe_eval_finance(f"linreg({xs!r}, {values!r})", {})
            slope = result[0] if isinstance(result, list) else result
            return str(slope)

        # ── Correlation: split values in half as two series ─────────
        if func == "correlation" and len(values) >= 4:
            mid = len(values) // 2
            result = safe_eval_finance(
                f"correlation({values[:mid]!r}, {values[mid:]!r})", {}
            )
            return str(result)

        # ── Two-value arithmetic ────────────────────────────────────
        if len(values) >= 2:
            v1, v2 = values[0], values[1]
            if func in ("difference", "subtraction", "absolute_difference",
                        "arithmetic_difference"):
                diff = v1 - v2
                return str(abs(diff) if "absolute" in func else diff)
            if func in ("percent_change", "percentage_change", "pct_change",
                        "yoy_growth_rate", "growth_rate"):
                if v1 == 0:
                    return ""
                return str(round((v2 - v1) / v1 * 100, 6))
            if func in ("ratio", "division", "ratio_calculation"):
                if v2 == 0:
                    return ""
                return str(round(v1 / v2, 6))

        # ── Single-value lookup ─────────────────────────────────────
        if func in ("lookup", "simple_lookup", "single_value",
                    "point_in_time_value", "extraction") and len(values) >= 1:
            return str(values[0])

    except Exception:
        pass

    return ""


# ── Orchestrator ───────────────────────────────────────────────────

def orchestrate(question: str, workspace: str = "/opt/officeqa") -> dict:
    """Run the full orchestrated pipeline: Plan → Research → Compute."""
    llm = _build_llm()
    mcp_config = _build_mcp_config()
    prompts_dir = os.environ.get("PROMPTS_DIR", "/opt/officeqa/prompts")

    trajectory: dict[str, Any] = {
        "question": question,
        "phases": [],
        "start_time": time.time(),
    }

    total_budget = int(os.environ.get("MAX_ITERATIONS", "15"))
    # Budget split: 2 plan + 8 research + 4 compute = 14 (1 spare)
    plan_budget = 2  # 2 iterations: model may try a tool call first, then output text
    research_budget = min(8, total_budget - 5)
    compute_budget = min(4, total_budget - research_budget - plan_budget)

    # ── Phase 1: Plan ──────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"PHASE 1: PLANNER (budget={plan_budget})")
    print(f"{'='*50}")

    plan_result = run_phase(
        llm=llm,
        system_prompt_path=f"{prompts_dir}/planner_system.j2",
        instruction=f"QUESTION: {question}",
        phase_name="planner",
        max_iterations=plan_budget,
        # No MCP, no terminal — pure text output
        include_terminal=False,
        mcp_config=None,
        workspace=workspace,
    )
    trajectory["phases"].append(plan_result)

    # Parse and validate plan
    plan = _extract_json(plan_result["raw_output"])
    if not plan:
        print("WARNING: No JSON plan extracted, using raw output as context")
        plan = {"notes": plan_result["raw_output"][:800]}

    # ── Plan Validation ────────────────────────────────────────────
    validation = validate_plan(plan, question)
    plan = validation["plan"]  # may have auto-corrections applied

    print(f"Plan: feasibility={plan.get('feasibility')}, "
          f"computation={plan.get('computation', {}).get('type')}, "
          f"queries={len(plan.get('search_queries', []))}, "
          f"valid={validation['valid']}")
    if validation["warnings"]:
        for w in validation["warnings"]:
            print(f"  ⚠ {w}")
    if validation["fixes"]:
        for k, v in validation["fixes"].items():
            print(f"  ✓ Fixed {k} → {v}")

    trajectory["plan"] = plan
    trajectory["plan_validation"] = validation

    # ── Phase 2: Research ──────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"PHASE 2: RESEARCHER (budget={research_budget})")
    print(f"{'='*50}")

    # Build researcher instruction with the plan context
    research_instruction = (
        f"SEARCH PLAN:\n{json.dumps(plan, indent=2)}\n\n"
        f"ORIGINAL QUESTION: {question}\n\n"
        f"Execute the search plan. Find ALL data values needed to answer the question."
    )

    research_result = run_phase(
        llm=llm,
        system_prompt_path=f"{prompts_dir}/researcher_system.j2",
        instruction=research_instruction,
        phase_name="researcher",
        max_iterations=research_budget,
        mcp_config=mcp_config,
        include_terminal=False,  # Researcher cannot write files
        workspace=workspace,
        template_kwargs={"max_calls": research_budget},
    )
    trajectory["phases"].append(research_result)

    # Collect data from researcher
    data_text = research_result["raw_output"]
    # Also collect raw tool results (more reliable than model's text summary)
    tool_results = [
        ev["content"] for ev in research_result["events"]
        if ev["type"] == "tool_result" and ev.get("content")
    ]
    if tool_results:
        data_text += "\n\nRAW TOOL RESULTS:\n" + "\n---\n".join(tr[:2000] for tr in tool_results[:5])

    # ── Research Validation ──────────────────────────────────────────
    tool_calls_made = [ev for ev in research_result["events"] if ev["type"] == "tool_call"]
    has_data = "DATA_FOUND" in data_text or "value" in data_text.lower()
    has_not_found = "NOT_FOUND" in data_text
    has_error = any("error" in (ev.get("content", "").lower()) for ev in research_result["events"] if ev["type"] == "tool_result")

    research_status = "ok" if has_data and not has_not_found else "partial" if has_data else "empty"
    print(f"Researcher: {len(data_text)} chars, {len(tool_results)} results, "
          f"{len(tool_calls_made)} calls, status={research_status}")
    if has_not_found:
        print("  ⚠ Researcher reported NOT_FOUND for some data")
    if has_error:
        print("  ⚠ Some tool calls returned errors")
    if not tool_calls_made:
        print("  ⚠ Researcher made no tool calls — may have ignored instructions")

    trajectory["research_validation"] = {
        "status": research_status,
        "tool_calls": len(tool_calls_made),
        "tool_results": len(tool_results),
        "has_data": has_data,
        "has_errors": has_error,
    }

    # ── Phase 3: Compute ───────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"PHASE 3: CALCULATOR (budget={compute_budget})")
    print(f"{'='*50}")

    computation_plan = plan.get("computation", {})

    # Try deterministic compute first — parse values from researcher output,
    # apply the function from the plan directly. No LLM needed for common cases.
    det_answer = _deterministic_compute(data_text, plan, question)
    if det_answer:
        print(f"Deterministic compute succeeded: {det_answer}")
        answer_file = Path("/app/answer.txt")
        answer_file.parent.mkdir(parents=True, exist_ok=True)
        answer_file.write_text(det_answer)
        trajectory["phases"].append({"phase": "calculator", "method": "deterministic",
                                      "answer": det_answer, "iterations": 0, "events": []})
    else:
        # Fall back to LLM with terminal only (no search tools).
        print("Deterministic compute failed — falling back to LLM calculator")
        calc_instruction = (
            f"ORIGINAL QUESTION: {question}\n\n"
            f"RETRIEVED DATA:\n{data_text[:6000]}\n\n"
            f"COMPUTATION PLAN: {json.dumps(computation_plan, indent=2)}\n\n"
            f"Compute the answer using Python in the terminal and write it to "
            f"/app/answer.txt using: echo -n \"VALUE\" > /app/answer.txt"
        )
        calc_result = run_phase(
            llm=llm,
            system_prompt_path=f"{prompts_dir}/calculator_system.j2",
            instruction=calc_instruction,
            phase_name="calculator",
            max_iterations=compute_budget,
            mcp_config=None,
            include_terminal=True,
            workspace=workspace,
            template_kwargs={"max_calls": compute_budget},
        )
        trajectory["phases"].append(calc_result)

    # ── Extract answer ─────────────────────────────────────────────
    answer = ""

    # Check answer.txt first (written by calculator via terminal)
    answer_file = Path("/app/answer.txt")
    if answer_file.exists():
        answer = answer_file.read_text().strip()

    # Fallback: parse from LLM calculator output (only set if deterministic failed)
    calc_raw = locals().get("calc_result", {}).get("raw_output", "")
    if not answer and calc_raw:
        m = re.search(r'ANSWER:\s*(.+?)(?:\n|$)', calc_raw)
        if m:
            answer = m.group(1).strip()

    if not answer and calc_raw:
        m = re.search(r'<FINAL_ANSWER>(.*?)</FINAL_ANSWER>', calc_raw, re.DOTALL)
        if m:
            answer = m.group(1).strip()

    if not answer and calc_raw:
        nums = re.findall(r'[-+]?[\d,]+\.?\d*', calc_raw)
        if nums:
            answer = nums[-1].replace(",", "")

    # Write answer if not already written
    if answer and not answer_file.exists():
        answer_file.parent.mkdir(parents=True, exist_ok=True)
        answer_file.write_text(answer)

    trajectory["answer"] = answer
    trajectory["end_time"] = time.time()
    trajectory["total_cost_usd"] = sum(p.get("cost_usd", 0) for p in trajectory["phases"])
    trajectory["total_iterations"] = sum(p.get("iterations", 0) for p in trajectory["phases"])
    trajectory["total_elapsed_s"] = round(time.time() - trajectory["start_time"], 2)

    print(f"\n{'='*50}")
    print(f"DONE — Answer: {answer}")
    print(f"Cost: ${trajectory['total_cost_usd']:.4f}")
    print(f"Iterations: {trajectory['total_iterations']}")
    print(f"Time: {trajectory['total_elapsed_s']}s")
    print(f"{'='*50}")

    return trajectory


# ── Trajectory conversion ──────────────────────────────────────────

def _to_atif(trajectory: dict, model: str) -> dict:
    """Convert orchestrator trajectory to ATIF format for arena compatibility."""
    steps = []
    step_id = 1

    for phase in trajectory.get("phases", []):
        # Phase header
        steps.append({
            "step_id": step_id,
            "source": "system",
            "message": f"--- {phase['phase'].upper()} PHASE ---",
        })
        step_id += 1

        for ev in phase.get("events", []):
            if ev["type"] == "message":
                steps.append({
                    "step_id": step_id,
                    "source": "agent",
                    "message": ev.get("content", ""),
                    "model_name": model,
                })
                step_id += 1
            elif ev["type"] == "tool_call":
                steps.append({
                    "step_id": step_id,
                    "source": "agent",
                    "tool_calls": [{
                        "tool_call_id": ev.get("id", ""),
                        "function_name": ev.get("tool", ""),
                        "arguments": ev.get("args", {}),
                    }],
                    "model_name": model,
                })
                step_id += 1
            elif ev["type"] == "tool_result":
                if steps and steps[-1].get("source") == "agent":
                    steps[-1]["observation"] = {
                        "results": [{"content": ev.get("content", "")}]
                    }

    return {
        "schema_version": "ATIF-v1.5",
        "session_id": os.environ.get("SESSION_ID", "orchestrator"),
        "agent": {"name": "orchestrator", "version": "1.0"},
        "steps": steps,
        "final_metrics": {
            "total_cost_usd": trajectory.get("total_cost_usd", 0),
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
        },
    }


# ── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Orchestrated sub-agent pipeline")
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--logs-dir", required=True)
    parser.add_argument("--trajectory-path", required=True)
    args = parser.parse_args()

    # Extract question from instruction (may be wrapped in system.j2 template)
    question = args.instruction
    # If rendered from system.j2, question is after the template boilerplate
    if "WORKFLOW:" in question and "\n\n" in question:
        # Take everything after "ANSWER FORMAT:" line
        parts = question.split("\n\n")
        question = parts[-1].strip()

    workspace = os.getcwd()
    Path(args.logs_dir).mkdir(parents=True, exist_ok=True)

    model = os.environ.get("LLM_MODEL", "openrouter/minimax/minimax-m2.5")
    print(f"Orchestrator v1.0 | model={model} | budget={os.environ.get('MAX_ITERATIONS', '15')}")
    print(f"Question: {question[:200]}...")

    trajectory = orchestrate(question=question, workspace=workspace)

    # Save orchestrator trajectory
    traj_path = Path(args.trajectory_path)
    traj_path.parent.mkdir(parents=True, exist_ok=True)
    with open(traj_path, "w") as f:
        json.dump(trajectory, f, indent=2, default=str)

    # Also save ATIF-compatible trajectory for arena
    atif = _to_atif(trajectory, model)
    atif_path = traj_path.with_name("trajectory_atif.json")
    with open(atif_path, "w") as f:
        json.dump(atif, f, indent=2, default=str)

    print(f"Trajectory: {traj_path}")


if __name__ == "__main__":
    main()
