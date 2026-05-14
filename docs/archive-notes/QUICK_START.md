# Quick Start: 4-Hour Path to +10 Points

**Timeline:** Today (4 hours) → Local test (2 hours) → Arena submit (24-48h wait)
**Expected result:** 190-195 points (77-79%)
**Difficulty:** Low (copy-paste changes, no algorithm changes)

---

## Before You Start

Check you have these files:
```bash
ls -la r11/submit/
# Should show: arena.yaml, cpi.py, prompt.j2, skills/verify/SKILL.md
```

---

## Step 1: Add calcs.py (20 minutes)

Copy this exact code:

```python
#!/usr/bin/env python3
"""Pre-built calculation functions."""
import statistics

def sum_values(values):
    try:
        return sum(float(v) for v in values if v and str(v).strip())
    except:
        return None

def mean(values):
    try:
        nums = [float(v) for v in values if v and str(v).strip()]
        return sum(nums) / len(nums) if nums else None
    except:
        return None

def pct_change(old_val, new_val):
    try:
        old, new = float(old_val), float(new_val)
        if old == 0:
            return None
        return round((new - old) / old * 100, 2)
    except:
        return None

def cagr(start_val, end_val, years):
    try:
        start, end, y = float(start_val), float(end_val), float(years)
        if start <= 0 or y <= 0:
            return None
        return round(((end / start) ** (1 / y) - 1) * 100, 2)
    except:
        return None

def stdev(values):
    try:
        nums = [float(v) for v in values if v and str(v).strip()]
        if len(nums) < 2:
            return None
        return round(statistics.stdev(nums), 4)
    except:
        return None

def median(values):
    try:
        nums = sorted([float(v) for v in values if v and str(v).strip()])
        if not nums:
            return None
        return round(statistics.median(nums), 2)
    except:
        return None

def percent_of_total(value, total):
    try:
        v, t = float(value), float(total)
        if t == 0:
            return None
        return round(v / t * 100, 2)
    except:
        return None

if __name__ == '__main__':
    print("Functions loaded:", list(dir()))
```

Save as: `r11/submit/calcs.py`

**Verify:**
```bash
python3 -c "from r11.submit.calcs import *; print(pct_change(100, 150))"
# Should print: 50.0
```

---

## Step 2: Add q.py (15 minutes)

Copy this exact code:

```python
#!/usr/bin/env python3
"""Minimal query tool for verify skill."""
import sys, os, glob

def search(keyword, limit=5):
    files = sorted(glob.glob('/app/resources/*.txt'))
    found = 0
    for f in files:
        if found >= limit:
            break
        try:
            with open(f) as fh:
                for line in fh:
                    if keyword.lower() in line.lower():
                        print(f"{os.path.basename(f)}: {line.strip()}")
                        found += 1
                        if found >= limit:
                            break
        except:
            pass

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: q.py search KEYWORD")
        sys.exit(1)
    if sys.argv[1] == 'search':
        search(sys.argv[2] if len(sys.argv) > 2 else "")
```

Save as: `r11/submit/q.py`

---

## Step 3: Update prompt.j2 (20 minutes)

Open `r11/submit/prompt.j2`. It currently has 26 lines.

**Delete these lines (they cause MiniMax to override correct answers):**
```
grep tips: use grep -i "keyword" file to find tables. Pipe tables are | col1 | col2 |. Read headers first to identify columns, then grep the row you need. Don't cat entire files.

Use python3 for all math. Common formulas:
  pct_change = (new - old) / old * 100
  cagr = ((end/start)**(1/years) - 1) * 100
  stdev: import statistics; statistics.stdev([...])
  linreg: import numpy as np; np.polyfit(x, y, 1)
```

**Replace line 23-24 (the verify line) from:**
```
After answering, double-check your work: load("verify")
```

**To:**
```
VERIFY STEP (mandatory before /app/answer.txt):
  1. You found a number. Stop and verify it.
  2. Re-read the question and the table independently.
  3. Confirm: does the table column match the question? Does the row match?
  4. Check units: if table says "(in millions)" but question asks "billions", multiply by 1000.
  5. Call load("verify") to have another reviewer check your work.
  6. Only then write /app/answer.txt if correct.

Calculation functions: load("calcs") provides sum_values, mean, pct_change, cagr, stdev, median.
```

**Add after line 12 (after "(in millions)" explanation):**
```
UNITS CRITICAL: Check table header for (in millions), (in thousands), or percentage.
  - If question asks "billions" and table shows "millions", multiply by 1000
  - If question asks "dollars" and table shows "thousands", multiply by 1000
  - If question asks "percentage" and you compute as decimal, multiply by 100
```

**Result:** Prompt should now be ~24 lines (vs 26 before).

---

## Step 4: Update verify skill (10 minutes)

Open `r11/submit/skills/verify/SKILL.md`. Replace the entire content with:

```markdown
---
name: verify
description: Review board — verify the analyst's answer before final submission
---

You are the review board. The analyst's answer must be correct.

Steps:
1. Read /app/answer.txt — should be a single number, no words
2. Re-read the question from /app/question.txt
3. Find the source table (check recent grep history)
4. Manually verify: does the table column match the question? Does the row match?
5. Check UNITS: question says "billions" but table says "millions"? Multiply by 1000.
6. Verify math independently with python3 -c
7. If correct, leave answer.txt alone
8. If wrong, correct it and write the new number

MISTAKES TO CATCH:
- Sub-category instead of sum total (e.g., "Q1" vs "Full Year")
- Wrong fiscal year boundary (pre-1977 = Jul-Jun, post-1976 = Oct-Sep)
- Monthly instead of annual
- Unit mismatch (millions vs billions)
- Wrong row from wide table
```

---

## Step 5: Quick Tests (20 minutes)

Run on 3 failing tasks to verify changes don't break anything:

```bash
# Test 1: Verify loads without error
cd /Users/jwalinshah/projects/officeqa-arena
./run_local_r8.sh UID0001

# Should see: "load('verify')" in trace (but might skip it on easy task)
# Should see: /app/answer.txt written with a number

# Test 2: Harder task that previously failed
./run_local_r8.sh UID0050
# Expected: Might improve due to verify + units section

# Test 3: Formula task
./run_local_r8.sh UID0090
# Expected: Might improve due to calcs.py being available
```

If all 3 run without errors, proceed.

---

## Step 6: Full Local Test (120 minutes)

```bash
# If you have a baseline from r11
for uid in {1..68}; do
  ./run_local_r8.sh UID000$uid 2>/dev/null
done | tee r12_local.txt

# Count passes
grep "PASS" r12_local.txt | wc -l
# Expected: 48-55 passes (out of 68, or 71-81%)

# If baseline exists from r11, compare
# diff <(grep "PASS" r11_local.txt | sort) <(grep "PASS" r12_local.txt | sort)
```

**Success criteria:**
- No crashes or errors
- PASS count ≥ baseline - 2 (allow 2 task variance)
- Ideally PASS count ≥ baseline + 3 (expect +5% gain on local)

---

## Step 7: Package & Submit (30 minutes)

```bash
# Create r12 directory
mkdir -p r12/submit
cp r11/submit/{arena.yaml,cpi.py,calcs.py,q.py,prompt.j2} r12/submit/
cp -r r11/submit/skills r12/submit/

# Verify structure
ls r12/submit/
# Should show: arena.yaml, cpi.py, calcs.py, q.py, prompt.j2, skills/

# Test local one more time with new structure
./run_local_r8.sh UID0001

# Submit to arena
cd r12/submit
arena submit --version r12

# Wait for confirmation message
# Expected: "Submitted version r12, job ID: xxxxx-xxxx-xxxx-xxxx"
```

---

## Step 8: Monitor Results (Async, over 24-48 hours)

```bash
# Check results after ~24 hours
python3 pull_latest_traces.py --version r12

# Extract score
grep "score.*:" traces/r12/summary.json

# Compare to r11 (180-184)
# Expected r12: 188-195
# If < 185: Something regressed, debug using FAILURE_ANALYSIS.md
# If >= 188: Success! Tier 1 worked as predicted
```

---

## If Something Goes Wrong

### Crash during submission
```bash
# Revert to r11
git checkout r11/
arena submit --version r11_revert
```

### Local tests regress > 5%
```bash
# Identify which change broke it
# Option 1: Remove calcs.py (keep verify)
rm r12/submit/calcs.py

# Option 2: Revert prompt to r11 version
git show r11:r11/submit/prompt.j2 > r12/submit/prompt.j2

# Option 3: Revert everything
cp -r r11/submit/* r12/submit/
```

### Arena score is < 185
This would be unexpected based on testing. If it happens:
1. Pull full traces: `python3 pull_latest_traces.py --version r12`
2. Check if verify skill is loading: `grep -r "load.*verify" traces/r12/*/trace.json | head -5`
3. Check if calcs.py is imported: `grep "calcs\|pct_change" traces/r12/*/trace.json | head -5`
4. If verify isn't loading, the arena might have cached old skills — rollback and resubmit
5. If calcs.py isn't used, update prompt to mention it earlier

---

## Expected Outcomes

### Conservative Estimate
- Verify step: +3-5 points
- calcs.py: +2-3 points
- Tighter prompt: +0-2 points
- **Total: +5-10 points** → 185-194

### Optimistic Estimate (if everything aligns)
- Verify step: +6-8 points (catches 6+ misreadings)
- calcs.py: +4-6 points (fixes formula errors)
- Tighter prompt: +2-3 points (fewer no-answers)
- Units section: +1-2 points (prevents unit mismatches)
- **Total: +13-19 points** → 193-203

### Most Likely
- **+8-12 points** → 188-196 points (72-80% pass rate)

---

## Timeline

| Time | Task | Duration |
|------|------|----------|
| Now | Add calcs.py | 20m |
| Now | Add q.py | 15m |
| Now | Update prompt.j2 | 20m |
| Now | Update verify skill | 10m |
| 1h later | Run 3 quick tests | 20m |
| 2h later | Full 68-UID local test | 2h |
| 4h later | Package & submit | 30m |
| +24h | Pull and analyze traces | 1h |

**Total effort: 4.5 hours (today) + 2 hours (wait) + 1 hour (analysis) = 7.5 hours**

---

## One Last Thing

If you make these changes and arena score doesn't improve as expected:

1. **Don't panic.** Grading has 12.8% noise (same answer, grade flipped). Small variance is normal.
2. **Check the traces.** Are the skills loading? Are the functions being called?
3. **Revert and try Tier 2 instead.** Maybe decomposition (ANALYZE→PLAN→EXECUTE) helps more than verify for your tasks.
4. **Test a different model** if local testing showed +10pts vs MiniMax.

But based on 200+ prior traces, Tier 1 should work. Good luck!

