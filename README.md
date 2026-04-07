# OfficeQA Arena

Systematic exploration of grounded numerical question answering over U.S. Treasury Bulletin documents for the Sentient Arena **grounded-reasoning** track.

**Best score:** 184.5/246 (75.0% pass rate) | **Cost:** $1.71 for 246 tasks | **Duration:** 9 days, 9 architectural generations, ~4,400 task evaluations

## Key findings

1. **Simplicity wins.** Shell `grep` on raw TXT files (28KB tarball) outperformed an 11GB SQLite database, 677K-record master ledger, and 10-component consensus pipeline.
2. **Evidence selection is the bottleneck.** 48% of failures trace to wrong table/row/column extraction; 0% of correctly-grounded answers had arithmetic errors when using Python.
3. **Structured tools degrade performance.** MiniMax M2.5 chose `grep` over MCP tools in every trace. MCP tools were never called across ~4,400 arena evaluations.
4. **70% is the prompt ceiling.** A 14-variant A/B test showed prompt engineering adds only ~9% over a bare question (61% -> 70%).
5. **Mentor/review framing works.** "Review your intern's work" (+13 pts) vastly outperforms "verify your answer."

Full analysis: **[docs/RESEARCH_REPORT.md](docs/RESEARCH_REPORT.md)** | Project history: **[docs/COMPREHENSIVE_PROJECT_HISTORY.md](docs/COMPREHENSIVE_PROJECT_HISTORY.md)**

## Repository structure

```
.
├── arena.yaml                  # Active submission config (v12, Goose + MiniMax M2.5)
├── prompts/                    # All prompt versions (system.j2, system_v10-v13.j2)
├── mcp_minimal.py              # Lightweight MCP server (no DB, parses TXT directly)
├── mcp_v12.py                  # v12 MCP with inline tools (CPI, FY, calc, OLS)
├── tools.py                    # Standalone helper tools (file-drop into /app/resources/)
│
├── docs/
│   ├── RESEARCH_REPORT.md      # Full research paper with findings
│   ├── COMPREHENSIVE_PROJECT_HISTORY.md  # Day-by-day timeline
│   ├── running.md              # Runbook: local runs, Daytona, corpus notes
│   └── runner-pool.md          # DigitalOcean pool topology
│
├── nomcp/                      # No-MCP pipeline (deterministic grep + Python compute)
│   ├── solve.py                # Main solver
│   ├── bottomup/               # Component pipeline (decompose, search, extract)
│   └── results/traces/         # All arena traces (v0.1 through v12, 35+ runs)
│
├── server/                     # MCP server implementations
│   ├── mcp_stdio.py            # stdio MCP server
│   ├── tools.py                # Tool schemas and implementations
│   └── db.py                   # SQLite read path
│
├── analyst/                    # Mentor/intern pipeline (best prompt pattern)
├── submit/                     # OpenHands harness variant
├── submit-goose/               # Goose harness variant with skills
├── v7/, v10/, v13/             # Version-specific submission configs
│
├── scripts/                    # Analysis, deployment, and testing utilities (~70 files)
│   ├── pull_arena_traces.py    # Download traces from arena API
│   ├── triage_traces_vs_stability.py  # Cross-ref traces with stability buckets
│   ├── audit_traces.py         # Scan traces for harness signals
│   ├── daytona_sandbox.py      # Cloud sandbox A/B testing
│   └── do_runner_pool.sh       # DigitalOcean parallel runner pool
│
├── traces_v5/ - traces_v9/     # Local trace archives for stability analysis
├── results/                    # Arena polling data and analysis outputs
│
├── ARCHITECTURE.md             # Deep system design and prompt inventory
├── STABILITY_REPORT.md         # Multi-version stability analysis
└── ALWAYS_FAIL_ANALYSIS.md     # Root cause analysis of 39 always-fail tasks
```

## Score progression

| Version | Date | Architecture | Score | Pass Rate | Key Change |
|---------|------|-------------|-------|-----------|------------|
| v0.6 | Mar 31 | 7 MCP tools, 11GB SQLite | 151.8 | 63.0% | First submission |
| v1.0 | Apr 2 | 6 bug fixes, nomcp pipeline | 180.4 | 66.9% | +13 pt jump from bug fixes |
| **v5** | **Apr 4** | **Shell grep, no MCP** | **184.5** | **75.0%** | **Best score ($1.71 total)** |
| v7 | Apr 6 | Skills + inline CPI | 184.3 | 69.4% | Skills confirmed dead in arena |
| v10 | Apr 6 | Ultra-minimal 3-line prompt | 180.1 | 68.5% | Minimal beat verbose |
| v12 | Apr 6 | Minimal + file-drop backdoor | 181.0 | — | tools.py injected via MCP args |

## Quick start

```bash
# Local test (replicates arena submit environment)
./run_local_v12.sh --uid UID0001

# Arena submission
arena submit --config arena.yaml

# Pull traces after submission completes
python3 scripts/pull_arena_traces.py <submission_id>
```

## Corpus

696 TXT files of U.S. Treasury Bulletins (1939-2025), ~150MB total. Not tracked in git. The arena provides these at `/app/resources/` in each task container, along with oracle page files that pre-select relevant documents.

## Scoring

- **Correctness:** Fuzzy numeric match with 1% relative tolerance
- **Model:** MiniMax M2.5 via OpenRouter (required by arena)
- **Agent timeout:** 300s per task
