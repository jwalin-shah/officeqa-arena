# v7 Research Findings & Development Log

## Session: 2026-04-05/06 (~6 hours)

### Executive Summary
v7 submitted with inline CPI, 5 properly-formatted goose skills, and a lean 340-word prompt. First submission with correct SKILL.md format (previous 485+ traces had 0 skill usage due to wrong file format).

### Score History
| Version | Score | Success Rate | Key Change |
|---------|-------|-------------|------------|
| v5 | 184.5 | 68.3% | Baseline (MCP configured but never used) |
| v6 | 175.4 | 65.2% | Bloated prompt, max_turns=25. 9-point regression mostly from API flakiness |
| v7 | TBD | TBD | Inline CPI, proper skills, lean prompt, max_turns=10 |

### Key Discoveries

#### 1. Goose Skills Format
**Problem:** Skills in `skills/*.md` flat format were silently ignored in ALL runs (0/485 traces).
**Root cause:** Goose v1.25+ requires `skills/skill-name/SKILL.md` with YAML frontmatter (`name` + `description`). The summon extension scans `~/.agents/skills/`, `.agents/skills/`, `~/.config/goose/skills/`.
**Fix:** Restructured to correct format. Confirmed `load("cpi-reference")` works in manual Docker test.

#### 2. CPI Inline vs Skills
**Problem:** MiniMax curled BLS/FRED APIs for CPI data. When APIs failed, it spiraled (5-20 turns wasted).
**Fix:** CPI values embedded directly in prompt. Proven: uid0005 passed 3x with inline CPI, zero curl calls.
**Insurance:** CPI also in skills as backup. Both channels available in arena submit.

#### 3. Arena Test ≠ Arena Submit
**Problem:** Local `arena test` doesn't copy skills or project files into the Docker container.
**Root cause:** Harbor's `cp -r skills/*` runs inside container where source doesn't exist (project files not mounted). Only `install.sh` reaches `/installed-agent/`.
**Impact:** Can't validate skills locally. Must use arena submit traces.
**Workaround:** Built `run_local_v7.sh` harness that runs goose natively with oracle resources.

#### 4. GOOSE_MOIM_MESSAGE_TEXT
**Discovery:** Goose has a "Top of Mind" (tom) extension that injects `GOOSE_MOIM_MESSAGE_TEXT` env var into every turn.
**Result:** Doesn't work. Harbor doesn't pass the env var through to the goose process inside the container.

#### 5. MCP Server Failures
**Discovery:** Stdio MCP server failed with "process quit before initialization."
**Root cause:** Likely protocol handshake mismatch or Python buffering issue.
**Decision:** Abandoned MCP. MiniMax never used MCP tools in 485 traces anyway.

#### 6. v5→v6 Regression Analysis
**Finding:** 9-point drop was mostly noise + API flakiness, NOT the prompt change.
- 6/21 regressions: FRED/BLS API failures (different run = different API reliability)
- 15/21 regressions: MiniMax nondeterminism (same data, random wrong extraction)
- 12 improvements: Also nondeterminism going the other way

#### 7. Oracle Resources
**Finding:** Arena provides minimal oracle files in `/app/resources/`:
- `manifest.json` (698 bytes)
- 1-5 `*_page_NN.txt` files (~8KB each, contain exact answer table)
- Full `.txt` (~270KB) and `.json` (~460KB) as fallback
**Impact:** MiniMax goes straight to page files in 3 steps. This is why cost is $0.007/task.

#### 8. JSON Parsing Loops
**Finding:** 8 tasks in v5 got stuck repeating `python3 -c "import json; open(...)"` 30-70 times.
**Root cause:** JSON files are 460KB, output truncated, MiniMax retries identical command.
**Fix:** data-files skill says "avoid JSON, use page TXT files instead."

#### 9. max_turns Not Enforced
**Finding:** Harbor generates the goose command WITHOUT `--max-turns` flag despite it being in arena.yaml.
**Impact:** Tasks run until 300s timeout, not until 10 turns.
**Implication:** max_turns=10 in config is cosmetic. Timeout is the real constraint.

#### 10. todo_write Waste
**Finding:** 479 todo_write calls across 244 tasks in v6 (~2 per task). MiniMax plans instead of acting.
**Impact:** ~2 wasted turns per task on planning.
**Cannot fix:** Harbor always includes todo extension in the recipe.

### Failure Mode Coverage

| Failure Mode | v5 Count | v7 Mitigation | Expected Impact |
|---|---|---|---|
| JSON parsing loops | 8 | data-files skill | +3-5 points |
| CPI hallucination/API failure | 4-6 | inline CPI in prompt | +4-6 points |
| Wrong formula | 10-12 | computation-patterns skill | +2-4 points |
| FY/CY confusion | 5-8 | fiscal-calendar skill | +2-4 points |
| Wrong row/column | 15-20 | table-extraction skill | +1-3 points |
| No answer (timeout) | 23 | "write early" prompt + page-first | +2-4 points |
| Format issues | 3-5 | format rules in prompt | +2-3 points |
| Chart/graph questions | ~5 | Cannot fix (visual data) | 0 |

### Tools & Infrastructure

| Tool | Purpose | Status |
|---|---|---|
| `run_local_v7.sh` | Local test with oracle resources | Working |
| `run_batch_v7.sh` | Parallel batch testing | Working |
| Daytona sandboxes (2) | Docker-based arena test | Working but skills broken |
| `scripts/poll_submission.py` | Poll arena submission status | Working |
| Page file generator | officeqa repo transform_files_page_level.py | 83,216 files generated |

### v8 Experiment Plan
After v7 results:
1. If skills work in submit → try lean prompt (remove inline CPI, rely on skills only)
2. If skills don't work → keep inline CPI, investigate alternative approaches
3. Pull traces immediately to verify skill `load()` calls
