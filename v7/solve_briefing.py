#!/usr/bin/env python3
"""solve_briefing.py — Research briefing tool for OfficeQA arena.
Usage: python3 /installed-agent/solve_briefing.py "question" [--keywords "terms"] [--year 1940]
"""
import argparse, json, os, re, sys
from pathlib import Path

RESOURCES = Path("/app/resources")
ANSWER_FILE = Path("/app/answer.txt")

# --- CPI-U annual averages (BLS, base 1982-84=100) ---
CPI_U = {
    1929:17.2,1930:16.7,1931:15.2,1932:13.6,1933:12.9,1934:13.4,1935:13.7,1936:13.9,1937:14.4,1938:14.1,
    1939:13.9,1940:14.0,1941:14.7,1942:16.3,1943:17.3,1944:17.6,1945:18.0,1946:19.5,1947:22.3,1948:24.1,
    1949:23.8,1950:24.1,1951:26.0,1952:26.5,1953:26.7,1954:26.9,1955:26.8,1956:27.2,1957:28.1,1958:28.9,
    1959:29.1,1960:29.6,1961:29.9,1962:30.2,1963:30.6,1964:31.0,1965:31.5,1966:32.4,1967:33.4,1968:34.8,
    1969:36.7,1970:38.8,1971:40.5,1972:41.8,1973:44.4,1974:49.3,1975:53.8,1976:56.9,1977:60.6,1978:65.2,
    1979:72.6,1980:82.4,1981:90.9,1982:96.5,1983:99.6,1984:103.9,1985:107.6,1986:109.6,1987:113.6,1988:118.3,
    1989:124.0,1990:130.7,1991:136.2,1992:140.3,1993:144.5,1994:148.2,1995:152.4,1996:156.9,1997:160.5,1998:163.0,
    1999:166.6,2000:172.2,2001:177.1,2002:179.9,2003:184.0,2004:188.9,2005:195.3,2006:201.6,2007:207.3,2008:215.3,
    2009:214.5,2010:218.1,2011:224.9,2012:229.6,2013:233.0,2014:236.7,2015:237.0,2016:240.0,2017:245.1,2018:251.1,
    2019:255.7,2020:258.8,2021:271.0,2022:292.7,2023:304.7,2024:314.2,
}

# --- Helpers ---

def extract_years(text):
    """Pull all 4-digit years from text."""
    return sorted(set(int(m) for m in re.findall(r'\b(1[89]\d{2}|20[0-2]\d)\b', text)))

def extract_keywords(question, extra=None):
    """Extract meaningful search terms from a question."""
    stop = {'what','were','was','the','of','in','for','a','an','to','and','or','is',
            'how','much','many','total','amount','during','fiscal','year','calendar',
            'fy','cy','from','by','on','at','as','it','its','be','are','this','that',
            'have','has','had','do','does','did','will','would','could','should','may',
            'might','shall','can','per','than','into','over','about','between','through'}
    words = re.findall(r'[a-zA-Z]+', question.lower())
    kw = [w for w in words if w not in stop and len(w) > 2]
    if extra:
        kw.extend(re.findall(r'[a-zA-Z]+', extra.lower()))
    return list(dict.fromkeys(kw))  # dedupe, preserve order

def detect_fy_or_cy(question):
    """Detect whether the question asks about fiscal or calendar year."""
    q = question.lower()
    if re.search(r'\bfiscal\s+year\b|\bfy\s*\d', q):
        return "FY"
    if re.search(r'\bcalendar\s+year\b|\bcy\s*\d', q):
        return "CY"
    return "unknown"

def fy_months(year):
    """Return (start_month, end_month) for a fiscal year."""
    if year < 1977:
        return "Jul {}-Jun {}".format(year - 1, year)
    return "Oct {}-Sep {}".format(year - 1, year)

def detect_units(text):
    """Detect unit scale from surrounding text."""
    t = text.lower()
    if 'in billions' in t or 'billions of dollars' in t:
        return 'billions'
    if 'in millions' in t or 'millions of dollars' in t:
        return 'millions'
    if 'in thousands' in t or 'thousands of dollars' in t:
        return 'thousands'
    return 'unknown'

def parse_number(s):
    """Parse a number string, handling parens for negatives, commas, footnotes."""
    s = s.strip()
    s = re.sub(r'[¹²³⁴⁵⁶⁷⁸⁹⁰]+$', '', s)  # strip superscript footnotes
    s = re.sub(r'\s*[a-z]/\s*$', '', s)  # strip footnote markers like "1/"
    neg = False
    if s.startswith('(') and s.endswith(')'):
        neg = True
        s = s[1:-1]
    s = s.replace(',', '').replace('$', '').replace(' ', '')
    if s in ('', '-', '...', '—', '–', 'n.a.', 'N/A'):
        return None
    try:
        val = float(s)
        return -val if neg else val
    except ValueError:
        return None

def score_line(line, keywords):
    """Score how many keywords appear in a line (case-insensitive)."""
    low = line.lower()
    return sum(1 for kw in keywords if kw in low)

def search_page_files(keywords, years):
    """Search *_page_*.txt files for keyword matches. Returns list of evidence dicts."""
    evidence = []
    page_files = sorted(RESOURCES.glob("*_page_*.txt"))
    if not page_files:
        return evidence
    for pf in page_files:
        try:
            text = pf.read_text(errors='replace')
        except Exception:
            continue
        lines = text.split('\n')
        # Check if file is relevant: at least 2 keywords or 1 keyword + year
        file_lower = text.lower()
        kw_hits = sum(1 for kw in keywords if kw in file_lower)
        yr_hits = sum(1 for y in years if str(y) in text)
        if kw_hits == 0 or (kw_hits < 2 and yr_hits == 0):
            continue
        units = detect_units(text)
        # Find table header and best matching row
        table_name = ""
        for line in lines[:20]:
            stripped = line.strip()
            if stripped and not re.match(r'^[\d\s\|\-\+\.,$()]+$', stripped) and len(stripped) > 10:
                table_name = stripped
                break
        best_score = 0
        best_line = ""
        best_val = None
        for line in lines:
            sc = score_line(line, keywords)
            if sc > best_score:
                # Try to extract a number from this line
                nums = re.findall(r'[\d,]+(?:\.\d+)?', line.replace(',', ''))
                parts = re.split(r'\s{2,}|\t|\|', line)
                vals = [parse_number(p) for p in parts if parse_number(p) is not None]
                if vals:
                    best_score = sc
                    best_line = line.strip()
                    best_val = vals[-1] if years else vals[0]
                    # Try to pick the value under the right year column
                    for y in reversed(years):
                        # Find column index for the year
                        header_line = ""
                        for hl in lines:
                            if str(y) in hl:
                                header_line = hl
                                break
                        if header_line:
                            h_parts = re.split(r'\s{2,}|\t|\|', header_line)
                            for ci, hp in enumerate(h_parts):
                                if str(y) in hp:
                                    if ci < len(parts):
                                        v = parse_number(parts[ci])
                                        if v is not None:
                                            best_val = v
                                    break
        if best_score > 0 and best_val is not None:
            evidence.append({
                'file': pf.name,
                'table': table_name,
                'units': units,
                'matched_row': best_line,
                'value': best_val,
                'score': best_score,
            })
    evidence.sort(key=lambda e: e['score'], reverse=True)
    return evidence

def search_full_txt(keywords, years):
    """Search the full .txt file (not page files) as fallback."""
    evidence = []
    txt_files = [f for f in RESOURCES.glob("*.txt") if '_page_' not in f.name]
    for tf in txt_files:
        try:
            text = tf.read_text(errors='replace')
        except Exception:
            continue
        lines = text.split('\n')
        units = detect_units(text)
        # Find lines matching keywords, with context
        for i, line in enumerate(lines):
            sc = score_line(line, keywords)
            yr_hit = any(str(y) in line for y in years)
            if sc >= 2 or (sc >= 1 and yr_hit):
                parts = re.split(r'\s{2,}|\t|\|', line)
                vals = [parse_number(p) for p in parts if parse_number(p) is not None]
                if vals:
                    # Grab table context from nearby lines
                    ctx_start = max(0, i - 10)
                    context = '\n'.join(lines[ctx_start:i])
                    tbl = ""
                    u = detect_units(context)
                    if u != 'unknown':
                        units = u
                    for cl in lines[ctx_start:i]:
                        s = cl.strip()
                        if s and not re.match(r'^[\d\s\|\-\+\.,$()]+$', s) and len(s) > 10:
                            tbl = s
                    evidence.append({
                        'file': tf.name,
                        'table': tbl,
                        'units': units,
                        'matched_row': line.strip(),
                        'value': vals[-1] if years else vals[0],
                        'score': sc,
                    })
    evidence.sort(key=lambda e: e['score'], reverse=True)
    return evidence[:5]

def search_json(keywords, years):
    """Search JSON files for structured table data."""
    evidence = []
    json_files = sorted(RESOURCES.glob("*.json"))
    for jf in json_files:
        if jf.name == 'manifest.json':
            continue
        try:
            data = json.loads(jf.read_text(errors='replace'))
        except Exception:
            continue
        elements = data if isinstance(data, list) else data.get('elements', data.get('pages', []))
        if isinstance(elements, dict):
            elements = elements.get('elements', [])
        if not isinstance(elements, list):
            continue
        for elem in elements:
            if not isinstance(elem, dict):
                continue
            text = elem.get('text', '') or elem.get('content', '') or ''
            etype = elem.get('type', '')
            if 'table' not in etype.lower() and 'Table' not in etype:
                if len(text) < 50:
                    continue
            low = text.lower()
            sc = sum(1 for kw in keywords if kw in low)
            yr = any(str(y) in text for y in years)
            if sc >= 1 and (sc >= 2 or yr):
                units = detect_units(text)
                # Try to extract value from table text
                rows = text.split('\n')
                for row in rows:
                    rsc = score_line(row, keywords)
                    if rsc >= 1:
                        parts = re.split(r'\s{2,}|\t|\|', row)
                        vals = [parse_number(p) for p in parts if parse_number(p) is not None]
                        if vals:
                            evidence.append({
                                'file': jf.name,
                                'table': elem.get('title', '')[:80],
                                'units': units,
                                'matched_row': row.strip()[:120],
                                'value': vals[-1] if years else vals[0],
                                'score': rsc + sc,
                            })
    evidence.sort(key=lambda e: e['score'], reverse=True)
    return evidence[:3]

def list_resource_files():
    """List all files in /app/resources/."""
    if not RESOURCES.exists():
        return []
    return sorted(f.name for f in RESOURCES.iterdir() if f.is_file())

def pick_answer(evidence, question):
    """Pick the best answer from evidence list."""
    if not evidence:
        return None, "low"
    # Prefer page files over full txt over json
    page_ev = [e for e in evidence if '_page_' in e['file']]
    if page_ev:
        top = page_ev[0]
    else:
        top = evidence[0]
    val = top['value']
    # Format: integer if it's a whole number, else float
    if val is not None and val == int(val):
        val = int(val)
    # Confidence based on score and agreement
    vals = [e['value'] for e in evidence[:3] if e['value'] is not None]
    if len(vals) >= 2 and len(set(vals)) == 1:
        conf = "high"
    elif top['score'] >= 3:
        conf = "high"
    elif top['score'] >= 2:
        conf = "medium"
    else:
        conf = "low"
    return val, conf

def format_briefing(question, keywords, years, files, evidence, answer, confidence, fy_cy, caveats):
    """Format the research briefing output."""
    o = ["--- RESEARCH BRIEFING ---",
         f"QUESTION: {question}",
         f"SEARCH TERMS: {', '.join(keywords)}",
         f"PERIOD TYPE: {fy_cy}" + (f" ({fy_months(years[0])})" if fy_cy == "FY" and years else ""),
         f"YEARS: {', '.join(str(y) for y in years)}",
         f"FILES: {', '.join(files)}", ""]
    o.append("EVIDENCE FOUND:")
    if not evidence:
        o.append("  (none)")
    for i, ev in enumerate(evidence[:5]):
        o.append(f"  [{i+1}] File: {ev['file']}")
        if ev['table']: o.append(f"      Table: {ev['table']}")
        o.append(f"      Units: {ev['units']}")
        o.append(f"      Row: {ev['matched_row'][:150]}")
        o.append(f"      Value: {ev['value']}  (score: {ev['score']})")
    o += ["", f"PROPOSED ANSWER: {answer}", f"CONFIDENCE: {confidence}"]
    if caveats:
        o += ["", "CAVEATS:"] + [f"  - {c}" for c in caveats]
    o += ["", "---",
          f'Refine: python3 /installed-agent/solve_briefing.py "{question}" --keywords "other terms"',
          "---"]
    return '\n'.join(o)

def main():
    parser = argparse.ArgumentParser(description="Research briefing for OfficeQA")
    parser.add_argument("question", help="The question to answer")
    parser.add_argument("--keywords", default=None, help="Override/add search keywords (comma or space separated)")
    parser.add_argument("--year", type=int, default=None, help="Override year to search for")
    args = parser.parse_args()

    question = args.question
    keywords = extract_keywords(question, args.keywords)
    years = extract_years(question)
    if args.year and args.year not in years:
        years.append(args.year)
        years.sort()
    fy_cy = detect_fy_or_cy(question)
    files = list_resource_files()
    caveats = []

    # FY caveat
    if fy_cy == "FY" and years:
        for y in years:
            caveats.append(f"FY{y} = {fy_months(y)}")

    # Search strategy: page files first, then full txt, then json
    evidence = search_page_files(keywords, years)
    if len(evidence) < 2:
        evidence.extend(search_full_txt(keywords, years))
    if len(evidence) < 2:
        evidence.extend(search_json(keywords, years))

    # Deduplicate by value+file
    seen = set()
    deduped = []
    for e in evidence:
        key = (e['file'], e['value'])
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    evidence = deduped

    # Pick answer
    answer, confidence = pick_answer(evidence, question)

    # Check for CPI adjustment question
    q_low = question.lower()
    if any(phrase in q_low for phrase in ['constant dollar', 'real dollar', 'adjusted for inflation',
                                          'cpi', 'inflation adjust', 'in 20', 'in 19']):
        caveats.append("Question may require CPI adjustment. CPI-U data is baked in.")
        # Try to find target year for adjustment
        adj_match = re.search(r'in\s+(19|20)\d{2}\s+dollars', q_low)
        if adj_match and answer is not None and years:
            target_yr = int(re.search(r'((?:19|20)\d{2})', adj_match.group()).group())
            source_yr = years[0]
            if source_yr in CPI_U and target_yr in CPI_U:
                adjusted = round(answer * CPI_U[target_yr] / CPI_U[source_yr], 1)
                caveats.append(f"CPI adjustment: {answer} * {CPI_U[target_yr]}/{CPI_U[source_yr]} = {adjusted}")
                answer = adjusted

    # Check for percent change question
    if any(phrase in q_low for phrase in ['percent change', 'percentage change', '% change',
                                           'percent increase', 'percent decrease', 'growth rate']):
        caveats.append("Question asks for percent change. May need two values to compute.")
        if len(evidence) >= 2:
            v1 = evidence[1]['value']
            v2 = evidence[0]['value']
            if v1 and v2 and v1 != 0:
                pct = round((v2 - v1) / abs(v1) * 100, 1)
                caveats.append(f"Percent change: ({v2} - {v1}) / |{v1}| * 100 = {pct}%")

    # Conflicts
    vals = [e['value'] for e in evidence[:3] if e['value'] is not None]
    if len(set(vals)) > 1:
        caveats.append(f"CONFLICT: multiple values found: {vals}")
        confidence = "low"

    # Write answer
    if answer is not None:
        fmt_answer = str(int(answer)) if isinstance(answer, (int, float)) and answer == int(answer) else str(answer)
        try:
            ANSWER_FILE.parent.mkdir(parents=True, exist_ok=True)
            ANSWER_FILE.write_text(fmt_answer)
        except Exception as e:
            caveats.append(f"Could not write answer file: {e}")
    else:
        fmt_answer = None

    briefing = format_briefing(question, keywords, years, files, evidence,
                               fmt_answer if fmt_answer else "NONE — manual review needed",
                               confidence, fy_cy, caveats)
    print(briefing)

if __name__ == "__main__":
    main()
