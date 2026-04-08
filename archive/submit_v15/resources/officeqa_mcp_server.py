#!/usr/bin/env python3
"""OfficeQA MCP Server - standalone version for arena"""

import json
import re
import os
import sys
import difflib
import math
from io import StringIO

def clean(v):
    v = v.strip()
    v = re.sub(r'\s+[rp]$', '', v)         # "Feb. p" -> "Feb.", "36 r" -> "36"
    v = re.sub(r'(?<=[0-9])[rp]$', '', v)  # "36r" -> "36", "-39r" -> "-39"
    v = re.sub(r'\s*[0-9]+/\s*$', '', v)   # trailing "3/" footnotes
    v = re.sub(r'^[rp]/\s*', '', v)         # leading "r/ p/" prefixes
    m = re.match(r'^\(([0-9,.]+)\)$', v)   # "(123)" -> "-123"
    if m:
        v = '-' + m.group(1)
    return v.strip()

def to_num(v):
    c = clean(v).replace(',', '').replace('$', '').replace('%', '')
    try:
        f = float(c)
        return None if math.isnan(f) else f
    except:
        return None

def _html_cells(tr_html, tag):
    out = []
    for cell in re.finditer(r'<' + tag + r'(?:\s[^>]*)?>([^<]*)</', tr_html, re.I):
        s = re.search(r'colspan=["\']?(\d+)', cell.group(0), re.I)
        out.append((cell.group(1).strip(), int(s.group(1)) if s else 1))
    return out

def parse_html_table(text):
    """Parse HTML table (```html <table>...</table>``` format used in _page_.txt files)."""
    units = ''
    m = re.search(r'(millions?|billions?|thousands?|percent)', text, re.I)
    if m:
        units = m.group(0).lower()
    m = re.search(r'<table>(.*?)</table>', text, re.S | re.I)
    if not m:
        return [], [], units
    trs = re.findall(r'<tr>(.*?)</tr>', m.group(1), re.S | re.I)

    # Collect header rows; pick last pure-leaf row (all colspan=1) as column labels
    header_rows = []
    data_start = 0
    for i, tr in enumerate(trs):
        ths = _html_cells(tr, 'th')
        if ths:
            header_rows.append(ths)
            data_start = i + 1
        else:
            break
    headers = []
    if header_rows:
        leaf = [r for r in header_rows if all(s == 1 for _, s in r)]
        for txt, span in (leaf[-1] if leaf else header_rows[-1]):
            for _ in range(span):
                headers.append(txt)

    data = []
    for tr in trs[data_start:]:
        tds = _html_cells(tr, 'td')
        if not tds:
            continue
        # Single wide-spanning cell = section header
        if len(tds) == 1 and tds[0][1] > 1:
            data.append(('[section] ' + clean(tds[0][0]), []))
            continue
        row = [v for txt, span in tds for v in [txt] * span]
        if row:
            data.append((clean(row[0]), row[1:]))
    return headers, data, units

def parse_table(lines):
    """Auto-detect HTML vs pipe/tab and parse accordingly."""
    text = ''.join(lines)
    if '<table' in text:
        return parse_html_table(text)
    # Pipe/tab delimited (full treasury_bulletin_YYYY_MM.txt corpus files)
    p = sum(l.count('|') for l in lines)
    t = sum(l.count('\t') for l in lines)
    d = '|' if p > t else '\t'
    rows = []
    for l in lines:
        pts = [c.strip() for c in l.split(d) if c.strip()]
        if len(pts) >= 2 and not all(re.match(r'^-+$', c) for c in pts):
            rows.append(pts)
    if not rows:
        return [], [], ''
    h = rows[0]
    data = [(clean(r[0]), r[1:]) for r in rows[1:]]
    units = ''
    for l in lines[:15]:
        m = re.search(r'(millions?|billions?|thousands?|percent)', l, re.I)
        if m:
            units = m.group(0).lower()
            break
    return h, data, units

def extract_cell(filepath, row_pattern=None, col_pattern=None, fuzzy=False):
    """Extract cell(s) from table"""
    try:
        with open(filepath, errors='replace') as f:
            lines = f.readlines()
        h, data, units = parse_table(lines)
        if not h and not data:
            return {"error": "No table found"}
        result = []
        if units:
            result.append(f"[units: {units}]")
        for label, cells in data:
            if label.startswith('[section]'):
                result.append(label)
                continue
            if row_pattern:
                lbl = label.lower()
                if fuzzy:
                    ratio = difflib.SequenceMatcher(None, row_pattern.lower(), lbl).ratio()
                    if ratio < 0.5:
                        continue
                elif row_pattern.lower() not in lbl:
                    continue
            for j, raw in enumerate(cells):
                cn = h[j + 1] if j + 1 < len(h) else (h[j] if j < len(h) else f'c{j}')
                if col_pattern and col_pattern.lower() not in cn.lower():
                    continue
                if not raw or raw in ('-', '*', 'nan', ''):
                    continue
                num = to_num(raw)
                if num is not None:
                    result.append(f"{label} | {cn} = {num}")
                else:
                    c2 = clean(raw)
                    if c2:
                        result.append(f"{label} | {cn} = {c2}")
        return {"results": result}
    except Exception as e:
        return {"error": str(e)}

def list_rows(filepath):
    """List all rows in table"""
    try:
        with open(filepath, errors='replace') as f:
            lines = f.readlines()
        h, data, units = parse_table(lines)
        if not h and not data:
            return {"error": "No table found"}
        result = [f"[units: {units}]" if units else ""]
        for i, (label, _) in enumerate(data):
            result.append(f"[{i+1}] {label}")
        return {"rows": result}
    except Exception as e:
        return {"error": str(e)}

def list_cols(filepath):
    """List all columns in table"""
    try:
        with open(filepath, errors='replace') as f:
            lines = f.readlines()
        h, data, units = parse_table(lines)
        if not h and not data:
            return {"error": "No table found"}
        result = [f"[units: {units}]" if units else ""]
        for j, c in enumerate(h):
            result.append(f"[{j}] {c}")
        return {"columns": result}
    except Exception as e:
        return {"error": str(e)}

def grep_files(query, directory="/app/resources"):
    """Search files for pattern"""
    try:
        result = []
        if not os.path.isdir(directory):
            return {"error": f"Directory not found: {directory}"}
        for fp in sorted(os.listdir(directory)):
            if not fp.endswith('.txt'):
                continue
            full_path = os.path.join(directory, fp)
            try:
                with open(full_path, errors='replace') as f:
                    lines = f.readlines()
                for i, l in enumerate(lines):
                    if re.search(query, l, re.I):
                        ctx = ''.join(lines[max(0, i-1):i+2]).rstrip()
                        result.append(f"[{fp}:{i+1}]\n{ctx}")
            except:
                continue
        return {"matches": result if result else ["No matches"]}
    except Exception as e:
        return {"error": str(e)}

def batch_extract(row_pattern, directory="/app/resources"):
    """Extract row from all files"""
    try:
        result = []
        if not os.path.isdir(directory):
            return {"error": f"Directory not found: {directory}"}
        for fp in sorted(os.listdir(directory)):
            if not fp.endswith('.txt'):
                continue
            full_path = os.path.join(directory, fp)
            try:
                with open(full_path, errors='replace') as f:
                    lines = f.readlines()
                for l in lines:
                    if re.search(row_pattern, l, re.I):
                        vals = re.findall(r'[\d,]+\.?\d*', l)
                        if vals:
                            result.append(f"{fp}: {' | '.join(vals)}")
                        break
            except:
                continue
        return {"extractions": result if result else ["No matches"]}
    except Exception as e:
        return {"error": str(e)}

def get_cpi():
    """Return CPI-U data"""
    cpi_data = {
        1913: 9.9, 1914: 10.0, 1915: 10.1, 1916: 10.9, 1917: 12.8, 1918: 15.1, 1919: 17.3,
        1920: 20.0, 1921: 17.9, 1922: 16.8, 1923: 17.1, 1924: 17.1, 1925: 17.5, 1926: 17.7,
        1927: 17.4, 1928: 17.2, 1929: 17.2, 1930: 16.7, 1931: 15.2, 1932: 13.6, 1933: 12.9,
        1934: 13.4, 1935: 13.7, 1936: 13.9, 1937: 14.4, 1938: 14.1, 1939: 13.9, 1940: 14.0,
        1941: 14.7, 1942: 16.3, 1943: 17.3, 1944: 17.6, 1945: 18.0, 1946: 19.5, 1947: 22.3,
        1948: 24.1, 1949: 23.8, 1950: 24.1, 1951: 26.0, 1952: 26.5, 1953: 26.7, 1954: 26.9,
        1955: 26.8, 1956: 27.2, 1957: 28.1, 1958: 28.9, 1959: 29.1, 1960: 29.6, 1961: 29.9,
        1962: 30.2, 1963: 30.6, 1964: 31.0, 1965: 31.5, 1966: 32.4, 1967: 33.4, 1968: 34.8,
        1969: 36.7, 1970: 38.8, 1971: 40.5, 1972: 41.8, 1973: 44.4, 1974: 49.3, 1975: 53.8,
        1976: 56.9, 1977: 60.6, 1978: 65.2, 1979: 72.6, 1980: 82.4, 1981: 90.9, 1982: 96.5,
        1983: 99.6, 1984: 103.9, 1985: 107.6, 1986: 109.6, 1987: 113.6, 1988: 118.3,
        1989: 124.0, 1990: 130.7, 1991: 136.2, 1992: 140.3, 1993: 144.5, 1994: 148.2,
        1995: 152.4, 1996: 156.9, 1997: 160.5, 1998: 163.0, 1999: 166.6, 2000: 172.2,
        2001: 177.1, 2002: 179.9, 2003: 184.0, 2004: 188.9, 2005: 195.3, 2006: 201.6,
        2007: 207.3, 2008: 215.3, 2009: 214.5, 2010: 218.1, 2011: 224.9, 2012: 229.6,
        2013: 233.0, 2014: 236.7, 2015: 237.0, 2016: 240.0, 2017: 245.1, 2018: 251.1,
        2019: 255.7, 2020: 258.8, 2021: 271.0, 2022: 292.7, 2023: 304.7, 2024: 314.2,
    }
    return {"cpi": cpi_data, "base": 1982, "formula": "real = nominal * (target_cpi / source_cpi)"}

# Simple MCP interface
def main():
    try:
        from mcp.server import Server
        from mcp.types import TextContent
    except ImportError:
        print("Error: mcp not installed", file=sys.stderr)
        sys.exit(1)

    server = Server("officeqa")

    @server.define_tool
    def extract(filepath: str, row: str = None, col: str = None, fuzzy: bool = False):
        """Extract cell from Treasury file"""
        result = extract_cell(filepath, row, col, fuzzy)
        return TextContent(type="text", text=json.dumps(result, default=str))

    @server.define_tool
    def rows(filepath: str):
        """List rows in file"""
        result = list_rows(filepath)
        return TextContent(type="text", text=json.dumps(result, default=str))

    @server.define_tool
    def cols(filepath: str):
        """List columns in file"""
        result = list_cols(filepath)
        return TextContent(type="text", text=json.dumps(result, default=str))

    @server.define_tool
    def grep(query: str, directory: str = "/app/resources"):
        """Search files"""
        result = grep_files(query, directory)
        return TextContent(type="text", text=json.dumps(result, default=str))

    @server.define_tool
    def batch(row_pattern: str, directory: str = "/app/resources"):
        """Extract row from all files"""
        result = batch_extract(row_pattern, directory)
        return TextContent(type="text", text=json.dumps(result, default=str))

    @server.define_tool
    def cpi():
        """Get CPI-U reference data"""
        result = get_cpi()
        return TextContent(type="text", text=json.dumps(result, default=str))

    server.run()

if __name__ == "__main__":
    main()
