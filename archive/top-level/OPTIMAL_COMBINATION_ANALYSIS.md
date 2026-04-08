# Optimal AI Agent Combination: v5 + v20 + v15 Verification

## Executive Summary

We can achieve **80%+ accuracy** by combining the best elements from three versions:
- **v5's prompt philosophy** (minimal, permissive, ~30 lines)
- **v20's execution speed** (direct shell→python3→echo path, 12.5 steps avg)
- **v15's verification step** (checklist that flips 50% of wrong-answer fails)

**Key constraint:** v15's turn cost is too high (47 no-answer fails, poor skills adoption). The solution is **inline verification**, not skill-based.

---

## Version Comparison Matrix

| Metric | v5 | v10 | v15 | v20 |
|--------|----|----|-----|-----|
| **Score** | 184.5 | 180 | 162.5 | 183.8 |
| **Pass rate** | 74.8% | 73.2% | 66.1% | 74.4% |
| **Avg steps** | ~18 | ~8 | ~25 | 12.5 |
| **No-answer fails** | 19 | ? | 47 | 2 |
| **Wrong-answer fails** | 53 | ? | 73 | 73 |
| **Verification step?** | No | No | Yes | No |
| **Prompt length** | 30 lines | 5 lines | 20 lines | ~5 lines |
| **Skills?** | No | No | Yes | No |
| **MCP/tools?** | No | No | Yes | No |
| **Page files?** | Yes | Yes | Yes | Yes |

---

## Failure Analysis: Why Each Version Struggles

### v5 (184.5) — The Reference Point
**What works:**
- Minimal prompt (30 lines) doesn't distract MiniMax
- Page-first file discovery (natural for MiniMax)
- Permits MiniMax to explore freely without rule fatigue
- "Write answer immediately" principle prevents timeouts

**Why it fails (53 wrong numbers):**
- No verification step catches extraction errors
- Misreads rows/columns (15 cases)
- Hallucinated CPI values (5-6 cases)
- Wrong formula applied (3-5 cases)
- Ambiguous interpretation (remainder)

---

### v20 (183.8) — The Speed Champion
**What works:**
- Fastest execution (12.5 steps, almost no timeouts)
- Minimal no-answer fails (only 2)
- Direct linear path: cat page → grep → python3 -c → echo
- Respects MiniMax's natural workflow

**Why it fails (73 wrong numbers):**
- **No verification step** — goes cat→compute→write with zero confirmation
- 68% of failures (51/75) are "found data, wrong extraction"
  - Read wrong row despite being on correct page
  - Misread column alignment
  - Misinterpreted table headers
  - Grabbed adjacent cell instead of target

**Lesson:** v20 proves that once you find the right page, verification becomes the bottleneck, not search.

---

### v15 (162.5) — The Verification Attempt
**What works:**
- `verify` skill flips 50% of wrong-answer tasks to correct (impressive!)
- Checklist catches row/section/column/units/sign/formula errors
- Pre-1977/post-1977 FY rules explicitly enumerated

**Why it fails (47 no-answer, 73 wrong):**
- **Turn budget blown on skills loading** (decompose + tools + reference = 3+ turns just to initialize)
- Skills format brittle in arena (only works with subdirectory/SKILL.md)
- `officeqa-tools` has e.py with 2% success rate (most extractions fail)
- Verify runs LLM sub-call (ask command) which is slow and unreliable
- 40-turn budget exhausted on loop failures, not problem-solving

**Key insight:** v15 proves verification works, but the *execution* is wrong.

---

### v10 (180) — The Ultra-Minimal
**Why so much worse than v5 (184.5 vs 180)?**
- Loss of ~20 lines of guidance doesn't warrant 4.5-point drop
- Suggests some prompt content IS valuable
- The missing piece: clarification of edge cases (parentheses = negative, FY vs CY rules)

---

## Root Cause of v5 Dominance

v5 wins because it hits the **Goldilocks zone** for MiniMax:
1. **Enough structure** to guide file discovery (page-first hint)
2. **Enough freedom** to avoid rule-override backlash
3. **Enough clarity** on math rules (parentheses, pct_change formula) to prevent hallucination
4. **Just enough constraints** ("write answer.txt immediately") to prevent timeout loops

v20 is only 1 point behind because it does steps 1-3 perfectly, but loses 1 point per ~15 wrong-answer fails by not doing verification.

---

## The Bottleneck Shift

**v5's 53 wrong-number failures** are split roughly:
- 15 wrong data extraction (wrong row/column/alignment)
- 5-6 hallucinated CPI/FX
- 3-5 wrong formula
- 20+ ambiguous interpretation

**v20's 73 wrong-number failures** are concentrated:
- 51/73 = 68% are "found data, wrong extraction" (wrong row/column/cell)
- 13% never wrote answer (D category: computed but crashed before echo)
- 12% exhausted turns
- 7% other

**Insight:** v20 optimizes away time, which shifts the bottleneck from "find the page" to "read the cell correctly." This is exactly where v15's verify step wins.

---

## Optimal Design: v5+20+15 Fusion

### Prompt (v5 base, ~35 lines)

```
You are a Treasury Data Analyst. Answer the question using local files only.

/app/resources/ contains bulletin files. Start with *_page_*.txt files (small,
answer table inside). Fall back to full .txt for broader searches.

Use python3 -c for ALL arithmetic. Never do mental math.
Trust ONLY values from /app/resources/ files — not your memory.

CRITICAL: Write your best answer to /app/answer.txt immediately once you have
a reasonable estimate. A wrong answer beats no answer.

KEY RULES:
- "(123)" means negative 123. Strip footnote markers (r/, p/, 3/).
- Check table headers: "(in millions)" ≠ "(in thousands)".
- FISCAL vs CALENDAR: FY pre-1977 = Jul–Jun. FY post-1977 = Oct–Sep. CY = Jan–Dec.
- Bulletin year ≠ data year. A 1941 bulletin often reports 1940 data.
- Match the EXACT row label. "National defense" ≠ "Total national security".
- Read columns carefully: count from header, don't assume alignment.
- Percentages: write 15.3 not 0.153. Range = max−min.

BEFORE COMPUTING: Verify extraction
- Is this the right row? Re-read the label. "Total" ≠ the line item.
- Right column/year? Count from header.
- Check units match question (millions/billions/thousands).
- Did I get all values? (12 for monthly, 2 for comparison, etc.)

MATH: pct_change=((new−old)/old)*100 | CAGR=(end/start)**(1/n)−1

FORMAT: echo −n "VALUE" > /app/answer.txt

{{ instruction }}
```

**Why this works:**
- Base from v5 (proven 184.5 score)
- Added v15's verification checklist (inline, not skill-based)
- Explicit column-counting rule (catches v20's main error)
- "Verify extraction" section runs inline without turn cost
- Keeps "write answer immediately" to prevent timeouts
- Removes skills/MCP entirely (never worked in arena)

---

### Workflow

No change to MiniMax's natural workflow:
1. `ls /app/resources/*.txt` (page-first discovery)
2. `cat /app/resources/*_page_*.txt` (find answer table)
3. **INLINE CHECK:** Re-read row label, count columns, verify units (3-4 lines of reasoning)
4. `grep -i "metric" page.txt | head -20` (extract values with context)
5. `python3 -c "print((new - old) / old * 100)"` (compute)
6. `echo -n "VALUE" > /app/answer.txt` (write)

**Key difference:** Step 3 is now explicit in the prompt instead of being a skill summon.

---

## Expected Impact on Failure Categories

### Starting point: v20 baseline (73 wrong + 2 no-answer = 75 fails)

**With inline verification in prompt:**

| Failure Mode | v20 Count | Expected Fix | Rationale |
|---|---|---|---|
| B: Wrong extraction (51/75 = 68%) | 51 | -25 to -30 | Explicit checklist catches row/column misreads |
| D: Computed but didn't write (10/75 = 13%) | 10 | -2 to -3 | Inline reasoning doesn't add turn cost |
| A: Turn exhaustion (9/75 = 12%) | 9 | -1 to -2 | Verification doesn't loop, just confirms |
| E: No answer (2/75 = 3%) | 2 | -0 to -1 | Quick verification won't timeout |
| C: Quick wrong (20/75 = 27%) | 20 | -3 to -5 | Formula/units clarification helps |

**Conservative estimate:** Fix 30-40 fails (B+C+D+A) → drop from 75 to 35-45 fails

**New score:** 171 + 30-40 fixes = **201-211/246 (81-85%)**

**With grading noise variance (±10 points):** Expected range 191-221 score

---

## Why This Beats Individual Approaches

| Attempt | Score | Problem |
|---|---|---|
| Just use v5 again | 184.5 | Ceiling reached; no new improvement lever |
| Just use v20 again | 183.8 | Missing verification; 68% of fails are extraction errors |
| Just use v15 again | 162.5 | Turn budget + skills overhead kills it |
| v20 + inline verify | ~205 | ✓ Combines speed + accuracy |
| v5 + skills verify | ~185 | ✗ Skills don't work in arena (confirmed in v15) |

---

## Implementation Checklist

### 1. Prompt file (35 lines)
- [ ] Base from v5 system.j2
- [ ] Add v15's verification checklist inline (not as skill)
- [ ] Add explicit "count columns from header" rule
- [ ] Add "right row ≠ wrong row" distinction (Individual vs Total income taxes example)
- [ ] Keep "write answer immediately" principle
- [ ] Remove all MCP/skills references

### 2. Arena configuration
- [ ] Set `harness_name: goose`
- [ ] Set `model: openrouter/minimax/minimax-m2.5`
- [ ] Set `max_turns: 40` (enough for v20-speed path + inline verification)
- [ ] Remove `skills_dir` entirely
- [ ] Remove `server` section (no MCP)
- [ ] Keep `timeout_per_task: 480` (same as v20)

### 3. No code changes
- [ ] Zero tools.py
- [ ] Zero MCP
- [ ] Zero skills subdirectories
- [ ] Just the prompt

### 4. Testing before submission
- [ ] Run local harness on 40-task sample with --max-turns 40
- [ ] Verify inline checks don't cause loops (they shouldn't — just reasoning)
- [ ] Spot-check 5 traces for "verify" section showing in reasoning
- [ ] Compare against v20 baseline (should beat it by 10-30 tasks)

---

## Risk Analysis

### Risk 1: Inline verification adds turns, hurts no-answer rate
**Mitigation:** Verification is just reasoning (no tool calls), so zero turn cost. v15 had tool calls inside verify (ask command), which was expensive. Ours is inline text.

### Risk 2: Prompt too long again, triggers MiniMax rule-override
**Mitigation:** Keep at 35 lines (v5 is 30, v20 is 5, this is hybrid). 35 is still under the "minimal" threshold that's proven effective.

### Risk 3: Verification checklist is too prescriptive, MiniMax ignores it
**Mitigation:** Frame as suggestions, not commands. "Is this the right row?" not "ALWAYS check the row label." Learned from v5: permissive > prescriptive.

### Risk 4: Inline verification is too vague, MiniMax skips it
**Mitigation:** Test locally first. If MiniMax doesn't follow through, add one concrete example ("If the question asks for 'individual income tax', don't accidentally read 'total receipts' from the line above").

---

## Alternate: Hybrid with Single Skill (Riskier)

If we want to preserve v15's verify benefit while minimizing turn cost:

**Option: Single inline Python validator**

Instead of skill, embed a one-liner python call:

```bash
python3 -c "
import re
text = open('/app/resources/page.txt').read()
print('Row found:', 'metric' in text)
print('Value context:', re.findall(r'metric.*?\d+', text))
"
```

This would:
- Cost 1 turn (grep costs 1 turn too, so net zero)
- Provide inline verification without skill overhead
- Let MiniMax see the extraction before compute

**BUT:** Risk is if MiniMax misinterprets regex output or loops on the validation. Not recommended unless local testing shows it works cleanly.

---

## Decision Matrix: Which Version to Submit

| Scenario | Recommendation | Expected Score |
|---|---|---|
| **High confidence in v5+inline verify** | Submit it | 200-215 |
| **Risk-averse, trust v20** | Submit v20 again | 183.8 |
| **Have time for local testing** | Test v5+verify on 68-UID set first, then submit | 195-220 |
| **Want quick validation** | Run against 20-task sample with local harness, submit if >75% | 195-220 |

---

## Why This is Better Than the 80.9% Ensemble

The 80.9% overlap (55/68 tasks both v15+v20 pass) was computed on a **subset of 68 tasks where both ran successfully**. The full 246-task arena includes:

- Tasks only v20 passes (29 out of 68 analyzed)
- Tasks only v15 passes (10 out of 68 analyzed)
- Tasks both fail (63 out of 68 analyzed)

A single v5+verify submission would:
- Get v20's 29 easy tasks (speed, minimal turnaround)
- Get v15's 10 verification-dependent tasks (checklist catches errors)
- Potentially crack 10-20 of the 63 joint-fail tasks via verification + v5 prompt clarity

**Projected combined score:** 171 (v20 baseline) + 30-40 (verification fixes) = 201-211

This is a **single-submission approach** rather than ensemble, which works because we're fusing the architectures, not voting.

---

## What We're NOT Doing

❌ **Not bringing back skills** (arena doesn't support them reliably, too many turn wasters)
❌ **Not including MCP** (never worked in arena, 0/246 traces used it)
❌ **Not embedding full CPI table** (too much context, MiniMax gets distracted)
❌ **Not doing multi-stage decomposition** (slow, turns-expensive, v20 already proved linear is better)
❌ **Not adding few-shot examples** (A/B test proved they hurt, they anchor behavior)

---

## Success Metrics

Submit this and track against baseline v20 (183.8):

- **Tier 1 (Success):** Score > 200 (best-of baseline + 10%+ improvement)
- **Tier 2 (Win):** Score 190-200 (matches or beats v5)
- **Tier 3 (Okay):** Score 183-190 (keeps v20's speed, barely ahead)
- **Tier 4 (Regression):** Score < 183 (revert, inline verify was too noisy)

---

## Appendix: The Verification Checklist (Inline)

This goes directly in the prompt, not as a skill:

```
BEFORE COMPUTING: Verify extraction
- Is this the right row? Re-read its label. "National Defense" ≠ "Total National Security".
  Check if the row is under the right section header (Receipts vs Refunds, etc.).
- Right column/year? Count columns from the header, don't assume alignment.
- Right units? Check table header: millions ≠ billions ≠ thousands.
- Parentheses mean negative: (123) = -123. Strip footnotes (r/, p/, etc.).
- Did I get all values? (12 for monthly, 2 for year-over-year, etc.)
- Magnitude reasonable? Federal budgets in billions, not millions.
```

This is ~8 lines, inlining what v15's verify skill did in 20 lines with a sub-call. Zero turn cost.

