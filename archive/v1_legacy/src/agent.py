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
from src.parser import can_execute_deterministically, parse_question
from src.executor import execute_spec

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
# Observation masking — compress noisy tool outputs for MiniMax
# ---------------------------------------------------------------------------

_EMPTY_SIGNATURES = frozenset(['[]', '{}', 'null', '""', '{"rows": []}'])


def _mask_observation(tool_name: str, args: dict[str, Any], result_str: str) -> str:
    """Return a compressed version of tool output when it's empty or an error.

    MiniMax fixates on verbose failure messages, causing loops.  Replace them
    with concise, actionable one-liners so the model moves on.
    """
    if result_str in _EMPTY_SIGNATURES:
        params_hint = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:3])
        return f'{{"note": "{tool_name}({params_hint}) returned no results. Try different parameters or a different tool."}}'

    # Check for error in first 300 chars
    if '"error"' in result_str[:300]:
        try:
            parsed = json.loads(result_str)
            if isinstance(parsed, dict) and "error" in parsed:
                err_msg = str(parsed["error"])[:150]
                return json.dumps({"error": err_msg, "note": "Try different parameters."})
        except (json.JSONDecodeError, ValueError):
            pass

    # Truncate very large results to keep context lean (>8KB)
    if len(result_str) > 8192:
        return result_str[:8192] + '\n... (truncated)'

    return result_str


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def _build_budget_hint(iteration: int, max_iter: int, log: list[dict]) -> str | None:
    """Build a progressive meta-cognitive hint based on iteration and evidence state.

    Returns None if no hint needed this iteration.
    """
    remaining = max_iter - iteration
    # Determine what evidence we've gathered so far
    has_compute = False
    has_verdict = False
    has_rows = False
    best_value = None

    for entry in log:
        for tc in entry.get("tool_calls", []):
            res = tc.get("result_full", {})
            if not isinstance(res, dict):
                continue
            if res.get("ok") and res.get("result") is not None:
                has_compute = True
                best_value = res["result"]
            verdict = res.get("verdict")
            if isinstance(verdict, dict) and verdict.get("value") is not None:
                has_verdict = True
                if best_value is None:
                    best_value = verdict["value"]
            rows = res.get("rows") or []
            if not rows:
                for sub in res.get("results", []):
                    if isinstance(sub, dict) and sub.get("rows"):
                        rows = sub["rows"]
                        break
            if rows:
                has_rows = True
                if best_value is None:
                    for row in rows[:3]:
                        if isinstance(row, dict):
                            v = row.get("value_scaled")
                            if v is None:
                                v = row.get("normalized_value")
                            if v is None:
                                v = row.get("value")
                            if v is not None:
                                best_value = v
                                break
            series = res.get("series", {})
            if isinstance(series, dict) and series:
                if best_value is None:
                    last_key = sorted(series.keys())[-1]
                    best_value = series[last_key]

    # Progressive hints at key milestones
    if remaining == 7:
        # ~halfway: gentle status update
        if has_rows or has_verdict:
            return (
                f"[Budget: {remaining} rounds left. You have data. "
                f"Move to computation or deliver your answer with "
                f"<FINAL_ANSWER>value</FINAL_ANSWER>.]"
            )
        else:
            return (
                f"[Budget: {remaining} rounds left. No data found yet. "
                f"Try extract_values with simpler/broader terms, or try grep_corpus as fallback.]"
            )

    if remaining == 4:
        # Urgent: must commit now
        if has_compute and best_value is not None:
            return (
                f"[Budget: {remaining} rounds left. You already computed a result. "
                f"Deliver it now: <FINAL_ANSWER>{best_value}</FINAL_ANSWER>]"
            )
        elif best_value is not None:
            return (
                f"[Budget: {remaining} rounds left. Best value found so far: {best_value}. "
                f"If math is needed, call compute_expression NOW, then deliver with "
                f"<FINAL_ANSWER>value</FINAL_ANSWER>. A wrong answer beats no answer.]"
            )
        else:
            return (
                f"[Budget: {remaining} rounds left. No values found. "
                f"Try grep_corpus as emergency fallback, or deliver your best estimate. "
                f"An empty answer scores 0.]"
            )

    if remaining == 2:
        # Final warning
        if best_value is not None:
            return (
                f"[FINAL WARNING: {remaining} rounds left. "
                f"Deliver now: <FINAL_ANSWER>{best_value}</FINAL_ANSWER>]"
            )
        else:
            return (
                f"[FINAL WARNING: {remaining} rounds left. "
                f"Write your best guess immediately with <FINAL_ANSWER>value</FINAL_ANSWER>.]"
            )

    return None


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

    # ---- Spec-first path: parse → execute deterministically -----------
    try:
        spec, confidence = parse_question(instruction, model, api_key)
        if can_execute_deterministically(spec):
            logger.info("spec-first: confidence=%.2f ops=%s", confidence, spec.get("compute_ops"))
            exec_result = execute_spec(spec, tools_obj)
            if exec_result.success:
                answer = clean_answer(exec_result.answer)
                spec_log = [{
                    "path": "spec-first",
                    "spec": spec,
                    "result": exec_result.answer,
                    "value": exec_result.value,
                    "evidence": exec_result.evidence,
                    "compute_log": exec_result.compute_log,
                }]
                if verbose:
                    print(f"  [spec-first] answer={answer} (confidence={confidence:.2f})")
                logger.info("spec-first success: answer=%s", answer)
                return answer, spec_log
            else:
                logger.info("spec-first execution failed: %s — falling back to agent loop", exec_result.warnings)
        else:
            logger.info("spec not deterministic: ops=%s confidence=%.2f — using agent loop", spec.get("compute_ops"), confidence)
    except Exception as exc:
        logger.info("spec-first parse failed: %s — falling back to agent loop", exc)

    # ---- Legacy agent loop (fallback) ---------------------------------
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    # Budget hints are now progressive — see _build_budget_hint()

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

        # Progressive budget hints at key milestones (remaining=7, 4, 2).
        # We ONLY inject user messages at milestones, not every turn —
        # injecting every turn breaks the tool→assistant flow and causes
        # MiniMax to restart its search instead of continuing.
        budget_hint = _build_budget_hint(iteration, max_iterations, log)
        if budget_hint and not final_answer:
            messages.append({"role": "user", "content": budget_hint})

        # ---- LLM call with retry + exponential backoff -----------------------
        response = None
        for attempt in range(3):
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
                break  # success
            except Exception as exc:
                api_latency = time.time() - t0
                if attempt < 2:
                    wait = 2 ** attempt  # 1s, 2s
                    logger.warning(
                        "API call failed at iter %d attempt %d (%.2fs), retrying in %ds: %s",
                        iteration, attempt + 1, api_latency, wait, exc,
                    )
                    time.sleep(wait)
                else:
                    log.append({"iteration": iteration, "error": str(exc)})
                    logger.warning(
                        "API call failed at iter %d after 3 attempts (%.2fs): %s",
                        iteration, api_latency, exc,
                    )
                    if verbose:
                        print(f"API error (final): {exc}")
        if response is None:
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
            # Execute ALL tool calls sequentially. Previously we truncated
            # multiple retrieval calls to just the first, but this caused
            # MiniMax to loop — it would re-emit the same calls next turn.
            messages.append(msg.model_dump())
            tool_calls_to_execute = list(msg.tool_calls)

            if len(tool_calls_to_execute) > 1:
                logger.info(
                    "Executing %d tool calls sequentially: %s",
                    len(tool_calls_to_execute),
                    [tc.function.name for tc in tool_calls_to_execute],
                )

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

                # Observation masking: compress empty/error results to reduce
                # context noise that causes MiniMax to loop or fixate on failures.
                content_for_model = _mask_observation(fn_name, fn_args, result_str)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": content_for_model,
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
