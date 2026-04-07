#!/usr/bin/env python3
"""solve_v14.py -- Research intern for OfficeQA Arena (v14).
Searches Treasury Bulletin files, parses tables with vertical serialization,
pre-computes when possible, produces a structured briefing for the mentor LLM.
Usage:
    python3 solve_v14.py "What were total expenditures for national defense in CY 1940?"
    python3 solve_v14.py "question" --keywords "defense expenditures" --year 1940
"""
import argparse, os, re, sys
from pathlib import Path

RESOURCES = Path(os.environ.get("RESOURCES_DIR", "/app/resources"))
CORPUS = Path(os.environ.get("CORPUS_DIR", "/app/corpus"))
ANSWER_FILE = Path(os.environ.get("ANSWER_PATH", "/app/answer.txt"))

CPI = {
    1913:9.9,1914:10.0,1915:10.1,1916:10.9,1917:12.8,1918:15.1,1919:17.3,
    1920:20.0,1921:17.9,1922:16.8,1923:17.1,1924:17.1,1925:17.5,1926:17.7,
    1927:17.4,1928:17.2,1929:17.2,1930:16.7,1931:15.2,1932:13.6,1933:12.9,
    1934:13.4,1935:13.7,1936:13.9,1937:14.4,1938:14.1,1939:13.9,1940:14.0,
    1941:14.7,1942:16.3,1943:17.3,1944:17.6,1945:18.0,1946:19.5,1947:22.3,
    1948:24.1,1949:23.8,1950:24.1,1951:26.0,1952:26.5,1953:26.7,1954:26.9,
    1955:26.8,1956:27.2,1957:28.1,1958:28.9,1959:29.1,1960:29.6,1961:29.9,
    1962:30.2,1963:30.6,1964:31.0,1965:31.5,1966:32.4,1967:33.4,1968:34.8,
    1969:36.7,1970:38.8,1971:40.5,1972:41.8,1973:44.4,1974:49.3,1975:53.8,
    1976:56.9,1977:60.6,1978:65.2,1979:72.6,1980:82.4,1981:90.9,1982:96.5,
    1983:99.6,1984:103.9,1985:107.6,1986:109.6,1987:113.6,1988:118.3,
    1989:124.0,1990:130.7,1991:136.2,1992:140.3,1993:144.5,1994:148.2,
    1995:152.4,1996:156.9,1997:160.5,1998:163.0,1999:166.6,2000:172.2,
    2001:177.1,2002:179.9,2003:184.0,2004:188.9,2005:195.3,2006:201.6,
    2007:207.3,2008:215.3,2009:214.5,2010:218.1,2011:224.9,2012:229.6,
    2013:233.0,2014:236.7,2015:237.0,2016:240.0,2017:245.1,2018:251.1,
    2019:255.7,2020:258.8,2021:271.0,2022:292.7,2023:304.7,2024:314.2,
}

TABLE_FAMILY_MAP = {
    "national defense": ("expenditures", ["analysis","general","expenditures","function"]),
    "defense": ("expenditures", ["analysis","general","expenditures","function"]),
    "military": ("expenditures", ["military","defense","expenditures"]),
    "expenditures": ("expenditures", ["analysis","expenditures","budget"]),
    "receipts": ("receipts", ["budget","receipts","internal","revenue"]),
    "revenue": ("receipts", ["internal","revenue","collections"]),
    "customs": ("receipts", ["customs","duties","import"]),
    "public debt": ("debt", ["public","debt","outstanding"]),
    "interest-bearing": ("debt", ["interest","bearing","debt"]),
    "securities": ("debt", ["federal","securities","ownership"]),
    "savings bonds": ("debt", ["savings","bonds","series"]),
    "tax": ("receipts", ["tax","internal","revenue","collections"]),
    "income tax": ("receipts", ["income","tax","individual","corporation"]),
    "corporation": ("receipts", ["corporation","income","tax"]),
    "employment": ("receipts", ["employment","tax","social","insurance"]),
    "trust fund": ("trust", ["trust","fund","social","security"]),
    "gold": ("monetary", ["gold","stock","monetary"]),
    "currency": ("monetary", ["currency","circulation","money"]),
    "imports": ("international", ["imports","merchandise","trade"]),
    "exports": ("international", ["exports","merchandise","trade"]),
}

STOP = {'what','were','was','the','of','in','for','a','an','to','and','or','is',
        'how','much','many','total','amount','during','fiscal','year','calendar',
        'fy','cy','from','by','on','at','as','it','its','be','are','this','that',
        'have','has','had','do','does','did','will','would','could','should','may',
        'might','shall','can','per','than','into','over','about','between','through',
        'with','not','no','all','each','every','some','any','been','being'}

MONTHS = ["january","february","march","april","may","june",
          "july","august","september","october","november","december"]
MON3 = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"]

# ── Question Parsing ─────────────────────────────────────────────────────────
def extract_years(text):
    years = set()
    for m in re.finditer(r'\b(1[89]\d{2}|20[0-2]\d)s\b', text):
        years.update(range(int(m.group(1)), int(m.group(1)) + 10))
    for m in re.finditer(r'\b(1[89]\d{2}|20[0-2]\d)\b', text):
        years.add(int(m.group(1)))
    return sorted(years)

def extract_keywords(question, extra=None):
    words = re.findall(r'[a-zA-Z]+', question.lower())
    kw = [w for w in words if w not in STOP and len(w) > 2]
    if extra:
        kw.extend(re.findall(r'[a-zA-Z]+', extra.lower()))
    return list(dict.fromkeys(kw))

def detect_period(question):
    q = question.lower()
    if re.search(r'\bfiscal\s+year\b|\bfy\s*\d', q): return "fiscal"
    if re.search(r'\bcalendar\s+year\b|\bcy\s*\d', q): return "calendar"
    return "unknown"

def detect_operation(question):
    q = question.lower()
    if re.search(r'percent(age)?\s+(change|increase|decrease|growth)|% change|growth rate', q):
        return "pct_change"
    if re.search(r'\bdifference\b|\bhow much (more|less|greater|larger|smaller)\b', q):
        return "difference"
    if re.search(r'\bratio\b|\btimes\b|\bfold\b', q): return "ratio"
    if re.search(r'\baverage\b|\bmean\b', q): return "mean"
    if re.search(r'\bsum\b|\btotal\b|\bcombined\b|\baggregate\b', q): return "sum"
    if re.search(r'\bcompar', q): return "comparison"
    return "lookup"

def get_boost_terms(keywords):
    q = ' '.join(keywords)
    boost = []
    for phrase, (_, terms) in TABLE_FAMILY_MAP.items():
        if phrase in q:
            boost.extend(terms)
    return list(dict.fromkeys(boost))

# ── Number / Unit Helpers ────────────────────────────────────────────────────
def parse_number(s):
    if not s or not isinstance(s, str): return None
    s = s.strip()
    s = re.sub(r'\s*[a-z0-9]/\s*$', '', s)
    s = re.sub(r'[*]+$', '', s)
    neg = s.startswith('(') and s.endswith(')')
    if neg: s = s[1:-1]
    s = s.replace(',', '').replace('$', '').replace(' ', '')
    if s in ('', '-', '...', '---', '\u2014', '\u2013', 'n.a.', 'N/A', '(X)', 'X'):
        return None
    try:
        val = float(s)
        return -val if neg else val
    except ValueError:
        return None

def detect_units(text):
    t = text.lower()
    if 'in billions' in t or 'billions of dollars' in t: return 'billions of dollars'
    if 'in millions' in t or 'millions of dollars' in t: return 'millions of dollars'
    if 'in thousands' in t or 'thousands of dollars' in t: return 'thousands of dollars'
    if 'percent' in t or '%' in t: return 'percent'
    return 'dollars (units unclear)'

def detect_evidence_period(text):
    t = text.lower()
    fy = sum(1 for s in ('fiscal year','fiscal years','end of year') if s in t)
    cy = sum(1 for s in ('calendar year','calendar years') if s in t)
    mo = sum(1 for s in (MONTHS + MON3) if re.search(r'\b' + s + r'\b', t))
    if mo >= 3: return "calendar"
    return "calendar" if cy > fy else "fiscal" if fy > cy else "unknown"

def fy_months(year):
    return f"Jul {year-1}-Jun {year}" if year < 1977 else f"Oct {year-1}-Sep {year}"

# ── Vertical Table Serialization ─────────────────────────────────────────────
def _col_positions(line):
    """Detect column start positions from gaps (2+ spaces) in a line."""
    pos, in_gap = [], True
    for i, ch in enumerate(line):
        if ch != ' ':
            if in_gap: pos.append(i); in_gap = False
        elif not in_gap and i + 1 < len(line) and line[i + 1] == ' ':
            in_gap = True
    return pos

def _extract_cols(line, positions):
    vals = []
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(line)
        vals.append(line[start:end].strip() if start < len(line) else '')
    return vals

def _is_sep(line):
    s = line.strip()
    return bool(s) and len(re.sub(r'[\s\-=_\.+|]', '', s)) < max(3, len(s) * 0.15)

def _find_headers(lines):
    """Find header row(s) with year columns or month names. Returns (labels, indices, positions)."""
    yr_pat = re.compile(r'\b(1[89]\d{2}|20[0-2]\d)\b')
    mo_pat = re.compile(r'\b(?:' + '|'.join(MONTHS + MON3) + r')\b', re.I)
    for i, line in enumerate(lines):
        if len(yr_pat.findall(line)) >= 2 or len(mo_pat.findall(line)) >= 3:
            pos = _col_positions(line)
            cols = _extract_cols(line, pos)
            if i > 0 and not re.match(r'^[\s\-=_.]+$', lines[i-1]):
                prev = _extract_cols(lines[i-1], pos)
                merged = []
                for ci in range(len(cols)):
                    p = prev[ci].strip() if ci < len(prev) else ''
                    c = cols[ci].strip()
                    if p and c:
                        if yr_pat.match(p) and not yr_pat.match(c): merged.append(f"{c} {p}")
                        elif yr_pat.match(c) and not yr_pat.match(p): merged.append(f"{p} {c}")
                        else: merged.append(c)
                    else: merged.append(c or p)
                return merged, [i-1, i], pos
            return cols, [i], pos
    return [], [], []

def _is_md_table(lines):
    """Check if the text contains a Markdown pipe-delimited table."""
    pipe_lines = sum(1 for l in lines if l.strip().startswith('|') and l.strip().endswith('|'))
    return pipe_lines >= 3

def _parse_md_row(line):
    """Split a Markdown pipe row into cell values, stripping outer pipes."""
    line = line.strip()
    if line.startswith('|'): line = line[1:]
    if line.endswith('|'): line = line[:-1]
    return [c.strip() for c in line.split('|')]

def _is_md_sep(line):
    """Check if line is a Markdown separator row like |---|---|."""
    stripped = line.strip()
    if not stripped.startswith('|'): return False
    inner = stripped.strip('|').replace('|', '').replace('-', '').replace(':', '').replace(' ', '')
    return len(inner) == 0

def _clean_footnotes(s):
    """Remove footnote markers like 1/, 2/, 3/, p/, r/ from a cell value."""
    return re.sub(r'\s*[a-z0-9]+/\s*', '', s).strip()

def _serialize_md_table(lines, keywords=None, target_years=None):
    """Parse Markdown pipe-delimited table lines into vertical entries."""
    entries = []
    headers = None
    for line in lines:
        stripped = line.strip()
        if not stripped or not stripped.startswith('|'):
            # If we already found a table and hit a non-pipe line, keep scanning
            continue
        if _is_md_sep(stripped):
            continue
        cells = _parse_md_row(stripped)
        if headers is None:
            headers = [_clean_footnotes(c) for c in cells]
            continue
        # Data row
        if not cells:
            continue
        label = _clean_footnotes(cells[0])
        label = re.sub(r'\.{2,}\s*$', '', label).strip()
        label = re.sub(r'\s*[.]{3,}\s*', ' ', label).strip()
        if not label or re.match(r'^[\s\-=_.]+$', label):
            continue
        for ci in range(1, len(cells)):
            raw = cells[ci].strip() if ci < len(cells) else ''
            raw = _clean_footnotes(raw)
            if not raw or raw.lower() == 'nan':
                continue
            hdr = headers[ci].strip() if ci < len(headers) else f"col_{ci}"
            entries.append({'row_label': label, 'column': hdr,
                            'value': raw, 'numeric': parse_number(raw)})
    return entries

def _parse_html_tables(text, keywords=None, target_years=None):
    """Parse HTML <table> elements into vertical entries."""
    entries = []
    # Find all <table>...</table> blocks
    tables = re.findall(r'<table>(.*?)</table>', text, re.DOTALL | re.IGNORECASE)
    for table_html in tables:
        # Extract header cells
        headers = []
        header_match = re.search(r'<tr>(.*?)</tr>', table_html, re.DOTALL)
        if header_match:
            headers = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', header_match.group(1), re.DOTALL)
            headers = [re.sub(r'<[^>]+>', ' ', h).strip() for h in headers]
        if not headers:
            continue
        # Extract data rows (skip first row = headers)
        rows = re.findall(r'<tr>(.*?)</tr>', table_html, re.DOTALL)
        for row_html in rows[1:]:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if not cells:
                continue
            label = _clean_footnotes(cells[0]) if cells else ''
            label = re.sub(r'\.{2,}\s*$', '', label).strip()
            if not label or re.match(r'^[\s\-=_.]+$', label):
                continue
            for ci in range(1, min(len(cells), len(headers))):
                raw = _clean_footnotes(cells[ci])
                if not raw or raw == '-' or raw.lower() == 'nan':
                    continue
                hdr = headers[ci] if ci < len(headers) else f'col_{ci}'
                entries.append({'row_label': label, 'column': hdr,
                                'value': raw, 'numeric': parse_number(raw)})
    return entries

def serialize_table(text, keywords=None, target_years=None):
    """Parse table text into vertical entries: [{row_label, column, value, numeric}]."""
    lines = text.split('\n')

    # Try HTML tables first (oracle page files use this format)
    if '<table>' in text.lower():
        entries = _parse_html_tables(text, keywords, target_years)
        if entries:
            return entries

    # Try Markdown pipe-delimited table first
    if _is_md_table(lines):
        entries = _serialize_md_table(lines, keywords, target_years)
        if entries:
            return entries

    # Fall back to fixed-width column detection
    headers, hidx, cpos = _find_headers(lines)
    if not headers or not cpos:
        return []
    start = max(hidx) + 1
    while start < len(lines) and _is_sep(lines[start]):
        start += 1
    entries = []
    for li in range(start, len(lines)):
        line = lines[li]
        if not line.strip() or _is_sep(line): continue
        cols = _extract_cols(line, cpos)
        if not cols: continue
        label = re.sub(r'\.{2,}\s*$', '', cols[0]).strip()
        label = re.sub(r'\s*[.]{3,}\s*', ' ', label).strip()
        if not label or re.match(r'^[\s\-=_.]+$', label): continue
        for ci in range(1, len(cols)):
            v = cols[ci].strip() if ci < len(cols) else ''
            if not v: continue
            hdr = headers[ci].strip() if ci < len(headers) else f"col_{ci}"
            entries.append({'row_label': label, 'column': hdr,
                            'value': v, 'numeric': parse_number(v)})
    return entries

def format_entries(entries, keywords=None, target_years=None, limit=60):
    if not entries: return "  (no table data parsed)"
    def _score(e):
        s = 0
        ll, cl = e['row_label'].lower(), e['column'].lower()
        if keywords: s += sum(2 for k in keywords if k in ll)
        if target_years: s += sum(3 for y in target_years if str(y) in cl)
        if e['numeric'] is not None: s += 1
        return s
    ranked = sorted(entries, key=_score, reverse=True)[:limit]
    return '\n'.join(f"    {e['row_label']}, {e['column']}: {e['value']}" for e in ranked)

# ── Evidence Search ──────────────────────────────────────────────────────────
def _relevance(text, keywords, years):
    t = text.lower()
    return sum(1 for k in keywords if k in t) * 2 + sum(1 for y in years if str(y) in text)

def _table_title(lines, n=25):
    for line in lines[:n]:
        s = line.strip()
        if s and not _is_sep(s) and not re.match(r'^[\d\s\|\-\+\.,$()]+$', s) and len(s) > 10:
            return s
    return "(untitled table)"

def _best_value(entries, keywords, year):
    best, best_sc = None, -1
    for e in entries:
        if e['numeric'] is None: continue
        sc = 0
        ll, cl = e['row_label'].lower(), e['column'].lower()
        if str(year) in cl: sc += 5
        if str(year) in e['value']: sc += 2
        if keywords: sc += sum(2 for k in keywords if k in ll)
        if 'total' in ll: sc += 1
        if sc > best_sc: best_sc, best = sc, e
    return best

def _build_evidence(filepath, text, keywords, years):
    """Build an evidence dict from a file's text content."""
    lines = text.split('\n')
    entries = serialize_table(text, keywords, years)
    extracted = {}
    for y in years:
        v = _best_value(entries, keywords, y)
        if v: extracted[y] = v
    return {
        'file': filepath.name, 'table': _table_title(lines),
        'units': detect_units(text), 'period': detect_evidence_period(text),
        'vertical_text': format_entries(entries, keywords, years),
        'entries': entries, 'extracted_values': extracted,
        'relevance': _relevance(text, keywords, years),
    }

def search_oracle(keywords, years):
    evidence = []
    if not RESOURCES.exists():
        return evidence
    # Priority 1: page-level extracts (small, targeted)
    page_files = sorted(RESOURCES.glob("*_page_*.txt"))
    # Priority 2: full bulletin files in resources (oracle provides these too)
    bulletin_files = sorted(RESOURCES.glob("treasury_bulletin_*.txt"))
    # Priority 3: any other txt files in resources
    other_files = [f for f in sorted(RESOURCES.glob("*.txt"))
                   if f not in page_files and f not in bulletin_files
                   and f.name != "index.txt"]
    for pf in page_files + bulletin_files + other_files:
        try: text = pf.read_text(errors='replace')
        except Exception: continue
        rel = _relevance(text, keywords, years)
        # Lower threshold for page files (they're pre-selected), higher for full bulletins
        threshold = 1 if "_page_" in pf.name else 2
        if rel < threshold: continue
        evidence.append(_build_evidence(pf, text, keywords, years))
    evidence.sort(key=lambda e: e['relevance'], reverse=True)
    return evidence

def search_corpus(keywords, years, max_files=20):
    if not CORPUS.exists(): return []
    files = sorted(CORPUS.glob("treasury_bulletin_*.txt"))
    if not files: files = sorted(CORPUS.glob("*.txt"))
    boost = get_boost_terms(keywords)
    scored = sorted(files, key=lambda f: sum(1 for k in keywords + boost if k in f.name.lower()), reverse=True)
    evidence = []
    for cf in scored[:max_files]:
        try: text = cf.read_text(errors='replace')
        except Exception: continue
        if _relevance(text, keywords, years) < 3: continue
        evidence.append(_build_evidence(cf, text, keywords, years))
    evidence.sort(key=lambda e: e['relevance'], reverse=True)
    return evidence[:5]

# ── Pre-Computation ──────────────────────────────────────────────────────────
def _get_vals(evidence, years):
    """Extract {year: numeric_value} from evidence for given years."""
    result = {}
    for y in years:
        for ev in evidence:
            v = ev.get('extracted_values', {}).get(y)
            if v and v['numeric'] is not None:
                result[y] = v['numeric']; break
    return result

def try_precompute(op, evidence, keywords, years):
    if not evidence or not years: return None, None
    all_entries = [e for ev in evidence for e in ev.get('entries', [])]

    if op == "sum":
        # Monthly sum for single year
        y0 = years[0]
        monthly = [e['numeric'] for e in all_entries
                   if e['numeric'] is not None
                   and (str(y0) in e['column'].lower() or str(y0) in e['value'])
                   and any(m in e['column'].lower() for m in MON3 + MONTHS)
                   and any(k in e['row_label'].lower() for k in keywords[:3])]
        if len(monthly) >= 10:
            t = sum(monthly)
            return t, f"SUM of {len(monthly)} monthly values = {t:,.2f}"
        # Sum across year range
        if len(years) > 2:
            vals = _get_vals(evidence, years)
            if len(vals) == len(years):
                t = sum(vals.values())
                detail = ' + '.join(f"{vals[y]:,.2f} ({y})" for y in years)
                return t, f"SUM across {len(years)} years: {detail} = {t:,.2f}"

    if op == "pct_change" and len(years) >= 2:
        vals = _get_vals(evidence, [years[0], years[-1]])
        vo, vn = vals.get(years[0]), vals.get(years[-1])
        if vo is not None and vn is not None and vo != 0:
            p = (vn - vo) / abs(vo) * 100
            return round(p, 2), f"pct_change({vo:,.2f}, {vn:,.2f}) = (({vn:,.2f}-{vo:,.2f})/{abs(vo):,.2f})*100 = {p:.2f}%"

    if op == "difference" and len(years) >= 2:
        vals = _get_vals(evidence, [years[0], years[-1]])
        vo, vn = vals.get(years[0]), vals.get(years[-1])
        if vo is not None and vn is not None:
            d = vn - vo
            return d, f"difference: {vn:,.2f} - {vo:,.2f} = {d:,.2f}"

    if op == "ratio" and len(years) >= 2:
        vals = _get_vals(evidence, [years[0], years[-1]])
        vo, vn = vals.get(years[0]), vals.get(years[-1])
        if vo is not None and vn is not None and vo != 0:
            r = vn / vo
            return round(r, 4), f"ratio: {vn:,.2f} / {vo:,.2f} = {r:.4f}"

    if op == "mean":
        vals = _get_vals(evidence, years)
        if len(vals) >= 2:
            a = sum(vals.values()) / len(vals)
            return round(a, 2), f"mean of {len(vals)} values = {a:,.2f}"

    if op == "lookup" and years:
        for ev in evidence:
            v = ev.get('extracted_values', {}).get(years[0])
            if v and v['numeric'] is not None:
                return v['numeric'], f"lookup: {v['row_label']}, {v['column']} = {v['value']}"
    return None, None

# ── Conflict Detection ───────────────────────────────────────────────────────
def detect_conflicts(evidence, years):
    conflicts = []
    for y in years:
        srcs = [(ev['file'], ev['extracted_values'][y]['numeric'])
                for ev in evidence if y in ev.get('extracted_values', {})
                and ev['extracted_values'][y]['numeric'] is not None]
        if len(srcs) < 2: continue
        base = abs(srcs[0][1]) or 1
        for i in range(1, len(srcs)):
            pct = abs(srcs[i][1] - srcs[0][1]) / base * 100
            if pct > 2:
                conflicts.append(f"Year {y}: {srcs[0][0]}={srcs[0][1]:,.2f} vs "
                                 f"{srcs[i][0]}={srcs[i][1]:,.2f} (diff={pct:.1f}%)")
    return conflicts

# ── CPI Adjustment ───────────────────────────────────────────────────────────
def check_cpi(question, answer, years):
    q = question.lower()
    if not any(t in q for t in ('constant dollar','real dollar','adjusted for inflation','in 20','in 19')):
        return answer, None
    m = re.search(r'in\s+((?:19|20)\d{2})\s+dollars', q)
    if m and answer is not None and years:
        tgt, src = int(m.group(1)), years[0]
        if src in CPI and tgt in CPI:
            adj = round(answer * CPI[tgt] / CPI[src], 2)
            return adj, f"CPI: {answer:,.2f} * {CPI[tgt]}/{CPI[src]} = {adj:,.2f}"
    return answer, None

# ── Briefing Output ──────────────────────────────────────────────────────────
def briefing(question, keywords, years, period, op, evidence,
             answer, confidence, trace, conflicts, caveats):
    o = [f"--- INTERN'S RESEARCH BRIEFING ---",
         f"QUESTION: {question}", f"QUESTION TYPE: {op}",
         f"PERIOD BASIS REQUESTED: {period}",
         f"TARGET YEARS: {', '.join(str(y) for y in years)}",
         f"SEARCH TERMS: {', '.join(keywords)}", ""]
    for i, ev in enumerate(evidence[:5]):
        ptag = ev['period'].upper() if ev['period'] != 'unknown' else 'UNKNOWN'
        if period != 'unknown' and ev['period'] != 'unknown':
            suf = " \u2713 matches" if ev['period'] == period else " \u26a0 MISMATCH"
        else: suf = ""
        o += [f"EVIDENCE #{i+1}:", f"  Source: {ev['file']}",
              f"  Table: {ev['table']}", f"  Units: {ev['units']}",
              f"  Period: {ptag} YEAR{suf}", f"  Data (vertical format):",
              ev['vertical_text']]
        for y in years:
            v = ev.get('extracted_values', {}).get(y)
            if v: o.append(f"  >> Year {y} best match: {v['row_label']}, {v['column']}: {v['value']}")
        o.append("")
    if not evidence: o += ["EVIDENCE: (none found)", ""]
    if conflicts:
        o.append("\u26a0 CONFLICT DETECTED:")
        for c in conflicts: o.append(f"  {c}")
        o.append("")
    fmta = (str(int(answer)) if isinstance(answer, float) and answer == int(answer)
            else str(answer)) if answer is not None else "NONE -- manual review needed"
    o += [f"INTERN'S PROPOSED ANSWER: {fmta}", f"CONFIDENCE: {confidence}"]
    if trace: o.append(f"COMPUTATION TRACE: {trace}")
    if caveats:
        o.append("\nCAVEATS:")
        for c in caveats: o.append(f"  - {c}")
    for ev in evidence:
        if period != 'unknown' and ev['period'] != 'unknown' and ev['period'] != period:
            o += ["", f"\u26a0 WARNING: {ev['file']} is {ev['period'].upper()} YEAR but question asks {period.upper()} YEAR.",
                  "  Pre-1977 FY = Jul-Jun, Post-1977 FY = Oct-Sep"]
            break
    o.append("---")
    return '\n'.join(o)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Research intern for OfficeQA (v14)")
    ap.add_argument("question")
    ap.add_argument("--keywords", default=None)
    ap.add_argument("--year", type=int, default=None)
    args = ap.parse_args()

    question, kw = args.question, extract_keywords(args.question, args.keywords)
    years = extract_years(question)
    if args.year and args.year not in years: years.append(args.year); years.sort()
    period, op, caveats = detect_period(question), detect_operation(question), []

    if period == "fiscal" and years:
        caveats.extend(f"FY{y} = {fy_months(y)}" for y in years)

    # Priority 1: oracle pages
    ev = search_oracle(kw, years)
    # Priority 2: corpus fallback
    if len(ev) < 2: ev.extend(search_corpus(kw, years))
    # Priority 3: broadened search
    if not ev:
        boost = get_boost_terms(kw)
        if boost:
            broader = kw[:2] + boost[:2]
            ev = search_oracle(broader, years)
            if not ev: ev = search_corpus(broader, years)
            if ev: caveats.append("Used broadened search (table family boost)")

    conflicts = detect_conflicts(ev, years)
    if conflicts: caveats.append("Multiple sources disagree -- verify correct table.")

    answer, trace = try_precompute(op, ev, kw, years)
    if answer is None and ev and years:
        for e in ev:
            v = e.get('extracted_values', {}).get(years[-1])
            if v and v['numeric'] is not None:
                answer, trace = v['numeric'], f"direct: {v['row_label']}, {v['column']} = {v['value']}"
                break

    if answer is not None:
        adj, ctrace = check_cpi(question, answer, years)
        if ctrace:
            answer, trace = adj, (trace or "") + " | " + ctrace
            caveats.append("CPI-U adjustment applied.")

    conf = "LOW"
    if conflicts: conf = "LOW"
    elif answer is not None and ev:
        r = ev[0]['relevance']
        conf = "HIGH" if r >= 6 else "MEDIUM" if r >= 3 else "LOW"

    print(briefing(question, kw, years, period, op, ev, answer, conf, trace, conflicts, caveats))

    if answer is not None:
        fa = str(int(answer)) if isinstance(answer, float) and answer == int(answer) else str(answer)
        try:
            ANSWER_FILE.parent.mkdir(parents=True, exist_ok=True)
            ANSWER_FILE.write_text(fa)
            print(f"\n[answer.txt written: {fa}]")
        except Exception as e:
            print(f"\n[Could not write answer.txt: {e}]", file=sys.stderr)
    else:
        print("\n[No answer proposed -- mentor must investigate manually]")

if __name__ == "__main__":
    main()
