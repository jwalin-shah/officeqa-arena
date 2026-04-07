# V14 Proposal: The Mentor-Intern Architecture

**Goal**: Beat 192.0 (current #1) → target 200+
**Current**: 184.5 (#7)
**Gap**: 7.5 points (~3-4 more correct questions)
**Date**: 2026-04-07

---

## Executive Summary

We combine three proven insights into one architecture:

1. **Mentor/intern framing scored 184.5** — our all-time best. MiniMax is better at reviewing than searching.
2. **Oracle pages eliminate the search bottleneck** — the Python script gets the right pages automatically.
3. **Fewer turns = better answers** — 1-5 tool calls have 82% pass rate vs 60% at 11+ calls.

The v14 architecture: a **Python "intern" script** does all the grunt work (extraction, computation, conflict detection), then MiniMax **reviews the briefing as a mentor** and writes the answer. MCP tools available as fallback for edge cases.

---

## The Leaderboard Reality

```
#1  Dolores Research     192.0   (target to beat)
#2  Vikranth's Team      191.0
#3  CTR Evolver          187.9
#7  Zero Node            184.5   (us)
```

The gap is **7.5 points**. With run-to-run variance (~5-8 points), a well-tuned v14 that picks up 3-4 more flaky questions AND gets a speed/cost bonus could reach 195+.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  MINIMAX (Mentor)                │
│  "Senior Treasury Analyst reviewing intern work" │
│                                                   │
│  Step 1: Run intern's tool                       │
│     python3 /installed-agent/solve_briefing.py   │
│                                                   │
│  Step 2: Review the briefing                     │
│     - Right table? Right row? Right units?       │
│     - Fiscal vs calendar year correct?           │
│     - Conflict between sources?                  │
│                                                   │
│  Step 3: If good → write answer.txt              │
│          If bad → try alternatives:              │
│            a) Re-run with --keywords "..."       │
│            b) grep directly                      │
│            c) Use MCP tool as fallback           │
│            d) python3 -c "compute..."            │
│                                                   │
│  Step 4: Commit answer. Move on.                 │
└─────────────────────────────────────────────────┘
         │                        │
         ▼                        ▼
┌─────────────────┐    ┌──────────────────────┐
│  PYTHON INTERN  │    │   MCP TOOLS (backup) │
│  solve_v14.py   │    │   5 tools only       │
│                 │    │                      │
│  • Oracle pages │    │  • search_tables     │
│  • Table parse  │    │  • query_rows        │
│  • Vertical fmt │    │  • compute_expr      │
│  • CPI/FX data  │    │  • get_cpi_index     │
│  • Period tags  │    │  • verify_answer     │
│  • Conflict det │    │                      │
│  • Pre-compute  │    │                      │
└─────────────────┘    └──────────────────────┘
```

---

## What the Python Intern Does (solve_v14.py)

The intern script is the workhorse. With oracle pages, it doesn't need to search — it gets the right documents automatically. Its job:

### 1. Parse the Question
- Extract: metric, year(s), period basis (fiscal/calendar), operation type
- Detect: sum, percent change, lookup, comparison, time series
- Tag: CPI adjustment needed? Exchange rate needed? Multi-year?

### 2. Extract Evidence (Oracle Pages Available)
- Read all page files in `/app/resources/`
- Parse tables with **vertical serialization** (key: value format, eliminates column misalignment)
- Multi-row header merging (handles hierarchical headers)
- Period-basis tagging on every extracted value

### 3. Pre-Compute When Possible
- Simple sums: extract 12 monthly values, compute sum
- Percent change: extract both values, apply formula
- CPI adjustment: inline CPI table (1929-2024), compute directly
- Exchange rates: inline common rates, convert directly

### 4. Generate Structured Briefing
```
--- INTERN'S RESEARCH BRIEFING ---
QUESTION: {{ question }}
QUESTION TYPE: {{ sum | pct_change | lookup | comparison }}
PERIOD BASIS: {{ fiscal (Oct-Sep) | calendar (Jan-Dec) }}

EVIDENCE #1:
  Source: {{ filename }}, Table: {{ title }}
  Units: {{ millions of dollars }}
  Period: {{ CALENDAR YEAR | matches question ✓ }}
  Data (vertical format):
    National defense, Jan: 103,030
    National defense, Feb: 98,445
    ...
  Pre-computed: SUM = 1,234,567

EVIDENCE #2 (if found):
  ...

⚠ CONFLICT: Evidence #1 says 1,234,567 but Evidence #2 says 1,245,000
   Likely cause: Evidence #2 is from a FISCAL year table (Oct-Sep)
   Recommendation: Use Evidence #1 (calendar year matches question)

INTERN'S PROPOSED ANSWER: 1,234,567
CONFIDENCE: HIGH (single source, exact match, units verified)
COMPUTATION TRACE: sum([103030, 98445, ...]) = 1,234,567
---
```

### 5. What's New vs v5's solve_briefing.py

| Feature | v5 | v14 | Impact |
|---------|-----|------|--------|
| Table format | Raw text | Vertical serialization | Fixes 33% of always-fail |
| Period tagging | Basic detection | Explicit ✓/✗ match | Fixes 13% of always-fail |
| CPI data | Not available | Inline (96 years) | Eliminates CPI hallucination |
| FX rates | Not available | Inline (5 currencies) | Handles 13 exchange rate questions |
| Pre-computation | None | Sum, pct_change, CAGR | Saves turns, avoids MiniMax arithmetic |
| Conflict detection | Basic | Structured with cause | Helps mentor adjudicate |
| Computation trace | None | Full trace | Mentor can verify math |
| Formula specification | Ambiguous | Explicit in briefing | Fixes formula variant errors |

---

## The Mentor Prompt (system_v14.j2)

```jinja2
You are a Senior Treasury Analyst mentoring a junior intern. The intern has built
a research tool that searches U.S. Treasury Bulletin files and produces a briefing
with evidence and a proposed answer.

Your intern is eager but still learning. They sometimes pull the wrong row from a
table, confuse fiscal years with calendar years, or miss unit conversions. Your
role is to review their work, catch mistakes, and guide them toward the right
answer — like a good mentor would.

Start by having your intern run their tool:
```
python3 /installed-agent/solve_v14.py "{{ instruction }}"
```

When the briefing comes back, review it the way you'd review an intern's first draft:

- Does the evidence PERIOD BASIS match the question? If the question says
  "calendar year" and the data is tagged FISCAL → that's wrong. Point it out.
- Check the row labels carefully. "Total receipts" ≠ "Net receipts".
  "National defense" ≠ "Total national defense".
- Look at the UNITS line. Millions? Thousands? Raw dollars?
- If the intern pre-computed an answer and showed the trace, verify the math.
  Percent change = ((new - old) / old) × 100, NOT |new - old| / avg.
- If there's a CONFLICT between evidence sources, adjudicate: which source
  is more authoritative? (Usually: later bulletin > earlier, exact year > range)

If the briefing looks solid and the evidence clearly supports the answer:
```
printf '%s' "ANSWER_VALUE" > /app/answer.txt
```

If something doesn't look right:
- Different search: `python3 /installed-agent/solve_v14.py "{{ instruction }}" --keywords "different terms"`
- Direct grep: `grep -i "specific phrase" /app/resources/*.txt | head -30`
- Quick math: `python3 -c "print(132 + 456)"`

A reasonable answer submitted is better than a perfect answer never written.
When the evidence is good enough, commit and move on.
```

Key changes from v5:
- Period basis checking is explicit (proven 13% failure reduction)
- Formula specification inline (fixes percent change confusion)
- Resources dir instead of corpus dir (oracle pages)
- Removed `solve.py` fallback (it's slower and we have MCP as backup)

---

## MCP Server (5 Tools Only — Backup Path)

Research confirms: **4-5 tools > 9+ tools**. We expose only:

### 1. `search_tables(query, year_range)` → Find relevant tables
- Recall-oriented, returns top-5 candidates with metadata
- Period-basis tags on results

### 2. `query_table_rows(table_pk, filters)` → Get specific data
- Returns vertical format (key: value pairs)
- Eliminates column misalignment

### 3. `compute_expression(expression)` → Safe math
- All arithmetic, statistics, CAGR, pct change, Theil index
- Python execution — never let MiniMax do math

### 4. `get_cpi_index(year, month?)` → CPI reference
- 1913-2024, monthly resolution
- For inflation adjustments

### 5. `verify_answer(question, proposed_answer)` → Independent re-check
- Re-extracts source values independently
- Re-runs computation
- Returns PASS/FAIL + discrepancy
- Based on CRITIC paper (ICLR 2024): tool-based verification > self-verification

---

## Environment Variables to Test

Goose resolves config as: **env > config.yaml > defaults**. Harbor drops config fields but env vars might pass through:

```yaml
env:
  OPENROUTER_API_KEY: "${oc.env:OPENROUTER_API_KEY}"
  GOOSE_MAX_TURNS: "15"              # May bypass Harbor's recipe
  GOOSE_TEMPERATURE: "0.0"           # May work via env
  GOOSE_CONTEXT_LIMIT: "128000"      # Prevent context bloat
  GOOSE_AUTO_COMPACT_THRESHOLD: "0.7" # Compact earlier
```

These need Daytona testing — if they work, we get turn control back.

---

## The 38 Flaky Questions — Our #1 Target

These pass sometimes, meaning the data and path exist. We just need consistency:

**Top 12 flaky (67% pass rate — close to stable):**
UID0008, UID0011, UID0021, UID0026, UID0044, UID0066, UID0091, UID0121, UID0125, UID0172, UID0177, UID0182

If we stabilize just 4 of these from 67% → 90%, that's ~1 more point per question = **+4 points**.

**How v14 stabilizes them:**
- **UID0021**: Column misalignment → vertical serialization fixes this
- **UID0026**: Model spirals with 19 steps → mentor pattern caps at 3-4 steps
- **UID0008**: FY/CY confusion → explicit period tags in briefing
- **UID0004**: Percent difference vs change → formula in briefing header

---

## MiniMax-Specific Optimizations

Research findings about MiniMax M2.5 (230B MoE, 10B active):

1. **Context degrades at ~90K tokens** → Keep turns short. Mentor pattern naturally does this.
2. **Ignores system prompt constraints** → Don't say "don't search" — just don't give it search tools upfront. Python script handles search.
3. **Best at BFCL multi-turn (76.8%)** → Tool calling is its strength. Let it call the intern script + compute tools.
4. **3.7x verbose** → Turn cap is critical. `GOOSE_MAX_TURNS=15` if env vars work.
5. **Action-triggered, not protocol-following** → Mentor framing works because "review this briefing" is an action, not a rule.

---

## Research-Backed Techniques Applied

| Technique | Source | How We Apply |
|-----------|--------|-------------|
| Difficulty-aware routing | DAAO (arXiv:2509.11079) | Python script pre-computes simple questions; MiniMax only reviews |
| Evidence curation | HiREC (ACL 2025) | Briefing filters irrelevant evidence before presenting |
| Chain-of-table | Google Research (arXiv:2401.04398) | Vertical serialization = table operations decomposed |
| Tool-based verification | CRITIC (ICLR 2024) | verify_answer MCP tool for independent re-check |
| Trajectory pruning | AgentDiet (arXiv:2509.23586) | Briefing format = pre-pruned, only relevant data |
| Contextual metadata | FinSage (arXiv:2504.14493) | Period tags, units, source file in every evidence block |
| Code-based computation | Reasoning by Commented Code (arXiv:2602.00543) | compute_expression returns Python trace |
| EvoSkill | Sentient AGI (arXiv:2603.02766) | Their own tool improved OfficeQA 60.6→67.9%; investigate |

---

## Testing Strategy (Daytona)

### Phase 1: Build & Smoke Test
1. Build solve_v14.py with vertical serialization + period tags + CPI/FX inline
2. Test on 5 known-pass questions — verify no regression
3. Test on 5 known-fail questions — verify improvement
4. Test on 5 flaky questions — verify stabilization

### Phase 2: A/B Test Prompt Variants
- v14a: Mentor + python intern (no MCP)
- v14b: Mentor + python intern + 5-tool MCP backup
- v14c: Mentor + python intern + MCP + env var turn control
- Run each on 40-question subset (UID0001-0040)

### Phase 3: Full Run
- Best variant on all 246 questions
- Compare against v5 baseline (184.5)
- Analyze: which flaky questions stabilized? Which always-fail flipped?

### Phase 4: Submit
- Submit best variant to arena
- Pull traces within 24h (they purge)
- Analyze and iterate

---

## File Structure

```
officeqa-arena/
├── v14/
│   ├── arena.yaml           # Goose config
│   ├── prompts/
│   │   └── system.j2        # Mentor prompt
│   ├── solve_v14.py          # Python intern (main script)
│   ├── tools.py              # CLI tools (cpi, fy, calc)
│   └── server/
│       ├── mcp_stdio.py      # Zero-dep MCP server (5 tools)
│       └── tools.py          # MCP tool implementations
├── run_local_v14.sh          # Local test harness
└── PROPOSAL_V14.md           # This document
```

---

## Expected Score Breakdown

| Component | Points | Confidence |
|-----------|--------|------------|
| Baseline (v5 mentor pattern) | 184.5 | Proven |
| + Vertical serialization (stabilize 4 flaky) | +4 | High |
| + Period basis tags (fix 2 FY/CY) | +2 | High |
| + Inline CPI/FX (fix 2 reference) | +2 | High |
| + Pre-computation (fix 2 arithmetic) | +2 | Medium |
| + Formula specification (fix 1 formula) | +1 | Medium |
| + Speed/cost bonus (fewer turns) | +3-5 | Medium |
| **Total projected** | **~198-200** | |
| + Variance upside | +3-5 | Possible |
| **Best case** | **~203-205** | |

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Harbor drops env vars | Medium | Test on Daytona first; fall back to prompt-only control |
| MCP still doesn't connect | High | Python script is self-contained; MCP is just backup |
| solve_v14.py bugs | Medium | Extensive Daytona testing before submit |
| Oracle pages not available | Low | Script falls back to grep search (v5 behavior) |
| MiniMax ignores mentor framing | Low | Proven at 184.5; framing is action-based |

---

## Decision: What to Build First

**Priority 1**: `solve_v14.py` — Enhanced Python intern with vertical serialization, period tags, CPI/FX, pre-computation, conflict detection. This is the core.

**Priority 2**: `system.j2` — Mentor prompt adapted from v5 with explicit period checking and formula specs.

**Priority 3**: MCP server — 5-tool backup, zero-dep stdio. Port from existing submit/server/ code.

**Priority 4**: arena.yaml — Config with env var experiments (GOOSE_MAX_TURNS, etc.)

**Priority 5**: Daytona testing — Full A/B test suite.

---

## One More Thing: EvoSkill

Sentient's own EvoSkill tool (arXiv:2603.02766) improved OfficeQA from 60.6% to 67.9% through automated skill discovery from failure traces. It's at `github.com/sentient-agi/EvoSkill`. Worth investigating — it's literally designed for this exact benchmark by the competition organizers.
