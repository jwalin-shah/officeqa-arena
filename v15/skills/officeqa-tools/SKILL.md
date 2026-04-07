---
name: officeqa-tools
description: Table parser + computation recipes with data requirements
---

## Save this table parser to /tmp/e.py:
```python
import re,sys
args=sys.argv[1:]
fp=args[0]
rf=cf=lr=None;sr=sc=False;i=1
while i<len(args):
    if args[i]=='--row':rf=args[i+1].lower();i+=2
    elif args[i]=='--col':cf=args[i+1].lower();i+=2
    elif args[i]=='--lines':m=re.match(r'(\d+)-(\d+)',args[i+1]);lr=(int(m[1])-1,int(m[2])) if m else None;i+=2
    elif args[i]=='--rows':sr=True;i+=1
    elif args[i]=='--cols':sc=True;i+=1
    else:i+=1
with open(fp,errors='replace') as f:al=f.readlines()
lines=al[lr[0]:lr[1]] if lr else al
p=sum(l.count('|') for l in lines);t=sum(l.count('\t') for l in lines)
d='|' if p>t else '\t'
rows=[]
for n,l in enumerate(lines):
    pts=[c.strip() for c in l.split(d) if c.strip()]
    if len(pts)>=2:rows.append((n,pts))
if not rows:print(''.join(lines[:30]));sys.exit()
h=rows[0][1];data=rows[1:]
if sc:
    for j,c in enumerate(h):print(f'[{j}] {c}')
elif sr:
    for n,pts in data:print(f'[{n+1}] {pts[0]}')
else:
    for n,pts in data:
        if rf and rf not in pts[0].lower():continue
        for j in range(1,len(pts)):
            cn=h[j] if j<len(h) else f'c{j}'
            if cf and cf not in cn.lower():continue
            if pts[j] and pts[j]!='nan':print(f'{pts[0]} | {cn} = {pts[j]}')
```

## Save this grep helper to /tmp/g.py:
```python
import re,sys,os
q=sys.argv[1];d=sys.argv[2] if len(sys.argv)>2 else '/app/resources'
for fp in sorted(os.listdir(d)):
    if not fp.endswith('.txt'):continue
    full=os.path.join(d,fp)
    with open(full,errors='replace') as f:lines=f.readlines()
    for i,l in enumerate(lines):
        if re.search(q,l,re.I):
            ctx=''.join(lines[max(0,i-1):i+2]).rstrip()
            print(f'[{fp}:{i+1}]\n{ctx}\n')
```
Usage: `python3 /tmp/g.py "national defense" /app/resources`

## Computation recipes — what data you need and how to compute:

**Sum of monthly values (56% of questions):**
Data: extract all 12 month values for one row. Use: `python3 /tmp/e.py FILE --row "metric"`
Compute: `python3 -c "print(sum([v1,v2,...,v12]))"`

**Percent change:**
Data: extract OLD value and NEW value (same row, two different year/month columns).
Compute: `python3 -c "print((NEW-OLD)/OLD*100)"`

**Standard deviation (sample/population):**
Data: extract N values (all months or all years for one metric).
Compute: `python3 -c "import statistics; print(statistics.stdev([v1,v2,...]))"`
Population: use `pstdev` instead of `stdev`.

**Geometric mean:**
Data: extract N positive values.
Compute: `python3 -c "import statistics; print(statistics.geometric_mean([v1,v2,...]))"`

**Linear regression:**
Data: extract paired (x,y) values — x=year or month index, y=metric values.
Compute: `python3 -c "import statistics; r=statistics.linear_regression([x1,x2,...],[y1,y2,...]); print(r.slope,r.intercept)"`
Correlation: `python3 -c "import statistics; print(statistics.correlation([x1,...],[y1,...]))"`

**Theil index:**
Data: extract N positive values for one metric across time periods.
Compute: `python3 -c "import math; v=[v1,v2,...]; m=sum(v)/len(v); print(sum((x/m)*math.log(x/m) for x in v)/len(v))"`

**Z-score:**
Data: extract the full series AND the target value.
Compute: `python3 -c "import statistics; v=[v1,v2,...]; t=TARGET; print((t-statistics.mean(v))/statistics.stdev(v))"`

**Expected shortfall (95%):**
Data: extract all return/loss values.
Compute: `python3 -c "v=sorted([v1,v2,...]); c=max(1,int(len(v)*0.05)); print(sum(v[:c])/c)"`

**CAGR:**
Data: extract start value, end value, count years between them.
Compute: `python3 -c "print(((END/START)**(1/YEARS)-1)*100)"`

**Continuously compounded growth:**
Data: same as CAGR.
Compute: `python3 -c "import math; print(math.log(END/START)/YEARS)"`
