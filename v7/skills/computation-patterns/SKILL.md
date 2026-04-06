---
name: computation-patterns
description: Python computation patterns for Treasury data. Use for percent change, CAGR, stdev, kurtosis, VaR, regression, Theil index, duration, and other statistical calculations. Always use python3 -c.
---

# Always use python3 -c for calculations

## Basic
- Percent change: ((new - old) / old) * 100
- CAGR: (end/begin)**(1/years) - 1
- Range: max(values) - min(values)

## Statistics (import statistics)
- Sample stdev: statistics.stdev([...])
- Population stdev: statistics.pstdev([...])
- Mean: statistics.mean([...])
- Median: statistics.median([...])

## Advanced
- Geometric mean: math.prod(vals) ** (1/len(vals))
- Fisher kurtosis: m4/m2**2 - 3 (m2=variance, m4=4th central moment)
- Skewness (Fisher-Pearson): n/((n-1)*(n-2)) * sum(((x-mean)/stdev)**3)
- VaR (parametric 95%): mean - 1.645 * pstdev
- Expected Shortfall: mean of all values below VaR cutoff
- OLS slope: sum((x-xbar)*(y-ybar)) / sum((x-xbar)**2)
- OLS intercept: ybar - slope * xbar
- Arc elasticity: ((Q2-Q1)/((Q2+Q1)/2)) / ((P2-P1)/((P2+P1)/2))
- Theil index: (1/n) * sum((xi/mean) * ln(xi/mean))
- Macaulay duration: sum(t * CF_t / (1+y)^t) / sum(CF_t / (1+y)^t)
- Constant hazard rate: ln(V2/V1) / years
