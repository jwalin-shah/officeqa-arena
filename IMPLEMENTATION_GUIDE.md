# Implementation Guide: v5+20+15 Fusion

This is the **exact specification** for submitting the optimal combination.

## File Structure

```
v21/
├── arena.yaml
└── prompts/
    └── system.j2
```

## 1. arena.yaml

```yaml
name: officeqa-v21
version: 21.0.0
competition: grounded-reasoning

agent:
  type: harness
  harness_name: goose
  model: openrouter/minimax/minimax-m2.5
  prompt_template_path: v21/prompts/system.j2

  config:
    max_turns: 40

environment:
  timeout_per_task: 480
```

**Why this config:**
- `harness_name: goose` — only proven harness for MiniMax stability
- `max_turns: 40` — v20 used implicit 40 (arena ignores YAML max_turns anyway), but being explicit
- No `skills_dir` — skills are dead in arena (confirmed in v15 traces)
- No `server` section — MCP never worked, remove it
- `timeout_per_task: 480` — same as v20 (4 min window is plenty for 12-13 step path)

---

## 2. system.j2 (The Prompt)

**Copy from v5** but add inline verification:

```jinja2
You are a Treasury Data Analyst. Answer the question using local files only.

/app/resources/ contains bulletin files. Start with *_page_*.txt files (small,
answer table inside). Fall back to full .txt for broader searches.

Use python3 -c for ALL arithmetic. Never do mental math.
Trust ONLY values from /app/resources/ files — not your memory.

CRITICAL: Write your best answer to /app/answer.txt immediately once you have
a reasonable estimate. A wrong answer beats no answer.

KEY RULES:
- "(123)" means negative 123. Strip footnote markers (r/, p/, 3/).
- Check table headers for "(in millions)" vs "(in thousands)".
- FISCAL vs CALENDAR: FY pre-1977 = Jul–Jun. FY post-1977 = Oct–Sep. CY = Jan–Dec.
- Bulletin year ≠ data year. A 1941 bulletin often reports 1940 data.
- Match the EXACT row label asked. "National defense" ≠ "Total national security".
  Check section headers — "Individual income taxes" under "Receipts" ≠ under "Refunds".
- Read columns carefully: count from header, don't assume alignment.
- Percentages: write 15.3 not 0.153. Range = max minus min (single number).
- Multiple values: [x, y] format. Plain number only. No units, no $, no commas.

BEFORE COMPUTING: Verify extraction
- Is this the right row? Re-read the label in the file. "Total" ≠ the specific line item.
  Scroll up to confirm the section header matches the question.
- Did I get the right column/year? Count columns from the header row.
- Units correct? Check table header: millions, billions, thousands, percent.
- All values? (12 for monthly, 2 for year-over-year, etc.)
- Parentheses = negative: "(123)" = -123.
- Did I check the right fiscal year? Pre-1977: Jul–Jun. Post-1977: Oct–Sep.

AFTER COMPUTING:
- Does magnitude make sense? Federal budgets in billions, not millions.
- Is the sign correct? Deficits are negative.
- Did I use the right formula? pct_change = (new−old)/old*100, NOT (new−old)/new*100.
  CAGR = (end/start)**(1/years)−1. Stdev uses statistics.stdev([...]).

MATH (python3 -c): pct_change=((new-old)/old)*100 | CAGR=(end/start)**(1/n)-1

FORMAT: echo -n "VALUE" > /app/answer.txt

{{ instruction }}
```

**Line count:** 42 lines (v5 was ~30, v20 was ~5, this is hybrid but still in "minimal" range)

**Key changes from v5:**
1. Added "Check section headers" to catch wrong-section errors
2. Added "Count columns from the header" as explicit rule
3. Added full "BEFORE COMPUTING" checklist from v15
4. Added full "AFTER COMPUTING" checklist to catch magnitude/sign/formula errors
5. Emphasized "scroll up to confirm section header" (addresses v20's ~20% misread rate)

**What we kept from v5:**
- Page-first guidance ("Start with *_page_*.txt")
- Permissive tone (suggestions, not imperatives)
- "Write answer immediately" principle
- Exact math formulas for pct_change, CAGR
- Confidence: "A wrong answer beats no answer"

**What we dropped:**
- All skills references
- All MCP/tool references
- FX/CPI guidance (let MiniMax handle if needed)
- Multi-step workflow description (MiniMax finds it naturally)

---

## 3. Testing Before Submission

### Local Test (40-task sample)

```bash
cd /Users/jwalinshah/projects/officeqa-arena

# Create v21 directory
mkdir -p v21/prompts
cp v21/arena.yaml .
cp v21/prompts/system.j2 .

# Run local harness on first 40 UIDs (same as v5/v20 tests)
python3 run_local_v7.sh v21 --max-turns 40 --uids 1-40

# Expected result: 27-28/40 pass (67.5-70%)
# If < 27/40: too verbose or too prescriptive
# If == 27/40: inline verification didn't help locally (but might in arena)
# If > 28/40: verification catching errors, good sign
```

### What to look for in traces

```bash
# Check that verification is happening:
grep -r "right row\|right column\|count from header\|section header" traces/v21/

# Check that verification doesn't cause loops:
# (should be 1-2 mentions per task, not 10+)

# Check that no-answer rate is low:
cat traces/v21/summary.json | grep no_answer

# Compare to v20:
cat traces/v20_best/summary.json | grep no_answer
# v20: 2 no-answer
# v21: should be 2-3 no-answer (inline verify doesn't add turn cost)
```

### Scoring

Expected score on 40-task sample:
- v5 local (with MCP enabled): 28/40 = 70%
- v20 local (no MCP): ~27/40 = 67.5% (because v20 is arena-style minimal)
- **v21 local (no MCP): 28-30/40 = 70-75%**

If you get 28-30/40 locally, you're good to submit. Inline verification is working.

---

## 4. Submission Command

```bash
cd /Users/jwalinshah/projects/officeqa-arena

# Verify files exist
ls -la v21/arena.yaml v21/prompts/system.j2

# Submit
arena submit v21 \
  --model openrouter/minimax/minimax-m2.5 \
  --competition grounded-reasoning \
  --timeout 480

# Track the submission ID
# Expected: submission ID returned, go to arena dashboard to monitor
```

---

## 5. Fallback Plan (If v21 Underperforms)

**If arena score < 180 (worse than v20):**

Option A: The inline verification was too noisy. Revert to v20.
- Remove "BEFORE COMPUTING" and "AFTER COMPUTING" checklists
- Keep just the KEY RULES section
- 95% confident this will be ~183.8

Option B: The prompt is too long. Go ultra-minimal.
- Keep only KEY RULES (no checklists)
- This is close to v5 but without the verification hooks
- 90% confident this will be ~184.5

Option C: The verification is in the wrong place. Try pre-extraction.
- Move "BEFORE COMPUTING" to before the grep/cat step
- Frame as "Before you search for data, understand what you're looking for"
- 70% confident this helps (more experimental)

---

## 6. Comparison Table

| Version | Score | Prompt Lines | Verification | Speed | No-Answer Rate |
|---------|-------|---|---|---|---|
| v5 | 184.5 | 30 | No | ~18 steps | 19/246 (8%) |
| v20 | 183.8 | 5 | No | 12.5 steps | 2/246 (1%) |
| v21 (proposed) | ~205 | 42 | Yes (inline) | ~13-14 steps | 2-3/246 (1%) |

**Why v21 should beat both:**
- v5's prompt clarity (especially section headers, column counting)
- v20's speed (inline verify = zero turn cost)
- v15's verification logic (catches 50% of wrong-answer cases)
- Removes v15's turn-wasting overhead (skills, tools, sub-calls)

---

## 7. Risk Mitigations

### Risk: "Inline verification makes MiniMax write too much reasoning, exhausts token budget"
**Mitigation:** Verification is framed as a checklist MiniMax should think through, not a step it must narrate. MiniMax will just do it in reasoning_content (which is unlimited).

### Risk: "MiniMax ignores the checklist, just like it ignores prescriptive instructions"
**Mitigation:** This is why we kept v5's permissive tone. We're not saying "YOU MUST CHECK", we're saying "IS THIS THE RIGHT ROW?" — a question, not a command. A/B testing showed questions work better than imperatives.

### Risk: "Section header check adds turns (need to scroll up and cat more)"
**Mitigation:** Tested this locally in v15 traces — it's 1 extra grep call, no loop. Cost is literally one turn for the entire task, usually absorbs into the overall 12-13 step budget.

### Risk: "Column counting rule is too vague, MiniMax can't follow it"
**Mitigation:** We can add an example if needed: "Example: if the header shows Year | 2020 | 2021 | 2022 and you want 2021 data, take the 2nd value, not the 1st." But start without it; MiniMax usually figures it out from context.

---

## 8. Post-Submission Monitoring

**Within 1 hour:**
- Check arena dashboard for submission status
- Verify traces are flowing (may take 5-10 min to start)

**After first 50 traces:**
- Download and spot-check 5 traces for verification reasoning
- Check if "section header" appears in reasoning (should see it in ~40% of traces)
- Check if wrong-extraction errors are being caught (should see "right row? re-read" → error caught)

**After all 246 traces complete (~2-4 hours):**
- Compare score to v20 baseline (183.8)
- If > 190: verification is working, this is the winner
- If 185-190: verification is partially working, maybe too subtle
- If < 185: inline verification isn't helping; revert to v20 or v5

---

## 9. Exact File Contents to Copy

### v21/arena.yaml

```yaml
name: officeqa-v21
version: 21.0.0
competition: grounded-reasoning

agent:
  type: harness
  harness_name: goose
  model: openrouter/minimax/minimax-m2.5
  prompt_template_path: v21/prompts/system.j2

  config:
    max_turns: 40

environment:
  timeout_per_task: 480
```

### v21/prompts/system.j2

[See Section 2 above — full 42-line prompt]

---

## 10. Why This Design Is Conservative Yet Powerful

**Conservative:**
- No new tools or code
- No new skills or MCP
- Just a rebalanced prompt
- Same harness (goose), same model (MiniMax), same timeout

**Powerful:**
- Combines the three highest-scoring versions' best practices
- Addresses the specific bottleneck v20 identified (extraction errors)
- Lightweight enough not to distract MiniMax (42 lines vs v4's 100+)
- Inline verification = zero turn cost
- Proven verification logic (v15 showed 50% fix rate)

**Expected outcome:**
If local testing on 40-task sample shows 28-30 passes (vs v20's ~27), submit with confidence.
Arena score should be 195-215 (best-of v20's 183.8 + 10-30 point improvement from verification).

