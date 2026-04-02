# OfficeQA Arena — Roadmap to April 6 Midnight

> Team: 3 members (Jwalin + 2)
> Current: 180.4 pts (68.7% accuracy) | Target: 220+ pts (78%+ accuracy)
> Deadline: April 6, midnight UTC
> Submissions: 3/day (resets midnight UTC = 5 PM PST)
> Strategy: OpenHands SDK for submissions, Goose kept hidden until last day

---

## Priority Framework

We have **4 days** and **~12 submission slots** remaining. Every change must be:
1. **Measurable** — Run against known tasks before submitting
2. **Traceable** — Tagged in git, logged in telemetry
3. **Reversible** — Can roll back if score drops

---

## Day 1: April 3 (Thu) — Infrastructure & Telemetry

**Goal:** Fix the mess. Clean runner scripts, proper logging, change tracking.

### P0: Runner Script Cleanup (Person A)
- [ ] Refactor `scripts/do_runner_pool.sh`:
  - Add structured JSON logging (not just lane*.log plaintext)
  - Add run metadata header: git SHA, prompt hash, config hash, timestamp
  - Add per-task result summary to stdout (task_id, pass/fail, answer, gold, cost, time)
  - Add `--dry-run` flag to validate config without launching
  - Add `--resume` flag to skip already-completed tasks
  - Fix error handling: trap SSH failures, arena CLI crashes, OOM kills
  - Add health checks: verify DB accessible, MCP server responds, API key valid
- [ ] Create `scripts/run_tagged.sh` — wrapper that:
  - Takes a `--tag "description"` argument
  - Records git SHA + dirty status
  - Hashes prompt files and arena.yaml for change detection
  - Creates `results/runs/<tag>-<timestamp>/` with metadata.json
  - Runs pool or single task
  - Auto-generates comparison with previous tagged run

### P0: Telemetry Pipeline Fix (Person B)
- [ ] Fix telemetry server to record:
  - Git SHA of the code that produced each event
  - Prompt file hash (system.j2 or goose_instructions.md)
  - Arena config hash
  - Run tag (links events to a named experiment)
- [ ] Create `scripts/compare_runs.py`:
  - Input: two run tags or directories
  - Output: per-task diff (gained/lost/unchanged), aggregate stats
  - Show which tasks flipped (pass→fail or fail→pass)
  - Identify regressions vs improvements
- [ ] Fix `pull_telemetry.py` to support:
  - `--run-tag` filter
  - `--compare tag1 tag2` mode
  - `--export csv` for spreadsheet analysis

### P1: Change Tracking System (Person C)
- [ ] Create `CHANGELOG.md` format:
  ```
  ## [tag] YYYY-MM-DD HH:MM
  - git: <sha>
  - prompt_hash: <hash>
  - config_hash: <hash>
  - score: X/246 (Y%)
  - delta: +N/-M from previous
  - changes: <what changed>
  - flipped_tasks: <gained>, <lost>
  ```
- [ ] Add pre-submission checklist script `scripts/pre_submit.sh`:
  - Verify git clean (no uncommitted changes)
  - Verify API key valid
  - Verify MCP bundle matches local code
  - Verify DB accessible from container
  - Run 5-question smoke test
  - Print diff from last submission

### P1: Goose Telemetry Validation (Person B)
- [ ] Verify Goose telemetry is actually working:
  - Run 5 tasks with Goose, check telemetry server receives events
  - Verify `TELEMETRY_SOURCE: "goose"` appears in events
  - Confirm trajectory summaries POST to `/trajectory`
  - Ensure goose_telemetry.jsonl is being written
- [ ] Add telemetry source differentiation:
  - OpenHands events tagged `source: "openhands"`
  - Goose events tagged `source: "goose"`
  - Compare tool usage patterns between harnesses

---

## Day 2: April 4 (Fri) — Evidence Selection Improvements

**Goal:** Attack the #1 bottleneck (evidence selection, not arithmetic).

### P0: Improve resolve_numeric_evidence (Person A)
Current: 44.3% task pass rate when used. This is the most impactful tool.
- [ ] Add **candidate reranking** by:
  - Bulletin vintage (prefer newest)
  - Exact vs fuzzy match score
  - Period basis match (fiscal/calendar alignment)
  - Unit consistency with question context
- [ ] Add **disambiguation metadata** to response:
  - Show unit_scale for each candidate
  - Show period_basis for each candidate
  - Show bulletin_year for each candidate
  - Flag when candidates disagree (ambiguous)
- [ ] Fix **year-type confusion**:
  - If question says "fiscal year" but data is calendar → warn in response
  - If question says "calendar year" but data is fiscal → warn in response

### P0: Improve search_data Recall (Person B)
Current: 42.7% task pass rate. Second most-used search tool.
- [ ] Add **synonym expansion** for common terms:
  - "customs" ↔ "customs duties" ↔ "import duties"
  - "defense" ↔ "national defense" ↔ "military" ↔ "war department"
  - "income tax" ↔ "individual income taxes" ↔ "corporation income taxes"
- [ ] Add **year-in-title matching**:
  - "1940 budget" should match tables with 1940 in title or coverage
  - Currently relies on year metadata which is NULL for 41% of tables
- [ ] Improve **result ranking**:
  - Weight exact phrase matches higher
  - Penalize tables where year range doesn't overlap question year

### P1: Comparison Question Fixes (Person C)
Current: 43.6% pass rate (worst operation type). 78 tasks.
- [ ] Analyze top 10 comparison failures from pool run
- [ ] Common patterns:
  - "How much more/less X than Y" → needs two lookups + subtraction
  - "Ratio of X to Y" → needs two lookups + division
  - "Percent change from X to Y" → needs two years + formula
- [ ] Add **comparison helper** to compute_expression:
  - `compare(a, b, op="difference"|"ratio"|"pct_change")`
  - Returns formatted result with sign

### Submit Checkpoint (Evening)
- [ ] Tag: `evidence-rerank-v1`
- [ ] Run 20-task smoke test (mix of domains)
- [ ] If improvement: submit to arena
- [ ] Compare with previous submission using compare_runs.py

---

## Day 3: April 5 (Sat) — Prompt Tuning & Edge Cases

**Goal:** Squeeze accuracy from prompt and tool improvements.

### P0: Prompt A/B Testing (All hands)
- [ ] Prepare 3 prompt variants:
  1. **Baseline:** Current system.j2
  2. **Aggressive-early:** Force answer attempt after 3 tool calls, then refine
  3. **Evidence-lock:** Once data found, lock it in — no more searching
- [ ] Run each against same 50-task subset
- [ ] Pick winner based on: accuracy, cost, time
- [ ] Tag each: `prompt-baseline-v1`, `prompt-early-v1`, `prompt-lock-v1`

### P0: Fix Known Failure Patterns (Person A)
From failure analysis, fix the most common patterns:
- [ ] **Missing answer.txt** (8 failures): Add mandatory write before submit in prompt
- [ ] **Unit scale errors**: Enhance get_table_profile response with bolded unit warning
- [ ] **Fiscal/calendar confusion**: Add explicit FY/CY label in resolve_numeric_evidence response
- [ ] **Decade queries** ("1940s"): Verify decade parsing fix is working in production

### P1: Statistical Question Improvements (Person B)
Current: 46.9% pass rate, 49 tasks.
- [ ] Review compute_expression function list:
  - sum, mean, median, stdev, cagr, correlation, linreg, theil_index, percentile, etc.
- [ ] Add missing computations if any (check question corpus)
- [ ] Improve error messages when expression fails (tell model what went wrong)

### P1: Rates & Securities Domain (Person C)
Current: 43.3% pass rate (worst domain), 67 tasks.
- [ ] Analyze top 10 failures in this domain
- [ ] Common issues: yield curves, interest rates, bond pricing
- [ ] May need specialized table matching for financial instruments

### Submit Checkpoint (Evening)
- [ ] Tag: `prompt-tuned-v1`
- [ ] Run full 246 tasks on pool (or 100-task subset if time-constrained)
- [ ] Submit best variant to arena
- [ ] Document: which tasks flipped, what changed, why

---

## Day 4: April 6 (Sun) — Final Day, Goose Decision, Final Submissions

**Goal:** Maximum score. Decide Goose vs OpenHands. Final submissions.

### Morning: Goose Comparison Run
- [ ] Run Goose harness against same 50-task subset used for OpenHands
- [ ] Compare:
  - Accuracy (pass rate)
  - Cost per task
  - Time per task
  - Failure patterns (different from OpenHands?)
- [ ] **Decision point:** If Goose > OpenHands on these 50 tasks → switch for final submission

### Afternoon: Final Optimizations
- [ ] Cherry-pick best improvements from Days 2-3
- [ ] Run pre-submission checklist
- [ ] Verify telemetry is clean
- [ ] Clear any stale state on runner pool

### Evening: Final Submissions (3 slots)
- [ ] **Submission 1** (early evening): Best OpenHands configuration
  - Tag: `final-openhands-v1`
  - Full 246 tasks
- [ ] **Submission 2** (if Goose competitive): Best Goose configuration
  - Tag: `final-goose-v1`
  - Only if Day 4 morning comparison justifies it
- [ ] **Submission 3** (reserve): Emergency fix or best-of-both
  - Tag: `final-hybrid-v1`
  - Keep one slot for last-minute fixes

---

## Risk Mitigation

### If Score Drops After Changes
- Every change is tagged in git with run results
- Can revert to any previous tag
- compare_runs.py shows exactly which tasks regressed
- Always keep one submission slot in reserve

### If Runner Pool Breaks
- Fallback: Single droplet via `scripts/do_runner.sh`
- Fallback: Local via `scripts/arena_test.sh` (slower)
- Fallback: Daytona sandbox for individual tasks

### If Telemetry Goes Down
- Events still logged locally in goose_telemetry.jsonl
- Can rebuild from .arena/runs/ directories
- Telemetry is fire-and-forget (doesn't block agent)

### If API Key Exhausted
- Monitor via `curl https://openrouter.ai/api/v1/auth/key`
- Budget alert at $50 remaining
- Reduce pool size (4 lanes → 2) if burning too fast

---

## Team Assignment Summary

| Person | Day 1 | Day 2 | Day 3 | Day 4 |
|---|---|---|---|---|
| **A** | Runner cleanup | resolve_numeric_evidence | Fix known failures | Final optimization |
| **B** | Telemetry fix | search_data recall | Statistical questions | Goose comparison |
| **C** | Change tracking | Comparison questions | Rates & securities | Final submissions |

---

## Success Metrics

| Metric | Current | Day 2 Target | Day 3 Target | Final Target |
|---|---|---|---|---|
| Accuracy | 68.7% | 72% | 75% | 78%+ |
| Score | 180.4 | 190 | 200 | 220+ |
| Cost/task | $0.06 | $0.06 | $0.05 | $0.05 |
| Time/task | ~57s | ~50s | ~45s | ~40s |
| Regressions | — | 0 | 0 | 0 |

---

## Non-Goals (Don't Do These)

- Don't add vector search or embeddings (complexity without proven benefit)
- Don't add more tools beyond current 17 (diminishing returns)
- Don't build complex multi-agent systems (MiniMax can't handle it)
- Don't try to fix MiniMax's terminal preference via prompts (structural fix already deployed)
- Don't hardcode answers (banned by competition rules)
- Don't spend time on .arenaignore (known broken, not fixable)
- Don't build auto-generated prompts (manual tuning is more effective)

---

*Last updated: April 2, 2026. Review and update daily.*
