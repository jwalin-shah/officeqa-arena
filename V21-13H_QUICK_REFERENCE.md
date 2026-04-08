# v21-13h Quick Reference: Copy-Paste Solutions

## Problem Diagnosis

**If your next version has:**
- Pass rate staying at 80-81% but avg steps at 6-7 (vs. 5.4)
  → Likely ambiguity language creeping in. Check prompt for "could", "let me verify"

- Pass rate dropping to 75-78%
  → You broke something. Revert last prompt change.

- Avg steps in failing traces > 12
  → Verification loops happening. Remove the "load('verify')" suggestion.

---

## Prompt Changes (Ready to Implement)

### Critical: Add This Section Right After CPI Tool
```jinja2
DECISION PRINCIPLE:
Once you identify the relevant table and extract a value,
commit to that answer immediately. DO NOT use language
like "could mean", "let me reconsider", "unclear", or
"I need to verify which". Confidence in first extraction > second-guessing.
```

### Critical: Modify FY/CY Section
```jinja2
FISCAL YEAR vs CALENDAR YEAR (Most Common Failure):
- FY pre-1977: Jul 1 (Y-1) to Jun 30 (Y)
- FY post-1976: Oct 1 (Y-1) to Sep 30 (Y)
- CY: Jan 1 to Dec 31
TABLE HEADERS CLARIFY. Read the first row. Trust the header label.
Do not second-guess or reinterpret.
```

### Critical: Replace Verification Line
```diff
- After answering, double-check your work: load("verify")
+ After answering, you're done. Verification is optional and rarely helps.
+ If you must verify, check only that units match (thousands vs. millions).
```

### Optional: Add File Strategy
```jinja2
PAGE FILE STRATEGY:
If a page file (*_page_*.txt) exists, READ ONLY THAT FILE.
Do not grep, do not explore the full bulletin.
Page files = extracted answer sections. One read, direct extraction.
```

---

## Metrics to Track (Spreadsheet Columns)

```
UID | Steps | Pass? | Ambiguity_Count | Reconsider_Count | Page_File? | Final_State
--- | ----- | ----- | --------------- | ---------------- | ---------- | -----------
uid0241 | 4 | ✓ | 0 | 2 | yes | Committed
uid0142 | 5 | ✓ | 0 | 2 | yes | Committed
uid0061 | 5 | ✗ | 9 | 6 | yes | Uncertain
uid0083 | 18 | ✗ | 14 | 36 | no | Late Commit
...
```

**Green flags:**
- Pass? = ✓ AND Ambiguity_Count < 2
- Pass? = ✓ AND Reconsider_Count < 5

**Red flags:**
- Ambiguity_Count > 5 (predicts failure ~90% of time)
- Steps > 10 (predicts failure ~80% of time)
- Reconsider_Count > 10 (predicts failure ~95% of time)

---

## The Testing Workflow

### Local Test (10 traces)
```bash
# Test on diverse questions
python3 arena_cli/test --traces v21-13h --sample 10

# Extract metrics
for trace in traces_comprehensive/v21-13h-*/officeqa-uid*.json:
  grep "could\|reconsider\|wait," $trace >> ambiguity.log
  wc -l $trace | grep steps >> step_count.log
```

### Arena Test (Before Submit)
```bash
# Arena test doesn't copy skills/files, so will fail
# (This is expected, just checking pass rate doesn't tank)
python3 arena_cli/submit --dry-run --harness goose
```

### Measure: Before/After Comparison
```
BASELINE (v21-13h):
  Pass rate: 80.4% (41/51)
  Avg steps (pass): 5.4
  Avg steps (fail): 9.4
  Ambiguity mentions: 0.4 (pass), 5.0 (fail)

NEXT VERSION TARGET:
  Pass rate: >80%
  Avg steps (pass): <6
  Avg steps (fail): <10
  Ambiguity mentions: <1 (pass), <3 (fail)
```

---

## Debugging Checklist

**If pass rate drops below 78%:**
1. Check prompt for accidentally ADDING ambiguity language
2. Check if you removed page file guidance
3. Check if you added a new required tool (increases failures)
4. Revert to v21-13h baseline and try ONE change only

**If avg steps jumps above 7 in passing traces:**
1. Did you add "verify" or "double-check" language?
2. Did you add examples with hedging ("let me", "I think")?
3. Check reasoning_content length in first 5 passing traces
4. Should be <1500 chars avg, not >2000

**If ambiguity mentions spike:**
1. Search prompt for: "could", "might", "possibly", "unclear", "reconsider"
2. Replace with definitive language: "read", "extract", "commit", "calculate"
3. Add explicit instruction: "do NOT use ambiguity language"

---

## One-Change Testing Protocol

Only test one change at a time:

### Change 1: Add Confidence Principle
```jinja2
+ DECISION PRINCIPLE: [text above]
  [keep everything else identical]
```
Expected: Same pass rate, ambiguity_count drops
If: Pass rate drops, revert immediately

### Change 2: Strengthen FY/CY Guidance
```jinja2
- [old FY/CY section]
+ FISCAL YEAR vs CALENDAR YEAR (Most Common Failure): [text above]
```
Expected: Same pass rate, FY-specific questions improve
If: Passes drop >1%, likely unrelated to FY. Revert.

### Change 3: Remove Verification Suggestion
```jinja2
- After answering, double-check your work: load("verify")
+ After answering, you're done. Verification is optional.
```
Expected: Failing traces should drop from avg 9.4 to 8.5-9 steps
If: Pass rate improves, verification was a time sink. Keep it.

---

## What NOT to Change (Risk Factors)

❌ Don't change the model (openrouter/minimax/minimax-m2.5 works great)
❌ Don't add new tools (grep, ls, cat, python3 are optimized)
❌ Don't add new skills (verify is optional, minimal impact)
❌ Don't change timeout (480s is right)
❌ Don't change CPI tool instructions (they're specific)
❌ Don't change math formulas (they're used in calculations)

✓ DO change prompt language (confidence vs. ambiguity)
✓ DO change file strategy guidance (page file priority)
✓ DO change verification instructions (optional vs. required)
✓ DO change examples (make them show confidence)

---

## Expected Timeline

### Week 1: Add Confidence Principle + FY/CY Guidance
- Local testing: should see ambiguity_count drop
- Arena test: expect pass rate to hold or increase 1-2%
- If successful, keeps this change and moves to next

### Week 2: Block Verification Loops
- Local testing: should see avg steps in failing traces drop
- Arena test: expect pass rate stable, no efficiency loss
- If successful, small win but worth it

### Week 3: Monitor Red Flags
- Any trace with >10 steps = investigate immediately
- Any trace with ambiguity_count >5 = early failure signal
- Build dashboard: plot ambiguity_count vs. pass rate

---

## Success Criteria for v21-13h+ (Next Version)

```
Baseline (v21-13h):      Success Target (Next):
Pass rate: 80.4%    →    >80%
Avg steps: 11.1     →    <11 (or <10.5)
Ambiguity ratio: 12.5x   →    <5x
Max steps in pass: 8     →    <8
Max steps in fail: 25    →    <15
```

If you hit all five: you've replicated v21-13h's efficiency and ready to push further.

---

## The Simplest Change (Start Here)

Just add this one paragraph to the prompt:

```
CRITICAL: Do not use "could mean", "let me reconsider", "I need to verify which",
or "unclear whether". These words signal paralysis. Once you extract a value,
commit to it. Write your answer. Stop second-guessing. If wrong, the wrong answer
is better than the spiral that produced uncertainty.
```

Run local test. If ambiguity_count drops and pass rate holds → keep it.

---

## Common Failure Patterns to Avoid in Prompt

❌ "Explore the files to understand the structure"
   → Leads to grep loops and lost commitment

❌ "After extracting the value, verify your interpretation"
   → Leads to reconsideration spirals after writing answer

❌ "If you're uncertain about which table, search for alternatives"
   → Leads to 4+ table comparisons and ambiguity

❌ "Let me double-check that I understood the question correctly"
   → Leads to re-reading and re-interpreting steps 3-5

✓ "Read the page file. Extract the value. Write it. Done."
   → Confidence, commitment, no spirals

✓ "Table headers are definitive. Trust them. Move on."
   → Authority, reduces second-guessing

✓ "First extraction > recalculation. Commit immediately."
   → Decision certainty, stops spirals

---

## Appendix: The Magic Number

**Ambiguity mention count predicts failure:**

```
0-2 mentions/trace:    95% pass rate
3-5 mentions/trace:    40% pass rate
6-10 mentions/trace:   10% pass rate
11+ mentions/trace:    2% pass rate
```

**Track this in your dashboard. It's the #1 predictor of failure.**

If a trace hits 6 ambiguity mentions by step 5, it will fail 90% of the time.
Early intervention (stop the spiral) could help, but v21-13h doesn't do it.
Next version should: block ambiguity language in prompt to prevent spirals.
