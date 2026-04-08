# Optimal AI Agent Combination Analysis

## Quick Navigation

Start here based on your need:

### 1. **Decision Makers** (5 min read)
→ Read: `ANALYSIS_SUMMARY.txt` (this file)
- One-page overview of the recommendation
- Risk/benefit analysis
- Expected scores

### 2. **Strategic Deep Dive** (15 min read)
→ Read: `RECOMMENDATION_SUMMARY.md`
- Why each version wins/loses
- Root cause analysis
- Decision matrix

### 3. **Ready to Implement** (30 min)
→ Read: `IMPLEMENTATION_GUIDE.md`
- Step-by-step setup
- Local testing instructions
- Fallback plans

### 4. **Copy & Submit** (5 min)
→ Read: `v21_READY_TO_SUBMIT.md`
- Exact files to create
- Copy-paste ready prompts
- Arena submission command

### 5. **Understand the Fix** (20 min)
→ Read: `VERIFICATION_EXAMPLES.md`
- 6 real failure cases from v20
- How v21's verification catches them
- Visual before/after

### 6. **Full Technical Analysis** (60 min)
→ Read: `OPTIMAL_COMBINATION_ANALYSIS.md`
- Complete failure breakdown by version
- Detailed comparison matrix
- All design rationales

---

## Summary

**Design:** v21 (v5 + v20 + v15 fusion)
- **Base:** v5's 30-line prompt (proven 184.5 score)
- **Add:** v20's 12-step execution speed (proven 183.8, fast)
- **Insert:** v15's verification checklist (proven 50% fix rate)

**Result:** 205-215 expected score (vs v20's 183.8 baseline)
**Risk:** Low (can revert to v20 if underperforms)
**Effort:** 30 min test + 2-4 hours arena run

---

## The Insight

v20 optimized away the SEARCH bottleneck, but revealed a DATA EXTRACTION bottleneck:
- 68% of v20's failures = found the right page, misread the row/column
- v15 proved that a simple checklist flips 50% of these errors
- But v15's skills-based approach was too expensive (47 no-answer failures)

**Solution:** Inline the checklist into the prompt instead of using skills.

---

## Why This Works

| Element | From | Why |
|---------|------|-----|
| Base prompt (30 lines) | v5 | Proven highest score (184.5); permissive tone works with MiniMax |
| Page-first guidance | v5 | Natural file discovery; MiniMax does this anyway |
| "Write immediately" | v5 | Prevents timeout loops; only 2 no-answer fails in v20 |
| Speed (12.5 steps) | v20 | Already proven minimal no-answer rate |
| Verification checklist | v15 | Proven to flip 50% of wrong-answer cases |
| Inline implementation | New | Zero turn cost (vs v15's 3+ turns for skills) |
| Parentheses rule | v5 | Prevents hallucination; (123) = -123 |
| FY vs CY clarity | v5 | Prevents fiscal year boundary errors |
| Section header check | New | Catches "Total receipts" vs "Individual income" errors |
| Column counting rule | New | Catches alignment errors |

---

## What You Get

### Analysis Documents (read in order)
1. `ANALYSIS_SUMMARY.txt` — One-page overview
2. `RECOMMENDATION_SUMMARY.md` — Strategic rationale
3. `OPTIMAL_COMBINATION_ANALYSIS.md` — Full technical analysis
4. `VERIFICATION_EXAMPLES.md` — Real failure cases + fixes
5. `IMPLEMENTATION_GUIDE.md` — Setup and testing

### Ready-to-Submit Materials
- `v21_READY_TO_SUBMIT.md` — Exact files + commands

---

## Next Steps

### If you want to understand the strategy (30 min):
```
1. Read ANALYSIS_SUMMARY.txt (5 min)
2. Read RECOMMENDATION_SUMMARY.md (15 min)
3. Skim VERIFICATION_EXAMPLES.md (10 min)
```

### If you want to implement immediately (1 hour):
```
1. Read v21_READY_TO_SUBMIT.md (5 min)
2. Create v21/arena.yaml and v21/prompts/system.j2 (5 min)
3. Run local test: python3 run_local_v7.sh v21 --uids 1-40 (40 min)
4. Submit if ≥28/40 passes (5 min)
```

### If you want deep understanding (2 hours):
```
1. Read all documents in order
2. Review real examples in VERIFICATION_EXAMPLES.md
3. Understand the design rationale in OPTIMAL_COMBINATION_ANALYSIS.md
4. Then implement
```

---

## Expected Outcome

**Local test (40-task sample):**
- v20 baseline: ~27/40 (67.5%)
- v21 expected: 28-30/40 (70-75%)
- If you see 28-30, proceed to arena submit

**Arena submission (246 tasks):**
- v20 baseline: 183.8 score
- v21 expected: 205-215 score
- v21 conservative: 195 score
- v21 worst case: 185 score (still marginal win)

---

## Risk Mitigation

**If local test shows <28/40 passes:**
- Revert to v20 (command: `arena submit v20`)
- No loss; you already know v20 scores 183.8

**If arena score <185:**
- Expected within ±10 variance
- Submit v20 next time
- Lesson learned; don't repeat this experiment

**If arena score 185-195:**
- Marginal improvement
- Keep it or revert to v20
- Your choice

**If arena score 195-215:**
- Success! Verification is working
- This is the new baseline

---

## Files Created

All analysis and implementation files are in `/Users/jwalinshah/projects/officeqa-arena/`:

```
├── ANALYSIS_SUMMARY.txt ..................... (1-page overview, START HERE)
├── RECOMMENDATION_SUMMARY.md ............... (strategic rationale)
├── OPTIMAL_COMBINATION_ANALYSIS.md ........ (full technical analysis)
├── VERIFICATION_EXAMPLES.md ............... (real failure cases + fixes)
├── IMPLEMENTATION_GUIDE.md ................ (setup + testing)
├── v21_READY_TO_SUBMIT.md ................. (exact files to submit)
└── README_ANALYSIS.md ..................... (this file)
```

---

## TL;DR

**Design v21:** Combine v5's prompt + v20's speed + v15's verification (inlined)

**Expected score:** 205-215 (vs 183.8 baseline, +21 improvement)

**Risk:** Low (revert if underperforms)

**Action:** Read `v21_READY_TO_SUBMIT.md`, create two files, test locally, submit

**Time to completion:** 30 min test + 2-4 hours arena

