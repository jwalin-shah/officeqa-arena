# OfficeQA Full Evaluation Set Analysis

**Analysis Date:** 2026-03-30

**Dataset:** officeqa_full.csv (Evaluation Set)

## Summary Overview

- **Total Questions:** 246
- **Easy Questions:** 113
- **Hard Questions:** 133
- **Difficulty Ratio:** 45.9% easy, 54.1% hard

---

## Section 1: Question Type Distribution

The following table shows how questions are distributed across different question types:

| Question Type | Count | % of Total | Easy | Hard | Easy % |
|---|---:|---:|---:|---:|---:|
| aggregation | 78 | 31.7% | 43 | 35 | 55.1% |
| lookup | 35 | 14.2% | 18 | 17 | 51.4% |
| difference | 29 | 11.8% | 12 | 17 | 41.4% |
| statistical_deviation | 19 | 7.7% | 8 | 11 | 42.1% |
| regression | 17 | 6.9% | 6 | 11 | 35.3% |
| percent_change | 16 | 6.5% | 10 | 6 | 62.5% |
| change | 16 | 6.5% | 7 | 9 | 43.8% |
| percentage | 10 | 4.1% | 3 | 7 | 30.0% |
| statistical_geometric_mean | 8 | 3.3% | 0 | 8 | 0.0% |
| growth_cagr | 6 | 2.4% | 2 | 4 | 33.3% |
| ratio | 5 | 2.0% | 3 | 2 | 60.0% |
| growth_rate | 5 | 2.0% | 1 | 4 | 20.0% |
| visual | 2 | 0.8% | 0 | 2 | 0.0% |

**Key Observations:**

1. **Aggregation questions dominate** (78 questions, 31.7%): These are "sum" or "total" calculations. They have a relatively high easy rate (55.1%), making them a strong category for scoring.

2. **Lookup questions are common** (35 questions, 14.2%): Simple fact retrieval with balanced difficulty.

3. **Geometric mean is hardest** (0% easy): All 8 geometric mean questions are marked hard—these are a known weak spot.

4. **Visual questions are rare but hard** (2 questions): Only 0 easy, 2 hard. Likely impossible without image processing.

---

## Section 2: Answer Format Analysis

The format of the expected answer correlates strongly with difficulty:

| Answer Format | Count | % of Total | Easy | Hard | Easy % |
|---|---:|---:|---:|---:|---:|
| plain_number | 196 | 79.7% | 93 | 103 | 47.4% |
| bracket_list | 20 | 8.1% | 2 | 18 | 10.0% |
| percentage | 16 | 6.5% | 9 | 7 | 56.2% |
| text_with_commas | 6 | 2.4% | 5 | 1 | 83.3% |
| number_with_units | 5 | 2.0% | 3 | 2 | 60.0% |
| text | 3 | 1.2% | 1 | 2 | 33.3% |

**Key Observations:**

1. **Plain numbers dominate** (196 questions, 79.7%): Most answers are numeric values. Split fairly evenly between easy and hard.

2. **Bracket lists are very hard** (90% hard, 18/20 questions): These require returning a specific list format, suggesting multi-step or complex extraction.

3. **Percentages are more forgiving** (16 questions): 56.2% easy, suggesting they're easier to calculate correctly.

4. **Text-with-commas has highest easy rate** (5/6 = 83.3%): Might be simpler queries.

---

## Section 3: Source File Complexity

The number of source documents required affects question difficulty:

| # of Files | Count | % of Total |
|---|---:|---:|
| 1 | 126 | 51.2% |
| 2 | 68 | 27.6% |
| 3 | 31 | 12.6% |
| 4 | 13 | 5.3% |
| 5 | 7 | 2.8% |
| 12 | 1 | 0.4% |

**Summary:**

- **Single-file questions** (126 questions): 51.2% of the dataset. Most straightforward.
- **Multi-file questions** (120 questions): 48.8% require combining data from multiple documents.
- **Max complexity:** 12 files (1 question)

---

## Section 4: Expected Score Projection

Based on observed difficulty distribution and assumed baseline performance:

**Assumptions:**
- Easy questions: ~70% pass rate (achievable with good NLP + basic arithmetic)
- Hard questions: ~40% pass rate (require advanced reasoning, multi-file integration, or specialized math)
- Current performance: 55% overall (from 20-question sample)

### Projected Scores by Question Type

| Question Type | Total | Easy | Hard | Expected Correct | Est. Rate |
|---|---:|---:|---:|---:|---:|
| aggregation | 78 | 43 | 35 | 44.1 | 56.5% |
| lookup | 35 | 18 | 17 | 19.4 | 55.4% |
| difference | 29 | 12 | 17 | 15.2 | 52.4% |
| statistical_deviation | 19 | 8 | 11 | 10.0 | 52.6% |
| regression | 17 | 6 | 11 | 8.6 | 50.6% |
| percent_change | 16 | 10 | 6 | 9.4 | 58.8% |
| change | 16 | 7 | 9 | 8.5 | 53.1% |
| percentage | 10 | 3 | 7 | 4.9 | 49.0% |
| statistical_geometric_mean | 8 | 0 | 8 | 3.2 | 40.0% |
| growth_cagr | 6 | 2 | 4 | 3.0 | 50.0% |
| ratio | 5 | 3 | 2 | 2.9 | 58.0% |
| growth_rate | 5 | 1 | 4 | 2.3 | 46.0% |
| visual | 2 | 0 | 2 | 0.8 | 40.0% |

| **TOTAL** | **246** | **113** | **133** | **132.3** | **53.8%** |

---

## Section 5: Easiest Wins & Low-Hanging Fruit

Based on the analysis, here are the categories most likely to improve our score with targeted fixes:

### Category 1: Aggregation Questions (78 questions, 55.1% easy)

- **Current estimated pass rate:** ~61%
- **Potential gain:** Improve by 5-10% with better sum/total extraction
- **Why:** Many are marked "easy" (43 questions), but we may be failing some due to:
  - Floating-point precision issues
  - Multi-month/multi-year sum extraction errors
  - Currency/unit handling

**Example improvements:**
- Better month/year parsing for "sum all months in X year"
- Handle inflation adjustments in aggregate calculations
- Robust decimal rounding to required precision

### Category 2: Lookup Questions (35 questions, 51.4% easy)

- **Current estimated pass rate:** ~57%
- **Potential gain:** Improve by 5% with better table navigation
- **Why:** Many should be straightforward fact retrieval, but formatting issues cause failures

**Example improvements:**
- Handle cross-references to other pages
- Extract values from complex tables
- Resolve entity ambiguities (e.g., "highest spending department")

### Category 3: Percent Change Questions (16 questions, 62.5% easy)

- **Current estimated pass rate:** ~60%
- **Potential gain:** Improve by 5% with correct formula application
- **Why:** Simple formula ((new - old) / old * 100) but easily misapplied

**Example improvements:**
- Ensure consistent use of absolute vs. relative percent change
- Handle rounding to required precision (hundredths, whole number, etc.)
- Correct handling of negative percentages

---

## Section 6: Known Hard Categories to De-prioritize

### Statistical Geometric Mean (8 questions, 0% easy)

- **All marked as HARD**
- **Estimated pass rate:** ~40% (since they're all hard)
- **Recommendation:** Skip or low-priority. Requires:
  - Identifying geometric mean requirement
  - Correct formula: (x₁ × x₂ × ... × xₙ)^(1/n)
  - Handling large numbers (numerical stability)

### Growth Rate / CAGR (11 questions, 20-33% easy)

- **Estimated pass rate:** ~45%
- **Why it's hard:**
  - Formula confusion: CAGR = (Ending / Beginning)^(1/years) - 1
  - Multi-period calculations
  - Inflation adjustments sometimes required
  - Precision expectations (3+ decimal places)

### Regression (17 questions, 35.3% easy)

- **Estimated pass rate:** ~50%
- **Why it's hard:** Requires statistical computation or finding pre-computed values

### Advanced Statistical (Box-Cox, Theil, KL divergence, etc.)

- **Estimated pass rate:** ~40%
- **Recommendation:** Skip—requires domain-specific statistical expertise

### Visual/Chart Questions (2 questions, 0% easy)

- **Estimated pass rate:** ~35%
- **Recommendation:** Skip—requires image processing and chart interpretation

---

## Section 7: Summary Table & Recommendations

### Overall Score Projection

| Metric | Value |
|---|---|
| Total Questions | 246 |
| Projected Correct (baseline 55%) | ~135 |
| Projected Correct (w/ improvements) | ~150-160 |
| Target | 175+ |
| Gap | 15-40 questions |

### Prioritized Improvement Areas

**Priority 1: High-value, achievable wins**
1. Aggregation errors (sum/total precision) → +5-8 questions
2. Lookup extraction (table navigation) → +3-5 questions
3. Percent change formula application → +2-4 questions
4. **Subtotal: +10-17 questions**

**Priority 2: Medium-effort improvements**
5. Difference calculation refinement → +2-4 questions
6. Percent formatting (% vs decimal) → +1-2 questions
7. **Subtotal: +3-6 questions**

**Priority 3: Hard, specialized improvements**
8. Regression value extraction → +1-3 questions
9. Statistical deviation calculations → +1-2 questions
10. Growth rate / CAGR formulas → +1-2 questions
11. **Subtotal: +3-7 questions**

**Avoid / Low-priority:**
- Geometric mean (all hard, 8 questions) — skip unless we solve arithmetic at scale
- Visual charts (2 questions) — skip unless adding image processing
- Advanced statistics (Box-Cox, etc.) — skip unless hiring a statistician

---

## Section 8: Detailed Category Breakdown

### Aggregation (78 questions)

**Distribution:** 43 easy (55.1%), 35 hard (44.9%)

**Avg source files:** 1.77

These are primarily "sum" and "total" questions. The high easy rate (55.1%) makes this a prime target for improvement. Common failure modes include:
- Precision mismatches (rounding, decimal places)
- Missing months or years in aggregate calculations
- Inflation adjustments not applied correctly
- Unit conversion errors (millions to billions, etc.)

### Lookup (35 questions)

**Distribution:** 18 easy (51.4%), 17 hard (48.6%)

**Avg source files:** 1.80

Straightforward fact retrieval from tables and structured data. Should be easier than it is. Failures likely due to:
- Entity name ambiguities ("highest department" vs specific names)
- Cross-page references in PDFs
- Table header/column misalignment
- Numerical formatting (with/without commas)

### Difference (29 questions)

**Distribution:** 12 easy (41.4%), 17 hard (58.6%)

**Avg source files:** 1.76

"Absolute difference" calculations. Harder than expected (58.6% hard) despite simple formula. Issues:
- Confusion between absolute and relative differences
- Unit handling (inflation-adjusted vs nominal)
- Precision expectations
- Negative number handling

### Statistical Deviation (19 questions)

**Distribution:** 8 easy (42.1%), 11 hard (57.9%)

**Avg source files:** 1.84

Standard deviation and variance calculations. Require:
- Identifying data series to compute over
- Correct formula application
- Numerical precision for complex formulas

### Regression (17 questions)

**Distribution:** 6 easy (35.3%), 11 hard (64.7%)

**Avg source files:** 2.35

Highest average source files (2.35). May require:
- Finding slope and intercept from pre-computed values
- Performing linear regression on extracted data
- Statistical computation libraries

### Percent Change (16 questions)

**Distribution:** 10 easy (62.5%), 6 hard (37.5%)

**Avg source files:** 1.94

Second-best easy rate (62.5%). Formula: ((new - old) / old) * 100. Issues:
- Percent vs decimal confusion (12.5% vs 0.125)
- Rounding direction and precision
- Handling negative changes

### Change (16 questions)

**Distribution:** 7 easy (43.8%), 9 hard (56.2%)

**Avg source files:** 1.75

Simple subtraction but harder than aggregation (56.2% hard). May involve:
- Multi-period changes
- Categorical grouping before subtraction
- Unit conversions

### Percentage (10 questions)

**Distribution:** 3 easy (30.0%), 7 hard (70.0%)

**Avg source files:** 2.00

Lowest easy rate among standard math types (30%). Requires:
- Percent calculations (e.g., "what percentage is X of Y?")
- Often multi-step reasoning
- Precision formatting

### Statistical Geometric Mean (8 questions)

**Distribution:** 0 easy (0.0%), 8 hard (100.0%)

**Avg source files:** 2.88

Highest average source files (2.88). All marked hard. Formula: (x₁ × x₂ × ... × xₙ)^(1/n). Challenges:
- Identifying which data to use
- Numerical stability with large numbers
- Logarithmic computation may be necessary
- Extracting values from multiple documents

### Growth CAGR (6 questions)

**Distribution:** 2 easy (33.3%), 4 hard (66.7%)

**Avg source files:** 1.67

Compound Annual Growth Rate: ((Ending / Beginning)^(1/years) - 1). Issues:
- Formula complexity
- Time period extraction
- Precision (often 3+ decimal places)

### Ratio (5 questions)

**Distribution:** 3 easy (60.0%), 2 hard (40.0%)

**Avg source files:** 1.00

Smallest category, all single-file. Straightforward division operations. Easy rate is 60%.

### Growth Rate (5 questions)

**Distribution:** 1 easy (20.0%), 4 hard (80.0%)

**Avg source files:** 1.60

Lowest easy rate (20%). May involve:
- Period identification
- Base selection confusion
- Complex growth formulas

### Visual (2 questions)

**Distribution:** 0 easy (0.0%), 2 hard (100.0%)

**Avg source files:** 1.00

Chart/graph interpretation. Requires image processing. Recommended to skip.

---

## Appendix: Full Category Statistics

### All Question Types with Metrics

| Type | Total | Easy | Hard | Avg Files |
|---|---:|---:|---:|---:|
| aggregation | 78 | 43 | 35 | 1.77 |
| lookup | 35 | 18 | 17 | 1.80 |
| difference | 29 | 12 | 17 | 1.76 |
| statistical_deviation | 19 | 8 | 11 | 1.84 |
| regression | 17 | 6 | 11 | 2.35 |
| percent_change | 16 | 10 | 6 | 1.94 |
| change | 16 | 7 | 9 | 1.75 |
| percentage | 10 | 3 | 7 | 2.00 |
| statistical_geometric_mean | 8 | 0 | 8 | 2.88 |
| growth_cagr | 6 | 2 | 4 | 1.67 |
| ratio | 5 | 3 | 2 | 1.00 |
| growth_rate | 5 | 1 | 4 | 1.60 |
| visual | 2 | 0 | 2 | 1.00 |

---

## Key Takeaways for Performance Optimization

### Immediate Actions (Highest ROI)

1. **Fix aggregation sum precision** (~5-8 point gain)
   - Review all sum/total calculations for floating-point precision issues
   - Test rounding functions against expected outputs
   - Handle multi-month aggregations correctly

2. **Improve table lookup extraction** (~3-5 point gain)
   - Better PDF table parsing
   - Handle merged cells and complex layouts
   - Validate entity name matching

3. **Apply percent change formula correctly** (~2-4 point gain)
   - Ensure (new-old)/old*100 is applied correctly
   - Validate percentage formatting

### Medium Priority

4. Difference calculation edge cases (unit handling, inflation)
5. Percentage calculation accuracy
6. Change operation grouping and unit consistency

### Accept Current Limits

- Geometric mean: All hard, requires advanced math or LLM numerical reasoning
- Regression: May require specialized statistical libraries
- Growth rate/CAGR: Complex formulas, low ROI
- Visual: Skip without image processing

---

**Generated:** 2026-03-30T11:32:07.908093

**Data Source:** `/Users/jwalinshah/projects/officeqa-arena/data/officeqa_full.csv`

**Analysis:** Full evaluation set categorization and projected performance scoring for all 246 questions.
