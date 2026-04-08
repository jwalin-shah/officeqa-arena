# OfficeQA Execution Strategy & Model Analysis Report

**Analysis Date**: April 8, 2026
**Scope**: 15 versions, 3,654 total task traces, 246 unique tasks
**Focus**: Model choices, execution strategies, what works vs. what doesn't

---

## Executive Summary

### Key Findings

1. **All versions use the same model** (MiniMax M2.5), so performance differences are entirely strategy-based
2. **~70% is the realistic ceiling** for this task set (41 always-fail, 56 flaky tasks)
3. **v20_best (69.8% on 245 tasks) is the best large-scale baseline** — most efficient, fewest tools
4. **Verify step is the highest-leverage improvement** — can add +2-3% for ~1 turn cost
5. **"Aggressive grepping" beats "thorough exploration"** — fewer steps = better accuracy

### Recommended Next Step

**Implement v20_best + Verify Skill** (expected 72-74% vs v20's 69.8%)
- Minimal risk (proven components)
- High leverage (verify flips 50% of wrong answers)
- Low effort (1 prompt line addition)

---

## 1. Version Rankings

### Top 10 by Pass Rate

| Rank | Version | Pass Rate | Tasks | Avg Steps | Key Strategy |
|------|---------|-----------|-------|-----------|--------------|
| 1 | v7_original_174 | 100.0% | 5 | 21.2 | Thorough python-heavy (sample too small) |
| 2 | v0.2.0 | 72.2% | 36 | 18.2 | Hybrid balanced with write() caching |
| 3 | **v20_best** | 69.8% | 245 | 14.7 | **Grep-first minimal (BEST BASELINE)** |
| 4 | v12_old_181 | 67.9% | 243 | 17.7 | Write-heavy iterative with find() |
| 5 | v10_old_180 | 67.8% | 242 | 17.4 | Similar to v12_old_181 |
| 6 | v13 | 67.5% | 243 | 18.7 | Similar to v12 |
| 7 | v9_old_174 | 65.8% | 243 | 18.3 | Simplified from v8 |
| 8 | v12_171 | 64.9% | 245 | 18.5 | Variant of v12 |
| 9 | v02a_170 | 64.0% | 242 | 17.7 | Variant of v0.2.0 |
| 10 | v7_166 | 62.6% | 246 | 18.9 | Regression from v7_original |

### Critical Observation

**Sample size matters for reliability:**
- v7_original_174 (n=5): 100% → unreliable, likely overfit
- v0.2.0 (n=36): 72.2% → moderately reliable, sample bias possible
- v20_best (n=245): 69.8% → most reliable, statistically significant
- v12_old_181 (n=243): 67.9% → comparable reliability to v20_best

**Therefore**: v20_best is the most trustworthy baseline for implementation.

---

## 2. Model Analysis

### Model Distribution

```
All 15 versions: openrouter/minimax/minimax-m2.5 (100%)
```

### Key Implications

1. **No model variation tested** — all versions use identical MiniMax M2.5
2. **Performance range (57.6% to 100%) is entirely strategy-driven**, not model-driven
3. **No benefit from switching models** — tested in memory/repo shows A/B tests with different prompts, not different models
4. **Model is capable enough** — the 70% ceiling is task difficulty, not model limitation

### Why Only MiniMax?

- **Cost**: MiniMax very cheap via OpenRouter
- **Reliability**: Consistent behavior across runs
- **Memory capacity**: Sufficient for 245-task evaluation
- **Arena support**: Available in production arena environment

### Model-Agnostic Insight

The execution strategy is what matters, not the specific model. A well-designed prompt + tool strategy can extract 70% pass rate from MiniMax, while a poor strategy only gets 58%.

---

## 3. Execution Strategy Comparison

### Tool Usage Patterns

#### v20_best (Grep-First Minimal) — RECOMMENDED

```
Approach:      grep -i "keyword" → cat specific file → sed/grep extract → python3
Tools:         shell (1241 calls), todo_write (100), write (7)
Avg Steps:     14.7
Pass Rate:     69.8%
Strengths:
  - Fewest tools (3 types) = fewest decision points
  - Aggressive grepping finds tables directly
  - Minimal wasted exploration
  - Direct shell access avoids tool-loop issues
Weakness:
  - No verify step = leaves 5-8 points on table
```

#### v12_old_181 / v10_old_180 (Write-Heavy Iterative) — FALLBACK

```
Approach:      todo_write → ls/find explore → grep/cat → write temp files → python3 iterate
Tools:         shell (1374), todo_write (182), write (98), find (97)
Avg Steps:     17.4-17.7
Pass Rate:     67.9%
Strengths:
  - find() catches edge-case documents
  - write() intermediate files reduce re-scanning
  - More iterations = more corrections
Weakness:
  - +3 steps vs v20_best, lower pass rate
  - More tools = more confusion for MiniMax
```

#### v0.2.0 (Hybrid Balanced)

```
Approach:      Explore + careful data formatting + write to files
Tools:         shell (469), write (84), todo_write (56)
Avg Steps:     18.2
Pass Rate:     72.2% (but n=36)
Strengths:
  - High write() usage suggests careful formatting
  - Hybrid of grep and exploration
Weakness:
  - Sample size (36) suggests possible overfit
  - Doesn't scale to 245 tasks (likely drops to ~70%)
```

### Key Pattern: Step Efficiency

```
v20_best:    14.7 steps → 69.8% ✓ Most efficient
v12_old:     17.7 steps → 67.9% (1.9% worse per 3 extra steps)
v7_original: 21.2 steps → 100% (n=5, unreliable)

FINDING: Fewer steps = Higher pass rate at scale
REASON:  Less exploration = fewer decision points = fewer mistakes
```

---

## 4. What Works (Proven Winners)

### High-Value Components (All Top Versions Use These)

1. **FY/CY Explicit Guidance**
   - Impact: 52% of failures were time-period confusion (R10 report)
   - Implementation: "FY pre-1977: Jul-Jun, FY post-1976: Oct-Sep, CY: Jan-Dec"
   - Proven in: v10+, v12+, v20_best
   - Status: ✓ ESSENTIAL

2. **Grep-First Strategy**
   - Usage: v20_best (302 greps), v12 (355 greps)
   - Approach: grep -i "keyword" file.txt to locate table, then extract
   - Benefit: Fast table location, avoids exploration waste
   - Status: ✓ PROVEN

3. **Early Answer Writing**
   - Instruction: "Write your best guess immediately after finding data"
   - Benefit: Prevents "no answer" penalty, allows iteration
   - Used in: All top versions
   - Status: ✓ ESSENTIAL

4. **Todo-Write Planning**
   - Usage: All top versions (100+ todo_write calls)
   - Approach: "- [ ] Read question twice", "- [ ] Find data", "- [ ] Compute", etc.
   - Benefit: Forces decomposition, improves structure
   - Status: ✓ HIGH VALUE

5. **Python3 Inline Computation**
   - Usage: All versions heavily (450-565 python calls)
   - Approach: python3 -c "import statistics; statistics.stdev([...])"
   - Benefit: Direct computation, no tool wrapper needed
   - Status: ✓ ESSENTIAL

6. **Short Prompts (19-21 lines)**
   - v20_best: 19 lines, 14.7 steps
   - v12: 21 lines, 17.7 steps
   - Longer prompts waste turns
   - Status: ✓ IMPORTANT

7. **Verify Step**
   - Implementation: load("verify") after writing answer
   - Documentation: Checks units, FY/CY boundaries, column selection
   - Impact: Documented to flip 50% of wrong-answer tasks
   - Status: ✓ HIGHEST LEVERAGE (not used in v20_best!)

---

## 5. What Doesn't Work (Proven Failures)

### Confirmed Harmful Approaches

1. **MCP Tools** ❌
   - Status: Available in r8+ tarballs
   - Usage: ZERO MCP calls across all 245 v20_best traces
   - Cause: Tool-loop failures, silent failures in arena
   - Example: v8 attempted inline CPI via MCP → 58.9% (regression)
   - Lesson: Don't use MCP; use raw shell instead

2. **Pre-Built SQL Database** ❌
   - Status: /installed-agent/db.sqlite in r8+ tarballs (68MB)
   - Usage: Never queried in v20_best
   - Reason: Raw grep beats structured query; DB loses format variation
   - Lesson: Raw TXT files + grep > SQL database

3. **Skills with Formulas** ❌
   - Status: v7 had 5 SKILL.md files, dropped by v8
   - Result: v13_150 with skills = 57.6% (regression from 67.5%)
   - Reason: Skills work locally, fail silently in arena
   - Lesson: Don't use skills; keep everything in prompt + shell

4. **Negative Instructions** ❌
   - Tested: "NEVER curl external API" to prevent API calls
   - Result: v8 had MORE curl attempts (248) vs v7 (204)
   - Reason: MiniMax does opposite of negative framing
   - Lesson: Use positive framing only

5. **Few-Shot Examples** ❌
   - A/B test: Examples in prompt
   - Result: 55% vs 70% baseline
   - Reason: Examples anchor MiniMax on patterns, reduce generalization
   - Lesson: Don't include examples

6. **Verbose Briefings** ❌
   - Finding: Verbose context before question causes answer override
   - Test: v8 verbose < v9 minimal
   - Reason: MiniMax gets confused by volume
   - Lesson: Use answer-first, compact format

7. **Complex Tool Loops** ❌
   - Issue: MiniMax can't maintain state across multiple tool calls
   - Tested: Tool → file → tool → file chains
   - Result: Fails silently or produces wrong results
   - Lesson: Use single-purpose calls or direct shell

---

## 6. Failure Mode Analysis

### Always-Fail Tasks (41 UIDs fail in ALL tested versions)

UIDs: 0018, 0028, 0029, 0030, 0032, 0034, 0041, 0055, 0057, 0062, 0069, 0077, 0083, 0096, 0098, 0110, 0113, 0114, 0117, 0118, ... (21 more)

**Estimated causes:**
- Regression/OLS fitting (numpy missing): ~16 tasks
- Percentile/median calculations: ~5 tasks
- Currency exchange (external API): ~9 tasks
- CPI adjustments (tool never used): ~8 tasks
- Ambiguous interpretation: ~3 tasks

**Impact**: These 41 tasks are inherently unsolvable with current approach. Expected realistic max is (246 - 41) / 246 = 83% before flaky tasks.

### Flaky Tasks (56 fail in 4/5 tested versions)

Includes the 41 always-fail + 15 additional:
- UID0037, UID0050, UID0071, UID0073, UID0074, UID0102, UID0120, UID0121, UID0123, UID0134, UID0135, UID0136, UID0138, UID0140, ...

**Characteristics:**
- Wide tables (40+ columns): Column selection varies by exploration strategy
- Multi-step arithmetic: Rounding error accumulation
- Grep false positives: Same keyword in multiple tables

**Opportunity**: Verify step can fix some of these (~5-10 tasks).

### v20_best Failure Breakdown (74 failures)

| Mode | Count | % | Description |
|------|-------|---|-------------|
| **Wrong number** (found data, wrong row/col) | 51 | 69% | Found right table, extracted wrong value |
| **Computation error** | 20 | 27% | Python formula mistake or missing import |
| **No answer written** | 2 | 3% | Never committed to answer.txt |
| **Timeout** | 1 | 1% | Execution timeout |

**Key insight**: 69% of failures are "found data, wrong extraction" — exactly what verify step targets.

---

## 7. Recommended Strategies for Next Implementation

### Option A: v20_best + Verify Skill (RECOMMENDED)

**Configuration:**
```
Base:       v20_best prompt (19 lines)
Add:        load("verify") after writing answer
Tools:      shell, todo_write, write
Expected:   72-74% pass rate
Risk:       Low
Effort:     Minimal (1 line)
```

**Why this works:**
- v20_best proven most efficient (14.7 steps, 69.8%)
- Verify step documented to flip 50% of wrong answers
- v20_best has 51 wrong-number failures → verify can fix ~25
- Expected: 171 + (5-10) = 176-181 → 72-74%

**Fallback:** If verify doesn't help by expected amount, proceed to Option B.

---

### Option B: v12_old_181 Strategy (FALLBACK)

**Configuration:**
```
Base:       v12_old_181 approach (find + write caching)
Add:        Verify skill
Expected:   70-71% pass rate
Risk:       Medium
Effort:     Moderate
```

**Why consider:**
- Proven reliable on large dataset (67.9% on 243 tasks)
- write() caching may help edge cases
- find() catches subdirectory documents

**When to use:** If Option A verify step doesn't achieve +2% gain.

---

### Option C: "Best of Both" Hybrid (AGGRESSIVE)

**Configuration:**
```
Base:       v20_best prompt (19 lines) + grep-first strategy
Add:        write() caching from v12 (selective use)
Add:        Verify skill
Add:        find() for edge cases (optional)
Expected:   71-73% pass rate
Risk:       Medium (trade-offs unclear)
Effort:     High
```

**Why consider:**
- Combine efficiency of v20_best with robustness of v12
- Selective write() caching without overhead

**When to use:** Only if Options A & B both underperform.

---

### Option D: Fresh Design (NOT RECOMMENDED)

- Risk: Very High (unknown unknowns)
- Effort: Very High
- Expected: 65-70% (likely worse than proven baselines)
- Lesson: Don't reinvent; optimize existing proven strategies

---

## 8. Key Insights for Decision-Making

### Insight 1: Step Efficiency Inversely Correlates with Pass Rate

```
v20_best:     14.7 steps → 69.8% ✓
v12_old_181:  17.7 steps → 67.9%
v7_original:  21.2 steps → 100% (n=5, unreliable)

FINDING:      Fewer steps = higher pass rate
IMPLICATION:  Aggressive grepping > thorough exploration
```

### Insight 2: Verify Step is Highest-Leverage Single Improvement

```
Current problem:  69% of v20_best failures are "wrong number"
Verify solution:  Catches wrong row/column, checks units, validates FY/CY
Expected impact:  +2-3% pass rate for ~1 turn cost
```

### Insight 3: Tool Count has Sweet Spot

```
v20_best:  3 tools → 69.8%
v12/v10:   4+ tools → 67.8%
v7:        3 tools → 100% (n=5)

FINDING:   3-4 tools is ideal; 5+ causes confusion
```

### Insight 4: FY/CY Guidance is Essential

```
R10 analysis:     52% of failures were time-period confusion
v10+ versions:    Include explicit FY/CY rules
v20_best impact:  Eliminates entire failure category
```

### Insight 5: ~70% is Realistic Ceiling

```
Always-fail:     41 tasks (impossible with current approach)
Flaky:           56 tasks (strategy-dependent)
Consistent pass: 149 tasks (always pass)

Calculation:     (246 - 41) / 246 = 83% theoretical max
                 With flaky tasks: 70-75% practical ceiling
```

### Insight 6: Model Doesn't Matter, Strategy Does

```
All versions use same model (MiniMax M2.5)
Range:            57.6% to 100% (entirely strategy-driven)
Conclusion:       No benefit to testing different models
```

---

## 9. What Changed Between Top Versions

### v0.2.0 → v20_best

| Aspect | v0.2.0 | v20_best | Change |
|--------|--------|----------|--------|
| Pass Rate | 72.2% | 69.8% | -2.4% (but 9x larger sample) |
| Tasks | 36 | 245 | 7x more tasks |
| Avg Steps | 18.2 | 14.7 | -3.5 steps (faster) |
| Grep Calls | 83 | 302 | +3.6x (more aggressive) |
| Write Calls | 84 | 7 | -91% (less caching) |
| Tools | 4 | 3 | Simplified |

**Interpretation:** v20_best is faster, more aggressive on grepping, simpler. The apparent regression in pass rate (72.2% → 69.8%) is due to sample size differences (36 vs 245). At scale, likely similar or v20_best wins.

### v12_old_181 → v20_best

| Aspect | v12 | v20 | Change |
|--------|-----|-----|--------|
| Pass Rate | 67.9% | 69.8% | **+1.9%** |
| Tasks | 243 | 245 | Similar |
| Avg Steps | 17.7 | 14.7 | -3 steps |
| Find Calls | 97 | 0 | Removed |
| Write Calls | 98 | 7 | -91% |
| Grep Calls | 355 | 302 | Moderate |

**Interpretation:** Removing find() and reducing write() caching didn't hurt; made it faster. Aggressive grepping (v20) beats thorough exploration (v12).

### v20_best → Opportunity: v20_best + Verify

**Expected change:**
- Add: load("verify") after writing answer
- Cost: ~1 additional turn
- Benefit: Flip 50% of 51 wrong-number failures = ~25 extra passes
- Net: 171 + (5-10 conservative) = 176-181 passes
- Pass Rate: 72-74% (from 69.8%)

---

## 10. Recommended Analysis Priority for Next Phase

### TIER 1: Implement v20_best + Verify (PRIMARY)

1. Copy v20_best prompt exactly
2. Add one line: `load("verify")`
3. Test on 40-task subset
4. Expected: 72-74% on full task set
5. Effort: 1-2 hours

### TIER 2: Study v12_old_181 (SECONDARY REFERENCE)

1. Understand write() caching patterns
2. Check if find() catches edge cases v20 misses
3. Compare step-efficiency trade-offs
4. Only if Tier 1 doesn't achieve expected gains

### TIER 3: Edge Case Analysis (OPTIONAL)

1. Examine v7_original_174 (why 100% on n=5?)
2. Look for overlooked verification patterns
3. Could reveal optimization v20_best missed

### DO NOT RE-ANALYZE

- v8_155 (58.9%) — inline CPI failed, move on
- v13_150 (57.6%) — skills approach broken in arena
- v9_158 (60.2%) — bare prompt underperformed

---

## 11. Implementation Checklist

### For v20_best + Verify Strategy

- [ ] Copy r11/submit/prompt.j2 (base v20_best structure)
- [ ] Verify FY/CY guidance is present (essential, not optional)
- [ ] Verify grep tips are clear (grep-first strategy)
- [ ] Add: load("verify") in prompt after answer.txt
- [ ] Ensure verify/SKILL.md exists in skills/ directory
- [ ] Test locally with oracle (run_local_vN.sh pattern)
- [ ] Verify unit tests pass (calcs, cpi if included)
- [ ] Submit to arena
- [ ] Collect traces and compare to v20_best baseline

### Success Criteria

- Achieve 72-74% on 246-task set (vs v20_best's 69.8%)
- Verify step called in at least 50% of traces
- Wrong-number failures should decrease (~51 → 26-35)

---

## 12. Final Recommendation

**START WITH: v20_best + Verify Skill**

**Why:**
1. Proven baseline (69.8% on 245 tasks)
2. Highest leverage improvement (verify flips 50% of errors)
3. Minimal risk (adding 1 line to prompt)
4. Low effort (1-2 hours implementation)
5. Expected outcome: 72-74% (+2-3% improvement)

**Fallback Plan:**
1. If verify doesn't reach +2% gain → try Option B (v12_old_181)
2. If neither works → examine flaky task patterns in more detail
3. Always maintain v20_best as baseline for comparison

**Do NOT:**
- Switch models (no benefit shown)
- Add MCP tools (never used in traces)
- Include pre-built DB (raw grep wins)
- Use skills for formulas (broken in arena)
- Write verbose prompts (causes confusion)

---

## Appendix: Detailed Metrics by Version

See attached files:
- `DETAILED_COMPARISON_TABLE.txt` — Full metrics table
- `EXECUTION_STRATEGY_SUMMARY.txt` — Executive overview
- Final Analysis markdown above

---

**Report Generated**: 2026-04-08
**Analysis Window**: v0.2.0 through v20_best
**Data Points**: 3,654 traces across 15 versions
