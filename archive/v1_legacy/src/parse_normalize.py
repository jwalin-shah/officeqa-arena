"""Map freeform LLM parse outputs to canonical enum values.

Each ``normalize_*`` function tries exact match first, then a synonym table,
then falls back to a sensible default.  A list of warnings is accumulated so
callers can log drift without blocking the pipeline.
"""
from __future__ import annotations

import re
from typing import Any

from src.parse_types import (
    CalendarBasis,
    ComputeOp,
    DateResKind,
    ExternalSource,
    Lane,
    OutputType,
    Rounding,
    UnitType,
    VisualSubtype,
)

# ── Synonym tables ────────────────────────────────────────────────────
# Keys are lowercase.  Values are canonical enum *values* (strings).

_COMPUTE_OP_SYNONYMS: dict[str, str] = {
    # difference family
    "subtraction": "difference",
    "subtract": "difference",
    "absolute_value": "absolute_difference",
    "absolute": "absolute_difference",
    # percent change family
    "percentage_change": "percent_change",
    "pct_change": "percent_change",
    "arc_percent_change": "percent_change",
    "arc_elasticity": "percent_change",
    "log_change": "percent_change",
    "log_growth": "percent_change",
    "logarithmic_growth_rate": "percent_change",
    "midpoint_normalized_difference": "percent_change",
    # average family
    "mean": "average",
    # multiply / divide
    "multiplication": "multiply",
    "multiply_100": "multiply",
    "division": "divide",
    "ratio_calculation": "ratio",
    # std_dev family
    "sample_std_dev": "std_dev",
    "population_std_dev": "std_dev",
    "population_standard_deviation": "std_dev",
    # correlation family
    "pearson": "correlation",
    "pearson_correlation": "correlation",
    "partial_correlation": "correlation",
    "covariance": "correlation",
    # log
    "ln": "log_transform",
    "log": "log_transform",
    "logarithm": "log_transform",
    # statistical
    "hazen_percentile": "percentile",
    "tukey_q1_exclusive_median": "percentile",
    "hill_estimator_k7": "Pareto_Hill",
    "arima_1_1_0": "forecast",
    "project": "forecast",
    "centered_moving_average": "moving_average",
    "moving_average_4yr": "moving_average",
    # misc
    "round": "other",
    "round_intermediate": "other",
    "rounding": "other",
    "filter": "lookup",
    "square": "multiply",
    "convert_ounces_to_pounds": "multiply",
    "minimum": "min",
    "maximum": "max",
    "quadratic_regression": "OLS",
    "gini coefficient calculation requires distribution data - interpret as ratio of difference to sum": "ratio",
}

_UNIT_SYNONYMS: dict[str, str] = {
    "nominal dollars": "nominal_dollars",
    "dollars": "nominal_dollars",
    "mil": "millions",
    "mm": "millions",
    "bn": "billions",
    "tn": "trillions",
    "pct": "percent",
    "%": "percent",
    "mixed": "other",
    "decimal": "other",
    "euros": "other",
    "pounds": "fine_pounds",
    "dem": "other",
    "inr": "other",
    "year": "years",
    "millions_march_1970_dollars_per_month": "millions",
    "millions_dollars_per_year": "millions",
    "percent|millions_dollars": "percent",
    "categories": "count",
    "cases": "count",
}

_ROUNDING_SYNONYMS: dict[str, str] = {
    "nearest whole": "nearest_whole",
    "two decimal places": "hundredths",
    "two_decimal_places": "hundredths",
    "2 decimal places": "hundredths",
    "nearest hundredth": "hundredths",
    "tenths|whole": "tenths",
    "millions": "nearest_whole",
    "mixed": "none",
}

_EXT_SOURCE_SYNONYMS: dict[str, str] = {
    "cpi": "BLS_CPI",
    "bls": "BLS_CPI",
    "fred": "FRED",
    "imf": "IMF",
    "worldbank": "WorldBank",
    "world_bank": "WorldBank",
    "macrotrends": "FRED",
    "bea": "BEA_GDP",
    "bea_gdp": "BEA_GDP",
    "gdp": "BEA_GDP",
    "treasury_bulletin": "Treasury_Bulletin",
    "treasury bulletin": "Treasury_Bulletin",
}

# Patterns that map to historical_event (matched via prefix)
_HISTORICAL_EVENT_PREFIX = "historical_date_"


# ── Public API ────────────────────────────────────────────────────────

def normalize_compute_ops(raw_list: list[str], warnings: list[str]) -> list[str]:
    """Return canonical compute_ops list."""
    out: list[str] = []
    valid = {e.value for e in ComputeOp}
    for raw in raw_list:
        low = raw.strip().lower()
        if raw in valid:
            out.append(raw)
        elif low in _COMPUTE_OP_SYNONYMS:
            out.append(_COMPUTE_OP_SYNONYMS[low])
        elif low in valid:
            # Case mismatch — find the right canonical value
            out.append(low)
        else:
            warnings.append(f"unknown compute_op '{raw}' → 'other'")
            out.append("other")
    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped = []
    for v in out:
        if v not in seen:
            seen.add(v)
            deduped.append(v)
    return deduped or ["none"]


def normalize_unit(raw: str, warnings: list[str]) -> str:
    """Return canonical unit string."""
    valid = {e.value for e in UnitType}
    if raw in valid:
        return raw
    low = raw.strip().lower()
    if low in _UNIT_SYNONYMS:
        return _UNIT_SYNONYMS[low]
    if low in valid:
        return low
    warnings.append(f"unknown unit '{raw}' → 'other'")
    return "other"


def normalize_rounding(raw: str, warnings: list[str]) -> str:
    """Return canonical rounding string."""
    valid = {e.value for e in Rounding}
    if raw in valid:
        return raw
    low = raw.strip().lower()
    if low in _ROUNDING_SYNONYMS:
        return _ROUNDING_SYNONYMS[low]
    if low in valid:
        return low
    warnings.append(f"unknown rounding '{raw}' → 'none'")
    return "none"


def normalize_output_type(raw: str, warnings: list[str]) -> str:
    valid = {e.value for e in OutputType}
    if raw in valid:
        return raw
    low = raw.strip().lower()
    if low in valid:
        return low
    warnings.append(f"unknown output_type '{raw}' → 'number'")
    return "number"


def normalize_external_sources(raw_list: list[str], warnings: list[str]) -> list[str]:
    valid = {e.value for e in ExternalSource}
    out: list[str] = []
    for raw in raw_list:
        if raw in valid:
            out.append(raw)
        elif raw.strip().lower() in _EXT_SOURCE_SYNONYMS:
            out.append(_EXT_SOURCE_SYNONYMS[raw.strip().lower()])
        elif raw.strip().lower().startswith(_HISTORICAL_EVENT_PREFIX):
            out.append("historical_event")
        else:
            warnings.append(f"unknown external_source '{raw}' → kept as-is")
            out.append(raw)
    return out or ["none"]


def normalize_lane(raw: str, warnings: list[str]) -> str:
    valid = {e.value for e in Lane}
    low = raw.strip().lower()
    if low in valid:
        return low
    warnings.append(f"unknown lane '{raw}' → 'table'")
    return "table"


def normalize_date_resolution_kind(raw: str, warnings: list[str]) -> str:
    valid = {e.value for e in DateResKind}
    if raw in valid:
        return raw
    low = raw.strip().lower()
    if low in valid:
        return low
    warnings.append(f"unknown date_resolution_kind '{raw}' → 'direct'")
    return "direct"


def normalize_calendar_basis(raw: str, warnings: list[str]) -> str:
    valid = {e.value for e in CalendarBasis}
    if raw in valid:
        return raw
    low = raw.strip().lower()
    if low in valid:
        return low
    warnings.append(f"unknown calendar_basis '{raw}' → 'unknown'")
    return "unknown"


def normalize_visual_subtype(raw: str, warnings: list[str]) -> str:
    valid = {e.value for e in VisualSubtype}
    if raw in valid:
        return raw
    low = raw.strip().lower()
    if low in valid:
        return low
    warnings.append(f"unknown visual_subtype '{raw}' → 'none'")
    return "none"


def normalize_years_in_constraints(constraints: list[dict]) -> list[dict]:
    """Ensure start/end are 4-digit year strings where possible."""
    for tc in constraints:
        for fld in ("start", "end"):
            val = str(tc.get(fld, "")).strip()
            # Handle "FY1940", "FY 1940", etc.
            fy = re.search(r"(?:FY|fy)\s*(1[89]\d{2}|20[0-2]\d)", val)
            if fy:
                tc[fld] = fy.group(1)
                continue
            # Extract first 4-digit year if embedded in text
            m = re.search(r"\b(1[89]\d{2}|20[0-2]\d)\b", val)
            if m:
                tc[fld] = m.group(1)
    return constraints


def _coerce_series_list(raw: Any, warnings: list[str], field_name: str) -> list[dict]:
    """Ensure series list contains dicts with 'metric' key, not bare strings."""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            warnings.append(f"{field_name}: coerced bare string '{item}' to dict")
            out.append({"metric": item, "entity_filter": "", "granularity": "annual"})
        elif isinstance(item, dict):
            out.append(item)
    return out


def _coerce_time_constraints(raw: Any, warnings: list[str]) -> list[dict]:
    """Ensure time_constraints use start/end format, not year/fiscal_year."""
    if not isinstance(raw, list):
        return []
    out = []
    for tc in raw:
        if not isinstance(tc, dict):
            continue
        if "start" in tc or "end" in tc:
            out.append(tc)
        elif "year" in tc:
            year = str(tc["year"])
            is_fiscal = tc.get("fiscal_year", False)
            gran = "year"
            if is_fiscal:
                warnings.append(f"time_constraint: coerced {{year: {year}, fiscal_year}} to start/end")
            out.append({"start": year, "end": year, "granularity": gran})
        else:
            out.append(tc)
    return out


def normalize_parsed(parsed: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Normalize all fields in a parsed dict in-place. Returns (parsed, warnings)."""
    warnings: list[str] = []

    # Structural coercions — fix shape before field-level normalization
    if "primary_series" in parsed:
        parsed["primary_series"] = _coerce_series_list(
            parsed["primary_series"], warnings, "primary_series"
        )
    if "comparison_series" in parsed:
        parsed["comparison_series"] = _coerce_series_list(
            parsed["comparison_series"], warnings, "comparison_series"
        )
    if "time_constraints" in parsed:
        parsed["time_constraints"] = _coerce_time_constraints(
            parsed["time_constraints"], warnings
        )

    # compute_ops
    if "compute_ops" in parsed:
        parsed["compute_ops"] = normalize_compute_ops(
            parsed["compute_ops"], warnings
        )

    # output_format
    of = parsed.get("output_format", {})
    if isinstance(of, dict):
        if "type" in of:
            of["type"] = normalize_output_type(of["type"], warnings)
        if "unit" in of:
            of["unit"] = normalize_unit(of["unit"], warnings)
        if "rounding" in of:
            of["rounding"] = normalize_rounding(of["rounding"], warnings)
        # Remove stray keys (e.g. "nominal_dollars" that appeared in V2 drift)
        allowed_of_keys = {"type", "unit", "rounding", "list_format"}
        stray = set(of.keys()) - allowed_of_keys
        for k in stray:
            warnings.append(f"removed stray output_format key '{k}'")
            del of[k]

    # external_sources
    if "external_sources" in parsed:
        parsed["external_sources"] = normalize_external_sources(
            parsed["external_sources"], warnings
        )

    # date_resolution_kind
    if "date_resolution_kind" in parsed:
        parsed["date_resolution_kind"] = normalize_date_resolution_kind(
            parsed["date_resolution_kind"], warnings
        )

    # calendar_basis
    if "calendar_basis" in parsed:
        parsed["calendar_basis"] = normalize_calendar_basis(
            parsed["calendar_basis"], warnings
        )

    # visual_required.subtype
    vr = parsed.get("visual_required", {})
    if isinstance(vr, dict) and "subtype" in vr:
        vr["subtype"] = normalize_visual_subtype(vr["subtype"], warnings)

    # time_constraints
    if "time_constraints" in parsed:
        parsed["time_constraints"] = normalize_years_in_constraints(
            parsed["time_constraints"]
        )

    # num_tables_needed — clamp
    ntn = parsed.get("num_tables_needed", 1)
    if not isinstance(ntn, int):
        try:
            ntn = int(ntn)
        except (ValueError, TypeError):
            ntn = 1
    parsed["num_tables_needed"] = max(1, min(ntn, 5))

    # confidence — clamp
    conf = parsed.get("confidence", 0.9)
    if not isinstance(conf, (int, float)):
        try:
            conf = float(conf)
        except (ValueError, TypeError):
            conf = 0.5
    parsed["confidence"] = max(0.0, min(float(conf), 1.0))

    return parsed, warnings
