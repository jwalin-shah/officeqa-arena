"""Deterministic executor: takes a validated ParseSpec dict and runs it
against MCP tools without any LLM involvement.

Given a spec (from the parser) and a tools object (OfficeQATools instance),
fetches evidence from the database and computes the answer using only the
safe arithmetic evaluator.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── Result container ─────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    answer: str = ""
    value: float | None = None
    evidence: list[dict] = field(default_factory=list)
    compute_log: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    success: bool = False


# ── Rounding helper ──────────────────────────────────────────────────

_ROUNDING_MAP: dict[str, int | None] = {
    "nearest_whole": 0,
    "tenths": 1,
    "hundredths": 2,
    "thousandths": 3,
    "4dp": 4,
    "5dp": 5,
    "6dp": 6,
    "none": None,
}


def _format_answer(value: float, output_format: dict) -> str:
    """Apply rounding and type-specific formatting."""
    rounding = output_format.get("rounding", "none")
    ndigits = _ROUNDING_MAP.get(rounding)
    if ndigits is not None:
        value = round(value, ndigits)

    # Format the number: drop trailing zeros for decimals, use integer form
    # when the result is a whole number.
    if ndigits == 0 or (ndigits is None and value == int(value)):
        formatted = str(int(value))
    else:
        formatted = f"{value:.{ndigits if ndigits is not None else 10}f}".rstrip("0").rstrip(".")

    out_type = output_format.get("type", "number")
    if out_type == "percent":
        formatted += "%"

    return formatted


# ── Value fetcher ────────────────────────────────────────────────────

def _fetch_value(
    tools_obj: Any,
    metric: str,
    year: int,
    calendar_basis: str,
    target_entity: str = "",
) -> tuple[float | None, dict]:
    """Try search_ledger first, then fall back to extract_values.

    Returns (numeric_value, evidence_dict).
    """
    evidence: dict[str, Any] = {
        "metric": metric,
        "year": year,
        "calendar_basis": calendar_basis,
    }

    # --- Attempt 1: search_ledger (fast, exact) ----------------------
    period_basis = calendar_basis if calendar_basis in ("calendar", "fiscal") else ""
    ledger = tools_obj.search_ledger(metric=metric, year=year, period_basis=period_basis)

    if ledger.get("results"):
        row = ledger["results"][0]
        val = row.get("value")
        if val is not None:
            try:
                numeric = float(val)
            except (ValueError, TypeError):
                numeric = None
            if numeric is not None:
                evidence.update({
                    "table_pk": row.get("table_pk"),
                    "source": row.get("source"),
                    "table_title": row.get("table_title"),
                    "value_raw": row.get("value_raw"),
                    "units": ledger.get("units", ""),
                    "time_key": row.get("time_key"),
                    "origin": "search_ledger",
                })
                return numeric, evidence

    # --- Attempt 2: extract_values (broader, slower) -----------------
    query = target_entity or metric
    ev = tools_obj.extract_values(query=query, metric=metric, year=year)

    # Check verdict first (pre-scored best match)
    verdict = ev.get("verdict") if isinstance(ev, dict) else None
    if isinstance(verdict, dict) and verdict.get("value") is not None:
        try:
            numeric = float(verdict["value"])
        except (ValueError, TypeError):
            numeric = None
        if numeric is not None:
            evidence.update({
                "table_pk": verdict.get("table_pk"),
                "table_title": verdict.get("table_title"),
                "units": verdict.get("units", ""),
                "origin": "extract_values/verdict",
            })
            return numeric, evidence

    # Check individual result rows
    for res in ev.get("results", []):
        for row in res.get("rows", []):
            # Prefer value_scaled when unit_scale > 1
            val = row.get("value_scaled") if row.get("unit_scale", 1) > 1 else None
            if val is None:
                val = row.get("value")
            if val is None:
                continue
            try:
                numeric = float(val)
            except (ValueError, TypeError):
                continue
            evidence.update({
                "table_pk": res.get("table_pk"),
                "table_title": res.get("table_title"),
                "units": res.get("units", ""),
                "row_label": row.get("row_label"),
                "column_label": row.get("column_label"),
                "origin": "extract_values/rows",
            })
            return numeric, evidence

    return None, evidence


def _fetch_series_values(
    tools_obj: Any,
    metric: str,
    year_start: int,
    year_end: int,
    target_entity: str = "",
) -> tuple[dict[int, float], list[dict]]:
    """Fetch a range of yearly values. Returns ({year: value}, [evidence])."""
    ts = tools_obj.get_time_series(
        metric=metric,
        year_start=year_start,
        year_end=year_end,
        query=target_entity or metric,
    )
    series_raw = ts.get("series", {})
    values: dict[int, float] = {}
    evidences: list[dict] = []

    for key, val in series_raw.items():
        try:
            yr = int(re.sub(r"[^\d]", "", str(key)))
            values[yr] = float(val)
            evidences.append({"year": yr, "value": float(val), "time_key": key})
        except (ValueError, TypeError):
            continue

    return values, evidences


# ── Year extraction ──────────────────────────────────────────────────

def _extract_years(time_constraints: list[dict]) -> tuple[int | None, int | None]:
    """Parse start/end years from time_constraints list."""
    if not time_constraints:
        return None, None
    tc = time_constraints[0]
    start_str = str(tc.get("start", ""))
    end_str = str(tc.get("end", ""))

    def _parse_year(s: str) -> int | None:
        m = re.search(r"\d{4}", s)
        return int(m.group()) if m else None

    return _parse_year(start_str), _parse_year(end_str)


# ── Main entry point ─────────────────────────────────────────────────

def execute_spec(spec: dict, tools_obj: Any) -> ExecutionResult:
    """Execute a ParseSpec dict deterministically using MCP tools.

    Routes to the appropriate execution path based on ``compute_ops``.
    """
    result = ExecutionResult()
    log = result.compute_log

    # --- Unpack spec fields -------------------------------------------
    target_entity = spec.get("target_entity", "")
    primary_series = spec.get("primary_series", [])
    comparison_series = spec.get("comparison_series", [])
    time_constraints = spec.get("time_constraints", [])
    compute_ops = spec.get("compute_ops", ["none"])
    output_format = spec.get("output_format", {})
    if isinstance(output_format, str):
        output_format = {"type": output_format}
    calendar_basis = spec.get("calendar_basis", "unknown")

    # Metric from primary series
    metric = ""
    if primary_series:
        ps0 = primary_series[0]
        metric = ps0.get("metric", "") if isinstance(ps0, dict) else ""
    if not metric:
        result.warnings.append("No metric found in primary_series")
        return result

    log.append(f"metric={metric!r}  entity={target_entity!r}  calendar={calendar_basis}")

    # Years
    year_start, year_end = _extract_years(time_constraints)
    log.append(f"years: start={year_start}  end={year_end}")

    # Primary compute op
    op = compute_ops[0] if compute_ops else "none"
    log.append(f"compute_op={op!r}")

    try:
        if op in ("none", "lookup"):
            _exec_lookup(tools_obj, result, metric, year_start or year_end, calendar_basis, target_entity, output_format)

        elif op == "difference":
            _exec_difference(tools_obj, result, metric, year_start, year_end, calendar_basis, target_entity, output_format)

        elif op == "absolute_difference":
            _exec_difference(tools_obj, result, metric, year_start, year_end, calendar_basis, target_entity, output_format, absolute=True)

        elif op == "percent_change":
            _exec_percent_change(tools_obj, result, metric, year_start, year_end, calendar_basis, target_entity, output_format)

        elif op == "ratio":
            _exec_ratio(tools_obj, result, metric, primary_series, comparison_series, year_start or year_end, calendar_basis, target_entity, output_format)

        elif op == "sum":
            _exec_aggregate(tools_obj, result, "sum", metric, year_start, year_end, calendar_basis, target_entity, output_format)

        elif op == "average":
            _exec_aggregate(tools_obj, result, "mean", metric, year_start, year_end, calendar_basis, target_entity, output_format)

        elif op in ("max", "min"):
            _exec_aggregate(tools_obj, result, op, metric, year_start, year_end, calendar_basis, target_entity, output_format)

        else:
            result.warnings.append(f"Unsupported compute_op: {op}")
            # Fall back to simple lookup
            _exec_lookup(tools_obj, result, metric, year_start or year_end, calendar_basis, target_entity, output_format)

    except Exception as exc:
        result.warnings.append(f"Execution error: {exc}")
        result.success = False

    return result


# ── Operation implementations ────────────────────────────────────────

def _exec_lookup(
    tools_obj: Any, result: ExecutionResult,
    metric: str, year: int | None, calendar_basis: str,
    target_entity: str, output_format: dict,
) -> None:
    if year is None:
        result.warnings.append("No year specified for lookup")
        return
    val, ev = _fetch_value(tools_obj, metric, year, calendar_basis, target_entity)
    result.evidence.append(ev)
    if val is None:
        result.warnings.append(f"No value found for {metric!r} year={year}")
        return
    result.value = val
    result.answer = _format_answer(val, output_format)
    result.compute_log.append(f"lookup -> {val}")
    result.success = True


def _exec_difference(
    tools_obj: Any, result: ExecutionResult,
    metric: str, year1: int | None, year2: int | None,
    calendar_basis: str, target_entity: str, output_format: dict,
    absolute: bool = False,
) -> None:
    if year1 is None or year2 is None:
        result.warnings.append("Need two years for difference")
        return
    v1, ev1 = _fetch_value(tools_obj, metric, year1, calendar_basis, target_entity)
    v2, ev2 = _fetch_value(tools_obj, metric, year2, calendar_basis, target_entity)
    result.evidence.extend([ev1, ev2])
    if v1 is None or v2 is None:
        result.warnings.append(f"Missing value: year1={v1}, year2={v2}")
        return

    expr = "abs(a - b)" if absolute else "a - b"
    comp = tools_obj.compute_expression(expression=expr, variables={"a": v2, "b": v1})
    result.compute_log.append(f"{expr}: a={v2} (yr={year2}), b={v1} (yr={year1}) -> {comp}")

    if comp.get("ok"):
        result.value = comp["result"]
        result.answer = _format_answer(comp["result"], output_format)
        result.success = True
    else:
        result.warnings.append(f"compute_expression error: {comp.get('error')}")


def _exec_percent_change(
    tools_obj: Any, result: ExecutionResult,
    metric: str, year1: int | None, year2: int | None,
    calendar_basis: str, target_entity: str, output_format: dict,
) -> None:
    if year1 is None or year2 is None:
        result.warnings.append("Need two years for percent_change")
        return
    v1, ev1 = _fetch_value(tools_obj, metric, year1, calendar_basis, target_entity)
    v2, ev2 = _fetch_value(tools_obj, metric, year2, calendar_basis, target_entity)
    result.evidence.extend([ev1, ev2])
    if v1 is None or v2 is None:
        result.warnings.append(f"Missing value: year1={v1}, year2={v2}")
        return
    if v1 == 0:
        result.warnings.append("Base value is zero; cannot compute percent change")
        return

    expr = "((a - b) / b) * 100"
    comp = tools_obj.compute_expression(expression=expr, variables={"a": v2, "b": v1})
    result.compute_log.append(f"percent_change: a={v2} (yr={year2}), b={v1} (yr={year1}) -> {comp}")

    if comp.get("ok"):
        result.value = comp["result"]
        # Force percent output format
        pct_fmt = dict(output_format)
        pct_fmt["type"] = "percent"
        result.answer = _format_answer(comp["result"], pct_fmt)
        result.success = True
    else:
        result.warnings.append(f"compute_expression error: {comp.get('error')}")


def _exec_ratio(
    tools_obj: Any, result: ExecutionResult,
    metric: str, primary_series: list, comparison_series: list,
    year: int | None, calendar_basis: str, target_entity: str,
    output_format: dict,
) -> None:
    if year is None:
        result.warnings.append("No year specified for ratio")
        return

    # Numerator from primary_series[0]
    v1, ev1 = _fetch_value(tools_obj, metric, year, calendar_basis, target_entity)
    result.evidence.append(ev1)

    # Denominator: comparison_series[0] or primary_series[1]
    denom_metric = ""
    if comparison_series:
        cs0 = comparison_series[0]
        denom_metric = cs0.get("metric", "") if isinstance(cs0, dict) else ""
    elif len(primary_series) > 1:
        ps1 = primary_series[1]
        denom_metric = ps1.get("metric", "") if isinstance(ps1, dict) else ""

    if not denom_metric:
        result.warnings.append("No denominator metric found for ratio")
        return

    v2, ev2 = _fetch_value(tools_obj, denom_metric, year, calendar_basis, target_entity)
    result.evidence.append(ev2)

    if v1 is None or v2 is None:
        result.warnings.append(f"Missing value for ratio: numerator={v1}, denominator={v2}")
        return
    if v2 == 0:
        result.warnings.append("Denominator is zero; cannot compute ratio")
        return

    comp = tools_obj.compute_expression(expression="a / b", variables={"a": v1, "b": v2})
    result.compute_log.append(f"ratio: a={v1}/{denom_metric!r}, b={v2} -> {comp}")

    if comp.get("ok"):
        result.value = comp["result"]
        result.answer = _format_answer(comp["result"], output_format)
        result.success = True
    else:
        result.warnings.append(f"compute_expression error: {comp.get('error')}")


def _exec_aggregate(
    tools_obj: Any, result: ExecutionResult,
    agg_fn: str, metric: str,
    year_start: int | None, year_end: int | None,
    calendar_basis: str, target_entity: str, output_format: dict,
) -> None:
    if year_start is None or year_end is None:
        result.warnings.append(f"Need year range for {agg_fn}")
        return

    values, evidences = _fetch_series_values(
        tools_obj, metric, year_start, year_end, target_entity,
    )
    result.evidence.extend(evidences)

    if not values:
        result.warnings.append(f"No series values found for {metric!r} {year_start}-{year_end}")
        return

    sorted_vals = [values[yr] for yr in sorted(values)]
    result.compute_log.append(f"{agg_fn} over {len(sorted_vals)} values: {sorted_vals}")

    # Build the appropriate expression
    var_names = [f"v{i}" for i in range(len(sorted_vals))]
    variables = {name: val for name, val in zip(var_names, sorted_vals)}
    var_list = ", ".join(var_names)

    if agg_fn == "sum":
        expr = f"sum({var_list})"
    elif agg_fn == "mean":
        expr = f"mean({var_list})"
    elif agg_fn == "max":
        expr = f"max({var_list})"
    elif agg_fn == "min":
        expr = f"min({var_list})"
    else:
        result.warnings.append(f"Unknown aggregate function: {agg_fn}")
        return

    comp = tools_obj.compute_expression(expression=expr, variables=variables)
    result.compute_log.append(f"{expr} -> {comp}")

    if comp.get("ok"):
        result.value = comp["result"]
        result.answer = _format_answer(comp["result"], output_format)
        result.success = True
    else:
        result.warnings.append(f"compute_expression error: {comp.get('error')}")
