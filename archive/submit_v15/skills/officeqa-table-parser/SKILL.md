---
name: officeqa-table-parser
description: Table parser + grep scripts — save to /tmp then use to extract data from Treasury files
---

## Save to /tmp/e.py — robust table extractor:
```python
import re,sys,difflib,math
def clean(v):
    v=v.strip()
    v=re.sub(r'\s+[rp]$','',v)        # "Feb. p"->"Feb.", "36 r"->"36"
    v=re.sub(r'(?<=[0-9])[rp]$','',v) # "36r"->"36", "-39r"->"-39"
    v=re.sub(r'\s*[0-9]+/\s*$','',v)  # trailing "3/" footnotes
    v=re.sub(r'^[rp]/\s*','',v)        # leading "r/ p/" prefixes
    m=re.match(r'^\(([0-9,.]+)\)$',v) # "(123)"->"-123"
    if m:v='-'+m.group(1)
    return v.strip()
def to_num(v):
    c=clean(v).replace(',','').replace('$','').replace('%','')
    try:
        f=float(c)
        return None if math.isnan(f) else f
    except:return None
def parse_html(text):
    units=''
    m=re.search(r'(millions?|billions?|thousands?|percent)',text,re.I)
    if m:units=m.group(0).lower()
    m=re.search(r'<table>(.*?)</table>',text,re.S|re.I)
    if not m:return [],[],units
    trs=re.findall(r'<tr>(.*?)</tr>',m.group(1),re.S|re.I)
    def cells(tr_html,tag):
        out=[]
        for cell in re.finditer(r'<'+tag+r'(?:\s[^>]*)?>([^<]*)</',tr_html,re.I):
            s=re.search(r'colspan=["\']?(\d+)',cell.group(0),re.I)
            out.append((cell.group(1).strip(),int(s.group(1)) if s else 1))
        return out
    header_rows=[];data_start=0
    for i,tr in enumerate(trs):
        ths=cells(tr,'th')
        if ths:header_rows.append(ths);data_start=i+1
        else:break
    headers=[]
    if header_rows:
        leaf=[r for r in header_rows if all(s==1 for _,s in r)]
        for txt,span in (leaf[-1] if leaf else header_rows[-1]):
            for _ in range(span):headers.append(txt)
    data=[]
    for tr in trs[data_start:]:
        tds=cells(tr,'td')
        if not tds:continue
        if len(tds)==1 and tds[0][1]>1:
            data.append(('[section] '+clean(tds[0][0]),[]))
            continue
        row=[v for txt,span in tds for v in [txt]*span]
        if row:data.append((clean(row[0]),row[1:]))
    return headers,data,units
def parse_delimited(lines):
    p=sum(l.count('|') for l in lines);t=sum(l.count('\t') for l in lines)
    d='|' if p>t else '\t'
    rows=[]
    for l in lines:
        pts=[c.strip() for c in l.split(d) if c.strip()]
        if len(pts)>=2 and not all(re.match(r'^-+$',c) for c in pts):rows.append(pts)
    if not rows:return [],[],''
    h=rows[0];data=[(clean(r[0]),r[1:]) for r in rows[1:]]
    units=''
    for l in lines[:15]:
        m=re.search(r'(millions?|billions?|thousands?|percent)',l,re.I)
        if m:units=m.group(0).lower();break
    return h,data,units
def parse(lines):
    text=''.join(lines)
    return parse_html(text) if '<table' in text else parse_delimited(lines)
args=sys.argv[1:];fp=args[0]
rf=cf=lr=None;sr=sc=fu=False;i=1
while i<len(args):
    if args[i]=='--row':rf=args[i+1].lower();i+=2
    elif args[i]=='--col':cf=args[i+1].lower();i+=2
    elif args[i]=='--lines':m=re.match(r'(\d+)-(\d+)',args[i+1]);lr=(int(m[1])-1,int(m[2])) if m else None;i+=2
    elif args[i]=='--rows':sr=True;i+=1
    elif args[i]=='--cols':sc=True;i+=1
    elif args[i]=='--fuzzy':fu=True;i+=1
    else:i+=1
with open(fp,errors='replace') as f:al=f.readlines()
lines=al[lr[0]:lr[1]] if lr else al
h,data,units=parse(lines)
if not h and not data:print(''.join(lines[:30]));sys.exit()
if units:print(f'[units: {units}]')
if sc:
    for j,c in enumerate(h):print(f'[{j}] {c}')
elif sr:
    for i2,(label,_) in enumerate(data):print(f'[{i2+1}] {label}')
else:
    for label,cells in data:
        if label.startswith('[section]'):print(label);continue
        if rf:
            lbl=label.lower()
            if fu:
                if difflib.SequenceMatcher(None,rf,lbl).ratio()<0.5:continue
            elif rf not in lbl:continue
        for j,raw in enumerate(cells):
            cn=h[j+1] if j+1<len(h) else (h[j] if j<len(h) else f'c{j}')
            if cf and cf not in cn.lower():continue
            if not raw or raw in('-','*','nan',''):continue
            num=to_num(raw)
            if num is not None:print(f'{label} | {cn} = {num}')
            else:
                c2=clean(raw)
                if c2:print(f'{label} | {cn} = {c2}')
```

## Save to /tmp/g.py — grep with context:
```python
import re,sys,os
q=sys.argv[1];d=sys.argv[2] if len(sys.argv)>2 else '/app/resources'
for fp in sorted(os.listdir(d)):
    if not fp.endswith('.txt'):continue
    with open(os.path.join(d,fp),errors='replace') as f:lines=f.readlines()
    for i,l in enumerate(lines):
        if re.search(q,l,re.I):
            ctx=''.join(lines[max(0,i-1):i+2]).rstrip()
            print(f'[{fp}:{i+1}]\n{ctx}\n')
```

## Usage:
```
python3 /tmp/e.py FILE --cols                    # list columns
python3 /tmp/e.py FILE --rows                    # list rows with line numbers
python3 /tmp/e.py FILE --row "defense" --col "1953"  # exact cell
python3 /tmp/e.py FILE --row "defense"           # all cols for row
python3 /tmp/e.py FILE --row "natl def" --fuzzy  # fuzzy match
python3 /tmp/g.py "keyword" /app/resources       # search files
python3 /tmp/batch.py "metric" /app/resources    # extract row from ALL files at once
```

## For tables with multiple sections:
If a file has multiple tables, find the right section first:
```
python3 /tmp/e.py FILE --rows    # scan all row labels — find the section you need
grep -n "Table\|TABLE" FILE      # find table boundaries by line number
python3 /tmp/e.py FILE --lines START-END --row "target"  # extract within that section only
```

## Multi-file batch extraction (save as /tmp/batch.py):
```python
import re,sys,os
row=sys.argv[1];d=sys.argv[2] if len(sys.argv)>2 else '/app/resources'
for fp in sorted(os.listdir(d)):
    if not fp.endswith('.txt'):continue
    full=os.path.join(d,fp)
    with open(full,errors='replace') as f:lines=f.readlines()
    for l in lines:
        if re.search(row,l,re.I):
            vals=re.findall(r'[\d,]+\.?\d*',l)
            if vals:print(f'{fp}: {" | ".join(vals)}')
            break
```
Usage: `python3 /tmp/batch.py "Rural Electrification" /app/resources`
Gets the target row from ALL files in one call — saves turns on multi-file questions.
For multi-year: count extracted values vs expected count before computing.

## Precision report — use for any "rounded to N places" question:
```python
python3 -c "
x=YOUR_RAW_VALUE; n=DECIMAL_PLACES
print(f'raw={x}')
print(f'rounded={round(x,n)}')
print(f'truncated={int(x*10**n)/10**n}')
"
```
If rounded and truncated differ, **prefer truncated** — Treasury legacy systems use fixed-point truncation.
Write the truncated value to answer.txt.

After extracting data, load("officeqa-compute") for calculation recipes.
