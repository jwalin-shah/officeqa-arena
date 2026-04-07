# Cohort 0 Final Report — Team Zero Node

## 1. Team Info

- **Team name:** Zero Node
- **Team members:** Tarun Reddi, Jwalin Shah, Sanjay Sai

## 2. What We Built

We built a grounded QA system for answering 246 financial questions about U.S. Treasury Bulletin data spanning 1939–2025. Our best submission scored **184.5/246 (75.0%)** using **Goose + MiniMax-M2.5**.

**The core insight:** MiniMax is a better *reviewer* than *retriever*. Our highest-scoring architecture separates these concerns — a Python "intern" script handles search, extraction, and computation, then MiniMax reviews the structured briefing as a "senior Treasury analyst" and writes the final answer.

We developed **9 architectural generations across 20+ submissions** over 9 days, conducting ~4,400 individual task evaluations. The journey taught us that simpler systems consistently outperformed engineered ones.

**Architecture evolution:**

| Generation | Approach | Score | Lesson |
|-----------|----------|-------|--------|
| 1–2 | MCP server + 11GB SQLite | ~150 | DB lost 50% of cell data during parsing |
| 3 | State-machine controller | 147–167 | MiniMax ignores phase boundaries |
| 4 | Decomposition pipeline | 170–180 | 8-phase LLM pipeline; computation in Python |
| 5 | Minimal prompt, free exploration | **184.5** | 30-line prompt beats 200-line prescriptive |
| 6–7 | Skills (SKILL.md) + MCP | 166–175 | Skills silently dropped; MCP never connected |
| 8 | Base64 MCP in arena.yaml | 172 | Works locally, not in arena |
| 9 | Mentor/intern (v14) | 184.5 | Python intern + MiniMax reviewer |

## 3. How We Worked On It

### Iteration cycle
Submit → pull traces (245 tasks, ~4h per run) → classify failures → adjust → resubmit. We pulled and analyzed traces after every submission using the arena CLI's async API.

### Failure taxonomy
We classified every failing task across all runs:
- **Evidence selection (48%)** — finding the wrong table, wrong row, wrong file
- **Period confusion (18%)** — fiscal year vs calendar year
- **Row selection (15%)** — right table, wrong row
- **Unit errors (12%)** — millions vs billions
- **Computation (10%)** — wrong formula applied
- Less common: hallucination, format mismatches

This showed **evidence selection is the bottleneck, not arithmetic**. It directly drove our architecture: have the Python intern pre-select evidence, so MiniMax only needs to verify.

### A/B testing
We ran 12+ prompt variants in parallel across 3 DigitalOcean droplets. Key finding: prompt changes had <5% impact on accuracy. The biggest improvements came from architectural changes (separating search from reasoning) and embedding reference data (CPI indices inline in prompt).

### What we built but couldn't use in the arena
- **MCP stdio server** (542 lines) — 9 tools including search_tables, compute_expression, verify_answer, get_cpi_index. Zero external dependencies. Works perfectly locally. In the arena: `tool_definitions=null` in every trace. Never connected.
- **Goose skills** (5 SKILL.md modules) — checklist, table-parser, compute, CPI, verify. The `summon` extension isn't in the harbor-task recipe, so skills are unreachable.
- **Decomposition engine** — 8-phase pipeline that breaks questions into sub-queries, searches per-query, extracts in parallel, computes in Python. Promising for complex multi-step questions (52% of the dataset needs monthly series), but couldn't deploy it through the arena harness.
- **5 database versions** — from 11GB full corpus to 68MB master_ledger with 677K records, 131K precomputed YoY changes. The irony: `grep` on raw text files outperformed every database version because the DB lost data during ingestion.

### Data engineering
We built a 4-stage ingestion pipeline: extraction (700 lines), enrichment (1,466 lines), compression (12.3x ratio via msgpack+zstd), and synthesis (CY/FY totals, master_ledger). This work was essential to understanding *why* simpler approaches won — the raw TXT files were complete and uncorrupted while structured DBs lost 50% of cells to parsing edge cases.

## 4. What We Found

### Counterintuitive findings
1. **Simpler wins.** A 30-line prompt with `grep` beat a 200-line prompt with a 9-tool MCP server backed by an engineered database. MiniMax performs best when unprompted — it naturally discovers page files and writes Python computations.
2. **Fewer turns = better answers.** 1–5 tool calls had 82% pass rate vs 60% at 11+ calls. The model gets lost in long research chains.
3. **Narrative framing beats rules.** "You've learned that fiscal years before 1977 run July–June" works; "NEVER confuse FY with CY" gets ignored.
4. **Inline reference data eliminates hallucination categories.** Embedding CPI-U indices (1913–2024) directly in the prompt means the model never needs to search for them and never hallucinates them.

### Grading inconsistency
When the arena re-triggered our submissions (same code), scores dropped 10–23 points across all versions. We pulled all traces and compared 971 task pairs:
- **75% of pass→fail flips had byte-identical answers** — the grader returned different verdicts for the same string
- Agent behavior was statistically identical: same steps (18.2), tools (14.1 shell/task), reasoning (~27KB)
- 6 tasks always fail despite matching the gold answer exactly and passing the published `reward.py`
- Score confidence interval: **±15 points**

### Task stability (across 12–15 runs per task)
- **67 tasks (27%)** — always pass
- **141 tasks (57%)** — flaky (grading varies even with identical answers)
- **38 tasks (15%)** — always fail (6 are provable grading bugs; 26 genuinely wrong)
- Theoretical ceiling: 208, not 246. Expected score: 157 ± 14.

### Grading bugs found
6 tasks where our answer matches `officeqa_full.csv` exactly but always fails in the arena:

| UID | Our Answer = Gold Answer | Arena Result |
|-----|-------------------------|-------------|
| 0073 | 6379.29 | Always FAIL |
| 0135 | 951134.33 | Always FAIL |
| 0136 | 1.558 | Always FAIL |
| 0158 | 0.55 | Always FAIL |
| 0212 | 0.063 | Always FAIL |
| 0055 | 0.0 / 0.00 | Always FAIL |

Additionally, UID 0120's gold answer `[44.00,231.52]` is impossible to match — the grader's regex parses `44.00231` as one number if the agent adds a space after the comma.

## 5. Feedback for Arena

### What was confusing
- **Harness config is a black box.** Temperature, max_turns, skills, and file mounts are silently dropped. We spent days debugging features that were never wired through. An explicit error would save enormous time.
- **`arena test` vs `arena submit` behave differently.** Test doesn't copy skills or files. We validated locally, submitted, got different results, then had to reverse-engineer why.
- **The arena grader doesn't match the published `reward.py`.** We proved 6 tasks with exact-match answers that pass locally but always fail in the arena.

### What should be improved
- **Publish the exact grading code** used in production, or run the published `reward.py` as-is.
- **Deterministic grading.** A ±15 point variance on identical answers makes the leaderboard unreliable and optimization impossible. We can't distinguish a real improvement from noise.
- **Document which `arena.yaml` fields work.** A table of "field → supported/ignored" prevents days of wasted effort. We discovered through trial and error that only `prompt` + `mcp_servers` + `env` are functional.
- **MCP support in the arena container.** MCP works locally but fails silently in the arena. Either fix it or document it as unsupported.
- **Trace retention.** Traces purge after ~24h. For a multi-day competition, keeping them longer would help iteration.
- **List answer formatting.** The regex parser should tolerate whitespace in `[44.00, 231.52]` vs `[44.00,231.52]`.

### What would have helped us move faster
- A working MCP example in the actual arena container
- Knowing upfront that skills, temperature, and turn limits are dropped
- A local Docker image matching the arena container exactly
- Deterministic grading — we would have shipped fewer submissions and spent more time on real improvements instead of chasing noise
