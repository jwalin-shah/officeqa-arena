# v21-13h Efficiency Implementation Checklist

## Quick Summary
**The Secret:** Confidence-first extraction eliminates ambiguity spirals. v21-13h passing traces (5.4 steps) vs. failing traces (9.4 steps) differ by **decision paralysis**, not speed.

---

## Prompt Changes (Critical Path)

### 1. Add Confidence Principle (Top Priority)
```diff
+ DECISION PRINCIPLE:
+ Once you identify the relevant table and extract a value,
+ commit to that answer. Do NOT use language like "could mean",
+ "let me reconsider", "unclear", or "I need to verify which".
+ Confidence in first extraction > second-guessing.
```

**Why:** Failing traces show 5.0 ambiguity mentions vs. 0.4 in passing. This is the biggest lever.

**Measurement:** Track "could", "unclear", "reconsider", "wait," in reasoning. Should be <2 per passing trace.

---

### 2. Page File First (Already in v21-13h, Reinforce)
```diff
+ If a page file (*_page_*.txt) exists, READ ONLY THAT FILE.
+ Do NOT grep, do NOT explore the full bulletin.
+ Page files = extracted answer sections. TXT files = noise.
```

**Why:** All passing traces used page files when available. Failing traces spent 3-4 steps exploring.

**Implementation:** Add to prompt as explicit heuristic, not suggestion.

---

### 3. Block Verification Loops (New)
```diff
+ After writing /app/answer.txt, do NOT recalculate or reinterpret.
+ Verification is OPTIONAL and only for unit-checking (thousands vs. millions).
+ First extraction > second-guessing. If you must verify, use load("verify") skill,
+ but understand that reconsideration after writing rarely improves answers.
```

**Why:** Failing uid0083 spent steps 15-18 verifying an answer already written in step 14.

**Measurement:** Traces with >2 verification steps should flag as "overconfident failure".

---

### 4. FY/CY Guidance (Enhance Current)
```diff
- Fiscal year vs Calendar year — get this right:
+ FISCAL YEAR vs CALENDAR YEAR (Biggest ambiguity source):
  FY pre-1977: Jul 1 (Y-1) to Jun 30 (Y). FY1976 = Jul 1975–Jun 1976.
  FY post-1976: Oct 1 (Y-1) to Sep 30 (Y). FY1981 = Oct 1980–Sep 1981.
  CY: Jan 1 to Dec 31.
+ TABLE HEADERS CLARIFY. Read the header row first. Do not second-guess.
+ Wrong choice: using annual FY total when CY was asked.
+ Right choice: table header labels it "Fiscal" or "Calendar". Trust the header.
```

**Why:** FY/CY confusion appears in multiple failing traces (uid0083, uid0173).

**Measurement:** Count FY/CY questions that fail due to wrong interpretation.

---

### 5. Answer Format (Already Strong, Just Clarify)
```diff
+ You MUST write a number to /app/answer.txt before the last step.
+ A wrong answer is better than no answer (negative points for missing answer).
- After answering, double-check your work: load("verify")
+ After answering, you're done. Verification is optional and rarely helps.
```

**Why:** Current prompt says "after answering, double-check" but this invites reconsideration spirals.

---

## Code/Tool Changes (Optional, Lower Priority)

### 6. Confidence Monitoring (If Building Learning Loop)
```python
# Track per-trace metrics
confidence_score = (
    100 - (ambiguity_mentions * 20)
    - (reconsideration_count * 15)
    - (message_rewrites * 10)
)
# Flag < 30 as "spiral risk"
```

**Why:** Early detection of spiraling traces (uid0083 visible by step 5).

---

### 7. Page File Detection (If Optimizing File Selection)
```python
# Before any reads, check:
if any(f.endswith("_page_*.txt") for f in ls_resources()):
    target_file = [f for f in ls_resources() if "_page_" in f][0]
    read_file_directly(target_file)
else:
    use_grep_strategy()
```

**Why:** Eliminates 1-2 steps of exploration (uid0030 failing because page file missing is OK).

---

## Measurement Targets (For Next Submission)

### Success Criteria
- [ ] Ambiguity language mentions: < 1 per trace (vs. 0.4 passing / 5.0 failing now)
- [ ] Reconsideration count: < 2 per trace (vs. 2.6 passing / 12.4 failing now)
- [ ] Pass rate: > 80% (maintain v21-13h level)
- [ ] Avg steps in passing: < 6 (vs. 5.4 currently)
- [ ] Avg steps in failing: < 10 (vs. 9.4 currently)

### Red Flags
- Any trace with > 10 steps
- Any trace mentioning "could mean" more than once
- Any trace recalculating the same value twice
- Verification step that changes the answer

---

## Testing Checklist

### Unit Test: Confidence Language
- [ ] Prompt contains "do NOT use" + list of ambiguity words
- [ ] No hedging language in examples ("let me check", "I think")
- [ ] Clear consequence: "first extraction > second-guessing"

### Integration Test: Page File Strategy
- [ ] Test on 10 traces WITH page files → should all read page file first
- [ ] Test on 5 traces WITHOUT page files → should fall back to grep/TXT
- [ ] Measure: page file traces should be 1-2 steps shorter

### System Test: FY/CY Parsing
- [ ] Run on 5 FY-specific questions → should parse FY correctly
- [ ] Run on 5 CY-specific questions → should parse CY correctly
- [ ] Measurement: 100% correct interpretation (not 80%)

### Integration Test: Verification Blocking
- [ ] Manual inspection of first 20 passing traces
- [ ] Count post-answer verification steps
- [ ] Should be 0 in almost all cases (optional, rarely triggered)

---

## Prompt Wording Template (Ready to Use)

```jinja2
Treasury data analyst. Files in /app/resources/. Page files (*_page_*.txt) have the answer.

CORE PRINCIPLE:
Confidence in first extraction > reconsideration. Once you identify the relevant
table and extract the value, commit to that answer immediately. Do NOT use language
like "could mean", "let me reconsider", "unclear", or "I need to verify which".
These stall the process and rarely improve accuracy.

PAGE FILE STRATEGY:
If a page file (*_page_*.txt) exists, READ ONLY THAT FILE. Page files are extracted
answer sections. Do not explore the full bulletin or grep for alternatives.

FY/CY CRITICAL (Biggest ambiguity source):
- FY pre-1977: Jul 1 (Y-1) to Jun 30 (Y)
- FY post-1976: Oct 1 (Y-1) to Sep 30 (Y)
- CY: Jan 1 to Dec 31
TABLE HEADERS CLARIFY. Read the first row. Do not second-guess the header label.

CPI TOOL:
python3 /installed-agent/cpi.py YEAR → index
python3 /installed-agent/cpi.py YEAR1 YEAR2 VALUE → adjusted value

TABLES:
Table headers show "(in millions)" or "(in thousands)". Match what the question asks.
Column headers are definitive. Do not reinterpret.

GREP TIPS:
Use grep -i "keyword" file ONCE to find the table. Read the header row first.
Then extract the row you need. Do not iterate.

MATH:
pct_change = (new - old) / old * 100
cagr = ((end/start)**(1/years) - 1) * 100
stdev: import statistics; statistics.stdev([...])
linreg: import numpy as np; np.polyfit(x, y, 1)

ANSWER REQUIREMENT:
You MUST write a numeric value to /app/answer.txt. Wrong answer > no answer.
Write your answer by step 4-5. Do not rewrite or verify after writing.

{{ instruction }}
```

---

## One-Sentence Summary

**Failing traces (9.4 steps) fail because of ambiguity spirals, not hard problems. Block "could mean" language and commit to first extraction to cut steps by 4 and maintain 80%+ pass rate.**
