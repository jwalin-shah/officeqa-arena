# Harness Switching Guide

Both **Goose** and **OpenHands SDK** harnesses can now be switched easily. They share the same MCP tools and have consistent behavior.

## Quick Switch

```bash
# Switch to Goose
cp arena.goose.yaml arena.yaml

# Switch to OpenHands SDK
cp arena.openhands.yaml arena.yaml

# Verify
grep harness_name arena.yaml
```

## Consistency Across Both

### Shared Components ✓
- **MCP Server Code** (`server/tools.py`): Both harnesses use same tools
- **Bundle** (`mcp_bundle.tar.gz`): Single bundle for both
- **Status Fields**: Both recognize tool status ("success", "no_results", "error")

### Harness-Specific Behavior

| Feature | Goose | OpenHands |
|---------|-------|-----------|
| Prompt | `prompts/goose_instructions.md` | `prompts/system.j2` |
| Tool Loop | Orchestrated (Plan-Action-Reflect) | Flat (tool calling) |
| Tool Budget | ~40 shell commands | 22 MCP calls |
| Fallback | grep/sqlite (capped at 10 lines) | None (MCP only) |
| Abort Strategy | Stop after 2 failures | Stop at 12 calls if failing |

### Tool Status Field (Both Use This)

All tools return a `status` field:

```json
{
  "matches": [...],
  "count": 5,
  "status": "success",
  "note": "Found results in master_ledger"
}
```

**Agent should check `status` field:**
- `"success"` → use results
- `"no_results"` → try different tool
- `"error"` → immediately fallback or submit best guess

## When to Use Which

- **Goose**: Testing fallback strategies, more exploratory search
- **OpenHands**: Faster, cleaner tool calling, smaller token budgets

## Deployment

Both harnesses automatically:
1. Download latest MCP bundle from `http://147.182.206.223:9090/mcp_bundle.tar.gz`
2. Use updated tool schemas with status fields
3. Follow prompt guidelines for error handling

To deploy new changes:
1. Update `server/tools.py` (server code)
2. Update both prompts (`goose_instructions.md` + `system.j2`)
3. Run `./build_mcp_bundle.sh`
4. `scp mcp_bundle.tar.gz root@147.182.206.223:/var/www/html/`
5. Done! Both harnesses auto-load on next run

## Current Improvements (Both Harnesses)

✓ Explicit status fields for tool failures
✓ Early abort on 2 consecutive failures
✓ Grep output capped at 10 lines (Goose only)
✓ Budget-aware stopping rules
✓ Better error recognition
