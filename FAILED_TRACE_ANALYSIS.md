# Failed Trace Analysis: v5.0.0_184 (31 UIDs)

## Summary Table

| UID | Category | Formula Needed | Agent Answer | What Went Wrong | Fixable w/ Cheat Sheet? |
|-----|----------|---------------|-------------|-----------------|------------------------|
| uid0011 | Complex | Page lookup | 72 | Found "Series E Savings Bonds" table on pg 72, but question asks specifically for "payroll saving plans" sub-table which is on a different page. Data retrieval error, not computation. | No |
| uid0027 | Complex | Yield spread -> (month*100)+year | 2269 | Computed (3*100)+1969=2269. Formula and yield spread identification look correct. Likely wrong data extraction from multi-column table, or wrong month/year identification. | No |
| uid0059 | Complex | CAGR | 23.19 | CAGR = (1353.7/724.1)^(1/3)-1 = 23.19%. Formula is correct. Likely wrong data values extracted (wrong row/column from table), or wrong number of years (FY1947 to FY1950 = 3 years is correct). | Unlikely |
| uid0069 | Complex | Expected Shortfall (ES) at 95% | 18.51 | Used year-over-year yield changes as "returns". ES = average of returns below 5th percentile. With only 9 data points, ES = worst return = -18.51%. Method seems reasonable but may have wrong yield data or wrong ES definition. | Maybe |
| uid0071 | Complex | Population std dev | 1.017766 | Found only 3 TIPS auction prices. Pop std dev of [99.342, 99.213, 101.434] = 1.017766. May be missing data points or using wrong price type (unadjusted vs adjusted). | No |
| uid0084 | Complex | OLS forecast error (actual-forecast) | 0.262857 | OLS on FY1961-1967 interest data, forecast FY1968. Error = (4499-4236.14)/1000 = 0.262857 billion. Same underlying data as uid0074. Error might be in billions vs millions conversion, or wrong column from table. | Maybe |
| uid0098 | Complex | 20% trimmed mean of ln() | 28.150 | Converted millions to actual dollars then took ln (ln(666472e6)=27.2, etc). Method correct. 20% trim on 9 values = trim 1 each end. Answer 28.150. Likely wrong borrowings data extracted from tables (wrong row or column). | No |
| uid0102 | Complex | IQR (H-spread) Type 7 | 65.20 | Type 7 quartile positions correct: Q1 at pos 3.25, Q3 at pos 9.75. But agent rounded intermediate values to tenths BEFORE computing H-spread. Q1=5.15->5.1, Q3=70.325->70.3, H=65.2. Should keep full precision until final rounding. | Yes |
| uid0105 | Complex | Fisher excess kurtosis (unbiased) | -3.941 | Kurtosis formula applied to paper money in circulation FY1941-1950. Formula seems correct (using bias-corrected sample kurtosis). Could be wrong data values or wrong kurtosis formula variant. | Maybe |
| uid0120 | Complex | CPI adjustment + linear regression | [44.31, 230.66] | Adjusted savings bond redemptions to March 1970 dollars using CPI, then fit regression on 3 points (x=1,2,3). Only 3 data points makes regression fragile. Could have wrong CPI values or wrong redemption data. | No |
| uid0123 | Complex | Percentage + Pearson correlation | [26.7, 0.932] | Computed American vessels as % of grand total = 26.7% and Pearson r = 0.932 for Jan-Mar 1941. Could have wrong data extraction or wrong table (gross vs net tonnage). | No |
| uid0144 | Complex | VaR (parametric) | 155 | VaR = mean - 1.645*sigma. Data had a discontinuity: 1980 bulletin shows Oct=303 but 1981 bulletin shows Nov=102,Dec=100. This is likely a data extraction error (missing leading digit). Mean=274.6, sigma=73.0, VaR=155. Data quality issue. | No |
| uid0150 | Complex | Exponential smoothing + FX conversion | [175.90, 17.79] | SES with alpha=0.3 on 4 bid prices. Forecast=74.50. FX rate used: 2.361 DEM/USD. The FX rate source is questionable (used "March 1, 1975" rate but may need "March 1, 1976"). Multi-step compounding of errors. | No |
| uid0165 | Complex | VaR + FX conversion | 29639 | Used parametric VaR: mean_loss + 2.326*sigma. Foreign holdings changes have only 4 data points. VaR=272.09B USD * 108.93 JPY/USD = 29639B JPY. Could have wrong holdings data or wrong VaR method (parametric vs historical). | Maybe |
| uid0170 | Complex | HHI + effective number | [6114.969, 1.635] | HHI = 6114.969 (0-10000 scale). Effective number = 10000/6114.969 = 1.635 (normalized). But question says "reciprocal of HHI" which could mean 1/0.6115 = 1.635 or literal 1/6114.969. Interpretation ambiguity. | Maybe |
| uid0174 | Complex | Arc elasticity | -3.147 | Formula correct: (deltaQ/avgQ)/(deltaP/avgP). Values plugged in correctly. Could be wrong data extraction for total collections or unemployment insurance. | No |
| uid0188 | Complex | Silver quantity * inflation-adjusted price | 22784.07 | Complex multi-step: nominal value / statutory rate = ounces, then ounces * inflation-adjusted silver price. Many opportunities for wrong historical silver prices or wrong CPI values. | No |
| uid0193 | Complex | Forecast error % / FX rate | 1.6431 | Linear forecast of fish imports, then error% / exchange rate. Used $4.03/GBP as 1941 rate. Could be wrong fish import data, wrong exchange rate, or wrong forecast method. | No |
| uid0196 | Complex | CPI adjustment + MoM change | -415.45 | May 1979 FRN adjusted to June 1979 dollars: 103774*(259.2/255.7)=105194.45. Change = 104779-105194.45 = -415.45. **Agent hallucinated CPI-U values** (255.7 and 259.2 don't match any BLS base year for 1979). Actual CPI-U 1982-84=100 for May/Jun 1979 would be ~72-73. CPI wasn't in the data files, model made up numbers. | Yes |
| uid0213 | Complex | Inflation-adjusted difference | -470.0 | Dec 1946 balance adjusted to 1947 dollars: 7585.3*(23.0/20.3)=8593.0. Diff = 8124.2-8593.0 = -468.8 (agent got -470.0). CPI values 20.3 and 23.0 may be wrong. Could also be annual vs December CPI. | Maybe |
| uid0219 | Complex | CAGR ratio | 4.5 | Foreign holdings CAGR (March 2003 to Dec 2012) / GDP CAGR (2003-2012). Used 9 years for both. But holdings dates are March 2003 vs December 2012 (not same month). Period mismatch or wrong data values. | Maybe |
| uid0223 | Complex | Linear regression + counterfactual | 13.36 | 2-point regression (only 2 data points). Germany GDP growth rate applied to Europe value. Many compounding assumptions. Could be wrong GDP values or wrong interpretation. | No |
| uid0229 | Complex | VaR historical simulation | 0.0149 | 3 returns, position = 4*0.05=0.2. VaR = r[0]+0.2*(r[1]-r[0]) = 0.0149. With only 3 data points, VaR estimation is highly unstable. Method looks correct but could be wrong percentile convention. | Maybe |
| uid0018 | Computation | Geometric mean | 80.289 | Geometric mean of 39 monthly judiciary outlays. Formula correct. Could be wrong data values extracted from tables across 4 bulletins. | No |
| uid0041 | Computation | Theil index | 0.012 | T = (1/n)*sum((yi/ybar)*ln(yi/ybar)). Applied to Rural Electrification Admin 1961-1970. Formula correct. Could be wrong data values. | No |
| uid0073 | Computation | Population std dev | 6379.29 | Pop std dev of 12 monthly net outlays FY1981. Question says "net outlays by function" which might mean per-function breakdown, not total. Ambiguous question interpretation. | Maybe |
| uid0074 | Computation | OLS forecast error (forecast-actual) | -262.86 | Same data as uid0084 but different sign convention. Forecast-actual = 4236.14-4499 = -262.86 million. Question asks for answer in millions. This might actually be correct for the question's convention. | Maybe |
| uid0101 | Computation | CAGR + decay factor + arc elasticity | [-0.153, 0.847, -292.567] | Three calculations. CAGR=(35810/135030)^(1/8)-1=-0.153. Decay=0.847. Arc elasticity uses midpoint method. Values could be wrong data extraction. | No |
| uid0136 | Computation | Geometric mean of rates | 1.558 | Geometric mean of 14 weekly discount rates across Sep 1953-1955. Formula correct. Could have wrong rate values or missing/extra rates. | No |
| uid0148 | Computation | Count + geometric mean | [29, 2446.22] | Counted 13-week bills with amount > 2400M issued Feb-Apr 1972-1974. Complex filtering criteria could be misinterpreted. | No |
| uid0212 | Computation | Continuously compounded growth rate | 0.063 | ln(807.0/429.5)/10 = 0.063. Formula correct. Could be wrong data values (429.5 and 807.0) from tables. | No |


## Root Cause Categories

### 1. Wrong Data Extraction (15 UIDs) -- NOT fixable with formula cheat sheet
UIDs: uid0011, uid0027, uid0071, uid0120, uid0123, uid0144, uid0150, uid0174, uid0188, uid0193, uid0018, uid0041, uid0101, uid0136, uid0148

The agent found plausible-looking data but extracted wrong values from complex multi-column tables, used the wrong table, or missed data points. No formula fix helps here.

### 2. Wrong Formula/Method (5 UIDs) -- Fixable with formula cheat sheet
UIDs: uid0102, uid0196, uid0069, uid0165, uid0229

- **uid0102**: Rounded intermediate quartile values before computing H-spread
- **uid0196**: Agent hallucinated CPI-U values (255.7/259.2 for May/Jun 1979 -- no BLS series has these values). The data files didn't contain CPI data so the model fabricated numbers.
- **uid0069**: ES with only 9 data points, questionable interpolation
- **uid0165**: Parametric VaR with only 4 data points
- **uid0229**: VaR percentile interpolation with only 3 data points

### 3. Ambiguous Interpretation (7 UIDs) -- Partially fixable
UIDs: uid0059, uid0084, uid0073, uid0074, uid0105, uid0170, uid0213, uid0219, uid0223

The question wording is ambiguous (e.g., "by function" meaning total vs per-function, sign convention for forecast error, HHI scale, CPI annual vs monthly). Clearer formulas might help some but not all.

### 4. Insufficient Data Points for Statistical Methods (3 UIDs)
UIDs: uid0069 (9 points for ES), uid0165 (4 points for VaR), uid0229 (3 points for VaR)

These questions ask for statistical measures on tiny datasets. The agent applied correct formulas but the specific interpolation/estimation method matters enormously with so few points.


## Formula Cheat Sheet (for system prompt)

```
COMPUTATION REFERENCE -- use these exact methods:

1. CAGR (Compound Annual Growth Rate):
   CAGR = (end_value / start_value)^(1/n) - 1
   where n = number of YEARS between measurements (not number of data points)
   Report as decimal (0.2319) unless question says "percent" (23.19%)

2. Continuously Compounded Growth Rate:
   r = ln(end_value / start_value) / n
   Report as decimal unless told otherwise

3. Geometric Mean of N values:
   GM = (product of all values)^(1/N)
   For rates/percentages: use the raw rate values (e.g., 1.961, not 0.01961)

4. Population Standard Deviation:
   sigma = sqrt( sum((xi - mean)^2) / N )
   Use N in denominator (not N-1). Keep full precision until final rounding.

5. Sample Standard Deviation:
   s = sqrt( sum((xi - mean)^2) / (N-1) )

6. Fisher Excess Kurtosis (unbiased/sample):
   g2 = [n(n+1)/((n-1)(n-2)(n-3))] * sum(((xi-mean)/s)^4) - [3(n-1)^2/((n-2)(n-3))]
   where s is SAMPLE std dev (N-1 denominator)

7. Theil Index:
   T = (1/n) * sum( (yi/ybar) * ln(yi/ybar) )

8. OLS Linear Regression (simple):
   slope = [n*sum(xi*yi) - sum(xi)*sum(yi)] / [n*sum(xi^2) - (sum(xi))^2]
   intercept = ybar - slope * xbar
   Forecast error: check question for convention:
     - "actual - forecast" means (actual - predicted)
     - "forecast - actual" means (predicted - actual)
     - "forecast error" alone typically means (actual - predicted)

9. Arc Elasticity (midpoint method):
   E = (deltaQ / avgQ) / (deltaP / avgP)
   where avgQ = (Q1+Q2)/2, avgP = (P1+P2)/2

10. Value at Risk (VaR) - Parametric:
    VaR = mean + z * sigma  (loss convention: VaR = mean - z * sigma)
    z values: 1% -> 2.326, 5% -> 1.645, 10% -> 1.282
    NOTE: With < 30 data points, prefer historical simulation over parametric

11. Value at Risk (VaR) - Historical Simulation:
    Sort returns ascending. Position = (N+1) * alpha
    If position is fractional, interpolate between adjacent sorted values.
    With very few data points (< 5), the result is unreliable.
    5th percentile of 3 values: position = 4*0.05 = 0.2
      -> VaR = sorted[0] + 0.2*(sorted[1]-sorted[0])

12. Expected Shortfall (ES) / CVaR at confidence level c:
    ES = average of all returns below the VaR threshold
    For 95% confidence: average of returns below 5th percentile
    With few data points: if only 1 return is below threshold, ES = that return

13. Quartiles (Type 7 / Linear Interpolation):
    Position p for quantile q: p = 1 + (N-1)*q
    Q1: p = 1 + (N-1)*0.25
    Q3: p = 1 + (N-1)*0.75
    Interpolate: value = sorted[floor(p)-1] + frac(p) * (sorted[floor(p)] - sorted[floor(p)-1])
    H-Spread (IQR) = Q3 - Q1
    IMPORTANT: Do NOT round intermediate quartile values. Only round the final answer.

14. Simple Exponential Smoothing:
    S_1 = Y_1 (initialize with first observation)
    S_t = alpha * Y_t + (1 - alpha) * S_{t-1}
    Forecast for next period = S_last

15. Herfindahl-Hirschman Index (HHI):
    HHI = sum(si^2) where si are market shares
    If shares are in percent (0-100): HHI ranges 0-10000
    If shares are in decimal (0-1): HHI ranges 0-1
    Effective number of firms = 1/HHI (using decimal shares, i.e., 1/sum(si^2))
    If using percent shares: effective number = 10000/HHI

16. Pearson Correlation Coefficient:
    r = [n*sum(xi*yi) - sum(xi)*sum(yi)] / sqrt([n*sum(xi^2)-(sum(xi))^2]*[n*sum(yi^2)-(sum(yi))^2])

17. CPI Inflation Adjustment:
    real_value = nominal_value * (CPI_target / CPI_base)
    CRITICAL: Check which CPI-U base year the question uses:
    - Pre-1978 data: CPI-U base 1967=100 (values ~30-80 for 1940s-1970s)
    - Post-1988 data: CPI-U base 1982-84=100 (values ~120-300 for 1990s-2020s)
    Use MONTHLY CPI values when adjusting monthly data.
    Use ANNUAL AVERAGE CPI when question says "for those years."

18. Trimmed Mean:
    For k% trimmed mean with N values:
    - Number to trim from each end = floor(N * k/100)
    - If N*k/100 is not integer, trim floor() from each end
    - Compute mean of remaining values

19. Natural Logarithm for financial data:
    Read the question carefully for unit specification.
    If question says "ln of borrowings" and data is in millions, check whether
    the question means ln(value_in_millions) or ln(value_in_actual_dollars).
    - ln(1,419,286 million as millions) = ln(1419286) = 14.166
    - ln(1,419,286 million as dollars) = ln(1419286 * 1e6) = ln(1.419e12) = 27.98
    Default: use the values as given in the source data units.

20. Percent Change:
    Simple: (new - old) / old * 100
    For CAGR over multiple periods, see formula #1.
```

## Estimate: How Many Would Be Fixed?

**Clearly fixable with cheat sheet: 2-3 UIDs**
- uid0102: Would be fixed by "do not round intermediates" rule
- uid0196: Partially fixable -- cheat sheet says "use monthly CPI values" and provides base year guidance, but the real problem is the agent HALLUCINATED CPI values when they weren't in the data files. A cheat sheet can't fix hallucination; we'd need CPI data in the corpus or a web lookup tool.
- uid0069: Possibly fixed with clearer ES definition

**Possibly fixable: 3-5 UIDs**
- uid0084/uid0074: Sign convention clarity would help (same underlying question, different error direction)
- uid0073: "by function" interpretation guidance
- uid0170: HHI scale clarification
- uid0229: VaR interpolation method clarity

**Not fixable with formulas alone: 22-24 UIDs**
Most failures are data extraction errors (wrong table, wrong column, wrong row, missing data points). The agent applied reasonable formulas but to wrong inputs. Several questions also require external data (CPI, GDP, exchange rates) that the agent hallucinated rather than looked up.

### Bottom Line
**Estimated improvement: 3-5 UIDs out of 31 (10-16%)**

The formula cheat sheet will primarily help with:
1. Intermediate rounding errors (uid0102) -- clear win
2. Sign conventions for forecast errors (uid0084/uid0074)
3. Statistical method selection with small samples (uid0229, uid0069)

### Bigger Wins (not formula-related):
1. **CPI/GDP/FX data in corpus**: 5-6 UIDs (uid0196, uid0213, uid0165, uid0193, uid0219, uid0223) require external economic data that the agent hallucinated. Providing a CPI lookup table would directly fix uid0196 and uid0213.
2. **Better table parsing**: 15+ UIDs extracted wrong values from complex multi-column Treasury Bulletin tables. Better column identification or structured data would help more than any formula guidance.
3. **Data validation**: The agent rarely cross-checks extracted values. A prompt instruction like "verify extracted numbers by reading the raw source text" could catch some extraction errors.
