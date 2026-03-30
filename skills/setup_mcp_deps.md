---
name: setup_mcp_deps
description: Pre-install Python dependencies for MCP server tools
---

NOTE: MCP tools (search_tables, query_table_rows, compute_expression, etc.) require Python packages.
If you see "unavailable tool" errors for MCP tools, run this in terminal first:

```bash
apt-get update -qq && apt-get install -y -qq python3-pip && pip3 install --quiet --break-system-packages mcp jinja2 pyyaml
```

Then the MCP tools should become available.
