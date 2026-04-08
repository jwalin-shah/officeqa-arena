# Would a SQLite DB Actually Help?

## Short Answer
**No. A SQLite DB would help at most 2-4%.**

## The 68 Failures Breakdown

### Missing Numbers (36 failures = 53%)
**Model finds data but doesn't write the final answer.**

Examples:
- UID0021: Model writes "[tool call]" and stops
- UID0012: Model says "I found the table..." then lists the data but never extracts the number
- UID0020: Model says "Here's a summary..." and stops mid-calculation

**Root cause**: Generation/completion problem
- Model might be running out of tokens
- Model gets distracted by verbose output
- Model never reaches "write final answer" step

**SQLite DB helps**: ❌ No
- The model already found the data
- The problem is generating the output, not finding the data
- Better phrasing: "END WITH: <FINAL_ANSWER>123</FINAL_ANSWER>" would help more than a DB

### Wrong Numbers (32 failures = 47%)
**Model extracts numbers but they're wrong.**

Examples:
- UID0012: Found "Defense: 35,532 million" when answer should be "36,080 million" (added wrong column)
- UID0020: Found bank data but computed KL divergence incorrectly
- UID0018: Found monthly values but averaged them instead of geometric mean

**Root causes**:
- Picked wrong row/column from table
- Applied wrong formula (sum vs mean vs geometric mean)
- Extracted from wrong year/period
- Didn't understand table structure

**SQLite DB helps**: ⚠️ Maybe 5-10% of these

**How it might help**:
```
TEXT FILE (current):
"Table 2: Expenditures by Agency, FY 1955
Defense (Mil): 35,532
Defense (Civ): 548
..."

Model can:
- Misread numbers
- Apply wrong formula
- Pick wrong row

SQLITE DB:
SELECT SUM(amount) FROM expenditures WHERE year=1955 AND agency='Defense';

Model can:
- Write wrong SQL
- Misunderstand schema
- Still pick wrong agency/year
```

Even with SQL, the model would need to:
1. Understand the schema
2. Write correct SQL
3. Perform correct computation
4. Know when to use SUM vs MEAN vs GEO_MEAN

**Estimated help**: Maybe 3-6 questions (2-4% improvement → 74-76%)

## Why Text Files Beat Databases

Your v20_best (72.2%) uses **page files** (oracle text) and beats all database approaches because:

1. **Human-readable**: "Defense 35,532" is clear
2. **No schema confusion**: No need to understand table structure
3. **Computation explicit**: "Sum of Jan-Dec = 12,345" is obvious
4. **Less room for error**: Can't write bad SQL or misunderstand column names

## What Actually Helps (in order)

1. **Better answer extraction format** ⭐⭐⭐
   - Current: Model outputs prose with numbers buried
   - Better: "FINAL ANSWER: 12345"
   - Gain: +5-10% (fixes the 36 "missing number" cases)

2. **Better instruction/prompt** ⭐⭐⭐
   - Current: Prompt lets model ramble
   - Better: Force structured output format
   - Gain: +3-5% (prevents token overflow and confusion)

3. **Different model** ⭐⭐
   - MiniMax 2.5 > GPT-5 mini (we saw this in v15 tests)
   - Gain: +2-3%

4. **SQLite with schema help** ⭐
   - Structured data access
   - Pre-aggregated sums
   - Gain: +2-4% (only helps the 32 "wrong number" cases)

5. **Better formula detection** ⭐
   - Detect when question asks for: sum, mean, median, pct_change, etc.
   - Gain: +1-2%

## The Math

```
Current (v20): 72.2%

Scenario: Add SQLite DB with perfect schema
- Fixes best case of 10% of "wrong number" failures (32 * 0.1 = 3)
- New score: (177 + 3) / 245 = 73.5%

Scenario: Perfect answer format ("FINAL ANSWER: X")
- Fixes most "missing number" failures (36 * 0.8 = 29)
- New score: (177 + 29) / 245 = 84.0%

Scenario: SQLite + perfect format + better model
- (177 + 3 + 29 + 5) / 245 = 87.8%
```

## Conclusion

A SQLite DB is **expensive complexity for minimal gain**:

| Approach | Gain | Effort | ROI |
|----------|------|--------|-----|
| Better output format | +5-10% | Low | ⭐⭐⭐ |
| Clearer prompt | +3-5% | Low | ⭐⭐⭐ |
| SQLite DB | +2-4% | High | ⭐ |
| Different model (MiniMax) | +2-3% | Medium | ⭐⭐ |

**Recommendation**:
1. First: Fix the output format to force "FINAL ANSWER: X"
2. Second: Simplify prompt, add verification step
3. Third: Try MiniMax 2.5 if not already using it
4. Only if stuck: Add structured DB access (but probably won't help much)

The data isn't the constraint. **Model generation is.**
