# Recommendation Summary: Design the Optimal Combination

## Quick Answer

**Design v21:** Combine v5's proven 30-line prompt philosophy + v20's 12-step execution speed + v15's verification checklist (inlined, not skill-based).

**Expected score:** 205-215 (vs v20's 183.8 baseline, +10-30 improvement)
**Confidence:** High (70%)
**Risk:** Low (revert to v20 if underperforms)

---

## The Core Insight

The v20 traces revealed that **68% of failures (51/75 = 68%) are "found data, wrong extraction"**:
- Grabbed the right page
- Found the right table
- But misread which row/column/cell

This is exactly what v15's `verify` checklist targets. v15 proved the fix works (50% of wrong-answer cases flip to correct), but the implementation was too expensive (47 no-answer failures from turn-wasting on skills).

**Solution:** Inline the verification logic directly into the prompt instead of using skills.

---

## What Each Version Does Best

| Aspect | v5 | v20 | v15 |
|--------|----|----|-----|
| **Prompt style** | 30 lines, permissive | 5 lines, minimal | 20 lines, tools-heavy |
| **Execution** | ~18 steps | 12.5 steps | ~25 steps (bloated) |
| **Score** | 184.5 | 183.8 | 162.5 |
| **No-answer rate** | 8% | 1% | 19% |
| **Verification** | No | No | Yes (but expensive) |
| **Why it loses** | No verification (53 wrong numbers) | No verification (73 wrong) | Turn waste + skills overhead (47 no-answer) |

---

## The v21 Design

### Prompt Structure (42 lines)

```
[Base from v5 — page-first discovery, "write immediately" principle]

+ [KEY RULES from v5 — parentheses, units, FY vs CY, exact row labels]

+ [BEFORE COMPUTING checklist from v15 — inline verification]
  - Is this the right row?
  - Right column/year?
  - Units correct?
  - All values?
  - Parentheses checked?
  - FY boundaries?

+ [AFTER COMPUTING checklist from v15 — sanity check]
  - Magnitude reasonable?
  - Sign correct?
  - Formula right?

- [Remove all skills references]
- [Remove all MCP references]
- [Remove FY/CPI/tools prescriptions]
```

### Why This Works

1. **Combines the three highest-scoring approaches:**
   - v5's permissive framing (MiniMax ignores detailed rules)
   - v20's speed (inline checks don't add turns)
   - v15's verification logic (proven 50% fix rate on wrong answers)

2. **Targets the specific bottleneck:**
   - v20 optimized away search time
   - Bottleneck shifted from "find page" → "read page correctly"
   - v21's checklist directly addresses this

3. **Zero turn cost:**
   - Verification is just reasoning (no tool calls)
   - Inline vs skill = 0 turns saved per task
   - v15 spent 3+ turns on skills, v21 spends 0

4. **Stays in MiniMax's sweet spot:**
   - Still ~40 lines (permissive zone)
   - Still page-first guidance
   - Still "write answer immediately" principle
   - Just adds quiet confirmation steps

---

## Concrete Improvements (By Failure Category)

Starting from v20's 75 failures:

| Failure Mode | Count | Expected Fix | Method |
|---|---|---|---|
| B: Wrong extraction (51 fails) | 51 | -25 to -30 | Inline row/column/section checks |
| C: Quick wrong number (20 fails) | 20 | -3 to -5 | Units/magnitude/sign checks |
| D: Computed but didn't write (10 fails) | 10 | -2 to -3 | No change (verify doesn't loop) |
| A: Turn exhaustion (9 fails) | 9 | -1 to -2 | Inline verify is cheap |
| E: No answer (2 fails) | 2 | -0 to -1 | Verify doesn't timeout |

**Conservative estimate:** Fix 30-35 failures (B + partial C + partial D + A)
**Result:** 171 passes + 30-35 improvements = **201-206/246**

**With optimistic scenario (fix 35-40 fails):**
**Result:** 171 + 35-40 = **206-211/246**

**Expected score range: 201-215** (with grading noise variance ±10)

---

## Why NOT the Alternatives

### Alternative 1: Just Use v5 Again
- **Why not:** Already achieved 184.5. Ceiling likely reached; no new lever.
- **Upside:** Guaranteed ~184.5
- **Downside:** No improvement

### Alternative 2: Just Use v20 Again
- **Why not:** Misses the verification opportunity. 68% of fails are extraction errors.
- **Upside:** Guaranteed ~183.8
- **Downside:** No improvement

### Alternative 3: Reuse v15 as-is
- **Why not:** Turn waste kills it (47 no-answer failures). Skills don't work reliably in arena.
- **Upside:** Verification logic proven
- **Downside:** Too slow, 162.5 score

### Alternative 4: v5 + v15 Skills (Hybrid)
- **Why not:** Skills are broken in arena (confirmed v15 traces show zero skill loads in some tasks). Would just add overhead without benefit.
- **Upside:** None
- **Downside:** Revives broken skill system

### Alternative 5: v20 + Single Python Validator
- **Why not:** Over-engineered. Inline reasoning is simpler and works better with MiniMax.
- **Upside:** One turn cost for validation
- **Downside:** Adds complexity, MiniMax may ignore it or loop on it

---

## Implementation Plan

### Step 1: Create v21 (2 files)
```
v21/
├── arena.yaml (copy from v20 config, no changes)
└── prompts/
    └── system.j2 (v5 base + inline v15 verification)
```

### Step 2: Local Testing (30 min)
```bash
python3 run_local_v7.sh v21 --max-turns 40 --uids 1-40
```
**Target:** 28-30/40 passes (70-75%)
**Decision:**
- ≥28 passes → submit v21 with confidence
- 27 passes → equivalent to v20, marginal risk
- <27 passes → inline checks are too noisy, revert to v20

### Step 3: Submit
```bash
arena submit v21 ...
```

### Step 4: Monitor
**After 50 traces:** Check if verification logic appears in reasoning
**After 246 traces:** Compare to v20 baseline (183.8)
- ≥195 score → verification is working, success
- 185-195 score → marginal improvement, keep it
- <185 score → revert to v20 for next attempt

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Inline checks too noisy, MiniMax loops | Low (15%) | Medium (-5 points) | Local test catches this, revert to v20 |
| Prompt too long, MiniMax ignores rules | Low (10%) | Medium (-5 points) | 42 lines is still "minimal" zone, v5 was 30 |
| Verification catches nothing, no improvement | Medium (25%) | Low (0-2 points) | v20 proved the error exists; verification should catch it |
| Verification adds turns, hurts no-answer rate | Low (10%) | Medium (-3 points) | Verification is just reasoning, no tool calls |
| Arena grading noise masks improvement | Medium (35%) | Low (noise ±10) | Normal variance; won't fully hide 10-30 point improvement |

**Overall:** 70% confidence this beats v20 by 10-30 points

---

## Success Criteria

| Outcome | Score | Status |
|---|---|---|
| **Home run** | >210 | v15's verification works + v20's speed = achieved goal |
| **Win** | 195-210 | Inline verification is catching errors as expected |
| **Break-even** | 183.8-194 | Verification adds noise but doesn't help; revert to v20 |
| **Regression** | <183.8 | Inline checks backfired; lesson learned, don't repeat |

---

## What We Learned from Each Version

**v5 (184.5):**
- Minimal prompts work better than detailed ones
- Page-first discovery is natural for MiniMax
- "Write immediately" reduces no-answer failures
- ~30 lines is the sweet spot

**v20 (183.8):**
- Speed matters (12.5 steps is faster than 18)
- 68% of failures are extraction errors, not search errors
- Verification is the missing piece
- v20 optimized away the bottleneck but created a new one

**v15 (162.5):**
- Verification logic works (50% fix rate proved)
- But skills are fragile in arena
- Turn budget is the real constraint
- Need to inline the verification, not skill-ify it

**v10 (180):**
- Ultra-minimal (5 lines) loses 4.5 points vs v5 (30 lines)
- Some prompt content is valuable
- The missing content is likely edge case rules (parentheses, FY vs CY)

---

## Concrete Prompt Content

The v21 prompt will contain:

**From v5 (keep):**
- Page-first guidance
- "write answer immediately" principle
- Parentheses rule
- FY vs CY distinction
- "Exact row label" emphasis
- Math formulas (pct_change, CAGR)

**From v15 (add inline):**
- "Is this the right row?" checklist
- "Right column/year?" section counting
- "Units correct?" check
- "All values?" completeness check
- "Parentheses = negative" reinforcement
- "FY boundaries" verification
- "Magnitude reasonable?" sanity check
- "Sign correct?" deficits are negative
- "Formula right?" double-check calculation

**Remove completely:**
- All skills references
- All MCP tool references
- Multi-stage decomposition steps
- CPI table embedding
- Few-shot examples

---

## What Success Looks Like in Traces

When v21 works, you'll see in the reasoning_content of traces:

```
[Task: "What was individual income tax in FY1995?"]

Found the page showing receipts data.
Let me verify:
- Is this the right row? "Individual income taxes" ≠ "Total receipts" ✓
- Right year? 1995 is the 2nd column in the header ✓
- Units? Table header shows "(in millions)" ✓

Extracting: 160,000 (in millions)
Magnitude check: federal taxes in millions, makes sense ✓
Writing answer...
```

You'll see these checks appear naturally in reasoning without adding turns. This is the sign verification is working.

---

## Final Decision Matrix

| If you believe... | Then choose... | Expected score |
|---|---|---|
| "Inline verification is worth +10-30 points" | Submit v21 | 195-215 |
| "Verification might backfire, stick with speed" | Submit v20 | 183.8 |
| "I want to be 100% safe, proven baseline" | Submit v5 | 184.5 |
| "I have time to test locally first" | Test v21 locally, then decide | 195-215 if >28/40 passes |

---

## Recommendation

**I recommend v21 (v5+20+15 fusion) with local testing first.**

**Rationale:**
1. Low risk (revert to v20 if it underperforms)
2. High upside (10-30 point improvement if verification works)
3. Targets the specific bottleneck v20 identified
4. Proof of concept from v15 (verification flips 50% of errors)
5. Zero turn cost (inline reasoning, not skill overhead)
6. MiniMax's behavior unchanged (still page-first, still writes immediately)

**Next steps:**
1. Create v21/arena.yaml and v21/prompts/system.j2
2. Run local harness test on 40-task sample (30 min)
3. If >28/40 passes: submit v21
4. If ≤27/40 passes: submit v20 (revert)

This is a high-leverage, low-risk experiment that directly addresses the bottleneck we identified.

