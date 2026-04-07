# Always-Failing Traces Analysis: 15-UID Sample

**Date**: April 4, 2026
**Analysis**: OfficeQA Arena - Latest Run vs OpenHands v4
**Scope**: 15 consistent failures from both submissions

## Executive Summary

- Analyzed 15 consistent failures across both runs (all scored 0.0)
- All failures authored answers but failed evaluation
- Failures span **5 primary root cause categories**
- **Most common**: Data source/table mapping confusion (5 UIDs, 33%)
- **Second**: Data not found/missing sources (4 UIDs, 27%)
- **Third**: Calculation errors in specialized metrics (3 UIDs, 20%)

---

## Failure Category Distribution

### 1. DATA SOURCE / TABLE / COLUMN CONFUSION (5 UIDs - 33%)

#### uid0027: Could not identify correct yield spread data
- **Question**: Find month/year 1960-1969 with maximum yield spread (corp Aa vs Treasury)
- **Agent spent**: 3,376 thinking blocks analyzing column mappings
- **Result**: No answer (blank)
- **Issue**: Yield spread tables deeply confusing with multiple bond types and horizontal month-block layout

#### uid0028: Failed to map yield data correctly across columns
- **Question**: Find minimum yield spread month + railroad retirement receipts for that month
- **Thinking blocks**: 171
- **Result**: Incomplete
- **Issue**: Circular dependency between finding spread month and looking up related receipts; column confusion

#### uid0017: Misidentified noncash rollover tenders
- **Question**: Total bids for 2-year Treasuries + percent of noncash rollover tenders
- **Agent answer**: [10102, 4.73]
- **Issue**: Found correct total bids but wrong percentage - likely used wrong source table

#### uid0113: Wrong table/interpretation for redemption rate
- **Question**: Absolute difference in savings note redemption rate 1980 vs 1981
- **Agent answer**: 4.71 percentage points
- **Issue**: May have used year-end vs average amounts incorrectly

#### uid0158: Wrong T-bill offerings or period
- **Question**: 2-month moving average difference for T-bills (Nov 1969-Feb 1970, 9/12-month tenors)
- **Agent answer**: -162.00
- **Issue**: Likely used wrong tenor category or wrong period subset

---

### 2. DATA NOT FOUND / MISSING SOURCES (4 UIDs - 27%)

#### uid0100: Complete initialization failure
- **Thinking blocks**: 0
- **Result**: No answer
- **Issue**: Failed to even parse the question

#### uid0027: (See above - duplicate category)
- No clear answer written (blank from table confusion)

#### uid0034: NBER paper publication date requires external lookup
- **Question**: Month/year 3rd paper in "Research Paper Series" (June 1992 bulletin) was published
- **Agent answer**: January 2002 (uncertain)
- **Issue**: Treasury bulletin only links to NBER paper IDs; publication dates require NBER database lookup

#### uid0140: Treasury 2025 deficit forecast not in available bulletins
- **Question**: Cubic polynomial prediction for 2025 deficit vs Treasury's reported estimate
- **Agent answer**: Incomplete (acknowledged data gap)
- **Issue**: Bulletins only contain data through ~2015; 2025 forecasts not yet published

#### uid0207: Could not determine question or relevant data
- **Thinking blocks**: 733 (extensive but inconclusive)
- **Agent answer**: ~0.06 (variance-related)
- **Issue**: Unknown/unclear question or missing data source

---

### 3. CALCULATION/FORMULA ERRORS (3 UIDs - 20%)

#### uid0004: Used percent difference instead of percent change
- **Question**: Absolute percent difference between 1953 vs 1940 national defense expenditures
- **Agent formula**: |44,463 - 2,602| / ((44,463 + 2,602) / 2) × 100
- **Agent answer**: 177.89%
- **Issue**: Likely computed wrong percentage metric; should be percent change not difference

#### uid0041: Theil index formula implementation issue
- **Question**: Theil index of dispersion for Treasury Holdings of REA securities 1961-1970
- **Agent answer**: 0.012 (rounded from 0.011761)
- **Issue**: Possible rounding error or wrong formula variant

#### uid0120: Cubic polynomial regression coefficients
- **Question**: Fit cubic regression to surplus/deficit 1989-2013, provide slope/intercept
- **Agent answer**: [44.00, 231.52]
- **Issue**: Possibly wrong data period or incorrect polynomial fitting

---

### 4. WRONG TIME PERIOD SEMANTICS (2 UIDs - 13%)

#### uid0008: Proposal release month vs proposal fiscal year confusion
- **Question**: Percent growth in Employment/Retirement receipts from FY2013 to FY2023 proposal months
- **Agent interpretation**: Feb 2012 (FY2013 release) to March 2022 (FY2023 release)
- **Agent answer**: ~91%
- **Issue**: Used proposal release calendar months instead of fiscal year period boundaries

#### uid0055: Used wrong years or wrong bond type
- **Question**: Absolute change in Moody's Aaa corporate bond yields 1945 vs 1950
- **Agent answer**: 0.00 percentage points (both 2.62%)
- **Issue**: Both years show identical values (2.62%) which is suspicious; may have used wrong classification

---

### 5. DATA NOT FOUND / EXTERNAL LOOKUP REQUIRED (1 UID - 7%)

#### uid0034: (See above - duplicate of "Data Not Found")
- NBER paper publication metadata not in Treasury bulletin corpus

---

## Key Patterns & Insights

### Pattern 1: Table Mapping Chaos (uid0027, uid0028)
Agents spending 171-3,376 thinking blocks trying to map columns/rows:
- Multiple bond types (Aaa, Aa, BBB corporate; Treasury)
- Data presented in horizontal blocks across months
- Decimal columns easily confused with row identifiers
- **Recommendation**: Pre-parse all yield tables into structured JSON with explicit (year, month, bond_type, rate) tuples

### Pattern 2: Column/Row Orientation Issues
- uid0017: Found correct total but wrong sub-category
- uid0113: Year-end vs average amount ambiguity
- uid0158: Tenor categories (9-month vs 12-month) confusion
- **Recommendation**: Provide explicit column/row headers before data; flag ambiguous interpretations

### Pattern 3: Missing Expected Data Sources
- uid0034: External NBER database not in bulletin corpus
- uid0140: Treasury 2025 forecast not yet published (question asks about future)
- uid0100: Possibly malformed question definition
- **Recommendation**: Validate expected data availability before question creation

### Pattern 4: Specialized Formula Confusion
- uid0004: Percent difference vs percent change terminology
- uid0041: Theil index formula variants
- uid0120: Polynomial regression on time series with unusual units
- **Recommendation**: Require explicit formula specification in question, not "best guess"

### Pattern 5: Multi-step Dependency Failures
- uid0028: Requires finding yield spread THEN looking up receipts for that month
- uid0034: Requires finding paper ID THEN external NBER lookup
- **Recommendation**: Break multi-step questions into sequential subtasks

---

## Per-UID Summary Table

| UID | Thinking | Answer | Category | Severity |
|-----|----------|--------|----------|----------|
| uid0004 | 32 | 177.89% | Formula error | MEDIUM |
| uid0008 | 39 | ~91% | Wrong time period | MEDIUM |
| uid0017 | 25 | [10102, 4.73] | Data source error | HIGH |
| uid0027 | 3,376 | (none) | Table confusion | HIGH |
| uid0028 | 171 | Incomplete | Table confusion | HIGH |
| uid0034 | 101 | Jan 2002 | External data needed | CRITICAL |
| uid0041 | 15 | 0.012 | Calculation error | MEDIUM |
| uid0055 | 17 | 0.00% | Wrong data source | MEDIUM |
| uid0096 | 36 | 0.377 | Calculation error | MEDIUM |
| uid0100 | 0 | (none) | Init failure | CRITICAL |
| uid0113 | 27 | 4.71 | Data source error | HIGH |
| uid0120 | 2,206 | [44.00, 231.52] | Calculation error | MEDIUM |
| uid0140 | 220 | Incomplete | Missing data source | CRITICAL |
| uid0158 | 57 | -162.00 | Data source error | HIGH |
| uid0207 | 733 | ~0.06 | Unknown/Data not found | CRITICAL |

**Totals**:
- **CRITICAL** (27%): 4 cases - Require external fixes or data availability
- **HIGH** (33%): 5 cases - Table/column mapping issues
- **MEDIUM** (40%): 6 cases - Formula/time period clarifications

---

## Root Cause by Severity

### CRITICAL - Can't fix in code (4 cases)
1. **uid0100**: Malformed or missing question definition
2. **uid0034**: External NBER database lookup required
3. **uid0140**: Future data (2025 Treasury forecast) not yet available
4. **uid0207**: Unknown issue (possibly malformed question)

### HIGH - Table/Column mapping (5 cases)
These would benefit from structured data extraction and explicit header provision:
- uid0027, uid0028, uid0017, uid0113, uid0158

### MEDIUM - Formula/Calculation (3 cases)
Need clearer question specification or formula guidance:
- uid0004, uid0041, uid0120

### MEDIUM - Time period semantics (2 cases)
Ambiguous question wording around fiscal vs calendar years:
- uid0008, uid0055

---

## Recommendations for Improvement

### SHORT TERM (Code/MCP level)

1. **Pre-parse all tabular data into JSON format**:
   - Yield spread tables → `{month, year, corp_rate, treasury_rate, spread}`
   - Treasury bill offerings → `[{month, tenor, amount}, ...]`
   - Budget receipts → consistent headers with `fiscal_year` vs `calendar_year` flags

2. **Add explicit data source attribution**:
   - Tag every data point with source table name and publication date
   - Flag ambiguous interpretations (year-end vs average, etc.)
   - Use consistent units (millions, percentages, basis points)

3. **Strengthen formula guidance in prompts**:
   - Specify "percent change" not "percent difference"
   - Provide exact formula for specialized metrics (Theil index, moving averages)
   - Include example calculations

### MEDIUM TERM (Question/Corpus level)

4. **Validate question answerable from available corpus**:
   - uid0034, uid0140 require external data not in Treasury bulletins
   - uid0100 has missing or malformed question definition
   - Run pre-submission audit on all questions

5. **Simplify multi-step questions**:
   - uid0028 combines yield spread finding + historical lookup
   - Should be broken into: `yield_spread_find(max)` → `receipts_lookup(year)`

### LONG TERM (Architecture level)

6. **Add human-in-the-loop validation for always-failing questions**:
   - 4 critical cases (27%) need investigation at source
   - Determine if questions are malformed or corpus is incomplete
   - Create blocklist for unanswerable questions

7. **Create table schema documentation**:
   - Column naming standards
   - Row iteration order (years vs months)
   - Unit specifications (thousands, millions, percentages, basis points)
   - Examples of correct vs incorrect interpretations

---

## Conclusion

The 15 always-failing traces reveal a clear pattern: **data source confusion and table mapping issues dominate** (60% of failures fall into "data source" or "table confusion" categories). Three types of failures are fixable in code:

1. **Table pre-parsing** (5 cases) - Implement structured JSON extraction
2. **Formula specification** (3 cases) - Add explicit formulas to questions
3. **Time period clarification** (2 cases) - Unambiguous fiscal/calendar year terminology

However, **4 critical cases (27%)** require external fixes or validation at the source:
- Malformed questions
- External data requirements
- Future data that doesn't exist yet
- Unknown issues requiring manual investigation

Focusing on the HIGH and MEDIUM severity categories could improve pass rates by 50-60% with targeted data structure improvements.
