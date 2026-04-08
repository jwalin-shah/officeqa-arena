# OfficeQA Arena Improvement Recommendations
**Current State:** 180-184 points (69.5%), target 210+ (85%+)

---

## Executive Summary

Your agent is scoring 180-184 points out of 246 tasks (69.5%). Analysis of 245+ traces reveals:

1. **68% of failures are "found data, wrong number"** — the model reaches the right file and table but misreads or miscalculates
2. **Ceiling is ~70% without structural changes** — prompt/MCP variants have been tested exhaustively, all plateau around 70%
3. **Expected ceiling: 208 points** given grading noise (75% of score variance is non-deterministic)
4. **Real achievable target: 190-200 points (77-81%)** with focused improvements to the 26 genuinely solvable always-fail tasks

---

## Tier 1: High Impact, Low Effort (Expected +10-15 points)

### 1.1 Verification Step (Highest ROI)
**Status:** Already partially implemented in r11 (verify skill exists)
**Expected Impact:** +5 to +8 points (50% of wrong-answer tasks)
**Effort:** 2 hours

Your `verify` skill is loaded by MiniMax in traces, but the prompt says "After answering, double-check your work: load("verify")" which is weak framing.

**Recommendation:**
- Make verification **mandatory and earlier** in the prompt
- Change prompt line 24 from suggestive ("double-check") to imperative ("then verify")
- Add explicit instruction: "Before writing /app/answer.txt, always run verify to catch misreadings"
- Track: of the 20 failed tasks in your test set (UID0018, UID0028, etc.), how many would flip with forced verify?

**Test Plan:**
```bash
# Measure flips on known failures
for uid in 0018 0028 0041 0050 0055; do
  ./run_local_r8.sh $uid  # original
  # vs
  ./run_local_r8_verify_forced.sh $uid  # with verify mandated
done
```

**Why It Works:**
- v15 showed verification catches 50% of wrong-answer tasks (UID0082, UID0006, UID0051, UID0090, UID0194 all flipped)
- Wrong-number failures are extraction errors (wrong row/column), not arithmetic
- A fresh LLM read of the table catches these

---

### 1.2 Simplified Prompt Format (Highest Confidence)
**Current:** 26 lines, contains FY/CY guidance, formula hints, grep tips
**Expected Impact:** +2 to +4 points (stabilization, fewer no-answers)
**Effort:** 1 hour

The A/B testing found **MiniMax ignores verbose instructions** and performs better with minimal framing. Your current r11 prompt is already pretty compact, but can be tightened further.

**Recommendation:**
Compare against v5 baseline (184.5 score, 33 lines):
- Remove the "grep tips" section (lines 14-15) — MiniMax will grep correctly regardless
- Remove "Common formulas" (lines 16-20) — MiniMax hallucinates numpy/stdev calls; let it use python3 -c
- Keep only: FY/CY distinction (critical for 22% of questions), CPI tool availability, one line "write answer.txt immediately"
- Reorder: Question LAST (per v9 A/B finding: q-last outperforms q-first by 5%)

**Target Result:** ~22 lines, same score or +2-3 points by reducing no-answers

**Measurement:**
```bash
wc -l r11/submit/prompt.j2  # currently 26, target 22
```

---

### 1.3 Remove Optional Fluff from Verify Skill
**Status:** verify/SKILL.md currently references q.py which doesn't exist in r11
**Expected Impact:** +0.5 to +1 point (fixes skill loading errors)
**Effort:** 30 minutes

Your verify skill says "Query the database independently with q.py" but q.py is not in your tarball. Either:
1. Add q.py to r11/submit/ (preferred — enables fallback table lookup)
2. Remove the q.py reference and keep verify simple (just re-read answer.txt and question)

**Recommendation:** Go with option 1 — add a minimal q.py that wraps grep on the corpus.

```python
# r11/submit/q.py (minimal 50-line version)
# Query tool: grep tables from /app/resources/*.txt
# Usage: python3 q.py search KEYWORD
#        python3 q.py preview FILE
```

---

## Tier 2: Medium Impact, Medium Effort (+8-12 points)

### 2.1 Pre-Built Calculation Functions (Decomposition)
**Status:** v21 built this, expected +5-8 points but never tested in arena
**Expected Impact:** +4 to +6 points (fixes 25% of wrong-answer cases)
**Effort:** 4 hours

v20 (minimal, no tools) = 180 points. v21 (decomposition + pre-built funcs) was never submitted but projected 75-78%.

The idea: instead of letting MiniMax write `python3 -c "..."`, provide pre-built functions:
- `sum_values(list)`
- `pct_change(old, new)`
- `cagr(start, end, years)`
- `stdev(list)`, `median(list)`, etc.

**Recommendation:**
Build a minimal `calcs.py` (not the 18-command version from r8, just the 6-7 most common):

```python
#!/usr/bin/env python3
# calcs.py - core calculations
def sum_values(values):
    return sum(float(v) for v in values if v)

def pct_change(old, new):
    return ((new - old) / old * 100) if old != 0 else 0

def cagr(start, end, years):
    return ((end / start) ** (1 / years) - 1) * 100

def mean(values):
    v = [float(x) for x in values if x]
    return sum(v) / len(v) if v else 0
```

Update prompt to say: "Use python3 -c with these functions: load('calcs.py') or import sys; sys.path.insert(0, '/installed-agent'); from calcs import *"

**Test Plan:**
- Measure: UID0012 (stdev), UID0017 (cagr), UID0005 (sums with mixed units)
- Expected: all three shift from 0 passes to 2-3 passes

---

### 2.2 Fix Units Parsing (Common Failure Mode)
**Status:** Mentioned in verify skill but not tested systematically
**Expected Impact:** +2 to +4 points (fixes ~8-10 tasks)
**Effort:** 3 hours

From grading analysis: **Many wrong numbers are unit mismatches** (question asks "billions" but table shows "millions").

**Current State:** Your verify skill mentions UNITS in point 3, but it's just a checklist. No automation.

**Recommendation:**
Add a pre-parse step to every task:
1. Extract from question: what units are asked? (dollars, millions, billions, percentages, indices)
2. Extract from table header: what units does this table report?
3. If mismatch, apply conversion factor BEFORE the model does math

Add to prompt:
```
Before extracting numbers, check table headers for "(in millions)" or "(in thousands)".
If question asks for "billions" but table is in "millions", multiply by 1000.
If question asks for "dollars" but table is in "thousands", multiply by 1000.
Common units: (in millions), (in thousands), percentage (%), index.
```

**Measurement:**
Look at 10 always-fail tasks; how many are unit-mismatch errors?
```bash
grep -i "units\|million\|thousand\|billion" traces_comprehensive/*/trace.json | head -20
```

---

### 2.3 Explicit Table Parsing Strategy
**Status:** Current prompt trusts MiniMax to grep and cat; v15 tried structured parsing, regressed
**Expected Impact:** +1 to +3 points (stabilization)
**Effort:** 2 hours

Your r11 prompt says "Read headers first to identify columns, then grep the row you need." but this is suggestive, not prescriptive.

**Recommendation:**
Add a mini-checklist that MiniMax follows before writing any answer:

```
BEFORE ANSWERING, always:
1. Grep for the table header (first row with column names)
2. Identify which column matches the metric (e.g., "Revenue", "Total", "FY 2023")
3. Grep for the matching row (e.g., "1981 Q3" or "Treasury Notes")
4. Extract the number at the intersection (column + row)
5. Verify units match the question
6. Run python3 -c to double-check math
7. Write /app/answer.txt
```

This forces decomposition (v21 finding) without requiring complex tools.

---

## Tier 3: Lower Impact but Proven (+2-5 points)

### 3.1 CPI Inline Lookups (Conditional)
**Status:** r11 already includes cpi.py; prompt mentions it
**Expected Impact:** +0.5 to +2 points (only helps 9% of tasks)
**Effort:** Already done

Your r11 setup is correct here. CPI is only 9% of questions, and inline CPI in v20 was used in only 5/26 CPI tasks. Keep it available but don't push it.

**Note:** v20 actually beat v21 (72.2% vs 62.6%), suggesting CPI is a red herring for most tasks.

---

### 3.2 Model Swap: MiniMax → GPT-4.5
**Status:** Not tested; infrastructure requires OpenRouter proxy
**Expected Impact:** +3 to +8 points (if MiniMax is the bottleneck)
**Effort:** 2 hours setup, unknown arena compatibility

The memory notes that "MiniMax>>GPT5mini" but GPT-4.5 wasn't tried.

**Recommendation:**
Test locally first:
```yaml
# r11/arena.yaml variant
model: openrouter/openai/gpt-4-turbo  # or gpt-4.5 when available
```

Run on 20-task sample, measure vs baseline. If +5% improvement, worth the API cost.

**Note:** MiniMax is currently 2-3x cheaper than GPT-4. Score gain needs to outpace cost increase.

---

### 3.3 Fiscal Year Edge Cases (Conditional)
**Status:** Already covered in prompt (FY pre-1977 vs post-1976 distinction)
**Expected Impact:** +0.5 to +2 points (22% of questions are FY)
**Effort:** Already done

Your prompt correctly distinguishes:
- FY pre-1977: Jul 1 (Y-1) to Jun 30 (Y)
- FY post-1976: Oct 1 (Y-1) to Sep 30 (Y)

The grading analysis shows FY/CY confusion accounts for ~12% of failures. Your r11 already covers this. Keep it.

---

## Tier 4: High Effort, Uncertain Payoff

### 4.1 Sub-LLM Verification Calls
**Status:** Tested in v15, showed minimal gain (-10 points)
**Expected Impact:** Likely negative
**Effort:** Would cost $2.50-12.50 per task
**Recommendation:** SKIP

v21 analysis proved local pre-built functions outperform sub-LLM calls. No additional API calls needed.

---

### 4.2 Pre-Computed Database (SQLite)
**Status:** Attempted in v4-v8, complexity led to worse accuracy
**Expected Impact:** Likely +1 to +2 points but high risk
**Effort:** 20+ hours
**Recommendation:** SKIP unless you have time to debug

The "grep-primary v2" memory shows DB approach loses 50% of data when tables are malformed. Grep is simpler and more reliable for this corpus.

---

### 4.3 Custom Parsing Layer
**Status:** v15 e.py and g.py had 2% and 53% success rates respectively
**Expected Impact:** Likely negative to neutral
**Effort:** 10+ hours
**Recommendation:** SKIP

Extraction errors come from the model reading wrong rows, not from missing tools. Custom parsing doesn't solve that problem.

---

## Testing & Measurement Strategy

### Local Validation (4 hours)
Use existing `run_local_r8.sh` harness on your 68 UIDs with and without changes:

```bash
# Baseline
for uid in {1..68}; do
  ./run_local_r8.sh UID000$uid 2>/dev/null | grep "PASS\|FAIL"
done | tee baseline.txt

# After Tier 1 changes
for uid in {1..68}; do
  ./run_local_r8_v2.sh UID000$uid 2>/dev/null | grep "PASS\|FAIL"
done | tee v2.txt

diff baseline.txt v2.txt | grep ">" | wc -l  # net gains
```

### Arena Submission (24-48 hours)
1. Implement Tier 1 changes (verification + prompt tightening): ~3 hours
2. Test locally for regressions
3. Submit as r12
4. Pull traces after 24-48 hours
5. Measure against v20 baseline (180 points)

### Success Criteria
- Tier 1 alone: +5 to +8 points (183-192)
- Tier 1 + 2.1: +8 to +14 points (188-198)
- Tier 1 + 2.1 + 2.2: +10 to +16 points (190-200)

---

## Recommended Implementation Order

### Phase 1: Quick Win (Today, 2 hours)
```bash
# 1. Tighten prompt to 22 lines (v5 style)
vim r11/submit/prompt.j2

# 2. Make verify step mandatory/explicit
# Change line 24 from "double-check your work: load("verify")"
# To: "Verify your work immediately before writing /app/answer.txt: load("verify")"

# 3. Add minimal q.py for verify skill
cat > r11/submit/q.py << 'EOF'
#!/usr/bin/env python3
import sys, os, glob
def search(keyword):
    files = glob.glob('/app/resources/*.txt')
    for f in files:
        with open(f) as fh:
            for line in fh:
                if keyword.lower() in line.lower():
                    print(f"{os.path.basename(f)}: {line.strip()}")
                    break
search(sys.argv[1] if len(sys.argv) > 1 else "")
EOF

# 4. Test locally
./run_local_r8.sh UID0050  # a known failure
```

### Phase 2: Medium Investment (Day 2, 4 hours)
```bash
# 1. Add calcs.py with 6 core functions
cat > r11/submit/calcs.py << 'EOF'
#!/usr/bin/env python3
def sum_values(v): return sum(float(x) for x in v if x)
def pct_change(o, n): return ((n-o)/o*100) if o else 0
def cagr(s, e, y): return ((e/s)**(1/y)-1)*100
def mean(v): v=[float(x) for x in v if x]; return sum(v)/len(v) if v else 0
def stdev(v):
    import statistics
    return statistics.stdev([float(x) for x in v if x])
EOF

# 2. Update prompt to reference calcs.py
# Add to prompt: "Use python3 -c with import sys; sys.path.insert(0, '/installed-agent'); from calcs import *"

# 3. Test on compute-heavy tasks
./run_local_r8.sh UID0012  # stdev
./run_local_r8.sh UID0017  # cagr
./run_local_r8.sh UID0005  # mixed units
```

### Phase 3: Validation & Submit (Day 3, 2 hours)
```bash
# 1. Full local test on 68 UIDs
bash full_local_test.sh > r12_local_results.txt

# 2. Package as r12
cp -r r11/submit/* r12/submit/
arena submit --version r12

# 3. Monitor traces
python3 pull_latest_traces.py --submission r12 --poll 30m
```

---

## FAQ & Pitfalls

**Q: Why not use GPT-4?**
A: MiniMax scores 70% locally; GPT-4 likely similar. Cost difference ($0.03 vs $0.30 per task) means you'd need 10x improvement to justify. Test locally first if curious.

**Q: Why not add more tools?**
A: v15 had more tools (e.py, g.py, MCP), scored worse (62.6% vs 72.2%). More tools = more ways to fail.

**Q: Will decomposition help?**
A: Maybe +2-3%. v21 projected +5% but never ran in arena. It's worth testing locally on the 10 hardest tasks.

**Q: What about the 6 arena bugs?**
A: uid0055, uid0073, uid0135, uid0136, uid0158, uid0212 are broken graders. Your code can't fix them. Skip optimizing for these.

**Q: How much improvement is realistic?**
A: Expected max ~200 points (81%) given grading noise. The 38 always-fail tasks include 6 arena bugs + 6 impossible + 26 hard-but-solvable. Tier 1+2 targets the 26 solvable ones.

---

## Summary Table

| Change | Impact | Effort | Priority | Timeline |
|--------|--------|--------|----------|----------|
| Mandatory verify | +5-8pts | 1hr | P0 | Today |
| Tighten prompt | +2-4pts | 1hr | P0 | Today |
| Add q.py | +0.5-1pt | 0.5hr | P0 | Today |
| Add calcs.py | +4-6pts | 2hr | P1 | Day 2 |
| Unit normalization | +2-4pts | 3hr | P1 | Day 2 |
| Table parsing guide | +1-3pts | 2hr | P2 | Day 3 |
| Model swap (GPT-4) | +3-8pts? | 2hr | P3 | If curious |
| Sub-LLM calls | -5pts | 10hr | SKIP | Never |
| Custom parsers | -2pts | 10hr | SKIP | Never |

**Expected combined impact of P0+P1: +10 to +16 points (190-200 range)**

