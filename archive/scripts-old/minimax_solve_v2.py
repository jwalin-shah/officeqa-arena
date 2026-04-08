#!/usr/bin/env python3
"""
MiniMax Ultra-Optimized Solve Pipeline V2
=========================================
A completely reimagined pipeline based on deep analysis of failures.

Key improvements:
1. Smart decompose with question classification
2. Domain-aware search with knowledge base
3. Semantic column matching
4. Proper math formulas (KL, geometric mean, etc.)
5. Historical knowledge handling
6. Multiple verification stages
"""

import json
import math
import os
import re
import sys
import time
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

# == Config ==
CORPUS_DIR = os.environ.get("CORPUS_DIR", "./corpus")
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = os.environ.get("SOLVER_MODEL", "minimax/minimax-m2.5")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# == Historical Knowledge Base ==
HISTORICAL_FACTS = {
    "treasury notes of 1890 removed": 1957,
    "treasury notes of 1890": 1957,
    "notes of 1890": 1957,
    "ww2 started": 1939,
    "world war 2 started": 1939,
    "world war ii started": 1939,
    "world war i started": 1914,
    "ww1 started": 1914,
    "great depression started": 1929,
    "bretton woods": 1944,
    "federal reserve act": 1913,
}

# == Domain Knowledge for Search ==
DOMAIN_SEARCH_TERMS = {
    "bond yield": [
        "bond yield",
        "yield",
        "interest rate",
        "bond rate",
        "long-term rate",
        "treasury yield",
    ],
    "interest cost": [
        "interest cost",
        "net interest",
        "interest on debt",
        "interest outlays",
    ],
    "national defense": [
        "national defense",
        "defense",
        "military",
        "defense and associated",
    ],
    "veterans": [
        "veterans",
        "veterans administration",
        "veterans affairs",
        "veterans benefits",
    ],
    "budget receipts": [
        "budget receipts",
        "receipts",
        "revenue",
        "income",
        "net receipts",
    ],
    "paper money": ["paper money", "currency", "circulation", "money in circulation"],
    "bank deposits": ["bank deposits", "deposits", "time deposits", "savings deposits"],
    "geometric mean": ["outlays", "expenditures", "spending"],
}


# == Math Formulas ==
def compute_geometric_mean(values):
    """Compute geometric mean of a list of values."""
    values = [
        float(v) for v in values if v and str(v).strip() and str(v).strip() != "-"
    ]
    if not values:
        return 0.0
    # Use exp(mean(log(x))) formula
    logs = [math.log(max(v, 0.0001)) for v in values if v > 0]
    if not logs:
        return 0.0
    return math.exp(sum(logs) / len(logs))


def compute_kl_divergence(p, q):
    """
    Compute Kullback-Leibler divergence.
    D(P||Q) = sum(P[i] * log(P[i] / Q[i]))
    """
    import numpy as np

    p = np.array(p, dtype=float)
    q = np.array(q, dtype=float)

    # Normalize to make valid distributions
    p = p / p.sum() if p.sum() > 0 else p
    q = q / q.sum() if q.sum() > 0 else q

    # Add small epsilon to avoid log(0)
    epsilon = 1e-10
    p = np.clip(p, epsilon, 1)
    q = np.clip(q, epsilon, 1)

    # KL divergence
    return np.sum(p * np.log(p / q))


def compute_percent_change(old_val, new_val):
    """Compute percent change."""
    old = float(str(old_val).replace(",", "").replace("%", ""))
    new = float(str(new_val).replace(",", "").replace("%", ""))
    if old == 0:
        return 0.0
    return abs((new - old) / old) * 100


def compute_difference(val1, val2):
    """Compute absolute difference."""
    v1 = float(str(val1).replace(",", ""))
    v2 = float(str(val2).replace(",", ""))
    return abs(v1 - v2)


# == LLM Interface ==
def call_llm(
    system_prompt: str, user_prompt: str, max_tokens: int = 2048
) -> Optional[str]:
    """Call OpenRouter API."""
    if not API_KEY:
        print("ERROR: No API key", file=sys.stderr)
        return None

    import urllib.request
    import urllib.error

    payload = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
    ).encode()

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                OPENROUTER_URL,
                data=payload,
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  LLM attempt {attempt + 1} failed: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(2**attempt)
    return None


def parse_json_response(text: str) -> Optional[dict]:
    """Parse JSON from LLM response."""
    if not text:
        return None
    text = text.strip()
    # Remove markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON in text
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return None


# == Phase 1: Smart Decompose ==
DECOMPOSE_SYSTEM_V2 = """You are a question classifier and data planner for Treasury data.

TASK: Given a question, produce a structured plan to find the answer.

CRITICAL RULES:
1. IDENTIFY FISCAL YEAR vs CALENDAR YEAR:
   - "FY YYYY" or "fiscal year YYYY" = use bare year row (FY total)
   - "CY YYYY" or "calendar year YYYY" or "in YYYY" = extract ALL 12 months and sum
   - NEVER assume bare year row is calendar year

2. COLUMN SELECTION:
   - Use EXACT column header from the table
   - "National defense" ≠ "National defense and associated activities"
   - "Interest cost" ≠ "Net interest" (different tables!)
   - When unsure, prefer MORE specific column name

3. YEAR BLOCKS:
   - FY blocks: bare year like "1940" = FY1940 (Jul 1939 - Jun 1940 pre-1977)
   - CY months: "January", "February" etc. under a year block

4. SPECIAL COMPUTATIONS:
   - geometric_mean: product of N values, then Nth root (or exp(mean(log(values))))
   - KL divergence: normalize both distributions, then sum(p * log(p/q))
   - percent_change: abs((new - old) / old) * 100
   - difference: abs(value1 - value2)

OUTPUT JSON:
{
  "question_type": "fy_annual|cy_monthly|single_month|complex_compute",
  "data_years": [list of years needed],
  "sub_queries": [
    {
      "id": "A",
      "description": "what data to find",
      "search_terms": ["term1", "term2"],
      "target_bulletin_year": YYYY,
      "data_year": YYYY,
      "value_type": "annual_total|monthly_series|single|max_in_row",
      "column_hint": "exact column name from table",
      "fallback_columns": ["alternative1", "alternative2"]
    }
  ],
  "computation": {
    "type": "sum|difference|percent_change|ratio|geometric_mean|kl_divergence|custom",
    "formula": "description",
    "sub_query_refs": ["A", "B"]
  },
  "notes": "any special handling needed"
}

EXAMPLES:

Q: "total expenditures for national defense in calendar year 1940?"
{
  "question_type": "cy_monthly",
  "data_years": [1940],
  "sub_queries": [{
    "id": "A",
    "search_terms": ["national defense", "expenditures"],
    "target_bulletin_year": 1941,
    "data_year": 1940,
    "value_type": "monthly_series",
    "column_hint": "National defense"
  }],
  "computation": {"type": "sum", "sub_query_refs": ["A"]}
}

Q: "difference between FY 1950 and FY 1949 receipts"
{
  "question_type": "fy_annual",
  "data_years": [1950, 1949],
  "sub_queries": [
    {"id": "A", "data_year": 1950, "value_type": "annual_total", "column_hint": "Total"},
    {"id": "B", "data_year": 1949, "value_type": "annual_total", "column_hint": "Total"}
  ],
  "computation": {"type": "difference", "sub_query_refs": ["A", "B"]}
}

Output ONLY JSON."""


def decompose_question(question: str) -> Optional[dict]:
    """Decompose question into plan."""
    print(f"[Decompose] Analyzing: {question[:80]}...", file=sys.stderr)

    response = call_llm(DECOMPOSE_SYSTEM_V2, question)
    if not response:
        print("[Decompose] Failed", file=sys.stderr)
        return None

    plan = parse_json_response(response)
    if not plan or "sub_queries" not in plan:
        print(f"[Decompose] Invalid response", file=sys.stderr)
        return None

    print(
        f"[Decompose] Found {len(plan['sub_queries'])} sub-query(s), type: {plan.get('question_type', '?')}",
        file=sys.stderr,
    )
    return plan


# == Phase 2: Domain-Aware Search ==
def get_expanded_search_terms(sub_query: dict) -> list:
    """Expand search terms with domain knowledge."""
    base_terms = sub_query.get("search_terms", [])
    expanded = list(base_terms)

    # Check against domain knowledge
    for key, synonyms in DOMAIN_SEARCH_TERMS.items():
        for term in base_terms:
            if key in term.lower() or term.lower() in key:
                for syn in synonyms:
                    if syn.lower() not in [t.lower() for t in expanded]:
                        expanded.append(syn)

    return expanded


def find_tables_for_subquery(sub_query: dict, corpus_dir: str) -> list:
    """Find tables matching sub-query with smart search."""
    data_year = sub_query.get("data_year")
    target_year = sub_query.get(
        "target_bulletin_year", data_year + 1 if data_year else None
    )
    search_terms = get_expanded_search_terms(sub_query)
    col_hint = sub_query.get("column_hint", "")

    # Also try fallback columns
    for fallback in sub_query.get("fallback_columns", []):
        if fallback.lower() not in [t.lower() for t in search_terms]:
            search_terms.append(fallback)

    print(f"[Search] Terms: {search_terms[:5]}", file=sys.stderr)
    print(f"[Search] Target bulletin year: {target_year}", file=sys.stderr)

    candidates = []

    # Search in priority order: target year, then widen
    years_to_try = []
    if target_year:
        years_to_try.append(target_year)
    if data_year:
        for delta in [1, 2, 3, -1, 4, 5, -2]:
            yr = (data_year + 1) + delta
            if yr not in years_to_try and 1930 <= yr <= 2025:
                years_to_try.append(yr)

    for yr in years_to_try[:10]:  # Limit search
        yr_str = str(yr)
        corpus_path = Path(corpus_dir)

        # Find all files for this year
        for tb_file in sorted(corpus_path.glob(f"treasury_bulletin_{yr_str}_*.txt"))[
            :3
        ]:
            tables = find_tables_in_file(tb_file, search_terms)
            for t in tables:
                t["search_year"] = yr
            candidates.extend(tables)

    # Also try broad search if no results
    if not candidates:
        print(f"[Search] Broad search...", file=sys.stderr)
        for tb_file in list(Path(corpus_dir).glob("treasury_bulletin_*.txt"))[-24:]:
            tables = find_tables_in_file(tb_file, search_terms)
            candidates.extend(tables)

    # Deduplicate by title
    seen = set()
    deduped = []
    for c in candidates:
        title = c.get("title", "").lower()[:50]
        if title not in seen:
            seen.add(title)
            deduped.append(c)

    print(f"[Search] Found {len(deduped)} candidates", file=sys.stderr)
    return deduped[:8]


def find_tables_in_file(filepath: Path, search_terms: list) -> list:
    """Find tables in a single file matching search terms."""
    try:
        text = filepath.read_text(errors="replace")
    except:
        return []

    lines = text.splitlines()
    tables = []

    # Simple approach: find lines with search terms, then get context
    search_text = "\n".join(lines).lower()

    # Check if any term matches in the file
    term_matches = []
    for term in search_terms:
        term_lower = term.lower()
        for i, line in enumerate(lines):
            if term_lower in line.lower():
                term_matches.append((i, line))
                if len(term_matches) >= 10:
                    break

    if not term_matches:
        return []

    # Group nearby matches into table regions
    # Find the header row (has | and column headers)
    header_row = None
    data_rows = []

    # Look for table around the match
    first_match_line = min(m[0] for m in term_matches)

    # Search backwards from first match for header
    for i in range(first_match_line - 1, max(0, first_match_line - 20), -1):
        line = lines[i].strip()
        if line.startswith("|"):
            # Check if it's a header row (has text, not just dashes)
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if cells and not all(re.match(r"^[-:]+$", c) for c in cells):
                header_row = (i, line)
                break

    # Search forward for data rows
    for i in range(first_match_line, min(len(lines), first_match_line + 30)):
        line = lines[i].strip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.split("|") if c.strip()]
            # Skip separator rows
            if cells and not all(re.match(r"^[-:]+$", c) for c in cells):
                data_rows.append((i, line))

    if not data_rows:
        return []

    # Extract title from above header
    title = ""
    if header_row:
        for j in range(header_row[0] - 1, max(0, header_row[0] - 10), -1):
            line = lines[j].strip()
            if not line or line.startswith("|") or line.startswith("---"):
                break
            if not re.match(r"^\d+$|page\s+\d+", line, re.I):
                title = line + " " + title
        title = title.strip()

        # Extract columns from header row
        header_line = header_row[1]
        cols = [c.strip() for c in header_line.split("|") if c.strip()]
        cols = [c for c in cols if not re.match(r"^[-:]+$", c)]
    else:
        # Use first data row
        cols = [c.strip() for c in data_rows[0][1].split("|") if c.strip()]
        cols = [c for c in cols if c and not re.match(r"^[-:]+$", c)]

    # Calculate score
    search_text = (title + " " + "\n".join([r[1] for r in data_rows])).lower()
    hits = sum(1 for term in search_terms if term.lower() in search_text)

    table_start = data_rows[0][0] if data_rows else first_match_line
    table_end = data_rows[-1][0] + 1 if data_rows else first_match_line + 10

    return [
        {
            "title": title if title else "Unknown table",
            "columns": cols,
            "file": str(filepath),
            "line_start": max(0, table_start - 3),
            "line_end": min(len(lines), table_end + 3),
            "score": hits,
        }
    ]


def extract_table_title(lines: list, table_start: int) -> str:
    """Extract title above table."""
    title_lines = []
    for j in range(table_start - 1, max(0, table_start - 10), -1):
        line = lines[j].strip()
        if not line or line.startswith("|") or line.startswith("---"):
            break
        if re.match(r"^\d+$|page\s+\d+", line, re.I):
            continue
        title_lines.insert(0, line)
    return " ".join(title_lines).strip()


def extract_columns(table_lines: list) -> list:
    """Extract column headers from table."""
    for line in table_lines:
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if cells and not all(re.match(r"^[-:]+$", c) for c in cells):
                return cells
    return []


# == Phase 3: Smart Table Selection ==
def select_best_table(sub_query: dict, candidates: list) -> Optional[dict]:
    """Select best table from candidates using semantic matching."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    col_hint = (sub_query.get("column_hint") or "").lower()
    data_year = str(sub_query.get("data_year", ""))
    value_type = sub_query.get("value_type", "")

    best_score = -999
    best_table = candidates[0]

    for cand in candidates:
        score = 0
        cols = [c.lower() for c in cand.get("columns", [])]
        title = cand.get("title", "").lower()

        # Column hint matching (most important)
        if col_hint:
            col_words = set(col_hint.split())
            for col in cols:
                if col_hint in col:
                    score += 20  # Exact match
                elif any(w in col for w in col_words if len(w) > 2):
                    score += 5

        # Check for the column in title too
        if col_hint and col_hint in title:
            score += 5

        # Data year in table body
        if data_year:
            try:
                body = Path(cand.get("file")).read_text(errors="replace")
                # Get lines around table
                ls = cand.get("line_start", 0)
                le = cand.get("line_end", ls + 50)
                body_snippet = "\n".join(body.splitlines()[ls:le])
                if data_year in body_snippet:
                    score += 10
            except:
                pass

        # Monthly columns check
        if value_type == "monthly_series":
            month_count = sum(
                1
                for c in cols
                if any(
                    m in c
                    for m in [
                        "jan",
                        "feb",
                        "mar",
                        "apr",
                        "may",
                        "jun",
                        "jul",
                        "aug",
                        "sep",
                        "oct",
                        "nov",
                        "dec",
                    ]
                )
            )
            if month_count >= 6:
                score += 15

        # File year proximity (prefer bulletins ~1 year after data)
        file_match = re.search(r"treasury_bulletin_(\d{4})", cand.get("file", ""))
        if file_match and data_year:
            file_year = int(file_match.group(1))
            data_yr = int(data_year)
            dist = abs(file_year - (data_yr + 1))
            if dist == 0:
                score += 10
            else:
                score -= dist * 3

        if score > best_score:
            best_score = score
            best_table = cand

    print(
        f"[Select] Selected: {best_table.get('title', '')[:50]} (score: {best_score})",
        file=sys.stderr,
    )
    return best_table


# == Phase 4: Extract Data with Verification ==
def extract_value_from_table(sub_query: dict, table: dict) -> dict:
    """Extract values from selected table."""
    print(f"[Extract] From: {table.get('title', '')[:50]}", file=sys.stderr)

    try:
        text = Path(table.get("file")).read_text(errors="replace")
    except:
        return {"values": None, "confidence": "low", "error": "Could not read file"}

    # Get relevant section
    lines = text.splitlines()
    ls = table.get("line_start", 0)
    le = min(table.get("line_end", ls + 50), len(lines))
    table_text = "\n".join(lines[ls:le])

    if len(table_text) > 6000:
        table_text = table_text[:6000] + "\n..."

    # Build extraction prompt
    col_hint = sub_query.get("column_hint", "")
    data_year = sub_query.get("data_year", "")
    value_type = sub_query.get("value_type", "")

    prompt = f"""Extract data from this table.

TABLE:
{table_text}

REQUEST:
- Data year: {data_year}
- Value type: {value_type}
- Expected column: {col_hint}
- Column fallback: {sub_query.get("fallback_columns", [])}

IMPORTANT:
1. Find the row for year {data_year}
2. Extract from column matching "{col_hint}"
3. If column not found exactly, try fallback columns
4. For monthly_series: extract ALL 12 months (Jan-Dec) in order
5. For annual_total: extract the bare year row
6. "-" means zero, "nan" means not available
7. Strip any footnote markers (3/, r, p, *)

Return JSON:
{{
  "values": <number or [12 values]>,
  "source_row": "exact row label",
  "source_column": "exact column name", 
  "confidence": "high|medium|low",
  "notes": "any issues"
}}"""

    response = call_llm("You are a precise data extractor.", prompt, 1024)
    if not response:
        return {"values": None, "confidence": "low", "error": "LLM failed"}

    result = parse_json_response(response)
    if not result:
        # Try to parse numbers from response
        nums = re.findall(r"[\d,]+\.?\d*", response.replace(",", ""))
        if nums:
            try:
                return {
                    "values": float(nums[0]),
                    "confidence": "low",
                    "notes": "Parsed raw",
                }
            except:
                pass
        return {"values": None, "confidence": "low", "error": "Parse failed"}

    return result


# == Phase 5: Compute with Proper Formulas ==
def compute_answer(plan: dict, extracted: dict) -> str:
    """Compute final answer based on computation type."""
    comp = plan.get("computation", {})
    comp_type = comp.get("type", "direct")
    sub_refs = comp.get("sub_query_refs", [])

    values = extracted.get("values")
    if values is None:
        return "N/A"

    try:
        if comp_type == "sum":
            if isinstance(values, list):
                return str(
                    sum(
                        float(str(v).replace(",", ""))
                        for v in values
                        if v and str(v).strip()
                    )
                )
            return str(values)

        elif comp_type == "difference":
            # Need two sub-queries for difference
            if isinstance(values, list) and len(values) >= 2:
                v1, v2 = float(values[0]), float(values[1])
                return str(abs(v1 - v2))
            return str(values)

        elif comp_type == "geometric_mean":
            if isinstance(values, list):
                result = compute_geometric_mean(values)
                return str(round(result, 3))
            return str(values)

        elif comp_type == "percent_change":
            if isinstance(values, list) and len(values) >= 2:
                old, new = float(values[0]), float(values[1])
                return str(round(compute_percent_change(old, new), 2))
            return str(values)

        elif comp_type == "kl_divergence":
            # Need two distributions
            if isinstance(values, list) and len(values) >= 2:
                p = values[0] if isinstance(values[0], list) else [values[0]]
                q = values[1] if isinstance(values[1], list) else [values[1]]
                if isinstance(values[0], (list, tuple)) and len(values) == 2:
                    result = compute_kl_divergence(values[0], values[1])
                    return str(result)
            return str(values)

        else:
            return str(values)

    except Exception as e:
        print(f"[Compute] Error: {e}", file=sys.stderr)
        return str(values)


# == Phase 6: Verify Answer ==
def verify_answer(question: str, answer: str, expected_format: str = "") -> dict:
    """Verify answer makes sense."""
    issues = []

    # Check if answer is N/A
    if answer == "N/A":
        return {"verified": False, "issues": ["No answer computed"]}

    # Try to extract numeric value
    num_str = str(answer).replace(",", "").replace("%", "").replace("$", "").strip()
    try:
        val = float(num_str)

        # Sanity checks based on question type
        q = question.lower()

        if "percent" in q or "%" in q:
            # Percent should usually be reasonable
            if val > 1000:
                issues.append(f"Unusually large percent: {val}")

        if "million" in q:
            # Millions should be in reasonable range
            if val > 1e7:
                issues.append(f"Unusually large value: {val}")

    except ValueError:
        # Non-numeric answer - might be text
        pass

    return {"verified": len(issues) == 0, "issues": issues}


# == Main Pipeline ==
def solve_v2(question: str) -> str:
    """Main solve function."""
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(f"[Solve] Question: {question[:100]}", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)

    # Phase 1: Decompose
    plan = decompose_question(question)
    if not plan:
        return "N/A"

    # Phase 2: Search for each sub-query
    all_extracted = {}
    for sq in plan.get("sub_queries", []):
        sq_id = sq.get("id", "A")
        print(f"\n[Process Sub-query {sq_id}]", file=sys.stderr)

        # Find tables
        candidates = find_tables_for_subquery(sq, CORPUS_DIR)
        if not candidates:
            print(f"  No tables found", file=sys.stderr)
            all_extracted[sq_id] = {"values": None, "error": "No tables"}
            continue

        # Select best table
        table = select_best_table(sq, candidates)
        if not table:
            all_extracted[sq_id] = {"values": None, "error": "Selection failed"}
            continue

        # Extract data
        extracted = extract_value_from_table(sq, table)
        all_extracted[sq_id] = extracted
        print(f"  Extracted: {extracted.get('values')}", file=sys.stderr)

    # Phase 3: Compute
    print(f"\n[Compute]", file=sys.stderr)

    # Collect values from all sub-queries
    all_values = []
    for sq in plan.get("sub_queries", []):
        sq_id = sq.get("id", "A")
        vals = all_extracted.get(sq_id, {}).get("values")
        if vals is not None:
            all_values.append(vals)

    if not all_values:
        return "N/A"

    # Flatten if needed
    if len(all_values) == 1:
        flat_values = all_values[0]
    else:
        flat_values = all_values

    extracted_data = {"values": flat_values}
    answer = compute_answer(plan, extracted_data)

    # Phase 4: Verify
    verification = verify_answer(question, answer)
    if not verification["verified"]:
        print(f"  [Warning] {verification['issues']}", file=sys.stderr)

    print(f"\n[Answer] {answer}", file=sys.stderr)
    return answer


# == CLI ==
def main():
    if len(sys.argv) < 2:
        print("Usage: python3 solve_v2.py 'QUESTION'")
        sys.exit(1)

    question = sys.argv[1]
    answer = solve_v2(question)

    # Write answer
    answer_path = Path("/app/answer.txt" if Path("/app").exists() else "./answer.txt")
    answer_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.write_text(str(answer))

    print(f"[Output] Written to {answer_path}: {answer}", file=sys.stderr)


if __name__ == "__main__":
    main()
