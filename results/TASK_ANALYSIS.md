# OfficeQA Arena — Per-Task Telemetry Analysis
**Pool:** pool-20260402T094504Z
**Date:** 2026-04-02
**Source data:** trace_index.csv (246 tasks), deep_trials/reports/ (246 JSON), officeqa_full.csv

---

## Overview

| Metric | Value |
|---|---|
| Total tasks | 246 |
| Passed | 122 (49.6%) |
| Failed | 124 (50.4%) |
| Easy tasks (passed / total) | 68 / 113 (60.2%) |
| Hard tasks (passed / total) | 54 / 133 (40.6%) |
| Avg tool calls — passed | 32.1 total / 5.9 MCP |
| Avg tool calls — failed | 46.1 total / 7.0 MCP |
| Tasks with exceptions | 19 |
| Pool cost | $156.96 |

---

## Section 1: Task Difficulty Tiers

> Note: this pool is a single-shot run (one trial per task), so there is no cross-run pass-rate variance. Tiers are inferred from difficulty label, tool count, and answer proximity.

### Tier A — Passed (122 tasks)

Likely reliably solvable given the agent passed on one shot.

```
UID0002, UID0003, UID0004, UID0005, UID0006, UID0009, UID0010, UID0017, UID0023, UID0024,
UID0031, UID0032, UID0033, UID0039, UID0040, UID0041, UID0042, UID0043, UID0047, UID0048,
UID0050, UID0051, UID0052, UID0054, UID0057, UID0059, UID0061, UID0063, UID0064, UID0065,
UID0067, UID0068, UID0070, UID0072, UID0073, UID0074, UID0075, UID0078, UID0080, UID0083,
UID0084, UID0086, UID0087, UID0088, UID0090, UID0093, UID0095, UID0097, UID0099, UID0100,
UID0103, UID0106, UID0107, UID0109, UID0111, UID0112, UID0116, UID0119, UID0130, UID0131,
UID0134, UID0136, UID0137, UID0139, UID0142, UID0143, UID0145, UID0147, UID0148, UID0151,
UID0152, UID0155, UID0160, UID0162, UID0163, UID0164, UID0167, UID0169, UID0171, UID0173,
UID0174, UID0176, UID0177, UID0178, UID0180, UID0181, UID0184, UID0185, UID0186, UID0187,
UID0189, UID0192, UID0194, UID0195, UID0197, UID0198, UID0199, UID0200, UID0202, UID0203,
UID0204, UID0205, UID0206, UID0211, UID0212, UID0214, UID0217, UID0218, UID0220, UID0221,
UID0224, UID0225, UID0228, UID0229, UID0230, UID0231, UID0232, UID0234, UID0235, UID0236,
UID0241, UID0242
```

### Tier B — "Sometimes Pass" / Borderline (12 tasks)

Failed with a wrong answer that was within 5% of the correct value. These are fragile passes — close but not close enough. High-priority targets for rounding or data-selection fixes.

| UID | Expected | Submitted | % Error | Domain |
|---|---|---|---|---|
| UID0079 | 11.73% | 11.60 | 1.1% | rates_and_securities |
| UID0098 | 14.166 | 14.335 | 1.2% | rates_and_securities |
| UID0018 | 81.406 | 80.262 | 1.4% | budget_and_receipts |
| UID0049 | 1.56 | 1.59 | 1.9% | rates_and_securities |
| UID0141 | 0.3535 | 0.3604 | 1.95% | other |
| UID0159 | 39.31 | 38.5 | 2.1% | fx |
| UID0207 | 0.058 | 0.06 | 3.5% | rates_and_securities |
| UID0038 | 2382 | 2293 | 3.7% | debt_and_international |
| UID0060 | 13.009% | 12.497 | 3.9% | other |
| UID0029 | 0.88525 | 0.84758 | 4.3% | rates_and_securities |
| UID0089 | -118255.5 | -112960.75 | 4.5% | budget_and_receipts |
| UID0210 | 0.84 | 0.88 | 4.8% | debt_and_international |

### Tier C — "Always Fail" (current run) — 112 tasks

Failed with a wrong answer not in the borderline range above, or failed to submit, or timed out. Listed below by sub-category.

```
UID0001, UID0007, UID0008, UID0011, UID0012, UID0013, UID0014, UID0015, UID0016, UID0019,
UID0020, UID0021, UID0022, UID0025, UID0026, UID0027, UID0028, UID0030, UID0034, UID0035,
UID0036, UID0037, UID0044, UID0045, UID0046, UID0053, UID0055, UID0056, UID0058, UID0062,
UID0066, UID0069, UID0071, UID0076, UID0077, UID0081, UID0082, UID0085, UID0091, UID0092,
UID0094, UID0096, UID0101, UID0102, UID0104, UID0105, UID0108, UID0110, UID0113, UID0114,
UID0115, UID0117, UID0118, UID0120, UID0121, UID0122, UID0123, UID0124, UID0125, UID0126,
UID0127, UID0128, UID0129, UID0132, UID0133, UID0135, UID0138, UID0140, UID0144, UID0146,
UID0149, UID0150, UID0153, UID0154, UID0156, UID0157, UID0158, UID0161, UID0165, UID0166,
UID0168, UID0170, UID0172, UID0175, UID0179, UID0182, UID0183, UID0188, UID0190, UID0191,
UID0193, UID0196, UID0201, UID0208, UID0209, UID0213, UID0215, UID0216, UID0219, UID0222,
UID0223, UID0226, UID0227, UID0233, UID0237, UID0238, UID0239, UID0240, UID0243, UID0244,
UID0245, UID0246
```

### Tier D — "Never Attempted" / Timeout before answer (3 tasks)

These tasks timed out within the first few tool calls — the agent appeared to hang or the MCP server stalled before substantive work began.

| UID | Tools Called | Elapsed | Notes |
|---|---|---|---|
| UID0001 | 2 (tree, todo) | 138s | Called `tree` then stalled waiting for corpus response |
| UID0011 | 1 (tree) | 65s | Single `tree` call then timeout; 42-second question |
| UID0153 | 4 (search_data, search_tables, analyze) | 75s | `analyze` tool caused OOM/hang |

---

## Section 2: Easy Wins (Currently Failing, Should Be Easy)

45 tasks are labeled "easy" but failed. The highest-ROI subset are those that submitted a wrong answer with a diagnosable root cause.

### 2.1 Sign Error (1 task) — Trivial to fix

| UID | Expected | Submitted | Root Cause |
|---|---|---|---|
| UID0132 | 73985 | -73985 | Agent computed deficit as negative; question asked for the magnitude. Absolute value wrapper would fix this. |

**Question:** Average nominal U.S. federal budget deficit for FY1994–1996 Q1, in millions USD.

### 2.2 Scale / Unit Error (1 task)

| UID | Expected | Submitted | Root Cause |
|---|---|---|---|
| UID0125 | 104193994.3 | 104194.0 | Agent reported answer in millions when source data was in thousands. Off by exactly 1000×. |

**Question:** Average of ESF total assets for September 2010–2012 in thousands of USD.

### 2.3 Computation Formula Error (easy tasks with low tool counts)

These submitted an answer but used the wrong formula or wrong variant of a statistic. The data retrieval worked; the math didn't.

| UID | Expected | Submitted | Root Cause |
|---|---|---|---|
| UID0066 | 1.967 | 0.508 | Pareto tail exponent: agent likely submitted the Hill estimator reciprocal (1/α vs α). |
| UID0091 | 0.105 | 2.574 | Constant hazard rate: agent used wrong formula (likely solved for rate in wrong direction). |
| UID0104 | 1.505 | 1.297 | Fisher-Pearson adjusted skewness: agent used unadjusted formula or wrong n. |
| UID0157 | 155276 | 5276 | Absolute difference: agent likely subtracted wrong direction and dropped a digit. Off by 150000. |
| UID0239 | 0.045 | 4.828 | Continuous rate of change: agent submitted ln(V2/V1) without dividing by time period (in months), off by 2-year factor. |
| UID0146 | 3.26 | 2.81 | Ratio of marketable to non-marketable Treasury debt: agent likely included wrong category. |
| UID0082 | 5.3 | 8.3 | Absolute percentage point change: agent computed from wrong year-end or wrong "held by public" definition. |

### 2.4 Data Selection Error (easy tasks — found data but wrong table/row)

| UID | Expected | Submitted | Root Cause |
|---|---|---|---|
| UID0081 | $23,918,635 | 22,565,547 | Submitted marketable debt excluding one category (e.g., missed TIPS or FRNs). Off by ~$1.35T. |
| UID0046 | 69% | 75 | Read wrong percentage from chart — chart is read, but agent interpolated/selected wrong data point. |
| UID0016 | 93,349 million | 89,256 | Federal interest cost for CY1981 — agent used wrong fiscal/calendar year boundary. |
| UID0045 | 3 | 0 | Claims on Zaire 1997: agent returned 0 (likely found no claims, missed the correct table). |
| UID0157 | 155276 | 5276 | Excise tax difference: agent may have found wrong fiscal year data. |

### 2.5 No Submit — Gave Up Before Answering (easy tasks)

| UID | Expected | Notes |
|---|---|---|
| UID0020 | 0.00262 | KL divergence computation — agent spiraled through compute_expression calls, never submitted |
| UID0138 | 1.600 | TSP payroll deduction percentage — agent did 25 shell calls, never committed to an answer |
| UID0115 | 136137 | Foreign currency total — 45 tool calls, no submit |

---

## Section 3: Tool Pattern Correlations

### 3.1 Tool Volume

| Metric | Passed | Failed | Ratio |
|---|---|---|---|
| Avg total tool calls | 32.1 | 46.1 | 1.44× more tools when failing |
| Avg MCP tool calls | 5.9 | 7.0 | 1.19× more MCP calls when failing |
| submit_answer usage | 92% of passing tasks | 75% of failing tasks | Failing tasks don't even submit 25% of the time |

**Key insight:** Failing tasks use 44% more total tool calls. The excess is almost entirely in `shell` calls — agents spiral through grep/ls/tree loops rather than using structured MCP tools.

### 3.2 MCP Tool Usage per Task (Passed vs Failed)

| Tool | Pass avg/task | Fail avg/task | Interpretation |
|---|---|---|---|
| `compute_expression` | 2.94 | 3.83 | Used more when failing → more retries of wrong calculations |
| `search_data` | 0.62 | 0.69 | Slightly more when failing → multiple fruitless search attempts |
| `resolve_numeric_evidence` | 0.30 | 0.45 | More resolution attempts when failing — evidence isn't found on first try |
| `submit_answer` | 0.92 | 0.75 | **Critical: 25% of failing tasks never call submit_answer** |
| `get_exchange_rate` | 0.08 | 0.06 | Used more in passing tasks for FX questions |
| `get_table_context` | 0.04 | 0.02 | Used 2× more in passing tasks — suggests it helps when used |

### 3.3 Tool Sequences Correlated with Success

**Pattern A — Structured retrieval + quick compute (highest success rate):**
```
search_data → resolve_numeric_evidence → compute_expression → submit_answer
```
Example: UID0002 (passed, 507), UID0099 (passed, 9732.50)
- Characteristically low total tool count (10–20 total)
- 1–2 search_data calls, 1 resolve_numeric_evidence, 1–3 compute_expression

**Pattern B — Shell-light with direct compute:**
```
shell (≤10 calls) → compute_expression (1–3) → submit_answer
```
Example: UID0163 (passed, -75), UID0152 (passed, 451), UID0086 (passed, 4.815)
- Clean extraction, minimal exploration

**Pattern C — MCP tool chain:**
```
route_question → search_data → get_time_series → compute_expression → submit_answer
```
Example: UID0099 (passed), UID0134 (passed)
- Works well for time-series lookup questions

### 3.4 Tool Sequences Correlated with Failure

**Anti-pattern A — Shell spiral (most common):**
```
shell → shell → shell → ... (>50 calls) → [no submit or wrong submit]
```
Examples: UID0179 (210 shell calls), UID0122 (111+), UID0114 (117+)
- Agent repeatedly greps/ls/trees without converging
- Accounts for 31 of 124 failures (25%)

**Anti-pattern B — Repeated resolve_numeric_evidence with no progress:**
```
search_data → resolve_numeric_evidence → shell → search_data → resolve_numeric_evidence → ...
```
- Agent can't find the right table, bounces between search and resolve
- Common in `rates_and_securities` domain failures

**Anti-pattern C — analyze tool call (causes hang):**
```
search_data → analyze → [timeout/OOM]
```
- `analyze` tool appears to cause OOM or indefinite hang
- Seen in UID0153 (75s timeout after 4 tools)

### 3.5 Domain-Level Pass Rates

| Domain | Pass Rate | Avg Tool Calls | Notes |
|---|---|---|---|
| other | 53.7% (36/67) | 35.8 | Best performer; varied question types |
| budget_and_receipts | 50.9% (27/53) | 40.0 | Solid but many comparison failures |
| fx | 52.0% (13/25) | 50.6 | High tool count; FX lookup is expensive |
| debt_and_international | 50.0% (12/24) | 31.8 | Even split |
| macro_and_monetary | 50.0% (5/10) | 32.8 | Small sample |
| rates_and_securities | **43.3% (29/67)** | 41.2 | **Worst domain — 38 failures** |

### 3.6 Operation-Level Pass Rates

| Operation | Pass Rate | Avg MCP Calls | Notes |
|---|---|---|---|
| lookup_or_aggregation | 54.7% (64/117) | 5.28 | Best operation type |
| conversion | 50.0% (1/2) | 15.0 | Too small to judge |
| statistical | 46.9% (23/49) | 7.76 | High MCP usage, lower success |
| comparison | **43.6% (34/78)** | 7.24 | **Worst operation — requires finding 2+ data points** |

---

## Section 4: Failure Signatures

### 4.1 Tool Spiral (31 tasks, 25% of all failures)

Agent entered a repetitive loop of shell commands, never converging on an answer. High tool counts (>60) with either no submit or a wrong submit.

**Spiral + no answer (15 tasks):**
`UID0007, UID0013, UID0014, UID0021, UID0034, UID0053, UID0056, UID0069, UID0114, UID0118, UID0144, UID0179, UID0182, UID0216, UID0223`

Extreme cases: UID0179 (210 tools), UID0122 (134 tools), UID0114 (126 tools), UID0037 (119 tools), UID0096 (117 tools), UID0126 (116 tools).

**Spiral + wrong answer (16 tasks):**
`UID0018, UID0026, UID0037, UID0038, UID0071, UID0089, UID0096, UID0122, UID0126, UID0129, UID0140, UID0159, UID0161, UID0168, UID0193, UID0219`

Root cause: Agent repeatedly greps for keywords in corpus text files without using structured MCP tools. Gets partial data, computes wrong answer, submits.

### 4.2 Wrong Answer — Calculation Error (75 tasks, 60% of all failures)

Agent found data but computed the wrong value. Sub-categories:

- **Close but wrong (within 5%):** 12 tasks — rounding, formula variant, or boundary year issue
- **Sign error:** 1 task (UID0132)
- **Scale/unit error:** 1 task (UID0125, off by 1000×)
- **Wrong formula:** ~15 tasks (Pareto, hazard rate, skewness, etc.)
- **Data selection error:** ~20 tasks (wrong year, wrong category, wrong table)
- **Wildly wrong:** ~26 tasks

### 4.3 Timeout — asyncio.wait_for exceeded (16 tasks, 13% of all failures)

All 19 exception-type failures trace back to `asyncio.wait_for` timeout in the arena harness. 16 of 19 hit the 900s wall-clock limit. 3 timed out very early (UID0001 at 138s, UID0011 at 65s, UID0153 at 75s) — these likely stalled due to a hung MCP call or OOM during a large tool operation.

**Hard tasks timed out:** UID0007, UID0022, UID0027, UID0028, UID0053, UID0114, UID0118, UID0161, UID0165, UID0179, UID0188, UID0216
**Easy tasks timed out:** UID0014, UID0021, UID0034, UID0208

### 4.4 No Submit / Missing Answer (14 tasks, 11% of all failures)

Agent completed exploration but never wrote `/app/answer.txt` or called `submit_answer`. Often a sign the agent ran out of budget, lost track of the task goal, or had no confidence in its result.

`UID0015, UID0020, UID0113, UID0115, UID0127, UID0138, UID0149, UID0190, UID0201`
(plus 5 with exceptions that also had no submit)

### 4.5 Exception / Crash (3 early-failure tasks)

- **UID0001:** Called `tree` then hung — likely waiting for MCP response to very large directory listing. 2 tools, 138s.
- **UID0011:** Called `tree` only. 1 tool, 65s. Question asking for a specific page number — agent hadn't started real work yet when it died.
- **UID0153:** Called `analyze` tool which caused OOM/hang. 4 tools, 75s.

---

## Section 5: Priority Fix List

Ordered by estimated impact × likelihood of being fixable. Score formula: `difficulty_score (easy=3, hard=1) × mode_score × tool_score (low tools = higher)`.

| Rank | UID | Score | Mode | Diff | Tools | Expected | Submitted | Fix Hypothesis |
|---|---|---|---|---|---|---|---|---|
| 1 | UID0011 | 27 | timeout_early | easy | 1 | 42 | NONE | Agent calls `tree` and hangs; block `tree` or add timeout on large dir listing |
| 2 | UID0046 | 27 | wrong_answer | easy | 17 | 69% | 75 | Agent read wrong percentage from chart; improve chart/image data extraction guidance |
| 3 | UID0081 | 27 | wrong_answer | easy | 16 | $23,918,635 | 22,565,547 | Exclude marketable debt: agent summed wrong categories; add category disambiguation prompt |
| 4 | UID0153 | 27 | timeout_early | easy | 4 | 0.92 | NONE | `analyze` tool hangs; remove or rate-limit `analyze` calls |
| 5 | UID0079 | 24 | close_wrong | easy | 23 | 11.73% | 11.60 | Coefficient of variation: 1.1% off; likely rounding or boundary issue — fix rounding instruction |
| 6 | UID0141 | 24 | close_wrong | easy | 29 | 0.3535 | 0.3604 | Treasury Notes share: 1.95% off; agent likely used wrong year boundary (March weekday) |
| 7 | UID0060 | 18 | wrong_answer | easy | 36 | 13.009% | 12.497 | CAGR formula: agent used wrong number of periods (Korean War year ambiguity) |
| 8 | UID0066 | 18 | wrong_answer | easy | 13 | 1.967 | 0.508 | Pareto exponent: agent returned 1/α instead of α (reciprocal error) |
| 9 | UID0082 | 18 | wrong_answer | easy | 17 | 5.3 | 8.3 | Treasury debt share change: agent used wrong base year or wrong "public" definition |
| 10 | UID0091 | 18 | wrong_answer | easy | 13 | 0.105 | 2.574 | Hazard rate: agent solved ln(V2/V1)/t in wrong direction (inverted sign or period) |
| 11 | UID0104 | 18 | wrong_answer | easy | 11 | 1.505 | 1.297 | Fisher-Pearson skewness: agent used unadjusted or non-adjusted formula; add explicit formula |
| 12 | UID0125 | 18 | wrong_answer | easy | 17 | 104193994.3 | 104194.0 | Unit error: answer is correct ÷1000; add "check units match question's requested units" |
| 13 | UID0132 | 18 | wrong_answer | easy | 15 | 73985 | -73985 | Sign error on deficit: add "return magnitude when question says 'deficit amount'" |
| 14 | UID0146 | 18 | wrong_answer | easy | 12 | 3.26 | 2.81 | Debt ratio: agent included wrong categories; improve table disambiguation for Oct 1959 |
| 15 | UID0157 | 18 | wrong_answer | easy | 6 | 155276 | 5276 | Excise tax difference: off by 150000 — agent likely found one year but not the other |
| 16 | UID0210 | 18 | wrong_answer | easy | 27 | 0.84 | 0.88 | CPI-adjusted z-score: 4.76% off; likely CPI year mismatch or rounding in adjustment |
| 17 | UID0239 | 18 | wrong_answer | easy | 18 | 0.045 | 4.828 | Continuous rate: agent returned ln(V2/V1) without dividing by period length (months) |
| 18 | UID0008 | 12 | wrong_answer | easy | 35 | 73 | 57 | Budget receipts growth: agent found wrong month baseline; add "from the month of X" disambiguation |
| 19 | UID0020 | 12 | no_submit | easy | 21 | 0.00262 | NONE | KL divergence: agent computed but never submitted; add forced-submit guardrail |
| 20 | UID0045 | 12 | wrong_answer | easy | 33 | 3 | 0 | Zaire claims 1997: agent found no data (table lookup failed); improve country alias search |

---

## Key Takeaways

### Highest-Impact Structural Fixes

1. **Block/rate-limit `tree` and `analyze` tools** — UID0001, UID0011, UID0153 died from these. Blocking them recovers 3 tasks including 2 easy ones.

2. **Force submit_answer before timeout** — 14 tasks never submitted. Add a hard rule: at 80% of budget, write best-guess answer to `/app/answer.txt` unconditionally.

3. **Unit/scale validation** — UID0125 was correct ÷1000. A post-compute sanity check ("does submitted value match requested units?") would catch this class.

4. **Sign convention for deficits/changes** — UID0132 got exact magnitude but wrong sign. Adding "report deficit as positive magnitude unless question explicitly asks for signed value" would fix it.

5. **Anti-spiral guardrail** — 31 failures (25%) involved >60 tool calls. A hard cutoff at 50 total shell calls with forced MCP fallback would prevent the worst spirals (UID0179 at 210 calls, etc.).

6. **rates_and_securities domain** — Worst domain at 43.3% pass rate, 38 failures. Many involve reading historical bond tables or computing statistical metrics on yield series. Improving `get_time_series` coverage and disambiguation for bond data would have the highest domain-level ROI.

7. **Close-wrong fixes (Tier B, 12 tasks)** — These tasks need only minor formula adjustments. UID0079 (1.1% off), UID0098 (1.2% off), UID0049 (1.9% off) are statistical/rounding issues likely fixable by clarifying formula instructions (e.g., "use population std dev not sample").
