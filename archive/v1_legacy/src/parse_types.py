"""Canonical schema types for the ParseSpec pipeline.

Defines enums and a dataclass that downstream stages (retrieval, extraction,
computation) consume.  Every enum uses ``str`` as a mixin so values serialise
directly to JSON strings.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ── Enums ─────────────────────────────────────────────────────────────

class Lane(str, Enum):
    table = "table"
    visual = "visual"
    external_date = "external_date"
    hybrid = "hybrid"
    unknown = "unknown"


class DateResKind(str, Enum):
    direct = "direct"
    relative = "relative"
    event_anchor = "event_anchor"
    historical_anchor = "historical_anchor"
    document_anchor = "document_anchor"
    cross_calendar = "cross_calendar"


class CalendarBasis(str, Enum):
    calendar = "calendar"
    fiscal = "fiscal"
    mixed = "mixed"
    unknown = "unknown"


class ComputeOp(str, Enum):
    none = "none"
    lookup = "lookup"
    sum = "sum"
    difference = "difference"
    absolute_difference = "absolute_difference"
    percent_change = "percent_change"
    ratio = "ratio"
    CAGR = "CAGR"
    OLS = "OLS"
    geometric_mean = "geometric_mean"
    weighted_average = "weighted_average"
    average = "average"
    median = "median"
    min = "min"
    max = "max"
    count_ = "count"
    std_dev = "std_dev"
    CV = "CV"
    correlation = "correlation"
    interpolate = "interpolate"
    kurtosis = "kurtosis"
    skewness = "skewness"
    VaR = "VaR"
    ES = "ES"
    Theil = "Theil"
    Zipf = "Zipf"
    Box_Cox = "Box_Cox"
    HP_filter = "HP_filter"
    exponential_smoothing = "exponential_smoothing"
    Winsorized_range = "Winsorized_range"
    KL_divergence = "KL_divergence"
    Pareto_Hill = "Pareto_Hill"
    log_transform = "log_transform"
    multiply = "multiply"
    divide = "divide"
    sqrt = "sqrt"
    percentile = "percentile"
    inflation_adjustment = "inflation_adjustment"
    exchange_rate_conversion = "exchange_rate_conversion"
    moving_average = "moving_average"
    forecast = "forecast"
    normalize = "normalize"
    z_score = "z_score"
    range = "range"
    other = "other"


class OutputType(str, Enum):
    number = "number"
    percent = "percent"
    ratio = "ratio"
    list = "list"
    text = "text"
    date = "date"


class UnitType(str, Enum):
    millions = "millions"
    billions = "billions"
    trillions = "trillions"
    thousands = "thousands"
    nominal_dollars = "nominal_dollars"
    percent = "percent"
    yen = "yen"
    fine_pounds = "fine_pounds"
    ratio = "ratio"
    count_ = "count"
    years_ = "years"
    other = "other"
    none = "none"


class Rounding(str, Enum):
    nearest_whole = "nearest_whole"
    tenths = "tenths"
    hundredths = "hundredths"
    thousandths = "thousandths"
    dp4 = "4dp"
    dp5 = "5dp"
    dp6 = "6dp"
    none = "none"


class ExternalSource(str, Enum):
    none = "none"
    BLS_CPI = "BLS_CPI"
    FRED = "FRED"
    IMF = "IMF"
    WorldBank = "WorldBank"
    BEA_GDP = "BEA_GDP"
    Treasury_Bulletin = "Treasury_Bulletin"
    historical_event = "historical_event"
    exchange_rate_USD_JPY = "exchange_rate_USD_JPY"
    exchange_rate_USD_GBP = "exchange_rate_USD_GBP"
    exchange_rate_USD_DEM = "exchange_rate_USD_DEM"
    exchange_rate_USD_INR = "exchange_rate_USD_INR"
    exchange_rate_USD_CAD = "exchange_rate_USD_CAD"
    exchange_rate_other = "exchange_rate_other"
    event_date_lookup = "event_date_lookup"


class VisualSubtype(str, Enum):
    none = "none"
    chart_read = "chart_read"
    page_number = "page_number"
    table_image = "table_image"
    count_marks = "count_marks"
    layout_navigation = "layout_navigation"


class RetrievalOp(str, Enum):
    lookup = "lookup"
    filter = "filter"
    join_ = "join"
    page_locate = "page_locate"
    chart_read = "chart_read"
    series_extract = "series_extract"


# ── Dataclass ─────────────────────────────────────────────────────────

@dataclass
class SeriesSpec:
    metric: str = ""
    entity_filter: str = ""
    granularity: str = "annual"


@dataclass
class TimeConstraint:
    start: str = ""
    end: str = ""
    granularity: str = "year"
    note: str = ""


@dataclass
class OutputFormat:
    type: str = "number"
    unit: str = "other"
    rounding: str = "none"
    list_format: str = "single_value"


@dataclass
class VisualRequired:
    needed: bool = False
    subtype: str = "none"


@dataclass
class WorldKnowledgeAnchor:
    needed: bool = False
    phrase: str = ""
    expected_resolution: str = ""


@dataclass
class DocumentAnchor:
    needed: bool = False
    bulletin_date: str = ""
    specific_table: str = ""
    specific_page: str = ""


@dataclass
class ParseSpec:
    """Typed parse specification — backward-compatible with V2 ``parsed`` dict."""

    target_entity: str = ""
    primary_series: list[SeriesSpec] = field(default_factory=list)
    comparison_series: list[SeriesSpec] = field(default_factory=list)
    time_constraints: list[TimeConstraint] = field(default_factory=list)
    date_resolution_kind: str = "direct"
    calendar_basis: str = "unknown"
    retrieval_ops: list[str] = field(default_factory=lambda: ["lookup"])
    compute_ops: list[str] = field(default_factory=lambda: ["none"])
    output_format: OutputFormat = field(default_factory=OutputFormat)
    external_sources: list[str] = field(default_factory=lambda: ["none"])
    visual_required: VisualRequired = field(default_factory=VisualRequired)
    world_knowledge_anchor: WorldKnowledgeAnchor = field(
        default_factory=WorldKnowledgeAnchor
    )
    document_anchor: DocumentAnchor = field(default_factory=DocumentAnchor)
    num_hops: int = 1
    num_tables_needed: int = 1
    confidence: float = 0.9
    notes: list[str] = field(default_factory=list)

    # ── Router flags (V3-only, not in V2 output) ─────────────────────
    needs_cpi: bool = False
    needs_fx: bool = False
    needs_event_resolution: bool = False
    needs_visual: bool = False
    needs_multi_table: bool = False
    compute_family: str = "lookup"

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the same shape as V2 ``parsed`` dict.

        Router-only flags are excluded so downstream stages see the same
        contract they expect from ``parse_v2``.
        """
        d = asdict(self)
        # Remove V3-only router flags
        for key in (
            "needs_cpi", "needs_fx", "needs_event_resolution",
            "needs_visual", "needs_multi_table", "compute_family",
        ):
            d.pop(key, None)
        return d
