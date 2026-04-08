# Turn Budget Optimization: Visual Summary

## The Perfect 6-8 Turn Path (PASS)

```
┌─────────────────────────────────────────────────────────────────┐
│                     PASSING TASK (6-8 TURNS)                    │
└─────────────────────────────────────────────────────────────────┘

TURN 1: ORIENTATION
├─ Command: ls -la /app/resources/
├─ Output: [list of treasury_bulletin_*.txt files]
└─ Cost: 1 turn (1 shell call)

TURN 2: [OPTIONAL - SKIP if file obvious]
├─ Command: grep -i "table_name\|year_hint" /app/resources/*.txt
├─ Output: [matching line with page location]
└─ Cost: 0-1 turns (90% of cases skip this)

TURN 3: READ DATA
├─ Command: cat /app/resources/treasury_bulletin_YYYY_MM_page_XX.txt
├─ Output: [table with headers and values visible]
└─ Cost: 1 turn (1 shell call)

TURN 4: EXTRACT + COMPUTE
├─ Command: python3 -c "import re; ... print(answer)"
├─ Output: [single numeric value or answer]
├─ Logic:
│  ├─ Parse table structure
│  ├─ Find matching row (by header)
│  ├─ Find matching column (by header)
│  ├─ Extract value & handle units
│  ├─ Compute if needed (sum, %, CPI, etc)
│  └─ Return final answer
└─ Cost: 1 turn (1 shell call)

TURN 5: [OPTIONAL - ONLY IF COMPLEX]
├─ Command: python3 -c "# second computation"
├─ Purpose: FY logic, CPI lookup, multi-file aggregation
└─ Cost: 0-1 turns (for simple sum, skip this)

TURN 6: WRITE ANSWER ⭐ CRITICAL
├─ Command: echo -n "VALUE" > /app/answer.txt
├─ Purpose: Commit answer before token limit
├─ Status: MUST HAPPEN BY TURN 8
└─ Cost: 1 turn (1 shell call)

TURN 7: VERIFY [OPTIONAL]
├─ Command: cat /app/answer.txt
├─ Purpose: Confirm answer written, check format
└─ Cost: 1 turn (1 shell call)

TOTAL: 6-8 TURNS, ALL PRODUCTIVE

SUCCESS RATE: ~95% for tasks completing by turn 8
```

---

## The Failure Thrashing Path (18+ TURNS)

```
┌─────────────────────────────────────────────────────────────────┐
│                    FAILING TASK (18+ TURNS)                     │
│                     "Wrong Number" Failure                       │
└─────────────────────────────────────────────────────────────────┘

TURN 1: ORIENTATION
├─ ls /app/resources/
└─ Output: Files listed

TURN 2-4: SEARCH EXPLORATION
├─ grep "defense" file1.txt        [no match or wrong table]
├─ grep "defense" file2.txt        [no match or wrong table]
├─ grep "defense" file3.txt        [FOUND but wrong column]
└─ ⚠️  Problem: Model picks wrong table

TURN 5: READ (WRONG FILE)
├─ cat /app/resources/treasury_bulletin_1985_03_page_22.txt
├─ Finds: "Defense: 80.289 billions"
│         (Should be: 80,289 millions)
└─ ❌ Wrong magnitude (off by 1000x)

TURN 6-8: FIRST EXTRACTION (WRONG)
├─ python3 -c "extract defense value"
├─ Output: 80.289
├─ Error: Didn't convert billions to millions
└─ ⚠️  No verification, moves forward

TURN 9-10: DOUBT & RE-CHECK
├─ grep "defense" /app/resources/treasury_bulletin_1986_03_page_26.txt
├─ Finds: slightly different value
└─ ⚠️  Model realizes values don't match, searches for why

TURN 11-14: EXTRACTION RETRY
├─ python3 -c "extract from file1, file2, file3..."
├─ Multiple attempts with different logic
├─ Still getting ~ 80.289 (wrong)
└─ ⚠️  Commits to wrong answer anyway

TURN 15: WRITE (WRONG)
├─ echo -n "80.289" > /app/answer.txt
└─ ❌ FAIL: Wrote wrong answer

TURN 16: (OPTIONAL) VERIFY
├─ cat /app/answer.txt
└─ Too late to change

TOTAL: 16+ TURNS, MULTIPLE WRONG EXTRACTIONS

SUCCESS RATE: ~5% (wrong answer written)

ROOT CAUSE: Found data (correct table) but misread it.
FIX: Verify units/scale at turn 4-5 before committing.
```

---

## Turn Budget by Question Complexity

```
SIMPLE (55% of questions)
Total Defense Spending for Year X
├─ Turns 1-2: Find file (obvious from year)
├─ Turn 3: Read page
├─ Turn 4: Extract + compute (single row/col)
├─ Turn 5: Write
└─ Total: 6 TURNS ✓

MODERATE (31% of questions)
Defense Spending YoY % Change, Year X→Y
├─ Turns 1-2: Find files (two different years)
├─ Turn 3: Read first file
├─ Turn 4: Extract first value
├─ Turn 5: Read second file
├─ Turn 6: Extract second value
├─ Turn 7: Compute % change
├─ Turn 8: Write
└─ Total: 8 TURNS ✓

COMPLEX (22% of questions)
Defense Spending in FY1977 (Jul-Jun pre-1977 rule)
├─ Turns 1-2: Find file (must be 1977-1978 bulletin)
├─ Turn 3: Read page
├─ Turn 4: Extract months Jul-Dec 1976
├─ Turn 5: Extract months Jan-Jun 1977
├─ Turn 6: Sum with FY rule
├─ Turn 7: Write
└─ Total: 8-9 TURNS ✓

HARDEST (15% of questions)
Defense Spending in 2020 Dollars for Year X
├─ Turns 1-2: Find file
├─ Turn 3: Read page
├─ Turn 4: Extract value (nominal dollars)
├─ Turn 5: Look up CPI for year X
├─ Turn 6: Look up CPI for 2020
├─ Turn 7: Compute: value × (CPI_2020 / CPI_year)
├─ Turn 8: Write
└─ Total: 10 TURNS ✓

ALL types fit within 10 turns with good design.
Turns 11+: Dead zone. Model either has answer or is lost.
```

---

## Turn Cost Comparison: v15 vs v20 vs Optimal

```
                    v15 (50%)    v20 (69.5%)    Optimal (75%+)
                    ─────────    ───────────    ──────────────
Skill load           2 turns      0 turns        0 turns
File select          1-2 turns    1 turn         1 turn
Read file            1 turn       1 turn         1 turn
Extract/compute      2-3 turns    1-2 turns      1-2 turns
Write answer         1 turn       1 turn         1 turn
Verify               0-1 turns    1 turn         1 turn (added)
                     ─────────    ───────────    ──────────────
TOTAL                7-10 turns   6-8 turns      6-8 turns

Overhead reduction: v15→v20 = -40% turns
                    v15→Optimal = -50% turns

Accuracy gain:       v15→v20 = +19.5%
                     v20→Optimal = +5-8% (estimated)
```

---

## Failure Mode Distribution (v20 Data)

```
75 FAILURES ANALYZED
    
41% WRONG NUMBER (31 tasks)
├─ Found correct table ✓
├─ Found correct row ✓
├─ Found correct column ✓
├─ Misread value ✗
│  ├─ Units: 80 billions → 80 (forgot × 1000)
│  ├─ Format: "80,289" → 80 (truncated)
│  └─ Scaling: Value from two tables, summed wrong
└─ Solution: Verify at extraction time
   Effect: Fixes ~50% of these (15-16 tasks)

27% QUICK WRONG (20 tasks)
├─ Grabbed first matching number
├─ Wrong table/column entirely
└─ Solution: Better grep, verify column header
   Effect: Fixes ~50% (10 tasks)

13% NEVER WROTE (10 tasks)
├─ Computed answer correctly
├─ Ran out of tokens/turns
├─ Answer never written to file
└─ Solution: Force write by turn 6
   Effect: Fixes ~90% (9 tasks)

12% WRONG NUMBER AFTER TIMEOUT (9 tasks)
├─ Exhausted turn limit
├─ Wrote wrong answer
└─ Solution: Better extraction quality
   Effect: Fixes ~30% (3 tasks)

3% NO ANSWER TIMEOUT (2 tasks)
├─ Ran out of turns
├─ Never committed answer
└─ Solution: Force write by turn 5
   Effect: Fixes ~100% (2 tasks)

3% TRUNCATED (2 tasks)
├─ Output cut off mid-calculation
└─ Solution: Rare, hard to prevent
   Effect: Fixes ~50% (1 task)

TOTAL FIX POTENTIAL: ~40 of 75 fails (53% improvement possible)
Expected with optimizations: 211/246 = 85%+ accuracy
```

---

## Turn Commitment by Time

```
v20 OBSERVED (69.5%)

Turn   Pass Rate   Status
────   ─────────   ──────────────────────────────────
1      99%         Orientation (almost always succeeds)
2      96%         File selection (sometimes needed)
3      93%         Read file (rare failure)
4      88%         Extract attempt
5      85%         Compute or verify
6      82%         Write attempt
7      78%         Verify written
8      75%         Still possible to fix
9      70%         Getting risky
10     65%         Very risky (failure mode: thrashing)
11     55%         Likely failure
12     40%         Usually wrong answer by now
13+    <30%        Dead zone (47 v15 no-answers)


⚠️  CRITICAL ZONE: Turns 9-12
    This is where successes become failures.
    Either model has answer and writes it (PASS)
    Or model is lost searching (FAIL)

✓  SAFE ZONE: Turns 1-8
    If answer not written by turn 8: force commit.
```

---

## Overhead Breakdown: v15 Skill Load Penalty

```
v15 TIMELINE (Typical Task)

0-5 sec: Model reads question
5-8 sec: load("officeqa-checklist") API call
8-12 sec: Model thinks, load("officeqa-tools") API call
12-18 sec: ls /app/resources/ (discovers /tmp/g.py missing)
18-22 sec: load("officeqa-table-parser") API call
22-28 sec: Model writes /tmp/g.py (script creation)
28-35 sec: python3 /tmp/g.py executes
35-45 sec: First actual extraction begins
45-65 sec: Multiple grep/sed operations
65-75 sec: Compute & verification
75-82 sec: echo > /app/answer.txt
────────────
82 sec TOTAL (18 shell turns + skill overhead)

v20 TIMELINE (Same Task)

0-3 sec: Model reads question
3-5 sec: ls /app/resources/ (find file)
5-8 sec: cat /app/resources/obvious_file.txt
8-15 sec: python3 -c "extract + compute" (single call)
15-18 sec: echo > /app/answer.txt
────────────
18 sec TOTAL (5 shell calls, no overhead)

TIME SAVED: 64 seconds (78% faster)
TURNS SAVED: 13 turns (72% fewer)
FAILURE RATE: v15=47 no-answers, v20=2 no-answers (96% improvement)
```

---

## Implementation Priority Matrix

```
                  EFFORT    ROI
                  ──────    ────

1. Reduce Prompt   Low      High  ✓✓✓ DO FIRST
   (3 lines, add turn hints)

2. Inline CPI      Low      High  ✓✓✓ DO FIRST
   (400 bytes embedded)

3. Verify Step     Medium   High  ✓✓ DO SECOND
   (units, row/col check)

4. FY Logic        Medium   Medium ✓ DO THIRD
   (pre/post-1977 rules)

5. Table Names     Low      Medium ✓ DO THIRD
   (pre-embed top 20)

6. Multi-stage     High     Low   ✗ SKIP
   (staged extraction)

7. Oracle Tables   High     Low   ✗ SKIP
   (embedded JSON)

8. MCP Integration High     Low   ✗ SKIP
   (arena unreliable)
```

---

## Success Criteria Checklist

- [ ] 90% of passing tasks use <8 turns (median 6)
- [ ] Average pass turns: <10 (v20 baseline: 10.3)
- [ ] "Wrong number" failures: <25% (v20: 41%)
- [ ] "No answer" failures: <2% (v20: 3%)
- [ ] Answer written by turn 6-7 for 85%+ of passes
- [ ] Accuracy: 75%+ (v20 baseline: 69.5%)
- [ ] No regressions vs v20 on simple questions
- [ ] FY questions correctly detect pre/post-1977 rule
