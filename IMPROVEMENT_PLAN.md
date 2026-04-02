# OfficeQA Arena Improvement Plan

## Current Score: 147.86 (65.9% = 162/246)
## Target: 180+ (73%+ = 180/246)

## ~~Priority 1: Fix CY/FY Synthesis Bug~~ (RESOLVED)

**Problem**: `enrich_calendar_totals.py` groups monthly cells by `(column_label, year)`.
Multiple row categories can share the same column label (e.g., "Total" column appears
for both "Receipts" and "Expenditures" rows). This means the CY/FY synthetic totals
can be contaminated with values from the wrong category.

**Fix**: Grouped by `(column_label, row_label, series_label, year)` to ensure clean isolation.

## ~~Priority 2: Strengthen verify_answer~~ (RESOLVED)

**Problem**: Current verify_answer only checks basic unit scale and provenance, but fails to clearly distinguish severity.
**Fix**: Overhauled `verify_answer` to return structured, severity-based warnings (e.g., `unit_mismatch`, `period_mismatch`), and integrated this with the deterministic finalizer.

## ~~Priority 3: Better System Prompt~~ (RESOLVED via META-HARNESS)

**Problem**: Current prompt is good but lacks structural boundaries, leading to agent spinning.
**Fix**: Implemented the "Meta-Harness" architecture. Added `route_question` to determine paths (`ledger`, `table`, `unsupported`). The prompt now acts as a strict state-machine contract rather than loose advice. Tool outputs have been aggressively truncated to save context window tokens.

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

## ~~Priority 6: Fix API Key Leak~~ (REVERTED FOR ARENA RUNNER)

**Problem**: arena.yaml has hardcoded OpenRouter key in plaintext.
**Fix**: Reverted back to hardcoded API keys because the Arena remote test runner requires the actual key to be embedded within `arena.yaml` to function correctly.

