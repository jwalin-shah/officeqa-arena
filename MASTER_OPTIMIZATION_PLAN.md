# MASTER OPTIMIZATION PLAN: OfficeQA Arena
## Final Strategy to Reach 190-200 Points

**Status:** Current 180-184 points (69.5%)
**Target:** 190-200 points (77-81%)
**Timeline:** 4-6 hours implementation + 24-48h arena validation
**Confidence:** HIGH (based on 245+ traces + 12+ prior submissions)

---

## EXECUTIVE SYNTHESIS

### The Bottleneck (from agent analysis)
68% of failures are **"found the right data, wrong number"** — extraction and formula errors, not reasoning failures. This is fixable.

### The Ceiling (proven exhaustively)
- MiniMax locally plateaus at **70% ± 2%** regardless of prompt instructions (14-variant A/B test)
- Arena theoretical max is **~208 points (85%)** accounting for grading noise
- **Realistic achievable target: 190-200 (77-81%)** requires recovering 10-20 of 26 solvable hard tasks

### The Solution (three tiers)
1. **Tier 1 (P0):** Fix extraction errors via mandatory verification → **+5-8 points**
2. **Tier 2 (P1):** Fix formula errors via pre-built functions → **+4-6 points**
3. **Tier 3 (P2):** Fix unit/prompt issues → **+2-4 points**
- **Total expected: +10-16 points** (180→190-196 range)

---

## PRIORITY RANKING (What to Implement First)

### P0: MANDATORY (1.5 hours, +5-8 points) ⭐⭐⭐ HIGHEST ROI

**Problem:** Model finds table, reads wrong number. Happens fast (20 cases) and slow (31 cases).
**Solution:** Make verify step **mandatory and early** in the prompt, with explicit checklist.
**Why:** v15 proved this catches **50% of wrong-answer cases** (UID0082, UID0006, UID0051, UID0090, UID0194 all flipped when re-verified).

**Implementation:**
1. Change prompt line 23-24 from suggestive ("double-check your work") to imperative ("verify before writing answer.txt")
2. Add explicit checklist: check row headers, column headers, units
3. Improve verify skill wording (clearer structure)
4. Add minimal q.py (50 lines) as fallback lookup tool

**Test Plan:**
- Local test on 5 known failures: UID0050, UID0012, UID0018, UID0028, UID0041
- Measure: How many flip from FAIL→PASS or stay PASS?
- Expected: 2-3 of 5 flip due to verify

**Validation:**
- Cost: Zero (no API calls, just LLM re-reads existing answer)
- Risk: Very low (verify is already used, just more strongly)
- Proven: v15 traces show this works

---

### P1: HIGH IMPACT (2 hours, +4-6 points) ⭐⭐⭐ HIGH ROI

**Problem:** Model writes wrong formulas or uses functions incorrectly.
**Solution:** Provide pre-built calcs.py with 8 core functions (sum, mean, pct_change, cagr, stdev, median, etc.).
**Why:** v21 analysis showed pre-built functions **eliminate formula errors** — model can't misuse a function it didn't write.

**Implementation:**
1. Add calcs.py (60 lines) with: sum_values, mean, pct_change, cagr, stdev, median, percent_of_total
2. Update prompt to reference: "load("calcs") for pre-built functions"
3. Test on compute-heavy tasks: UID0012 (stdev), UID0017 (CAGR), UID0005 (unit conversion)

**Evidence:**
- Multiple failures are formula errors: (new-old)/new instead of (new-old)/old
- v15 with tools had issues; v21 pre-built functions were designed to fix this
- Expected wins: UID0090 (pct_change), UID0012 (stdev), UID0017 (CAGR)

**Validation:**
- Cost: Zero (local Python, no API)
- Risk: Low (functions are simple, well-tested)
- Local signal: Will see immediate wins on math-heavy tasks

---

### P2: MEDIUM IMPACT (1.5 hours, +2-4 points) ⭐⭐⭐ STABILIZATION

**Problem:** Verbose prompts cause MiniMax to override correct answers and explore on its own.
**Solution:** Tighten prompt from 26 → 22 lines, remove noise, keep FY/CY distinction.
**Why:** A/B testing proved **minimal prompts outperform verbose ones** (v5=184.5 > v8=172.7).

**Implementation:**
1. Remove "grep tips" section (4 lines)
2. Remove "Common formulas" section with numpy hints (5 lines)
3. Keep FY/CY distinction (critical for 22% of questions)
4. Add units parsing section (3 lines)
5. Reorder: question at end (v9 finding)

**Evidence:**
- v5 (minimal, 33 lines): 184.5 points
- v8 (verbose, 30+ lines): 172.7 points
- Difference: -12 points from verbosity
- Feedback_minimax_overrides: Verbose briefings cause overrides

**Validation:**
- Cost: Zero (prompt only)
- Risk: Low (removing lines is less risky than adding)
- Measurement: wc -l prompt.j2 (should be ~22)

---

### P3: OPTIONAL (1 hour, +1-2 points) ⭐⭐ NICE TO HAVE

**Problem:** 8-10 tasks have unit mismatches (billions vs millions).
**Solution:** Add units parsing section to prompt + verify checklist.

**Implementation:**
1. Add 3-line units section to prompt
2. Include units check in verify skill (already partially there)
3. Examples: "If question asks billions but table shows millions, multiply by 1000"

**Evidence:**
- Known failure mode from grading analysis
- v10 analysis showed FY/CY + units = 52% of failures
- Relatively straightforward to add

---

## EXPECTED GAINS (Ranked by Confidence)

| Tier | Change | Local Impact | Arena Impact | Effort | Priority |
|------|--------|--------------|--------------|--------|----------|
| P0 | Verify mandatory | +5-8pts | +5-8pts | 1.5h | HIGHEST |
| P1 | calcs.py | +4-6pts | +3-5pts | 2h | HIGH |
| P2 | Tighten prompt | +2-4pts | +1-3pts | 1.5h | MEDIUM |
| P3 | Units parsing | +1-2pts | +0-2pts | 1h | OPTIONAL |
| **Total** | **All Tiers** | **+12-20pts** | **+9-16pts** | **6h** | - |
| **Conservative** | **P0+P1** | **+9-14pts** | **+8-13pts** | **3.5h** | - |

**Expected Final Score: 190-196 (best case 200+)**

---

## TESTING STRATEGY (De-risk Before Arena Submission)

### Phase 1A: Quick Validation (1 hour)
```bash
# 1. Syntax check all Python files
python3 -m py_compile r11/submit/{calcs,q,cpi}.py

# 2. Test on 3 known failures
./run_local_r8.sh UID0050  # unit mismatch (verify + units parsing)
./run_local_r8.sh UID0012  # stdev (calcs.py)
./run_local_r8.sh UID0041  # extraction error (verify)

# 3. Measure: Count PASS vs FAIL in traces
# Expected: at least 1 of 3 flips from FAIL→PASS
```

### Phase 1B: Full Local Test (2 hours)
```bash
# Run all 68 UIDs locally with new config
bash full_test.sh 2>&1 | tee r12_local_results.txt

# Compare against r11 baseline
# Measure: Total PASS count (should be ≥ r11)
# Expected: +5-8 additional PASS

# If gain ≥ +3pts and no regressions → proceed to arena
# If loss > 2pts → rollback and debug
```

### Phase 2: Arena Validation (24-48 hours)
```bash
# Submit to arena
arena submit --version r12

# After 24-48h, pull traces
python3 pull_latest_traces.py --submission r12

# Analyze:
# - Verify skill: is it loading? (should be 80%+ of traces)
# - Score delta: (r12 final - r11 baseline) vs prediction
# - Failure modes: same extraction errors, or new ones?

# Expected: +8-12 points in arena
# Acceptable range: +5 to +15 points
# Red flag: < +3 points or > 2 regressions
```

---

## IMPLEMENTATION ROADMAP

### TODAY (4.5 hours)

**1. Update prompt.j2** (0.5h)
- Line 23-24: Make verify mandatory + explicit
- Remove grep tips (4 lines)
- Remove formula hints (5 lines)
- Add units parsing section (3 lines)
- Target: 22-24 lines

**2. Add q.py** (0.5h)
```python
#!/usr/bin/env python3
"""Minimal query tool for verify skill."""
import sys, os, glob

def search(keyword, limit=5):
    files = sorted(glob.glob('/app/resources/*.txt'))
    found = 0
    for f in files:
        if found >= limit: break
        with open(f) as fh:
            for line in fh:
                if keyword.lower() in line.lower():
                    print(f"{os.path.basename(f)}: {line.strip()}")
                    found += 1
                    if found >= limit: break
```

**3. Add calcs.py** (1h)
- 8 functions: sum_values, mean, pct_change, cagr, stdev, median, percent_of_total
- ~60 lines total
- All with try/except for robustness

**4. Improve verify skill** (0.5h)
- Rewrite for clarity (7-step checklist)
- Add MISTAKES TO CATCH section
- Make units check explicit

**5. Local test on 5 UIDs** (1h)
- UID0050 (unit), UID0012 (stdev), UID0018 (FY), UID0028 (sum), UID0041 (extract)
- Measure: flips from FAIL→PASS or regressions
- Expected: 2-3 flips

**6. Full 68-UID local test** (1h)
- Baseline vs new config comparison
- Expected: +5-8 additional PASS

### TOMORROW (2 hours)

**7. Validation & Rollback Plan** (1h)
- If local gain ≥ +3: package as r12
- If local gain < +3: debug or revert P1-P3
- Archive baseline for comparison

**8. Submit to Arena** (0.5h)
```bash
cp -r r11/submit r12/submit
# Apply all changes
arena submit --version r12
```

**9. Schedule Trace Pull** (0.5h)
- Set reminder to pull traces in 24-48h
- Prepare comparison script

### DECISION POINT: 48 hours post-submission
- If arena gain = +8-12pts → Success, consider Tier 3
- If arena gain = +5-8pts → As predicted, consider optional improvements
- If arena gain < +5pts → Investigate traces for root cause
- If arena loss → Rollback immediately

---

## RISK ASSESSMENT & MITIGATION

### Risk 1: Local Gains Don't Translate to Arena (Medium Risk)
**Why:** Grading has 12.8% noise; local test bias with 30-turn limit
**Mitigation:**
- Test on multiple task types (sums, CY, FY, compute-heavy)
- Check traces for skill loading (should be 80%+)
- If suspect, pull traces and compare vs r11 baseline
**Rollback:** git checkout r11/; arena submit --version r11_revert

### Risk 2: Verify Step Breaks Some Tasks (Low Risk)
**Why:** Re-verification might cause overthinking
**Mitigation:**
- v15 proved verify helps 50% and hurts 0% (net positive)
- Traces will show if verify is loading
- Can be disabled easily in prompt
**Rollback:** Change "mandatory" back to "suggestive" in prompt

### Risk 3: calcs.py Hallucinations (Low Risk)
**Why:** Model might try to use functions that don't exist
**Mitigation:**
- Include only 8 proven functions
- All have try/except error handling
- Prompt says "or use python3 -c" if prefer
**Rollback:** rm r12/submit/calcs.py; arena submit --version r12_no_calcs

### Risk 4: Tighter Prompt Loses Information (Very Low Risk)
**Why:** Removing lines could hurt edge cases
**Mitigation:**
- FY/CY guidance stays (critical for 22% of tasks)
- Grep tips removed but MiniMax greps correctly anyway (proven in v20)
- Formula hints removed but calcs.py provides better alternative
**Rollback:** git show r11:r11/submit/prompt.j2 > r12/submit/prompt.j2

### Risk 5: Arena Submission Fails (Very Low Risk)
**Why:** Tarball format or version issues
**Mitigation:**
- Test locally first (catches syntax errors)
- Use standard r11 as base (format is proven)
- Keep .arenaignore if present
**Fallback:** Submit r11_revert immediately

---

## WHAT WON'T WORK (Avoid These)

### Sub-LLM Verification Calls (SKIP)
- Cost: $2.50-12.50 per task
- Gain: Likely negative (v15 showed tools hurt)
- Reasoning: Unnecessary overhead; local verify is free and proven

### Custom Parsing Layer (SKIP)
- Cost: 10+ hours to build and debug
- Gain: -2 points (v15 e.py had 2% success)
- Reasoning: Extraction errors come from model reading wrong rows, not missing parsing tools

### Pre-Computed SQLite DB (SKIP)
- Cost: 20+ hours
- Gain: +1-2 points (DB loses 50% of data)
- Reasoning: Grep is simpler and more reliable for malformed tables

### Model Swap to GPT-4 (CONDITIONAL)
- Cost: 100x more expensive ($0.30 vs $0.03 per task)
- Gain: Unknown, likely +3-8 points
- Recommendation: Test locally on 10 tasks first; only pursue if +10pts locally
- Current status: Not worth trying until P0-P2 ceiling is proven

---

## SUCCESS METRICS & GO/NO-GO GATES

### Gate 1: Local Testing (Pass/Fail today)
**Target:** No crashes, verify loads, calcs imports
**Success:** 3/3 test tasks run without errors
**Action if FAIL:** Debug syntax before arena submission

### Gate 2: Local Full Test (Pass/Fail today)
**Target:** +3 to +8 additional PASS on 68 UIDs
**Success:** r12_local >= r11_baseline by at least 3 points
**Action if FAIL:**
- If < 0 (regression): Revert P2-P3, keep P0
- If 0-2 (no improvement): Investigate traces, consider Tier 3
- If > 8 (overperforming): Expect arena to be 20-30% lower due to noise

### Gate 3: Arena Submission (Pass/Fail in 48h)
**Target:** +8 to +12 points (expected from 180→188-192)
**Success Range:** 185-195 (gain of +5-15)
**Action if PASS:** Consider Tier 3 improvements
**Action if < 183 (loss): Rollback and debug immediately**

### Gate 4: Traces Show Verify Loading (Pass/Fail)
**Target:** verify skill called in 80%+ of traces
**Success:** Manual spot-check shows skill in traces
**Action if FAIL:** Investigate skill format or recipe issues

---

## IMPLEMENTATION CHECKLIST

### Pre-Implementation
- [ ] Read CONCRETE_CHANGES.md for exact diffs
- [ ] Have r11/submit/ backed up
- [ ] Verify local test harness works: ./run_local_r8.sh UID0001

### Phase 1: Code Changes (1.5h)
- [ ] Update prompt.j2 (verify mandatory, remove noise, add units)
- [ ] Add q.py (50 lines, search + preview)
- [ ] Add calcs.py (60 lines, 8 functions)
- [ ] Update verify skill (clearer wording, units check)

### Phase 2: Quick Validation (1h)
- [ ] Syntax check: python3 -m py_compile calcs.py q.py
- [ ] Quick test: UID0050, UID0012, UID0018
- [ ] Manual verification: ls -la r11/submit/ shows all new files

### Phase 3: Full Local Test (2h)
- [ ] Run: bash full_test.sh 2>&1 | tee r12_local.txt
- [ ] Count: grep "PASS" r12_local.txt | wc -l
- [ ] Compare: diff r11_baseline.txt r12_local.txt
- [ ] Decision: If gain >= +3, proceed; else debug

### Phase 4: Arena Submission (0.5h)
- [ ] Package: cp -r r11/submit r12/submit; git add r12
- [ ] Commit: git commit -m "r12: Mandatory verify + calcs.py + tighter prompt"
- [ ] Submit: arena submit --version r12
- [ ] Log: Save submission ID

### Phase 5: Trace Validation (24-48h)
- [ ] Pull: python3 pull_latest_traces.py --submission r12
- [ ] Analyze: Check verify skill loading, score delta
- [ ] Compare: vs r11 baseline in traces
- [ ] Decide: Gate 3 pass/fail

---

## RESOURCE ALLOCATION

### Effort Budget: 6 hours total
- Today: 4.5 hours (coding + local test)
- Tomorrow: 0.5-1 hour (final validation + submission)
- 24-48h: 0.5 hour (trace pull + analysis)

### Cost Budget
- P0: $0 (no API calls, just prompt)
- P1: $0 (local Python functions)
- P2: $0 (prompt change only)
- P3: $0 (optional units guidance)
- **Total: $0** (no additional API costs)

### Arena Submissions
- Current: r11 baseline (baseline for comparison)
- Planned: r12 (Tier 1+2 combined)
- Optional: r12_no_calcs (if P1 regresses)
- Optional: r13 (Tier 3 if r12 succeeds)

### Local Test Count
- 3-task quick validation: 3 UIDs
- Full validation: 68 UIDs
- **Total local runs: 71** (low cost)

---

## FAQ & DECISION SUPPORT

### Q: Should I do all three tiers or just P0?
**A:** Start with P0 alone (1.5h). If local test shows +3pts, add P1 immediately (only +2h more). P2 is optional stabilization.

### Q: What if local test shows 0 improvement?
**A:** Investigate using traces. Likely issue: verify skill not loading (format error). Check SKILL.md exists in r11/submit/skills/verify/. If format is wrong, revert and debug.

### Q: Is 190 realistic or wishful thinking?
**A:** Realistic. v15 verified step alone caught 5 known failures. calcs.py addresses 4-6 formula errors. Together with tighter prompt = +9-14pts conservatively. Arena variance means final might be 185-195, but central estimate is 188-192.

### Q: What's the path to 200?
**A:** P0+P1 gets you to 188-192. From there:
- Model swap (GPT-4): +3-8 pts (expensive, test locally)
- Forced decomposition: +1-2 pts (added complexity)
- Better FY/CY rules: +1-3 pts (hard to enforce without structure)
- Unlikely to reach 200 without one of these Tier 3 efforts

### Q: Will arena differ from local?
**A:** Yes, by ~20-30%. Local with 30-turn limit biases toward longer prompts. Arena actual is often 5-15 points different from local. **Always trust arena results over local.**

### Q: Should I try different models?
**A:** Not yet. MiniMax is at ~70% ceiling; GPT-4 likely similar. Worth exploring only after hitting P0+P1 ceiling. Test locally on 10 tasks first.

### Q: What if something breaks?
**A:** Rollback: `git checkout r11/; arena submit --version r11`. Takes 5 minutes. You have proven r11 baseline.

---

## THE DECISION

**RECOMMENDATION: Proceed with Tier 1 (P0) today.**

| Metric | Value | Status |
|--------|-------|--------|
| Expected gain | +5-8 points | HIGH confidence |
| Effort | 1.5 hours | VERY LOW |
| Risk | Low | v15 proved this works |
| Cost | $0 | FREE |
| Timeline | 1.5h code + 1h test = 2.5h today | IMMEDIATE |
| Local signal | Should see 2-3 UID flips | MEASURABLE in 1h |
| Arena signal | 24-48h from submission | FINAL PROOF |

**GREEN LIGHT: Implement P0 today, add P1 if local shows +3pts, submit to arena by end of day.**

---

## LONG-TERM ROADMAP (If You Want to Reach 200)

### Week 1 (Now)
- [ ] **Day 1:** Implement P0, test locally, submit r12
- [ ] **Day 2:** Pull r12 traces, confirm +8-12pt gain
- [ ] **Day 3:** Implement P1 if not already included in r12

### Week 2 (Optional, if r12 = 188-192)
- [ ] Analyze remaining 30 failures (the hard 26)
- [ ] Identify which are fixable vs arena bugs
- [ ] Test model swap on 10-task sample
- [ ] Consider forced decomposition (ANALYZE→PLAN→EXECUTE)

### Week 3+ (If pursuing 195+)
- [ ] Implement best Tier 3 option (model or decomposition)
- [ ] Iterate on FY/CY rules with stronger enforcement
- [ ] Deep dive on always-fail tasks (38 total, 26 solvable)

---

## CONCLUSION

Your agent is at 69.5%. The consensus from 200+ traces and 12+ prior submissions is **clear and actionable:**

1. **The problem is wrong numbers, not missing reasoning.** Verify fixes this.
2. **More tools hurt; simpler tools help.** Pre-built functions are proven.
3. **Verbose prompts cause overrides.** Keep it tight.
4. **10-16 point gain is realistic** with 4-6 hours of focused work.
5. **Tier 1 alone should hit +5-8 points** within 2.5 hours.

**Start with P0 today. If local test shows +3pts, commit and submit by EOD. You'll see results in 48 hours.**

Expected final score: **190-196 points (77-80%)**. This is the realistic path to beating your current ceiling.

---

## APPENDICES

### A: Git Workflow
```bash
# Create feature branch
git checkout -b r12/master-opt

# Make changes
# Test locally
bash full_test.sh

# Commit when local shows +3pts gain
git commit -am "r12: Mandatory verify + calcs.py + units parsing (P0+P1+P2)"

# Submit to arena
arena submit --version r12

# Monitor
python3 pull_latest_traces.py --submission r12 --poll 30m
```

### B: Exact File Locations
- Prompt: `r11/submit/prompt.j2`
- Verify skill: `r11/submit/skills/verify/SKILL.md`
- New files: `r11/submit/q.py`, `r11/submit/calcs.py`
- Local harness: `run_local_r8.sh` (provided)
- Full test: `bash full_test.sh` (generates pass/fail counts)

### C: Key Memory Documents for Reference
1. **project_v20_trace_analysis.md** — 245 traces, 69.5%, failure modes
2. **feedback_verify_works.md** — Proof: verify flips 50% of wrong-answer tasks
3. **feedback_minimax_overrides.md** — Why verbose prompts hurt
4. **project_ab_test_results.md** — 14 variants, MiniMax ceiling
5. **CONCRETE_CHANGES.md** — Exact diffs for all files

### D: Success Looks Like
```
Day 1 (local test):
  - run_local_r8.sh UID0050 → changed from FAIL to PASS ✓
  - run_local_r8.sh UID0012 → changed from FAIL to PASS ✓
  - bash full_test.sh → 165-172 PASS (vs r11 baseline ~159-163) ✓

Day 2 (submission):
  - arena submit --version r12 ✓
  - Receive submission ID ✓

Day 3-4 (validation):
  - Pull traces showing verify skill loaded ✓
  - Final score 188-195 (gain of +8-12) ✓
  - Decide on Tier 3 or ship as-is ✓
```

---

**END MASTER PLAN**

This is your actionable roadmap. It's conservative, proven, and ready to execute. Questions? See IMPROVEMENT_RECOMMENDATIONS.md for detailed rationale on each decision.
