---
name: Arena Discord Intel (2026-03-30)
description: Key competition details from Discord — model, scoring, MCP, submission limits
type: project
---

Final eval uses **MiniMax M2.5** (confirmed by Oleg Golev). Score formula:
```
Score = correct_tasks × (1.0 + cost_adj + time_adj)
```
Max possible score: 282.9. Adjustments are ~10% of total.

**Why:** Scoring rewards correctness primarily, with small bonuses for speed and cost. Optimize for accuracy first, then latency.

**How to apply:**
- Use `openrouter/minimax/minimax-m2.5` in arena.yaml
- MCP servers and skills ARE supported in evaluation (confirmed by Quancore)
- 3 submissions per day, resets midnight PST (official docs say PST)
- Only harness-based agents permitted: opencode, codex, goose, openhands-sdk
- Teams lock on first submission
- Deadline: April 4 at 11:59 PM PST (vote pending to extend to April 11)
- CatVarn reports OpenCode is most reliable harness for submissions; OpenHands had config issues
- Oleg confirmed (2026-03-30): putting SQLite DB in Docker image IS allowed ("I don't see why not")
- Some participants report local `arena test` passing but submissions failing (config errors)
