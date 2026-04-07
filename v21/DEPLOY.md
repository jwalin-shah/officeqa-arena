# Deploy v21 to Arena

## Quick Start

```bash
cd /Users/jwalinshah/projects/officeqa-arena

# 1. Verify files are in place
ls -la v21/
# Should show: prompt.j2, tools.py, calcs.py, arena.yaml, README.md

# 2. Copy arena.yaml to project root (arena looks there)
cp v21/arena.yaml arena.yaml

# 3. Verify it's correct
cat arena.yaml | head -10

# 4. Submit to arena
arena submit

# 5. Get submission ID from output and track it
# Example: Submission ID: abc123xyz...
```

## What Changed vs v20

| File | v20 | v21 |
|------|-----|-----|
| `prompts/system.j2` | Simple, direct | ← v21 has new: `v21/prompt.j2` |
| Tools | None | ← v21 has: `tools.py`, `calcs.py` |
| Output format | Prose | Structured: `FINAL_ANSWER: X` |
| Process | Direct search+compute | 4-step: Analyze→Plan→Execute→Answer |

## Before Submitting: Test Locally

```bash
# Test that prompt works with a few questions
bash v21/test_locally.sh

# Check that tools.py can be imported
python3 -c "import sys; sys.path.insert(0, 'v21'); from tools import identify_metric; print(identify_metric('What is the sum?'))"
# Should output: sum
```

## Expected Arena Results

After submission (24-48 hours):

```bash
# Check results
arena list-trajectories --submission-id YOUR_ID

# Grade it correctly
python3 score_versions.py

# Look for v21 in output (if traces downloaded)
# Expected: ~75-78% (improvement from v20's 72.2%)
```

## Monitoring

```bash
# While arena is running, check status periodically
arena list-trajectories --submission-id YOUR_ID --limit 10

# Once done, pull traces
arena pull-trajectories --submission-id YOUR_ID --output traces/v21

# Grade it
python3 -c "
from pathlib import Path
import json, csv

# Load gold answers
gold = {}
with open('data/officeqa_full.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        gold[row['uid']] = row['answer']

# Count correct
correct = 0
total = 0
for f in Path('traces/v21').glob('*.json'):
    uid = f.stem.replace('officeqa-', '').upper()
    if uid in gold:
        total += 1
        # Check if answer is in trace (simple heuristic)
        with open(f) as fp:
            trace = json.load(fp)
            # If arena marked it passed, likely correct
            if trace.get('reward', 0) > 0:
                correct += 1

print(f'Quick check: {correct}/{total} passed (arena scoring)')
"
```

## If Something Goes Wrong

**Arena submission fails:**
```bash
# Check arena.yaml syntax
yaml v21/arena.yaml

# Check prompt file exists
cat v21/prompt.j2 | head -5

# Check tools are accessible
python3 -c "import sys; sys.path.insert(0, 'v21'); import tools; print('OK')"
```

**Scores are lower than expected:**
1. Check traces to see if decomposition step is in model's output
2. Check if FINAL_ANSWER appears in responses
3. Check if /app/answer.txt is being written
4. If not, prompt may need adjustment (more explicit headers)

**Scores are similar to v20 (~72%):**
- Decomposition might not be helping (model ignores step format)
- Pre-built functions not being used
- May need to redesign prompt with clearer constraints

## Next Steps

1. **Deploy v21** (this guide)
2. **Wait for arena results** (24-48h)
3. **Analyze traces** using `CORRECT_SCORES.md` method
4. **If v21 ≥ 75%**: Success! Consider submitting to final round
5. **If v21 < 75%**: Iterate on prompt or add more structure

---

## Advanced: Iterating if Needed

If v21 doesn't reach 75%, try these modifications:

### More Explicit Formatting

```diff
STEP 1: ANALYZE THE QUESTION (always do this first)
+ Answer these questions:
+ 1) Is this asking for: [sum/mean/percent_change/other]?
+ 2) Time period: [YYYY-YYYY or specific months]?
+ 3) Category: [department/agency/fund]?
+ 4) Special conditions: [YES/NO, describe if YES]
```

### Forced Function Usage

```diff
STEP 3: EXECUTE THE PLAN
- Use grep/cat to find data
- Use python3 to do ALL arithmetic
+ Python imports available:
+   from calcs import sum_values, pct_change, geometric_mean
+   Use these functions, do NOT compute manually
```

### Stricter Output Format

```diff
STEP 4: WRITE FINAL ANSWER
- Once you have the answer, ALWAYS write to /app/answer.txt
+ STOP HERE. Do NOT explain further.
+ Write EXACTLY this to /app/answer.txt:
+   FINAL_ANSWER: <NUMBER>
+ Example: FINAL_ANSWER: 12345.67
+ Nothing else. No units. No text. Just the number.
```

Resubmit after modifying `v21/prompt.j2` and updating `arena.yaml`.

