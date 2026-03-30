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
# Tool definitions (OpenAI function-calling format) -- 7 core tools
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_tables",
            "description": "Find tables by keyword and year. Returns ranked candidates with column samples. Start here for every question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search terms (e.g., 'public works expenditures')"},
                    "file_id": {"type": "string", "default": "", "description": "Restrict to one bulletin file"},
                    "year_range": {"type": "array", "items": {"type": "integer"}, "description": "[start_year, end_year]"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_table_rows",
            "description": "Get cell values from a table. Filter by row label, column, year, month.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_pk": {"type": "integer", "description": "Table primary key from search_tables"},
                    "file_id": {"type": "string", "default": ""},
                    "table_title": {"type": "string", "default": ""},
                    "row_label": {"type": "string", "default": "", "description": "Filter rows containing this text"},
                    "column_label": {"type": "string", "default": "", "description": "Filter to this column"},
                    "year": {"type": "integer", "description": "Single year filter"},
                    "year_range": {"type": "array", "items": {"type": "integer"}, "description": "[start, end] for multi-year"},
                    "month": {"type": "integer"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_structure",
            "description": "List all tables in a bulletin file with titles and row/column counts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_profile",
            "description": "Inspect a table's columns, year coverage, and row count.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_pk": {"type": "integer"},
                },
                "required": ["table_pk"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_expression",
            "description": "Safe arithmetic evaluator. Use for ALL math — never do mental math.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression (e.g., 'a - b', 'a / b * 100')"},
                    "variables": {"type": "object", "description": "Variable values (e.g., {\"a\": 494, \"b\": 154})"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cpi_index",
            "description": "Get CPI-U index value for inflation-adjusted calculations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer"},
                    "month": {"type": "integer"},
                },
                "required": ["year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fiscal_year_bounds",
            "description": "Get start/end dates for a U.S. federal fiscal year.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fiscal_year": {"type": "integer"},
                },
                "required": ["fiscal_year"],
            },
        },
    },
]


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
    model: str = "minimax/minimax-m2.7",
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

    for iteration in range(max_iterations):
        if verbose:
            print(f"  [iter {iteration + 1}/{max_iterations}]", end=" ", flush=True)

        # Budget warning injection
        if iteration == budget_warning_at:
            remaining = max_iterations - iteration
            messages.append({"role": "user", "content": BUDGET_WARNING_MSG.format(remaining=remaining)})

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
            # Only process the FIRST tool call — model must see each result
            # before deciding the next step. Even with parallel_tool_calls=False,
            # some models may still emit multiple; we enforce single execution.
            first_tc = msg.tool_calls[0]
            if len(msg.tool_calls) > 1:
                logger.warning(
                    "Model emitted %d tool calls, only executing first: %s",
                    len(msg.tool_calls), first_tc.function.name,
                )
                # Rewrite message to only contain the first tool call
                msg_dict = msg.model_dump()
                msg_dict["tool_calls"] = [msg_dict["tool_calls"][0]]
                messages.append(msg_dict)
            else:
                messages.append(msg.model_dump())

            entry["tool_calls"] = []
            for tc in [first_tc]:
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
