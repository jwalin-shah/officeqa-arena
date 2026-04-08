# V22 Testing Plan

## 🎯 Goal

Validate whether **explicit decomposition** helps MiniMax retrieve missing numbers from documents.

## 📊 Hypothesis

- **Problem**: v20 has 36 "missing number" failures — the number IS in the doc, but MiniMax doesn't find it
- **Solution**: Force a 4-step process (Find → Extract → Identify → Calculate) to ensure systematic searching
- **Expected Outcome**: +2-4% improvement (74-76% vs v20's 72.2%)

## 🧪 Test Strategy

### Phase 1: Quick Validation (10 questions, ~10 min)
```bash
./run_local_v22.sh --batch UID0001 UID0003 UID0010 UID0050 UID0100 UID0150 UID0200 UID0245 UID0090 UID0120
```

**Goal**: Confirm v22 works at all, doesn't timeout, writes answers

### Phase 2: Sample Testing (20 questions, ~30 min)
```bash
python3 test_v22_sample.py --sample 20 --parallel 5
```

**Goal**: Get early signal on pass rate (target: >70%)

### Phase 3: Full Batch (245 questions, ~2-3 hours)
```bash
./run_local_v22.sh --parallel UID0001 UID0002 ... UID0245
```

**Goal**: Definitive comparison vs v20's 72.2%

## 📈 Success Criteria

| Scenario | Pass Rate | Decision |
|----------|-----------|----------|
| v22 >>> v20 | >75% | ✅ Submit to arena |
| v22 > v20 | 73-75% | 🟡 Run full batch, then decide |
| v22 ≈ v20 | 71-73% | ❌ Keep v20 or iterate on prompt |
| v22 < v20 | <71% | ❌ Revert, decomposition hurts |

## 🔍 What to Look For

### Good Signs
- Answers written consistently (no "NO ANSWER" errors)
- Quick execution (most <30s per question)
- Improvement on retrieval cases (fewer "missing" failures)

### Bad Signs
- Timeouts (>60s per question)
- Blank answer.txt files
- Worse performance on "found the wrong number" cases
- MiniMax stuck in loops

## 📋 Quick Test Commands

**Single question (debug mode):**
```bash
GOOSE_MAX_TURNS=25 ./run_local_v22.sh UID0001
```

**10-question sample:**
```bash
./run_local_v22.sh --batch UID0001 UID0010 UID0020 UID0030 UID0040 UID0050 UID0100 UID0150 UID0200 UID0245
```

**20 random questions with parallelism:**
```bash
python3 test_v22_sample.py --sample 20 --parallel 5
```

**All UIDs in parallel (if feeling brave):**
```bash
CSV_PATH=/tmp/officeqa_full.csv python3 -c "
import csv
uids = [r['uid'].upper() for r in csv.DictReader(open('/tmp/officeqa_full.csv'))]
import subprocess
subprocess.run(['bash', 'run_local_v22.sh', '--parallel'] + uids, cwd='.')
"
```

## ⏱️ Expected Duration

- Phase 1: 10 min
- Phase 2: 30 min
- Phase 3: 2-3 hours (can run overnight)

## 🚀 After Testing

### If Results Are Good (>74%)
```bash
cp v22/arena.yaml arena.yaml
arena submit
# Wait 24-48 hours for arena results
```

### If Results Are Unclear (72-74%)
1. Review a few failure cases manually
2. Try tweaking prompt slightly
3. Retest on Phase 2 sample
4. Then decide on Phase 3 + arena

### If Results Are Bad (<72%)
1. Revert: `cp v20/arena.yaml arena.yaml` (or use v15 current)
2. Analyze what went wrong (too prescriptive? not enough guidance?)
3. Iterate v23 with different approach

## 📝 Key Metrics to Track

After each run, note:
- **Total Pass**: X/N questions correct
- **Pass Rate**: X%
- **NO ANSWER count**: How many wrote nothing?
- **Timeout count**: How many >60s?
- **Avg time per question**: (total time) / N

## 🎬 Let's Go!

Start with Phase 1 (quick validation):
```bash
./run_local_v22.sh --batch UID0001 UID0003 UID0010 UID0050 UID0100
```

Report results and we'll decide on Phase 2/3.
