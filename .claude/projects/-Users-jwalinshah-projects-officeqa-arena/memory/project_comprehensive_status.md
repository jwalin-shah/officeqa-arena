---
name: comprehensive project status and next steps
description: Full synthesis of fixes made, failure taxonomy, ideal tool sequences, and prioritized next steps as of 2026-03-29
type: project
---

## Current Performance
- Smoke test (3 questions): 2/3 = 66.7% (UID0001 exact, UID0003 exact)
- Dev test (9/20 completed): 1/9 = 11.1% (UID0010 only)
- With pending fixes (round bug + multi-tool): potential 3/9 = 33%
- Old system baseline: 0/12

## Top Failure Categories (from 9 dev questions)
1. **Extraction failures** (right table, wrong value): UID0012, UID0013, UID0018
2. **Iteration exhaustion** (ran out of 15 calls): UID0005, UID0007
3. **Tool bugs** (round() in safe_eval): UID0009
4. **Retrieval failures** (can't find the table): UID0017
5. **Wrong computation formula**: UID0015

## Priority Next Steps
P0: Enforce inspect-before-fetch, default limit=50 (done), synonym expansion in search
P1: Structured scratchpad tool, enable grounding rejection, column-label-aware search
P2: Chain-of-Table enforcer, adaptive retry with reformulation

## Ideal Tool Sequences
- Simple lookup: 3-4 calls (search → profile → query → answer)
- Calendar-year sum: 4-5 calls (search → profile → query monthly → compute sum → answer)
- Percent change: 4-5 calls (search → profile → query both years → compute → answer)
- Recovery pattern: +1-2 calls via get_file_structure on Y+1 January bulletin

## Key Architectural Insight
Old pipeline separated extraction from computation (model extracts, Python computes).
Current system makes model do everything. The fix is smarter tools, not more pipeline stages.
