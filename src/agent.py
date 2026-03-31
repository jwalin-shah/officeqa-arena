"""Main agent loop for OfficeQA Arena.

Drives an OpenRouter-hosted LLM through iterative tool use until it
produces a FINAL_ANSWER or exhausts its iteration budget.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from src.answer import (
    clean_answer,
    extract_echo_answer,
    extract_final_answer,
    extract_from_history,
)

# TODO: grounding module is being created by another agent.
# Import conditionally until it lands.
try:
    from src.grounding import audit_answer, build_repair_message  # type: ignore[import-not-found]
    _HAS_GROUNDING = True
except ImportError:
    _HAS_GROUNDING = False

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# Auto-generated from MCP TOOL_SCHEMAS to stay in sync with submission path.
# ---------------------------------------------------------------------------

def _mcp_to_openai_tools() -> list[dict[str, Any]]:
    """Convert MCP TOOL_SCHEMAS to OpenAI function-calling format.

    This ensures local eval uses the EXACT same tool surface as MCP submission.
    """
    from server.mcp_stdio import TOOL_SCHEMAS
    tools = []
    for schema in TOOL_SCHEMAS:
        tools.append({
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema["description"],
                "parameters": schema["inputSchema"],
            },
        })
    return tools


TOOL_DEFINITIONS: list[dict[str, Any]] = _mcp_to_openai_tools()


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _render_system_prompt(instruction: str) -> str:
    """Render prompts/system.j2 with Jinja2, falling back to a plain template."""
    template_path = ROOT / "prompts" / "system.j2"
    if template_path.exists():
        try:
            import jinja2

            env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(str(template_path.parent))
            )
            tmpl = env.get_template(template_path.name)
            return tmpl.render(instruction=instruction)
        except ImportError:
            text = template_path.read_text()
            return text.replace("{{ instruction }}", instruction)

    # Hard-coded fallback
    return (
        "You are a Treasury Department financial-data specialist.\n\n"
        f"Task: {instruction}\n\n"
        "Process:\n"
        "1. Parse the question (entity, year, metric, unit).\n"
        "2. Retrieve evidence with search_tables + query_table_rows.\n"
        "3. Verify year, row, column, and units match exactly.\n"
        "4. Use compute_expression for arithmetic.\n"
        "5. Return ONLY the answer value.\n"
    )


def _load_skills() -> str:
    """Load all skills/*.md files and concatenate them."""
    skills_dir = ROOT / "skills"
    if not skills_dir.is_dir():
        return ""
    parts: list[str] = []
    for md in sorted(skills_dir.glob("*.md")):
        text = md.read_text().strip()
        if text:
            parts.append(text)
    if not parts:
        return ""
    return "\n\n--- Skills ---\n" + "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def _call_tool(tools_obj: Any, name: str, arguments: dict[str, Any]) -> str:
    """Call an MCP tool method and return JSON result string."""
    method = getattr(tools_obj, name, None)
    if method is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = method(**arguments)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc), "tool": name})


# ---------------------------------------------------------------------------
# Structured tool-call logging
# ---------------------------------------------------------------------------

def _log_tool_call(
    name: str,
    arguments: dict[str, Any],
    result_str: str,
    latency_s: float,
) -> None:
    """Log a single tool call with truncated params, response size, and latency."""
    params_preview = json.dumps(arguments, default=str)[:200]
    resp_bytes = len(result_str.encode("utf-8", errors="replace"))

    # Check for warning conditions
    is_empty = result_str in ('[]', '{}', 'null', '""', '{"rows": []}')
    has_error = '"error"' in result_str[:200]

    if is_empty:
        logger.warning(
            "tool=%s params=%s -> EMPTY result (%d bytes, %.2fs)",
            name, params_preview, resp_bytes, latency_s,
        )
    elif has_error:
        logger.warning(
            "tool=%s params=%s -> ERROR in response (%d bytes, %.2fs): %s",
            name, params_preview, resp_bytes, latency_s, result_str[:200],
        )
    else:
        logger.info(
            "tool=%s params=%s -> %d bytes, %.2fs",
            name, params_preview, resp_bytes, latency_s,
        )


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

BUDGET_WARNING_MSG = "You have {remaining} calls left. Deliver your answer now. Use <FINAL_ANSWER>value</FINAL_ANSWER>."


def run_agent_loop(
    instruction: str,
    tools_obj: Any,
    model: str = os.environ.get("OFFICEQA_MODEL", "minimax/minimax-m2.5"),
    max_iterations: int = 15,
    verbose: bool = False,
) -> tuple[str, list[dict]]:
    """Run the agentic tool-use loop. Returns (final_answer, conversation_log)."""
    from openai import OpenAI

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is not set")

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    # Configurable budget warning: whichever is later --
    # halfway through, or 5 iterations before the end.
    budget_warning_at = max(max_iterations - 5, max_iterations // 2)

    # ---- Build system prompt ------------------------------------------------
    system_prompt = _render_system_prompt(instruction)

    skills_text = _load_skills()
    if skills_text:
        system_prompt += "\n" + skills_text

    system_prompt += (
        "\n\nIMPORTANT: Wrap your final answer in "
        "<FINAL_ANSWER>your answer</FINAL_ANSWER> tags. "
        "Write ONLY the value inside the tags -- no prose, no explanation."
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": instruction},
    ]

    final_answer = ""
    log: list[dict] = []
    _forced_finish_injected = False

    for iteration in range(max_iterations):
        if verbose:
            print(f"  [iter {iteration + 1}/{max_iterations}]", end=" ", flush=True)

        # Budget warning injection
        if iteration == budget_warning_at:
            remaining = max_iterations - iteration
            messages.append({"role": "user", "content": BUDGET_WARNING_MSG.format(remaining=remaining)})

        # Forced finish: at iteration 8, inject evidence summary and demand answer
        if iteration == 8 and not final_answer and not _forced_finish_injected:
            _forced_finish_injected = True
            # Build evidence summary from tool results so far
            evidence_lines = []
            best_value = None  # track best single value for fallback suggestion
            for entry in log:
                for tc in entry.get("tool_calls", []):
                    res = tc.get("result_full", {})
                    if not isinstance(res, dict):
                        continue
                    # compute_expression result = highest priority
                    if res.get("ok") and res.get("result") is not None:
                        best_value = res["result"]
                        evidence_lines.append(f"  compute_expression = {best_value}")
                    # verdict from extract_values
                    verdict = res.get("verdict")
                    if isinstance(verdict, dict) and verdict.get("value") is not None:
                        if best_value is None:
                            best_value = verdict["value"]
                        evidence_lines.append(f"  verdict: {verdict.get('row_label','')} = {verdict['value']}")
                    # rows from query_table_rows / extract_values
                    rows = res.get("rows") or []
                    if not rows:
                        for sub in res.get("results", []):
                            if isinstance(sub, dict) and sub.get("rows"):
                                rows = sub["rows"]
                                break
                    for row in (rows or [])[:3]:
                        if isinstance(row, dict):
                            rl = row.get("row_label", "")
                            cl = row.get("column_label", "")
                            v = row.get("value_scaled") or row.get("value_raw") or row.get("value") or row.get("normalized_value")
                            if v is not None:
                                if best_value is None:
                                    best_value = v
                                evidence_lines.append(f"  {rl} | {cl} = {v}")
                    # time series
                    series = res.get("series", {})
                    if isinstance(series, dict):
                        for k in sorted(series.keys())[:6]:
                            evidence_lines.append(f"  {k} = {series[k]}")
            evidence_text = "\n".join(evidence_lines[:15]) if evidence_lines else "  (no values extracted yet)"
            suggestion = ""
            if best_value is not None:
                suggestion = (
                    f"\n\nIf no further computation is needed, your best answer is: "
                    f"<FINAL_ANSWER>{best_value}</FINAL_ANSWER>"
                )
            messages.append({"role": "user", "content":
                f"STOP SEARCHING. You have {max_iterations - iteration} rounds left.\n\n"
                f"Data you have found so far:\n{evidence_text}\n\n"
                f"Use these values NOW. Call compute_expression if math is needed, "
                f"then write your answer with <FINAL_ANSWER>value</FINAL_ANSWER>. "
                f"A wrong answer scores better than no answer.{suggestion}"
            })

        # ---- LLM call -------------------------------------------------------
        t0 = time.time()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                parallel_tool_calls=False,
                temperature=0.0,
                max_tokens=4096,
                # extra_body={"reasoning_effort": "medium"},  # removed — let model decide
            )
        except Exception as exc:
            api_latency = time.time() - t0
            log.append({"iteration": iteration, "error": str(exc)})
            logger.warning(
                "API call failed at iter %d (%.2fs): %s", iteration, api_latency, exc,
            )
            if verbose:
                print(f"API error: {exc}")
            break

        api_latency = time.time() - t0
        logger.info("iter=%d api_latency=%.2fs", iteration, api_latency)

        choice = response.choices[0]
        msg = choice.message

        entry: dict[str, Any] = {
            "iteration": iteration,
            "finish_reason": choice.finish_reason,
            "api_latency_s": round(api_latency, 3),
        }

        if msg.content:
            entry["content"] = msg.content[:500]
            if verbose:
                print(f"content: {msg.content[:120]}...")

        # ---- Check for FINAL_ANSWER -----------------------------------------
        if msg.content:
            fa = extract_final_answer(msg.content)
            if fa is not None:
                final_answer = clean_answer(fa)
                log.append(entry)

                # Post-answer grounding audit (log only — don't reject answers yet)
                if _HAS_GROUNDING:
                    audit = audit_answer(instruction, final_answer, log)
                    logger.info(
                        "Grounding audit at iter %d: grounded=%s score=%d/7 checks=%s",
                        iteration, audit.get("grounded"), audit.get("score", 0),
                        audit.get("checks", {}),
                    )
                    # TODO: re-enable rejection once audit accuracy is validated
                    # if not audit["grounded"] and iteration < max_iterations - 2:
                    #     repair_msg = build_repair_message(audit)
                    #     messages.append(msg.model_dump())
                    #     messages.append({"role": "user", "content": repair_msg})
                    #     final_answer = ""
                    #     continue

                break

            echo = extract_echo_answer(msg.content)
            if echo is not None:
                final_answer = clean_answer(echo)
                log.append(entry)

                # Post-answer grounding audit (same logic for echo extraction)
                if _HAS_GROUNDING and iteration < max_iterations - 2:
                    audit = audit_answer(instruction, final_answer, log)
                    if not audit["grounded"]:
                        repair_msg = build_repair_message(audit)
                        messages.append(msg.model_dump())
                        messages.append({"role": "user", "content": repair_msg})
                        final_answer = ""
                        logger.info(
                            "Grounding audit failed (echo) at iter %d, injecting repair brief",
                            iteration,
                        )
                        continue

                break

        # ---- Process tool calls ---------------------------------------------
        if msg.tool_calls:
            # Decide which tool calls to execute:
            # - For retrieval tools (search_tables, query_table_rows, get_file_structure,
            #   get_table_profile): only execute the FIRST — model must see results
            #   before deciding the next step.
            # - For computation/reference tools (compute_expression, get_cpi_index,
            #   get_fiscal_year_bounds): execute ALL — these are deterministic and
            #   the model knows the inputs upfront.
            _RETRIEVAL_TOOLS = {
                "search_tables", "query_table_rows", "get_file_structure",
                "get_table_profile", "extract_values", "get_time_series",
                "get_multi_year_series", "resolve_agency_alias",
                "grep_corpus", "web_lookup",
            }

            all_retrieval = all(
                tc.function.name in _RETRIEVAL_TOOLS for tc in msg.tool_calls
            )

            if len(msg.tool_calls) > 1 and all_retrieval:
                # Multiple retrieval calls — only execute first
                first_tc = msg.tool_calls[0]
                logger.warning(
                    "Model emitted %d retrieval tool calls, only executing first: %s",
                    len(msg.tool_calls), first_tc.function.name,
                )
                msg_dict = msg.model_dump()
                msg_dict["tool_calls"] = [msg_dict["tool_calls"][0]]
                messages.append(msg_dict)
                tool_calls_to_execute = [first_tc]
            else:
                # Either single call, or mix includes computation — execute all
                messages.append(msg.model_dump())
                tool_calls_to_execute = list(msg.tool_calls)

            entry["tool_calls"] = []
            for tc in tool_calls_to_execute:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    fn_args = {}

                if verbose:
                    print(f"  tool: {fn_name}({json.dumps(fn_args)[:100]})")

                tool_t0 = time.time()
                result_str = _call_tool(tools_obj, fn_name, fn_args)
                tool_latency = time.time() - tool_t0

                _log_tool_call(fn_name, fn_args, result_str, tool_latency)

                # Parse full result for grounding audit
                try:
                    result_parsed = json.loads(result_str)
                except (json.JSONDecodeError, ValueError):
                    result_parsed = {"text": result_str[:500]}

                entry["tool_calls"].append({
                    "name": fn_name,
                    "args": fn_args,
                    "result_preview": result_str[:200],
                    "result_full": result_parsed,
                    "result_bytes": len(result_str.encode("utf-8", errors="replace")),
                    "latency_s": round(tool_latency, 3),
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

            log.append(entry)
            continue

        # ---- No tool calls, no tags -- treat content as answer ---------------
        if msg.content and choice.finish_reason == "stop":
            content = msg.content.strip()
            if len(content) < 200:
                final_answer = clean_answer(content)
            else:
                for line in reversed(content.split("\n")):
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("*"):
                        final_answer = clean_answer(line)
                        break

            # Post-answer grounding audit for fallback extraction
            if final_answer and _HAS_GROUNDING and iteration < max_iterations - 2:
                audit = audit_answer(instruction, final_answer, log)
                if not audit["grounded"]:
                    repair_msg = build_repair_message(audit)
                    messages.append(msg.model_dump())
                    messages.append({"role": "user", "content": repair_msg})
                    final_answer = ""
                    logger.info(
                        "Grounding audit failed (fallback) at iter %d, injecting repair brief",
                        iteration,
                    )
                    continue

            log.append(entry)
            break

        log.append(entry)

    # ---- History fallback ---------------------------------------------------
    if not final_answer:
        hist_val = extract_from_history(messages)
        if hist_val:
            final_answer = clean_answer(hist_val)

    return final_answer, log
