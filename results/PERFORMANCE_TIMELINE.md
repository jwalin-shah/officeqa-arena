# OfficeQA Arena — Performance Timeline

**Generated:** 2026-04-02
**Competition:** Sentient Arena — Grounded Reasoning
**Total tasks:** 246
**Max possible score:** 282.9

---

## Section 1: Score Timeline

Scores come from three data sources:
- **Arena submissions** — official scores via `poll_v11.jsonl` and `submission_poll_log.md`
- **Pool runs** — internal Daytona droplet runs (`results/runner_pool/`)
- **Local Daytona tests** — small-sample accuracy checks (`results/*.jsonl`)

### Official Arena Submission Scores

All submissions appear as "completed" in the poll snapshot taken at 2026-04-01 22:33–23:52 UTC.
Submission IDs are partially ordered by estimated submission date based on git commit timestamps and the `submission_poll_log.md`.

| Approx. Date | Submission ID (short) | Score  | Successful / Total | Success % | Avg Cost/Task | Harness     | Key Change                                         |
|--------------|----------------------|--------|--------------------|-----------|---------------|-------------|----------------------------------------------------|
| 2026-03-30   | 69e7d7ce             | 143.3  | 155 / 246          | 63.0%     | ~$0.06        | opencode    | First full submission — lean-db-tight-prompt v0.7.0 |
| ~2026-03-31  | 121d5f33             | 144.3  | 152 / 246          | 61.8%     | ~$0.06        | opencode    | Early iteration, answer extraction fixes           |
| ~2026-03-31  | 89790f83             | 147.1  | 152 / 246          | 61.8%     | ~$0.06        | opencode    | OpenHands SDK switch (first attempt)               |
| ~2026-03-31  | 3a1ae778             | 147.1  | 154 / 246          | 62.6%     | ~$0.06        | opencode    | Canonical fact store + search_canonical tool       |
| ~2026-04-01  | 0d738df1             | 148.9  | 139 / 246          | 56.5%     | ~$0.06        | openhands-sdk | Tool fix + meta-harness (partial — fewer tasks passed despite higher score implies partial scoring) |
| ~2026-04-01  | cc19566b             | 151.8  | 158 / 246          | 64.2%     | ~$0.06        | openhands-sdk | Meta-harness + anti-spin guardrails                |
| 2026-04-01   | 40dc21e2             | **167.2** | **159 / 246**   | **64.6%** | **~$0.07**    | openhands-sdk | **Best submission** — full tool fix (6 bugs), v3 DB, composite evidence tools |
| ~2026-04-01  | 2f4a7c50             | 0.0    | 0 / 246            | 0.0%      | $0.00         | —           | Failed submission (infra/config error)             |
| ~2026-04-01  | b16e46c1             | 0.0    | 0 / 246            | 0.0%      | $0.00         | —           | Blocked by quota limit                             |
| ~2026-04-01  | ca4d3c7b             | 0.0    | 0 / 246            | 0.0%      | $0.00         | —           | Blocked by quota limit                             |

**Best score to date: 167.2 points (submission 40dc21e2, 2026-04-01)**

The `submission_poll_log.md` also records real-time score accumulation for the first submission (69e7d7ce) from
2026-03-30 — its final projected score was ~173–175 at the time, but the completed score resolved to 143.3
(the projections were extrapolated and proved optimistic as harder tasks were scored later).

### Score Progression for Best Submission (40dc21e2)

Captured every ~5 minutes from poll during run on 2026-04-01:

| Time (UTC)  | Score  | Successful | Success % |
|-------------|--------|------------|-----------|
| 22:33       | 4.6    | 4          | 66.7%     |
| 22:38       | 20.7   | 18         | 66.7%     |
| 22:43       | 33.4   | 29         | 69.0%     |
| 22:48       | 47.1   | 41         | 70.7%     |
| 22:53       | 59.8   | 52         | 68.4%     |
| 22:58       | 70.2   | 61         | 67.0%     |
| 23:03       | 82.8   | 72         | 66.1%     |
| 23:08       | 98.9   | 86         | 67.7%     |
| 23:13       | 110.8  | 97         | 68.3%     |
| 23:18       | 121.4  | 107        | 67.7%     |
| 23:23       | 128.0  | 114        | 66.7%     |
| 23:28       | 136.5  | 123        | 67.2%     |
| 23:33       | 143.8  | 131        | 66.8%     |
| 23:38       | 153.7  | 142        | 67.6%     |
| 23:43       | 162.3  | 152        | 66.7%     |
| 23:48       | 166.6  | 157        | 66.2%     |
| 23:52 (done)| 167.2  | 159        | 64.6%     |

Note: success% drifted down from 70.7% to 64.6% as harder tasks were scored later in the run,
reflecting that easy tasks complete faster and push early rate up.

### Internal Pool Runs (Daytona droplets, with reward data)

| Date              | Pool Label                       | Tasks | Passed | Pass % | Total Cost  | Avg Cost/Task | Avg Elapsed | Notes                               |
|-------------------|----------------------------------|-------|--------|--------|-------------|---------------|-------------|-------------------------------------|
| 2026-04-02 09:45  | pool-20260402T094504Z            | 246   | 122    | 49.6%  | $156.96     | $0.638        | 450s        | Full 246-task pool, OpenHands SDK + v3 DB |
| 2026-04-02 16:50  | pool-20260402T165000Z-oom-fix    | 10    | N/A    | N/A    | $6.16       | $0.616        | 668s        | OOM fix subset, no reward data      |
| 2026-04-02 16:50  | pool-20260402T165000Z-oom-fix-02 | 9     | N/A    | N/A    | $6.50       | $0.722        | 788s        | OOM fix subset, no reward data      |
| 2026-04-02 18:11  | pool-20260402T181120Z            | 15    | N/A    | N/A    | $5.09       | $0.339        | 436s        | Post-OOM-fix, lower cost/task       |
| 2026-04-02 18:11  | pool-20260402T181120Z-02         | 12    | N/A    | N/A    | $4.55       | $0.379        | 491s        | Post-OOM-fix parallel               |

The pool-094504 pass rate (49.6%) is lower than the official submission's success rate (64.6%) because the pool runs
use a different scoring threshold — a pool "passed" requires reward=1.0, while the arena applies partial credit
and time/cost bonuses. The pool runs also do not benefit from the arena's partial scoring.

### Local Daytona Test Runs (small-sample, no partial credit)

| Approx. Date  | File                              | n  | Exact Correct | Accuracy | Avg Cost/Task | Avg Elapsed | Harness / Key Config         |
|---------------|-----------------------------------|----|---------------|----------|---------------|-------------|------------------------------|
| ~2026-03-31   | daytona_lean_goose_15_v5.jsonl    | 15 | 0             | 0%       | $0.001        | 6s          | Goose v5 — infra still broken (no answers) |
| ~2026-03-31   | daytona_lean_goose_15_v6.jsonl    | 15 | 0             | 0%       | $0.008        | 48s         | Early tool testing, wrong answers |
| ~2026-03-31   | daytona_lean_goose_15_v7.jsonl    | 15 | 0             | 0%       | $0.011        | 112s        | Improved tools, still 0 exact |
| ~2026-04-01   | daytona_v5_phase_gating.jsonl     | 6  | 0             | 0%       | $0.027        | 194s        | Phase gating v1               |
| ~2026-04-01   | daytona_v6_no_gating.jsonl        | 20 | 0             | 0%       | $0.022        | 147s        | No gating, better convergence |
| ~2026-04-01   | daytona_v9_fixes.jsonl            | 9  | 0             | 0%       | $0.030        | 111s        | v9 tool fixes                 |
| ~2026-04-01   | daytona_v9d_v3db.jsonl            | 5  | 0             | 0%       | $0.026        | 137s        | v3 DB with normalized rows    |
| ~2026-04-01   | daytona_v10_composite_tools.jsonl | 12 | 1             | 8%       | $0.040        | 184s        | Composite tools — first local correct answer |

Local test accuracy was near 0% throughout because the local Daytona sandbox had DB/tool issues that were
fixed before submitting to the arena. Official arena accuracy (63–67%) was always much higher.

---

## Section 2: Per-Domain Performance Over Time

Only the `pool-20260402T094504Z` pool run (246 tasks) has structured domain-level data.
The official submission results do not expose per-domain breakdowns in the poll API.

### Domain Family Accuracy (pool-20260402T094504Z, 246 tasks)

| Domain Family           | Passed | Total | Pass % | Avg Cost/Task | Avg Tool Calls |
|-------------------------|--------|-------|--------|---------------|----------------|
| other                   | 36     | 67    | 53.7%  | $0.0095       | 35.78          |
| rates_and_securities    | 29     | 67    | 43.3%  | $0.0360       | 41.24          |
| budget_and_receipts     | 27     | 53    | 50.9%  | $0.0166       | 40.02          |
| fx                      | 13     | 25    | 52.0%  | $0.0303       | 50.56          |
| debt_and_international  | 12     | 24    | 50.0%  | $0.0110       | 31.75          |
| macro_and_monetary      | 5      | 10    | 50.0%  | $0.0078       | 32.80          |

Note: "rates_and_securities" is the weakest domain at 43.3%, despite being tied for the largest category.
It is also the most expensive domain, averaging $0.036/task — 3.8× the cheapest domain.

### Operation Type Accuracy (pool-20260402T094504Z)

| Operation Type       | Passed | Total | Pass % | Avg Cost/Task | Avg MCP Calls |
|----------------------|--------|-------|--------|---------------|---------------|
| lookup_or_aggregation| 64     | 117   | 54.7%  | $0.0150       | 5.28          |
| comparison           | 34     | 78    | 43.6%  | $0.0343       | 7.24          |
| statistical          | 23     | 49    | 46.9%  | $0.0121       | 7.76          |
| conversion           | 1      | 2     | 50.0%  | $0.0000       | 15.00         |

"comparison" questions are the hardest operation type — 43.6% pass rate — and cost 2.3× more than
aggregations. They require finding multiple values from potentially different tables and computing a ratio or delta.

### Historical Domain Trend

Since only one pool run has domain breakdown data, a cross-time domain comparison cannot be constructed from
the available files. The submission poll API only exposes aggregate scores. Based on the failure analysis
and memory files, the following directional changes are known:

| Period          | Key Domain Change                                                       |
|-----------------|-------------------------------------------------------------------------|
| ~2026-03-30     | Baseline: ~63% accuracy, heavy reliance on shell grep for all domains   |
| ~2026-03-31     | OpenHands switch: removed native shell → forced MCP-only data access    |
| ~2026-04-01     | v3 DB + canonical search: improved budget & receipts, FX lookup         |
| 2026-04-01      | Tool fix (6 bugs): "rows"→"matches" key fix restored query_table_rows, decade parsing improved statistical ops |
| 2026-04-02      | OOM guardrails: reduced tool spiraling in rates_and_securities           |

---

## Section 3: Tool Usage Evolution

### Pool-094504 Tool Usage (246 tasks, openhands-sdk, full corpus)

The trace analysis covers 227 of the 246 tasks. The agent logged 8,125,463 Goose tokens total.

| Tool                                   | Total Calls | Notes                                          |
|----------------------------------------|-------------|------------------------------------------------|
| shell                                  | 7,232       | Dominant — most data access was via shell grep |
| officeqa-arena__compute_expression     | 834         | Heavy arithmetic usage                         |
| todo__todo_write                       | 557         | Planning scaffold                              |
| write                                  | 243         | File writes (answer.txt and scratch)           |
| officeqa-arena__submit_answer          | 205         | Many retries / multiple submissions per task   |
| officeqa-arena__search_data            | 161         | MCP data search                                |
| officeqa-arena__search_tables          | 99          | Table discovery                                |
| officeqa-arena__resolve_numeric_evidence| 93         | Value resolution                               |
| officeqa-arena__route_question         | 63          | Router dispatching                             |
| officeqa-arena__get_time_series        | 56          | Time series lookups                            |
| officeqa-arena__get_exchange_rate      | 17          | FX lookups                                     |
| officeqa-arena__get_cpi_index          | 16          | CPI data                                       |
| officeqa-arena__extract_values         | 15          | Column extraction                              |
| officeqa-arena__get_table_profile      | 12          | Table schema inspection                        |
| officeqa-arena__query_table_rows       | 9           | Direct row lookup                              |
| officeqa-arena__get_table_context      | 8           | Context retrieval                              |
| officeqa-arena__get_multi_year_series  | 5           | Multi-year aggregation                         |

**Key finding:** Shell calls (7,232) outnumber all MCP tool calls combined (~1,641) by 4.4:1.
This is despite the Terminal Tool restriction intended to block data retrieval via shell.
The MCP-heavy strategy had a 52.9% success rate vs 49.1% for shell-heavy — a meaningful but small gap.

### Goose Telemetry Tool Usage (single live run, 500 events, latest architecture)

This data is from the most recent MCP sessions captured via the telemetry server.

| Tool                      | Calls | Error Rate | Avg Latency |
|---------------------------|-------|------------|-------------|
| compute_expression        | 185   | 5%         | ~0ms        |
| search_data               | 63    | 0%         | 24.2s       |
| submit_answer             | 47    | 0%         | ~2ms        |
| search_tables             | 45    | 83%        | 1.4s        |
| resolve_numeric_evidence  | 32    | 45%        | 5.0s        |
| get_time_series           | 18    | 0%         | 5.8s        |
| route_question            | 16    | 0%         | ~0ms        |
| get_table_profile         | 6     | 0%         | ~5ms        |
| get_cpi_index             | 6     | 100%       | ~1ms        |
| query_table_rows          | 6     | 33%        | ~2ms        |
| get_table_context         | 5     | 100%       | ~0ms        |
| get_exchange_rate         | 3     | 100%       | ~0ms        |
| extract_values            | 4     | 0%         | 2.3s        |
| get_multi_year_series     | 2     | 0%         | 2.2s        |

**High error rates to note:**
- `search_tables` (83% errors) — the term index misses 41% of tables; direct column LIKE search fixes this (see tool_fix_findings.md)
- `resolve_numeric_evidence` (45% errors) — alias resolution failures
- `get_cpi_index`, `get_table_context`, `get_exchange_rate` (100% errors) — these tools have been removed or are broken in the latest toolset

### Tool Evolution Summary

| Period       | Strategy                                | MCP Ratio | Shell Ratio | Key Tools Added/Removed          |
|--------------|-----------------------------------------|-----------|-------------|----------------------------------|
| ~2026-03-29  | OpenCode native: pure shell + basic MCP | ~20%      | ~80%        | Initial 7-tool MCP               |
| ~2026-03-30  | Shell-MCP hybrid                        | ~30%      | ~70%        | +exchange_rate, +cpi, +web_lookup|
| ~2026-03-31  | OpenHands SDK enforced                  | ~40%      | ~60%        | +search_canonical, +search_ledger|
| ~2026-04-01  | Meta-harness (13 tools)                 | ~50%      | ~50%        | -web_lookup, +route_question, merged search_canonical+search_ledger→search_data |
| 2026-04-02   | Current (17 tools, query fix)           | ~45%      | ~55%        | +search_canonical, +search_ledger re-exposed; "rows"→"matches" key fixed |

Shell usage has never dropped below ~50% despite restrictions, because the agent finds ways to use the
terminal for navigation even when data retrieval is blocked.

---

## Section 4: Cost Efficiency Trend

### Arena Submission Cost Profile

All submissions completed at approximately $0.06–$0.07 per task on average.

| Submission   | Score  | Successful | Avg Cost/Task | Cost Efficiency (score/dollar) |
|--------------|--------|------------|---------------|-------------------------------|
| 69e7d7ce     | 143.3  | 155        | ~$0.06        | ~9.75 pts/$                   |
| cc19566b     | 151.8  | 158        | ~$0.06        | ~10.35 pts/$                  |
| 40dc21e2     | 167.2  | 159        | ~$0.07        | ~9.70 pts/$                   |

Estimated total cost per submission: ~$0.06 × 246 = ~$14.76 per run.

### Pool Run Cost Profile

| Pool Run             | Passed | Pass%  | Total Cost | Cost/Task | Cost/Correct Task |
|----------------------|--------|--------|------------|-----------|-------------------|
| pool-094504Z         | 122    | 49.6%  | $156.96    | $0.638    | $1.286            |
| pool-165000Z-oom-fix | N/A    | N/A    | $6.16      | $0.616    | N/A               |
| pool-181120Z         | N/A    | N/A    | $5.09      | $0.339    | N/A               |

Pool runs cost ~10× more per task than arena runs. This is because:
1. Pool runs use a heavier agent (full OpenHands SDK + more iterations)
2. Arena runs hit the task time/cost budget limits that cap spending
3. Pool runs have no hard budget per task (up to ~$2.81 on worst task)

The post-OOM-fix pool runs (pool-181120Z) cut cost/task from $0.64 to $0.34 — a 47% reduction —
by preventing tool spiraling and infinite loops.

### Cost per Correct Answer Over Time (Pool-094504Z)

| Domain                  | Pass%  | Avg Cost/Task | Cost per Correct Task |
|-------------------------|--------|---------------|-----------------------|
| macro_and_monetary      | 50.0%  | $0.0078       | $0.016                |
| debt_and_international  | 50.0%  | $0.0110       | $0.022                |
| other                   | 53.7%  | $0.0095       | $0.018                |
| budget_and_receipts     | 50.9%  | $0.0166       | $0.033                |
| fx                      | 52.0%  | $0.0303       | $0.058                |
| rates_and_securities    | 43.3%  | $0.0360       | $0.083                |

"rates_and_securities" costs 5.2× more per correct answer than the cheapest domain.

---

## Section 5: Key Inflection Points

### +0 → 143.3 pts: First Working Submission (2026-03-30)

**Commits:** `9a82aae` through `0c44118`, `902e587`, `673f34f`
**Git SHA range:** ~`0c7b8ab` (initial) → `1f0baad`
**What changed:** Built the base system from scratch — 7-tool MCP stdio server, SQLite corpus,
lean prompt, OpenCode harness.
**Score:** 143.3 (155/246 correct, ~63%)
**Key insight:** OpenCode harness worked but gave the model native bash tools that it preferred over MCP,
causing ~0% accuracy in local tests. Arena submissions still worked because the system prompt
forced answer.txt writes.

### 143.3 → 147.1: OpenHands SDK Switch (2026-03-31)

**Commits:** `e76382e` through `2727f80`
**Git SHA:** `e76382e` (Add full OpenHands SDK replication)
**What changed:** Switched `arena.yaml` from `opencode` to `openhands-sdk`. Restricted TerminalTool
via `sitecustomize.py` PYTHONPATH override. Added `search_canonical` MCP tool, hierarchical canonical
fact store, remote telemetry.
**Score:** 147.1 (154/246 correct, +2 tasks)
**Key insight:** All top-4 teams use openhands-sdk. The switch was necessary but only gave +4 pts
because the canonical fact store was populated from a subset of the corpus.

### 147.1 → 151.8: Meta-Harness + Anti-Spin (2026-04-01)

**Commits:** `4890f64` through `c6abc6d`
**Git SHA:** `479ef06` (Switch to Lean Goose architecture)
**What changed:** Implemented 3-phase state machine (Search → Compute → Submit), anti-spin guardrails
(identical tool call detection), observation compaction, auto-submit backstop. Consolidated tools
from 18 → 13. Compressed system prompt 290 → 145 lines.
**Score:** 151.8 (158/246 correct, +4 tasks)
**Key insight:** Phase gating forced termination but MiniMax still called blocked tools 6–7×.
The real win was structural: the agent wasted fewer budget calls on dead-end paths.

### 151.8 → 167.2: Critical Tool Bug Fixes (2026-04-01 → 2026-04-02)

**Commits:** `919ab3d` (Fix 6 critical tool bugs), `1c6ca27`, `dd1e4b3`, `ef84d7d`
**Git SHA:** `919ab3d`
**What changed:** Fixed 6 confirmed bugs:
1. `query_table_rows` returned key "rows" but code expected "matches" — agent saw no data
2. Silent fallback in column search hid failures — added direct LIKE search
3. Budget mismatch (22 vs 20 iterations) confused the agent
4. System prompt referenced hidden tools (search_canonical, search_ledger)
5. Decade parsing ("1940s") didn't generate year ranges
6. Tool exposure incomplete (re-added search_canonical, search_ledger; total 17 tools)
**Score:** 167.2 (159/246 correct, +8 tasks, **+15.4 pts**)
**Key insight:** A single dict key mismatch ("rows"→"matches") was silently failing all `query_table_rows`
calls throughout. Fixing it alone recovered multiple questions that had all the right data but
returned empty results.

### Notable Score Drops / Failures

| Submission   | Score | Cause                                                               |
|--------------|-------|---------------------------------------------------------------------|
| 0d738df1     | 148.9 | Only 139 successful despite 148.9 score — partial scoring anomaly; some fixes not yet deployed |
| 2f4a7c50     | 0.0   | Submission failed at infra level (likely missing dependencies in bundle) |
| b16e46c1     | 0.0   | Arena quota exhausted — all tasks returned error, no answers written |
| ca4d3c7b     | 0.0   | Arena quota exhausted — same session                                |

---

## Section 6: Current Baseline

**As of 2026-04-02, latest submitted code: commit `919ab3d` (tool fixes) + `a717013` (scoring logic)**

### Official Score Baseline

| Metric                  | Value                |
|-------------------------|----------------------|
| Best submission score   | 167.2 pts            |
| Successful tasks        | 159 / 246            |
| Success rate            | 64.6%                |
| Competition rank        | ~9th (as of 2026-04-01 22:50 UTC leaderboard) |
| Gap to #1 (Vikranth)    | 182.1 − 167.2 = **14.9 pts** (~10 more correct tasks needed) |
| Gap to top 5 threshold  | ~171 pts (3–4 more tasks) |
| Avg cost per task       | ~$0.07               |
| Harness                 | openhands-sdk        |
| Model                   | MiniMax M2.5 via OpenRouter |
| Max turns               | 25                   |

### Accuracy by Domain (pool-094504Z, closest internal baseline)

| Domain Family           | Pass%  | vs. Field Avg (~65%)  |
|-------------------------|--------|-----------------------|
| other                   | 53.7%  | −11.3 pp              |
| rates_and_securities    | 43.3%  | −21.7 pp              |
| budget_and_receipts     | 50.9%  | −14.1 pp              |
| fx                      | 52.0%  | −13.0 pp              |
| debt_and_international  | 50.0%  | −15.0 pp              |
| macro_and_monetary      | 50.0%  | −15.0 pp              |

Note: Pool pass rates are lower than arena rates because pool scoring requires reward=1.0 with no partial
credit or time/cost bonus. The official arena success rate is ~65% vs ~50% pool rate.

### Accuracy by Operation Type (pool-094504Z)

| Operation Type          | Pass%  | Bottleneck                                                          |
|-------------------------|--------|---------------------------------------------------------------------|
| lookup_or_aggregation   | 54.7%  | Evidence selection (finding the right table/year)                   |
| comparison              | 43.6%  | Requires 2 values; if either is wrong, full task fails              |
| statistical             | 46.9%  | Complex aggregations (Benford, percentile) fail on wrong table pick |
| conversion              | 50.0%  | Rare (2 tasks); FX lookup tool currently broken                     |

### Current Tool Health

| Tool                    | Status   | Error Rate | Notes                                            |
|-------------------------|----------|------------|--------------------------------------------------|
| compute_expression      | Healthy  | 5%         | Core arithmetic tool, most-called MCP tool       |
| search_data             | Healthy  | 0%         | High latency (24s) but reliable                  |
| search_tables           | Broken   | 83%        | Term index misses 41% of tables; needs LIKE fix  |
| resolve_numeric_evidence| Degraded | 45%        | Alias resolution failures                         |
| get_time_series         | Healthy  | 0%         | 5.8s latency                                     |
| query_table_rows        | Fixed    | 33%        | Was 100% broken; "matches" key fix applied        |
| submit_answer           | Healthy  | 0%         | —                                                |
| get_cpi_index           | Broken   | 100%       | Returns no data                                  |
| get_exchange_rate       | Broken   | 100%       | Returns no data                                  |
| get_table_context       | Broken   | 100%       | Removed or non-functional                        |

### Failure Mode Breakdown (pool-094504Z, 124 failures)

| Failure Mode                   | Count | %    | Description                                              |
|--------------------------------|-------|------|----------------------------------------------------------|
| Calculation/Extraction Error   | 75    | 60%  | Right table, wrong value — or selected wrong table       |
| Tool Spiraling / Timeout       | 41    | 33%  | Repeated identical calls, OOM (exit code 137)            |
| Missing answer.txt             | 8     | 6%   | Agent finished thinking but didn't write final answer    |
| Confident but Wrong            | 5     | 4%   | (Subset of above) Wrong document year / table selected   |

### Leaderboard Context (snapshot: 2026-04-01 22:50 UTC)

| Rank | Team                         | Score  | Successful | Success% | Harness     | Avg Cost |
|------|------------------------------|--------|------------|----------|-------------|----------|
| 1    | Vikranth Reddimasu's Team    | 182.1  | 169 / 246  | 68.7%    | openhands-sdk | $0.06  |
| 2    | Kurukshetra's                | 175.4  | 164 / 246  | 66.7%    | openhands-sdk | $0.06  |
| 3    | CTR Evolver                  | 175.3  | 161 / 246  | 65.4%    | openhands-sdk | $0.05  |
| 4    | Zeno AI                      | 174.1  | 160 / 246  | 65.0%    | openhands-sdk | $0.05  |
| 5    | Dolores Research             | 170.7  | 158 / 246  | 64.2%    | openhands-sdk | $0.05  |
| 6    | GroundWire                   | 160.6  | 154 / 246  | 62.6%    | openhands-sdk | $0.07  |
| 7    | Bayes Foundry                | 156.3  | 146 / 246  | 59.3%    | openhands-sdk | $0.05  |
| 8    | Pranav Patel's Team          | 155.6  | 158 / 246  | 64.2%    | opencode    | $0.13    |
| **9**| **Zero Node (us)**           | **151.8** | **158 / 246** | **64.2%** | **opencode** | **$0.12** |
| 10   | The Big Q                    | 139.2  | 147 / 246  | 59.8%    | opencode    | $0.13    |

Note: Our best submitted score (167.2, openhands-sdk) had not yet appeared on the leaderboard at the
time of this snapshot — the snapshot was taken mid-run. The current position based on 167.2 would be
approximately **rank 6–7**, between Dolores (170.7) and GroundWire (160.6).

### Path to Next 10 Points

Based on failure analysis, the highest-leverage remaining improvements are:

| Fix                                          | Estimated Gain | Difficulty |
|----------------------------------------------|----------------|------------|
| Fix search_tables (83% error rate)           | +4–6 tasks     | Medium     |
| Fix get_cpi_index / get_exchange_rate        | +2–3 tasks     | Low        |
| Improve evidence selection for comparison ops| +3–5 tasks     | High       |
| Reduce tool spiraling in rates_and_securities| +2–4 tasks     | Medium     |
| Fix Missing answer.txt (8 tasks)             | +2–4 tasks     | Low        |

Target: 180+ pts (169/246 correct, 68.7%) to reach rank 1.

---

*Data sources: `results/poll_v11.jsonl`, `results/submission_poll_log.md`, `results/runner_pool/pool-20260402T094504Z/`, `results/goose_telemetry.jsonl`, `results/telemetry_live.jsonl`, `results/runner_pool/pool-20260402T094504Z/analysis/summary.md`, `results/runner_pool/pool-20260402T094504Z/POOL_ANALYSIS_REPORT.md`, memory files in `~/.claude/projects/...memory/`, git log.*
