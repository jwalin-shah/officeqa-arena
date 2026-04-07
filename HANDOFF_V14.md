# v14 Handoff — Next Chat Prompt

Copy-paste this into a new chat:

---

We're working on the OfficeQA Arena competition (Sentient Arena, grounded reasoning over U.S. Treasury Bulletins). Currently #7 at 184.5, targeting 192+ to beat #1.

## Current State (commit affc5a3 on main)

v14 is the mentor/intern architecture: MiniMax (via goose) calls solve_v14.py as a search/compute tool. The intern searches oracle page files, parses HTML tables with stdlib HTMLParser, computes monthly sums, and writes a draft answer.txt. MiniMax verifies and can override.

**What's proven working (3/3 pass rate):**
- UID0003: monthly sum with abbreviated months (Jan./Feb./Mar.) → 44,463
- UID0004: pct_change of two calendar year monthly sums → 1608.80%

**What's broken:**
- UID0001: intern correctly computes 2602 (CY monthly sum) but MiniMax consistently overrides with 1580 (FY annual row). The evidence section shows "1940, National defense: 1,580" and MiniMax grabs that instead of trusting the computation. Need to suppress competing annual values from evidence when monthly sum was computed.
- UID0027/0028 (yield spreads), UID0041 (Theil index) — always-fail, need MiniMax to decompose these

**Key findings:**
- 52% of questions (129/246) need monthly series data — our intern handles sum, pct_change, difference, ratio, mean with monthly awareness
- **Narrative framing >> rules** — MiniMax responds to situational role-play ("You've learned from experience that..."), NOT imperative rules ("NEVER do X", "ALWAYS do Y"). Frame constraints as professional experience, not mandates. The current `system.j2` is still a dry rule list — it should narrate a situation MiniMax can role-play into.
- v5-style prompt scored 184.5 not because it was minimal, but because it was *narratively framed* and short. Detailed prescriptive prompts are actively harmful — MiniMax ignores them or follows them mechanically.
- Compact answer-first briefing (62 lines vs 383) prevents MiniMax from overriding correct answers
- The intern's deterministic math is more reliable than MiniMax's mental math

## What needs to happen:

1. **Fix the UID0001 override** — when intern computes a monthly sum, suppress the competing annual/fiscal row from the evidence section so MiniMax doesn't grab it. In `briefing()` (solve_v14.py:944-964), the scored entries include annual rows that compete with the monthly sum. When trace contains "SUM of N monthly values", filter out non-monthly entries from the display.
1b. **Rewrite system.j2 with narrative framing** — the current prompt is a dry RULES/TOOLS list. MiniMax needs situational narration: "You are a senior Treasury analyst who's done this hundreds of times. Your intern already searched and computed — you've learned that the intern's monthly sums are trustworthy..." Frame the intern relationship as experience, not instructions. Keep it ~30 lines but make it a story, not a spec.
2. **Wider variance testing** — run 20+ UIDs (mix of always-pass, flaky, always-fail) 3x each across the 3 DO runners to get real pass rates. Not just the 3 UIDs we've been testing.
3. **Test no-regression** — pick 10 random always-pass UIDs, verify they still pass with v14
4. **Arena submission** — we have 3 submissions/day (resets midnight UTC). Submit when pass rates look good.
5. **Investigate complex questions** — pull traces for UID0027 (yield spread), UID0041 (Theil index). Can MiniMax decompose these with the current prompt? The prompt has hints for spreads and statistical measures.

## Infrastructure

3 DO runners ready:
- 209.38.146.35 (r1, s-4vcpu-8gb)
- 159.223.199.81 (r2, s-2vcpu-4gb)
- 143.198.230.97 (r3, s-2vcpu-4gb)

All have: goose at ~/.local/bin/goose, 697 corpus files, 83,216 oracle page files, CSV, git credentials. Deploy: `git push` then `ssh root@IP "cd /root/officeqa-arena && git pull origin main"`

Run tests: `ssh root@IP "export PATH=\$HOME/.local/bin:\$PATH OPENROUTER_API_KEY=REDACTED; cd /root/officeqa-arena; bash run_local_v14.sh --batch UID0001 UID0003"`

2 Daytona sandboxes (b300439b, a29635ff) — NOT set up for v14 yet.

## Key files
- v14/solve_v14.py — intern (search + parse + compute)
- v14/prompts/system.j2 — prompt template (v5-style, 33 lines)
- v14/server/mcp_stdio.py — MCP backup tools
- v14/tools.py — calc, cpi, fy tools
- v14/arena.yaml — arena config (model, MCP, env)
- run_local_v14.sh — local test harness
- decomposition_results_v3.json — pre-decomposed all 246 questions
- docs/analysis/DECOMPOSITION_KNOWN_ISSUES.md — 89 questions with known traps

## Key memories to review
Check MEMORY.md — especially: v14 Status, MiniMax Override Behavior, v5 Prompt Style Wins, MiniMax Ignores Prompts, A/B Test Results, Turn Cap Helps, File Drop Backdoor, Harness Controls
