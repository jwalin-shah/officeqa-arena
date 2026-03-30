---
name: Max Iterations Must Stay at 15
description: More iterations = worse performance. M2.5 over-searches when given budget.
type: feedback
---

max_iterations MUST stay at 15. When set to 30, the model used 80 steps, cost $0.86, and took 892s — for the SAME correct answer that took 15 steps, $0.10, and 483s with max_iterations=15.

**Why:** MiniMax M2.5 will use every iteration it's given. More budget = more over-searching, not better answers. The iteration constraint forces the model to commit to an answer.

**How to apply:** Always set `max_iterations: 15` in arena.yaml. Do NOT increase this even though "more thinking time" seems helpful. The cost/time penalty outweighs any accuracy gain.

Also: the 7GB DB (with term_index) was slower than the 5.5GB DB. The extra 12s decompression per question adds up. Use the smaller DB with cell indexes only.
