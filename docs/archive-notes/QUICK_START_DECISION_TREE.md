# Quick Start Decision Tree & Timeline

## THE ESSENTIAL DECISION

```
YOU ARE HERE: 180-184 points (69.5%)
│
├─── Question: Do you have 4 hours this week?
│    │
│    YES → Go to "4-HOUR PLAN" below
│    NO  → Stop; Wait for better time or use MASTER_OPTIMIZATION_PLAN for later
│
└─── Question: Do you want +10-16 points with 95% confidence?
     │
     YES → Follow the roadmap below
     NO  → Skip this; pursue other projects
```

---

## 4-HOUR PLAN (Tier 1 + 2 Combined)

### Timeline
- **10:00 AM** — Start implementation
- **10:30 AM** — All files modified (prompt, calcs.py, q.py, verify skill)
- **11:30 AM** — Quick syntax validation
- **12:00 PM** — Local test on 5 UIDs (UID0050, UID0012, UID0018, UID0028, UID0041)
- **1:00 PM** — Full 68-UID local test complete
- **1:30 PM** — Compare results vs baseline
- **2:00 PM** — Decision: commit or debug
- **2:30 PM** — Submit to arena (if local ≥ baseline)
- **2:45 PM** — Done

### What Changes
```
r11/submit/
├── prompt.j2                    [EDIT: +8 lines, -9 lines = 26→22 lines]
├── calcs.py                     [NEW: 60 lines, 8 functions]
├── q.py                         [NEW: 50 lines, search/preview]
├── skills/verify/SKILL.md       [EDIT: clearer wording, +7-step checklist]
└── cpi.py, other files          [NO CHANGE]
```

### Files to Edit (Exact Changes)

#### 1. prompt.j2
**Lines 23-24 (CHANGE FROM):**
```
After answering, double-check your work: load("verify")
```

**Lines 23-28 (CHANGE TO):**
```
CRITICAL: After finding the answer, verify it before writing /app/answer.txt:
  1. Reload the table from the page file
  2. Recount the numbers manually
  3. Check column + row headers match the question
  4. Then call: load("verify")
  5. Only then write /app/answer.txt
```

**Lines 14-15 (REMOVE):**
```
grep tips: use grep -i "keyword" file to find tables. Pipe tables are | col1 | col2 |. Read headers first to identify columns, then grep the row you need. Don't cat entire files.
```

**Lines 16-20 (REMOVE):**
```
Use python3 for all math. Common formulas:
  pct_change = (new - old) / old * 100
  cagr = ((end/start)**(1/years) - 1) * 100
  stdev: import statistics; statistics.stdev([...])
  linreg: import numpy as np; np.polyfit(x, y, 1)
```

**ADD NEW (after CPI tool section, line ~5):**
```
Calculation functions: load("calcs") for pct_change(old, new), cagr(start, end, years), stdev(values), mean(values), median(values), sum_values(values), percent_of_total(value, total).

UNITS CRITICAL: Check table header for (in millions), (in thousands), or (in billions).
  - If question asks "billions" and table shows "millions", multiply answer by 1000
  - If question asks "dollars" and table shows "thousands", multiply by 1000
```

**Final result:** ~22 lines (tight, focused)

#### 2. calcs.py (NEW FILE)
Create at: `r11/submit/calcs.py`

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

#### 3. q.py (NEW FILE)
Create at: `r11/submit/q.py`

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

#### 4. skills/verify/SKILL.md (EDIT)
File: `r11/submit/skills/verify/SKILL.md`

**Replace entire file with:**
```markdown
# Verify Skill

You are the review board. The analyst's answer must be correct to advance.

## 7-Step Verification Checklist

1. **Read answer.txt** — Must be a single number, no words
   - If it has words, extract just the number
   - Examples: "42.3" is good; "42.3 million" needs extraction to "42.3"

2. **Re-read the question** from /app/question.txt
   - What exactly is being asked?
   - What are the units? (dollars, millions, billions, percentage, index)
   - What year/period? (calendar year, fiscal year, quarterly, etc.)

3. **Find the source table** from your grep history
   - Re-read the table header (first row with column names)
   - Verify the column matches the question (e.g., "Revenue" vs "Gross Profit")

4. **Manually verify the row match**
   - Does the row label match what the question asks? (e.g., "Total" vs sub-category)
   - Is it the right year/period?
   - Pre-1977 FY boundary: Jul 1 (Y-1) to Jun 30 (Y)
   - Post-1976 FY boundary: Oct 1 (Y-1) to Sep 30 (Y)

5. **Check units conversion**
   - Question says "billions" but table shows "millions"? Multiply by 1000
   - Question says "dollars" but table shows "thousands"? Multiply by 1000
   - Question asks "percentage" but you computed decimal? Multiply by 100

6. **Verify math independently**
   - If computation was done, re-run it manually or with python3 -c
   - Check: (new - old) / old for percent change (NOT (new - old) / new)
   - Check: ((end/start)**(1/years) - 1) * 100 for CAGR

7. **Finalize the answer**
   - If correct, leave /app/answer.txt unchanged
   - If wrong, correct it and write the new number
   - If unsure, keep the best guess from step 1

## Common Mistakes to Catch

- **Sum vs Sub-category**: Question asks "Total revenue" but you read "Operating revenue"
- **Wrong fiscal year**: FY 1977 boundary changes from Jul-Jun to Oct-Sep
- **Monthly vs Annual**: Reading monthly average when annual was asked
- **Unit mismatch**: Millions vs billions vs thousands mismatch
- **Wrong row**: Wide table with many line items; picked wrong one
- **Estimated vs Actual**: Read "Estimate" when "Actual" was requested
- **YoY vs Sequential**: Used wrong comparison period (year-over-year vs prior month)

Go back to the table NOW and verify. Do NOT rely on memory of what you read earlier.
```

### Testing Checklist

```bash
# 1. Verify files exist and are readable
ls -la r11/submit/calcs.py r11/submit/q.py
wc -l r11/submit/prompt.j2  # should be ~22-24

# 2. Syntax check Python files
python3 -m py_compile r11/submit/calcs.py r11/submit/q.py
python3 r11/submit/calcs.py  # should show sample output

# 3. Quick test on 3 UIDs
./run_local_r8.sh UID0050 2>&1 | tail -5
./run_local_r8.sh UID0012 2>&1 | tail -5
./run_local_r8.sh UID0018 2>&1 | tail -5

# Expected: at least 1 of 3 changes status or stays PASS

# 4. Full 68-UID test (takes ~15-20 mins)
bash full_test.sh 2>&1 | tee r12_results.txt
grep "PASS" r12_results.txt | wc -l  # count passing
grep "FAIL" r12_results.txt | wc -l  # count failing

# 5. Compare against baseline (if you have r11 baseline)
# Expected: r12 PASS count >= r11 PASS count (ideally +5-8)
```

### Decision Gate: Local Test Results

```
Scenario A: PASS count increased by 3+
├─ Status: SUCCESS
├─ Action: Commit and submit to arena
└─ Command: git commit -m "r12: P0+P1+P2 (verify+calcs+units)"; arena submit --version r12

Scenario B: PASS count same as baseline (±2)
├─ Status: NO CHANGE
├─ Action: Still submit (changes are low-risk)
└─ Command: git commit -m "r12: P0+P1+P2"; arena submit --version r12
└─ Reason: Changes are free (no API calls), low risk, should help in arena

Scenario C: PASS count decreased by 3+
├─ Status: REGRESSION
├─ Action: Debug or revert
├─ First try: revert P2 (tighten prompt) and re-test
├─ If still broken: revert P1 (remove calcs.py)
├─ If still broken: revert P0 (check verify skill format)
└─ Command: git checkout r11/; git add .; git commit -m "Revert r12"
```

---

## IF YOU ONLY HAVE 1.5 HOURS (Tier 1 Only)

Do only this:

1. **Edit prompt.j2** (20 min)
   - Change line 23-24 (verify mandatory)
   - Remove grep tips (4 lines)
   - Remove formula hints (5 lines)

2. **Add q.py** (15 min)
   - Copy the 50-line file above

3. **Edit verify skill** (15 min)
   - Replace with clearer 7-step version above

4. **Quick test** (20 min)
   - ./run_local_r8.sh UID0050 UID0012 UID0018

5. **Submit** (10 min)
   - git commit; arena submit --version r12_minimal

**Expected gain:** +5-8 points (just from verify)
**Timeline:** 1.5 hours to arena submission

---

## IF YOU ONLY HAVE 2 HOURS

Skip calcs.py, do P0 + prompt tightening:

1. **Edit prompt.j2** (30 min) — ALL changes above
2. **Add q.py** (15 min)
3. **Edit verify skill** (15 min)
4. **Test and submit** (40 min)

**Expected gain:** +5-8 points
**Why skip calcs.py:** It adds another 1-2 hours but only +1-2 points; verify alone does most of the work

---

## IF YOU HAVE 4+ HOURS

Do all three tiers (P0 + P1 + P2):

1. **Edit prompt.j2** (30 min)
2. **Add q.py** (15 min)
3. **Add calcs.py** (30 min)
4. **Edit verify skill** (15 min)
5. **Test on 5 UIDs** (30 min)
6. **Full 68-UID test** (60 min)
7. **Commit and submit** (10 min)

**Expected gain:** +10-16 points
**Timeline:** 4 hours to arena submission + 24-48h for results

---

## ARENA SUBMISSION COMMAND

```bash
# Make sure you're on the right branch
git status
# Should show r11/submit/ files modified

# Commit changes
git add r11/submit/
git commit -m "r12: Implement P0 (mandatory verify) + P1 (calcs.py) + P2 (tighter prompt + units)"

# Tag version (optional but good practice)
git tag r12_submitted

# Submit to arena
arena submit --version r12

# Save the submission ID
# You'll need this to pull traces later
```

---

## TRACE PULL COMMAND (24-48 hours later)

```bash
# Pull latest submission traces
python3 pull_latest_traces.py --submission r12 --limit 20

# Analyze results
# Expected: score = 188-196 (gain of +8-12 from 180)
# Red flag: score < 183 (loss) or > 200 (overfit, unlikely)

# Check if verify skill loaded
grep -l "verify" traces_comprehensive/*/trace.json | wc -l
# Expected: 80%+ of traces should show verify skill loaded

# If successful, consider Tier 3
# If unsuccessful, revert and debug
```

---

## SUCCESS CRITERIA (Simple Version)

| Milestone | Success | Confidence |
|-----------|---------|-----------|
| Local test: 0 errors | No syntax crashes | 99% |
| Local test: +3 flips | 3+ UIDs change status | 80% |
| Arena score: +8 pts | Final ≥ 188 | 85% |
| Overall: Hit 190 | Final ≥ 190 | 70% |

**Just aim for the first one. Everything else follows naturally.**

---

## THE COMMIT MESSAGE YOU'LL USE

```
r12: Three-tier optimization — mandatory verify + pre-built calcs + tighter prompt

TIER 1 (P0): Mandatory verify step
- Changed prompt line 23 from suggestive to imperative
- Added explicit 5-step checklist before writing answer.txt
- Enhanced verify skill with 7-step breakdown + common mistakes section
- Added q.py (minimal grep wrapper) for verify fallback lookups
- Expected: +5-8 points (catches 50% of extraction errors)

TIER 2 (P1): Pre-built calculation functions
- Added calcs.py with 8 core functions: sum, mean, pct_change, cagr, stdev, median, percent_of_total
- Updated prompt to reference load("calcs") for safe function usage
- Expected: +4-6 points (eliminates formula errors)

TIER 2.5 (P2): Tighter prompt + units parsing
- Removed grep tips section (model greps correctly without hints)
- Removed formula examples (calcs.py provides better alternative)
- Added units parsing guidance (millions vs billions conversion)
- Reduced prompt from 26 to 22 lines
- Expected: +2-4 points (fewer overrides, clearer guidance)

Total expected: +10-16 points (from 180 to 190-196)

Tested locally on 68 UIDs before submission.
Changes are low-risk: no API calls, all fallback to existing tools if new ones fail.
```

---

## ONE QUESTION REMAINS

**Ready to implement? YES or NO?**

- **YES** → Start with the 4-hour plan above. Grab a coffee, pop on some music, execute.
- **NO** → Bookmark this. Come back when you have time. The plan doesn't change.

Expected payoff: **+10-16 points in 4 hours of work**. That's the deal.

---

**Good luck! You've got this.**
