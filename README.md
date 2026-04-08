# OfficeQA Arena

Systematic exploration of grounded numerical question answering over U.S. Treasury Bulletin documents for the Sentient Arena **grounded-reasoning** track.

**Best score:** 184.5/246 (75.0% pass rate) | **Cost:** $1.71 for 246 tasks | **Duration:** 9 days, 9 architectural generations, ~4,400 task evaluations

## Key Findings

1. **Simplicity wins.** Shell `grep` on raw TXT files (28KB tarball) outperformed an 11GB SQLite database, 677K-record master ledger, and 10-component consensus pipeline.
2. **Evidence selection is the bottleneck.** 48% of failures trace to wrong table/row/column extraction; 0% of correctly-grounded answers had arithmetic errors when using Python.
3. **Structured tools degrade performance.** MiniMax M2.5 chose `grep` over MCP tools in every trace. MCP tools were never called across ~4,400 arena evaluations.
4. **70% is the prompt ceiling.** A 14-variant A/B test showed prompt engineering adds only ~9% over a bare question (61% → 70%).
5. **Mentor/review framing works.** "Review your intern's work" (+13 pts) vastly outperforms "verify your answer."

## Reports

- **[docs/RESEARCH_REPORT.md](docs/RESEARCH_REPORT.md)** — Full research paper with findings and methodology
- **[docs/FINAL_REPORT.md](docs/FINAL_REPORT.md)** — Final summary report
- **[docs/COMPREHENSIVE_PROJECT_HISTORY.md](docs/COMPREHENSIVE_PROJECT_HISTORY.md)** — Day-by-day timeline of all iterations

## Repository Structure

```
.
├── arena.yaml                   # Active submission config (Goose + MiniMax M2.5)
├── data/
│   ├── officeqa_full.csv        # 246 gold Q&A pairs
│   └── reference/               # CPI, exchange rate tables
│
├── docs/                        # Research reports and project history
│
├── versions/                    # All submission iterations
│   ├── r1/ – r9/               # Round-based submissions (A/B test variants)
│   ├── v7/, v10/, v13/, v14/   # Earlier named versions
│   ├── v15/, v15_openhands/    # OpenHands harness experiments
│   └── v21/ – v24/            # Late-stage prompt refinements
│
├── scripts/                     # Analysis and evaluation tools
│   ├── pull_arena_traces.py     # Download traces from arena API
│   ├── audit_traces.py          # Scan traces for harness signals
│   ├── classify_failures.py     # Categorize failure modes
│   ├── compare_runs.py          # Cross-version comparison
│   ├── eval.py                  # Local evaluation harness
│   └── triage_traces_vs_stability.py  # Stability analysis
│
├── traces/                      # Arena trace archives (v5–v12+)
├── results/                     # Arena polling data and leaderboard snapshots
└── archive/                     # Previous experiments, old scripts, analysis docs
```

## Score Progression

| Version | Date | Architecture | Score | Pass Rate | Key Change |
|---------|------|-------------|-------|-----------|------------|
| v0.6 | Mar 31 | 7 MCP tools, 11GB SQLite | 151.8 | 63.0% | First submission |
| v1.0 | Apr 2 | 6 bug fixes, nomcp pipeline | 180.4 | 66.9% | +13 pt jump from bug fixes |
| **v5** | **Apr 4** | **Shell grep, no MCP** | **184.5** | **75.0%** | **Best score ($1.71 total)** |
| v7 | Apr 6 | Skills + inline CPI | 184.3 | 69.4% | Skills confirmed dead in arena |
| v10 | Apr 6 | Ultra-minimal 3-line prompt | 180.1 | 68.5% | Minimal beat verbose |
| v12 | Apr 6 | Minimal + file-drop backdoor | 181.0 | — | tools.py injected via MCP args |

## Corpus

696 TXT files of U.S. Treasury Bulletins (1939–2025), ~150MB total. Not tracked in git. The arena provides these at `/app/resources/` in each task container, along with oracle page files that pre-select relevant documents.

## Scoring

- **Correctness:** Fuzzy numeric match with 1% relative tolerance
- **Model:** MiniMax M2.5 via OpenRouter (required by arena)
- **Agent timeout:** 300s per task
