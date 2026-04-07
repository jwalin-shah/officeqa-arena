---
name: officeqa-compute
description: Python one-liner recipes for common Treasury Bulletin calculations — stdev, regression, pct change, CAGR, etc.
---

All recipes use python3 -c with extracted values. Replace [...] with your actual numbers.

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
