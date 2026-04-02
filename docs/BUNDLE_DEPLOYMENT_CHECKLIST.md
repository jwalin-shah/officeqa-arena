# MCP Bundle Deployment Checklist

## Status as of 2026-04-02 10:10 UTC

### ✅ Completed Setup

#### 1. Bundle Creation
- [x] `mcp_bundle.tar.gz` created locally (118KB)
- [x] Contains: server/, prompts/, scripts/, run_mcp.sh, arena.yaml, requirements.txt, data/reference/
- [x] Verified: extraction test successful
- [x] Guardrails present: 4/4 (Back-off, Shell Limit, Verification, Finalization)

#### 2. DDB Deployment
- [x] Bundle uploaded to `http://147.182.206.223:9090/mcp_bundle.tar.gz`
- [x] Location: `/var/www/officeqa/mcp_bundle.tar.gz`
- [x] Nginx serving on port 9090
- [x] HTTP 200 OK confirmed via curl

#### 3. Arena Integration
- [x] arena.yaml updated with correct port 9090
- [x] MCP server command: `curl -fsSL http://147.182.206.223:9090/mcp_bundle.tar.gz | tar xz -C /tmp && chmod +x /tmp/run_mcp.sh && exec /tmp/run_mcp.sh`
- [x] Command verified to work end-to-end

#### 4. Documentation
- [x] Created `docs/MCP_BUNDLE_SETUP.md` (complete reference)
- [x] Includes: architecture, components, workflow, troubleshooting
- [x] Git commits: `be4e65f`, `611d41c`

#### 5. Guardrails in Prompts
- [x] Back-off Trigger: Prevents repeating same grep/ls/tree 3+ times
- [x] Shell Limit: 40 command max (force finalize at 35)
- [x] Verification Step: Mandatory target/unit/reasonableness checks
- [x] Finalization Handshake: Write to /app/answer.txt before submit

#### 6. Infrastructure
- [x] LANES_PER_RUNNER: 4 → 2 (OOM prevention)
- [x] RAM per lane: 4GB → 8GB on 16GB droplets
- [x] Expected fix: Exit Code 137 (OOM kills)

#### 7. Telemetry
- [x] Server running: `python3 /root/telemetry_server.py --port 8080`
- [x] Logging to: `/root/telemetry_live.jsonl`
- [x] Configured in arena.yaml: `TELEMETRY_URL: "http://147.182.206.223:8080"`

---

## How to Use the Bundle System

### For Local Development

**When you modify code**:
```bash
# 1. Make changes (e.g., add guardrails to prompts/goose_instructions.md)
# 2. Test locally
# 3. Create new bundle
tar -czf mcp_bundle.tar.gz \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
  server/ prompts/ scripts/executor.py scripts/stage_runner.py \
  run_mcp.sh run_mcp_with_db.sh arena.yaml requirements.txt data/reference/

# 4. Upload to DDB
scp mcp_bundle.tar.gz root@147.182.206.223:/var/www/officeqa/

# 5. Verify
curl -I http://147.182.206.223:9090/mcp_bundle.tar.gz

# 6. Commit to git
git add <changed files>
git commit -m "feat: describe your change"
```

### For Testing

**Option 1: Manual extraction test**
```bash
mkdir -p /tmp/bundle_test
curl -fsSL http://147.182.206.223:9090/mcp_bundle.tar.gz | tar xz -C /tmp/bundle_test
ls -la /tmp/bundle_test/
```

**Option 2: Via arena submit**
```bash
# Uses arena.yaml MCP command (curls bundle automatically)
arena submit
```

**Option 3: Via runner pool**
```bash
# Runs against actual runner infrastructure
RUN_LABEL=test ./scripts/do_runner_pool.sh run --uids "UID0001,UID0002"
```

---

## Current Runs

### OOM-Prone Task Rerun
**Label**: `pool-20260402T165000Z-oom-fix`

**UIDs** (19 tasks):
- UID0001, UID0007, UID0011, UID0014, UID0021, UID0022, UID0027, UID0028, UID0034
- UID0053, UID0114, UID0118, UID0153, UID0161, UID0165, UID0179, UID0188, UID0208, UID0216

**Expected Improvements**:
- **OOM Fix** (Exit Code 137): 8GB RAM/lane vs 4GB
- **Anti-Spiral**: 40-cmd limit prevents runaway loops
- **Accuracy**: Verification step reduces calculation errors

**Monitoring**:
```bash
# Check progress
tail -f /tmp/oom_run.log

# When done, results will be in:
results/runner_pool/pool-20260402T165000Z-oom-fix/deep_trials/
```

---

## Key Files

| File | Purpose | Last Updated |
|------|---------|--------------|
| `mcp_bundle.tar.gz` | Packaged agent code | 2026-04-02 |
| `/var/www/officeqa/mcp_bundle.tar.gz` (on DDB) | Hosted for download | 2026-04-02 |
| `arena.yaml` | Arena config with MCP command | 2026-04-02 (port 9090) |
| `prompts/goose_instructions.md` | Agent instructions + guardrails | 2026-04-02 |
| `scripts/do_runner_pool.sh` | Runner pool control (2 lanes/runner) | 2026-04-02 |
| `run_mcp.sh` | MCP launcher with DB auto-download | 2026-04-02 |
| `docs/MCP_BUNDLE_SETUP.md` | Complete reference docs | 2026-04-02 |

---

## Troubleshooting

### Bundle Not Accessible
```bash
# Check DDB
ssh root@147.182.206.223 "ls -lh /var/www/officeqa/"

# Test curl
curl -v http://147.182.206.223:9090/mcp_bundle.tar.gz 2>&1 | head -20
```

### Containers Using Old Code
**Cause**: Bundle was updated but container hasn't restarted

**Fix**: Restart container (bundle is fetched on each init)
```bash
# For runner pool, restart will auto-fetch new bundle
docker restart <container_id>
```

### Missing Files in Bundle
**Check**:
```bash
tar -tzf mcp_bundle.tar.gz | grep server/tools.py
tar -tzf mcp_bundle.tar.gz | grep prompts/goose_instructions.md
```

**Fix**: Recreate and re-upload bundle

---

## Next Steps (If Needed)

- [ ] Monitor OOM rerun results → evaluate success rate
- [ ] If improved: run full 246-task rerun
- [ ] If not: investigate remaining OOM causes
- [ ] Consider bundle versioning (e.g., mcp_bundle_v2.tar.gz)
- [ ] Set up automated bundle creation on git push
