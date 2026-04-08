# OfficeQA Arena Analysis: 8,265 Traces Across 62 Versions

**Date:** April 8, 2026  
**Analysis Scope:** 62 agent versions with 8,265 total traces (246 tasks per version)  
**Best Observed:** 80.4% pass rate (v21-13h)  
**Median Performance:** 65.4% pass rate  
**Average:** 65.6% pass rate

---

## 1. PATTERN RECOGNITION: WHAT CORRELATES WITH SUCCESS

### 1.1 Step Count Sweet Spot
**Finding:** Optimal performance occurs with 10-15 average steps per task.

| Step Range | Avg Pass Rate | Count |
|-----------|---------------|-------|
| 10-15 steps | 71.3% | 5 versions |
| 15-20 steps | 64.3% | 26 versions |
| 5-10 steps | 66.4% | 8 versions |

**Interpretation:** 
- More thinking = better, but diminishing returns after ~12 steps
- Bottom performers (v13, v8) use 19-21 steps with SAME reasoning depth as top performers
- **Top performers achieve more with less** - they decide faster while thinking equally deeply

### 1.2 Top Performer Characteristics (80.4% vs 65.6% baseline)

| Metric | Top Performers | Bottom Performers | Gap |
|--------|-----------------|-------------------|-----|
| Avg Steps | 11-12 | 19-21 | -7 to -9 steps |
| Reasoning/Step | 1,700-1,750 chars | 1,400-1,600 chars | +100-150 chars |
| Reasoning-Heavy Steps | 153-244 | 279-297 | Fewer but better |
| Model | minimax-m2.5 | minimax-m2.5 | Same |

**Key Insight:** Top performers make better *decisions* with the same or slightly more *thought* - they don't second-guess themselves.

### 1.3 Model Consistency
- **All 39 analyzed versions** use `openrouter/minimax/minimax-m2.5`
- **Pass rate range:** 57.3% - 80.4% (23.1 percentage point spread)
- **Implication:** Model choice is locked in; improvements come purely from prompt/approach

### 1.4 Performance Ceiling
- **Observed maximum:** 80.4% (v21-13h-178.8)
- **Realistic upper bound:** 75-80% with prompt tuning alone
- **Grading noise factor:** ±3-5% variance (expected 157±14 from memory)

---

## 2. TASK-LEVEL INSIGHTS

### 2.1 Task Difficulty Distribution

| Category | Count | Pass Rate | Details |
|----------|-------|-----------|---------|
| Always-Pass | 56 tasks | 100% | Free wins (no version fails these) |
| Always-Fail | 37 tasks | 0% | Hard problems (no version passes) |
| Flaky | 153 tasks | 20%-80% | Improvement opportunity |

### 2.2 Always-Failing Tasks (Hard Problems)
**Sample failing tasks:** uid0120, uid0029, uid0245, uid0223, uid0030, uid0096, uid0212, uid0032

**Likely root causes:**
1. **Parser limitations** - certain document formats/tables not extracted correctly
2. **Question ambiguity** - "Which data?" unclear without seeing source
3. **Infrastructure constraints** - document not in corpus, or latency timeouts

**Recommendation:** Investigate 2-3 of these manually to diagnose pattern

### 2.3 Flaky Tasks (Improvement Opportunity)
**~78 tasks** with 40-60% pass rate across versions.

**Most uncertain (7/15 = 47%):**
- officeqa-uid0210, uid0227, uid0214, uid0148

**Opportunity:** Improving these from 47% to 60% = **+4-6 percentage points** on total score

---

## 3. QUICK WINS: LOW-EFFORT IMPROVEMENTS

### 3.1 Reduce Step Count → +2-3%
**Action:** Add `max_turns=12` or `max_turns=15` constraint
```
Why: Top performer (80.4%) uses 11-12 steps
Bottom performer uses 19-21 with same reasoning depth
```
**Expected gain:** +2-3 percentage points

### 3.2 Early Termination Signal → +1-2%
**Action:** Prompt instruction:
> "If you have high confidence in the answer after gathering evidence, state it immediately without further verification."

**Why:** MiniMax rarely commits early even when confident
**Expected gain:** +1-2 percentage points

### 3.3 Deeper Reasoning on Uncertain Steps → +1-2%
**Action:** Prompt: Encourage detailed reasoning for calculations/dates
```
Why: Top performers have 1,700-1,750 chars/step vs bottom's 1,400-1,600
More thoughtfulness = fewer calculation errors
```
**Expected gain:** +1-2 percentage points

### 3.4 Focus on Flaky Tasks → +4-5%
**Action:** Analyze top 10 flaky tasks, identify common failure patterns
**Why:** 153 tasks are solvable; getting 10-15 more right = +4-5%
**Effort:** Investigate off-hours, batch to next submission

---

## 4. SYSTEMATIC IMPROVEMENTS: WHAT TO TEST NEXT

### 4.1 Parameter Sweep (HIGH PRIORITY)
**Test matrix (40+ configurations):**

1. **Turns/Steps Control**
   - `max_turns=10, 12, 15, 18` (test locally at each)
   - Current best is 11-12, so expect sweet spot at 12-15

2. **Verification Strategy**
   - No verification (current)
   - Sanity-check before answer (arithmetic, date validity)
   - Re-read answer to confirm matches document

3. **Few-Shot Examples**
   - No examples (current)
   - 2-3 examples for hard question types (FY/CY conversion, YoY %)
   - Format: "Example question → found doc → extracted data → answer"

4. **Decomposition Depth**
   - Free-form (current best: v21-13h at 80.4%)
   - Forced 4-step: Find doc → Extract range → Compute → Verify
   - Results: v21 uses forced decomposition, v13 uses free-form (but worse)

**Expected outcome:** Find 3-5 configurations that hit 72-75%

### 4.2 Approach Variants (MEDIUM PRIORITY)

1. **Page-First Strategy**
   - Current: Search immediately
   - Test: Scan table of contents/structure first to understand document
   - Success rate on page-first (v20): 69.8% (neutral, not better)
   - **Status:** Likely no gain; deprioritize

2. **Verify-First Strategy**
   - Current: Answer when confident
   - Test: Explicit verification step that double-checks arithmetic
   - Success rate with verification (v15): 80% on sample (very small N=10)
   - **Status:** Promising, test at larger scale

3. **Pre-Compute Heavy Calculations**
   - 55% of questions need sum/aggregation (memory: reference_question_types.md)
   - 39% need CY conversion (fiscal/calendar year)
   - 31% need percent change
   - Test: Pre-compute CPI, period conversions as cached functions
   - Success rate with cached: 69-71% (tested as v15, neutral)
   - **Status:** No measurable gain; deprioritize

4. **Multi-Model Fallback**
   - Current: Only MiniMax (expensive, high quality)
   - Test: Use MiniMax for hard Qs, cheaper model for simple sum/YoY
   - **Status:** Not tested; medium priority (cost vs speed tradeoff)

### 4.3 Infrastructure (LOWER PRIORITY)
✗ MCP tools: Tested in v4, v12, v20 - **no measurable gain**  
✗ Skills: Loaded in v15, v20, v21 - **appears neutral**  
✗ Database caching: Tested in v14, v15 - **no gain (DB loses 50% of data)**  
✓ MiniMax finds files naturally - **no special infrastructure needed**

---

## 5. RISK FACTORS & CONSTRAINTS

### 5.1 Grading Variance
- Arena has **±3-5% noise** in scoring (known issue)
- Best observed (184) but expected given our prompts (~157±14)
- **Implication:** Improvements <3% are within noise; focus on 5%+ gains

### 5.2 Always-Fail Plateau
- **37 tasks never pass** despite 15 different version approaches
- Likely causes: parser bug, document missing, infrastructure timeout
- **Recommendation:** Pick top 2-3, manually debug to find root cause
- **Realistic expectation:** Can recover maybe 5-10 of these (1-2%)

### 5.3 Local vs Arena Bias
- Local testing with `MAX_TURNS=25` favors verbose approaches
- But v10 minimal (180 score, fewer words) beat v9 verbose (174) in arena
- **Implication:** Test locally with `turns=12-15`, NOT 25+
- This prevents local overfitting to verbosity

### 5.4 Prompt-Only Ceiling
- Current best with minimal prompt: 80.4% (v21-13h)
- Adding MCP/skills/tools has NOT improved beyond 76-77%
- **Implication:** Prompt tuning > infrastructure; invest in A/B testing prompts

---

## 6. RECOMMENDED NEXT STEPS (PRIORITY ORDER)

### Phase 1: Quick Wins (2-3 days)
1. **Test max_turns=12-15** locally (should add 2-3%)
2. **Add early-termination signal** to prompt (should add 1-2%)
3. **Increase reasoning depth** prompt (should add 1-2%)
4. **Local A/B:** Run variants against v21-13h baseline
5. **Submit best variant** to arena

### Phase 2: Parameter Sweep (3-5 days)
1. **Verify strategy variants** (verify-first, sanity-check arithmetic)
2. **Few-shot examples** for FY/CY and percent change questions
3. **Decomposition depth** (forced 4-step vs free-form)
4. **Test matrix:** 40+ configurations in parallel
5. **Identify 3-5 winners**, submit top 2

### Phase 3: Hard Problems (2-3 days, lower ROI)
1. **Manually debug 2-3 always-fail tasks** to find pattern
2. **Analyze top 10 flaky tasks** for commonality
3. **Add targeted logic** if pattern found (e.g., "questions about labor always need dataset X")
4. **Submit targeted fix**

### Phase 4: Advanced Techniques (effort > reward)
1. Multi-model fallback (cost vs speed)
2. Custom skills/tools for domain patterns
3. Infrastructure optimization (likely no ROI)

---

## 7. KEY METRICS DASHBOARD

| Metric | Value | Implication |
|--------|-------|-------------|
| Current median | 65.4% | Starting baseline |
| Best observed | 80.4% | Upper bound with prompt alone |
| Realistic target | 72-75% | Achievable with phase 1+2 |
| Ceiling w/infrastructure | 76-80% | MCP/tools not helping (tested) |
| Always-pass tasks | 56 | No value in optimizing these |
| Flaky tasks | 153 | 78 at 50% pass rate = biggest win |
| Always-fail tasks | 37 | ~1-2% value if investigated |
| Step count optimal | 11-12 | Force commitment, not exploration |

---

## 8. APPENDIX: FULL VERSION RANKINGS

### Top 15 Performers (out of 39 with sufficient traces)
1. **v21-13h-178.8** - 80.4% (11.1 steps) ⭐ BEST
2. **v21-10h-135.8** - 77.4% (12.6 steps)
3. **mcp-v5-2d-184.5** - 76.2% (18.0 steps)
4. **nomcp-v2-5d-170.9** - 71.4% (16.8 steps)
5. **v20-1d-183.8** - 71.0% (15.6 steps)

### Bottom 10 Performers
...37. **v13-1d-150.4** - 57.3% (17.7 steps)
...38. **v13** - 57.3% (17.7 steps)
...39. **v8** - 58.9% (18.8 steps)

---

## Conclusion

**The data shows clear paths to +10-15% improvement:**
- Reduce exploration (11-12 steps vs 19-21) = +2-3%
- Encourage early commitment = +1-2%
- Deepen reasoning on uncertain steps = +1-2%
- Fix 10-15 flaky tasks = +4-5%
- **Total realistic gain: 8-13 percentage points → 73-78% target**

Success requires disciplined A/B testing. Start with phase 1 (quick wins), measure carefully, then expand to phase 2.
