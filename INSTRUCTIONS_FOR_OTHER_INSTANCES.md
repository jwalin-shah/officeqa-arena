# Instructions for Other AI Instances

## Context
We're improving an agentic QA system for the Sentient Arena OfficeQA benchmark.
Current score: 147.86 (65.9%, 162/246 tasks correct). Target: 180+.

The system uses MiniMax M2.5 via OpenRouter, with an MCP tool server backed by SQLite.
The agent gets a question, calls tools to search/extract data from Treasury Bulletins,
computes answers, and writes to /app/answer.txt.

## What's Already Done
- Master Ledger with pre-computed CY/FY totals
- search_ledger (gold path), extract_values (silver), search_tables (bronze)
- verify_answer tool with unit/period checks
- Budget-based progressive hints
- Grounding audit (currently disabled)

## Key Files
- `server/tools.py` — All tool implementations (search_ledger, extract_values, verify_answer, etc.)
- `server/mcp_stdio.py` — MCP server with tool schemas
- `prompts/system.j2` — Active system prompt (51 lines)
- `src/agent.py` — Agent loop with tool dispatch and answer extraction
- `src/answer.py` — Answer extraction from tool results
- `src/grounding.py` — Grounding audit (7 checks)
- `skills/*.md` — Domain knowledge files loaded into context
- `scripts/enrich_calendar_totals.py` — Builds CY/FY synthetic rows
- `arena.yaml` — Arena config (model, timeout, MCP server)

## Top Failure Modes (ranked by frequency)
1. **Wrong row/column** — Agent picks "Total" when it should pick a sub-category, or vice versa
2. **Fiscal vs Calendar year confusion** — Pre-1977 FY=Jul-Jun, post-1976 FY=Oct-Sep
3. **Unit mismatch** — Values in "thousands" vs "millions" not properly scaled
4. **Wrong bulletin/revision** — Using stale data from an older bulletin
5. **Premature commitment** — Agent locks onto first plausible number without verification
6. **Retrieval miss** — Term index misses 41% of tables

## Task 1: Build a Verification Script
Create `scripts/verify_synthesis.py` that:
1. Opens the enriched SQLite DB
2. For each master_ledger entry with row_type="synthetic_cy_total" or "synthetic_fy_total":
   - Manually sums the 12 monthly values from table_first_table_cells
   - Compares against the synthetic total
   - Reports any discrepancies > 0.01
3. Output: a report of all mismatched synthetic values with the delta

This validates whether the CY/FY enrichment is producing correct totals.

## Task 2: Build a Question Classifier
Create `src/question_classifier.py` that classifies questions into types:
- `direct_lookup` — "What was X in year Y?"
- `comparison` — "What was the difference between X in Y1 and Y2?"
- `aggregation` — "What was the total X from Y1 to Y2?"
- `ratio` — "What percent of X was Y?"
- `cpi_adjustment` — "In real/constant dollars..."
- `time_series` — "What was the CAGR/growth rate..."
- `multi_table` — Requires data from multiple tables

Input: question string
Output: dict with `type`, `metric`, `years`, `period_basis` (fiscal/calendar/unknown),
        `output_unit`, `requires_computation`

This helps route to the right tool path and set up verification.

## Task 3: Improve System Prompt
The current prompt at `prompts/system.j2` is good but could be tighter.
Create `prompts/system_v3.j2` with these changes:
- Add 3 SHORT exemplars showing common mistakes and fixes:
  1. FY/CY confusion example
  2. Wrong "Total" row example
  3. Unit mismatch example
- Make the workflow more contract-like (numbered conditions, not prose)
- Remove the FINAL_ANSWER tags — have the agent just write to /app/answer.txt directly
- Keep total length under 60 lines

## Task 4: Build DB Audit Script
Create `scripts/audit_db.py` that reports:
1. Total tables in table_index
2. Total rows in master_ledger
3. Number of distinct metrics in master_ledger
4. Coverage: which years have the most/fewest metrics
5. CY/FY synthetic row counts
6. Tables with monthly data but no synthetic CY/FY rows
7. Any master_ledger entries where the same (metric, time_key) has multiple conflicting values

## Task 5: Enhanced Error Codes for Tools
Update `server/tools.py` to make tool errors more structured.
Instead of `{"error": "some string"}`, return:
```json
{
  "status": "error",
  "error_code": "NO_RESULTS",
  "message": "No tables found matching 'customs duties' for year 1940",
  "suggested_action": "Try broader terms like 'customs' or check year range",
  "context": {"query": "customs duties", "year": 1940}
}
```

Error codes to support:
- `NO_RESULTS` — query returned nothing
- `AMBIGUOUS_MATCH` — multiple candidates, need disambiguation
- `BUDGET_EXCEEDED` — search/grep budget hit
- `UNIT_MISMATCH` — cross-table unit conflict detected
- `PERIOD_MISMATCH` — fiscal/calendar mismatch
- `YEAR_OUT_OF_RANGE` — requested year not in any table

## Constraints
- Keep everything compatible with Python 3.12
- No new pip dependencies (only stdlib + what's already installed)
- Don't change the MCP protocol or tool schemas (they're shared with the arena)
- Don't store benchmark answers or question-answer pairs
- All files should be self-contained and testable
