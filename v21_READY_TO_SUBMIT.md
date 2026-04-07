# v21: Ready to Submit

This is the **exact specification** for the optimal combination. Copy and paste these files, test locally, then submit.

---

## File 1: v21/arena.yaml

```yaml
name: officeqa-v21
version: 21.0.0
competition: grounded-reasoning

agent:
  type: harness
  harness_name: goose
  model: openrouter/minimax/minimax-m2.5
  prompt_template_path: v21/prompts/system.j2

  config:
    max_turns: 40

environment:
  timeout_per_task: 480
```

---

## File 2: v21/prompts/system.j2

```jinja2
You are a Treasury Data Analyst. Answer the question using local files only.

/app/resources/ contains bulletin files. Start with *_page_*.txt files (small,
answer table inside). Fall back to full .txt for broader searches.

Use python3 -c for ALL arithmetic. Never do mental math.
Trust ONLY values from /app/resources/ files — not your memory.

CRITICAL: Write your best answer to /app/answer.txt immediately once you have
a reasonable estimate. A wrong answer beats no answer.

KEY RULES:
- "(123)" means negative 123. Strip footnote markers (r/, p/, 3/).
- Check table headers for "(in millions)" vs "(in thousands)".
- FISCAL vs CALENDAR: FY pre-1977 = Jul–Jun. FY post-1977 = Oct–Sep. CY = Jan–Dec.
- Bulletin year ≠ data year. A 1941 bulletin often reports 1940 data.
- Match the EXACT row label asked. "National defense" ≠ "Total national security".
  Check section headers — "Individual income taxes" under "Receipts" ≠ under "Refunds".
- Read columns carefully: count from header, don't assume alignment.
- Percentages: write 15.3 not 0.153. Range = max minus min (single number).
- Multiple values: [x, y] format. Plain number only. No units, no $, no commas.

BEFORE COMPUTING: Verify extraction
- Is this the right row? Re-read the label in the file. "Total" ≠ the specific line item.
  Scroll up to confirm the section header matches the question.
- Did I get the right column/year? Count columns from the header row.
- Units correct? Check table header: millions, billions, thousands, percent.
- All values? (12 for monthly, 2 for year-over-year, etc.)
- Parentheses = negative: "(123)" = -123.
- Did I check the right fiscal year? Pre-1977: Jul–Jun. Post-1977: Oct–Sep.

AFTER COMPUTING:
- Does magnitude make sense? Federal budgets in billions, not millions.
- Is the sign correct? Deficits are negative.
- Did I use the right formula? pct_change = (new−old)/old*100, NOT (new−old)/new*100.
  CAGR = (end/start)**(1/years)−1. Stdev uses statistics.stdev([...]).

MATH (python3 -c): pct_change=((new-old)/old)*100 | CAGR=(end/start)**(1/n)-1

FORMAT: echo -n "VALUE" > /app/answer.txt

{{ instruction }}
```

---

## Setup Instructions

### Create the directory structure
```bash
cd /Users/jwalinshah/projects/officeqa-arena

mkdir -p v21/prompts

# Copy or create arena.yaml
cat > v21/arena.yaml << 'EOF'
name: officeqa-v21
version: 21.0.0
competition: grounded-reasoning

agent:
  type: harness
  harness_name: goose
  model: openrouter/minimax/minimax-m2.5
  prompt_template_path: v21/prompts/system.j2

  config:
    max_turns: 40

environment:
  timeout_per_task: 480
EOF

# Copy or create system.j2 (use the prompt above)
cat > v21/prompts/system.j2 << 'EOF'
[paste the full system.j2 prompt above]
EOF

# Verify files exist
ls -la v21/arena.yaml v21/prompts/system.j2
```

---

## Local Test

### Run on 40-task sample (matches v5/v20 test set)
```bash
# Using run_local_v7.sh (assumes it's in the repo)
python3 run_local_v7.sh v21 --max-turns 40 --uids 1-40

# Expected output:
# Pass: 28-30 tasks (70-75%)
# Fail: 3-5 tasks
# NoAnswer: 7-9 tasks
```

### Interpret results
- **28-30 passes:** Good! Verification is working. Proceed to submit.
- **27 passes:** Break-even with v20. Marginal risk; you could submit or play it safe.
- **26 or fewer:** Inline checks are too noisy. Revert to v20 or v5.

### Check reasoning traces
```bash
# Verify inline verification is happening
grep -r "right row\|count from header\|section header" traces/v21/ | wc -l

# Should show 30-40 matches (roughly one per task, varies)
# If 0 matches: MiniMax is ignoring the checklist

# Check no-answer rate
python3 -c "
import json
tasks = [f for f in os.listdir('traces/v21') if f.endswith('.json')]
no_answer = sum(1 for t in tasks if json.load(open(f'traces/v21/{t}'))['status'] == 'no_answer')
print(f'No-answer rate: {no_answer}/{len(tasks)} = {no_answer/len(tasks)*100:.1f}%')
"

# Should be ~2-3/40 (5-7.5%), same as v20
# If >10/40: verification is causing loops, too expensive
```

---

## Arena Submission

### Before submitting, double-check
```bash
# 1. Files exist
ls -la v21/arena.yaml v21/prompts/system.j2

# 2. No extra files in v21/
ls v21/
# Should only show: arena.yaml, prompts/

# 3. arena.yaml syntax is valid
python3 -c "import yaml; yaml.safe_load(open('v21/arena.yaml'))" && echo "Valid"

# 4. Prompt is readable
head -20 v21/prompts/system.j2
```

### Submit
```bash
arena submit v21 \
  --competition grounded-reasoning \
  --timeout 480

# Returns submission ID — save this
# Format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### Monitor (in arena dashboard)
- First traces appear within 5-10 minutes
- First batch (50 traces) completes in ~1 hour
- Full 246 traces complete in ~2-4 hours
- Score updates as traces complete

---

## Expected Scores

| Benchmark | Score | Progress |
|---|---|---|
| v20 baseline | 183.8 | Starting point |
| Conservative estimate | 195 | +11 points (25 wrong-answer fixes) |
| Expected | 205 | +21 points (35 wrong-answer fixes) |
| Optimistic | 215 | +31 points (40 wrong-answer fixes) |

**With grading noise variance:** ±10 points

So:
- **Best case:** 215-225 (if everything works perfectly)
- **Expected case:** 195-215 (most likely outcome)
- **Worst case:** 175-185 (if verification backfires badly)

The local test (40-task sample) will give you a preview. If you get 28-30/40 (70-75%), you're in the "expected" range for the full submission.

---

## Fallback Plans

### If arena score 190-200 (marginal improvement)
- Verification is working, but only partially
- You could either:
  - Keep it (still beats v20 by ~7-10 points)
  - Revert to v20 and try a different approach

### If arena score 180-190 (worse than expected)
- Inline checks might be too noisy or MiniMax is ignoring them
- Revert to v20 for next attempt

### If arena score < 180 (regression)
- Something went wrong
- Immediately revert to v20 (score ~184)

---

## Code Diff: What Changed from v20

If comparing to v20/prompts/system.j2:

**Added:**
- Lines 13-14: "Check section headers — "Individual income taxes" under "Receipts" ≠ under "Refunds"."
- Lines 15: "Read columns carefully: count from header, don't assume alignment."
- Lines 19-25: Full "BEFORE COMPUTING" checklist
- Lines 27-31: Full "AFTER COMPUTING" checklist

**Removed:**
- None (this is additive from v5 + v20 base)

**Net change:** +42 lines (v20 had ~5 lines of core instruction, v21 has ~42)

---

## Why This Specific Design

**Combines three proven approaches:**

1. **v5's prompt philosophy** (30 lines, permissive, page-first)
   - Why: 184.5 score, highest baseline
   - How: Keep the core structure and tone

2. **v20's execution path** (12.5 steps, minimal overhead)
   - Why: Fast, minimal no-answer failures (only 2)
   - How: Don't add complexity; verification is just thinking

3. **v15's verification logic** (50% fix rate on wrong answers)
   - Why: Targets the bottleneck (68% of v20 failures are extraction errors)
   - How: Inline the checklist instead of using skills (zero turn cost)

**Result:** v5's foundation + v20's speed + v15's verification = 205+ expected score

---

## Decision

You now have three options:

| Option | Action | Expected Score |
|---|---|---|
| **Conservative** | Submit v20 again | 183.8 (safe) |
| **Recommended** | Test v21 locally, then submit if ≥28/40 | 195-215 (high leverage) |
| **Aggressive** | Submit v21 directly without local test | 195-215 (higher risk) |

---

## What to Tell Others

"We identified that v20's 73 wrong-answer failures are mostly extraction errors (wrong row/column). v15 proved that a verification checklist flips 50% of these. We're inlining v15's checklist into v5's prompt to get the benefits of both without v15's turn overhead. Expected improvement: 10-30 points (score 195-215)."

---

## Files Ready to Copy

All four documents have been created in `/Users/jwalinshah/projects/officeqa-arena/`:

1. `OPTIMAL_COMBINATION_ANALYSIS.md` — Full strategic analysis
2. `IMPLEMENTATION_GUIDE.md` — Step-by-step setup
3. `VERIFICATION_EXAMPLES.md` — Real failure cases and how v21 catches them
4. `RECOMMENDATION_SUMMARY.md` — Decision framework
5. `v21_READY_TO_SUBMIT.md` — This file (exact files to submit)

These are your reference materials for:
- Understanding why this design works
- Testing locally before submitting
- Monitoring arena results
- Deciding on fallback strategies
- Explaining the approach to others

---

## Next Step

1. Read `RECOMMENDATION_SUMMARY.md` if you want the strategic overview
2. Use `IMPLEMENTATION_GUIDE.md` to set up and test locally
3. Follow the "Arena Submission" section above to submit
4. Monitor the dashboard and compare to v20's 183.8 baseline

Good luck!

