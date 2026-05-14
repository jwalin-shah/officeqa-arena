# OfficeQA Arena

Grounded numerical question answering over U.S. Treasury Bulletins, built for the [Sentient Arena](https://sentient.foundation/) **grounded-reasoning** track.

**Best score:** 184.5 / 246 — **75.0 %** pass rate at **$1.71** for all 246 tasks. 9 days, 12 architectural rounds, ~4,400 task evaluations.

📄 **Read the paper:** [research.pdf](research.pdf) · [research.html](research.html) — *Prompt Engineering for LLM Agents on Grounded Financial QA*

---

## TL;DR — what we learned

1. **Simplicity wins.** Shell `grep` over the raw 28 KB TXT corpus beat an 11 GB SQLite database, a 677K-row ledger, and a 10-component consensus pipeline.
2. **Evidence selection is the bottleneck.** 48 % of failures came from wrong table/row/column picks. 0 % of correctly-grounded answers had arithmetic errors when the agent used Python.
3. **Structured tools hurt.** MiniMax M2.5 picked `grep` over our MCP tools in every trace. Across ~4,400 evaluations, MCP tools were never called.
4. **There's a prompt ceiling around 70 %.** A 14-variant A/B test moved a bare question from 61 % → 70 %. Past that, prompting alone stops helping.
5. **Mentor framing > self-verify.** *"Review your intern's work"* (+13 pts) beat *"verify your answer."*

Full methodology and numbers: [docs/RESEARCH_REPORT.md](docs/RESEARCH_REPORT.md).

---

## Repository layout

```
.
├── arena.yaml              # Active submission config (Goose harness + MiniMax M2.5)
├── research.pdf / .html    # Submitted research paper
├── requirements.txt        # Python dependencies for local scripts
│
├── data/                   # Benchmark + reference tables
│   ├── officeqa_full.csv     # 246 gold Q&A pairs
│   └── reference/            # CPI, exchange rates
│
├── docs/
│   ├── RESEARCH_REPORT.md    # Full research paper (long form)
│   ├── FINAL_REPORT.md       # Executive summary
│   ├── COMPREHENSIVE_PROJECT_HISTORY.md  # Day-by-day timeline
│   └── archive-notes/        # Working notes from each round
│
├── versions/               # Every submission iteration (r1–r12, v7–v24)
│   ├── r1/  … r12/            # Round-based submissions
│   ├── v7/, v10/, v13–v15/    # Earlier named versions
│   ├── v15_openhands/         # OpenHands harness experiment
│   └── v21/ … v24/            # Late-stage prompt refinements
│
├── scripts/                # Reproducible tooling
│   ├── eval.py                  # Local evaluation harness
│   ├── pull_arena_traces.py     # Download traces from arena API
│   ├── audit_traces.py          # Scan traces for harness signals
│   ├── classify_failures.py     # Categorize failure modes
│   ├── compare_runs.py          # Cross-version comparison
│   ├── triage_traces_vs_stability.py
│   └── analysis/                # Ad-hoc one-off analyzers
│
└── archive/                # Previous experiments + raw trace dumps
```

---

## Score progression

| Version | Date  | Architecture                            | Score     | Pass rate  | Key change                            |
| ------- | ----- | --------------------------------------- | --------- | ---------- | ------------------------------------- |
| v0.6    | Mar 31 | 7 MCP tools, 11 GB SQLite              | 151.8     | 63.0 %     | First submission                      |
| v1.0    | Apr 2  | 6 bug fixes, nomcp pipeline            | 180.4     | 66.9 %     | +13 pt jump from bug fixes            |
| **v5**  | **Apr 4** | **Shell `grep`, no MCP**            | **184.5** | **75.0 %** | **Best score — total cost $1.71**     |
| v7      | Apr 6  | Skills + inline CPI                    | 184.3     | 69.4 %     | Confirmed skills are dead in arena    |
| v10     | Apr 6  | Ultra-minimal 3-line prompt            | 180.1     | 68.5 %     | Minimal beat verbose                  |
| v12     | Apr 6  | Minimal + file-drop backdoor           | 181.0     | —          | `tools.py` injected via MCP args      |
| r11     | Apr 8  | Submission-ready prompt + CPI guidance | —         | —          | Inline FY/CY rules, verify skill      |

Each row links 1-to-1 to a directory in `versions/`. The best run (v5) lives at `versions/v15/` and friends — see [docs/COMPREHENSIVE_PROJECT_HISTORY.md](docs/COMPREHENSIVE_PROJECT_HISTORY.md) for the full day-by-day with all 23 rounds.

---

## Reproducing the best run locally

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Validate against the 246-question benchmark
python scripts/eval.py --version versions/v15 --data data/officeqa_full.csv

# 3. (Optional) Pull traces of past arena runs
export ARENA_API_KEY=...
python scripts/pull_arena_traces.py --out archive/traces/
```

The arena itself runs the bundle defined by `arena.yaml`: it mounts the Treasury Bulletin TXTs at `/app/resources/` inside a container, then invokes the Goose harness with MiniMax M2.5. Local evaluation simulates the same shape against `data/officeqa_full.csv`.

---

## Corpus

696 TXT files of U.S. Treasury Bulletins (1939–2025), ~150 MB total. Not tracked in git — they're provided by the arena at runtime under `/app/resources/`, along with oracle page files that pre-select relevant documents per task.

---

## Scoring rules

- **Correctness:** fuzzy numeric match with 1 % relative tolerance
- **Model:** `openrouter/minimax/minimax-m2.5` (required by the arena)
- **Agent timeout:** 300 s per task

---

## License

MIT — see [LICENSE](LICENSE).
