# OfficeQA Arena

Clean implementation for the Sentient Arena OfficeQA challenge.

## Structure

```
officeqa-arena/
  arena.yaml              # Arena harness config
  prompts/system.j2       # Single system prompt
  skills/                 # Domain knowledge (auto-injected)
  server/                 # MCP server + tools
    mcp_server.py         # FastMCP entry point
    tools.py              # Tool implementations
    db.py                 # SQLite read layer
    safe_eval.py          # Arithmetic evaluator
  src/                    # Agent + eval
    agent.py              # Agent loop
    answer.py             # Answer extraction
    reward.py             # Scoring
  scripts/
    eval.py               # Eval harness
    smoke.py              # Quick tool test
  config/
    default.yaml          # Paths and limits
```

## Scoring

Fuzzy numeric matching, 1% tolerance. Get the right number.

## Tools (7)

1. `search_tables` - Find tables by keyword + year (auto-widens, returns column samples)
2. `query_table_rows` - Get cell data (supports year_range for multi-year)
3. `get_file_structure` - List tables in a bulletin file
4. `compute_expression` - Deterministic arithmetic
5. `get_table_profile` - Inspect table columns/coverage
6. `get_cpi_index` - CPI reference data
7. `get_fiscal_year_bounds` - Fiscal year date resolution
