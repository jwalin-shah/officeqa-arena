---
name: 60% system architecture from archive
description: The system that achieved 60% (12/20) on Arena used OpenCode harness + 25 MCP tools + MiniMax M2.7. 70% with Sonnet.
type: project
---

## The 60% System (run-20260328-160243-a7d1d5)
- **Harness**: OpenCode (not custom agent loop)
- **Model**: MiniMax M2.7 via OpenRouter
- **MCP server**: 25+ tools via stdio, backed by same SQLite DB
- **Reasoning effort**: high
- **Key tools that made the difference**:
  - `extract_values` — mega search+fetch in 1 call
  - `query_facts` — queries 5.8M pre-extracted facts table directly
  - `verify_grounding` — returns verification_token
  - `calculate_finance` — only works WITH verification_token
  - `get_multi_year_series` — one call for multi-year data
  - `lookup_numeric_answer` — question-oriented retrieval
  - `resolve_agency_alias` — maps historical agency names
  - `list_related_bulletins` — finds revision follow-up bulletins
  - `get_national_gdp` — reference library

## The 70% System (run-20260328-154528-834dcc)
- Same architecture but with Claude Sonnet instead of MiniMax
- 7/10 questions correct

## Critical Scoring Insight
Arena scores ONLY numeric accuracy (1% tolerance), NOT strict grounding.
All grounding audit machinery is wasted for competition scoring.
Grounding is useful for debugging but should NEVER gate the final answer.

**How to apply:** Port the rich MCP tools from officeqa-core into officeqa-arena's
MCP server. Use OpenCode harness for Arena submission. Keep custom eval for testing.
The model's job should be asking the right question — the tools do the work.
