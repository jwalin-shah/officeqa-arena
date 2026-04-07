# V22: Decomposition Testing

## What We're Testing

**Hypothesis:** Forcing explicit decomposition will improve retrieval of "missing numbers" — data that's in the document but MiniMax didn't find it.

## Key Changes from V20 (72.2% baseline)

### Prompt Changes
- **Shorter** (30 lines vs v21's 80)
- **Search-focused** (Step 1: "Find the exact metric and time period in files")
- **Fewer prescriptions** (4 clear steps, no decorative formatting)
- **Better retrieval guidance** (Try page files first, then broader search)

### Why This Matters
From v20's trace analysis:
- **36 failures** are missing numbers (number is in doc, but not retrieved)
- **32 failures** are wrong numbers (retrieved wrong calculation)

Decomposition should primarily help with **missing** cases by forcing explicit search logic.

## Expected Results

- **v20 baseline:** 72.2% (177/245 correct)
- **v22 target:** 74-76% (+2-4% improvement from better retrieval)
  - Fixes ~8-12 of the 36 missing-number cases
  - Maintains or improves wrong-number handling

## Testing Locally

### Single Question
```bash
./run_local_v22.sh UID0001
```

### Batch of Questions
```bash
./run_local_v22.sh --batch UID0001 UID0003 UID0005
```

### Parallel Testing (5 at a time)
```bash
./run_local_v22.sh --parallel UID0001 UID0002 UID0003 UID0004 UID0005
```

### Random Sample
```bash
python3 test_v22_sample.py --sample 20 --parallel 5
```

## Files

- `prompt.j2` — Simplified 4-step decomposition prompt
- `tools.py` — Calculation helpers (from v21)
- `calcs.py` — Math implementations
- `arena.yaml` — Arena submission config

## Evaluation Criteria

### ✅ Success
- Local test pass rate > 74% on sample
- Noticeable improvement on "missing number" cases
- No regression on "wrong number" handling

### ❌ Concern Signals
- Pass rate ≤ 72% (same or worse than v20)
- Many "NO ANSWER" outputs (not writing to answer.txt)
- High timeout rate (>10s per question)

## Running Full Batch

To test all 245 questions (takes ~2-3 hours):
```bash
# Get all UIDs
python3 -c "
import csv
uids = []
with open('/tmp/officeqa_full.csv') as f:
    for r in csv.DictReader(f):
        uids.append(r['uid'].upper())
print(' '.join(sorted(uids)))
" > /tmp/all_uids.txt

# Run batch
./run_local_v22.sh --batch $(cat /tmp/all_uids.txt) 2>&1 | tee v22_results.log

# Extract summary
grep -E "^Pass:|^Fail:" v22_results.log
```

## Comparison to V20

V20's prompt was minimal and worked well (72.2%). V22 adds structure but should be light enough not to hurt.

Key risk: Over-prescription might hurt MiniMax's exploration.

## What to Do with Results

1. **If pass rate > 74%**: v22 is an improvement, submit to arena
2. **If pass rate 72-74%**: Marginal, but test on full set before deciding
3. **If pass rate < 72%**: Decomposition hurts, revert to v20 approach

## Notes

- Uses openrouter/minimax/minimax-m2.5 (same as v20/v21)
- max_turns=35 (same as v21)
- Test locally before arena submission
- Full arena run takes 24-48 hours to get results
