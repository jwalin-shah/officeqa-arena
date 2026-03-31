# OfficeQA Arena Improvement Plan

## Current Score: 147.86 (65.9% = 162/246)
## Target: 180+ (73%+ = 180/246)

## Priority 1: Fix CY/FY Synthesis Bug (likely +5-10 pts)

**Problem**: `enrich_calendar_totals.py` groups monthly cells by `(column_label, year)`.
Multiple row categories can share the same column label (e.g., "Total" column appears
for both "Receipts" and "Expenditures" rows). This means the CY/FY synthetic totals
can be contaminated with values from the wrong category.

**Fix**: Group by `(column_label, row_label_prefix, year)` where row_label_prefix
captures the parent category. See `scripts/enrich_calendar_totals_v2.py`.

**How to validate**: Pick the question that was "off by 26". Query the master_ledger
for that metric+year. Compare the synthetic CY value against manual sum of 12 months.
If they differ, the enrichment bug is confirmed.

## Priority 2: Strengthen verify_answer (likely +5-8 pts)

**Problem**: Current verify_answer only checks:
- Unit scale (thousands/millions/billions)
- Value provenance (is answer in evidence?)
- Basic period mentions

**Missing checks**:
- Row hierarchy: Is the model using a "Total" row when it should use a sub-row?
- Period boundary: Does the question ask for CY but evidence is FY?
- Synthetic vs raw: If using a synthetic CY row, was it complete (12 months)?
- Revision freshness: Is this from the latest bulletin?
- Cross-table unit mismatch: Are two evidence values in different units?

**Fix**: Enhanced verify_answer with structured error codes. See changes in tools.py.

## Priority 3: Better System Prompt (likely +3-5 pts)

**Problem**: Current prompt is good but:
- No exemplars showing common mistakes
- No structured output contract
- Skills files are loaded but bloat the context

**Fix**: Tighter contract-style prompt with 2-3 error exemplars. See `prompts/system_v2.j2`.

## Priority 4: Telemetry (enables all future improvements)

**Problem**: No structured logging of:
- Which tool path led to the answer (ledger vs extract_values vs grep)
- Whether verify_answer caught errors
- What the failure category was
- Time per tool call

**Fix**: Add structured telemetry to agent loop. See `src/telemetry.py`.

## Priority 5: Re-enable Grounding Audit with Safety (likely +2-3 pts)

**Problem**: The grounding audit rejection is commented out (agent.py:418-424).
It was probably disabled because it was too aggressive (rejecting correct answers).

**Fix**: Re-enable with a "soft gate" - only reject if score is very low (≤2/7)
AND there are enough iterations remaining (≥4). This prevents false rejections
while still catching clearly ungrounded answers.

## Priority 6: Fix API Key Leak

**Problem**: arena.yaml has hardcoded OpenRouter key in plaintext.

**Fix**: Use environment variable reference instead.
