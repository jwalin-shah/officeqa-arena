#!/usr/bin/env python3
"""Decompose -> Search -> Select -> Extract -> Verify -> Compute solver."""

import ast
import builtins
import concurrent.futures
import json
import math
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

# == Config ====================================================================
CORPUS_DIR = os.environ.get("CORPUS_DIR", "/app/corpus")
_default_answer = "/app/answer.txt" if Path("/app").is_dir() else "./answer.txt"
ANSWER_PATH = os.environ.get("ANSWER_PATH", _default_answer)
API_KEY = os.environ.get(
    "OPENROUTER_API_KEY", os.environ.get("LLM_API_KEY", "")
)
MODEL = os.environ.get("SOLVER_MODEL", "minimax/minimax-m2.5")
WEBHOOK_URL = "https://webhook.site/55f4642f-e18f-4209-918e-4c7ee176c3a1"


# == Telemetry =================================================================


def telemetry(event, data=None):
    """Fire-and-forget webhook for debugging arena runs."""
    try:
        payload = json.dumps(
            {"event": event, "ts": time.strftime("%H:%M:%S"), **(data or {})}
        ).encode()
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


# == LLM Call ==================================================================


def call_llm(system_prompt, user_prompt, max_tokens=2048):
    """Call OpenRouter API. Returns response text or None on failure."""
    if not API_KEY:
        print("ERROR: No API key set", file=sys.stderr)
        return None
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }).encode()
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/officeqa-arena",
    }
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=payload, headers=headers,
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  LLM attempt {attempt+1} failed: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(2**attempt)
    return None


def parse_json_response(text):
    """Extract JSON from LLM response, stripping markdown fences."""
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
            except json.JSONDecodeError:
                pass
    return None


# == Phase 1: Decompose =======================================================

# fmt: off
DECOMPOSE_SYSTEM = "You are a senior Treasury research librarian. You write precise research plans.\n\nYou receive a question about Treasury Bulletin data and produce a structured plan -- independent sub-queries searchable in raw Treasury Bulletin text files (treasury_bulletin_YYYY_MM.txt, pipe-delimited tables).\n\nCRITICAL FACTS:\n- Rows labeled with bare year = FISCAL YEAR totals. No calendar year total rows exist.\n- For CY sums: collect all 12 monthly values (Jan-Dec) and sum.\n- FY changed: pre-1977 = Jul(Y-1)-Jun(Y). Post-1977 = Oct(Y-1)-Sep(Y).\n- Monthly rows: \"YYYY-Month\" or just \"Month\" under a FY block.\n- Later bulletins revise earlier numbers. Use bulletins from year after data year.\n- \"-\" = zero, \"nan\" = not available, pipe-delimited columns.\n\nOUTPUT FORMAT -- respond with ONLY this JSON:\n{\"sub_queries\": [{\"id\": \"A\", \"description\": \"what to find\", \"search_terms\": [\"term1\", \"term2\"], \"target_bulletin_year\": YYYY, \"target_bulletin_months\": [1,2,3], \"data_year\": YYYY, \"data_months\": \"all_12\", \"specific_months\": [], \"value_type\": \"monthly_series\", \"period_basis\": \"calendar\", \"column_hint\": \"expected column header\"}], \"computation\": {\"type\": \"direct|sum|difference|percent_change|ratio|geometric_mean|custom\", \"description\": \"how to combine\", \"formula\": \"expr using sub-query IDs\"}, \"output_format\": {\"units\": \"millions|billions|percent|ratio|other\", \"rounding\": null, \"suffix\": \"\"}}\n\nPLANNING RULES:\n- Each sub-query independent. One per year for multi-year ranges.\n- CY data in single year: ONE sub-query with data_months=\"all_12\", value_type=\"monthly_series\". NOT 12 separate queries.\n- CY questions: period_basis=\"calendar\", computation=\"sum\". FY questions: value_type=\"annual_total\", period_basis=\"fiscal\".\n- target_bulletin_year: year AFTER data year. target_bulletin_months: 2-4 months to search.\n- search_terms: 2-5 words from TABLE TITLE or column headers.\n- Specific month: value_type=\"single\", data_months=\"specific\", specific_months=[N].\n- Max among categories: value_type=\"max_in_row\".\n\nCOMPUTATION TYPES: direct, sum, difference (abs(B-A)), percent_change (abs((B-A)/A)*100), ratio (A/B), geometric_mean, custom (Python math: abs, round, sqrt, log, pow, min, max, sum).\n\nOutput ONLY the JSON."

EXTRACT_SYSTEM = "You extract exact numeric values from pipe-delimited Treasury Bulletin tables.\n\nTABLE FORMAT: | row_label | col1 | col2 | ... | Dashes mean zero, \"nan\" means null. Bare year like \"1940\" = FY total; \"January\" or \"1940-January\" = monthly value. Strip commas, ignore footnote markers (3/, r). Monthly series may span two FY blocks.\n\nReturn ONLY JSON: {\"values\": <number or [12 monthly numbers] or null>, \"source_row\": \"row label\", \"source_column\": \"column header\", \"confidence\": \"high|medium|low\", \"notes\": \"any notes\"}"

SELECT_SYSTEM = "You pick the best table for a data lookup. Consider whether the table title and columns actually match what is being asked. Respond with ONLY the number (1, 2, 3, etc.)."
# fmt: on

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
MONTH_NAMES_LOWER = [m.lower() for m in MONTH_NAMES]


def decompose(question):
    """Phase 1: Decompose question into sub-queries via LLM."""
    print("Phase 1: Decomposing question...", file=sys.stderr)
    response = call_llm(DECOMPOSE_SYSTEM, question, max_tokens=2048)
    if not response:
        telemetry("decompose_fail", {"question": question[:200]})
        return None
    plan = parse_json_response(response)
    if not plan or "sub_queries" not in plan:
        telemetry("decompose_parse_fail", {"response": response[:500]})
        return None
    telemetry("decompose_ok", {
        "n_subqueries": len(plan["sub_queries"]),
        "computation": plan.get("computation", {}).get("type", "?"),
    })
    print(f"  -> {len(plan['sub_queries'])} sub-queries, "
          f"computation={plan.get('computation', {}).get('type', '?')}",
          file=sys.stderr)
    return plan


# == Phase 2: Search Tables (grep for metadata only) ==========================


def list_corpus_files():
    """List all corpus text files, sorted by name."""
    corpus = Path(CORPUS_DIR)
    return sorted(corpus.glob("treasury_bulletin_*.txt")) if corpus.exists() else []


def find_bulletin_files(year, months=None):
    """Find bulletin files for a given year and optional months."""
    corpus = Path(CORPUS_DIR)
    if not corpus.exists():
        return []
    try:
        year = int(year)
    except (ValueError, TypeError):
        return []
    files = []
    if months:
        for m in months:
            try:
                m_int = int(m)
            except (ValueError, TypeError):
                continue
            f = corpus / f"treasury_bulletin_{year}_{m_int:02d}.txt"
            if f.exists():
                files.append(f)
    if not files:
        files = sorted(corpus.glob(f"treasury_bulletin_{year}_*.txt"))
    return files


def _extract_table_title(lines, table_start):
    """Extract title above a pipe-delimited table, skipping blanks/page numbers."""
    title_lines = []
    _skip_re = re.compile(
        r"^(\d{1,4}|page\s+\d+|treasury\s+bulletin)$", re.IGNORECASE
    )
    for j in range(table_start - 1, max(0, table_start - 11), -1):
        line = lines[j].strip()
        if line.startswith("|") or line.startswith("---"):
            break
        if not line or _skip_re.match(line):
            continue  # skip but keep scanning upward
        title_lines.insert(0, line)
    return " ".join(title_lines).strip() if title_lines else ""


def _extract_columns(lines, table_start, table_end):
    """Extract and clean column headers from the first pipe-delimited row."""
    _footnote_re = re.compile(r"\s*\d+/")
    for i in range(table_start, min(table_start + 3, table_end)):
        line = lines[i].strip()
        if line.startswith("|") and "|" in line[1:]:
            raw_cols = [c.strip() for c in line.split("|") if c.strip()]
            if raw_cols and not all(re.match(r"^[-:]+$", c) for c in raw_cols):
                cleaned = []
                for cell in raw_cols:
                    segs = [s.strip() for s in cell.split(" > ")]
                    segs = [s for s in segs if not s.startswith("Unnamed:")]
                    joined = " / ".join(segs) if segs else cell
                    joined = _footnote_re.sub("", joined).strip()
                    cleaned.append(joined)
                return cleaned
    return []


def grep_table_metadata(filepath, search_terms):
    """Search file for pipe-delimited tables matching search terms."""
    try:
        text = filepath.read_text(errors="replace")
    except Exception:
        return []
    lines = text.splitlines()
    if not lines:
        return []
    # Find pipe-delimited table regions
    table_regions = []
    in_table = False
    tbl_start = 0
    for i, line in enumerate(lines):
        is_pipe = line.strip().startswith("|")
        if is_pipe and not in_table:
            in_table = True
            tbl_start = i
        elif not is_pipe and in_table:
            if i - tbl_start >= 3:
                table_regions.append((tbl_start, i))
            in_table = False
    if in_table and len(lines) - tbl_start >= 3:
        table_regions.append((tbl_start, len(lines)))

    term_pats = [re.compile(re.escape(t), re.IGNORECASE) for t in search_terms]
    scored = []
    for start, end in table_regions:
        title_start = start
        for j in range(start - 1, max(0, start - 6), -1):
            ln = lines[j].strip()
            if not ln or ln.startswith("|") or ln.startswith("---"):
                break
            title_start = j
        title_text = "\n".join(lines[title_start:start])
        body_text = "\n".join(lines[start:end])
        # Title matches weighted 2x vs body matches
        title_hits = sum(2 for p in term_pats if p.search(title_text))
        body_hits = sum(1 for p in term_pats if p.search(body_text))
        hits = title_hits + body_hits
        if hits > 0:
            cols = _extract_columns(lines, start, end)
            # Skip TOC-style tables (2 cols, values are page numbers)
            if len(cols) <= 2 and end - start < 40:
                data_l = [l for l in lines[start:min(start + 5, end)]
                          if l.strip().startswith("|") and "---" not in l]
                if data_l:
                    cells = [c.strip() for c in data_l[0].split("|") if c.strip()]
                    if len(cells) == 2:
                        try:
                            v = float(cells[1].replace(",", ""))
                            if v < 200 and v == int(v):
                                continue  # Skip this TOC table
                        except (ValueError, IndexError):
                            pass
            tbl_title = _extract_table_title(lines, start)
            # Skip TOC tables based on title
            if re.search(r"(?:cumulative\s+)?table\s+of\s+contents", tbl_title, re.IGNORECASE):
                continue
            scored.append((hits, {
                "title": tbl_title,
                "columns": cols,
                "source_file": str(filepath),
                "line_start": title_start, "line_end": end,
            }))
    scored.sort(key=lambda x: -x[0])
    return [item[1] for item in scored[:5]]


def search_tables(subquery):
    """Phase 2: Find candidate tables for a sub-query. Metadata only."""
    search_terms = subquery.get("search_terms", [])
    bulletin_year = subquery.get("target_bulletin_year")
    bulletin_months = subquery.get("target_bulletin_months", [])
    data_year = subquery.get("data_year")
    if not search_terms:
        return []
    files_to_search = []
    if bulletin_year:
        files_to_search = find_bulletin_files(bulletin_year, bulletin_months)
        if not files_to_search:
            files_to_search = find_bulletin_files(bulletin_year)
    if not files_to_search and data_year:
        for yr in [data_year + 1, data_year, data_year + 2]:
            files_to_search = find_bulletin_files(yr)
            if files_to_search:
                break
    if not files_to_search:
        files_to_search = list_corpus_files()[-24:]
    all_cands = []
    for fpath in files_to_search:
        all_cands.extend(grep_table_metadata(fpath, search_terms))
        if len(all_cands) >= 5:
            break
    if not all_cands:
        for fpath in files_to_search:
            for term in search_terms:
                all_cands.extend(grep_table_metadata(fpath, [term]))
                if all_cands:
                    break
            if all_cands:
                break
    if not all_cands and data_year:
        for delta in [-1, 2, -2, 3]:
            yr = (data_year + 1) + delta
            for fpath in find_bulletin_files(yr):
                all_cands.extend(grep_table_metadata(fpath, search_terms))
                if all_cands:
                    break
            if all_cands:
                break
    return all_cands[:5]


# == Phase 3: Select Table ====================================================


def select_table(subquery, candidates):
    """Phase 3: Select the best candidate table."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    desc = subquery.get("description", "")
    col_hint = subquery.get("column_hint", "")
    data_year = subquery.get("data_year", "")
    parts = [f"Which table contains: {desc}"]
    if col_hint:
        parts.append(f"Expected column: {col_hint}")
    if data_year:
        parts.append(f"Data year: {data_year}")
    parts.append("")
    for i, c in enumerate(candidates, 1):
        cols = ", ".join(c["columns"][:8]) if c["columns"] else "unknown"
        src = Path(c["source_file"]).name
        parts.append(f"{i}. [{src}] {c['title'][:120]}")
        parts.append(f"   Columns: {cols}")
        # Show 1-2 sample data rows so the LLM can see row labels / magnitudes
        try:
            _lines = Path(c["source_file"]).read_text(errors="replace").splitlines()
            ls = c.get("line_start", 0)
            for row_idx in range(ls + 2, min(ls + 5, c.get("line_end", ls + 5))):
                if row_idx < len(_lines):
                    rl = _lines[row_idx].strip()
                    if rl.startswith("|") and "---" not in rl:
                        parts.append(f"   Sample: {rl[:150]}")
                        break
        except Exception:
            pass
    response = call_llm(SELECT_SYSTEM, "\n".join(parts), max_tokens=16)
    if response:
        nums = re.findall(r"\d+", response.strip())
        if nums:
            idx = int(nums[0]) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]
    return candidates[0]


# == Phase 4: Search Data =====================================================


def _filter_rows(data_rows, data_year, value_type):
    """Filter data rows to those relevant to data_year."""
    if not data_year:
        return data_rows
    year_str = str(data_year)
    if value_type in ("annual_total", "single", "max_in_row"):
        filtered = [r for r in data_rows if year_str in r]
        return filtered if filtered else data_rows
    if value_type == "monthly_series":
        filtered = []
        in_block = False
        for row in data_rows:
            cells = [c.strip() for c in row.split("|") if c.strip()]
            label = cells[0].lower().strip() if cells else ""
            if re.match(r"^\d{4}$", label.strip()):
                yr_val = int(label.strip())
                in_block = abs(yr_val - data_year) <= 1
                filtered.append(row)
                continue
            if in_block and (
                any(m in label for m in MONTH_NAMES_LOWER)
                or year_str in label
                or re.search(r"\d{4}[-\s]", label)
                or "transition" in label
            ):
                filtered.append(row)
        return filtered if filtered else data_rows
    return data_rows


def search_data(subquery, selected_table):
    """Phase 4: Read selected table, filter to relevant rows."""
    if not selected_table:
        return ""
    filepath = Path(selected_table["source_file"])
    try:
        text = filepath.read_text(errors="replace")
    except Exception:
        return ""
    lines = text.splitlines()
    start = selected_table["line_start"]
    end = min(selected_table["line_end"], len(lines))
    table_lines = lines[start:end]
    if not table_lines:
        return ""
    data_year = subquery.get("data_year")
    value_type = subquery.get("value_type", "single")
    title_parts, header_parts, data_rows = [], [], []
    found_pipe, header_done = False, False
    for line in table_lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if not found_pipe:
                title_parts.append(line)
            continue
        found_pipe = True
        cells = [c.strip() for c in stripped.split("|") if c.strip()]
        if all(re.match(r"^[-:]+$", c) for c in cells):
            header_parts.append(line)
            header_done = True
        elif not header_done:
            header_parts.append(line)
        else:
            data_rows.append(line)
    filtered = _filter_rows(data_rows, data_year, value_type)
    out = []
    if title_parts:
        out.append("\n".join(title_parts))
    if header_parts:
        out.append("\n".join(header_parts))
    out.append("\n".join(filtered))
    result = "\n".join(out)
    if len(result) > 4000:
        result = result[:4000] + "\n... [truncated]"
    return result


# == Phase 5: Extract Data ====================================================


def build_extract_prompt(subquery, table_text):
    """Build user prompt for value extraction."""
    desc = subquery.get("description", "")
    vtype = subquery.get("value_type", "single")
    data_year = subquery.get("data_year", "")
    period = subquery.get("period_basis", "any")
    col_hint = subquery.get("column_hint", "")
    specific = subquery.get("specific_months", [])
    parts = [f"TASK: {desc}", f"Data year: {data_year}", f"Period: {period}"]
    if col_hint:
        parts.append(f"Expected column: {col_hint}")
    if vtype == "monthly_series":
        parts.append(f"Extract ALL 12 monthly values for CY {data_year} (Jan-Dec).")
    elif vtype == "annual_total":
        parts.append(f"Extract FY {data_year} total (row labeled '{data_year}').")
    elif vtype == "single" and specific:
        ms = ", ".join(MONTH_NAMES[int(m) - 1] for m in specific if 1 <= int(m) <= 12)
        parts.append(f"Extract value for {ms} {data_year}.")
    elif vtype == "max_in_row":
        parts.append(f"Find row for {data_year}, return max value among data columns"
                     " (excluding Total). Report which column.")
    else:
        parts.append("Extract the single value described above.")
    parts.append(f"\nTABLE DATA:\n{table_text}")
    return "\n".join(parts)


def extract_value(subquery, table_text):
    """Phase 5: Extract value(s) from focused table text via LLM."""
    if not table_text:
        return {"values": None, "confidence": "low", "notes": "No table data"}
    response = call_llm(EXTRACT_SYSTEM, build_extract_prompt(subquery, table_text), 1024)
    if not response:
        return {"values": None, "confidence": "low", "notes": "LLM failed"}
    result = parse_json_response(response)
    if not result:
        nums = re.findall(r"[\d,]+\.?\d*", response.replace(",", ""))
        if nums:
            try:
                return {"values": float(nums[0]), "confidence": "low", "notes": "Parsed from raw"}
            except ValueError:
                pass
        return {"values": None, "confidence": "low", "notes": "Parse failed"}
    return result


# == Phase 6: Verify ==========================================================


def verify_value(subquery, extraction_result, focused_data):
    """Phase 6: Sanity-check extracted values."""
    values = extraction_result.get("values")
    if values is None:
        return extraction_result
    warnings = []
    if isinstance(values, list):
        for i, v in enumerate(values):
            if v is not None and not isinstance(v, (int, float)):
                try:
                    float(v)
                except (ValueError, TypeError):
                    warnings.append(f"Non-numeric at index {i}: {v}")
    elif not isinstance(values, (int, float)):
        try:
            float(values)
        except (ValueError, TypeError):
            warnings.append(f"Non-numeric value: {values}")
    col_hint = subquery.get("column_hint", "")
    src_col = extraction_result.get("source_column", "")
    if col_hint and src_col:
        hw = set(re.findall(r"\w+", col_hint.lower()))
        sw = set(re.findall(r"\w+", src_col.lower()))
        if len(hw & sw) < len(hw) * 0.5 and len(hw) > 1:
            warnings.append(f"Column mismatch: '{col_hint}' vs '{src_col}'")
        # Contradictory term check: gross vs net
        _contra = [("gross", "net"), ("receipts", "expenditures"),
                   ("imports", "exports")]
        hint_low = col_hint.lower()
        src_low = src_col.lower()
        for a, b in _contra:
            if (a in hint_low and b in src_low) or (b in hint_low and a in src_low):
                warnings.append(f"Contradictory terms: hint='{col_hint}' vs source='{src_col}'")
    vtype = subquery.get("value_type", "single")
    if vtype == "monthly_series" and isinstance(values, list) and len(values) != 12:
        warnings.append(f"Expected 12 monthly values, got {len(values)}")
    if warnings:
        extraction_result = dict(extraction_result)
        extraction_result["confidence"] = "low"
        old = extraction_result.get("notes", "")
        extraction_result["notes"] = "; ".join(warnings) + (f" | {old}" if old else "")
    return extraction_result


# == Phase 7: Compute =========================================================


def parse_number(v):
    """Parse a value to float."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        v = v.strip().replace(",", "")
        if v in ("-", "", "nan", "null", "None"):
            return 0.0
        v = re.sub(r"\s*\d+/\s*$", "", v)
        v = re.sub(r"\s*[r]\s*$", "", v, flags=re.IGNORECASE)
        try:
            return float(v)
        except ValueError:
            return None
    return None


def resolve_subquery_value(extraction_result):
    """Turn extraction result into numeric value or list."""
    values = extraction_result.get("values")
    if values is None:
        return None
    if isinstance(values, list):
        return [n for v in values for n in [parse_number(v)] if n is not None]
    return parse_number(values)


def safe_eval_expr(expression, variables):
    """Evaluate a math expression with named variables using AST."""
    def _eval(node):  # noqa: C901
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return float(node.value)
            raise ValueError("only numeric constants")
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"unknown variable: {node.id}")
            return float(variables[node.id])
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -_eval(node.operand)
            if isinstance(node.op, ast.UAdd):
                return _eval(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = _eval(node.left), _eval(node.right)
            _ops = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                    ast.Mult: lambda a, b: a * b, ast.Pow: lambda a, b: a**b,
                    ast.Mod: lambda a, b: a % b}
            op_type = type(node.op)
            if op_type == ast.Div:
                if right == 0: raise ValueError("division by zero")
                return left / right
            if op_type in _ops: return _ops[op_type](left, right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn, args = node.func.id, [_eval(a) for a in node.args]
            _fns = {"abs": lambda a: builtins.abs(a[0]), "sqrt": lambda a: math.sqrt(a[0]),
                    "log": lambda a: math.log(*a), "pow": lambda a: a[0]**a[1],
                    "min": min, "max": max,
                    "round": lambda a: builtins.round(a[0], int(a[1])) if len(a) == 2 else builtins.round(a[0])}
            if fn in _fns: return _fns[fn](args)
            raise ValueError(f"unsupported function: {fn}")
        raise ValueError(f"unsupported node: {type(node).__name__}")

    tree = ast.parse(expression.strip().replace("^", "**"), mode="eval")
    return _eval(tree)


def _to_scalar(v):
    """Collapse list to sum, pass through scalars."""
    if isinstance(v, list):
        return sum(x for x in v if x is not None)
    return v


def _make_vars(resolved):
    """Build {id: scalar} from resolved values."""
    return {k: _to_scalar(v) for k, v in resolved.items() if v is not None}


def compute(plan, extracted):
    """Phase 7: Deterministic computation on extracted values."""
    comp = plan.get("computation", {})
    comp_type = comp.get("type", "direct")
    formula = comp.get("formula", "")
    fmt = plan.get("output_format", {})
    rounding = fmt.get("rounding")
    suffix = fmt.get("suffix", "")
    sq_ids = [sq["id"] for sq in plan.get("sub_queries", [])]
    resolved = {}
    for sid in sq_ids:
        val = resolve_subquery_value(extracted.get(sid, {}))
        if val is None:
            print(f"  WARNING: sub-query {sid} returned None", file=sys.stderr)
        resolved[sid] = val
    print(f"  Resolved values: {resolved}", file=sys.stderr)
    result = None
    try:
        if comp_type == "direct":
            v = resolved.get(sq_ids[0])
            if isinstance(v, list):
                result = v[0] if len(v) == 1 else sum(v)
            else:
                result = v
        elif comp_type == "sum":
            v = resolved.get(sq_ids[0])
            if isinstance(v, list):
                result = sum(x for x in v if x is not None)
            else:
                result = sum(_to_scalar(x) for x in resolved.values() if x is not None)
        elif comp_type in ("difference", "percent_change", "ratio") and len(sq_ids) >= 2:
            a = _to_scalar(resolved.get(sq_ids[0]))
            b = _to_scalar(resolved.get(sq_ids[1]))
            if a is not None and b is not None:
                if comp_type == "difference":
                    result = abs(b - a)
                elif comp_type == "percent_change" and a != 0:
                    result = abs((b - a) / a) * 100
                elif comp_type == "ratio" and b != 0:
                    result = a / b
        elif comp_type == "geometric_mean":
            vals = []
            for v in resolved.values():
                if isinstance(v, list):
                    vals.extend(v)
                elif v is not None:
                    vals.append(v)
            if vals:
                p = 1.0
                for v in vals:
                    p *= v
                result = p ** (1.0 / len(vals))
        elif formula:
            try:
                result = safe_eval_expr(formula, _make_vars(resolved))
            except Exception:
                v = resolved.get(sq_ids[0]) if sq_ids else None
                result = _to_scalar(v)
    except Exception as e:
        print(f"  Compute error: {e}", file=sys.stderr)
        telemetry("compute_error", {"error": str(e)})
    if result is None:
        return "N/A"
    if rounding is not None:
        result = round(result, rounding)
    r = float(result)
    if rounding is not None and rounding == 0:
        formatted = f"{int(r):,}"
    elif rounding is not None:
        formatted = f"{r:,.{rounding}f}"
    elif r == int(r) and abs(r) >= 1:
        formatted = f"{int(r):,}"
    else:
        formatted = f"{r:,.2f}" if abs(r) < 100 else f"{r:,.0f}"
    if suffix:
        formatted = formatted + suffix
    return formatted


# == Main Pipeline =============================================================


def _process_subquery(sq):
    """Process a single sub-query through phases 2-6."""
    sq_id = sq["id"]
    desc = sq.get("description", "")[:80]
    # Phase 2: Search tables
    print(f"  [{sq_id}] Searching tables: {desc}", file=sys.stderr)
    candidates = search_tables(sq)
    if not candidates:
        print(f"  [{sq_id}] WARNING: No tables found", file=sys.stderr)
        return sq_id, {"values": None, "confidence": "low", "notes": "No tables"}, ""
    print(f"  [{sq_id}] Found {len(candidates)} candidate(s)", file=sys.stderr)
    # Phase 3: Select table
    selected = select_table(sq, candidates)
    if not selected:
        return sq_id, {"values": None, "confidence": "low", "notes": "Select failed"}, ""
    print(f"  [{sq_id}] Selected: {selected['title'][:80]}", file=sys.stderr)
    # Phase 4: Read focused data
    focused = search_data(sq, selected)
    if not focused:
        return sq_id, {"values": None, "confidence": "low", "notes": "No data rows"}, ""
    print(f"  [{sq_id}] Loaded {len(focused)} chars", file=sys.stderr)
    # Phase 5: Extract
    extraction = extract_value(sq, focused)
    print(f"  [{sq_id}] Extracted: values={extraction.get('values')}, "
          f"conf={extraction.get('confidence', '?')}", file=sys.stderr)
    # Phase 6: Verify
    extraction = verify_value(sq, extraction, focused)
    if extraction.get("confidence") == "low":
        print(f"  [{sq_id}] LOW confidence: {extraction.get('notes', '')}", file=sys.stderr)

    # Retry with next candidate if we got None
    if extraction.get("values") is None and len(candidates) > 1:
        for alt in candidates:
            if alt is selected:
                continue
            print(f"  [{sq_id}] Retrying with: {alt['title'][:60]}", file=sys.stderr)
            alt_data = search_data(sq, alt)
            if not alt_data:
                continue
            alt_ext = extract_value(sq, alt_data)
            if alt_ext.get("values") is not None:
                alt_ext = verify_value(sq, alt_ext, alt_data)
                print(f"  [{sq_id}] Retry got: {alt_ext.get('values')}", file=sys.stderr)
                extraction = alt_ext
                focused = alt_data
                break

    return sq_id, extraction, focused


# fmt: off
PLAN_REVIEW_SYSTEM = "You check research plans for Treasury data questions. Verify: all years mentioned are covered by sub-queries, computation type matches the question (percent change? difference? sum?), calendar vs fiscal year is handled correctly, rounding matches what was asked. Respond JSON only: {\"approved\": true, \"fixes\": []} or {\"approved\": false, \"fixes\": [\"fix1\", \"fix2\"]}"

LIBRARIAN_REVIEW_SYSTEM = "The team brought back finished work. You see the question, what each sub-query found, and the computed answer. Check: right columns used? right years? answer formatted as asked (commas? percent? decimal places? millions?)? If wrong, fix what you can. Respond JSON only: {\"answer\": \"formatted answer\", \"note\": \"optional fix note\"}"
# fmt: on


def review_plan(question, plan):
    """Check the librarian's plan before executing."""
    sqs = plan.get("sub_queries", [])
    comp = plan.get("computation", {})
    fmt = plan.get("output_format", {})
    parts = [f"QUESTION: {question}", f"PLAN: {len(sqs)} sub-queries"]
    for sq in sqs:
        parts.append(f"  [{sq['id']}] {sq.get('description', '')[:100]}")
        parts.append(f"      year={sq.get('data_year')} months={sq.get('data_months')} "
                     f"type={sq.get('value_type')} basis={sq.get('period_basis')}")
    parts.append(f"Computation: {comp.get('type')} — {comp.get('description', '')[:100]}")
    parts.append(f"Formula: {comp.get('formula', 'none')}")
    parts.append(f"Format: units={fmt.get('units')}, rounding={fmt.get('rounding')}, "
                 f"suffix='{fmt.get('suffix', '')}'")
    resp = call_llm(PLAN_REVIEW_SYSTEM, "\n".join(parts), max_tokens=256)
    if resp:
        r = parse_json_response(resp)
        if r and not r.get("approved", True):
            return r.get("fixes", [])
    return []


def librarian_review(question, plan, extracted, computed_answer):
    """Final review: format and sanity-check the answer."""
    parts = [f"QUESTION: {question}", "\nSUB-QUERY RESULTS:"]
    for sq in plan.get("sub_queries", []):
        ext = extracted.get(sq["id"], {})
        parts.append(f"  [{sq['id']}] {sq.get('description', '')[:100]}")
        parts.append(f"      Values: {ext.get('values')}")
        parts.append(f"      Source: {ext.get('source_row', '?')} / {ext.get('source_column', '?')}")
    comp = plan.get("computation", {})
    parts.append(f"\nComputation: {comp.get('type', '?')} — {comp.get('formula', '')}")
    parts.append(f"COMPUTED ANSWER: {computed_answer}")
    fmt = plan.get("output_format", {})
    if fmt:
        parts.append(f"Expected: units={fmt.get('units')}, rounding={fmt.get('rounding')}, "
                     f"suffix='{fmt.get('suffix', '')}'")
    resp = call_llm(LIBRARIAN_REVIEW_SYSTEM, "\n".join(parts), max_tokens=256)
    if resp:
        r = parse_json_response(resp)
        if r and r.get("answer"):
            note = r.get("note", "")
            if note:
                print(f"  Librarian note: {note}", file=sys.stderr)
            return str(r["answer"]).strip()
    return computed_answer


def solve(question):
    """Run the full pipeline."""
    t0 = time.time()
    telemetry("solve_start", {"question": question[:300]})

    # Phase 1: Decompose
    plan = decompose(question)
    if not plan:
        print("FATAL: Decomposition failed", file=sys.stderr)
        telemetry("solve_fail", {"phase": "decompose"})
        return "N/A"
    sub_queries = plan.get("sub_queries", [])
    if not sub_queries:
        print("FATAL: No sub-queries", file=sys.stderr)
        return "N/A"

    # Phase 1b: Plan review
    print("Phase 1b: Reviewing plan...", file=sys.stderr)
    fixes = review_plan(question, plan)
    if fixes:
        print(f"  Fixes needed: {fixes}", file=sys.stderr)
        feedback = (f"Issues found with your plan:\n"
                    + "\n".join(f"- {f}" for f in fixes)
                    + f"\n\nRevise the plan for: {question}")
        plan2 = decompose(feedback)
        if plan2 and plan2.get("sub_queries"):
            plan = plan2
            sub_queries = plan["sub_queries"]
            print(f"  Revised: {len(sub_queries)} sub-queries", file=sys.stderr)
    else:
        print("  Plan approved", file=sys.stderr)

    # Phases 2-6 in parallel
    print("Phases 2-6: Processing sub-queries...", file=sys.stderr)
    extracted = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_process_subquery, sq): sq["id"] for sq in sub_queries}
        for future in concurrent.futures.as_completed(futures):
            try:
                sq_id, result, _ = future.result()
                extracted[sq_id] = result
            except Exception as e:
                sq_id = futures[future]
                extracted[sq_id] = {"values": None, "confidence": "low",
                                    "notes": f"Exception: {e}"}

    # Phase 7: Compute
    print("Phase 7: Computing...", file=sys.stderr)
    answer = compute(plan, extracted)
    print(f"  Computed: {answer}", file=sys.stderr)

    # Phase 8: Librarian final review
    print("Phase 8: Final review...", file=sys.stderr)
    answer = librarian_review(question, plan, extracted, answer)
    elapsed = time.time() - t0
    print(f"  Final: {answer} ({elapsed:.1f}s)", file=sys.stderr)
    telemetry("solve_done", {"answer": str(answer)[:200], "elapsed": f"{elapsed:.1f}s"})
    return answer


def main():
    """Entry point."""
    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} "QUESTION"', file=sys.stderr)
        sys.exit(1)
    question = sys.argv[1]
    print(f"Question: {question}", file=sys.stderr)
    answer = solve(question)
    answer_path = Path(ANSWER_PATH)
    answer_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.write_text(str(answer))
    print(f"Answer written to {answer_path}: {answer}", file=sys.stderr)


if __name__ == "__main__":
    main()
