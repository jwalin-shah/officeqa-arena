# OfficeQA Arena — Complete Project History & Analysis

> Last updated: 2026-04-02
> Team: 3 members | Deadline: April 6, midnight UTC

---

## Table of Contents

1. [Competition Overview](#1-competition-overview)
2. [Architecture Evolution](#2-architecture-evolution)
3. [Harness Experiments](#3-harness-experiments)
4. [System Prompt Iterations](#4-system-prompt-iterations)
5. [Tool Development & Fixes](#5-tool-development--fixes)
6. [Database & Ingestion Pipeline](#6-database--ingestion-pipeline)
7. [Infrastructure](#7-infrastructure)
8. [Results & Score History](#8-results--score-history)
9. [Failure Analysis](#9-failure-analysis)
10. [What Works vs What Doesn't](#10-what-works-vs-what-doesnt)
11. [Key Learnings](#11-key-learnings)
12. [Current State](#12-current-state)

---

## 1. Competition Overview

**Competition:** Sentient Arena — Grounded Reasoning track (OfficeQA)
**Dataset:** 246 questions about U.S. Treasury Bulletin data (1915–2016)
**Scoring:** `correct_tasks × (1.0 + cost_adj + time_adj)` — max possible 282.9
**Tolerance:** 1% relative error for numeric answers
**Model:** MiniMax M2.5 via OpenRouter (mandated by arena)
**Harness options:** opencode, codex, goose, openhands-sdk
**Submission limit:** 3 per day (resets midnight UTC = 5 PM PST)

### Question Breakdown
| Difficulty | Count | % |
|---|---|---|
| Easy | ~113 | 46% |
| Hard | ~133 | 54% |

### Operation Types
| Operation | Count | Best Pass Rate |
|---|---|---|
| lookup_or_aggregation | 117 | 54.7% |
| comparison | 78 | 43.6% |
| statistical | 49 | 46.9% |
| conversion | 2 | 50.0% |

### Domain Families
| Domain | Count | Best Pass Rate |
|---|---|---|
| other | 67 | 53.7% |
| rates_and_securities | 67 | 43.3% |
| budget_and_receipts | 53 | 50.9% |
| fx | 25 | 52.0% |
| debt_and_international | 24 | 50.0% |
| macro_and_monetary | 10 | 50.0% |

---

## 2. Architecture Evolution

### Phase 1: OpenCode Harness (Early March)
- **What:** Used `opencode` harness with raw terminal access
- **Problem:** MiniMax M2.5 overwhelmingly preferred terminal commands (grep/cat/sqlite3) over MCP tools — 50+ terminal commands per task, 0 MCP calls
- **Result:** 0% accuracy because model never used structured tools
- **Lesson:** MiniMax needs structural enforcement, not prompt suggestions

### Phase 2: OpenHands SDK + Terminal Override (Mid March)
- **What:** Switched to `openhands-sdk` harness with `sitecustomize.py` import hook
- **How:** PYTHONPATH override patches `TerminalExecutor.__call__` to block grep/cat/sed on corpus files
- **Result:** Forced model to use MCP tools, accuracy jumped significantly
- **Config:** `arena.openhands.yaml` — max_iterations=15, temperature=0.0, timeout=600s
- **Lesson:** Structural blocking works; prompt-based blocking doesn't for MiniMax

### Phase 3: Goose Harness Experiment (Late March–April 1)
- **What:** Tested `goose` harness with recipe-based orchestration
- **Advantages:** Plan-Action-Reflect loop, built-in shell access, skill injection via YAML
- **Config:** `arena.goose.yaml` — max_turns=25, timeout=300s
- **Problem:** Model still spiraled with shell commands (7,232 shell calls in 246-task run)
- **Result:** 49.6% accuracy (122/246) on full pool run — but $156.96 total cost

### Phase 4: Multi-Stage Orchestrator (Late March)
- **What:** Designed Plan→Research→Compute staged pipeline with validation gates
- **Implementation:** `scripts/stage_runner.py`, `scripts/run_planner.py`
- **Problem:** MiniMax ignores phase transitions in prompts — only respects structural blocking
- **Result:** Abandoned in favor of tighter flat loop with budget guardrails

### Phase 5: Current Architecture (April 2)
- **What:** OpenHands SDK flat loop + MCP tools + anti-spin guardrails + budget enforcement
- **Prompt:** `prompts/system.j2` with reasoning transparency (`<thinking>` / `<evaluation>` blocks)
- **Tools:** 17 exposed MCP tools with per-tool budgets and global 20-call limit
- **Score:** 180.4 points (best recorded)
- **Key change:** Fixed 6 critical tool bugs → +13.2 point improvement

### Dual-Track Strategy (Current)
- **Public:** OpenHands SDK submissions via `arena submit`
- **Private:** Goose harness for development/testing (telemetry marked as `TELEMETRY_SOURCE: "goose"`)
- **Goal:** Keep Goose improvements hidden until final day, then switch if beneficial

---

## 3. Harness Experiments

### OpenHands SDK (Current Primary)
```yaml
harness_name: "openhands-sdk"
model: "openrouter/minimax/minimax-m2.5"
max_iterations: 15
temperature: 0.0
timeout: 600s
```
- **Pros:** Flat tool loop, deterministic, terminal override works cleanly
- **Cons:** 12K char default system prompt (must override), no built-in shell fallback
- **Terminal Override:** `sitecustomize.py` patches TerminalExecutor to block data retrieval
- **System Prompt:** `system.j2` — 102 lines, 5-step workflow, reasoning blocks

### Goose (Secret Development Track)
```yaml
harness_name: "goose"
model: "openrouter/minimax/minimax-m2.5"
max_turns: 25
timeout: 300s
```
- **Pros:** Recipe-based, skill injection, Plan-Action-Reflect, built-in shell
- **Cons:** Shell spiraling (7,232 calls in 246 tasks), harder to enforce MCP-only
- **System Prompt:** `goose_instructions.md` — 106 lines, execution tracker, budget rules
- **Skills:** `skills_goose/tool_guide/SKILL.md`, `skills_goose/computation_patterns/SKILL.md`

### Key Differences
| Aspect | OpenHands SDK | Goose |
|---|---|---|
| Loop type | Flat tool-calling | Plan-Action-Reflect |
| Shell access | Blocked by sitecustomize.py | Unrestricted (budget-limited) |
| Skill injection | Via system prompt | Via YAML recipe merge |
| Abort mechanism | Budget + prompt | Budget + back-off triggers |
| Best accuracy | 68.7% (180.4 pts) | 49.6% (122/246) |
| Cost per task | ~$0.06 | ~$0.64 |

---

## 4. System Prompt Iterations

### Key Principles Learned
1. **Situational framing > imperative rules** — "repeating searches rarely helps" beats "NEVER do X"
2. **Budget as fact, not threat** — "You have 20 calls. Aim for 4-8." vs "DO NOT exceed 20 calls!!!"
3. **Loud warnings make it worse** — ALL-CAPS and exclamation marks cause model panic
4. **Under 60 lines ideal** — Progressive disclosure > information overload
5. **Reasoning transparency helps** — `<thinking>` and `<evaluation>` blocks improve decision quality

### system.j2 (Current — OpenHands)
- 5-step workflow: IDENTIFY → SEARCH → VERIFY → COMPUTE → SUBMIT
- Search strategy: resolve_numeric_evidence first, then period_series, time_series, tables, search_data
- Budget: 20 calls total, aim for 4-8, hard stop at 12+ if data found
- Fiscal year rules, common mistakes, answer format
- Reasoning blocks: `<thinking>` before tools, `<evaluation>` after results

### goose_instructions.md (Current — Goose)
- 3 routing paths: ledger, table, unsupported
- Plan-Action-Reflect with execution tracker
- Tool priority: search_ledger → compute → verify → search_tables → profile → query
- Stop conditions: 2x search_tables max, 2 profiles max, 3 row sets max
- Shell fallback strategy with grep/sqlite decision tree
- Shell limit: 40 commands, back-off at 35
- Verification step mandatory before submit

### Historical Prompts (Archived in prompts/)
- `system_prompt_*.md` — Various iterations of system prompts
- `planner_system.md` — Multi-stage planner prompt (abandoned)
- `verifier_system.md` — Answer verification prompt (simplified into tools)
- `orchestrator_system.md` — Orchestrator prompt (abandoned with staged architecture)
- `parser_system.md` — Question parsing prompt (moved into route_question tool)

---

## 5. Tool Development & Fixes

### Current Tool Inventory (17 Exposed MCP Tools)

#### Gold Path (Primary — Normalized Data)
| Tool | Purpose | Budget |
|---|---|---|
| `route_question` | Classify question type, select path | Unlimited |
| `resolve_numeric_evidence` | Single-value lookup across bulletins | Part of 15 total |
| `search_canonical` | 935K deduplicated facts search | Part of 15 total |
| `search_ledger` | 13,629 metric × time search | Part of 15 total |
| `search_data` | Merged canonical + ledger search | Part of 15 total |

#### Silver Path (Series Data)
| Tool | Purpose | Budget |
|---|---|---|
| `get_period_series` | Monthly values for one year | Part of 15 total |
| `get_time_series` | Multi-year series for one metric | Part of 15 total |
| `get_multi_year_series` | Non-consecutive years | Part of 15 total |
| `extract_values` | Direct label search | Part of 15 total |

#### Bronze Path (Raw Tables)
| Tool | Purpose | Budget |
|---|---|---|
| `search_tables` | Full-text table search | 4 max |
| `get_table_profile` | Schema inspection | 4 max |
| `query_table_rows` | Cell data retrieval | 6 max |
| `get_table_context` | Additional context | 3 max |

#### Computation & Reference
| Tool | Purpose | Budget |
|---|---|---|
| `compute_expression` | Safe arithmetic (14+ functions) | Unlimited |
| `submit_answer` | Write answer to /app/answer.txt | Unlimited |
| `get_cpi_index` | CPI-U lookup (1982-84=100) | Part of 15 total |
| `get_exchange_rate` | Historical FX rates | Part of 15 total |

### 6 Critical Bugs Fixed (April 2 — +13.2 Points)

1. **query_table_rows result key mismatch** — Code returned `"rows"` but prompt/agent expected `"matches"`. Fixed in 8 locations. Wasted 50%+ of budget when model couldn't find data in response.

2. **Silent fallback in column search** — `_direct_label_search()` silently returned empty results when column_label search failed. Added explicit stderr logging + fallback to direct table scan.

3. **Budget number mismatch** — Server enforced 22 calls but prompt said 20. Unified to 20 everywhere.

4. **System prompt referenced unexposed tools** — Prompt mentioned `grep_corpus`, `get_fiscal_year_bounds`, `resolve_agency_alias` which weren't in the MCP schema. Model wasted calls trying to use non-existent tools. Aligned to 17 actual tools.

5. **Decade parsing broken** — "1940s" wasn't parsed into year range [1940, 1949]. Added explicit decade detection regex.

6. **Hidden tools consuming budget** — `search_canonical` and `search_ledger` were registered internally but not exposed in MCP schema. Model couldn't call them directly. Added to exposed tool list.

### Tool Performance Analysis (from 246-task pool run)

| Tool | Calls | Tasks Using | Pass Rate |
|---|---|---|---|
| compute_expression | 834 | High | 52.3% |
| submit_answer | 205 | High | 54.9% |
| search_data | 161 | Medium | 42.7% |
| search_tables | 99 | Medium | 44.9% |
| resolve_numeric_evidence | 93 | Medium | 44.3% |
| route_question | 63 | Low | 48.4% |
| get_time_series | 56 | Low | 49.0% |
| extract_values | 15 | Low | — |
| get_table_profile | 12 | Low | — |
| query_table_rows | 9 | Low | — |

### Anti-Spin Guardrails

**MCP Server Level (mcp_stdio.py):**
- `_call_history`: Full call log with timestamps
- `_search_call_count`: Global search counter
- `_MAX_BUDGET`: 20 total calls hard limit
- Result caching: Identical calls return cached response
- Spin detection: `no_new_evidence_streak`, `repeated_table_family`

**Tool Level (tools.py):**
- Per-tool budgets in `_budgets` dict
- Budget violations return error JSON (don't raise exceptions)
- State reset between cases via `reset_budgets()`

**Prompt Level:**
- "If past 12 calls: stop searching, compute, submit"
- "If 2 consecutive no_results: abort approach"
- "NEVER call same tool with identical arguments twice"

---

## 6. Database & Ingestion Pipeline

### Database Schema

**Core Data Tables:**
| Table | Purpose | Size |
|---|---|---|
| `canonical_facts` | 935K deduplicated facts (entity_key, year, value) | Primary lookup |
| `master_ledger` | 13,629 metric × time entries | Time series |
| `table_first_table_cells` | Raw cell data (row, col, value, year, month) | Full DB only |
| `table_cell_blobs` | Compressed cell storage (msgpack + zstd) | Slim DB |
| `table_index` | Table metadata (title, file, units, years) | Search index |

**Index Tables:**
| Table | Purpose |
|---|---|
| `col_label_lookup` | Fast column search (LIKE on col_norm) |
| `row_label_lookup` | Fast row search (LIKE on row_label_norm) |
| `table_term_index` | Full-text bigram index |
| `table_scope_index` | Temporal coverage per table |

**Reference Tables:**
| Table | Source |
|---|---|
| CPI-U data | `data/reference/cpi_series.csv`, `cpi_monthly.csv` |
| Exchange rates | `data/reference/exchange_rates.csv` |
| GDP data | `data/reference/national_gdp.csv` |
| Agency aliases | `data/reference/agency_aliases.csv` |

### Database Versions
1. **Full DB** (~11 GB) — All cells in `table_first_table_cells`, used for ingestion
2. **Slim DB** (~1.5-2 GB) — Cells compressed into `table_cell_blobs`, used in production
3. **Enriched DB** (~6.9 GB decompressed) — Slim + master_ledger + canonical_facts + indexes

### Ingestion Pipeline
```
Source JSONs (Treasury Bulletins)
  → reingest_from_json.py (20-30 min)
  → build_slim_db.py (compress cells)
  → build_master_ledger_v2.py (flat metric index)
  → precompute_indexes.py (col/row label lookups)
  → ingestion_enrichment.py (CY/FY totals, fingerprints)
  → Compress with zstd level 19
  → Serve via nginx on port 9090
```

### Known Database Issues
- **Term index misses 41% of tables** — NULL year metadata causes missed matches
- **Fix:** `_direct_label_search` uses LIKE on 452K row column labels (<0.05s)
- **Bigram vs unigram mismatch** — Term index uses bigrams but search splits unigrams
- **Auto-widening** — If year_range returns 0 results, widens by ±3 years automatically

---

## 7. Infrastructure

### Droplets (DigitalOcean)

| Role | IP | Specs | Purpose |
|---|---|---|---|
| DDB (Database/Telemetry) | 147.182.206.223 | Persistent | nginx:9090 (DB), telemetry:8080 |
| Runner (alternate) | 64.23.196.53 | On-demand | Single arena test |
| Pool runners | Dynamic IPs | s-8vcpu-16gb | 2×4 lane pool |

### Execution Modes

1. **Local** — `scripts/arena_test.sh` — Single machine with Docker/Colima
2. **Single Droplet** — `scripts/do_runner.sh` — One DO droplet for testing
3. **Runner Pool** — `scripts/do_runner_pool.sh` — 2 droplets × 4 lanes = 8 concurrent
4. **Daytona Sandbox** — `scripts/daytona_sandbox.py` — Cloud sandbox for A/B testing

### MCP Bundle Hot-Reload
```
Local changes → build_mcp_bundle.sh → scp to DDB
  → Container downloads via curl in run_mcp.sh
  → tar extract → start MCP server
```
Bundle contents: server/, prompts/, run_mcp.sh (~118KB compressed)

### Telemetry Stack
- **Server:** `scripts/telemetry_server.py` on 147.182.206.223:8080
- **Events:** tool_call, mcp_started, data_available_redirect
- **Endpoints:** POST / (events), POST /trajectory (summaries), GET /?filters
- **Client:** `scripts/pull_telemetry.py` — fetch, filter, live polling
- **Storage:** `telemetry_live.jsonl`, `telemetry_trajectories.jsonl`

### Snapshot
- DO Snapshot ID: 223007008
- Name: officeqa-runner-ready-2026-04-02
- Pre-built with all deps, DB, and arena CLI

---

## 8. Results & Score History

### Submission History

| Date | Tag | Score | Accuracy | Notes |
|---|---|---|---|---|
| 2026-03-30 | lean-db-tight-prompt v0.7.0 | 77.4 | 70.4% | First OpenHands submission |
| 2026-04-01 | (droplet test) | 0/5 | 0% | Decision-making failure |
| 2026-04-02 | pool run (goose) | 122/246 | 49.6% | $156.96 cost, shell spiraling |
| 2026-04-02 | after 6 bug fixes | 180.4 | 68.7% | +13.2 pts from bug fixes |

### Score Progression (Submission 69e7d7ce)
```
Tasks Scored: ~2  → Score: 1.1   (50.0%)
Tasks Scored: ~6  → Score: 5.8   (83.3%)
Tasks Scored: ~22 → Score: 20.7  (81.8%)
Tasks Scored: ~44 → Score: 40.3  (79.5%)
Tasks Scored: ~87 → Score: 72.9  (72.7%)
Tasks Scored: ~96 → Score: 77.4  (70.4%) [FINAL]
```

### Cost Analysis
- OpenHands SDK: ~$0.06 per task average
- Goose: ~$0.64 per task average (10x more expensive)
- Pool run total: $156.96 for 246 tasks
- Budget target: <$0.10 per task

---

## 9. Failure Analysis

### Failure Classification (124 failures from 246-task Goose pool run)

| Category | Count | % | Description |
|---|---|---|---|
| Calculation/Extraction Error | 75 | 60.5% | Wrong table, miscounted data, complex extraction |
| Tool Spiraling/Timeout | 41 | 33.1% | Infinite loops, OOM kills (exit 137) |
| Missing answer.txt | 8 | 6.5% | Reasoning complete but no file write |
| Confident but Wrong | 5 | 4.0% | High confidence, wrong document/table |

### Root Cause: Evidence Selection (Primary Bottleneck)
The #1 failure mode is NOT arithmetic errors — it's selecting the wrong evidence:
- Wrong section (e.g., "customs duties" vs "Total receipts")
- Wrong unit scale (thousands vs millions)
- Wrong year type (fiscal vs calendar)
- Wrong vintage (revised vs unrevised bulletin)
- Wrong table (similar title, different content)

### Tool Spiraling Patterns
- **UID0179:** 165+ shell commands (repeatedly grepping same files)
- **UID0114:** 117 shell commands
- **UID0122:** 111 shell commands
- Common pattern: model finds data but doesn't recognize it, keeps searching

### Decision-Making Failures (from Droplet Run Analysis)
- Q1: Found correct answer 2602 twice but submitted 1657
- Q2: Found correct answer 507 on first attempt but switched to 1056
- Q3: Found correct answer 44463 twice but abandoned it
- Pattern: Model finds right answer, then over-searches and loses it

### Most Expensive Failures
| Task | Cost | Tools | Tokens | Issue |
|---|---|---|---|---|
| uid0246 | $0.71 | 44 | 66K | Complex extraction |
| uid0240 | $0.53 | 26 | 14K | Misidentification |
| uid0237 | $0.37 | 40 | 36K | Spiraling |
| uid0159 | $0.27 | 98 | 53K | Extreme spiraling |

---

## 10. What Works vs What Doesn't

### What Works Well
1. **MCP tools over terminal** — 52.9% vs 49.1% success rate, dramatically lower cost
2. **Structural enforcement** — sitecustomize.py terminal blocking is essential for MiniMax
3. **Budget guardrails** — Hard 20-call limit prevents runaway costs
4. **resolve_numeric_evidence** — Best single tool for simple lookups
5. **compute_expression** — Reliable arithmetic (14+ functions)
6. **Flat tool loop** — Simpler is better; staged architecture added complexity without benefit
7. **Low temperature (0.0)** — Deterministic outputs reduce variance
8. **Reasoning transparency** — `<thinking>` blocks improve decision quality
9. **Result caching** — Prevents duplicate work within a task
10. **Direct label search** — LIKE queries on 452K rows in <0.05s

### What Doesn't Work
1. **Prompt-based phase transitions** — MiniMax ignores them
2. **Imperative rules in ALL CAPS** — Causes model panic, worse results
3. **More iterations** — Beyond 15, model over-searches and loses correct answers
4. **Shell commands for data retrieval** — 7,232 shell calls = 49.6% accuracy
5. **Loud warning text** — Makes results WORSE
6. **Multi-stage orchestrator** — Added latency without accuracy gain
7. **Table path for simple lookups** — Ledger path is 3x faster and more reliable
8. **Retrying same tool calls** — Model doesn't learn from failure, just repeats
9. **Complex skill injection** — Diminishing returns past basic tool guide
10. **More tools** — 7-17 is sweet spot; beyond that, context pollution

### MiniMax M2.5 Specific Behaviors
- **Ignores prompts for behavioral change** — Only structural blocking works
- **Prefers terminal over MCP** — Must be forced via import hook
- **Follows situational framing** — "repeating rarely helps" > "NEVER repeat"
- **Thinking mode is catastrophic** — 195s latency (325x slower)
- **Prone to verification loops** — Checks same thing 3-4 times
- **Budget-aware but not budget-respecting** — Knows limit but overshoots

---

## 11. Key Learnings

### Architecture
- Flat loop + budget enforcement > staged pipeline
- Structural blocking > prompt-based suggestions
- Pre-computed indexes > runtime search
- Fewer, better tools > many specialized tools
- Deterministic (temp=0) > stochastic for data retrieval

### Prompt Engineering
- Situational framing > imperative commands
- Budget as fact > budget as threat
- Under 60 lines > comprehensive instructions
- Progressive disclosure > upfront information dump
- Reasoning blocks > blind tool calling

### Tool Design
- Return actionable context > raw data
- Compact JSON > verbose descriptions
- Error messages with recovery suggestions > generic failures
- Per-tool budgets > global-only limits
- Cache deduplication > budget penalties

### Infrastructure
- DO snapshots > fresh provisioning
- MCP bundle hot-reload > full redeployment
- Centralized telemetry > scattered logs
- Pool runners (8 concurrent) > sequential testing
- Pre-built images > install-on-demand

### Competition Strategy
- Wrong answer > no answer (always submit something)
- Cost optimization matters (~10% score adjustment)
- Time optimization matters (~10% score adjustment)
- Hardcoding answers is banned — must be generalizable
- 1% tolerance is generous — don't over-engineer precision

---

## 12. Current State (April 2, 2026)

### What's Deployed
- **OpenHands SDK** harness with `system.j2` prompt
- **17 MCP tools** with budget enforcement
- **Enriched SQLite DB** served from 147.182.206.223:9090
- **Telemetry server** on 147.182.206.223:8080
- **DO snapshot** 223007008 ready for pool runs
- **Terminal override** blocking data retrieval via shell

### Current Scores
- Best: 180.4 points (68.7% accuracy, 169/246 estimated correct)
- Max possible: 282.9 points
- Gap: ~102.5 points (77 more correct answers needed for max)

### Known Issues
1. Evidence selection remains primary bottleneck
2. Goose harness shell spiraling not fully solved
3. Runner scripts lack proper logging and error tracking
4. Telemetry doesn't clearly trace prompt changes to behavior changes
5. No automated A/B testing framework
6. .arenaignore is ignored by arena CLI
7. No version tracking for prompt/tool changes across submissions

### Files That Matter Most
| File | LOC | Impact |
|---|---|---|
| `server/tools.py` | 3,535 | Core tool implementations |
| `server/db.py` | 1,906 | Database queries |
| `prompts/system.j2` | 102 | Agent behavior (OpenHands) |
| `prompts/goose_instructions.md` | 106 | Agent behavior (Goose) |
| `server/mcp_stdio.py` | 502 | MCP server + anti-spin |
| `scripts/do_runner_pool.sh` | ~400 | Production runner |
| `arena.yaml` | 30 | Submission config |

---

*This document covers all approaches tried, results obtained, and lessons learned through April 2, 2026. Update as new experiments complete.*
