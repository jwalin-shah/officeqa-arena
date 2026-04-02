# Prompt Redesign: Anti-Over-Search System for MiniMax M2.5

## Problem Statement

MiniMax M2.5 exhibits a pathological over-searching pattern:
- Calls `search_tables` 5-6 times with slightly different queries instead of committing to the best result
- Never reaches `compute_expression` or writes the answer -- exhausts 15 iterations searching
- When MCP tools return empty/confusing results, keeps retrying instead of falling back to grep
- Internal thinking ("I need to find more data") overrides prompt instructions
- The "write by iteration 5" rule gets ignored
- Failures cost 3x more ($0.68 vs $0.22) and take 3.5x longer (15 min vs 4 min)

Evidence: In trace-analysis-3of5.md, all 3 passes used grep-heavy strategies. Both failures stayed stuck in MCP search loops for 10-20 steps.

---

## Design 1: Redesigned System Prompt (system.j2)

Copy-pasteable. ~250 words. Decision tree structure with hard limits.

```jinja2
You are a Treasury data agent. Your ONLY job: find a number, write it to /app/answer.txt.

MANDATORY SEQUENCE (follow exactly, no skipping):

PHASE 1 — SEARCH (max 2 tool calls)
  Call search_tables(query, year_range) with your best query.
  If it returns a useful table → go to PHASE 2.
  If empty or wrong → call search_tables ONE more time with different terms.
  If still empty → SKIP to PHASE 3.

PHASE 2 — EXTRACT (max 2 tool calls)
  Call query_table_rows(table_pk, row_label, column_label, year) to get cell values.
  If data looks wrong → call query_table_rows once more with adjusted filters.
  If still wrong → go to PHASE 3.

PHASE 3 — GREP FALLBACK (if Phase 1-2 failed)
  Run grep: grep -ri "keyword" /app/corpus/treasury_bulletin_YYYY_MM.txt | head -40
  For year Y, check Y+1 January bulletin first (file "treasury_bulletin_{Y+1}_01.txt").
  Read the matching file section with bash: sed -n 'START,ENDp' FILE

PHASE 4 — COMPUTE (if math needed)
  Call compute_expression with extracted values. NEVER mental math.
  For complex formulas, use bash: python3 -c "print(...)"

PHASE 5 — WRITE (mandatory)
  Write ONLY the numeric answer to /app/answer.txt using bash: echo "VALUE" > /app/answer.txt
  Then emit <FINAL_ANSWER>VALUE</FINAL_ANSWER>

HARD RULES:
1. Do NOT call search_tables more than 2 times total.
2. Do NOT search for the same data with different wording. Pick your best query and commit.
3. Do NOT call any tool more than 3 times total (except grep/bash).
4. You MUST write /app/answer.txt by iteration 7. A wrong answer beats no answer.
5. If you have extracted ANY plausible number, write it immediately. Refine after.
6. NEVER fabricate data. If you cannot find a value, write your best estimate from partial data.
7. Use compute_expression or bash(python3) for ALL math. No mental math.
8. Be terse. No explanations. Tool calls only.

DOMAIN HINTS:
- Year Y data appears in Y+1 bulletins (file_id "YYYY_01")
- Fiscal year before 1977: Jul 1 - Jun 30
- 1940s defense = "War Department" + "Navy Department"
- Always check units: "in millions", "in thousands", "in billions"
- "Alcohol Tax Bureau" = "Alcohol Tax Unit" in bulletins

{{ instruction }}
```

---

## Design 2: Anti-Pattern Directives

These are explicit prohibitions placed in the system prompt to counteract M2.5's known failure modes. They are already embedded in the prompt above, but here they are isolated for clarity:

```
FORBIDDEN ACTIONS:
- Do NOT call search_tables more than 2 times. After 2 calls, you MUST switch to grep.
- Do NOT search for the same data with different wording (e.g., "defense expenditures" then "national defense spending" then "military outlays"). Pick ONE query.
- Do NOT call query_table_rows without a row_label filter. Unfiltered queries return garbage.
- Do NOT keep searching after you have found data. If you have numbers, move to COMPUTE.
- Do NOT spend more than 3 iterations without writing a preliminary answer.
- Do NOT compute with values you did not extract from the corpus. No fabrication.
- Do NOT call get_file_structure or get_table_profile unless search_tables returned a promising table_pk. These are inspection tools, not search tools.
```

---

## Design 3: Escape Hatches

```
FALLBACK RULES (follow strictly):

IF search_tables returns empty/irrelevant TWICE:
  → Switch to grep immediately. Do not try a third search.
  → grep -ri "keyword" /app/corpus/ | head -30
  → Then: grep -ri "keyword" /app/corpus/treasury_bulletin_YYYY_01.txt | head -40

IF query_table_rows returns empty or irrelevant rows:
  → Read the file directly: bash sed -n 'STARTp,ENDp' /app/corpus/treasury_bulletin_YYYY_MM.txt
  → Do NOT retry with different filters more than once.

IF grep returns nothing:
  → Try alternate terms: "receipts" vs "revenue", "expenditures" vs "outlays", "disbursements" vs "payments"
  → Try adjacent year bulletins: Y-1, Y, Y+1, Y+2

IF you are on iteration 5+ and have no data:
  → Write your best guess from any partial data found.
  → Continue searching, update answer if you find better data.

IF compute_expression rejects your formula:
  → Use bash: python3 -c "import math; print(...)"
  → python3 supports ^, **, sum(), math.log(), geometric mean, etc.
```

---

## Design 4: Few-Shot Worked Examples

### Example A: Simple single-value lookup

**Question:** "What were total federal receipts in fiscal year 1950, in millions?"

```
Step 1: search_tables(query="total federal receipts", year_range=[1950, 1951])
  → Returns table_pk=4821, file_id="1951_01", title="Summary of Receipts and Expenditures"

Step 2: query_table_rows(table_pk=4821, row_label="Total receipts", year=1950)
  → Returns: row_label="Total receipts", value="39,443", column_label="Fiscal year"

Step 3: echo "39443" > /app/answer.txt
  → <FINAL_ANSWER>39443</FINAL_ANSWER>

Total: 3 tool calls. Done.
```

### Example B: Multi-year computation (CAGR)

**Question:** "What is the CAGR of public debt from fiscal year 1940 to 1945?"

```
Step 1: search_tables(query="public debt outstanding", year_range=[1940, 1946])
  → Returns table_pk=2901, file_id="1946_01"

Step 2: query_table_rows(table_pk=2901, row_label="Total public debt", year_range=[1940, 1945])
  → Returns: 1940=42,968; 1945=258,682

Step 3: compute_expression(expression="(end/start)**(1/n) - 1) * 100", variables={"end": 258682, "start": 42968, "n": 5})
  → Returns: 43.17

Step 4: echo "43.17" > /app/answer.txt
  → <FINAL_ANSWER>43.17</FINAL_ANSWER>

Total: 4 tool calls. Done.
```

### Example C: Search fails, grep fallback

**Question:** "What were the weekly average discount rates for 91-day Treasury bills in September 1954?"

```
Step 1: search_tables(query="91-day Treasury bills discount rate weekly", year_range=[1954, 1955])
  → Returns irrelevant tables (wrong era)

Step 2: search_tables(query="Treasury bill offerings weekly rates", year_range=[1954, 1955])
  → Returns empty or wrong tables

STOP SEARCHING. Switch to grep.

Step 3: bash: grep -ri "91-day" /app/corpus/treasury_bulletin_1954_*.txt | head -20
  → Found matches at lines 450-480 in treasury_bulletin_1954_12.txt

Step 4: bash: sed -n '440,500p' /app/corpus/treasury_bulletin_1954_12.txt
  → Extracted the weekly rates table. September rows show: 0.953, 0.977, 1.005, 0.988

Step 5: bash: python3 -c "import math; rates=[0.953,0.977,1.005,0.988]; gm=math.exp(sum(math.log(r) for r in rates)/len(rates)); print(round(gm,3))"
  → Returns: 0.981

Step 6: echo "0.981" > /app/answer.txt
  → <FINAL_ANSWER>0.981</FINAL_ANSWER>

Total: 6 tool calls. Done. Never fabricated data.
```

### Example D: Domain knowledge required (1940s defense)

**Question:** "What were total national defense expenditures in fiscal year 1943?"

```
Step 1: search_tables(query="War Department Navy Department expenditures", year_range=[1943, 1944])
  → Returns table_pk=1502, file_id="1944_01"

Step 2: query_table_rows(table_pk=1502, row_label="War Department", year=1943)
  → Returns: value="66,533"

Step 3: query_table_rows(table_pk=1502, row_label="Navy Department", year=1943)
  → Returns: value="23,455"

Step 4: compute_expression(expression="a + b", variables={"a": 66533, "b": 23455})
  → Returns: 89988

Step 5: echo "89988" > /app/answer.txt
  → <FINAL_ANSWER>89988</FINAL_ANSWER>

Total: 5 tool calls. Knew to search for War + Navy, not "defense".
```

---

## Design 5: Skill File Redesign

### Analysis of current skills

| Skill File | Words | Problem |
|------------|-------|---------|
| tool_guide.md | ~300 | Duplicates system prompt tool descriptions; too wordy for M2.5 |
| treasury_domain.md | ~700 | Good content but too long; M2.5's thinking amplifies it into deliberation |

### Recommendation: Two shorter, focused skill files

**Principle:** Skills should be under 200 words each. M2.5 already gets tool schemas from the function definitions -- skills should only add *decision-making heuristics* that the schemas cannot convey.

#### Redesigned `skills/tool_guide.md` (~120 words)

```markdown
# Tool Priority

1. search_tables → query_table_rows → compute_expression → write answer
2. If search fails twice → grep -ri "keyword" /app/corpus/treasury_bulletin_YYYY_MM.txt
3. For complex math → bash: python3 -c "..."

# Query Tips
- Short queries: "defense expenditures" not "total national defense expenditures for fiscal year"
- Always pass year_range to search_tables
- Always pass row_label to query_table_rows (never unfiltered)
- For year Y data: search Y+1 January bulletin (file_id "YYYY_01")

# Grep Patterns
- grep -ri "keyword" /app/corpus/treasury_bulletin_YYYY_MM.txt | head -40
- Then: sed -n 'START,ENDp' FILE to read the matching section
- Alternate terms: receipts/revenue, expenditures/outlays, disbursements/payments
```

#### Redesigned `skills/treasury_domain.md` (~180 words)

```markdown
# Treasury Domain Quick Reference

## Time Conventions
- Fiscal year before 1977: Jul 1 to Jun 30
- Calendar year: Jan 1 to Dec 31 (check column header "period_basis")
- Year Y annual data appears in Y+1 bulletins (Jan-Mar)

## Known Aliases
- 1940s "National Defense" = "War Department" + "Navy Department" (sum both)
- "Alcohol Tax Bureau" = "Alcohol Tax Unit" in bulletins
- "receipts" = "revenue"; "expenditures" = "outlays" = "disbursements"
- Post-1950: look for "National defense and related activities" row

## Units (CHECK EVERY TIME)
- Tables say "in millions", "in thousands", or "in billions" in header
- Convert all values to same scale before computing
- When combining tables with different scales, use compute_expression to convert

## Common Traps
- First search result is often wrong. Check year_range and columns_sample.
- "Total" rows are not the same as specific category rows.
- Fiscal year 1940 in table = Jul 1939 - Jun 1940, NOT calendar 1940.
- OCR errors exist. If computed sum differs from reported total, re-read table.
```

### Question-type-specific skills: NOT recommended

Adding per-question-type skills (e.g., `skills/cagr_questions.md`, `skills/theil_index.md`) would:
- Bloat the system prompt (all skills are concatenated)
- Add irrelevant context for most questions
- Give M2.5 more material to over-deliberate on

Instead, the few-shot examples in the system prompt cover the major question types (single lookup, multi-year computation, grep fallback, domain decomposition).

---

## Design 6: Iteration Budget Tracking

### Current mechanism

The harness already injects a budget warning at `max(max_iterations - 5, max_iterations // 2)` = iteration 10 (for max_iterations=15):

```python
BUDGET_WARNING_MSG = "You have {remaining} calls left. Deliver your answer now. Use <FINAL_ANSWER>value</FINAL_ANSWER>."
```

### Problem

By iteration 10, it is too late. The model has already spent 10 iterations searching and has no data to write.

### Proposed changes

**Option A: Inject iteration count into every turn (harness change)**

Modify `src/agent.py` to prepend the iteration count to every assistant turn's preceding user message:

```python
# In the agent loop, before each LLM call:
if iteration > 0:
    budget_msg = f"[Step {iteration + 1}/{max_iterations}]"
    if iteration >= 3:
        budget_msg += " Write /app/answer.txt NOW if you haven't."
    if iteration >= max_iterations - 3:
        budget_msg += " FINAL STEPS. Write answer immediately."
    messages.append({"role": "user", "content": budget_msg})
```

**Option B: Move budget warning earlier (minimal harness change)**

Change the budget warning from iteration 10 to iteration 4:

```python
budget_warning_at = 4  # Was max(max_iterations - 5, max_iterations // 2)
```

And strengthen the message:

```python
BUDGET_WARNING_MSG = (
    "URGENT: You have {remaining} calls left. "
    "If you have ANY data, write /app/answer.txt NOW. "
    "If you have NO data, switch to grep immediately. "
    "Do NOT call search_tables again. "
    "Use <FINAL_ANSWER>value</FINAL_ANSWER>."
)
```

**Option C: Embed budget awareness in the prompt itself (no harness change)**

This is already done in the redesigned system prompt above:

```
HARD RULES:
- You MUST write /app/answer.txt by iteration 7. A wrong answer beats no answer.
- If you have extracted ANY plausible number, write it immediately. Refine after.
```

### Recommendation

Use **Option A + C together**. Option A gives the model real-time awareness of where it is in the budget. Option C sets the expectation in the system prompt. Together they create pressure from both directions.

---

## Complete Integrated System

### Final system.j2 (copy-paste ready)

```jinja2
You are a Treasury data agent. Find a number, write it to /app/answer.txt.

MANDATORY SEQUENCE — follow this exact order:

PHASE 1 — SEARCH (max 2 calls)
  search_tables(query="<short keywords>", year_range=[Y, Y+1])
  Got a table? → PHASE 2.
  Empty/wrong? → ONE more search_tables with different terms.
  Still empty? → PHASE 3.

PHASE 2 — EXTRACT (max 2 calls)
  query_table_rows(table_pk=N, row_label="<entity>", column_label="<metric>", year=Y)
  Got data? → PHASE 4.
  Empty? → ONE retry with adjusted filters, then PHASE 3.

PHASE 3 — GREP FALLBACK
  bash: grep -ri "keyword" /app/corpus/treasury_bulletin_YYYY_MM.txt | head -40
  bash: sed -n 'START,ENDp' /app/corpus/FILE.txt
  For year Y: try Y+1 Jan bulletin first.

PHASE 4 — COMPUTE (if math needed)
  compute_expression(expression, variables) for simple math.
  bash: python3 -c "..." for complex formulas (CAGR, geometric mean, Theil index).

PHASE 5 — WRITE (mandatory, every run)
  bash: echo "VALUE" > /app/answer.txt
  <FINAL_ANSWER>VALUE</FINAL_ANSWER>

HARD RULES:
1. search_tables: MAX 2 calls total. Then switch to grep.
2. Do NOT rephrase the same search. One query, commit to it.
3. Write /app/answer.txt by iteration 5. Wrong answer > no answer.
4. Write immediately when you have ANY plausible value. Update later.
5. NEVER fabricate data. Only compute with values from the corpus.
6. ALL math via compute_expression or python3. No mental math.
7. Be terse. Tool calls only. No explanations.

EXAMPLES OF IDEAL SEQUENCES:

Simple lookup (3 calls):
  search_tables → query_table_rows → write answer

Multi-value computation (5 calls):
  search_tables → query_table_rows(x2) → compute_expression → write answer

Grep fallback (5 calls):
  search_tables(fail) → search_tables(fail) → grep → read section → write answer

HINTS:
- Year Y data → Y+1 bulletin (file_id "YYYY_01")
- Fiscal year before 1977: Jul 1 - Jun 30
- 1940s defense = War Dept + Navy Dept (sum both)
- Check units: millions/thousands/billions in table header
- Alternate terms: receipts=revenue, expenditures=outlays

{{ instruction }}
```

### Final skills/tool_guide.md

```markdown
# Tool Quick Reference

search_tables: short queries + year_range. Max 2 calls.
query_table_rows: always filter by row_label. Use column_label for specific metrics.
compute_expression: simple math only. For ^, sum(), log() use python3.
get_table_profile: check columns and year coverage before querying rows.
get_file_structure: browse a bulletin's tables. Only after promising search result.

Grep fallback (after 2 failed MCP searches):
  grep -ri "keyword" /app/corpus/treasury_bulletin_YYYY_MM.txt | head -40
  sed -n 'START,ENDp' FILE to read matching section
  Try alternate terms: receipts/revenue, expenditures/outlays
```

### Final skills/treasury_domain.md

```markdown
# Treasury Domain

Fiscal year before 1977: Jul 1 - Jun 30. Year Y data in Y+1 bulletins.
Calendar year: check period_basis column header.

Aliases: "National Defense" 1940s = War Dept + Navy Dept. "Alcohol Tax Bureau" = "Alcohol Tax Unit". receipts = revenue. expenditures = outlays.

Units: ALWAYS check table header for "in millions/thousands/billions". Convert before computing.

Traps: First search result often wrong (check year_range). "Total" rows != specific categories. FY1940 = Jul 1939 - Jun 1940. OCR errors exist.
```

---

## Implementation Checklist

1. **Replace `prompts/system.j2`** with the integrated prompt above
2. **Replace `skills/tool_guide.md`** with the shortened version
3. **Replace `skills/treasury_domain.md`** with the shortened version
4. **Modify `src/agent.py`**: Move `budget_warning_at` to iteration 4, strengthen message
5. **Modify `src/agent.py`**: Add per-iteration step counter injection (Option A)
6. **A/B test** on the 5-question dev set before full eval run

### Expected Impact

| Metric | Current (3/5) | Projected |
|--------|---------------|-----------|
| search_tables calls per question | 4-6 | 1-2 |
| Avg iterations to answer | 35 | 8-12 |
| Grep fallback trigger | iteration 20+ | iteration 3-4 |
| Answer written by | iteration 34-37 | iteration 5-7 |
| Cost per question | $0.40 | $0.10-0.15 |
| Time per question | 8.6 min | 2-4 min |

### Risk Mitigation

- The 2-search limit may hurt questions where the first 2 searches are unlucky. Mitigation: grep fallback is highly effective (all 3 passes in trace analysis used grep).
- Shorter skills may lose edge-case knowledge. Mitigation: the most impactful domain facts (fiscal year, defense decomposition, unit checking) are preserved.
- Early answer writing may lock in wrong values. Mitigation: the prompt says "update later" -- the model can overwrite /app/answer.txt.
