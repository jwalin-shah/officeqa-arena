#!/usr/bin/env python3
"""One-shot Treasury Bulletin solver.

If index exists, uses it. If not, builds it first.

Usage:
    python3 /installed-agent/solve.py "What were the total expenditures for national defense in CY 1940?"
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CORPUS_DIR = os.environ.get("CORPUS_DIR", "/app/corpus")
INDEX_PATH = os.environ.get("INDEX_PATH", "/tmp/table_index.jsonl")
KEYWORD_INDEX_PATH = os.environ.get("KEYWORD_INDEX_PATH", "/tmp/keyword_index.txt")
BUILD_SCRIPT = os.environ.get("BUILD_SCRIPT", "/installed-agent/build_index.py")


def ensure_index():
    """Build index if it doesn't exist."""
    if os.path.exists(INDEX_PATH) and os.path.getsize(INDEX_PATH) > 1000:
        return  # Already built

    # Try to find build script
    for candidate in [BUILD_SCRIPT, os.path.join(os.path.dirname(__file__), "build_index.py")]:
        if os.path.exists(candidate):
            print(f"Building index...", file=sys.stderr)
            subprocess.run([sys.executable, candidate], check=True)
            return

    print("ERROR: No index and no build script found", file=sys.stderr)
    sys.exit(1)


_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def parse_question(question):
    """Extract search terms, years, and explicit bulletin reference from the question."""
    q = question.lower()
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", q)]

    # Detect explicit bulletin reference:
    # "bulletin published in June 1970", "September 1990 US Treasury Monthly Bulletin",
    # "the bulletin from January 1944", "page 5 of the September 1990"
    explicit_file = None
    for pattern in [
        r"(?:bulletin|bulletin,)\s+(?:published|from|dated|of)\s+(?:in\s+)?(\w+)\s+((?:19|20)\d{2})",
        r"(\w+)\s+((?:19|20)\d{2})\s+(?:us\s+)?treasury\s+(?:monthly\s+)?bulletin",
        r"page\s+\d+\s+of\s+(?:the\s+)?(\w+)\s+((?:19|20)\d{2})",
        r"(?:the|a)\s+((?:19|20)\d{2})\s+(\w+)\s+(?:issue|edition|bulletin)",
    ]:
        m = re.search(pattern, q)
        if m:
            groups = m.groups()
            month_name = None
            year_str = None
            for g in groups:
                if g.lower() in _MONTH_MAP:
                    month_name = g.lower()
                elif re.match(r"^(19|20)\d{2}$", g):
                    year_str = g
            if month_name and year_str:
                explicit_file = f"treasury_bulletin_{year_str}_{_MONTH_MAP[month_name]}.txt"
                break

    metric_patterns = [
        r"national defense", r"veterans[' ]*administration", r"public debt",
        r"customs duties", r"internal revenue", r"income tax", r"excise tax",
        r"interest on the public debt", r"budget receipts", r"budget expenditures",
        r"total expenditures", r"total receipts", r"currency in circulation",
        r"corporate bonds", r"highway trust fund", r"social security",
        r"railroad retirement", r"employment taxes", r"estate and gift taxes",
        r"gross saving", r"personal saving", r"treasury bonds", r"treasury bills",
        r"foreign exchange", r"public works", r"agricultural", r"unemployment",
        r"claims", r"outlays", r"surplus", r"deficit", r"receipts",
        r"intergovernmental", r"interest\s+(?:cost|outlays|expense)",
        r"individual income tax", r"corporation income tax",
        r"department of (?:agriculture|defense|treasury|state)",
        r"bids?\s+submitted", r"treasury\s+notes", r"saving\s+rate",
    ]
    terms = []
    for pat in metric_patterns:
        m = re.search(pat, q)
        if m:
            terms.append(m.group())

    if not terms:
        stops = {"what", "were", "the", "total", "for", "this", "that", "from",
                 "with", "using", "only", "reported", "values", "individual",
                 "calendar", "fiscal", "year", "months", "dollars", "millions",
                 "thousands", "nominal", "figure", "should", "include", "much",
                 "does", "how", "many", "which", "page", "number", "rounded",
                 "nearest", "place", "percent", "value", "change", "absolute",
                 "according", "bulletin", "published", "treasury", "monthly"}
        words = re.findall(r"[a-z]+", q)
        terms = [w for w in words if len(w) > 3 and w not in stops][:4]

    return terms, years, explicit_file


def search_index(terms, years, need_monthly=False):
    """Search the keyword index for matching tables."""
    if not os.path.exists(KEYWORD_INDEX_PATH):
        return []

    results = []
    with open(KEYWORD_INDEX_PATH, "r") as f:
        for line in f:
            line_lower = line.lower()
            score = 0
            for t in terms:
                if t in line_lower:
                    score += 3
            for y in years:
                if str(y) in line:
                    score += 2

            if score < 3:
                continue

            parts = line.strip().split("\t")
            file_line = parts[0] if parts else ""
            title = parts[1] if len(parts) > 1 else ""
            units = parts[2] if len(parts) > 2 else ""
            tags = parts[3] if len(parts) > 3 else ""

            # Bonus for enriched metadata
            if "HAS_12_MONTHS" in tags:
                score += 2
                if need_monthly:
                    score += 3  # Strong bonus when question asks for monthly sum
            if "HAS_ANNUAL" in tags:
                score += 1

            # Extract pub year for vintage ranking
            pub_year = 0
            pub_match = re.search(r"PUB:(\d{4})", tags)
            if pub_match:
                pub_year = int(pub_match.group(1))

            # Prefer newest bulletin that's AFTER the data year
            vintage_bonus = 0
            for y in years:
                if pub_year >= y and pub_year <= y + 5:
                    vintage_bonus = max(vintage_bonus, 3)  # Sweet spot: 0-5 years after
                elif pub_year > y + 5:
                    vintage_bonus = max(vintage_bonus, 1)  # Still ok, just older revision

            score += vintage_bonus

            results.append({
                "file_line": file_line,
                "title": title,
                "units": units,
                "score": score,
                "pub_year": pub_year,
                "tags": tags,
            })

    # Sort: highest score first, then newest bulletin
    results.sort(key=lambda r: (-r["score"], -r["pub_year"]))
    return results[:10]


def read_table_context(filepath, line_num):
    """Read full table with surrounding context."""
    try:
        lines = Path(filepath).read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return f"File not found: {filepath}"

    target = line_num - 1
    if target < 0 or target >= len(lines):
        return f"Line {line_num} out of range"

    start = target
    for i in range(target - 1, max(0, target - 20), -1):
        line = lines[i].strip()
        if line.startswith("|") or "---" in line:
            start = i
        elif line and not line.startswith("|"):
            if re.search(r"\(.*(?:millions|thousands|dollars|percent).*\)", line, re.I):
                start = i
            elif i < start - 1:
                break
    start = max(0, start - 3)

    end = target
    for i in range(target + 1, min(len(lines), target + 60)):
        line = lines[i].strip()
        if line.startswith("|"):
            end = i
        elif line.startswith("Source:") or line.startswith("Note"):
            end = i
            break
        elif not line:
            if i < end + 3:
                continue
            break

    for i in range(end + 1, min(len(lines), end + 10)):
        line = lines[i].strip()
        if re.match(r"^[0-9*/]+[/)]", line) or line.startswith("Source:"):
            end = i
        elif not line:
            continue
        else:
            break

    return "\n".join(f"{i+1:5d} | {lines[i]}" for i in range(start, min(end + 1, len(lines))))


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 /installed-agent/solve.py \"<question>\"")
        sys.exit(1)

    question = sys.argv[1]
    terms, years, explicit_file = parse_question(question)

    # Detect if question needs monthly data
    q_lower = question.lower()
    need_monthly = any(phrase in q_lower for phrase in [
        "individual calendar months", "individual months", "monthly",
        "sum of these values", "sum of all", "each month",
        "all individual", "reported values for all",
    ])

    is_calendar = "calendar" in q_lower
    is_fiscal = "fiscal" in q_lower or bool(re.search(r"\bfy\s*\d{4}", q_lower))

    print(f"Question: {question[:120]}...")
    print(f"Keywords: {terms}")
    print(f"Years: {years}")
    if explicit_file:
        print(f"Explicit bulletin: {explicit_file}")
    if need_monthly:
        print(f"Note: Question asks for MONTHLY data — looking for tables with 12 months")
    if is_calendar:
        print(f"Note: CALENDAR year question — sum Jan-Dec or find 'Calendar yr.' row")
    if is_fiscal:
        print(f"Note: FISCAL year question — use annual row directly")
    print()

    ensure_index()

    results = search_index(terms, years, need_monthly=need_monthly)

    # If question names a specific bulletin, boost those results to the top
    if explicit_file:
        boosted = [r for r in results if explicit_file in r["file_line"]]
        others = [r for r in results if explicit_file not in r["file_line"]]
        if not boosted:
            # Search index specifically for that file
            with open(KEYWORD_INDEX_PATH) as f:
                for line in f:
                    if line.startswith(explicit_file + ":"):
                        parts = line.strip().split("\t")
                        score = sum(3 for t in terms if t in line.lower())
                        if score > 0 or not terms:
                            boosted.append({
                                "file_line": parts[0],
                                "title": parts[1] if len(parts) > 1 else "",
                                "units": parts[2] if len(parts) > 2 else "",
                                "score": score + 10,  # Strong boost
                                "pub_year": int(re.search(r"(\d{4})", explicit_file).group()) if re.search(r"(\d{4})", explicit_file) else 0,
                                "tags": parts[3] if len(parts) > 3 else "",
                            })
            boosted.sort(key=lambda r: -r["score"])
            boosted = boosted[:5]
        results = boosted + others

    if not results:
        print("NO TABLES FOUND in index.")
        print(f"Try manually: grep -i \"{terms[0] if terms else 'keyword'}\" /app/corpus/treasury_bulletin_*.txt | head -20")
        sys.exit(0)

    print(f"Found {len(results)} matching tables.")
    print()

    # Show top 3 tables with SMART SLICING — headers + target rows + footnotes only
    corpus = Path(CORPUS_DIR)
    shown = 0
    for r in results[:3]:
        fl = r["file_line"]
        parts_fl = fl.split(":")
        if len(parts_fl) < 2:
            continue
        fname = parts_fl[0]
        try:
            line_num = int(parts_fl[1])
        except ValueError:
            continue

        filepath = corpus / fname
        try:
            all_lines = filepath.read_text(errors="replace").splitlines()
        except FileNotFoundError:
            continue

        # Find table boundaries
        table_start = line_num - 1
        # Scan up for title/units
        for j in range(table_start - 1, max(0, table_start - 15), -1):
            ln = all_lines[j].strip()
            if ln.startswith("|"):
                table_start = j
            elif ln and not ln.startswith("|"):
                if re.search(r"\(.*(?:millions|thousands|dollars|percent).*\)", ln, re.I) or (len(ln) > 10 and not ln.startswith("---")):
                    table_start = j
                elif j < table_start - 1:
                    break
        table_start = max(0, table_start - 2)

        table_end = line_num - 1
        for j in range(line_num, min(len(all_lines), line_num + 80)):
            ln = all_lines[j].strip()
            if ln.startswith("|"):
                table_end = j
            elif ln.startswith("Source:") or re.match(r"^[0-9*/]+[/)]", ln):
                table_end = j
            elif not ln:
                if j < table_end + 3:
                    continue
                break
            else:
                break

        # Collect footnotes
        footnotes = []
        for j in range(table_end + 1, min(len(all_lines), table_end + 15)):
            ln = all_lines[j].strip()
            if re.match(r"^[0-9rR*/]+[/)]", ln) or ln.startswith("Source:") or ln.startswith("Note"):
                footnotes.append(j)
            elif ln.startswith("|"):
                break
            elif not ln:
                continue
            elif footnotes:
                break

        # SMART SLICE: collect line indices we want to show
        show_indices = set()

        # 1. Title + units + header (first 5 lines of table)
        for j in range(table_start, min(table_start + 8, len(all_lines))):
            show_indices.add(j)
            # Stop after separator row
            if "---" in all_lines[j]:
                break

        # 2. Target rows: lines containing target years or month names
        year_strs = [str(y) for y in years]
        for j in range(table_start, table_end + 1):
            ln = all_lines[j]
            # Show rows matching target years
            for ys in year_strs:
                if ys in ln:
                    # Include 1 line before for context
                    show_indices.add(max(table_start, j - 1))
                    show_indices.add(j)
                    show_indices.add(min(table_end, j + 1))
                    break
            # Show rows with month names if question needs monthly data
            if need_monthly and re.search(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", ln.lower()):
                show_indices.add(j)
            # Show "Calendar yr." or "Cal. yr." rows
            if re.search(r"cal(?:endar)?\.?\s*yr", ln.lower()):
                show_indices.add(j)

        # 3. Footnotes
        for j in footnotes:
            show_indices.add(j)

        # Print with "..." for gaps
        sorted_indices = sorted(show_indices)

        print(f"{'='*80}")
        print(f"TABLE {shown+1}: {fl} (score={r['score']})")
        print(f"Title: {r['title']}")
        print(f"Units: {r['units']}")
        if r.get("tags"):
            tags = r["tags"].split()
            tag_info = [t for t in tags if t.startswith("HAS_") or t.startswith("BASIS:")]
            if tag_info:
                print(f"Info: {' '.join(tag_info)}")
        print(f"{'='*80}")

        prev = -2
        for j in sorted_indices:
            if j < 0 or j >= len(all_lines):
                continue
            if j > prev + 1:
                print(f"  ... ")
            print(f"{j+1:5d} | {all_lines[j]}")
            prev = j
        print()
        shown += 1

    # Frame output as a completed analysis — MiniMax responds to situational context
    print(f"{'='*80}")
    print(f"DATA RETRIEVAL COMPLETE.")
    print(f"")
    print(f"Your task now: read the tables above, find the right values, compute, and submit.")
    print(f"  python3 -c \"print(...)\"")
    print(f"  echo -n \"ANSWER\" > /app/answer.txt")
    print(f"")
    # Situational warnings — framed as context, not commands
    if need_monthly:
        print(f"CONTEXT: The question specifically asks for 'individual monthly values'.")
        print(f"  The row labeled '1940' or '1953' is the FISCAL YEAR total — that is NOT what you want.")
        print(f"  You need to find the rows for Jan, Feb, Mar... Dec and sum them yourself.")
        print(f"  Monthly rows look like: '| 1940-January |' or '| January |' or '| Jan. |'")
    elif is_calendar:
        print(f"CONTEXT: This is a CALENDAR year question (Jan-Dec).")
        print(f"  Look for a 'Calendar yr.' or 'Cal. yr.' row. If none exists, sum Jan-Dec monthly rows.")
        print(f"  The row labeled just '1940' is the FISCAL year total (Jul-Jun), not calendar year.")
    elif is_fiscal:
        print(f"CONTEXT: This is a FISCAL year question.")
        print(f"  The row labeled '1940' IS the fiscal year total. Use it directly.")


if __name__ == "__main__":
    main()
