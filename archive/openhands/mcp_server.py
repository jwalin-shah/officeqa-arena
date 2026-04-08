#!/usr/bin/env python3
"""Lean MCP server — 5 high-leverage tools over stdio JSON-RPC 2.0.

Tools: find_values, read_page, compute, verify, submit_answer
Parses Treasury Bulletin files from /app/resources/ on startup.
Zero external dependencies.
"""
from __future__ import annotations

import difflib
import json
import math
import os
import re
import sqlite3
import statistics
import sys
import unicodedata
from pathlib import Path

# ── Resource parsing ──────────────────────────────────────────────────

RESOURCES_DIR = os.environ.get("RESOURCES_DIR", "/app/resources")

_tables: list[dict] = []         # parsed tables from resource files
_manifest: dict = {}             # manifest.json contents
_raw_texts: dict[str, str] = {}  # filename -> full text content
_page_texts: dict[str, str] = {} # filename -> page text content


def _parse_manifest():
    global _manifest
    mpath = Path(RESOURCES_DIR) / "manifest.json"
    if mpath.exists():
        try:
            _manifest = json.loads(mpath.read_text())
        except Exception:
            _manifest = {}


def _normalize_text(s: str) -> str:
    """Normalize text for search: NFKC, lowercase, strip punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    # Unify dashes
    s = re.sub(r"[–—−‐]", "-", s)
    # Strip punctuation except %, -, .
    s = re.sub(r"[^\w\s%\-.]", " ", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_numeric(s: str) -> float | None:
    """Try to parse a string as a number. Returns None if not numeric."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip().replace(",", "").replace("$", "").replace("%", "")
    # Handle parenthetical negatives: (123) -> -123
    m = re.match(r"^\(([0-9.]+)\)$", s)
    if m:
        s = "-" + m.group(1)
    # Handle footnote markers: 123 1/ -> 123
    s = re.sub(r"\s+\d+/\s*$", "", s)
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _detect_period_basis(text: str) -> str:
    """Detect fiscal vs calendar year from surrounding text."""
    t = text.lower()
    if "fiscal year" in t or "fiscal yr" in t:
        return "fiscal"
    if "calendar year" in t or "calendar yr" in t:
        return "calendar"
    # Month columns suggest calendar
    months = ["january", "february", "march", "april", "may", "june",
              "july", "august", "september", "october", "november", "december"]
    if any(m in t for m in months):
        return "calendar"
    return "unknown"


def _detect_units(text: str) -> str:
    """Detect unit scale from table text."""
    t = text.lower()
    if "in millions" in t or "(millions)" in t:
        return "millions"
    if "in thousands" in t or "(thousands)" in t:
        return "thousands"
    if "in billions" in t or "(billions)" in t:
        return "billions"
    if "percent" in t or "%" in t:
        return "percent"
    return ""


def _parse_table_from_text(text: str, source_file: str) -> list[dict]:
    """Extract tables from a page text file."""
    tables = []
    if "<table>" not in text:
        return tables

    parts = text.split("<table>")
    preamble = parts[0]
    for i, part in enumerate(parts[1:], 1):
        end = part.find("</table>")
        table_html = part[:end] if end >= 0 else part
        rows = []
        for tr_match in re.finditer(r"<tr>(.*?)</tr>", table_html, re.DOTALL):
            cells = re.findall(r"<t[hd]>(.*?)</t[hd]>", tr_match.group(1))
            if cells:
                rows.append([c.strip() for c in cells])
        if rows:
            # Smart header detection: find the row with the most non-empty cells
            # Treasury tables often have multi-row headers with colspan
            header_idx = 0
            if len(rows) > 1:
                # Check if first row is a grouped header (has few cells or empty cells)
                first_nonempty = sum(1 for c in rows[0] if c.strip())
                second_nonempty = sum(1 for c in rows[1] if c.strip()) if len(rows) > 1 else 0
                if second_nonempty > first_nonempty and first_nonempty <= 2:
                    header_idx = 1  # Use second row as header
                # Also check: if first row cells are all empty or just labels
                if all(not c.strip() or len(c.strip()) > 30 for c in rows[0]):
                    header_idx = 1

            header = rows[header_idx] if rows else []
            data_rows = rows[header_idx + 1:] if len(rows) > header_idx + 1 else rows

            title = ""
            pre_lines = [l.strip() for l in preamble.strip().split("\n") if l.strip()]
            if pre_lines:
                title = pre_lines[-1]
            # Use grouped header row as title if we skipped it
            if header_idx > 0 and rows[0]:
                grouped = " ".join(c.strip() for c in rows[0] if c.strip())
                if grouped:
                    title = grouped if not title else title + " - " + grouped

            # Detect metadata from title + preamble + header
            context_text = preamble + " " + title + " " + " ".join(header)
            period_basis = _detect_period_basis(context_text)
            units = _detect_units(context_text)

            tables.append({
                "source": source_file,
                "table_idx": i,
                "title": title,
                "header": header,
                "rows": data_rows,
                "period_basis": period_basis,
                "units": units,
                "raw_text": table_html[:2000],
            })
            preamble = part[end + len("</table>"):] if end >= 0 else ""
    return tables


def _parse_markdown_tables(text: str, source_file: str) -> list[dict]:
    """Parse pipe-delimited markdown tables from Databricks-transformed TXT files.

    These have flattened multi-level headers with ' > ' separators.
    """
    tables = []
    lines = text.split("\n")
    i = 0
    tbl_idx = 0
    while i < len(lines):
        line = lines[i].strip()
        # Detect table: line starts with |
        if line.startswith("|") and "|" in line[1:]:
            # Collect all consecutive pipe-delimited lines
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1

            if len(table_lines) < 2:
                continue

            # Parse header (first line)
            header_raw = [c.strip() for c in table_lines[0].split("|")[1:-1]]
            # Extract leaf label from hierarchical headers (after last ' > ')
            header = []
            for h in header_raw:
                parts = h.split(" > ")
                leaf = parts[-1].strip() if parts else h
                # Clean "Unnamed:" artifacts
                if leaf.startswith("Unnamed:") or not leaf:
                    leaf = parts[-2].strip() if len(parts) > 1 else ""
                header.append(leaf)

            # Skip separator line (| --- | --- |)
            data_start = 1
            if len(table_lines) > 1 and all(c.strip() in ("-", "---", "----", "") for c in table_lines[1].split("|")[1:-1]):
                data_start = 2

            # Parse data rows
            rows = []
            for tl in table_lines[data_start:]:
                cells = [c.strip() for c in tl.split("|")[1:-1]]
                if cells:
                    rows.append(cells)

            if header and rows:
                tbl_idx += 1
                # Get title from lines above table
                title = ""
                for j in range(max(0, i - len(table_lines) - 5), i - len(table_lines)):
                    candidate = lines[j].strip()
                    if candidate and not candidate.startswith("|") and len(candidate) > 5:
                        title = candidate
                        break

                context_text = title + " " + " ".join(header_raw[:5])
                period_basis = _detect_period_basis(context_text)
                units = _detect_units(context_text)

                tables.append({
                    "source": source_file,
                    "table_idx": tbl_idx,
                    "title": title,
                    "header": header,
                    "rows": rows,
                    "period_basis": period_basis,
                    "units": units,
                    "raw_text": "\n".join(table_lines[:5]),
                })
        else:
            i += 1
    return tables


def _load_resources():
    global _tables, _raw_texts, _page_texts
    rdir = Path(RESOURCES_DIR)
    if not rdir.exists():
        return

    _parse_manifest()

    for fpath in sorted(rdir.iterdir()):
        if fpath.name.startswith("."):
            continue
        if fpath.suffix == ".txt":
            text = fpath.read_text(errors="replace")
            _raw_texts[fpath.name] = text
            # Parse tables: try markdown pipes first (Databricks transformed format)
            if "|" in text and "| ---" in text:
                tables = _parse_markdown_tables(text, fpath.name)
                _tables.extend(tables)
            # Also try HTML tables (page extracts)
            if "<table>" in text:
                tables = _parse_table_from_text(text, fpath.name)
                _tables.extend(tables)
        elif fpath.suffix == ".json" and fpath.name != "manifest.json":
            try:
                data = json.loads(fpath.read_text())
                # Format 1: document.elements[] with type="table" and HTML content
                if isinstance(data, dict) and "document" in data:
                    elements = data["document"].get("elements", [])
                    tbl_idx = 0
                    for el in elements:
                        if el.get("type") == "table" and el.get("content"):
                            tbl_idx += 1
                            tables = _parse_table_from_text(
                                el["content"], fpath.name
                            )
                            for t in tables:
                                t["table_idx"] = tbl_idx
                            _tables.extend(tables)
                # Format 2: pages[].tables[] (legacy)
                elif isinstance(data, dict) and "pages" in data:
                    for page in data["pages"]:
                        for tbl in page.get("tables", []):
                            _tables.append({
                                "source": fpath.name,
                                "table_idx": tbl.get("table_index", 0),
                                "title": tbl.get("title", ""),
                                "header": tbl.get("header", []),
                                "rows": tbl.get("rows", []),
                                "period_basis": "unknown",
                                "units": "",
                                "raw_text": json.dumps(tbl)[:2000],
                            })
            except Exception:
                pass

    # Assign global indices
    for gi, t in enumerate(_tables):
        t["global_idx"] = gi


# ── FTS5 search index (difflib + sqlite3 full-text search) ───────────

_fts_conn: sqlite3.Connection | None = None
_all_labels: list[str] = []


def _build_fts_index():
    """Build in-memory FTS5 index from parsed tables for ranked search."""
    global _fts_conn, _all_labels
    _fts_conn = sqlite3.connect(":memory:")
    try:
        _fts_conn.execute(
            'CREATE VIRTUAL TABLE fts USING fts5('
            'text, table_idx, row_idx, label_type, '
            'tokenize="porter unicode61")'
        )
    except Exception:
        # FTS5 not available — fall back to keyword-only search
        print("WARNING: FTS5 not available, using keyword fallback", file=sys.stderr)
        _fts_conn = None
        return
    rows_to_insert = []
    label_set = set()

    for t in _tables:
        gi = t["global_idx"]
        # Index table title (normalized for search)
        if t["title"]:
            norm_title = _normalize_text(t["title"])
            rows_to_insert.append((norm_title, str(gi), "-1", "title"))
            label_set.add(norm_title)
        # Index column headers
        for h in t["header"]:
            if h and len(h) > 1:
                norm_h = _normalize_text(h)
                rows_to_insert.append((norm_h, str(gi), "-1", "header"))
                label_set.add(norm_h)
        # Index row labels (first cell of each row)
        for ri, row in enumerate(t["rows"]):
            if row and row[0] and len(str(row[0])) > 1:
                norm_label = _normalize_text(str(row[0]))
                rows_to_insert.append((norm_label, str(gi), str(ri), "row"))
                label_set.add(norm_label)

    _fts_conn.executemany("INSERT INTO fts VALUES (?, ?, ?, ?)", rows_to_insert)
    _fts_conn.commit()
    # Build word-level vocabulary for difflib (individual words, not full labels)
    word_set = set()
    for label in label_set:
        for w in re.findall(r'[a-z]+', label):
            if len(w) > 2:
                word_set.add(w)
    _all_labels = list(word_set)


def _fts_search(query: str, limit: int = 20) -> list[tuple[int, int, float, str]]:
    """Search FTS5 index with difflib-expanded terms.

    Returns list of (table_idx, row_idx, rank, matched_text).
    """
    if not _fts_conn:
        return []

    # Normalize and clean query terms
    query = _normalize_text(query)
    terms = set()
    for word in re.findall(r'[a-z0-9]+', query):
        if len(word) > 1:
            terms.add(word)

    # Expand via difflib fuzzy matching against known labels
    for word in list(terms):
        matches = difflib.get_close_matches(word, _all_labels, n=3, cutoff=0.55)
        for m in matches:
            for w in re.findall(r'[a-z]+', m.lower()):
                if len(w) > 2:
                    terms.add(w)

    if not terms:
        return []

    # Build FTS5 query with OR
    fts_query = " OR ".join(f'"{t}"' for t in terms)
    try:
        rows = _fts_conn.execute(
            "SELECT text, table_idx, row_idx, rank FROM fts "
            "WHERE fts MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, limit),
        ).fetchall()
        return [(int(r[1]), int(r[2]), r[3], r[0]) for r in rows]
    except Exception:
        return []


# ── Tool implementations ──────────────────────────────────────────────

def tool_find_values(query: str, year: str = "", month: str = "") -> dict:
    """One-shot search: find values matching a query across all tables.

    Uses FTS5 + difflib for fuzzy ranked search, then extracts values
    with full provenance.
    """
    if not query or not query.strip():
        return {"status": "error", "msg": "query cannot be empty"}
    year_str = str(year).strip() if year else ""
    month_str = month.strip().lower() if month else ""

    # Phase 1: FTS5 search to find relevant tables and rows
    search_query = query
    if year_str:
        search_query += " " + year_str
    if month_str:
        search_query += " " + month_str

    fts_hits = _fts_search(search_query, limit=30)

    # Group hits by table, accumulate scores
    table_scores: dict[int, float] = {}
    row_hits: dict[tuple[int, int], float] = {}  # (table_idx, row_idx) -> score

    for tbl_idx, row_idx, rank, text in fts_hits:
        # rank is negative (more negative = better match)
        score = -rank
        table_scores[tbl_idx] = table_scores.get(tbl_idx, 0) + score
        if row_idx >= 0:
            key = (tbl_idx, row_idx)
            row_hits[key] = row_hits.get(key, 0) + score
        else:
            # Title/header match — include ALL rows from this table
            if tbl_idx < len(_tables):
                for ri in range(len(_tables[tbl_idx]["rows"])):
                    key = (tbl_idx, ri)
                    row_hits[key] = row_hits.get(key, 0) + score * 0.5

    # Phase 2: Also do direct keyword matching on query terms (fallback)
    query_lower = query.lower()
    terms = query_lower.split()
    for t in _tables:
        gi = t["global_idx"]
        title_lower = t["title"].lower()
        header_lower = " ".join(t["header"]).lower()
        kw_score = 0
        for term in terms:
            if term in title_lower:
                kw_score += 3
            elif term in header_lower:
                kw_score += 2
        if kw_score > 0:
            table_scores[gi] = table_scores.get(gi, 0) + kw_score

        if gi not in table_scores:
            continue
        for ri, row in enumerate(t["rows"]):
            if row and any(term in str(row[0]).lower() for term in terms):
                key = (gi, ri)
                row_hits[key] = row_hits.get(key, 0) + 2

    # Phase 3: Extract values from top-scoring rows
    scored_results = []
    for (tbl_idx, row_idx), row_score in sorted(row_hits.items(), key=lambda x: -x[1]):
        if tbl_idx >= len(_tables):
            continue
        t = _tables[tbl_idx]
        if row_idx >= len(t["rows"]):
            continue
        row = t["rows"][row_idx]
        combined_score = table_scores.get(tbl_idx, 0) + row_score

        # Find target column
        col_idx = -1
        if year_str:
            for ci, h in enumerate(t["header"]):
                if year_str in h:
                    col_idx = ci
                    break
        if month_str and col_idx < 0:
            for ci, h in enumerate(t["header"]):
                if month_str in h.lower():
                    col_idx = ci
                    break

        if col_idx >= 0 and col_idx < len(row):
            val_raw = str(row[col_idx])
            scored_results.append({
                "value": val_raw,
                "numeric": _clean_numeric(val_raw),
                "row_label": row[0] if row else "",
                "column": t["header"][col_idx] if col_idx < len(t["header"]) else "",
                "source": t["source"],
                "title": t["title"][:120],
                "units": t["units"],
                "period_basis": t["period_basis"],
                "score": round(combined_score, 2),
            })
        else:
            # Return full row mapped to headers
            row_data = {}
            for ci, h in enumerate(t["header"]):
                if ci < len(row):
                    row_data[h] = row[ci]
            scored_results.append({
                "value": row_data,
                "row_label": row[0] if row else "",
                "source": t["source"],
                "title": t["title"][:120],
                "units": t["units"],
                "period_basis": t["period_basis"],
                "header": t["header"],
                "score": round(combined_score, 2),
            })

    scored_results.sort(key=lambda x: x["score"], reverse=True)
    top = scored_results[:5]

    return {
        "status": "ok" if top else "no_results",
        "count": len(scored_results),
        "results": top,
    }


def tool_read_page(filename: str, pattern: str = "") -> dict:
    """Read a resource file, optionally filtered by pattern."""
    # Find file
    text = _page_texts.get(filename) or _raw_texts.get(filename)
    if text is None:
        for k in {**_raw_texts, **_page_texts}:
            if filename in k:
                text = _page_texts.get(k) or _raw_texts.get(k)
                filename = k
                break
    if text is None:
        return {
            "status": "error",
            "msg": f"Not found: {filename}",
            "files": sorted(list(_raw_texts.keys()) + list(_page_texts.keys())),
        }

    if pattern:
        # Filter to lines matching pattern (case-insensitive) with context
        pattern_lower = pattern.lower()
        lines = text.split("\n")
        matches = []
        for li, line in enumerate(lines):
            if pattern_lower in line.lower():
                start = max(0, li - 1)
                end = min(len(lines), li + 2)
                matches.append("\n".join(lines[start:end]))
        return {
            "status": "ok" if matches else "no_match",
            "file": filename,
            "matches": matches[:10],
        }

    # Return full content (truncated)
    return {
        "status": "ok",
        "file": filename,
        "lines": len(text.split("\n")),
        "content": text[:8000],
    }


def tool_compute(expression: str, variables: dict = None) -> dict:
    """Evaluate math expressions with full statistics support.

    Built-in functions: sum, mean, median, geometric_mean, harmonic_mean,
    stdev, variance, correlation, linear_regression, percent_change,
    growth_rate, cagr, round, floor, ceil, sqrt, log, log10, abs, min, max, pow.
    """
    variables = variables or {}
    try:
        expr = expression.strip()
        # Block dangerous operations
        for blocked in ["import", "exec", "eval", "open", "__", "os.", "sys.", "getattr"]:
            if blocked in expr:
                return {"status": "error", "msg": f"Blocked: {blocked}"}

        def _percent_change(old, new):
            if old == 0:
                return float("inf") if new != 0 else 0.0
            return ((new - old) / abs(old)) * 100

        def _growth_rate(values):
            """Average period-over-period growth rate in percent."""
            if len(values) < 2:
                return 0.0
            rates = []
            for i in range(1, len(values)):
                if values[i - 1] != 0:
                    rates.append((values[i] - values[i - 1]) / abs(values[i - 1]) * 100)
            return statistics.mean(rates) if rates else 0.0

        def _cagr(start_val, end_val, years):
            if start_val <= 0 or years <= 0:
                return 0.0
            return ((end_val / start_val) ** (1.0 / years) - 1) * 100

        def _linear_regression(x_vals, y_vals):
            if len(x_vals) != len(y_vals) or len(x_vals) < 2:
                return {"error": "Need equal-length lists with >= 2 points"}
            n = len(x_vals)
            x_mean = statistics.mean(x_vals)
            y_mean = statistics.mean(y_vals)
            ss_xx = sum((xi - x_mean) ** 2 for xi in x_vals)
            ss_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x_vals, y_vals))
            ss_yy = sum((yi - y_mean) ** 2 for yi in y_vals)
            if ss_xx == 0:
                return {"slope": 0, "intercept": y_mean, "r_squared": 0}
            slope = ss_xy / ss_xx
            intercept = y_mean - slope * x_mean
            r_squared = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_yy != 0 else 0
            return {"slope": slope, "intercept": intercept, "r_squared": r_squared}

        def _correlation(x_vals, y_vals):
            if len(x_vals) != len(y_vals) or len(x_vals) < 2:
                return 0.0
            n = len(x_vals)
            x_mean = statistics.mean(x_vals)
            y_mean = statistics.mean(y_vals)
            ss_xx = sum((xi - x_mean) ** 2 for xi in x_vals)
            ss_yy = sum((yi - y_mean) ** 2 for yi in y_vals)
            ss_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x_vals, y_vals))
            denom = math.sqrt(ss_xx * ss_yy)
            return ss_xy / denom if denom != 0 else 0.0

        safe_ns = {
            # Basic
            "abs": abs, "round": round, "min": min, "max": max,
            "sum": sum, "len": len, "pow": pow, "int": int, "float": float,
            # Math
            "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
            "log2": math.log2, "exp": math.exp, "pi": math.pi, "e": math.e,
            "floor": math.floor, "ceil": math.ceil,
            # Statistics
            "mean": statistics.mean, "median": statistics.median,
            "geometric_mean": statistics.geometric_mean,
            "harmonic_mean": statistics.harmonic_mean,
            "stdev": statistics.stdev, "variance": statistics.variance,
            # Custom
            "percent_change": _percent_change,
            "growth_rate": _growth_rate,
            "cagr": _cagr,
            "linear_regression": _linear_regression,
            "correlation": _correlation,
        }
        safe_ns.update(variables)

        result = eval(expr, {"__builtins__": {}}, safe_ns)
        # Format output
        if isinstance(result, float):
            # Avoid floating point noise
            if result == int(result) and abs(result) < 1e15:
                result = int(result)
            else:
                result = round(result, 10)
        return {"status": "ok", "result": result}
    except Exception as exc:
        return {"status": "error", "msg": str(exc), "expr": expression}


def tool_verify(answer: str, question_type: str = "") -> dict:
    """Sanity-check an answer before submitting.

    Checks: is it numeric, reasonable magnitude, correct sign, etc.
    question_type: optional hint like 'percentage', 'dollar_amount', 'count'
    """
    warnings = []
    clean = str(answer).strip().replace(",", "").replace("$", "").replace("%", "")

    # Try parsing
    try:
        val = float(clean)
    except ValueError:
        return {"status": "warn", "warnings": ["Answer is not numeric"], "answer": answer}

    # Check common issues
    if math.isnan(val) or math.isinf(val):
        warnings.append("Answer is NaN or Inf")

    qtype = (question_type or "").lower()

    if qtype == "percentage":
        if abs(val) > 10000:
            warnings.append(f"Percentage {val}% seems too large")
        if abs(val) < 0.0001 and val != 0:
            warnings.append(f"Percentage {val}% seems too small — check decimal placement")

    if qtype in ("dollar_amount", "amount"):
        if val < 0:
            warnings.append("Negative dollar amount — verify sign")

    # Format suggestion
    if val == int(val) and abs(val) < 1e15:
        formatted = str(int(val))
    else:
        formatted = f"{val:.2f}"

    return {
        "status": "ok" if not warnings else "warn",
        "answer": formatted,
        "numeric": val,
        "warnings": warnings,
    }


def tool_submit_answer(answer: str) -> dict:
    """Write the final answer to /app/answer.txt."""
    try:
        answer_path = Path("/app/answer.txt")
        answer_path.parent.mkdir(parents=True, exist_ok=True)
        answer_path.write_text(str(answer).strip())
        return {"status": "ok", "answer": str(answer).strip()}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}


# ── Tool registry ─────────────────────────────────────────────────────

TOOLS = {
    "find_values": {
        "fn": lambda **kw: tool_find_values(**kw),
        "schema": {
            "name": "find_values",
            "description": "Search all tables for values matching a query. Returns top 3 matches with value, row label, column label, source file, units, and period basis. This is your PRIMARY data retrieval tool.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords (e.g. 'national defense expenditures')"},
                    "year": {"type": "string", "description": "Target year (e.g. '2020', '1995')", "default": ""},
                    "month": {"type": "string", "description": "Target month (e.g. 'January', 'March')", "default": ""},
                },
                "required": ["query"],
            },
        },
    },
    "read_page": {
        "fn": lambda **kw: tool_read_page(**kw),
        "schema": {
            "name": "read_page",
            "description": "Read a resource file. Optionally filter by pattern. Use when find_values is not enough and you need to see raw data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename or partial match in /app/resources/"},
                    "pattern": {"type": "string", "description": "Optional filter pattern (case-insensitive)", "default": ""},
                },
                "required": ["filename"],
            },
        },
    },
    "compute": {
        "fn": lambda **kw: tool_compute(**kw),
        "schema": {
            "name": "compute",
            "description": "Evaluate math expressions. Use for ALL arithmetic. Has: sum, mean, median, geometric_mean, harmonic_mean, stdev, variance, percent_change(old,new), growth_rate(values), cagr(start,end,years), linear_regression(x,y), correlation(x,y), sqrt, log, round, floor, ceil.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression (e.g. 'percent_change(100, 150)', 'mean([3,5,7])')"},
                    "variables": {"type": "object", "description": "Variable bindings (e.g. {\"a\": 100})", "default": {}},
                },
                "required": ["expression"],
            },
        },
    },
    "verify": {
        "fn": lambda **kw: tool_verify(**kw),
        "schema": {
            "name": "verify",
            "description": "Sanity-check your answer before submitting. Catches common errors (wrong units, sign, magnitude).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string", "description": "The answer to check"},
                    "question_type": {"type": "string", "description": "Hint: 'percentage', 'dollar_amount', 'count', 'ratio'", "default": ""},
                },
                "required": ["answer"],
            },
        },
    },
    "submit_answer": {
        "fn": lambda **kw: tool_submit_answer(**kw),
        "schema": {
            "name": "submit_answer",
            "description": "Submit the final answer. Writes to /app/answer.txt. Always submit something — a wrong answer scores higher than no answer.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string", "description": "The final answer (numeric)"},
                },
                "required": ["answer"],
            },
        },
    },
}

# ── MCP JSON-RPC 2.0 protocol ────────────────────────────────────────

_call_count = 0
_MAX_CALLS = 20  # Tighter budget forces efficient tool use


def _send(msg: dict) -> None:
    line = json.dumps(msg)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _handle(msg: dict) -> dict | None:
    global _call_count
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "officeqa-lean", "version": "2.0.0"},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        schemas = [t["schema"] for t in TOOLS.values()]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": schemas}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        tool = TOOLS.get(tool_name)
        is_error = False

        if not tool:
            # Don't count unknown tools against budget
            result_text = json.dumps({"status": "error", "msg": f"Unknown tool: {tool_name}. Available: {list(TOOLS.keys())}"})
            is_error = True
        else:
            _call_count += 1
            if _call_count > _MAX_CALLS and tool_name != "submit_answer":
                return {
                    "jsonrpc": "2.0", "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({
                            "status": "budget_exhausted",
                            "msg": "Budget exhausted. Call submit_answer now.",
                        })}],
                        "isError": True,
                    },
                }
            try:
                result = tool["fn"](**arguments)
                is_error = result.get("status") == "error"
                result["_call"] = _call_count
                result["_left"] = _MAX_CALLS - _call_count
                result_text = json.dumps(result, default=str)
            except Exception as exc:
                result_text = json.dumps({"status": "error", "msg": str(exc)})
                is_error = True

        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": result_text}],
                "isError": is_error,
            },
        }

    if msg_id is not None:
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        }
    return None


def main():
    _load_resources()
    _build_fts_index()
    print(f"Loaded: {len(_tables)} tables, {len(_raw_texts)+len(_page_texts)} files, {len(_all_labels)} FTS labels", file=sys.stderr)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue  # skip batch requests / malformed messages
        response = _handle(msg)
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
