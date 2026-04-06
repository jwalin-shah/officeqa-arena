#!/usr/bin/env python3
"""
MiniMax Ultra-Optimized Solve Pipeline V3
=========================================
Step-by-step approach:
1. Find tables (just find them, don't extract)
2. Select table (pick best)
3. Extract data
4. Compute
5. Verify
"""

import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

# == Config ==
CORPUS_DIR = os.environ.get("CORPUS_DIR", "./corpus")
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = os.environ.get("SOLVER_MODEL", "minimax/minimax-m2.5")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# == Math Formulas ==
def compute_geometric_mean(values):
    values = [
        float(v)
        for v in values
        if v and str(v).strip() and str(v).strip() not in ["-", "nan", ""]
    ]
    if not values:
        return 0.0
    logs = [math.log(max(v, 0.0001)) for v in values if v > 0]
    if not logs:
        return 0.0
    return math.exp(sum(logs) / len(logs))


def compute_kl_divergence(p, q):
    import numpy as np

    p = np.array(p, dtype=float)
    q = np.array(q, dtype=float)
    p = p / p.sum() if p.sum() > 0 else p
    q = q / q.sum() if q.sum() > 0 else q
    epsilon = 1e-10
    p = np.clip(p, epsilon, 1)
    q = np.clip(q, epsilon, 1)
    return float(np.sum(p * np.log(p / q)))


# == LLM Interface ==
def call_llm(
    system_prompt: str, user_prompt: str, max_tokens: int = 2048
) -> Optional[str]:
    if not API_KEY:
        print("ERROR: No API key", file=sys.stderr)
        return None

    import urllib.request

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
            req = urllib.request.Request(OPENROUTER_URL, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  LLM attempt {attempt + 1} failed: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(2**attempt)
    return None


def parse_json_response(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
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
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return None


def llm_decompose(question: str) -> dict:
    """
    Use LLM to decompose a question into what data is needed.
    Returns dict with fields explaining what data to fetch.
    """
    prompt = f"""Decompose this question to understand what data is needed to answer it.

QUESTION: {question}

Output JSON with these fields:
- data_year: the year(s) to look for
- topic: what category/column is needed
- period_type: fiscal or calendar
- computation: sum or difference or percent_change or geometric_mean or direct or average
- value_format: monthly_series or annual_total or multi_year
- years_needed: list of all years needed
- search_terms: keywords to find the table
- notes: any special handling

Output only valid JSON starting with curly brace."""

    response = call_llm(
        "You are a precise data analyst. Output ONLY valid JSON.", prompt, 1024
    )
    if not response:
        print(f"  LLM returned empty response", file=sys.stderr)
        return {"error": "LLM failed"}

    result = parse_json_response(response)
    if result:
        return result

    print(f"  Parse failed, raw: {response[:200]}", file=sys.stderr)
    return {"error": "Parse failed", "raw": response}


# ==============================================================================
# STEP 1: Find Tables - Just find matching tables, return structured info
# ==============================================================================


def find_tables_step(
    question: str,
    data_year: int,
    search_terms: list,
    target_bulletin_year: int,
    source_file: str = None,
) -> list:
    """
    STEP 1: Find the right file.
    """
    print(f"\n[STEP 1: Find Files]", file=sys.stderr)
    print(f"  Data year: {data_year}, Target: {target_bulletin_year}", file=sys.stderr)

    corpus = Path(CORPUS_DIR)
    candidates = []

    # If source_file provided (for testing), use it
    if source_file:
        full_path = corpus / source_file
        if full_path.exists():
            print(f"  Using provided: {source_file}", file=sys.stderr)
            return [{"file": str(full_path), "title": source_file, "match_score": 100}]

    # BROAD SEARCH: Look for files in a wider range around target year
    if target_bulletin_year:
        years_to_try = []
        for delta in range(-2, 4):  # -2, -1, 0, 1, 2, 3
            yr = target_bulletin_year + delta
            if 1935 <= yr <= 2025:
                years_to_try.append(yr)

        for yr in years_to_try:
            for month in [
                "01",
                "02",
                "03",
                "04",
                "05",
                "06",
                "07",
                "08",
                "09",
                "10",
                "11",
                "12",
            ]:
                fname = f"treasury_bulletin_{yr}_{month}.txt"
                fpath = corpus / fname
                if fpath.exists():
                    candidates.append(
                        {
                            "file": str(fpath),
                            "title": fname,
                            "match_score": 1,
                            "bulletin_year": yr,
                        }
                    )

    # Sort by year descending (newer first)
    candidates.sort(key=lambda x: -int(x.get("bulletin_year", 0)))

    print(f"  Found {len(candidates)} files to try", file=sys.stderr)
    for c in candidates[:3]:
        print(f"    - {c['title']}", file=sys.stderr)

    return candidates[:3]


def find_tables_in_file(
    filepath: Path, search_terms: list, data_year: int = None
) -> list:
    """Find tables in file matching search terms - finds BOTH annual and monthly tables."""
    try:
        text = filepath.read_text(errors="replace")
    except:
        return []

    lines = text.splitlines()
    tables = []

    # Strategy: find tables by looking for the COLUMN NAME in headers
    # Not by matching search terms in data rows

    # First, find all table header rows
    for i, line in enumerate(lines):
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.split("|") if c.strip()]
            # Check if it's a header (has text, not dashes)
            if cells and not all(re.match(r"^[-:]+$", c) for c in cells):
                # Score by number of columns (more columns = more likely to be data table)
                score = len(cells) if len(cells) > 3 else 1

                # Check if search terms match ANYWHERE in the header (not just first cell)
                # Join all cells to search across them
                full_header = " ".join(cells).lower()
                term_matches = sum(
                    1 for term in search_terms if term.lower() in full_header
                )
                score = score + term_matches * 5

                # Also prioritize if column hint is found in header - but we don't have sub_query here
                # Just use search_terms scoring

                # Only keep tables that match at least one search term
                if term_matches > 0:
                    # This is a potential table - get data rows
                    header_row = (i, line)
                    header_cols = cells

                    # Get data rows (forward from header)
                    data_rows = []
                    for j in range(i + 1, min(len(lines), i + 40)):
                        row = lines[j].strip()
                        if not row.startswith("|"):
                            continue
                        row_cells = [c.strip() for c in row.split("|") if c.strip()]
                        if row_cells and not all(
                            re.match(r"^[-:]+$", c) for c in row_cells
                        ):
                            data_rows.append((j, row))

                    if data_rows:
                        # Extract title
                        title = ""
                        for k in range(i - 1, max(0, i - 10), -1):
                            tline = lines[k].strip()
                            if (
                                not tline
                                or tline.startswith("|")
                                or tline.startswith("---")
                            ):
                                break
                            if not re.match(r"^\d+$|page\s+\d+", tline, re.I):
                                title = tline + " " + title
                        title = title.strip()

                        tables.append(
                            {
                                "title": title if title else "Unknown",
                                "columns": header_cols,
                                "file": str(filepath),
                                "line_start": max(0, i - 3),
                                "line_end": min(len(lines), data_rows[-1][0] + 3),
                                "data_rows": data_rows,
                                "score": score,
                            }
                        )

    # Sort by score and return top matches
    tables.sort(key=lambda x: -x["score"])
    print(
        f"  DEBUG: find_tables_in_file found {len(tables)} total tables",
        file=sys.stderr,
    )
    return tables[:20]


# ==============================================================================
# STEP 2: Select Table - Just return ALL candidates to let LLM decide
# ==============================================================================


def select_table_step(sub_query: dict, candidates: list) -> list:
    """
    STEP 2: Return ALL candidates to extraction - let LLM decide which to use.
    """
    print(f"\n[STEP 2: Select Table]", file=sys.stderr)

    if not candidates:
        print("  No candidates!", file=sys.stderr)
        return []

    print(
        f"  Returning {len(candidates)} candidates to LLM extraction", file=sys.stderr
    )

    # Take top 3 candidates to avoid too many LLM calls
    return candidates[:3]


# ==============================================================================
# STEP 3: Extract Data - Get values from selected table
# ==============================================================================


def extract_data_step(sub_query: dict, table: dict) -> dict:
    """
    STEP 3: Extract values from the selected table.
    Tries LLM first, falls back to deterministic.
    """
    print(f"\n[STEP 3: Extract Data]", file=sys.stderr)
    print(f"  From: {table.get('title', '')[:50]}", file=sys.stderr)

    # First try deterministic extraction
    result = extract_deterministic(sub_query, table)
    if result and result.get("values") is not None:
        print(f"  Deterministic: {result.get('values')}", file=sys.stderr)
        return result

    # Fall back to LLM
    print(f"  Trying LLM extraction...", file=sys.stderr)

    # Try LLM extraction with raw file content
    print(f"  Trying LLM extraction...", file=sys.stderr)

    # Read the full file
    try:
        filepath = table.get("file", "")
        if not filepath:
            return {"values": None, "confidence": "low", "error": "No file"}

        # Read full file
        full_text = Path(filepath).read_text(errors="replace")
    except:
        return {"values": None, "confidence": "low", "error": "Read failed"}

    col_hint = sub_query.get("column_hint", "")
    data_year = str(sub_query.get("data_year", ""))
    value_type = sub_query.get("value_type", "")

    # Give LLM the full file to search - let it find the right data
    prompt = f"""Search through this Treasury Bulletin file to find expenditure data.

FILE CONTENT (first 8000 chars):
{full_text[:8000]}

QUESTION: What were the total {col_hint} expenditures in millions for calendar year {data_year}?

INSTRUCTIONS:
1. Search for {col_hint} expenditure data
2. Look for {data_year} data - either monthly (12 months) or annual
3. If monthly, sum all 12 months
4. If annual, use that value

Return ONLY a number (the total in millions).
If you cannot find the data, return just "NONE"."""

    response = call_llm("You are a precise data extractor.", prompt, 512)

    if response and response.strip() and response.strip().upper() != "NONE":
        # Try to parse number
        nums = re.findall(r"[\d,]+\.?\d*", response.replace(",", ""))
        if nums:
            try:
                return {
                    "values": float(nums[0]),
                    "confidence": "medium",
                    "notes": "Full file LLM extraction",
                }
            except:
                pass

    return {"values": None, "confidence": "low", "error": "LLM extraction failed"}

    prompt = f"""Extract data from this Treasury table.

TABLE:
{table_text}

REQUESTED:
- Data year: {data_year}
- Value type: {value_type}
- Expected column: {col_hint}

INSTRUCTIONS:
1. Find row for year {data_year}
2. For monthly_series: extract ALL months (Jan-Dec) for that year from column "{col_hint}"
3. For annual_total: extract the single annual value
4. Use column: "{col_hint}" - look for this exact column
5. "-" or empty = zero

Return JSON:
{{
  "values": <number or [list of 12 monthly numbers]>,
  "source_row": "row label as shown",
  "source_column": "column name used",
  "confidence": "high|medium|low",
  "notes": "any issues"
}}"""

    response = call_llm("You are a precise data extractor.", prompt, 1024)
    if not response:
        return {"values": None, "confidence": "low", "error": "LLM failed"}

    result = parse_json_response(response)
    if not result:
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

    print(f"  LLM Extracted: {result.get('values')}", file=sys.stderr)
    print(f"  Confidence: {result.get('confidence')}", file=sys.stderr)

    return result


def extract_deterministic(sub_query: dict, table: dict) -> dict:
    """Try deterministic extraction first - much faster."""
    data_year = str(sub_query.get("data_year", ""))
    value_type = sub_query.get("value_type", "")
    col_hint = (sub_query.get("column_hint") or "").lower()

    if not data_year:
        return None

    try:
        text = Path(table.get("file")).read_text(errors="replace")
    except:
        return None

    lines = text.splitlines()
    ls = table.get("line_start", 0)
    le = min(table.get("line_end", ls + 60), len(lines))

    print(
        f"    DEBUG: line_start={ls}, line_end={le}, data_year={data_year}, col_hint={col_hint}",
        file=sys.stderr,
    )

    # Find header row
    header = None
    header_idx = None
    for i in range(ls, min(ls + 10, le)):
        line = lines[i].strip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if cells and not all(re.match(r"^[-:]+$", c) for c in cells):
                header = cells
                header_idx = i
                break

    if not header:
        return None

    # Find column index for our hint
    col_idx = None
    for i, h in enumerate(header):
        if col_hint in h.lower():
            col_idx = i
            break

    if col_idx is None:
        return None

    # Extract values
    values = []

    if value_type == "monthly_series":
        # Get 12 months for data_year
        for i in range(header_idx + 1, le):
            line = lines[i].strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if not cells:
                continue

            row_label = cells[0]

            # Track year state - if row has year, update current year
            current_year = None
            if row_label and re.match(r"^20\d{2}-", row_label):
                current_year = int(row_label.split("-")[0])
            elif row_label and re.match(r"^19\d{2}-", row_label):
                current_year = int(row_label.split("-")[0])

            # Check if this is a monthly row for our year
            is_monthly = False
            row_year = current_year

            # If row_label has year prefix like "1940-January"
            if f"{data_year}-January" in row_label or (
                f"{data_year}-" in row_label
                and any(
                    m in row_label
                    for m in [
                        "January",
                        "February",
                        "March",
                        "April",
                        "May",
                        "June",
                        "July",
                        "August",
                        "September",
                        "October",
                        "November",
                        "December",
                    ]
                )
            ):
                is_monthly = True
                row_year = data_year
            # If row_label is just month name (no year), need to check context
            elif row_label in [
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ]:
                # This is ambiguous - could be any year
                # For now, collect all month rows and sum
                is_monthly = True

            if is_monthly and col_idx < len(cells):
                val = cells[col_idx].replace(",", "").replace("-", "0").strip()
                try:
                    values.append(float(val))
                except:
                    values.append(0.0)

                if len(values) >= 12:
                    break

    elif value_type == "annual_total":
        for i in range(header_idx + 1, le):
            line = lines[i].strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if not cells:
                continue

            row_label = cells[0]
            if row_label == data_year and col_idx < len(cells):
                val = cells[col_idx].replace(",", "").replace("-", "0").strip()
                try:
                    return {
                        "values": float(val),
                        "confidence": "high",
                        "notes": "Deterministic",
                    }
                except:
                    pass

    if values and len(values) >= 12:
        return {
            "values": values,
            "confidence": "high",
            "notes": "Deterministic extraction",
        }

    return None


# ==============================================================================
# STEP 4: Compute - Calculate final answer
# ==============================================================================


def compute_step(plan: dict, extracted_values: Any) -> str:
    """
    STEP 4: Compute final answer from extracted values.
    """
    print(f"\n[STEP 4: Compute]", file=sys.stderr)

    comp = plan.get("computation", {})
    comp_type = comp.get("type", "direct")

    values = extracted_values
    if values is None:
        return "N/A"

    try:
        if comp_type == "sum":
            if isinstance(values, list):
                result = sum(
                    float(str(v).replace(",", ""))
                    for v in values
                    if v and str(v).strip()
                )
                return str(int(result))
            return str(values)

        elif comp_type == "difference":
            if isinstance(values, list) and len(values) >= 2:
                v1, v2 = float(values[0]), float(values[1])
                return str(int(abs(v1 - v2)))
            return str(values)

        elif comp_type == "geometric_mean":
            if isinstance(values, list):
                result = compute_geometric_mean(values)
                return str(round(result, 3))
            return str(values)

        elif comp_type == "percent_change":
            if isinstance(values, list) and len(values) >= 2:
                old, new = float(values[0]), float(values[1])
                if old == 0:
                    return "0"
                return str(round(abs((new - old) / old) * 100, 2))
            return str(values)

        elif comp_type == "kl_divergence":
            if isinstance(values, list) and len(values) == 2:
                result = compute_kl_divergence(values[0], values[1])
                return str(result)
            return str(values)

        else:
            return str(values)

    except Exception as e:
        print(f"  Compute error: {e}", file=sys.stderr)
        return str(values) if values else "N/A"


# ==============================================================================
# STEP 5: Verify - Sanity check answer
# ==============================================================================


def verify_step(question: str, answer: str) -> dict:
    """STEP 5: Verify answer makes sense."""
    print(f"\n[STEP 5: Verify]", file=sys.stderr)

    if answer == "N/A":
        print(f"  FAILED: No answer extracted", file=sys.stderr)
        return {"verified": False, "issues": ["No answer"]}

    # Try to get numeric value
    num_str = str(answer).replace(",", "").replace("%", "").replace("$", "").strip()

    # If the answer looks like an error message, fail
    if any(
        x in answer.lower()
        for x in ["none", "failed", "error", "no data", "not found", "available"]
    ):
        print(f"  FAILED: Answer indicates failure: {answer[:50]}", file=sys.stderr)
        return {"verified": False, "issues": ["Extraction failed"]}

    try:
        val = float(num_str)

        # Check for crazy values
        q = question.lower()

        if "percent" in q or "%" in q:
            if val > 10000:
                print(f"  WARNING: Unusually large percent: {val}", file=sys.stderr)

        if "million" in q:
            if val > 1e8:
                print(f"  WARNING: Unusually large value: {val}", file=sys.stderr)

        # Check if answer is suspiciously small (like a year number)
        if 1900 <= val <= 2050 and "year" not in q:
            print(f"  WARNING: Answer looks like a year: {val}", file=sys.stderr)
            return {"verified": False, "issues": ["Answer looks like year, not data"]}

        print(f"  Answer seems reasonable: {answer}", file=sys.stderr)

    except ValueError:
        print(f"  WARNING: Answer is not numeric: {answer}", file=sys.stderr)
        return {"verified": False, "issues": ["Not numeric"]}

    return {"verified": True, "issues": []}


# ==============================================================================
# Main Pipeline
# ==============================================================================


def solve_v3(question: str, source_file: str = None) -> str:
    """Main solve function - step by step."""
    print(f"\n{'=' * 70}", file=sys.stderr)
    print(f"[SOLVE V3] {question[:100]}", file=sys.stderr)
    print(f"{'=' * 70}", file=sys.stderr)

    # Step 0: Decompose question
    print(f"\n[STEP 0: Decompose]", file=sys.stderr)

    # First, analyze the question type properly
    question_lower = question.lower()
    is_fy = "fy" in question_lower or "fiscal year" in question_lower
    is_cy = (
        "calendar year" in question_lower
        or "cy" in question_lower
        or ("in 19" in question_lower or "in 20" in question_lower)
    )
    is_monthly = "month" in question_lower
    has_sum = "sum" in question_lower or "total" in question_lower
    has_diff = "difference" in question_lower or "change" in question_lower

    # Extract year
    year_match = re.search(r"(19|20)\d{2}", question)
    data_year = int(year_match.group()) if year_match else None

    # Determine value type
    # Calendar year with sum = monthly_series (get 12 months, sum)
    # Fiscal year = annual_total (get single year row)
    if is_fy:
        value_type = "annual_total"
        period = "fiscal"
    elif is_cy:
        # For calendar year - need to decide between monthly_series or annual
        # If asking for sum/total/average of a year, it's monthly_series
        if has_sum or "average" in question_lower or "mean" in question_lower:
            value_type = "monthly_series"
        else:
            value_type = "annual_total"
        period = "calendar"
    else:
        value_type = "annual_total"
        period = "fiscal" if is_fy else "calendar"

    # Determine computation
    if has_diff:
        comp_type = "difference"
    elif "geometric" in question_lower:
        comp_type = "geometric_mean"
    elif "percent" in question_lower:
        comp_type = "percent_change"
    elif has_sum:
        comp_type = "sum"
    else:
        comp_type = "direct"

    # Determine search terms - key insight: use column-like terms, not question terms
    search_terms = []
    if "defense" in question_lower or "national defense" in question_lower:
        search_terms.extend(["national defense", "expenditures"])
    if "veterans" in question_lower:
        search_terms.extend(["veterans", "expenditures"])
    if "receipts" in question_lower:
        search_terms.extend(["receipts", "revenue"])
    if "interest" in question_lower:
        search_terms.extend(["interest", "expenditures"])
    if not search_terms:
        search_terms = ["expenditures", "receipts"]

    # Add year to search
    if data_year:
        search_terms.append(str(data_year))

    target_bulletin = data_year + 1 if data_year else None

    print(f"  Question analysis:", file=sys.stderr)
    print(f"    Period: {period}, Value type: {value_type}", file=sys.stderr)
    print(f"    Computation: {comp_type}", file=sys.stderr)
    print(f"    Data year: {data_year}", file=sys.stderr)
    print(f"    Target bulletin: {target_bulletin}", file=sys.stderr)
    print(f"    Search terms: {search_terms}", file=sys.stderr)

    # Build plan
    plan = {
        "question_type": f"{period}_{value_type}",
        "data_years": [data_year] if data_year else [],
        "sub_queries": [
            {
                "id": "A",
                "search_terms": search_terms,
                "target_bulletin_year": target_bulletin,
                "data_year": data_year,
                "value_type": value_type,
                "column_hint": "National defense"
                if "defense" in question_lower
                else "Total",
            }
        ],
        "computation": {"type": comp_type, "sub_query_refs": ["A"]},
    }

    # Process sub-query
    all_extracted = {}

    for sq in plan.get("sub_queries", []):
        sq_id = sq.get("id", "A")
        print(f"\n{'=' * 50}", file=sys.stderr)
        print(f"[SUB-QUERY {sq_id}]", file=sys.stderr)

        # Step 1: Find files (now returns file list, not table list)
        file_candidates = find_tables_step(
            question,
            sq.get("data_year"),
            sq.get("search_terms", []),
            sq.get("target_bulletin_year"),
            source_file,  # Pass the known source file if we have it
        )

        # Step 2: Select files - just use the returned list
        if not file_candidates:
            all_extracted[sq_id] = {"values": None, "error": "No files found"}
            continue

        # Step 3: Try each file until LLM extracts data successfully
        extracted = None
        for i, fc in enumerate(file_candidates):
            print(
                f"  Trying file {i + 1}/{len(file_candidates)}: {fc.get('title', 'Unknown')}",
                file=sys.stderr,
            )
            result = extract_data_step(sq, fc)
            if result and result.get("values") is not None:
                extracted = result
                print(f"  Success with file {i + 1}!", file=sys.stderr)
                break

        if not extracted:
            extracted = {"values": None, "error": "All candidates failed"}

        all_extracted[sq_id] = extracted

    # Step 4: Compute
    print(f"\n{'=' * 50}", file=sys.stderr)
    print(f"[COMPUTE FINAL ANSWER]", file=sys.stderr)

    # Flatten values from all sub-queries
    all_values = []
    for sq in plan.get("sub_queries", []):
        sq_id = sq.get("id", "A")
        vals = all_extracted.get(sq_id, {}).get("values")
        if vals is not None:
            all_values.append(vals)

    if not all_values:
        return "N/A"

    flat_values = all_values[0] if len(all_values) == 1 else all_values

    answer = compute_step(plan, flat_values)

    # Step 5: Verify
    verify_step(question, answer)

    print(f"\n[FINAL ANSWER] {answer}", file=sys.stderr)
    return answer


# == CLI ==
def main():
    if len(sys.argv) < 2:
        print("Usage: python3 solve_v3.py 'QUESTION'")
        sys.exit(1)

    question = sys.argv[1]
    answer = solve_v3(question)

    answer_path = Path("/app/answer.txt" if Path("/app").exists() else "./answer.txt")
    answer_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.write_text(str(answer))

    print(f"[Output] {answer_path}: {answer}", file=sys.stderr)


if __name__ == "__main__":
    main()
