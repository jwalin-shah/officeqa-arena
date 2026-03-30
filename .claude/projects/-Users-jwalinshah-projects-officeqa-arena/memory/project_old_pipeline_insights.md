---
name: old pipeline architecture insights
description: Key differences between old multi-stage pipeline and current single-agent loop that explain performance gaps
type: project
---

The old sentient-arena-officeqa had a multi-stage pipeline: parse → plan → retrieve → extract → calculate → verify → finalize. Each stage was a SEPARATE LLM call with a specific job.

**Why:** Computation was never a bottleneck because `calculate_from_evidence_rows()` did ALL math deterministically in Python. The model's job was ONLY to extract raw values — Python handled difference, ratio, average, sum operations.

**How to apply:** The current single-agent loop makes the model do everything (search + extract + compute + format). This wastes iterations on computation that should be deterministic. Options:
1. Make compute_expression smarter (accept operation names like "geometric_mean" with a list of values)
2. Add a "batch compute" tool that takes extracted values + operation type
3. Return to multi-stage where extraction and computation are separated

Also: model should NOT use training knowledge for external data (exchange rates, etc.) — needs web search tool for that.
