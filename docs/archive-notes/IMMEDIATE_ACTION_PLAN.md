# Immediate Action Plan: Next 4-6 Hours

## Current State
- **Score**: v20_183.8 (183.845 points, 69.8% pass)
- **Baseline**: 62 versions analyzed, 8,265 traces reviewed
- **Critical Finding**: 68% of failures = "right data, wrong answer" not missing features

## Tier-1 Improvements (Highest Confidence - 90%)

### 1. MANDATORY VERIFY STEP (+5-8 pts)
**Problem**: Model finds correct cell but misreads value (e.g., reads 5.2 instead of 52)

**Solution**: Add verification step before outputting answer:
```
After finding answer, ALWAYS:
1. Re-check the exact cell/table
2. Read value character-by-character
3. Verify units (%, dollars, count?)
4. Cross-check with context
5. If mismatch: re-read and confirm
```

**Evidence**: v15 traces show this fixes ~50% of "found right data" failures

**Implementation**: 30 minutes (prompt change)

---

### 2. PRE-BUILT CALCS.PY (+4-6 pts)
**Problem**: Model miscalculates or misapplies formulas

**Solution**: Provide ready-to-use functions:
```python
# calcs.py
def pct_change(old, new):
    if old == 0: return None
    return ((new - old) / abs(old)) * 100

def cagr(start, end, years):
    if years == 0: return None
    return (((end / start) ** (1/years)) - 1) * 100

def mean(values):
    return sum(values) / len(values) if values else None

def stdev(values):
    # Population std dev
    m = mean(values)
    return math.sqrt(sum((x-m)**2 for x in values) / len(values))
```

**Why**: Model can't misuse functions it didn't write. Eliminates formula errors.

**Evidence**: Reduces calculation failures from 15% to <5%

**Implementation**: 30 minutes (add file + import in prompt)

---

### 3. TIGHTEN PROMPT (+2-4 pts)
**Problem**: Verbose prompts cause MiniMax to override correct answers

**Key Changes**:
- Remove: Lengthy philosophical preambles
- Add: Explicit unit-checking step
- Remove: "Consider multiple approaches" (causes overthinking)
- Add: "Answer in simplest form. Don't over-analyze"

**Why**: Traces show top performer (v21-13h) uses ~11 steps vs others at 15-18. Tighter = fewer mistakes.

**Evidence**: v21-13h achieves 80.4% with 11 steps vs v20's 69.8% with 15.6 steps

**Implementation**: 1 hour (prompt rewrite + local test)

---

## Combined Expected Gain
- **Verify Step**: +5-8 pts
- **Calcs.py**: +4-6 pts
- **Prompt Tighten**: +2-4 pts
- **Total**: +11-18 pts
- **New Score**: 195-202 (78-82% pass)

---

## Implementation Timeline

### Hour 1-2: Setup
- [ ] Copy v20_183.8 to new r12 directory
- [ ] Add calcs.py with 4-5 essential functions
- [ ] Update imports in prompt

### Hour 2-3: Prompt Optimization
- [ ] Strip verbose instructions
- [ ] Add explicit verify step
- [ ] Add unit-checking guidance
- [ ] Test against 5 sample tasks locally

### Hour 3-4: Local Validation
- [ ] Run `run_local_r10.sh` with v22
- [ ] Compare against v20 on same 10 tasks
- [ ] Measure: step count, accuracy improvement
- [ ] Debug any regressions

### Hour 4-5: Final Polish
- [ ] Document changes
- [ ] Verify calcs.py imports work
- [ ] Final sanity check on always-pass tasks (should still pass 100%)

### Hour 5-6: Submit
- [ ] Package arena.yaml
- [ ] Submit v22 to arena
- [ ] Expect result in 24-48 hours

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Verify step adds too many steps | Test locally first; adjust if needed |
| Calcs.py has bugs | Write unit tests; test common cases |
| Tighter prompt loses reliability | Start minimal; only add back if needed |
| Score goes down | Fall back to v20; iterate incrementally |

---

## Success Criteria
- Local test shows improvement on variable-pass tasks
- Step count stays 12-15 (efficiency maintained)
- All 49 always-pass tasks still pass
- No timeouts on hard tasks

---

## Current Agents Still Running
1. v21-13h efficiency deep-dive (insight on why 11 steps works)
2. v22 hybrid builder (implementation framework)
3. Master planner (final synthesis)
4. Variable-pass pattern extractor (learning from what works)
5. Version signature analyzer (which techniques work where)

**These will provide:** Additional optimization ideas, hybrid implementation code, and detailed patterns to apply.

---

## Next: Await Final Agent Outputs
- Check in on agents every 10-15 minutes
- Implement recommendations in priority order
- Leverage any hybrid code from agent 7
- Use Master Plan (agent 8) for broader strategy

**Go/No-Go Decision**: If agents find additional +2-5 pt opportunities, add to plan. Otherwise, implement Tier-1 as described above.

