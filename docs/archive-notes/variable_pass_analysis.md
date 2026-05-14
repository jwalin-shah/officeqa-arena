# Variable-Pass Task Analysis: What Makes Winners Succeed

## EXECUTIVE SUMMARY

Analyzed **178 traces** across **5 hardest variable-pass tasks** (20-50% success rate):
- **officeqa-uid0012**: 37.5% (18/48 pass)
- **officeqa-uid0177**: 32.4% (12/37 pass)
- **officeqa-uid0046**: 39.3% (11/28 pass)
- **officeqa-uid0237**: 30.3% (10/33 pass)
- **officeqa-uid0121**: 40.6% (13/32 pass)

**64 passing, 114 failing traces analyzed for patterns**

---

## KEY FINDINGS

### FINDING #1: FINAL ANSWER FORMAT IS CRITICAL (+17% difference)

**PASSING patterns:**
- Bold-formatted numeric answer (**bold**): **88%**
- Complete/finished statement: 58%
- Mentions /app/answer.txt: 66%

**FAILING patterns:**
- Bold-formatted numeric answer: **70%**
- Complete/finished statement: 45%
- Mentions /app/answer.txt: 61%

**Impact: +18 percentage points on bold formatting = strongest single indicator**

### FINDING #2: ANSWER CONFIDENCE COMMITMENT (+15% difference)

**PASSING:**
- 93% end with explicit statement (NOT tool call)
- 84% include verification in final 3 steps
- 89% have numeric answer in final response

**FAILING:**
- 78% end with explicit statement
- 18% end with tool calls or ambiguous messages
- 79% have numeric answer in final response

**Impact: Passing traces COMMIT to answer; failing traces trail off or call tools**

### FINDING #3: EFFICIENT VERIFICATION MATTERS (+9% difference)

**PASSING:**
- 55% complete in ≤15 steps
- Multiple verifications (2-3 passes)
- High confidence before stopping

**FAILING:**
- 47% complete in ≤15 steps
- Verification loops (4+ passes)
- Less committed to final answer

**Impact: Efficiency signals confidence; looping signals doubt**

### FINDING #4: SOURCE DOCUMENTATION HELPS

**PASSING:**
- 92% cite table/page reference in final answer
- Format: "From Table X on page Y: answer is [value]"
- Systematic verification of categories/fields

**FAILING:**
- 74% cite sources
- Less systematic enumeration
- Partial verification

**Impact: Source citation = evidence of verification**

---

## CONCRETE PATTERNS: WHAT TO CHANGE

### Pattern 1: Answer Format Standardization
**What passing traces do:**
```
**Answer:** [numeric value] [units]
```
or
```
Based on [Table X], page [Y]: **[value]** [units], written to `/app/answer.txt`.
```

**Why it works:**
- Grader uses pattern matching to extract answers
- Double-bold formatting is easily parseable
- Clear formatting = fewer parsing errors

**Implementation:** Enforce in prompt that final answer uses `**Answer:** [value]`

---

### Pattern 2: Confidence Commitment
**What passing traces do:**
1. Analyze thoroughly
2. Verify 1-2 times
3. **State final answer with certainty** (not as a question or tentative)
4. Stop immediately after final answer

**Why it works:**
- Tool calls at end = uncertainty signal
- Grader expects agent to "know" when it's done
- Ambiguous endings fail more often

**Implementation:** Add prompt: "Once verified, give your final answer with full confidence. Do NOT end with a tool call if you have the answer."

---

### Pattern 3: Efficient Verification (Not Excessive)
**What passing traces do:**
- Verify once after initial analysis
- Verify again if discrepancy found
- Then **commit and stop** (not loop)

**What failing traces do:**
- Verify 4+ times
- Re-check same data repeatedly
- Never reach decision point

**Implementation:** Add guidance: "Verify 1-2 times maximum. After confirmation, provide final answer immediately."

---

### Pattern 4: Source Documentation
**What passing traces do:**
- Every answer cites source: "From Table TSO-3: The answer is..."
- Reference page numbers explicitly
- Show which fields/rows were used

**Implementation:** Add prompt: "Always cite the source table and page number in your final answer."

---

## RECOMMENDED PROMPT CHANGES (Implementation Order)

### HIGH PRIORITY: Answer Format Standardization (+2%)
```
"When you have found the answer, ALWAYS format your final
statement as:

**Answer:** [numeric value] [units]

If applicable, also mention the source table/page.
If writing to a file, explicitly state '/app/answer.txt: [value]'."
```

### HIGH PRIORITY: Confidence Commitment (+1.5%)
```
"Once you have verified your answer, provide it with full confidence.

DO NOT:
- End with a tool call if you have the answer
- Say 'Let me double-check' after the final answer
- Use tentative language like 'I believe' or 'might be'

Your final message should be the answer statement with certainty."
```

### MEDIUM PRIORITY: Efficient Verification (+1%)
```
"Verification is important:
- Do your initial analysis
- Verify the answer once
- If correct, state final answer and STOP
- Do not enter re-check loops

Maximum 2 verification passes. Then commit."
```

### POLISH: Source Documentation (+0.5%)
```
"Always cite your source in the final answer:
'From [Table X] on page [Y]: The answer is **[value]**...'"
```

---

## ESTIMATED IMPACT

| Change | Individual | Cumulative |
|--------|-----------|-----------|
| Answer Format (1) | +2.0% | +2.0% |
| Confidence Commitment (2) | +1.5% | +3.5% |
| Efficient Verification (3) | +1.0% | +4.5% |
| Source Documentation (4) | +0.5% | +5.0% |

**Total estimated improvement: +2-5% on variable-pass tasks**

Expected overall score improvement: +0.5-1.5% (since these are hardest tasks)

---

## TASK-SPECIFIC INSIGHTS

### UID0012 (Federal Spending 1955)
**Failing reason:** Stop at military-only figure (35,532) instead of total (36,080)
**Winning approach:** Calculate total by adding military + civil functions
**Key:** Understand "total" != "military only" — requires completeness check

### UID0177 (Debt Limitation Data)
**Failing reason:** End with tool calls; no final statement
**Winning approach:** Explicit file write + final answer statement
**Key:** 77 steps vs 39 steps; longer analysis helps when done systematically

### UID0046 (Treasury Bulletin Table FO-1)
**Failing reason:** Find table but extract wrong value
**Winning approach:** 100% write to file; multiple verification passes
**Key:** File writing forces answer commitment

### UID0121 (Treasury Bills Categories)
**Failing reason:** Missing systematic verification of all categories
**Winning approach:** Enumerate each category, verify holdings explicitly
**Key:** Source citation + systematic approach

### UID0237 (Federal Securities Ownership)
**Failing reason:** Over-calculation (96% do calculations but fail)
**Winning approach:** Lean analysis (80% calculations); know when to stop
**Key:** This task punishes over-analysis; efficiency wins here

---

## NOTES AND CAVEATS

1. **Correlation ≠ Causation**
   - These patterns are strong correlates, but other factors may exist
   - Format and confidence patterns are highly consistent across 5 tasks
   - Safe to implement

2. **Grading Mechanics**
   - Some tasks use fuzzy numeric matching (±1%)
   - Answer format may matter less than correct value
   - But consistent formatting reduces parse errors

3. **Turn Count**
   - Passing: 21.7 avg steps
   - Failing: 20.7 avg steps
   - **Difference is small; efficiency matters more than total steps**
   - Current MAX_TURNS=25-30 is probably fine; just commit faster

4. **Model Generalization**
   - Most traces use minimax (v5/v20/v21)
   - Patterns should work with any model
   - Some models might be more format-sensitive

5. **Verification Type Matters**
   - Passing: Verify the *final answer* (is it correct?)
   - Failing: Verify *intermediate steps* (did I do math right?)
   - Failing traces often have correct steps but wrong conclusions

---

## NEXT STEPS

1. **Implement** Recommendations 1 & 2 in prompt immediately
2. **Test** on local harness with MAX_TURNS=15-20
3. **Measure** impact on uid0012, uid0177, uid0046 (use local oracle)
4. **If +2-3%** observed, submit as v22
5. **Track** overall score improvement (expect +0.5-1.5%)

---

## SUPPORTING DATA

- **Passing traces:** 64 across 5 tasks
- **Failing traces:** 114 across 5 tasks
- **Total versions analyzed:** 62 versions
- **Date of analysis:** April 8, 2026
- **Traces location:** `/Users/jwalinshah/projects/officeqa-arena/traces_comprehensive/`

