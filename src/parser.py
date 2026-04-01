"""Parse a natural-language question into a ParseSpec JSON dict via LLM.

Calls OpenRouter, normalises/validates the result using the existing
parse_normalize and parse_validate infrastructure.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from src.parse_normalize import normalize_parsed
from src.parse_validate import validate_parsed

log = logging.getLogger(__name__)

# ── Prompt ───────────────────────────────────────────────────────────

PARSER_PROMPT = """You are a structured-output parser for Treasury bulletin questions.
Your ONLY job is to decompose the question into a retrieval/computation plan.
NEVER answer the question. NEVER do arithmetic. NEVER guess values.
Just extract the structural fields below.

Return ONLY valid JSON with these fields:
{{
  "target_entity": "<primary entity or metric being asked about>",
  "primary_series": [
    {{"metric": "<exact column/series name>", "entity_filter": "<sub-filter if any>", "granularity": "annual"}}
  ],
  "comparison_series": [],
  "time_constraints": [
    {{"start": "<year>", "end": "<year>", "granularity": "year", "note": ""}}
  ],
  "date_resolution_kind": "direct",
  "calendar_basis": "calendar|fiscal|mixed|unknown",
  "retrieval_ops": ["lookup"],
  "compute_ops": ["none"],
  "output_format": {{
    "type": "number|percent|ratio|list|text|date",
    "unit": "millions|billions|nominal_dollars|thousands|percent|yen|ratio|fine_pounds|other",
    "rounding": "nearest_whole|tenths|hundredths|thousandths|4dp|5dp|6dp|none",
    "list_format": "single_value"
  }},
  "external_sources": ["none"],
  "visual_required": {{"needed": false, "subtype": "none"}},
  "world_knowledge_anchor": {{"needed": false, "phrase": "", "expected_resolution": ""}},
  "document_anchor": {{"needed": false, "bulletin_date": "", "specific_table": "", "specific_page": ""}},
  "num_hops": 1,
  "num_tables_needed": 1,
  "confidence": 0.9,
  "notes": []
}}

FEW-SHOT EXAMPLES:

Q: What was total public debt outstanding in fiscal year 1995?
A:
{{"target_entity": "total public debt outstanding", "primary_series": [{{"metric": "total public debt outstanding", "entity_filter": "", "granularity": "annual"}}], "comparison_series": [], "time_constraints": [{{"start": "1995", "end": "1995", "granularity": "year", "note": ""}}], "date_resolution_kind": "direct", "calendar_basis": "fiscal", "retrieval_ops": ["lookup"], "compute_ops": ["lookup"], "output_format": {{"type": "number", "unit": "millions", "rounding": "none", "list_format": "single_value"}}, "external_sources": ["none"], "visual_required": {{"needed": false, "subtype": "none"}}, "world_knowledge_anchor": {{"needed": false, "phrase": "", "expected_resolution": ""}}, "document_anchor": {{"needed": false, "bulletin_date": "", "specific_table": "", "specific_page": ""}}, "num_hops": 1, "num_tables_needed": 1, "confidence": 0.95, "notes": []}}

Q: What was the percent change in gold reserves between 1980 and 1990?
A:
{{"target_entity": "gold reserves", "primary_series": [{{"metric": "gold reserves", "entity_filter": "", "granularity": "annual"}}], "comparison_series": [], "time_constraints": [{{"start": "1980", "end": "1990", "granularity": "year", "note": ""}}], "date_resolution_kind": "direct", "calendar_basis": "fiscal", "retrieval_ops": ["series_extract"], "compute_ops": ["percent_change"], "output_format": {{"type": "percent", "unit": "percent", "rounding": "hundredths", "list_format": "single_value"}}, "external_sources": ["none"], "visual_required": {{"needed": false, "subtype": "none"}}, "world_knowledge_anchor": {{"needed": false, "phrase": "", "expected_resolution": ""}}, "document_anchor": {{"needed": false, "bulletin_date": "", "specific_table": "", "specific_page": ""}}, "num_hops": 1, "num_tables_needed": 1, "confidence": 0.9, "notes": []}}

Q: By how much did interest-bearing debt exceed non-interest-bearing debt in 1970?
A:
{{"target_entity": "interest-bearing debt vs non-interest-bearing debt", "primary_series": [{{"metric": "interest-bearing debt", "entity_filter": "", "granularity": "annual"}}, {{"metric": "non-interest-bearing debt", "entity_filter": "", "granularity": "annual"}}], "comparison_series": [], "time_constraints": [{{"start": "1970", "end": "1970", "granularity": "year", "note": ""}}], "date_resolution_kind": "direct", "calendar_basis": "fiscal", "retrieval_ops": ["lookup"], "compute_ops": ["difference"], "output_format": {{"type": "number", "unit": "millions", "rounding": "none", "list_format": "single_value"}}, "external_sources": ["none"], "visual_required": {{"needed": false, "subtype": "none"}}, "world_knowledge_anchor": {{"needed": false, "phrase": "", "expected_resolution": ""}}, "document_anchor": {{"needed": false, "bulletin_date": "", "specific_table": "", "specific_page": ""}}, "num_hops": 1, "num_tables_needed": 1, "confidence": 0.9, "notes": []}}

Q: In which year between 1950 and 1960 was total receipts the highest?
A:
{{"target_entity": "total receipts", "primary_series": [{{"metric": "total receipts", "entity_filter": "", "granularity": "annual"}}], "comparison_series": [], "time_constraints": [{{"start": "1950", "end": "1960", "granularity": "year", "note": ""}}], "date_resolution_kind": "direct", "calendar_basis": "fiscal", "retrieval_ops": ["series_extract"], "compute_ops": ["max"], "output_format": {{"type": "date", "unit": "other", "rounding": "none", "list_format": "single_value"}}, "external_sources": ["none"], "visual_required": {{"needed": false, "subtype": "none"}}, "world_knowledge_anchor": {{"needed": false, "phrase": "", "expected_resolution": ""}}, "document_anchor": {{"needed": false, "bulletin_date": "", "specific_table": "", "specific_page": ""}}, "num_hops": 1, "num_tables_needed": 1, "confidence": 0.9, "notes": []}}

Now parse this question. Return ONLY valid JSON, no markdown fences, no explanation.

Question: {question}"""


# ── JSON repair helper ───────────────────────────────────────────────

def _repair_json(text: str) -> dict:
    """Extract and parse JSON from LLM output, fixing common issues."""
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fix trailing commas before } or ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to extract the first JSON object
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            cleaned = re.sub(r",\s*([}\]])", r"\1", match.group())
            return json.loads(cleaned)

    raise ValueError(f"Could not parse JSON from LLM output: {text[:200]}")


# ── LLM call ────────────────────────────────────────────────────────

def parse_question(
    question: str, model: str, api_key: str
) -> tuple[dict, float]:
    """Call OpenRouter to parse *question* into a ParseSpec dict.

    Returns (parsed_dict, confidence).  Raises on failure.
    """
    prompt = PARSER_PROMPT.format(question=question)

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 1024,
        },
        timeout=30,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    parsed = _repair_json(content)

    # Normalize
    parsed, warnings = normalize_parsed(parsed)
    if warnings:
        log.debug("normalize warnings: %s", warnings)

    # Route to determine lane for validation
    lane = _route_spec(parsed)

    # Validate
    result = validate_parsed(parsed, lane)
    if not result.is_valid:
        log.warning("validation errors: %s", result.errors)

    confidence = float(parsed.get("confidence", 0.5))
    return parsed, confidence


# ── Router ───────────────────────────────────────────────────────────

def _route_spec(parsed: dict) -> str:
    """Deterministic router: returns lane based on ParseSpec fields.

    Same logic as stage_runner._route_question().
    """
    # Visual lane
    vis = parsed.get("visual_required", {})
    if isinstance(vis, dict) and vis.get("needed"):
        return "visual"

    # External data lane (CPI, FX, FRED, etc. -- not just event dates)
    ext = parsed.get("external_sources", ["none"])
    has_external_data = any(
        s not in ("none", "event_date_lookup") for s in ext
    )

    # World knowledge / event anchor lane
    wk = parsed.get("world_knowledge_anchor", {})
    has_event_date = (
        isinstance(wk, dict) and wk.get("needed")
    ) or "event_date_lookup" in ext
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


# ── Deterministic execution check ───────────────────────────────────

_DETERMINISTIC_OPS = frozenset({
    "none", "lookup", "difference", "percent_change",
    "ratio", "sum", "max", "min", "average",
})


def can_execute_deterministically(parsed: dict) -> bool:
    """Return True if the spec is simple enough for deterministic execution.

    Criteria:
    - All compute_ops are in the deterministic set
    - Lane is "table" (not visual/external_date/hybrid)
    - Confidence >= 0.75
    - primary_series has at least one entry with a non-empty metric
    """
    # Check compute_ops
    ops = parsed.get("compute_ops", ["none"])
    if not all(op in _DETERMINISTIC_OPS for op in ops):
        return False

    # Check lane
    if _route_spec(parsed) != "table":
        return False

    # Check confidence
    confidence = parsed.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)) or confidence < 0.75:
        return False

    # Check primary_series has a metric
    ps = parsed.get("primary_series", [])
    if not any(
        isinstance(s, dict) and s.get("metric", "").strip()
        for s in ps
    ):
        return False

    return True
