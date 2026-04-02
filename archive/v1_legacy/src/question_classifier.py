#!/usr/bin/env python3
"""Deterministic question classifier for OfficeQA Arena.

Classifies Treasury Bulletin questions by type, complexity, and recommended
tool strategy using regex/keyword matching. No LLM calls -- fast and
deterministic.

Usage:
    from src.question_classifier import classify, get_tool_strategy

    result = classify("What was the total receipts in FY 1953?")
    strategy = get_tool_strategy(result)
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Question type patterns (order matters -- first match wins for primary type)
_TYPE_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    ("visual", [
        re.compile(r"\b(page\s+\d+|chart|plot|graph|visual|figure|local\s+maxim|local\s+minim|inflection|trend\s+line|bar\s+chart|pie\s+chart|histogram)\b", re.I),
    ]),
    ("statistical", [
        re.compile(r"\b(theil|geometric\s+mean|stdev|standard\s+deviation|volatility|hodrick|euclidean|correlation|variance|coefficient\s+of\s+variation|box[\s-]?cox|percentile|median|dispersion|gini|herfindahl)\b", re.I),
    ]),
    ("growth_rate", [
        re.compile(r"\b(growth\s+rate|CAGR|compound\s+annual|year[\s-]over[\s-]year|YoY|annualized\s+(growth|return)|percent(age)?\s+change)\b", re.I),
    ]),
    ("ratio", [
        re.compile(r"\b(ratio|proportion|share|as\s+a\s+percent(age)?\s+of|fraction|relative\s+to)\b", re.I),
        re.compile(r"\bpercent\b(?!.*\b(change|growth|increase|decrease)\b)", re.I),
    ]),
    ("multi_value", [
        re.compile(r"\b(list|enumerate|comma[\s-]?separated|all\s+values)\b", re.I),
        re.compile(r"\[.*\]"),  # brackets in expected output
        re.compile(r"\bfrom\s+\d{4}\s+to\s+\d{4}\b", re.I),  # year ranges often want lists
    ]),
    ("aggregation", [
        re.compile(r"\b(sum|total|aggregate|cumulative|combined|add\s+up|net\s+total)\b", re.I),
        re.compile(r"\b(mean|average)\s+(of|for|across|over)\b", re.I),
    ]),
    ("comparison", [
        re.compile(r"\b(difference\s+between|compare|change\s+(in|from|between)|higher|lower|more\s+than|less\s+than|exceed|gap\s+between|delta|surplus|deficit\s+change)\b", re.I),
        re.compile(r"\bhow\s+much\s+(did|has|more|less)\b", re.I),
    ]),
    ("temporal", [
        re.compile(r"\b(trend|over\s+time|time[\s-]?series|historical|trajectory|evolution|progression)\b", re.I),
    ]),
    ("external_knowledge", [
        re.compile(r"\b(CPI|inflation[\s-]adjust|real\s+(value|dollar)|constant\s+dollar|nominal\s+to\s+real)\b", re.I),
        re.compile(r"\b(exchange\s+rate|foreign\s+currency|convert\s+to\s+(yen|pounds|euros|marks|rupees))\b", re.I),
        re.compile(r"\b(World\s+War|WW[12I]|Great\s+Depression|Black\s+Monday|Korean\s+War|Vietnam\s+War|Cold\s+War|New\s+Deal|Marshall\s+Plan|Bretton\s+Woods)\b", re.I),
    ]),
    ("direct_lookup", [
        re.compile(r".*", re.I),  # fallback -- everything else is direct lookup
    ]),
]

# Period basis detection
_FISCAL_PAT = re.compile(r"\b(fiscal\s+(year|month)|FY\s*\d|FY\b)", re.I)
_CALENDAR_PAT = re.compile(r"\b(calendar\s+year|CY\s*\d|CY\b)", re.I)

# Year extraction
_YEAR_PAT = re.compile(r"\b(1[89]\d{2}|20[0-3]\d)\b")

# Year range pattern (for detecting contiguous ranges)
_YEAR_RANGE_PAT = re.compile(r"\b(1[89]\d{2}|20[0-3]\d)\s*(?:to|through|thru|-|–|—)\s*(1[89]\d{2}|20[0-3]\d)\b", re.I)

# Output unit extraction
_UNIT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("millions", re.compile(r"\bin\s+millions?\b", re.I)),
    ("billions", re.compile(r"\bin\s+billions?\b", re.I)),
    ("thousands", re.compile(r"\bin\s+thousands?\b", re.I)),
    ("percent", re.compile(r"\b(percent(age)?|%)\b", re.I)),
    ("basis_points", re.compile(r"\bbasis\s+points?\b", re.I)),
]

_ROUND_PAT = re.compile(r"\brounded?\s+to\s+(\d+|the\s+nearest\s+\w+)", re.I)

# Metric extraction -- strip common preamble/postamble to isolate the metric
_METRIC_NOISE = re.compile(
    r"^(what\s+(was|is|were|are)\s+(the\s+)?(total\s+)?|"
    r"calculate\s+(the\s+)?|"
    r"find\s+(the\s+)?|"
    r"how\s+much\s+(was|is|did)\s+(the\s+)?|"
    r"list\s+(the\s+)?|"
    r"determine\s+(the\s+)?)",
    re.I,
)

# Historical event references
_HISTORICAL_EVENTS = re.compile(
    r"\b(World\s+War|WW[12I]|Great\s+Depression|Black\s+Monday|Black\s+Thursday|"
    r"Korean\s+War|Vietnam\s+War|Cold\s+War|New\s+Deal|Marshall\s+Plan|"
    r"Bretton\s+Woods|Pearl\s+Harbor|D[\s-]?Day|9/11|September\s+11|"
    r"Great\s+Recession|dot[\s-]?com|Gulf\s+War|Sputnik)\b",
    re.I,
)

# Tool names from MCP schema
ALL_TOOLS = [
    "search_ledger",
    "extract_values",
    "get_time_series",
    "get_multi_year_series",
    "search_tables",
    "query_table_rows",
    "get_table_profile",
    "get_file_structure",
    "compute_expression",
    "get_cpi_index",
    "get_exchange_rate",
    "get_fiscal_year_bounds",
    "grep_corpus",
    "web_lookup",
    "resolve_agency_alias",
    "verify_answer",
]


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

def _detect_type(question: str) -> str:
    """Return the primary question type."""
    for qtype, patterns in _TYPE_PATTERNS:
        for pat in patterns:
            if pat.search(question):
                # Special case: "total" in a direct lookup context is not aggregation
                if qtype == "aggregation":
                    # "total X in year Y" is direct_lookup (the table already has the total row)
                    # "total of X from Y1 to Y2" is aggregation (summing across years)
                    if re.search(r"\btotal\b", question, re.I) and not re.search(
                        r"\b(sum|aggregate|cumulative|combined|add\s+up|mean|average)\b", question, re.I
                    ):
                        years = _YEAR_PAT.findall(question)
                        year_range = _YEAR_RANGE_PAT.search(question)
                        # Single year + "total" = direct lookup for a total row
                        if len(years) <= 1 and not year_range:
                            continue  # skip aggregation, fall through
                return qtype
    return "direct_lookup"


def _extract_years(question: str) -> list[int]:
    """Extract all 4-digit years from the question."""
    return sorted(set(int(y) for y in _YEAR_PAT.findall(question)))


def _detect_period_basis(question: str) -> str:
    """Detect fiscal vs calendar year basis."""
    has_fiscal = bool(_FISCAL_PAT.search(question))
    has_calendar = bool(_CALENDAR_PAT.search(question))
    if has_fiscal and not has_calendar:
        return "fiscal"
    if has_calendar and not has_fiscal:
        return "calendar"
    return "unknown"


def _extract_output_unit(question: str) -> str | None:
    """Extract expected output unit from the question."""
    for unit_name, pat in _UNIT_PATTERNS:
        if pat.search(question):
            return unit_name
    rounding = _ROUND_PAT.search(question)
    if rounding:
        return f"rounded:{rounding.group(1)}"
    return None


def _extract_metrics(question: str) -> list[str]:
    """Extract likely metric names from the question.

    Uses heuristic stripping of question boilerplate to isolate the metric
    phrase. This is approximate -- the agent will refine via search.
    """
    metrics: list[str] = []
    # Remove year references and known noise
    cleaned = _YEAR_PAT.sub("", question)
    cleaned = _METRIC_NOISE.sub("", cleaned)
    # Remove trailing clauses
    cleaned = re.sub(
        r"\b(in\s+(millions?|billions?|thousands?|percent(age)?)|"
        r"for\s+the\s+U\.?S\.?|"
        r"from\s+\w+\s+to\s+\w+|"
        r"between\s+\w+\s+to\s+\w+|"
        r"fiscal\s+(year|month)|calendar\s+year|"
        r"rounded\s+to\s+\w+|"
        r"of\s+the\s+U\.?S\.?\s+Treasury|"
        r"FY|CY|"
        r"U\.?S\.?\s+Federal\s+Government|"
        r"on\s+page\s+\d+\s+of\s+the\s+\w+\s+\d+\s+US\s+Treasury\s+Monthly\s+Bulletin)\b",
        "",
        cleaned,
        flags=re.I,
    )
    # Remove dangling prepositions and whitespace
    cleaned = re.sub(r"\b(in|for|from|to|between|of|the|a|an)\s*$", "", cleaned.strip(), flags=re.I)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,?.")

    if cleaned and len(cleaned) > 3:
        metrics.append(cleaned)

    return metrics


def _assess_complexity(
    qtype: str, years: list[int], question: str
) -> str:
    """Assess question complexity."""
    year_range = _YEAR_RANGE_PAT.search(question)
    year_span = 0
    if year_range:
        year_span = int(year_range.group(2)) - int(year_range.group(1))

    # Hard cases
    if qtype in ("statistical", "visual"):
        return "hard"
    if qtype == "multi_value" and year_span > 3:
        return "hard"
    if qtype == "growth_rate" and year_span > 2:
        return "hard"
    if year_span > 5:
        return "hard"

    # Medium cases
    if qtype in ("comparison", "ratio", "growth_rate", "temporal"):
        return "medium"
    if qtype == "aggregation" and len(years) > 1:
        return "medium"
    if qtype == "multi_value":
        return "medium"
    if qtype == "external_knowledge":
        return "medium"
    if len(years) == 2:
        return "medium"

    # Easy
    return "easy"


def _recommend_tools(
    qtype: str,
    years: list[int],
    period_basis: str,
    question: str,
) -> list[str]:
    """Recommend tool call sequence based on question type."""
    tools: list[str] = []

    year_range = _YEAR_RANGE_PAT.search(question)

    # Primary data retrieval
    if qtype == "visual":
        tools.extend(["grep_corpus", "get_file_structure"])
    elif qtype == "multi_value" and year_range:
        tools.extend(["get_time_series", "search_ledger"])
    elif len(years) >= 3 or (year_range and int(year_range.group(2)) - int(year_range.group(1)) >= 2):
        tools.extend(["get_time_series", "search_ledger"])
    elif len(years) == 2:
        tools.extend(["search_ledger", "extract_values"])
    else:
        tools.extend(["search_ledger", "extract_values"])

    # Computation needs
    if qtype in ("growth_rate", "ratio", "comparison", "aggregation", "statistical"):
        tools.append("compute_expression")

    # External data
    if re.search(r"\b(CPI|inflation|real\s+dollar)", question, re.I):
        tools.append("get_cpi_index")
    if re.search(r"\b(exchange\s+rate|foreign\s+currency)", question, re.I):
        tools.append("get_exchange_rate")
    if period_basis == "fiscal":
        tools.append("get_fiscal_year_bounds")

    # Always verify
    tools.append("verify_answer")

    # Deduplicate preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for t in tools:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def _generate_warnings(
    qtype: str,
    years: list[int],
    period_basis: str,
    question: str,
) -> list[str]:
    """Generate warnings about potential pitfalls."""
    warnings: list[str] = []

    # Period basis ambiguity
    if period_basis == "unknown" and years:
        warnings.append("No explicit fiscal/calendar designation -- verify period_basis against source table")
    if re.search(r"\bcalendar\b", question, re.I):
        warnings.append("Question mentions calendar year -- verify period_basis='calendar' in search_ledger")
    if years and any(y < 1977 for y in years) and period_basis == "fiscal":
        warnings.append("Pre-1977 fiscal years run Jul-Jun (not Oct-Sep) -- verify fiscal year bounds")

    # Unit traps
    if re.search(r"\b(total|net|gross)\b", question, re.I) and qtype != "direct_lookup":
        warnings.append("'Total' row may already include sub-items -- do not double-count")
    if re.search(r"\b(million|billion|thousand)\b", question, re.I):
        warnings.append("Explicit unit scale mentioned -- verify source table units match before computing")

    # Year range traps
    year_range = _YEAR_RANGE_PAT.search(question)
    if year_range:
        y1, y2 = int(year_range.group(1)), int(year_range.group(2))
        if y2 - y1 > 20:
            warnings.append(f"Large year range ({y1}-{y2}) -- data may span multiple tables with different units")

    # Visual questions
    if qtype == "visual":
        warnings.append("Visual/page questions may require raw corpus text -- structured DB may not contain layout info")

    # Statistical functions
    if qtype == "statistical":
        warnings.append("Statistical computation -- use compute_expression with the appropriate function (theil_index, geometric_mean, etc.)")

    # Historical events
    if _HISTORICAL_EVENTS.search(question):
        warnings.append("Question references historical event -- may need to map event to specific years")

    # Fiscal month vs fiscal year
    if re.search(r"\bfiscal\s+month\b", question, re.I):
        warnings.append("'Fiscal month' mentioned -- this refers to monthly data within fiscal year periods, use monthly period_basis")

    return warnings


def classify(question: str) -> dict[str, Any]:
    """Classify a question and return structured metadata.

    Args:
        question: The question string to classify.

    Returns:
        Dict with keys: type, metrics, years, period_basis, output_unit,
        requires_computation, complexity, recommended_tools, warnings.
    """
    qtype = _detect_type(question)
    years = _extract_years(question)
    period_basis = _detect_period_basis(question)
    output_unit = _extract_output_unit(question)

    requires_computation = qtype in (
        "comparison", "aggregation", "ratio", "growth_rate", "statistical",
    )

    complexity = _assess_complexity(qtype, years, question)
    recommended_tools = _recommend_tools(qtype, years, period_basis, question)
    warnings = _generate_warnings(qtype, years, period_basis, question)
    metrics = _extract_metrics(question)

    return {
        "type": qtype,
        "metrics": metrics,
        "years": years,
        "period_basis": period_basis,
        "output_unit": output_unit,
        "requires_computation": requires_computation,
        "complexity": complexity,
        "recommended_tools": recommended_tools,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Strategy generator
# ---------------------------------------------------------------------------

_STRATEGY_TEMPLATES: dict[str, str] = {
    "direct_lookup": (
        "This is a direct lookup question. Start with search_ledger using the "
        "exact metric name and year. If the ledger returns a value_scaled field, "
        "that IS the answer -- do not multiply further. Verify units via "
        "get_table_profile on the source table_pk."
    ),
    "comparison": (
        "This is a comparison question requiring two values. Use search_ledger "
        "with years=[Y1, Y2] to fetch both values in one call. Then use "
        "compute_expression to calculate the difference. Watch for unit "
        "mismatches between periods."
    ),
    "aggregation": (
        "This is an aggregation question. If summing across years, use "
        "get_time_series to fetch the full range, then compute_expression "
        "with sum(). If the question asks for a 'total' row for a single year, "
        "that is a direct lookup -- the table already has it."
    ),
    "ratio": (
        "This is a ratio/percentage question. Fetch both the numerator and "
        "denominator values via search_ledger, then use compute_expression "
        "for the division. Ensure both values share the same unit scale."
    ),
    "growth_rate": (
        "This is a growth rate question. Fetch the start and end values, then "
        "use compute_expression. For YoY: (end - start) / start * 100. "
        "For CAGR: use cagr(start_value, end_value, n_years). Verify the "
        "formula matches what the question asks."
    ),
    "statistical": (
        "This is a statistical computation question. Fetch the data series via "
        "get_time_series, then use compute_expression with the appropriate "
        "function (theil_index, geometric_mean, stdev, correlation, etc.). "
        "Pass all values as arguments to the function."
    ),
    "multi_value": (
        "This question expects multiple values (a list). Use get_time_series "
        "for contiguous year ranges or get_multi_year_series for specific years. "
        "Format the output as a comma-separated list of values in chronological "
        "order."
    ),
    "visual": (
        "This is a visual/page-layout question. Structured DB queries will NOT "
        "help. Use grep_corpus to find the raw text from the specific page. "
        "Use get_file_structure to identify which bulletin file to search. "
        "Parse the raw text manually to count features."
    ),
    "temporal": (
        "This is a temporal/trend question. Use get_time_series to fetch the "
        "full time range. Analyze the series for the requested pattern (trend, "
        "peak, trough, inflection point)."
    ),
    "external_knowledge": (
        "This question requires external reference data. Use get_cpi_index for "
        "inflation adjustment, get_exchange_rate for currency conversion, or "
        "get_fiscal_year_bounds for fiscal period mapping. Fetch the Treasury "
        "data first, then apply the external adjustment."
    ),
}


def get_tool_strategy(classification: dict[str, Any]) -> str:
    """Return a suggested prompt prefix / strategy note for the agent.

    Args:
        classification: Output of classify().

    Returns:
        A strategy string the agent can use as a preamble.
    """
    qtype = classification["type"]
    base = _STRATEGY_TEMPLATES.get(qtype, _STRATEGY_TEMPLATES["direct_lookup"])

    parts = [base]

    # Add year-specific guidance
    years = classification.get("years", [])
    if len(years) == 1:
        parts.append(f"Target year: {years[0]}.")
    elif len(years) == 2:
        parts.append(f"Target years: {years[0]} and {years[1]}.")
    elif len(years) > 2:
        parts.append(f"Year range: {min(years)}-{max(years)} ({len(years)} years).")

    # Period basis
    pb = classification.get("period_basis", "unknown")
    if pb != "unknown":
        parts.append(f"Period basis: {pb}.")

    # Output unit
    unit = classification.get("output_unit")
    if unit:
        parts.append(f"Expected output unit: {unit}.")

    # Warnings
    for w in classification.get("warnings", []):
        parts.append(f"WARNING: {w}")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# CLI / self-test
# ---------------------------------------------------------------------------

def _self_test() -> None:
    """Run against sample questions and print results."""
    samples = [
        "What was the total Individual income taxes receipts for the U.S. Federal Government in calendar year 1953?",
        "Calculate the YoY growth rate in total gross obligations from 1989 to 1990",
        "What is the Theil index of dispersion value of the U.S Treasury Holdings between fiscal years 1961 to 1970",
        "On page 5 of the September 1990 US Treasury Monthly Bulletin, how many local maxima are there",
        "List the total gross U.S federal debt at the end of fiscal month January from 1969 to 1980",
    ]

    for q in samples:
        print(f"\nQ: {q}")
        c = classify(q)
        for k, v in c.items():
            print(f"  {k}: {v}")
        print(f"  STRATEGY: {get_tool_strategy(c)[:120]}...")
        print("-" * 80)


if __name__ == "__main__":
    _self_test()
