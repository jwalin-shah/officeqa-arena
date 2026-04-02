# Testing & Optimization Strategy

Last updated: 2026-03-30

## Current State Summary

- MCP tools now connect (16 tools from baked-in server at /opt/officeqa/)
- SQLite DB is NOT in the container yet (MCP falls back to slow text search)
- Lean DB (~5-6GB) is being built for download during install
- Prompt: 180 words, MCP-first routing with grep fallback
- Model: MiniMax M2.5 via OpenRouter
- Best local result: grep-only 218s latency, $0.07 cost, 1/1 pass
- Best submission result: 25% (5/20 dev, MCP partially broken)
- Old system baseline: 60% (12/20 dev, grep-only, different prompt)
- Leaderboard #1: 103.478 / 282.9 (~37% correct, 90 questions)
- 20 dev questions available locally; 246 total in full eval
- 3 submissions/day, deadline April 4 (possible extension to April 11)
- arena CLI supports: `--smoke`, `--all`, `--filter "glob"`, `--n N`, `--tag`

---

## 1. Testing Matrix (priority order)

Each row is a configuration to test. Run them in the order listed -- earlier rows have higher expected impact.

| # | Config Name | DB | Prompt | reasoning_effort | Skills | Expected Impact | Why |
|---|-------------|----|--------|-----------------|--------|-----------------|-----|
| 1 | **DB-baseline** | YES (lean) | Current slim (180w) | high | tool_guide + treasury_domain | HIGH | DB is the single biggest variable. MCP tools with DB should dramatically improve extraction accuracy and speed. |
| 2 | **DB + medium reasoning** | YES | Current slim | medium | tool_guide + treasury_domain | MEDIUM | M2.5 has known thinking overhead on tool calls. Medium effort may cut latency 20-30% with minimal accuracy loss. |
| 3 | **DB + no custom skills** | YES | Current slim | high | none (rely on baked-in 9 skills) | MEDIUM | Test whether our custom skills help or conflict with baked-in skills at /opt/officeqa/skills/arena_sdk/. |
| 4 | **DB + baked-in skills only** | YES | Current slim | high | baked-in 9 only (remove tool_guide, treasury_domain) | LOW-MEDIUM | Isolate skill contribution. |
| 5 | **DB + parallel tool hint** | YES | Slim + parallel calling directive | high | tool_guide + treasury_domain | LOW-MEDIUM | M2.5 supports parallel tool calls. Could reduce iterations on multi-value questions. |
| 6 | **No DB fallback** | NO | Current slim | high | tool_guide + treasury_domain | BASELINE | Current state. Establishes the no-DB performance floor. |
| 7 | **Verbose prompt (regression)** | YES | Old 588w prompt | high | all | LOW | Regression check. If verbose is somehow better, reconsider slimming. |

### How to run each

```bash
# Single question (fast iteration, ~3 min)
arena test --filter "officeqa-uid0012" --tag "db-baseline"

# Dev set (20 questions, ~1-2 hours)
arena test --all --tag "db-baseline"

# Smoke test (1 random question, ~5 min)
arena test --smoke --tag "db-baseline"

# Subset of N questions
arena test -n 5 --tag "db-medium-reasoning"
```

---

## 2. Local Testing Strategy

### 2.1 Available dev questions (20, all hard)

Categorized by difficulty-to-solve (test in this order for fastest signal):

**Tier A -- Likely solvable with DB (test first, 5 min each):**
- UID0012: Simple lookup (highest spending dept FY1955)
- UID0025: Two-value difference (public works 1934 vs 1946)
- UID0032: Sum-and-subtract (tobacco vs wool imports)
- UID0027: Time-series scan (max yield spread)
- UID0029: Average over time series (yield spread 1960-1969)

**Tier B -- Multi-step computation (test second):**
- UID0017: Lookup + percentage (2-year note bids)
- UID0019: Cross-table + FX conversion
- UID0009: Domain knowledge + weighted average
- UID0036: Domain decode + ratio difference

**Tier C -- Heavy computation (test third):**
- UID0007: Geometric mean over 79 months
- UID0018: Geometric mean over 39 months, 4 sources
- UID0013: OLS regression
- UID0022: OLS regression + prediction
- UID0015: Box-Cox transform
- UID0005: Inflation adjustment via CPI-U

**Tier D -- Likely unsolvable with text-only (deprioritize):**
- UID0030: Count local maxima on line plots (visual)
- UID0031: Read chart TF-G (visual)
- UID0035: Count leading digit '1' in table (visual/counting)
- UID0010: External FX rate from Macrotrends (needs web access)

### 2.2 Fast iteration loop

1. Pick one question from Tier A
2. Run: `arena test --filter "officeqa-uid0012" --tag "test-name"`
3. After completion, run `arena view` to inspect the trace
4. Check `/logs/verifier/reward.txt` and the actual answer vs expected
5. If failed: read the agent trace to identify WHERE it went wrong
   - Wrong table found? -> search/skill issue
   - Right table, wrong value? -> extraction/filter issue
   - Right value, wrong format? -> output format issue
   - Ran out of iterations? -> prompt efficiency issue
   - MCP tool error? -> server/DB issue

### 2.3 Failure analysis protocol

For each failed question, record:
- **Failure mode**: extraction / computation / format / retrieval / iteration-exhaustion / visual
- **Root cause**: what the agent did vs what it should have done
- **Fix category**: prompt change / skill change / tool bug / unsolvable

Track in a simple table. After 10+ failures, look for patterns to prioritize fixes.

### 2.4 Estimating full-set performance from dev results

- Dev set is all-hard. Full set is 54% hard, 46% easy.
- If we get X/20 on dev (all hard), expect roughly: `X/20 * 133 + (X/20 * 1.3) * 113` for full set (easy questions ~30% more solvable).
- Rough formula: full_correct ~ X * 12.3 + X * 7.3 = X * 12 (very approximate).
- Example: 10/20 dev -> ~120/246 full -> score ~120 * 1.05 = ~126.

---

## 3. Optimization Roadmap (after DB works)

### Phase 1: Accuracy (days 1-2, highest ROI)

1. **Validate DB-backed MCP tools work end-to-end**
   - Run Tier A questions (5 questions, expect 4-5/5 pass)
   - If <3/5 pass: debug MCP tool responses, check DB schema alignment

2. **Fix extraction failures (biggest category)**
   - From comprehensive_status: extraction failures were #1 cause
   - Ensure query_table_rows returns the right cells by testing with known UIDs
   - Check if extract_values is routing to the right tables

3. **Answer format handling**
   - 80% are plain numbers, but 21 are bracket lists, 16 are percentages, 5 have "million" suffix
   - Add format examples to the prompt if the model is stripping units or brackets
   - Test with UID0012 ("36080 million"), UID0036 ("9.89%"), UID0013 ("[0.096, -184.143]")

4. **Rounding precision**
   - Questions specify "nearest hundredths", "nearest thousandths", "4 decimal places", "5 significant digits"
   - Verify compute_expression handles all rounding modes
   - Test with UID0029 (5 sig digits: 0.88525) and UID0015 (4 decimal: 6.1596)

### Phase 2: Latency & cost (days 3-4)

5. **reasoning_effort: medium vs high**
   - Run same 5 Tier A questions with medium. If accuracy holds, switch.
   - Expected: 20-30% latency reduction, ~10% cost reduction
   - Risk: may hurt complex multi-step questions

6. **Reduce iteration count**
   - Current target: 5-8 tool calls. Analyze traces to see actual usage.
   - If most questions finish in <10 iterations, lower max_iterations to 12 (saves timeout cost on stuck questions)

7. **Skill pruning**
   - Test with/without custom skills to measure impact
   - If baked-in skills at /opt/officeqa/skills/arena_sdk/ overlap significantly, remove ours to save prompt tokens

### Phase 3: Edge cases (days 4-5)

8. **Multi-source questions** (120/246, ~49%)
   - These need data from 2-4 bulletins. Test UID0005, UID0018, UID0022, UID0025, UID0028.
   - If MCP search reliably finds across bulletins, great. If not, may need prompt hints.

9. **Statistical computations** (~51 questions)
   - Verify compute_expression supports: geometric_mean, linreg, Box-Cox
   - Test UID0007 (geometric_mean), UID0013 (linreg), UID0015 (Box-Cox)

10. **Visual/chart questions** (~10-15 questions)
    - Likely unsolvable with text-only approach. Accept the loss.
    - Unless the parsed .txt files contain OCR'd chart descriptions -- check one file.

11. **External data questions** (CPI-U, FX rates)
    - UID0005 needs CPI-U (get_cpi_index tool exists)
    - UID0010 needs Macrotrends FX (no tool exists -- needs web access or hardcoded data)
    - Check if get_cpi_index actually works in the container

---

## 4. Submission Strategy

### 4.1 Submission timing rules

- 3 submissions/day, resets midnight PST (7 AM UTC)
- Results take 1-2 hours (246 questions)
- Only highest score counts on leaderboard
- Cost: $0 (Arena uses their API keys)

### 4.2 When to use each daily submission

**Submission 1 (morning, ~10 AM PST):** The "learning" submission.
- Submit your best current config
- Use results to identify failure patterns across all 246 questions
- This gives data for the rest of the day

**Submission 2 (afternoon, ~3 PM PST):** The "fix" submission.
- Apply fixes based on Submission 1 failures
- Only submit if you made meaningful changes (not just a hunch)

**Submission 3 (evening, ~8 PM PST):** The "stretch" submission.
- Try a riskier change (e.g., reasoning_effort medium, different skill config)
- OR save it as insurance for the next day if you're still iterating

### 4.3 What to submit first

1. **First ever submission with working DB**: DB-baseline config (row #1 from testing matrix). This establishes the real baseline with MCP tools actually working.
2. **Second submission**: Apply fixes for any format/extraction issues found in submission 1 results.
3. **Third submission**: Try reasoning_effort medium if accuracy is stable.

### 4.4 Interpreting results

- `arena results` gives per-question pass/fail
- Compare against dev set results to validate local testing matches production
- If local passes but submission fails: likely a container environment issue
- Group failures by question category (from question-analysis.md) to find systematic issues
- Track score trend: if score plateaus across 2-3 submissions, the remaining failures may be fundamentally hard (visual, external data)

---

## 5. Day-by-Day Timeline

### Day 0: March 30 (today) -- Foundation

- [x] Research complete (findings, question analysis, prompt optimization)
- [ ] Finalize lean DB build
- [ ] Test DB download/install in container (arena test --smoke)
- [ ] Run 3 Tier A questions locally with DB
- [ ] Save submissions for tomorrow (no blind submissions today)

### Day 1: March 31 -- DB validation + first real submission

- AM: Run full dev set locally (`arena test --all --tag "db-baseline"`)
- AM: Analyze all 20 results, categorize failures
- **Submission 1**: DB-baseline config (learn from 246-question results)
- PM: Fix top failure category (likely extraction or format)
- PM: Run 5 failed questions locally to verify fix
- **Submission 2**: Fixes applied
- Evening: Analyze submission 2, plan next changes
- **Submission 3**: Save OR try reasoning_effort medium

### Day 2: April 1 -- Optimization sprint

- AM: Apply all learnings from Day 1 submissions
- AM: Test specific failing questions locally
- **Submission 1**: Best config so far
- PM: Skill optimization (test with/without custom skills)
- PM: Test Tier B and Tier C questions for computation accuracy
- **Submission 2**: Skill-optimized config
- **Submission 3**: Experimental (parallel tool hint, or medium reasoning)

### Day 3: April 2 -- Edge cases + polish

- AM: Focus on multi-source questions (49% of dataset)
- AM: Verify statistical computation tools (geometric_mean, linreg, Box-Cox)
- **Submission 1**: Edge-case fixes
- PM: Answer format hardening (bracket lists, percentages, "million" suffix)
- **Submission 2**: Format fixes
- **Submission 3**: Best overall config (insurance submission)

### Day 4: April 3 -- Final push

- AM: Review all submission results, identify any remaining fixable failures
- AM: Cherry-pick the highest-impact remaining fix
- **Submission 1**: Final optimized config
- **Submission 2**: Minor variant (test one risky change)
- **Submission 3**: SAVE as safety net for April 4

### Day 5: April 4 -- Deadline day

- AM: If April 3 submission 3 was saved, use it for final attempt
- Only submit if you have a meaningful improvement
- **Submission 1**: Final attempt (if needed)
- PM: Write research report
- 11:59 PM PST: Deadline

### If deadline extends to April 11:

- Days 5-7 (April 4-6): Deep dive on statistical/regression questions (~51 questions worth ~20% of score)
- Days 8-9 (April 7-8): Multi-source question optimization
- Days 10-11 (April 9-10): Latency/cost optimization for score multiplier
- Day 12 (April 11): Final submissions + research report

---

## 6. Risk Mitigation

### Risk 1: DB too large to download during install

- **Impact**: HIGH -- no DB means slow text search, much lower accuracy
- **Mitigation**: Lean DB target is 5-6GB. If too slow to download:
  - Pre-compress with gzip/zstd (expect 60-70% compression on SQLite)
  - Download only essential tables (drop full-text search index, keep structured data)
  - Fallback: ship a ~2GB index-only DB with the most common tables
- **Backup plan**: If DB never works, optimize grep-only path. The old 60% system proved grep alone can get 12/20.

### Risk 2: MCP tools connect but return wrong data

- **Impact**: MEDIUM -- tools work but answers are wrong
- **Mitigation**: Run Tier A questions first (known simple answers). Compare tool output against expected.
- **Backup plan**: The prompt already has grep fallback after 2 MCP failures. Ensure this path is robust.

### Risk 3: Submission results don't match local testing

- **Impact**: MEDIUM -- can't iterate effectively
- **Mitigation**:
  - Run `arena doctor` before each submission
  - Compare exact same questions locally vs submission
  - Check that install.sh properly sets up the environment
- **Backup plan**: If divergence is consistent, trust submission results over local.

### Risk 4: Model generates wrong answer format

- **Impact**: MEDIUM -- correct computation, scored as wrong
- **Mitigation**: Scoring uses 1% fuzzy numeric matching. But format matters:
  - "36080 million" vs "36080" -- does the evaluator parse the "million"?
  - "[0.096, -184.143]" -- bracket list exact format matters
  - "9.89%" -- does evaluator expect "9.89" or "9.89%"?
- **Test**: Submit questions with known answers and verify the evaluator's behavior.
- **Backup plan**: If format is causing failures, add explicit format examples to prompt.

### Risk 5: Iteration exhaustion on complex questions

- **Impact**: MEDIUM -- model uses all 15 iterations without writing answer
- **Mitigation**: "Write early" rule already in prompt. But verify it's working:
  - Check traces: does the model write to /app/answer.txt by iteration 5?
  - If not, make the directive stronger or add it to a skill
- **Backup plan**: Lower max_iterations to 12 to force earlier convergence.

### Risk 6: Visual/chart questions are unsolvable (~10-15 questions)

- **Impact**: LOW-MEDIUM -- ~6% of questions, ~15 points lost
- **Mitigation**: Check if .txt files contain any OCR'd chart descriptions or data tables that correspond to charts.
- **Backup plan**: Accept the loss. Even leaderboard #1 only gets ~37%. These questions may be universally hard.

### Risk 7: Running out of submissions before finding optimal config

- **Impact**: MEDIUM -- 3/day is very limited
- **Mitigation**:
  - Do extensive local testing before each submission
  - Never submit a config you haven't tested locally on at least 5 questions
  - Track what changed between submissions to isolate impact
- **Backup plan**: If deadline extends to April 11, we get 24 more submissions (8 more days x 3).

### Risk 8: Competitor leaps ahead

- **Impact**: LOW -- only our own score matters for ranking
- **Mitigation**: Focus on absolute accuracy, not relative position. Leaderboard #1 is at 103.478 (~37%). If we can hit 50%+ with DB, we're competitive.
- **Target**: 120+ score (roughly 50% accuracy with latency/cost bonus) = top 3.

---

## 7. Key Metrics to Track

| Metric | Target | Current | How to Measure |
|--------|--------|---------|----------------|
| Dev accuracy | 14/20 (70%) | 5/20 (25%) | `arena test --all` |
| Full accuracy | 120/246 (49%) | unknown | `arena submit` results |
| Avg latency | <120s | 218s (grep), 771s (MCP no DB) | From submission results |
| Avg cost/question | <$0.10 | $0.07 | From submission results |
| Score | >120 | unknown | Leaderboard |
| Tier A accuracy | 5/5 | untested with DB | Local test |
| Tier D accepted loss | 0-1/4 | n/a | Accept 3-4 losses |

---

## 8. Quick Reference: Arena CLI Commands

```bash
# Local testing
arena test --smoke                          # 1 random question
arena test --all --tag "my-tag"             # all 20 dev questions
arena test --filter "officeqa-uid0012"      # specific question
arena test -n 5 --tag "quick-check"         # 5 questions
arena test --dry-run                        # validate config only

# Submission
arena submit                                # submit to leaderboard
arena status                                # check submission status
arena results                               # get per-question results
arena history                               # all past submissions
arena leaderboard                           # current standings
arena quota                                 # remaining submissions today

# Debugging
arena doctor                                # diagnostic checks
arena view                                  # open trace viewer for last run
```
