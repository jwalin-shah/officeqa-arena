# Task Stability Analysis Report
**Generated:** 2026-04-04
**Scope:** 246 tasks across 15 runs (6 versions)

---

## Executive Summary

- **High-confidence tasks:** 131/246 (53%) pass 100% or ≥80% of runs
- **Problematic tasks:** 115/246 (47%) show instability or consistent failure
- **Key finding:** Hard questions are the bottleneck (25% always-fail vs 4% for easy)
- **Version progress:** nomcp-v2 improved 177 tasks (72%) vs arena-v0.6, with only 9 regressions (4%)

---

## 1. Task Categories by Pass Rate

### ALWAYS_PASS (100% pass rate across all 15 runs)
- **Count:** 56 tasks (22.8%)
- **Difficulty:** Hard=19 (34%), Easy=37 (66%)
- **UIDs:** UID0002, UID0003, UID0006, UID0007, UID0019, UID0023, UID0025, UID0033, UID0040, UID0042, UID0043, UID0047, UID0048, UID0060, UID0065, UID0072, UID0076, UID0078, UID0086, UID0087, UID0090, UID0106, UID0108, UID0115, UID0116, UID0124, UID0128, UID0130, UID0132, UID0133, UID0139, UID0142, UID0145, UID0146, UID0152, UID0153, UID0156, UID0160, UID0163, UID0164, UID0176, UID0180, UID0185, UID0187, UID0190, UID0192, UID0194, UID0195, UID0197, UID0201, UID0209, UID0218, UID0222, UID0234, UID0235, UID0236

### USUALLY_PASS (≥80% pass rate)
- **Count:** 75 tasks (30.5%)
- **Difficulty:** Hard=36 (48%), Easy=39 (52%)
- **UIDs:** UID0001, UID0009, UID0013, UID0014, UID0015, UID0016, UID0020, UID0022, UID0024, UID0036, UID0038, UID0039, UID0045, UID0049, UID0051, UID0052, UID0053, UID0054, UID0058, UID0061, UID0063, UID0064, UID0067, UID0068, UID0070, UID0080, UID0081, UID0092, UID0093, UID0094, UID0095, UID0099, UID0100, UID0103, UID0104, UID0107, UID0112, UID0119, UID0129, UID0131, UID0137, UID0151, UID0155, UID0157, UID0161, UID0167, UID0168, UID0169, UID0173, UID0178, UID0179, UID0181, UID0184, UID0186, UID0189, UID0191, UID0199, UID0200, UID0202, UID0203, UID0204, UID0205, UID0211, UID0215, UID0216, UID0217, UID0224, UID0226, UID0228, UID0230, UID0233, UID0238, UID0241, UID0242, UID0246

### FLIP_FLOP (30-70% pass rate — unstable)
- **Count:** 38 tasks (15.4%)
- **Difficulty:** Hard=23 (61%), Easy=15 (39%)
- **UIDs:** UID0004, UID0008, UID0010, UID0011, UID0017, UID0021, UID0026, UID0027, UID0035, UID0044, UID0050, UID0059, UID0066, UID0071, UID0079, UID0082, UID0083, UID0089, UID0091, UID0097, UID0121, UID0122, UID0125, UID0127, UID0143, UID0148, UID0149, UID0170, UID0172, UID0177, UID0182, UID0210, UID0214, UID0220, UID0225, UID0227, UID0231, UID0239

### USUALLY_FAIL (>0% but <30% pass rate)
- **Count:** 40 tasks (16.3%)
- **Difficulty:** Hard=22 (55%), Easy=18 (45%)
- **UIDs:** UID0005, UID0012, UID0028, UID0031, UID0034, UID0046, UID0056, UID0069, UID0074, UID0075, UID0085, UID0088, UID0098, UID0101, UID0102, UID0105, UID0109, UID0111, UID0117, UID0123, UID0126, UID0134, UID0138, UID0141, UID0147, UID0159, UID0162, UID0166, UID0171, UID0183, UID0198, UID0206, UID0207, UID0213, UID0221, UID0229, UID0232, UID0237, UID0240, UID0243

### ALWAYS_FAIL (0% pass rate)
- **Count:** 37 tasks (15.0%)
- **Difficulty:** Hard=33 (89%), Easy=4 (11%)
- **UIDs:** UID0018, UID0029, UID0030, UID0032, UID0037, UID0041, UID0055, UID0057, UID0062, UID0073, UID0077, UID0084, UID0096, UID0110, UID0113, UID0114, UID0118, UID0120, UID0135, UID0136, UID0140, UID0144, UID0150, UID0154, UID0158, UID0165, UID0174, UID0175, UID0188, UID0193, UID0196, UID0208, UID0212, UID0219, UID0223, UID0244, UID0245

---

## 2. Difficulty Analysis

### Category Breakdown

| Category | Hard | Easy | Hard % |
|----------|------|------|--------|
| ALWAYS_PASS | 19 | 37 | 33.9% |
| USUALLY_PASS | 36 | 39 | 48.0% |
| FLIP_FLOP | 23 | 15 | 60.5% |
| USUALLY_FAIL | 22 | 18 | 55.0% |
| ALWAYS_FAIL | 33 | 4 | 89.2% |

### Key Observations

**Hard questions (133 total):**
- 19 always-pass (14.3%) — top-tier problems
- 33 always-fail (24.8%) — systematic blockers
- Success rate: ~41% across all runs

**Easy questions (113 total):**
- 37 always-pass (32.7%) — well-solved
- 4 always-fail (3.5%) — outliers, only UID0041
- Success rate: ~89% across all runs

**Difficulty impact:** Hard questions are **7x more likely** to fail consistently (24.8% always-fail vs 3.5% for easy).

---

## 3. Flip-Flop Pattern Analysis

### Distribution by Pass Count (out of 15 runs)

| Pass Count | Rate | Count | H:E | UIDs |
|-----------|------|-------|-----|------|
| 5/15 | 33% | 4 | 3:1 | UID0027, UID0079, UID0083, UID0149 |
| 6/15 | 40% | 6 | 4:2 | UID0004, UID0017, UID0050, UID0089, UID0122, UID0143 |
| 7/15 | 47% | 6 | 5:1 | UID0059, UID0097, UID0148, UID0210, UID0214, UID0227 |
| 8/15 | 53% | 3 | 1:2 | UID0082, UID0225, UID0239 |
| 9/15 | 60% | 7 | 5:2 | UID0010, UID0035, UID0071, UID0127, UID0170, UID0220, UID0231 |
| 10/15 | 67% | 12 | 5:7 | UID0008, UID0011, UID0021, UID0026, UID0044, UID0066, UID0091, UID0121, UID0125, UID0172, UID0177, UID0182 |

### Insights

- **Most unstable (closest to 50%):** All 3 tasks at 8/15 (53%) and most at 9/15 (60%)
- **Hard problems dominate:** 60.5% of flip-flops are hard (vs 54% overall)
- **Suggests:** Inconsistencies arise from complex reasoning, not simple lookup errors

---

## 4. Top 10 Hardest Problems (Always Fail)

| # | UID | Difficulty |
|---|-----|------------|
| 1 | UID0018 | hard |
| 2 | UID0029 | hard |
| 3 | UID0030 | hard |
| 4 | UID0032 | hard |
| 5 | UID0037 | hard |
| 6 | UID0041 | easy |
| 7 | UID0055 | hard |
| 8 | UID0057 | hard |
| 9 | UID0062 | hard |
| 10 | UID0073 | hard |

**All 37 always-fail tasks:**
UID0018, UID0029, UID0030, UID0032, UID0037, UID0041, UID0055, UID0057, UID0062, UID0073, UID0077, UID0084, UID0096, UID0110, UID0113, UID0114, UID0118, UID0120, UID0135, UID0136, UID0140, UID0144, UID0150, UID0154, UID0158, UID0165, UID0174, UID0175, UID0188, UID0193, UID0196, UID0208, UID0212, UID0219, UID0223, UID0244, UID0245

---

## 5. Version Evolution

### Average Pass Rate by Version

| Version | Pass Rate | Runs | Note |
|---------|-----------|------|------|
| arena-v0.6 | 63.0% | 2 | Baseline |
| arena-v0.7 | 62.5% | 3 | Regression |
| arena-v0.8 | 56.5% | 1 | Worst |
| arena-v0.9 | 64.6% | 1 | Recovery |
| arena-v1 | 66.9% | 4 | Best (arena) |
| nomcp-v2 | 65.5% | 4 | Competitive |

### Key Transition: arena-v0.6 → nomcp-v2

| Metric | Count | % of 246 |
|--------|-------|----------|
| Improved | 177 | 72% |
| Regressed | 9 | 4% |
| Stable | 60 | 24% |

**Top improvements:**
- UID0014, UID0125, UID0127, UID0166: 0/2 → 4/4 (100% better)
- UID0016, UID0052, UID0067, UID0068: 1/2 → 4/4 (complete fix)

**Regressions:** UID0004, UID0027, UID0034, UID0074, UID0083, UID0098, UID0117, UID0134, UID0229

---

## 6. Key Patterns

### Pattern 1: Difficulty is Destiny
- **Hard questions are the bottleneck:** 25% always-fail vs 4% for easy
- **89% of always-fail tasks are hard** (33/37)
- Easy questions have 89% success rate; hard has 41%

### Pattern 2: Instability Correlates with Complexity
- **60% of flip-flop tasks are hard** (vs 54% overall)
- Suggests hard problems expose model/tool inconsistencies
- Easy questions tend toward stable (either always-pass or always-fail)

### Pattern 3: nomcp-v2 Shows Net Improvement Despite Approach Change
- **72% improvement rate** vs only 4% regression
- Suggests architectural change was beneficial overall
- But regressions indicate some specific cases lost fidelity

### Pattern 4: Low Overall Consistency
- **Only 55.3% of tasks are high-confidence** (100% or ≥80% pass)
- **45% of questions are unreliable** (≤70% pass rate)
  - 37 completely broken (0% any run)
  - 40 mostly broken (<30%)
  - 38 unpredictable (30-70%)
- Suggests systematic issues with specific question types or data

---

## Recommendations

1. **Focus on hard questions:** They are 7x more likely to fail. Investigate the 37 always-fail hard tasks first.

2. **Stabilize flip-flops:** The 38 unstable tasks suggest inconsistencies in:
   - Table selection logic (which table to query)
   - Data extraction (correct row/column identification)
   - Grounding confidence (when to trust vs fallback)

3. **Understand UID0041 outlier:** Only easy question that always fails — worth investigating what makes it unique.

4. **Version trend:** arena-v1 (66.9%) still beats nomcp-v2 (65.5%). Consider hybrid approach or understanding what arena-v1 does better.

5. **Data quality check:** Review the 37 always-fail tasks for OCR errors, ambiguous phrasing, or incorrect gold annotations.
