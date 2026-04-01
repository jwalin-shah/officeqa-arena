"""Validate a normalized ParseSpec dict and optionally auto-fix issues.

Returns a ``ValidationResult`` with the verdict, list of errors, and whether
auto-fixes were applied.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.parse_types import (
    ComputeOp,
    ExternalSource,
    OutputType,
    Rounding,
    UnitType,
)


@dataclass
class ValidationResult:
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    auto_fixed: bool = False
    needs_repair: bool = False  # True if errors are unfixable by Python alone


def _has_parseable_year(text: str) -> bool:
    return bool(re.search(r"\b(1[89]\d{2}|20[0-2]\d)\b", str(text)))


def validate_parsed(parsed: dict[str, Any], lane: str) -> ValidationResult:
    """Validate a normalized parsed dict.

    Attempts auto-fixes for minor issues.  Sets ``needs_repair=True`` when
    errors require an LLM re-prompt to fix.
    """
    r = ValidationResult()

    # 1. target_entity must be non-empty
    te = parsed.get("target_entity", "")
    if not te or not str(te).strip():
        r.errors.append("target_entity is empty")
        r.needs_repair = True

    # 2. primary_series must have at least one entry with non-empty metric
    ps = parsed.get("primary_series", [])
    if not ps or not isinstance(ps, list):
        r.errors.append("primary_series is missing or empty")
        r.needs_repair = True
    elif not any(
        isinstance(s, dict) and s.get("metric", "").strip() for s in ps
    ):
        r.errors.append("primary_series has no entry with a non-empty metric")
        r.needs_repair = True

    # 3. time_constraints — at least one with a parseable year
    tc = parsed.get("time_constraints", [])
    if not tc or not isinstance(tc, list):
        r.errors.append("time_constraints is missing or empty")
        r.needs_repair = True
    else:
        has_year = any(
            _has_parseable_year(c.get("start", "")) or _has_parseable_year(c.get("end", ""))
            for c in tc
            if isinstance(c, dict)
        )
        if not has_year:
            # Not necessarily fatal — event_anchor lane may not have years yet
            if lane not in ("external_date",):
                r.errors.append("time_constraints has no parseable year")
                r.needs_repair = True

    # 4. compute_ops — all values must be valid
    valid_ops = {e.value for e in ComputeOp}
    for op in parsed.get("compute_ops", []):
        if op not in valid_ops:
            r.errors.append(f"invalid compute_op '{op}'")
            # Auto-fixable: normalizer should have caught this
            r.auto_fixed = True

    # 5. output_format.type
    of = parsed.get("output_format", {})
    if isinstance(of, dict):
        valid_types = {e.value for e in OutputType}
        if of.get("type", "number") not in valid_types:
            r.errors.append(f"invalid output_format.type '{of.get('type')}'")
            of["type"] = "number"
            r.auto_fixed = True

        # 6. output_format.unit
        valid_units = {e.value for e in UnitType}
        if of.get("unit", "other") not in valid_units:
            r.errors.append(f"invalid output_format.unit '{of.get('unit')}'")
            of["unit"] = "other"
            r.auto_fixed = True

        # output_format.rounding
        valid_roundings = {e.value for e in Rounding}
        if of.get("rounding", "none") not in valid_roundings:
            r.errors.append(f"invalid output_format.rounding '{of.get('rounding')}'")
            of["rounding"] = "none"
            r.auto_fixed = True

    # 7. external_sources
    valid_ext = {e.value for e in ExternalSource}
    for src in parsed.get("external_sources", []):
        if src not in valid_ext:
            r.errors.append(f"invalid external_source '{src}'")

    # 8. Lane-specific consistency
    if lane == "visual":
        vr = parsed.get("visual_required", {})
        if not (isinstance(vr, dict) and vr.get("needed")):
            r.errors.append("lane=visual but visual_required.needed is not True")
            # Auto-fix
            if isinstance(vr, dict):
                vr["needed"] = True
                if vr.get("subtype", "none") == "none":
                    vr["subtype"] = "chart_read"
                r.auto_fixed = True

    # 9. Lane=external_date consistency
    if lane == "external_date":
        drk = parsed.get("date_resolution_kind", "direct")
        wk = parsed.get("world_knowledge_anchor", {})
        wk_needed = isinstance(wk, dict) and wk.get("needed")
        if drk not in ("event_anchor", "historical_anchor") and not wk_needed:
            r.errors.append(
                "lane=external_date but date_resolution_kind is not event/historical "
                "and world_knowledge_anchor.needed is not True"
            )
            # Auto-fix date_resolution_kind
            parsed["date_resolution_kind"] = "event_anchor"
            r.auto_fixed = True

    # 10. num_tables_needed range (normalizer already clamps, but double-check)
    ntn = parsed.get("num_tables_needed", 1)
    if not isinstance(ntn, int) or ntn < 1 or ntn > 5:
        r.errors.append(f"num_tables_needed out of range: {ntn}")
        parsed["num_tables_needed"] = max(1, min(int(ntn), 5))
        r.auto_fixed = True

    # 11. confidence range
    conf = parsed.get("confidence", 0.9)
    if not isinstance(conf, (int, float)) or conf < 0.0 or conf > 1.0:
        r.errors.append(f"confidence out of range: {conf}")
        parsed["confidence"] = 0.5
        r.auto_fixed = True

    # 12. No unknown top-level keys
    allowed_keys = {
        "target_entity", "primary_series", "comparison_series",
        "time_constraints", "date_resolution_kind", "calendar_basis",
        "retrieval_ops", "compute_ops", "output_format", "external_sources",
        "visual_required", "world_knowledge_anchor", "document_anchor",
        "num_hops", "num_tables_needed", "confidence", "notes",
    }
    stray = set(parsed.keys()) - allowed_keys
    if stray:
        r.errors.append(f"unknown top-level keys: {stray}")
        for k in stray:
            del parsed[k]
        r.auto_fixed = True

    r.is_valid = len(r.errors) == 0 or (r.auto_fixed and not r.needs_repair)
    return r


def build_repair_prompt(question: str, parsed: dict, errors: list[str]) -> str:
    """Build a repair prompt that asks the LLM to fix specific errors."""
    import json

    error_list = "\n".join(f"  - {e}" for e in errors)
    return f"""The following parse of a Treasury bulletin question has validation errors.
Fix ONLY the fields mentioned in the errors. Return the complete corrected JSON.

ERRORS:
{error_list}

ORIGINAL QUESTION: {question}

CURRENT PARSE (fix the errors below):
{json.dumps(parsed, indent=2)}

Return ONLY valid JSON with the corrected fields. Do NOT add notes or explanations."""
