#!/usr/bin/env python3
"""Search Treasury files and return structured table data.

Usage:
  python3 q.py "keyword"                          # search all files, show matching tables
  python3 q.py "keyword" --row "defense"           # search + extract specific row
  python3 q.py "keyword" --row "1940" --col "defense"  # search + specific cell
  python3 q.py FILE --rows                         # list all rows in a file
  python3 q.py FILE --cols                         # list all columns in a file
  python3 q.py FILE --row "defense"                # extract row from specific file
  python3 q.py FILE --row "1940" --col "defense"   # extract cell from specific file
"""
import re,sys,os,difflib
from html.parser import HTMLParser

# ── Table Parsing ──

def clean(v):
    v=re.sub(r'\s*[0-9]+/\s*$','',v)       # footnote refs: "123 2/" → "123"
    v=re.sub(r'^[rpe]/\s*','',v)            # prefix footnotes: "r/ 123" → "123"
    v=re.sub(r'[rpe]\s*$','',v)             # trailing footnote letters
    m=re.match(r'^\(([0-9,.]+)\)$',v)       # parenthetical negatives
    if m:v='-'+m.group(1)
    return v.strip()

def to_num(v):
    v=clean(v).replace(',','').replace('$','').replace('%','')
    if not v or v in ('nan','-','*','...',''):return None
    m2=re.match(r'^[rpe]\s+(.+)$',v)       # "r 3428" → "3428"
    if m2:v=m2.group(1).replace(',','')
    try:return float(v)
    except:return None

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables=[];self.cur_table=[];self.cur_row=[]
        self.in_cell=False;self.cell_text='';self.in_table=False
        self.header_rows=[];self._row_has_th=False;self.colspan=1
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='table':self.in_table=True;self.cur_table=[];self.header_rows=[]
        elif tag in('td','th') and self.in_table:
            self.in_cell=True;self.cell_text='';self.colspan=int(a.get('colspan','1'))
        elif tag=='tr' and self.in_table:self.cur_row=[];self._row_has_th=False
    def handle_endtag(self,tag):
        if tag in('td','th') and self.in_cell:
            self.in_cell=False;txt=self.cell_text.strip()
            for _ in range(self.colspan):self.cur_row.append(txt)
            if tag=='th':self._row_has_th=True
        elif tag=='tr' and self.in_table and self.cur_row:
            if self._row_has_th:self.header_rows.append(self.cur_row)
            else:self.cur_table.append(self.cur_row)
        elif tag=='table' and self.in_table:
            self.in_table=False
            if self.cur_table or self.header_rows:
                self.tables.append((self.header_rows,self.cur_table))
    def handle_data(self,data):
        if self.in_cell:self.cell_text+=data

def parse_table(text):
    """Parse HTML or pipe-delimited table. Returns (headers, data_rows, units)."""
    # Try HTML
    if '<table' in text.lower():
        p=TableParser();p.feed(text)
        # Handle unclosed tables
        if not p.tables and p.in_table and (p.cur_table or p.header_rows):
            p.tables.append((p.header_rows,p.cur_table))
        if p.tables:
            hdrs,rows=max(p.tables,key=lambda t:len(t[1]))
            h=[]
            for hr in reversed(hdrs):
                if len(hr)>=2:h=hr;break
            if not h and hdrs:h=hdrs[0]
            data=[(i,r) for i,r in enumerate(rows)]
            units=''
            m=re.search(r'(millions?|billions?|thousands?|percent)',text,re.I)
            if m:units=m.group(0).lower()
            return h,data,units
    # Try pipe/tab
    lines=text.splitlines(keepends=True)
    p=sum(l.count('|') for l in lines);t=sum(l.count('\t') for l in lines)
    if p>=5 or t>=5:
        d='|' if p>t else '\t'
        rows=[]
        for n,l in enumerate(lines):
            if d=='|' and re.match(r'^\s*\|[\s\-|]+\|\s*$',l):continue
            pts=[c.strip() for c in l.split(d) if c.strip()]
            if len(pts)>=2:rows.append((n,pts))
        if rows:
            h=rows[0][1];data=rows[1:]
            units=''
            for l in lines[:15]:
                m=re.search(r'(millions?|billions?|thousands?|percent)',l,re.I)
                if m:units=m.group(0).lower();break
            return h,data,units
    return [],[],''

def get_table_title(text):
    """Extract table title from text before <table> tag."""
    idx=text.lower().find('<table')
    if idx<0:idx=len(text)
    preamble=text[:idx].strip()
    lines=[l.strip() for l in preamble.split('\n') if l.strip()]
    # Return last 2 non-empty lines as title (usually "TABLE FFO-3..." + subtitle)
    return ' | '.join(lines[-2:]) if lines else '(untitled)'

# ── Output Formatting ──

def format_vertical(label, cols, vals, units=''):
    """Format a single row vertically: one line per column."""
    out=[]
    if units:out.append(f'  [units: {units}]')
    for j in range(len(vals)):
        cn=cols[j] if j<len(cols) else f'col_{j}'
        raw=vals[j] if j<len(vals) else ''
        if not raw or raw in ('nan','-','','...'):continue
        num=to_num(raw)
        if num is not None:
            out.append(f'  {cn} = {num}')
        else:
            out.append(f'  {cn} = {clean(raw)}')
    return '\n'.join(out)

# ── Main Logic ──

def search_and_extract(query, directory, row_filter=None, col_filter=None, fuzzy=False):
    """Search files for query, parse matching tables, return structured output."""
    results=[]
    for fp in sorted(os.listdir(directory)):
        if not fp.endswith('.txt'):continue
        full=os.path.join(directory,fp)
        with open(full,errors='replace') as f:text=f.read()
        if not re.search(query,text,re.I):continue

        h,data,units=parse_table(text)
        if not h or not data:continue

        title=get_table_title(text)

        if row_filter:
            # Extract matching rows
            for _,pts in data:
                label=pts[0]
                if fuzzy:
                    ratio=difflib.SequenceMatcher(None,row_filter,label.lower()).ratio()
                    if ratio<0.5:continue
                elif row_filter not in label.lower():continue

                # Filter columns if specified
                out_lines=[]
                for j in range(1,len(pts)):
                    cn=h[j] if j<len(h) else f'col_{j}'
                    if col_filter and col_filter not in cn.lower():continue
                    raw=pts[j]
                    if not raw or raw in ('nan','-','','...'):continue
                    num=to_num(raw)
                    val=str(num) if num is not None else clean(raw)
                    out_lines.append(f'  {cn} = {val}')
                if out_lines:
                    results.append(f'[{fp}] {title}')
                    if units:results.append(f'  [units: {units}]')
                    results.append(f'  ROW: {label}')
                    results.extend(out_lines)
                    results.append('')
        else:
            # Just show which tables matched + first few rows as preview
            results.append(f'[{fp}] {title}')
            if units:results.append(f'  [units: {units}]')
            results.append(f'  columns: {", ".join(h[:6])}{"..." if len(h)>6 else ""}')
            results.append(f'  rows: {len(data)}')
            # Show first 3 row labels
            for _,pts in data[:3]:
                results.append(f'    {pts[0]}')
            if len(data)>3:results.append(f'    ... ({len(data)-3} more)')
            results.append('')

    return '\n'.join(results) if results else f'No tables matching "{query}" found.'

def extract_from_file(filepath, row_filter=None, col_filter=None, list_rows=False, list_cols=False, fuzzy=False):
    """Parse a single file and extract data."""
    with open(filepath,errors='replace') as f:text=f.read()
    h,data,units=parse_table(text)
    if not h:return f'No table found in {filepath}'

    out=[]
    title=get_table_title(text)
    if units:out.append(f'[units: {units}]')

    if list_cols:
        for j,c in enumerate(h):out.append(f'[{j}] {c}')
        return '\n'.join(out)

    if list_rows:
        for n,pts in data:out.append(f'[{n+1}] {pts[0]}')
        return '\n'.join(out)

    if row_filter:
        for _,pts in data:
            label=pts[0]
            if fuzzy:
                ratio=difflib.SequenceMatcher(None,row_filter,label.lower()).ratio()
                if ratio<0.5:continue
            elif row_filter not in label.lower():continue
            for j in range(1,len(pts)):
                cn=h[j] if j<len(h) else f'col_{j}'
                if col_filter and col_filter not in cn.lower():continue
                raw=pts[j]
                if not raw or raw in ('nan','-','','...'):continue
                num=to_num(raw)
                val=str(num) if num is not None else clean(raw)
                out.append(f'{label} | {cn} = {val}')
        return '\n'.join(out) if out else f'No rows matching "{row_filter}" found.'

    # Default: show all data vertically
    for _,pts in data:
        label=pts[0]
        for j in range(1,len(pts)):
            cn=h[j] if j<len(h) else f'col_{j}'
            raw=pts[j]
            if not raw or raw in ('nan','-','','...'):continue
            num=to_num(raw)
            val=str(num) if num is not None else clean(raw)
            out.append(f'{label} | {cn} = {val}')
    return '\n'.join(out)

# ── CLI ──

if __name__=='__main__':
    args=sys.argv[1:]
    if not args:
        print(__doc__);sys.exit()

    target=args[0]
    rf=cf=None;sr=sc=fu=False;i=1
    while i<len(args):
        if args[i]=='--row':rf=args[i+1].lower();i+=2
        elif args[i]=='--col':cf=args[i+1].lower();i+=2
        elif args[i]=='--rows':sr=True;i+=1
        elif args[i]=='--cols':sc=True;i+=1
        elif args[i]=='--fuzzy':fu=True;i+=1
        else:i+=1

    if os.path.isfile(target):
        # Direct file access
        print(extract_from_file(target,row_filter=rf,col_filter=cf,list_rows=sr,list_cols=sc,fuzzy=fu))
    else:
        # Search mode: target is a keyword
        directory='/app/resources'
        if len(args)>1 and os.path.isdir(args[1]):
            directory=args[1]
        print(search_and_extract(target,directory,row_filter=rf,col_filter=cf,fuzzy=fu))
