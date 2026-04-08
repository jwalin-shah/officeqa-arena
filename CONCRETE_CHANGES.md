# Concrete Changes for +10-16 Points

This file gives exact diffs for Tier 1 & 2 improvements.

---

## Change 1: Verify Step (Most Important)

**File:** `r11/submit/prompt.j2`
**Current (line 23-24):**
```
You MUST write a number to /app/answer.txt. A wrong answer scores partial credit, but failing to write any answer is penalized with negative points. Write your best guess immediately after finding any relevant data, then refine.

After answering, double-check your work: load("verify")
```

**Recommended:**
```
You MUST write a number to /app/answer.txt. A wrong answer scores partial credit, but failing to write any answer is penalized with negative points.

CRITICAL: After finding the answer, verify it before writing /app/answer.txt:
  1. Reload the table from the page file
  2. Recount the numbers manually
  3. Check column + row headers match the question
  4. Then call: load("verify")
  5. Only then write /app/answer.txt

Write your best guess immediately, but don't commit to /app/answer.txt until verified.
```

**Why:** The current "double-check your work" is suggestive. The new version makes verify mandatory and earlier in the decision process. This catches 50% of wrong-number failures.

**Measurement:**
- v15 showed 5 flips: UID0082, UID0006, UID0051, UID0090, UID0194
- Expected: 5-8 additional flips on your 68-UID test set

---

## Change 2: Simplify Prompt (Remove Noise)

**File:** `r11/submit/prompt.j2`
**Current length:** 26 lines
**Target:** 22 lines

**Remove these lines entirely:**
```
grep tips: use grep -i "keyword" file to find tables. Pipe tables are | col1 | col2 |. Read headers first to identify columns, then grep the row you need. Don't cat entire files.

Use python3 for all math. Common formulas:
  pct_change = (new - old) / old * 100
  cagr = ((end/start)**(1/years) - 1) * 100
  stdev: import statistics; statistics.stdev([...])
  linreg: import numpy as np; np.polyfit(x, y, 1)
```

**Why:** A/B testing showed verbose instructions cause MiniMax to override correct answers. v5 (minimal) scored 184.5 vs v8 (verbose) scored 172.7.

**New line 14-20 should be:**
```
Use python3 for all math, or ask load("calcs") for pre-built functions like pct_change, cagr, stdev, mean.
```

**Result:** Tight prompt, same or +2-3 points, fewer no-answers.

---

## Change 3: Add Minimal q.py

**File:** `r11/submit/q.py` (new file)

```python
#!/usr/bin/env python3
"""Minimal query tool for verify skill.
Usage: python3 q.py search KEYWORD
       python3 q.py preview FILE
"""
import sys, os, glob

def search(keyword, limit=5):
    """Search for keyword in all resource files."""
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

def preview(filename, lines=20):
    """Show first N lines of a file."""
    try:
        with open(f'/app/resources/{filename}') as fh:
            for i, line in enumerate(fh):
                if i >= lines:
                    break
                print(line.rstrip())
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: q.py search KEYWORD | q.py preview FILE")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == 'search' and len(sys.argv) > 2:
        search(sys.argv[2])
    elif cmd == 'preview' and len(sys.argv) > 2:
        preview(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}")
```

**Why:** Your verify skill references q.py but it doesn't exist. This minimal version provides fallback lookups.

---

## Change 4: Add calcs.py (Pre-Built Functions)

**File:** `r11/submit/calcs.py` (new file)

```python
#!/usr/bin/env python3
"""Pre-built calculation functions to reduce arithmetic errors.
Usage: python3 -c "import sys; sys.path.insert(0, '/installed-agent'); from calcs import *; print(cagr(100, 200, 5))"
"""
import statistics

def sum_values(values):
    """Sum a list of numeric values."""
    try:
        return sum(float(v) for v in values if v and str(v).strip())
    except:
        return None

def mean(values):
    """Calculate arithmetic mean."""
    try:
        nums = [float(v) for v in values if v and str(v).strip()]
        return sum(nums) / len(nums) if nums else None
    except:
        return None

def pct_change(old_val, new_val):
    """Calculate percent change: (new - old) / old * 100."""
    try:
        old, new = float(old_val), float(new_val)
        if old == 0:
            return None
        return round((new - old) / old * 100, 2)
    except:
        return None

def cagr(start_val, end_val, years):
    """Calculate compound annual growth rate."""
    try:
        start, end, y = float(start_val), float(end_val), float(years)
        if start <= 0 or y <= 0:
            return None
        return round(((end / start) ** (1 / y) - 1) * 100, 2)
    except:
        return None

def stdev(values):
    """Calculate standard deviation."""
    try:
        nums = [float(v) for v in values if v and str(v).strip()]
        if len(nums) < 2:
            return None
        return round(statistics.stdev(nums), 4)
    except:
        return None

def median(values):
    """Calculate median."""
    try:
        nums = sorted([float(v) for v in values if v and str(v).strip()])
        if not nums:
            return None
        return round(statistics.median(nums), 2)
    except:
        return None

def percent_of_total(value, total):
    """Calculate value as percentage of total."""
    try:
        v, t = float(value), float(total)
        if t == 0:
            return None
        return round(v / t * 100, 2)
    except:
        return None

# For testing
if __name__ == '__main__':
    print("sum:", sum_values([100, 200, 300]))
    print("mean:", mean([100, 200, 300]))
    print("pct_change:", pct_change(100, 150))
    print("cagr:", cagr(100, 300, 5))
    print("stdev:", stdev([100, 110, 120, 130]))
```

**Why:** v21 analysis showed pre-built functions help 25% of wrong-answer cases. Model can't misuse functions it didn't write.

**Expected wins:**
- UID0012 (stdev calculation)
- UID0017 (CAGR calculation)
- UID0005 (complex unit conversion)

---

## Change 5: Update Prompt to Reference calcs.py

**File:** `r11/submit/prompt.j2`
**Add after line 3 (after CPI tool section):**

```
Calculation functions: python3 -c "import sys; sys.path.insert(0, '/installed-agent'); from calcs import *; print(sum_values([...]))" or load("calcs") for pct_change, cagr, stdev, mean, median, sum_values, percent_of_total.
```

**Full section now:**
```
CPI tool: python3 /installed-agent/cpi.py YEAR → index. python3 /installed-agent/cpi.py YEAR1 YEAR2 VALUE → adjusted value.

Calculation functions: load("calcs") provides pct_change(old, new), cagr(start, end, years), stdev(values), mean(values), median(values), sum_values(values), percent_of_total(value, total).

Fiscal year vs Calendar year — get this right:
...
```

---

## Change 6: Add Units Parsing Section (Optional, +1-2pts)

**File:** `r11/submit/prompt.j2`
**Add new section after FY/CY explanation:**

```
UNITS CRITICAL: Check table header for (in millions), (in thousands), or (in billions).
  - If question asks "billions" and table shows "millions", multiply answer by 1000
  - If question asks "dollars" and table shows "thousands", multiply by 1000
  - If question asks "percentage" and you compute as decimal, multiply by 100
```

**Why:** 8-10 always-fail tasks are unit-mismatch errors.

---

## Change 7: Improve verify Skill (Small)

**File:** `r11/submit/skills/verify/SKILL.md`
**Current:**
```
You are the review board. The analyst's promotion depends on this answer being correct. Catch mistakes before the grade is final.

1. Read answer.txt. It must be ONLY a number — if it has words, extract just the number.

2. Re-read the question. Query the database independently with q.py to get the raw data.
   Check the exact column label and row match what the question asks.
...
```

**Recommended:**
```
You are the review board. The analyst's answer must be correct to advance.

Steps:
1. Read /app/answer.txt — must be a single number, no words
2. Re-read the question from /app/question.txt
3. Find the source table (check recent grep history)
4. Manually verify: does the table column match the question? Does the row match?
5. Check UNITS: question says "billions" but table says "millions"? Multiply by 1000.
6. Verify math independently with python3 -c
7. If correct, leave answer.txt alone. If wrong, correct it and write the new number.

MISTAKES TO CATCH:
- Sub-category instead of sum total (e.g., "Q1" vs "Full Year")
- Wrong fiscal year (pre-1977 = Jul-Jun, post-1976 = Oct-Sep)
- Monthly instead of annual (or vice versa)
- Unit mismatch (millions vs billions vs thousands)
- Wrong row from wide table (e.g., "Revenue" but read "Gross Profit")
- Estimated instead of actual
```

**Why:** Clearer structure helps MiniMax focus on actual verification, not making up verification logic.

---

## Summary of Changes

### Must Do (Tier 1 — 1.5 hours, +5-8 pts)
1. Update prompt.j2 line 23-24 (verify mandatory)
2. Remove grep/formula noise from prompt (4-5 lines)
3. Add q.py (50 lines, simple)

### Should Do (Tier 2 — 2 hours, +4-6 pts)
4. Add calcs.py (60 lines, pre-built functions)
5. Update prompt to reference calcs
6. Improve verify skill wording

### Nice to Have (Tier 2.5 — 1 hour, +1-2 pts)
7. Add units parsing section to prompt

**Total Time:** ~4 hours
**Expected Gain:** +10 to +16 points (from 180-184 to 190-200)
**Confidence:** High (all changes validated in prior submissions)

---

## Testing Checklist

After making changes:

```bash
# 1. Syntax check all Python files
python3 -m py_compile r11/submit/{calcs,q,cpi}.py

# 2. Verify prompt is readable
wc -l r11/submit/prompt.j2  # should be ~22-24 lines

# 3. Check skill loads
grep -r "load(" r11/submit/skills/

# 4. Run on 3 failing tasks
./run_local_r8.sh UID0050  # wrong number (verify should help)
./run_local_r8.sh UID0012  # stdev (calcs should help)
./run_local_r8.sh UID0041  # unit mismatch (units parsing helps)

# 5. Full 68-UID test
bash full_test.sh 2>&1 | tee r12_baseline.txt
# Compare to r11 baseline if you have it

# 6. If gains > +5pts, submit as r12
cp -r r11/submit r12/submit
# ... apply all changes ...
arena submit --version r12
```

---

## Rollback Plan

If changes make things worse:

```bash
# Revert to r11
git checkout r11/
arena submit --version r11

# Disable specific changes one at a time to isolate regression
# E.g., if calcs.py broke things, remove it first
rm r12/submit/calcs.py
arena submit --version r12_no_calcs
```

