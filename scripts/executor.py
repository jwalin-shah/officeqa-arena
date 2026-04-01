#!/usr/bin/env python3
"""Deterministic executor: parse → retrieve → compute → format.

Takes parsed JSON (from parse_v3) and executes the plan using OfficeQATools
with ZERO additional LLM calls. Proves whether the parse is actionable.

Usage:
  python3 scripts/executor.py results/stages/parse_v3_eval31.jsonl \
      --output results/stages/exec_v3_eval31.jsonl

  # Table-lane only (skip hybrid/visual):
  python3 scripts/executor.py results/stages/parse_v3_eval31.jsonl --lanes table
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.tools import OfficeQATools
from src.reward import fuzzy_match_answer

# ── Defaults ─────────────────────────────────────────────────────────
DB_PATH = ROOT / "data" / "officeqa_corpus.sqlite3"
STAGES_DIR = ROOT / "results" / "stages"

# Unit scales for normalization
_UNIT_SCALES = {
    "millions": 1_000_000,
    "billions": 1_000_000_000,
    "trillions": 1_000_000_000_000,
    "thousands": 1_000,
}


# ── Helpers ──────────────────────────────────────────────────────────

def _parse_year(s: str) -> int | None:
    m = re.search(r"\b(1[89]\d{2}|20[0-2]\d)\b", str(s))
    return int(m.group(1)) if m else None


def _year_range_from_constraints(tc: list[dict]) -> tuple[int | None, int | None]:
    years: list[int] = []
    for c in tc:
        for fld in ("start", "end"):
            y = _parse_year(c.get(fld, ""))
            if y:
                years.append(y)
    if not years:
        return None, None
    return min(years), max(years)


def _build_search_query(parsed: dict) -> str:
    parts = []
    te = parsed.get("target_entity", "")
    if te:
        parts.append(te)
    for s in parsed.get("primary_series", []):
        metric = s.get("metric", "")
        ef = s.get("entity_filter", "")
        if metric and metric not in te:
            parts.append(metric)
        if ef and ef not in te and ef not in metric:
            parts.append(ef)
    return " ".join(parts)[:200]


def _needs_series(parsed: dict) -> bool:
    ops = parsed.get("compute_ops", ["none"])
    series_ops = {
        "sum", "average", "mean", "median", "std_dev", "correlation",
        "moving_average", "range", "Winsorized_range", "geometric_mean",
        "CAGR", "percent_change", "CV", "Theil", "kurtosis", "skewness",
        "Pareto_Hill", "KL_divergence", "interpolate", "percentile",
        "forecast", "HP_filter", "exponential_smoothing", "z_score",
        "VaR", "ES",
    }
    if any(op in series_ops for op in ops):
        return True
    tc = parsed.get("time_constraints", [])
    if len(tc) > 1:
        return True
    if tc and tc[0].get("granularity") == "month":
        return True
    return False


def _label_score(label: str, targets: list[str]) -> float:
    """Score how well a row/column label matches target strings (0-1)."""
    if not label or not targets:
        return 0.0
    label_low = label.lower().strip()
    best = 0.0
    for t in targets:
        t_low = t.lower().strip()
        if not t_low:
            continue
        # Exact match
        if label_low == t_low:
            return 1.0
        # Substring containment
        if t_low in label_low:
            best = max(best, 0.8)
        elif label_low in t_low:
            best = max(best, 0.7)
        else:
            # Word overlap
            t_words = set(t_low.split())
            l_words = set(label_low.split())
            if t_words and l_words:
                overlap = len(t_words & l_words) / max(len(t_words), 1)
                best = max(best, overlap * 0.6)
    return best


def _select_best_row(rows: list[dict], parsed: dict) -> dict | None:
    """Select the single best-matching row for a lookup/none op.

    Uses target_entity, metric, entity_filter to score row_label and column_label.
    Prefers rows labeled 'Total' or matching the target entity.
    """
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]

    # Build target strings for matching
    targets = []
    te = parsed.get("target_entity", "")
    if te:
        targets.append(te)
    for s in parsed.get("primary_series", []):
        m = s.get("metric", "")
        ef = s.get("entity_filter", "")
        if m:
            targets.append(m)
        if ef:
            targets.append(ef)

    best_row = None
    best_score = -1.0

    for row in rows:
        rl = str(row.get("row_label", ""))
        cl = str(row.get("column_label", ""))

        # Score both label and column against targets
        row_score = _label_score(rl, targets)
        col_score = _label_score(cl, targets)

        # Boost for "Total" in either label (often the right answer for aggregate questions)
        total_boost = 0.0
        if re.search(r"\btotal\b", rl, re.IGNORECASE):
            total_boost += 0.3
        if re.search(r"\btotal\b", cl, re.IGNORECASE):
            total_boost += 0.3

        # Combined score: prefer column match for lookup (column is usually the metric)
        score = col_score * 0.6 + row_score * 0.4 + total_boost

        if score > best_score:
            best_score = score
            best_row = row

    return best_row


def _select_best_rows_for_series(rows: list[dict], parsed: dict) -> list[dict]:
    """For series ops, filter rows to only those matching the primary metric.

    When get_time_series returns rows from a table with multiple columns,
    we need to pick only the column that matches our metric.
    """
    if not rows or len(rows) <= 1:
        return rows

    targets = []
    te = parsed.get("target_entity", "")
    if te:
        targets.append(te)
    for s in parsed.get("primary_series", []):
        m = s.get("metric", "")
        ef = s.get("entity_filter", "")
        if m:
            targets.append(m)
        if ef:
            targets.append(ef)

    if not targets:
        return rows

    # Group rows by column_label and pick the best-matching column group
    col_groups: dict[str, list[dict]] = {}
    for row in rows:
        cl = str(row.get("column_label", ""))
        col_groups.setdefault(cl, []).append(row)

    # If only one column, return all
    if len(col_groups) <= 1:
        # Try filtering by row_label instead
        rl_groups: dict[str, list[dict]] = {}
        for row in rows:
            rl = str(row.get("row_label", ""))
            rl_groups.setdefault(rl, []).append(row)

        if len(rl_groups) <= 1:
            return rows

        # Score each row_label group
        best_rl = ""
        best_score = -1.0
        for rl, group in rl_groups.items():
            score = _label_score(rl, targets)
            if re.search(r"\btotal\b", rl, re.IGNORECASE):
                score += 0.3
            if score > best_score:
                best_score = score
                best_rl = rl
        if best_score > 0.3 and best_rl:
            return rl_groups[best_rl]
        return rows

    # Score each column group
    best_col = ""
    best_score = -1.0
    for cl, group in col_groups.items():
        score = _label_score(cl, targets)
        if re.search(r"\btotal\b", cl, re.IGNORECASE):
            score += 0.3
        if score > best_score:
            best_score = score
            best_col = cl

    # Only filter if we have a reasonably confident match
    if best_score > 0.3 and best_col:
        return col_groups[best_col]
    return rows


def _normalize_value(raw_val: Any, table_unit_scale: int, output_unit: str) -> float:
    """Convert a raw table value to the canonical unit for computation.

    Strategy:
    - Raw table values are in the table's stated unit (e.g. "in millions" means
      the raw number IS in millions already).
    - For computation, we work in the raw table units.
    - At format time, we convert if the output unit differs from table unit.

    Returns the raw numeric value (no scaling applied during compute).
    """
    try:
        return float(str(raw_val).replace(",", ""))
    except (ValueError, TypeError):
        return float("nan")


def _values_to_floats(series: dict) -> list[float]:
    out = []
    for k in sorted(series.keys()):
        v = series[k]
        try:
            out.append(float(str(v).replace(",", "")))
        except (ValueError, TypeError):
            continue
    return out


def _format_answer(value: float, output_format: dict, table_unit_scale: int = 1) -> str:
    """Format a numeric result according to output_format spec.

    Handles unit conversion between table units and output units.
    """
    fmt_type = output_format.get("type", "number")
    rounding = output_format.get("rounding", "none")
    output_unit = output_format.get("unit", "other")

    # Unit conversion: if table values are in raw units and output expects
    # millions/billions, we may need to divide. But typically, table values
    # are already in the stated unit, so no conversion needed.
    # The key case is when output_unit doesn't match table scale.
    # For now, trust that raw values are already in the right magnitude.

    rounding_map = {
        "nearest_whole": 0,
        "tenths": 1,
        "hundredths": 2,
        "thousandths": 3,
        "4dp": 4,
        "5dp": 5,
        "6dp": 6,
    }
    if rounding in rounding_map:
        value = round(value, rounding_map[rounding])

    if fmt_type == "percent":
        dp = rounding_map.get(rounding, 2)
        return f"{value:.{dp}f}%"
    elif rounding == "nearest_whole":
        return f"{int(value):,}"
    elif rounding in rounding_map:
        dp = rounding_map[rounding]
        return f"{value:.{dp}f}"
    else:
        if value == int(value) and abs(value) < 1e15:
            return f"{int(value):,}"
        return f"{value:,.2f}"


# ── Compute dispatch ─────────────────────────────────────────────────

def _build_expression(ops: list[str], values: list[float], parsed: dict) -> str | None:
    if not values:
        return None

    val_str = ", ".join(str(v) for v in values)

    # Filter out meta-ops that don't map to compute_expression
    real_ops = [op for op in ops if op not in ("none", "lookup", "other",
                "inflation_adjustment", "exchange_rate_conversion",
                "normalize")]
    if not real_ops:
        real_ops = ["none"]

    # Single value lookups
    if real_ops == ["none"] or real_ops == ["lookup"]:
        if len(values) == 1:
            return str(values[0])
        # Multiple values with no op — try to find the most relevant one
        # (selection should have already happened, but fallback)
        return str(values[0])

    # Single op
    if len(real_ops) == 1:
        op = real_ops[0]
        if op == "sum":
            return f"sum([{val_str}])"
        if op in ("average", "mean"):
            return f"mean([{val_str}])"
        if op == "median":
            return f"median([{val_str}])"
        if op == "max":
            return f"max([{val_str}])"
        if op == "min":
            return f"min([{val_str}])"
        if op == "range":
            return f"max([{val_str}]) - min([{val_str}])"
        if op == "std_dev":
            return f"stdev([{val_str}])"
        if op == "CV":
            return f"cv([{val_str}])"
        if op == "geometric_mean":
            return f"geometric_mean([{val_str}])"
        if op == "Theil":
            return f"theil_index([{val_str}])"
        if op == "correlation" and len(values) >= 4:
            mid = len(values) // 2
            s1 = ", ".join(str(v) for v in values[:mid])
            s2 = ", ".join(str(v) for v in values[mid:])
            return f"correlation([{s1}], [{s2}])"
        if op == "Winsorized_range":
            n = len(values)
            k = max(1, int(n * 0.1))
            sv = sorted(values)
            winsorized = sv[k:-k] if k < len(sv) // 2 else sv
            w_str = ", ".join(str(v) for v in winsorized)
            return f"max([{w_str}]) - min([{w_str}])"
        if op == "CAGR" and len(values) >= 2:
            n_years = len(values) - 1
            return f"cagr({values[0]}, {values[-1]}, {n_years})"
        if op == "percent_change" and len(values) >= 2:
            return f"({values[-1]} - {values[0]}) / abs({values[0]}) * 100"
        if op == "difference" and len(values) >= 2:
            return f"{values[-1]} - {values[0]}"
        if op == "absolute_difference" and len(values) >= 2:
            return f"abs({values[-1]} - {values[0]})"
        if op == "ratio" and len(values) >= 2:
            return f"{values[0]} / {values[1]}"
        if op == "divide" and len(values) >= 2:
            return f"{values[0]} / {values[1]}"
        if op == "multiply" and len(values) >= 2:
            return f"{values[0]} * {values[1]}"
        if op == "log_transform" and len(values) >= 1:
            return f"ln({values[0]})"
        if op == "percentile" and len(values) >= 2:
            return f"percentile([{val_str}], 25)"
        if op == "Box_Cox" and len(values) >= 1:
            return f"boxcox([{val_str}], 0.5)"
        if op == "moving_average":
            if len(values) >= 4:
                mas = []
                for i in range(len(values) - 3):
                    window = values[i:i+4]
                    mas.append(sum(window) / 4)
                ma_str = ", ".join(str(round(v, 4)) for v in mas)
                return f"mean([{ma_str}])"

    # Multi-op chains
    if "sum" in real_ops and "percent_change" in real_ops and len(values) >= 2:
        mid = len(values) // 2
        s1 = ", ".join(str(v) for v in values[:mid])
        s2 = ", ".join(str(v) for v in values[mid:])
        return f"abs((sum([{s2}]) - sum([{s1}])) / sum([{s1}]) * 100)"

    if "sum" in real_ops and "absolute_difference" in real_ops and len(values) >= 2:
        mid = len(values) // 2
        s1 = ", ".join(str(v) for v in values[:mid])
        s2 = ", ".join(str(v) for v in values[mid:])
        return f"abs(sum([{s2}]) - sum([{s1}]))"

    if "CAGR" in real_ops and len(values) >= 2:
        n_years = len(values) - 1
        return f"cagr({values[0]}, {values[-1]}, {n_years})"

    if "moving_average" in real_ops and "range" in real_ops:
        if len(values) >= 4:
            mas = []
            for i in range(len(values) - 3):
                window = values[i:i+4]
                mas.append(sum(window) / 4)
            ma_str = ", ".join(str(round(v, 4)) for v in mas)
            return f"max([{ma_str}]) - min([{ma_str}])"

    if "absolute_difference" in real_ops and "min" in real_ops and len(values) >= 2:
        # Find the pair with minimum absolute difference
        # For T-bill spread: compute pairwise diffs
        # Typically this means: find min of |series1 - series2| at each point
        # But we'd need two aligned series for that — fallback to simple min abs diff
        return f"min([{val_str}])"

    if "ratio" in real_ops and len(values) >= 2:
        return f"{values[0]} / {values[1]}"

    if "divide" in real_ops and len(values) >= 2:
        return f"{values[0]} / {values[1]}"

    # Fallback: try the first real op
    for op in real_ops:
        if op == "sum":
            return f"sum([{val_str}])"
        if op in ("average", "mean"):
            return f"mean([{val_str}])"
        if op == "difference" and len(values) >= 2:
            return f"{values[-1]} - {values[0]}"
        if op == "absolute_difference" and len(values) >= 2:
            return f"abs({values[-1]} - {values[0]})"
        if op == "percent_change" and len(values) >= 2:
            return f"({values[-1]} - {values[0]}) / abs({values[0]}) * 100"

    # Last resort
    if len(values) == 1:
        return str(values[0])
    return f"sum([{val_str}])"


# ── Retrieval with row selection ─────────────────────────────────────

def _retrieve_lookup(tools: OfficeQATools, parsed: dict,
                     yr_start: int | None, yr_end: int | None,
                     query: str) -> dict:
    """Retrieve values for a single-value lookup (ops=none/lookup).

    Uses extract_values then selects the best matching row.
    """
    year = yr_start
    metric = ""
    ps = parsed.get("primary_series", [])
    if ps and isinstance(ps[0], dict):
        metric = ps[0].get("metric", "")

    result = tools.extract_values(query=query, metric=metric, year=year)
    results_list = result.get("results", [])

    if not results_list:
        return {"values": [], "table_pk": None, "table_title": "", "unit_scale": 1,
                "rows_detail": [], "method": "extract_values"}

    # Try each candidate table, pick best row from each, then best overall
    best_row = None
    best_table = None

    for res in results_list:
        rows = res.get("rows", [])
        if not rows:
            continue
        # Convert to dicts with consistent keys
        row_dicts = []
        for r in rows:
            row_dicts.append({
                "row_label": r.get("row_label", ""),
                "column_label": r.get("column_label", ""),
                "value": r.get("value"),
                "value_scaled": r.get("value_scaled"),
                "year": r.get("year"),
                "time_scope": r.get("time_scope"),
                "unit_scale": r.get("unit_scale", res.get("unit_scale", 1)),
            })

        selected = _select_best_row(row_dicts, parsed)
        if selected and best_row is None:
            best_row = selected
            best_table = res

    if not best_row or not best_table:
        return {"values": [], "table_pk": None, "table_title": "", "unit_scale": 1,
                "rows_detail": [], "method": "extract_values"}

    # Use raw value (not scaled) — table units are the working units
    raw_val = best_row.get("value")
    table_unit_scale = best_table.get("unit_scale", 1)

    try:
        val = float(str(raw_val).replace(",", ""))
    except (ValueError, TypeError):
        val = None

    # If we got a value, check if it looks like a single data point that
    # might need monthly aggregation. If the parse says granularity=month
    # or there are multiple rows for the same year, we may need to sum.
    return {
        "values": [val] if val is not None else [],
        "table_pk": best_table.get("table_pk"),
        "table_title": best_table.get("table_title", ""),
        "unit_scale": table_unit_scale,
        "rows_detail": [best_row],
        "all_rows": [r for r in results_list[0].get("rows", [])] if results_list else [],
        "method": "extract_values",
    }


def _retrieve_series(tools: OfficeQATools, parsed: dict,
                     yr_start: int, yr_end: int,
                     query: str) -> dict:
    """Retrieve a time series and filter to the best matching metric."""
    metric = ""
    for s in parsed.get("primary_series", []):
        metric = s.get("metric", "")
        if metric:
            break
    if not metric:
        metric = parsed.get("target_entity", "")

    result = tools.get_time_series(
        metric=metric,
        year_start=yr_start,
        year_end=yr_end,
        query=query,
    )

    series_raw = result.get("series", {})
    table_pk = result.get("table_pk")
    table_title = result.get("table_title", "")
    unit_scale = result.get("unit_scale", 1)

    # Series values are already filtered by get_time_series's cascade.
    # The values are raw (in table units).
    values = _values_to_floats(series_raw)

    return {
        "values": values,
        "series": series_raw,
        "table_pk": table_pk,
        "table_title": table_title,
        "unit_scale": unit_scale,
        "granularity": result.get("granularity", "annual"),
        "coverage": result.get("coverage", {}),
        "method": "get_time_series",
    }


def _retrieve_comparison(tools: OfficeQATools, parsed: dict,
                         query: str) -> dict:
    """Retrieve values for both primary and comparison series.

    Returns primary values followed by comparison values.
    """
    tc = parsed.get("time_constraints", [])
    if len(tc) < 2:
        return {"values": [], "error": "comparison needs 2+ time constraints"}

    # Primary series: first time constraint
    yr1_start = _parse_year(tc[0].get("start", ""))
    yr1_end = _parse_year(tc[0].get("end", ""))

    # Comparison series: second time constraint
    yr2_start = _parse_year(tc[1].get("start", ""))
    yr2_end = _parse_year(tc[1].get("end", ""))

    metric = ""
    for s in parsed.get("primary_series", []):
        metric = s.get("metric", "")
        if metric:
            break
    if not metric:
        metric = parsed.get("target_entity", "")

    results: dict[str, Any] = {
        "primary_values": [],
        "comparison_values": [],
        "values": [],
        "table_pk": None,
        "table_title": "",
        "unit_scale": 1,
        "method": "get_time_series (comparison)",
    }

    if yr1_start and yr1_end:
        r1 = tools.get_time_series(metric=metric, year_start=yr1_start,
                                    year_end=yr1_end, query=query)
        results["primary_values"] = _values_to_floats(r1.get("series", {}))
        results["table_pk"] = r1.get("table_pk")
        results["table_title"] = r1.get("table_title", "")
        results["unit_scale"] = r1.get("unit_scale", 1)

    if yr2_start and yr2_end:
        r2 = tools.get_time_series(metric=metric, year_start=yr2_start,
                                    year_end=yr2_end, query=query)
        results["comparison_values"] = _values_to_floats(r2.get("series", {}))

    # Concatenate: primary first, then comparison
    results["values"] = results["primary_values"] + results["comparison_values"]
    return results


# ── Main executor ────────────────────────────────────────────────────

def execute_one(parsed_row: dict, tools: OfficeQATools) -> dict:
    tools.reset_budgets()
    uid = parsed_row["uid"]
    parsed = parsed_row.get("parsed", {})
    gold = parsed_row.get("gold", "")
    lane = parsed_row.get("lane", "table")
    meta = parsed_row.get("v3_meta", {})

    trace: dict = {
        "uid": uid,
        "gold": gold,
        "lane": lane,
        "parse_valid": meta.get("is_valid", False),
        "steps": [],
    }

    t0 = time.time()

    query = _build_search_query(parsed)
    tc = parsed.get("time_constraints", [])
    yr_start, yr_end = _year_range_from_constraints(tc)
    ops = parsed.get("compute_ops", ["none"])
    output_format = parsed.get("output_format", {})
    needs_series = _needs_series(parsed)
    has_comparison = bool(parsed.get("comparison_series"))

    trace["search_query"] = query
    trace["year_range"] = [yr_start, yr_end]
    trace["compute_ops"] = ops
    trace["needs_series"] = needs_series

    if not query:
        trace["error"] = "empty search query from parse"
        trace["latency_s"] = round(time.time() - t0, 2)
        return trace

    # ── Retrieve ─────────────────────────────────────────────────
    retrieval: dict[str, Any] = {}

    if has_comparison and len(tc) >= 2:
        retrieval = _retrieve_comparison(tools, parsed, query)
    elif needs_series and yr_start and yr_end:
        retrieval = _retrieve_series(tools, parsed, yr_start, yr_end, query)
    else:
        retrieval = _retrieve_lookup(tools, parsed, yr_start, yr_end, query)
        # Fallback: if lookup found a value but the question might need
        # monthly aggregation (single year, table has monthly data),
        # try series retrieval as well and let compute decide
        if (retrieval.get("values") and yr_start and yr_start == yr_end
                and ops in (["none"], ["lookup"])):
            # Check if a series retrieval yields more data points
            series_ret = _retrieve_series(tools, parsed, yr_start, yr_end, query)
            if len(series_ret.get("values", [])) > len(retrieval.get("values", [])):
                # More data points available — but only switch if the
                # lookup value doesn't look like a pre-computed total
                lookup_val = retrieval["values"][0] if retrieval["values"] else 0
                series_vals = series_ret["values"]
                series_sum = sum(series_vals) if series_vals else 0
                # If the lookup value is close to the series sum,
                # keep the lookup (it's already the total)
                if series_vals and abs(lookup_val - series_sum) > abs(series_sum) * 0.1:
                    # Lookup value doesn't match series sum — might be
                    # a subcategory. Keep lookup as-is.
                    pass

    values = retrieval.get("values", [])
    table_pk = retrieval.get("table_pk")
    table_title = retrieval.get("table_title", "")
    table_unit_scale = retrieval.get("unit_scale", 1)

    trace["steps"].append({
        "tool": retrieval.get("method", "?"),
        "table_pk": table_pk,
        "table_title": table_title,
        "table_unit_scale": table_unit_scale,
        "values_fetched": len(values),
        "values_preview": values[:10],
    })
    trace["table_pk"] = table_pk
    trace["table_title"] = table_title
    trace["retrieval_method"] = retrieval.get("method", "?")
    trace["values_fetched"] = len(values)
    trace["raw_values"] = values[:20]

    if not values:
        trace["error"] = retrieval.get("error", "no values retrieved")
        trace["answer_produced"] = False
        trace["latency_s"] = round(time.time() - t0, 2)
        return trace

    # ── Compute ──────────────────────────────────────────────────
    expression = _build_expression(ops, values, parsed)
    trace["expression"] = expression

    if expression is None:
        trace["error"] = f"could not build expression for ops={ops}"
        trace["answer_produced"] = False
        trace["latency_s"] = round(time.time() - t0, 2)
        return trace

    compute_result = tools.compute_expression(expression)
    trace["steps"].append({
        "tool": "compute_expression",
        "expression": expression,
        "result": compute_result,
    })

    if not compute_result.get("ok") and "result" not in compute_result:
        trace["error"] = f"compute failed: {compute_result.get('error', '?')}"
        trace["answer_produced"] = False
        trace["latency_s"] = round(time.time() - t0, 2)
        return trace

    raw_result = compute_result.get("result")
    if raw_result is None:
        raw_result = compute_result.get("error", "unknown")
    try:
        numeric_result = float(raw_result)
    except (ValueError, TypeError):
        trace["error"] = f"non-numeric compute result: {raw_result}"
        trace["answer_produced"] = False
        trace["latency_s"] = round(time.time() - t0, 2)
        return trace

    # ── Format ───────────────────────────────────────────────────
    final_answer = _format_answer(numeric_result, output_format,
                                   table_unit_scale)
    trace["final_answer"] = final_answer
    trace["answer_produced"] = True

    # ── Score ─────────────────────────────────────────────────────
    is_correct, rationale = fuzzy_match_answer(gold, final_answer)
    trace["is_correct"] = is_correct
    trace["match_rationale"] = rationale

    trace["latency_s"] = round(time.time() - t0, 2)
    return trace


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Deterministic executor for parse_v3 output")
    parser.add_argument("input", type=str, help="Path to parse_v3 JSONL")
    parser.add_argument("--output", type=str, default="",
                        help="Output JSONL")
    parser.add_argument("--lanes", type=str, default="table,hybrid",
                        help="Comma-separated lanes (default: table,hybrid)")
    parser.add_argument("--db", type=str, default=str(DB_PATH))
    parser.add_argument("--uids", type=str, default="",
                        help="Comma-separated UIDs (default: all valid)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}")
        sys.exit(1)

    output_path = (Path(args.output) if args.output
                   else STAGES_DIR / f"exec_{input_path.stem}.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    allowed_lanes = set(args.lanes.split(","))
    uid_filter = set(args.uids.split(",")) if args.uids else None

    rows = []
    with open(input_path) as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            meta = row.get("v3_meta", {})
            if not meta.get("is_valid"):
                continue
            if row.get("lane") not in allowed_lanes:
                continue
            if uid_filter and row["uid"] not in uid_filter:
                continue
            rows.append(row)

    print(f"\n  EXECUTOR — {len(rows)} valid {args.lanes} parses")
    print(f"  Output: {output_path}\n")

    tools = OfficeQATools(args.db)
    correct = 0
    produced = 0
    errors = 0

    with open(output_path, "w") as f:
        for i, row in enumerate(rows):
            trace = execute_one(row, tools)
            f.write(json.dumps(trace) + "\n")
            f.flush()

            if trace.get("error"):
                status = f"ERROR: {trace['error'][:60]}"
                errors += 1
            elif trace.get("is_correct"):
                status = (f"CORRECT ✓  "
                          f"(got {trace['final_answer']}, "
                          f"gold {trace['gold']})")
                correct += 1
                produced += 1
            elif trace.get("answer_produced"):
                status = (f"WRONG ✗  "
                          f"(got {trace['final_answer']}, "
                          f"gold {trace['gold']})")
                produced += 1
            else:
                status = "NO ANSWER"
                errors += 1

            print(f"  [{i+1}/{len(rows)}] {trace['uid']} "
                  f"[{trace['lane']:<7}] "
                  f"{trace.get('latency_s', 0):.1f}s  {status}")

    print(f"\n  Executor complete:")
    print(f"    Answers produced: {produced}/{len(rows)}")
    print(f"    Correct: {correct}/{len(rows)} "
          f"({100*correct/len(rows):.0f}%)")
    print(f"    Errors: {errors}/{len(rows)}")
    print(f"\n  Output: {output_path}")


if __name__ == "__main__":
    main()
