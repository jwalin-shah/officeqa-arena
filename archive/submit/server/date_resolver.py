"""Date resolver for OfficeQA Arena.

Resolves indirect date references (event anchors, historical anchors)
to normalized dates before Treasury data retrieval.

Resolution strategy: web search only (no lookup tables — prohibited by rules).
Uses DuckDuckGo + Wikipedia API for event→date resolution.

Usage:
    from server.date_resolver import resolve_date, resolve_from_parse

    result = resolve_date("the year Black Monday happened")
    # -> {"original_phrase": "...", "resolved_year": 1987, ...}
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any


def _fetch_json(url: str, timeout: int = 8) -> dict:
    """Fetch JSON from a URL, return empty dict on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read(30720).decode("utf-8", errors="replace"))
    except Exception:
        return {}


def _fetch_text(url: str, timeout: int = 8) -> str:
    """Fetch text from a URL, return empty string on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(30720).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_date_from_text(text: str) -> dict | None:
    """Extract the most likely date from a block of text.

    Returns dict with resolved_date, resolved_year, granularity, or None.
    """
    if not text:
        return None

    month_names = {
        "January": "01", "February": "02", "March": "03", "April": "04",
        "May": "05", "June": "06", "July": "07", "August": "08",
        "September": "09", "October": "10", "November": "11", "December": "12",
    }

    # Full date: "October 19, 1987" or "19 October 1987"
    m1 = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        text,
    )
    if m1:
        mm = month_names[m1.group(1)]
        dd = m1.group(2).zfill(2)
        yyyy = m1.group(3)
        return {
            "resolved_date": f"{yyyy}-{mm}-{dd}",
            "resolved_year": int(yyyy),
            "granularity": "day",
        }

    # Day-first: "19 October 1987"
    m2 = re.search(
        r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        text,
    )
    if m2:
        dd = m2.group(1).zfill(2)
        mm = month_names[m2.group(2)]
        yyyy = m2.group(3)
        return {
            "resolved_date": f"{yyyy}-{mm}-{dd}",
            "resolved_year": int(yyyy),
            "granularity": "day",
        }

    # ISO date: "1987-10-19"
    m3 = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m3:
        return {
            "resolved_date": m3.group(0),
            "resolved_year": int(m3.group(1)),
            "granularity": "day",
        }

    # Month + year: "October 1987"
    m4 = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        text,
    )
    if m4:
        mm = month_names[m4.group(1)]
        yyyy = m4.group(2)
        return {
            "resolved_date": f"{yyyy}-{mm}-01",
            "resolved_year": int(yyyy),
            "granularity": "month",
        }

    # Year only (take the first 4-digit year in a reasonable range)
    m5 = re.search(r"\b(1[89]\d{2}|20[0-2]\d)\b", text)
    if m5:
        yyyy = m5.group(1)
        return {
            "resolved_date": f"{yyyy}-01-01",
            "resolved_year": int(yyyy),
            "granularity": "year",
        }

    return None


def _get_wiki_extract(title: str) -> str:
    """Get the intro extract of a Wikipedia article by title."""
    url = (
        f"https://en.wikipedia.org/w/api.php?action=query"
        f"&titles={urllib.parse.quote(title)}"
        f"&prop=extracts&exintro=1&explaintext=1&format=json"
    )
    data = _fetch_json(url)
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return ""
    page = next(iter(pages.values()))
    return page.get("extract", "")


def _resolve_via_wikipedia(phrase: str) -> dict | None:
    """Search Wikipedia for event date resolution.

    Uses Wikipedia search API to find relevant articles, then extracts
    dates from the intro paragraphs. Tries multiple results to handle
    disambiguation pages.
    """
    clean = re.sub(r"[''\"\".,;:!?()]+", "", phrase).strip()
    query = urllib.parse.quote(clean)

    # Use the full search API (better than opensearch for finding specific events)
    search_url = (
        f"https://en.wikipedia.org/w/api.php?action=query&list=search"
        f"&srsearch={query}&srlimit=5&format=json"
    )
    search_data = _fetch_json(search_url)
    results = search_data.get("query", {}).get("search", [])
    if not results:
        return None

    # Try each search result until we find a date
    for result in results:
        title = result.get("title", "")
        extract = _get_wiki_extract(title)

        if not extract:
            continue

        # Skip disambiguation pages
        if "may refer to:" in extract.lower() or "can refer to:" in extract.lower():
            continue

        date_info = _extract_date_from_text(extract)
        if date_info:
            return {
                "original_phrase": phrase,
                "resolved_date": date_info["resolved_date"],
                "resolved_year": date_info["resolved_year"],
                "granularity": date_info["granularity"],
                "source": "wikipedia",
                "confidence": 0.90,
                "note": f"From Wikipedia '{title}': {extract[:200]}",
            }

    return None


def _resolve_via_ddg(phrase: str) -> dict | None:
    """Search DuckDuckGo instant answer API for date resolution."""
    clean = re.sub(r"[''\"\".,;:!?()]+", "", phrase).strip()
    query = urllib.parse.quote(f"{clean} date")

    url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1"
    data = _fetch_json(url)
    if not data:
        return None

    text = " ".join([
        data.get("Abstract", ""),
        data.get("Answer", ""),
        data.get("AbstractText", ""),
        data.get("Definition", ""),
    ]).strip()

    if not text:
        # Try related topics
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict):
                text += " " + topic.get("Text", "")

    if not text:
        return None

    date_info = _extract_date_from_text(text)
    if date_info:
        return {
            "original_phrase": phrase,
            "resolved_date": date_info["resolved_date"],
            "resolved_year": date_info["resolved_year"],
            "granularity": date_info["granularity"],
            "source": "web_ddg",
            "confidence": 0.80,
            "note": f"From DuckDuckGo: {text[:200]}",
        }

    return None


def resolve_date(phrase: str) -> dict:
    """Resolve a date phrase to a normalized date via web search.

    Tries Wikipedia first (higher quality), then DuckDuckGo.
    No lookup tables — all resolution is dynamic.

    Args:
        phrase: Natural language date reference

    Returns:
        Dict with: original_phrase, resolved_date, resolved_year,
                    granularity, source, confidence, note
    """
    # Strategy 1: Wikipedia (best for historical events)
    result = _resolve_via_wikipedia(phrase)
    if result:
        return result

    # Strategy 2: DuckDuckGo instant answer
    result = _resolve_via_ddg(phrase)
    if result:
        return result

    # Unresolved
    return {
        "original_phrase": phrase,
        "resolved_date": None,
        "resolved_year": None,
        "granularity": None,
        "source": "unresolved",
        "confidence": 0.0,
        "note": "Web search could not resolve this date reference.",
    }


def resolve_from_parse(parse_spec: dict) -> dict | None:
    """Resolve dates from a ParseSpec V2 object.

    Checks world_knowledge_anchor and date_resolution_kind.
    Returns resolved date dict, or None if no resolution needed.
    """
    date_kind = parse_spec.get("date_resolution_kind", "direct")
    wk = parse_spec.get("world_knowledge_anchor", {})
    needs_resolution = (
        date_kind in ("event_anchor", "historical_anchor")
        or (isinstance(wk, dict) and wk.get("needed"))
    )

    if not needs_resolution:
        return None

    if isinstance(wk, dict) and wk.get("phrase"):
        phrase = wk["phrase"]
        result = resolve_date(phrase)
        if result.get("resolved_year"):
            return result

        # If web search failed, try using the LLM's suggested resolution
        expected = wk.get("expected_resolution", "")
        if expected:
            yr_match = re.search(r"\b(1[89]\d{2}|20[0-2]\d)\b", expected)
            if yr_match:
                year = int(yr_match.group(1))
                return {
                    "original_phrase": phrase,
                    "resolved_date": f"{year}-01-01",
                    "resolved_year": year,
                    "granularity": "year",
                    "source": "llm_suggestion",
                    "confidence": 0.65,
                    "note": f"Web search failed. Using LLM suggestion: {expected}",
                }

    return None


def resolve_all_dates(parse_spec: dict) -> list[dict]:
    """Resolve all date references in a ParseSpec.

    Returns list of resolved dates (may be empty).
    """
    results = []

    # Primary: world_knowledge_anchor
    primary = resolve_from_parse(parse_spec)
    if primary:
        results.append(primary)

    # Secondary: scan time_constraints notes for event references
    event_keywords = [
        "war", "invasion", "crash", "crisis", "pandemic", "declaration",
        "bailout", "recession", "bubble", "monday", "attack", "merged",
    ]
    for tc in parse_spec.get("time_constraints", []):
        note = tc.get("note", "").lower()
        if any(kw in note for kw in event_keywords):
            result = resolve_date(tc["note"])
            if result.get("resolved_year") and not any(
                r.get("resolved_date") == result["resolved_date"] for r in results
            ):
                results.append(result)

    return results
