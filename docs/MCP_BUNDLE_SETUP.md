# MCP Bundle Hot-Reload Setup

## Overview

The MCP bundle system enables rapid iteration on agent code without manual runner synchronization. The bundle is hosted centrally on the "Data Droplet" (DDB) at `147.182.206.223` and automatically downloaded by each container on startup.

## Architecture

```
┌──────────────────────────────────────┐
│  Local Development Machine           │
│  /Users/jwalinshah/projects/         │
└────────────┬─────────────────────────┘
             │
             ├─ mcp_bundle.tar.gz created
             │  (server/, prompts/, scripts/)
             │
             └─> scp upload to DDB

┌──────────────────────────────────────┐
│  DDB (147.182.206.223)               │
│  /var/www/officeqa/                  │
│  nginx:9090                          │
│  mcp_bundle.tar.gz (118KB)           │
└────────────┬─────────────────────────┘
             │
             │ HTTP GET (on container startup)
             │
┌────────────▼─────────────────────────┐
│  Runner Container (Daytona)          │
│  /tmp/run_mcp.sh                     │
│                                      │
│  1. curl bundle from DDB             │
│  2. tar xz -C /tmp                   │
│  3. chmod +x /tmp/run_mcp.sh         │
│  4. exec /tmp/run_mcp.sh             │
│     └─> python3 -m server.mcp_stdio  │
└──────────────────────────────────────┘
```

## Components

### 1. **mcp_bundle.tar.gz** (Created Locally)

**Location**: `/Users/jwalinshah/projects/officeqa-arena/mcp_bundle.tar.gz`

**Contents**:
```
mcp_bundle.tar.gz
├── server/                      # MCP server (tools, routing, DB)
│   ├── mcp_stdio.py
│   ├── mcp_server.py
│   ├── tools.py                 # All tool definitions
│   ├── db.py                    # SQLite interface
│   ├── safe_eval.py
│   ├── date_resolver.py
│   └── cell_blobs.py
├── prompts/                     # Agent instructions (with guardrails)
│   ├── goose_instructions.md    # ← Updated with:
│   │                              • Back-off Trigger
│   │                              • 40-command Shell Limit
│   │                              • Verification Step
│   │                              • Finalization Handshake
│   ├── orchestrator_system.j2
│   ├── researcher_system.j2
│   └── ...
├── scripts/
│   ├── executor.py              # Task executor
│   └── stage_runner.py          # Stage/runner config
├── run_mcp.sh                   # MCP launcher (auto-downloads DB)
├── run_mcp_with_db.sh
├── arena.yaml                   # Arena harness config
├── requirements.txt             # Python dependencies
└── data/reference/              # Reference data
```

**Size**: ~118KB (compressed)

**Build Command**:
```bash
tar -czf mcp_bundle.tar.gz \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.git' \
  server/ prompts/ \
  scripts/executor.py scripts/stage_runner.py \
  run_mcp.sh run_mcp_with_db.sh \
  arena.yaml requirements.txt \
  data/reference/
```

### 2. **DDB Hosting** (Server)

**Location**: `http://147.182.206.223:9090/mcp_bundle.tar.gz`

**Directory**: `/var/www/officeqa/` (nginx root for port 9090)

**Nginx Config**:
```nginx
server {
    listen 9090;
    root /var/www/officeqa;
    autoindex on;
    location / {
        try_files $uri $uri/ =404;
    }
}
```

**Verification**:
```bash
curl -I http://147.182.206.223:9090/mcp_bundle.tar.gz
# Expected: HTTP/1.1 200 OK
```

### 3. **Arena Configuration** (Client)

**Location**: `arena.yaml` (lines 21-25)

**MCP Server Command**:
```yaml
mcp_servers:
  - name: officeqa-arena
    transport: stdio
    command: bash
    args: ["-c", "curl -fsSL http://147.182.206.223:9090/mcp_bundle.tar.gz | tar xz -C /tmp && chmod +x /tmp/run_mcp.sh && exec /tmp/run_mcp.sh"]
```

**What happens**:
1. Arena SDK starts the MCP server (calls the bash command)
2. Bash curls the bundle from DDB (`-fsSL` = fail silently, show progress, follow redirects)
3. Pipes directly to tar (`tar xz -C /tmp` = extract to /tmp)
4. Makes run_mcp.sh executable
5. Execs run_mcp.sh (becomes the MCP process)
6. run_mcp.sh handles DB auto-download and starts the MCP server

### 4. **Container Runtime** (run_mcp.sh)

**Location in Container**: `/tmp/run_mcp.sh` or `/opt/officeqa/run_mcp.sh`

**Flow**:
```bash
# 1. Bootstrap (first run only)
#    - Install zstd, pip, msgpack, zstandard
#    - Touch .bootstrap_done marker
#
# 2. Auto-download DB (if not found)
#    - Check for /app/corpus/officeqa_enriched.sqlite3
#    - If missing: curl officeqa_v3.sqlite3.zst | zstd -d
#    - Export OFFICEQA_SQLITE_DB=/app/corpus/officeqa_enriched.sqlite3
#
# 3. Start MCP server
#    - exec python3 -m server.mcp_stdio
#    - Connects to Arena SDK via JSON-RPC/stdio
```

## Workflow

### Creating/Updating the Bundle

**When you make changes to**:
- `server/` (tools, routing)
- `prompts/` (instructions, guardrails)
- `scripts/` (executor, runner)
- `requirements.txt` (dependencies)

**Steps**:
1. Make changes locally
2. Test locally or via `arena submit` (uses arena.yaml)
3. Create bundle:
   ```bash
   tar -czf mcp_bundle.tar.gz \
     --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
     server/ prompts/ scripts/executor.py scripts/stage_runner.py \
     run_mcp.sh run_mcp_with_db.sh arena.yaml requirements.txt data/reference/
   ```
4. Upload to DDB:
   ```bash
   scp mcp_bundle.tar.gz root@147.182.206.223:/var/www/officeqa/
   ```
5. Verify:
   ```bash
   curl -I http://147.182.206.223:9090/mcp_bundle.tar.gz
   # Should return: HTTP/1.1 200 OK
   ```
6. Commit changes:
   ```bash
   git add <changed files> run_mcp.sh arena.yaml
   git commit -m "feat/fix: <description of change>"
   ```

### Testing the Bundle

**Option A: Local Test**
```bash
# Extract locally to verify contents
tar -tzf mcp_bundle.tar.gz | head -20
# Should show: server/, prompts/, scripts/, run_mcp.sh, etc.
```

**Option B: Via Arena Submit**
```bash
# Uses arena.yaml MCP command; curls and extracts bundle
arena submit
# Monitor: tail -f /tmp/arena_*.log
```

**Option C: Direct Bundle Validation**
```bash
# Download and verify integrity
curl -fsSL http://147.182.206.223:9090/mcp_bundle.tar.gz \
  | tar -tzf - > /tmp/bundle_contents.txt
# Check: wc -l /tmp/bundle_contents.txt (should be >20 files)
```

## Guardrails Included

The updated `prompts/goose_instructions.md` includes:

1. **Back-off Trigger** (line 42)
   - Prevents repeating the same grep/ls/tree command 3+ times
   - Forces pivot to different tool

2. **Shell Limit** (line 43)
   - Maximum 40 shell commands per task
   - Force finalization at 35 commands

3. **Verification Step** (lines 45-50)
   - Mandatory pre-submit consistency check
   - Confirms target, units, reasonableness

4. **Finalization Handshake** (lines 52-54)
   - Write answer to `/app/answer.txt`
   - Graceful timeout handling

## OOM Prevention

Infrastructure changes in `scripts/do_runner_pool.sh`:
- **LANES_PER_RUNNER**: Reduced from 4 → 2
- **RAM per Lane**: 4GB → 8GB (on 16GB droplets)
- Prevents Exit Code 137 (OOM kills)

## Troubleshooting

### Bundle Not Found (404)
**Check**:
```bash
ssh root@147.182.206.223 "ls -la /var/www/officeqa/mcp_bundle.tar.gz"
curl -I http://147.182.206.223:9090/mcp_bundle.tar.gz
```
**Fix**: Re-upload the bundle

### Bundle Corrupted (tar fails)
**Test**:
```bash
curl -fsSL http://147.182.206.223:9090/mcp_bundle.tar.gz | tar -tzf - > /dev/null
```
**Fix**: Recreate and re-upload

### DB Download Fails in Container
**Check**:
```bash
# Inside container
curl -I http://147.182.206.223:9090/officeqa_v3.sqlite3.zst
```
**Fix**: Ensure DDB is reachable and DB file exists

### Stale Code in Container
**Cause**: Bundle was updated but container using old version
**Fix**: Restart container (bundle is fetched on each startup)

## Security Notes

- Bundle is transferred over plain HTTP (DDB on trusted internal network)
- No authentication needed (internal only)
- Bundle integrity checked by tar (file format validation)
- All code is committed to git (audit trail)

## Future Enhancements

- [ ] Bundle versioning (include commit hash in filename)
- [ ] Automatic bundle creation on git push
- [ ] Bundle checksum validation
- [ ] Compression level optimization
- [ ] Staging/testing bundle URL before production
