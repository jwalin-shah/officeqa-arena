# v21: Decomposition + Structured Calculation

## Overview

v21 combines three high-ROI improvements to address the 68 failures in v20:

1. **Forced Decomposition** (fixes 20-30 of the 36 "missing number" failures)
   - Model MUST analyze the question first
   - Model MUST identify the metric (sum, mean, percent change, etc.)
   - Model MUST plan steps before executing
   - Model MUST write structured answers

2. **Pre-built Calculations** (fixes 5-8 of the 32 "wrong number" failures)
   - `tools.py` provides correct formula implementations
   - Model can call these instead of computing manually
   - Prevents formula mistakes (mean vs geometric mean, etc.)

3. **Structured Output** (fixes all "incomplete output" cases)
   - Model MUST end with: `FINAL_ANSWER: <value>`
   - MUST write to `/app/answer.txt`
   - No exceptions, no explanations after FINAL_ANSWER

## Expected Improvement

| Failure Type | v20 | v21 | Fix Mechanism |
|---|---|---|---|
| Missing numbers (36) | 36 fail | 8 fail | Forced decomposition + structure |
| Wrong numbers (32) | 32 fail | 26 fail | Pre-built functions + planning |
| **Total** | **68 fail** | **34 fail** | — |
| **Score** | 72.2% | **~77.6%** | +5.4 points |

## Files

- `prompt.j2` — Decomposition-first prompt with 4-step process
- `tools.py` — Calculation functions (sum, mean, pct_change, geom_mean, etc.)
- `calcs.py` — Raw calculation implementations
- `arena.yaml` — Configuration for arena submission
- `test_locally.sh` — Script to test on a few questions

## How It Works

### 4-Step Process

The prompt forces this exact workflow:

```
STEP 1: ANALYZE THE QUESTION
→ Identify metric (sum/mean/pct_change/etc.)
→ Identify time period
→ Identify category
→ Identify conditions

STEP 2: PLAN YOUR WORK
→ Write out exact steps
→ Reference metric from Step 1
→ Describe expected calculation

STEP 3: EXECUTE THE PLAN
→ Run grep/cat to find data
→ Use python3 -c for all math
→ Print intermediate values

STEP 4: WRITE FINAL ANSWER
→ FINAL_ANSWER: <value>
→ Write to /app/answer.txt
```

### Why This Works

**v20's problem:**
```
Model: "I found Defense spending: 35,532..."
Model: [response cuts off or doesn't write answer]
Score: ❌ No answer extracted
```

**v21's approach:**
```
Model: [ANALYSIS: Sum of monthly national defense, 1940, CY]
Model: [PLAN: Grep for 1940, extract Jan-Dec, sum them]
Model: [EXECUTION: grep "1940" → [list] → python3 -c "sum([...])"]
Model: FINAL_ANSWER: 2602
Score: ✓ Answer written, can be scored
```

## Pre-built Calculation Functions

Available in `tools.py`:

```python
# Basic operations
pct_change(old, new)           # ((new-old)/old)*100
cagr(start, end, years)        # (end/start)^(1/n)-1
geometric_mean(values)         # nth root of product
arithmetic_mean(values)        # sum/count
stdev_sample(values)           # sample standard deviation
stdev_population(values)       # population stdev
median(values)                 # middle value
range_val(values)              # max - min
sum_values(values)             # sum

# Utilities
identify_metric(question)      # Returns: sum|mean|pct_change|etc.
identify_time_period(question) # Returns: {years, type, months}
extract_numbers(text)          # Extract all numbers from text
search_and_extract(pattern)    # Search files and extract numbers
verify_answer(question, answer) # Basic sanity check
write_answer(answer)           # Write to /app/answer.txt
```

## Testing Locally

```bash
cd /Users/jwalinshah/projects/officeqa-arena

# Test on a few questions
bash v21/test_locally.sh

# Or run a specific UID
python3 -c "
from arena_sdk import run_single_task
result = run_single_task(
    task_id='officeqa-uid0001',
    prompt_template='v21/prompt.j2',
    model='openrouter/minimax/minimax-m2.5',
    resources_dir='.arena/samples/officeqa-uid0001/resources',
)
print(f'Result: {result}')
"
```

## Key Differences vs v20

| Aspect | v20 | v21 |
|--------|-----|-----|
| Prompt | Simple, direct | Structured, 4-step |
| Analysis | Implicit | **Explicit (STEP 1)** |
| Planning | None | **Required (STEP 2)** |
| Calculations | Model does math | **Pre-built functions** |
| Output | Prose | **Structured: FINAL_ANSWER: X** |
| Completion | Sometimes incomplete | **Always complete** |

## Why Pre-built Functions Matter

Example: "What is the geometric mean?"

**v20 (wrong):**
```
Model: "Find the values... [1, 2, 4, 8]... geometric mean"
Model: "Let me compute: average = (1+2+4+8)/4 = 3.75"
Score: ❌ Wrong (should be 2.828, model computed arithmetic mean)
```

**v21 (correct):**
```
Model: [ANALYSIS: Metric = geom_mean]
Model: [PLAN: Use geometric_mean() function]
Model: [EXECUTION: python3 -c "from calcs import geometric_mean; print(geometric_mean([1,2,4,8]))"]
Output: 2.828...
Score: ✓ Correct
```

## Risks & Mitigations

**Risk:** Model doesn't follow 4-step process
- Mitigation: Prompt is very explicit with clear headers

**Risk:** Pre-built functions aren't available
- Mitigation: Model can still use python3 -c directly (fallback to v20 approach)

**Risk:** Model writes answer but also includes explanation
- Mitigation: Specify "FINAL_ANSWER: X" must be alone on line, write to file

**Risk:** Model uses tools incorrectly
- Mitigation: Simple python functions, not SQL or complex APIs

## Next Steps if v21 ≤ 75%

If v21 doesn't reach expected 77.6%, investigate:

1. **Decomposition working?**
   - Check traces: Does model show STEP 1/2/3/4?
   - If not, prompt needs clearer formatting

2. **Pre-built functions helping?**
   - Check: Do traces show model using tools.py functions?
   - If not, maybe model prefers python3 -c (that's fine)

3. **Output format compliance?**
   - Check: Does FINAL_ANSWER appear in traces?
   - Does /app/answer.txt get written?

4. **Remaining failures:**
   - If still ~32 "wrong numbers": Issue is search/interpretation, not calculation
   - If still ~20 "missing numbers": Prompt isn't forcing completion

## Estimated ROI

| Investment | Expected Gain | Effort |
|---|---|---|
| Decomposition prompt | +5-8% | Low (already done) |
| Pre-built functions | +2-3% | Low (already done) |
| Testing & iteration | +1-2% | Low-Medium |
| **Total** | **+8-13%** → 75-77% | Low |

Much better ROI than SQLite DB approach (+2-4%, high effort).
