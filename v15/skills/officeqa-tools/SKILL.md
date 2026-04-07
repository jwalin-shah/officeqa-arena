---
name: officeqa-tools
description: Table parser + computation recipes — save scripts to /tmp
---

## Save to /tmp/e.py — robust table extractor:
```python
import re,sys,difflib
def clean(v):
    v=re.sub(r'\s*[0-9]+/\s*$','',v) # strip footnotes like 3/
    v=re.sub(r'^[rp]/\s*','',v) # strip r/ p/ prefixes
    m=re.match(r'^\(([0-9,.]+)\)$',v) # (123) = -123
    if m:v='-'+m.group(1)
    return v.strip()
def to_num(v):
    v=clean(v).replace(',','').replace('$','').replace('%','')
    try:return float(v)
    except:return None
def parse(lines):
    p=sum(l.count('|') for l in lines);t=sum(l.count('\t') for l in lines)
    d='|' if p>t else '\t'
    rows=[]
    for n,l in enumerate(lines):
        pts=[c.strip() for c in l.split(d) if c.strip()]
        if len(pts)>=2:rows.append((n,pts))
    if not rows:return [],[],''
    h=rows[0][1];data=rows[1:]
    units=''
    for l in lines[:15]:
        m=re.search(r'(millions?|billions?|thousands?|percent)',l,re.I)
        if m:units=m.group(0).lower();break
    return h,data,units
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
if not h:print(''.join(lines[:30]));sys.exit()
if units:print(f'[units: {units}]')
if sc:
    for j,c in enumerate(h):print(f'[{j}] {c}')
elif sr:
    for n,pts in data:print(f'[{n+1}] {pts[0]}')
else:
    for n,pts in data:
        label=pts[0]
        if rf:
            if fu:
                ratio=difflib.SequenceMatcher(None,rf,label.lower()).ratio()
                if ratio<0.5:continue
            elif rf not in label.lower():continue
        for j in range(1,len(pts)):
            cn=h[j] if j<len(h) else f'c{j}'
            if cf and cf not in cn.lower():continue
            raw=pts[j] if j<len(pts) else ''
            if not raw or raw=='nan':continue
            num=to_num(raw)
            if num is not None:print(f'{label} | {cn} = {num}')
            else:print(f'{label} | {cn} = {clean(raw)}')
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
python3 /tmp/e.py FILE --rows                    # list rows
python3 /tmp/e.py FILE --row "defense" --col "1953"  # exact cell
python3 /tmp/e.py FILE --row "defense"           # all cols for row
python3 /tmp/e.py FILE --row "natl def" --fuzzy  # fuzzy match
python3 /tmp/g.py "keyword" /app/resources       # search files
```

## Computation recipes — what data you need:

**Sum monthly values:** extract 12 months → `python3 -c "print(sum([v1,...,v12]))"`
**Pct change:** extract old, new → `python3 -c "print((NEW-OLD)/OLD*100)"`
**Stdev (sample):** extract N values → `python3 -c "import statistics; print(statistics.stdev([...]))"`
**Stdev (population):** → `statistics.pstdev([...])`
**Geometric mean:** N positive values → `statistics.geometric_mean([...])`
**Regression:** paired (x,y) → `r=statistics.linear_regression(xs,ys); print(r.slope,r.intercept)`
**Correlation:** → `statistics.correlation(xs,ys)`
**Theil index:** N values → `import math; v=[...]; m=sum(v)/len(v); print(sum((x/m)*math.log(x/m) for x in v)/len(v))`
**Z-score:** series + target → `print((TARGET-statistics.mean(v))/statistics.stdev(v))`
**Expected shortfall 95%:** → `v=sorted([...]); c=max(1,int(len(v)*0.05)); print(sum(v[:c])/c)`
**CAGR:** start,end,years → `print(((END/START)**(1/YEARS)-1)*100)`
**Compounded growth:** → `import math; print(math.log(END/START)/YEARS)`
