# Hosting the SQLite Database for Arena Containers

## Problem

We need Arena Docker containers to download a ~600MB-1GB compressed SQLite
database during setup. The containers run on the "sentient" droplet with
`allow_internet = true`. Speed matters -- download should take <30 seconds.

## Recommendation: Serve from the Droplet via Docker Bridge (Option 1)

**This is the clear winner.** Arena containers run ON the same droplet. By
serving the file from the host, the "download" is just a local data copy over
the Docker bridge network -- no real network traversal, essentially disk-read
speed. A 1GB file transfers in ~2-5 seconds over the bridge.

### How Docker containers reach the host

Docker containers on the default bridge network can reach the host at the
**gateway IP of the bridge**, which is almost always `172.17.0.1`. This is
the IP of the `docker0` interface on the host.

Alternative addresses:
- `host.docker.internal` -- works on Docker Desktop (macOS/Windows) but is
  **NOT available by default on Linux**. The droplet runs Linux, so do not
  rely on this.
- The droplet's public IP -- works if `allow_internet = true`, but adds
  unnecessary overhead (traffic goes out and back through the NIC).

**Use `172.17.0.1` as the primary target.** As a fallback, also try the
droplet's public/private IP.

### Verification

To confirm the bridge gateway IP on the droplet:

```bash
# On the droplet (host)
ip addr show docker0
# Look for inet 172.17.0.1/16

# Or:
docker network inspect bridge | grep Gateway
# Should show "172.17.0.1"
```

To test from inside a container:

```bash
docker run --rm alpine wget -qO- http://172.17.0.1:9123/test.txt
```

---

## Setup: One-Time on the Droplet

### Step 1: Place the compressed database file

```bash
ssh sentient

# Create a dedicated directory for serving
sudo mkdir -p /srv/officeqa-data
sudo chown $USER:$USER /srv/officeqa-data

# Copy/move the compressed DB there
# (adjust source path as needed)
cp /path/to/officeqa_corpus.sqlite3.zst /srv/officeqa-data/
```

### Step 2: Start a lightweight HTTP file server

**Option A: Python (simplest, zero install)**

```bash
cd /srv/officeqa-data
nohup python3 -m http.server 9123 --bind 0.0.0.0 > /tmp/fileserver.log 2>&1 &
```

Pros: Zero dependencies, already installed.
Cons: Single-threaded, no range requests, no compression negotiation. But for
a single large file served to local containers, this is fine.

**Option B: Nginx (best for production, supports range requests)**

```bash
sudo apt-get install -y nginx

# Create a minimal config
sudo tee /etc/nginx/sites-available/officeqa-data << 'CONF'
server {
    listen 9123;
    server_name _;

    location / {
        root /srv/officeqa-data;
        autoindex on;
        sendfile on;
        tcp_nopush on;
        tcp_nodelay on;
    }
}
CONF

sudo ln -sf /etc/nginx/sites-available/officeqa-data /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx
```

Pros: Fast, supports partial downloads/resume, handles concurrent requests.
Cons: Requires install (one-time).

**Option C: Caddy one-liner (if already installed)**

```bash
caddy file-server --listen :9123 --root /srv/officeqa-data &
```

### Step 3: Make it survive reboots (systemd)

For Python:

```bash
sudo tee /etc/systemd/system/officeqa-fileserver.service << 'UNIT'
[Unit]
Description=OfficeQA static file server
After=network.target

[Service]
Type=simple
WorkingDirectory=/srv/officeqa-data
ExecStart=/usr/bin/python3 -m http.server 9123 --bind 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now officeqa-fileserver
```

### Step 4: Firewall (optional, for security)

Only allow connections from Docker bridge, not the public internet:

```bash
# If using ufw:
sudo ufw allow from 172.17.0.0/16 to any port 9123
sudo ufw deny 9123
```

---

## Download from Inside Arena Containers

In the agent's setup script or at the start of `run_mcp.sh`:

```bash
DB_URL="http://172.17.0.1:9123/officeqa_corpus.sqlite3.zst"
DB_DIR="/app/corpus"
DB_FILE="${DB_DIR}/officeqa_corpus.sqlite3"

if [ ! -f "$DB_FILE" ]; then
    mkdir -p "$DB_DIR"
    echo "Downloading database..."
    wget -q "$DB_URL" -O "${DB_FILE}.zst" \
        || curl -sL "$DB_URL" -o "${DB_FILE}.zst"

    # Decompress (zstd is fastest; gzip works too)
    zstd -d "${DB_FILE}.zst" -o "$DB_FILE" && rm "${DB_FILE}.zst"
    # OR if using gzip: gunzip "${DB_FILE}.gz"

    echo "Database ready: $(du -h "$DB_FILE" | cut -f1)"
fi
```

### Compression format recommendation

| Format | Compress ratio | Decompress speed | Tool availability |
|--------|---------------|------------------|-------------------|
| zstd   | Best (~3-4x)  | Fastest          | May need install   |
| gzip   | Good (~2-3x)  | Fast             | Always available   |
| xz     | Best (~4x)    | Slow             | Usually available  |

**Use zstd if available** (best ratio + fastest decompress). Fall back to gzip
for maximum compatibility since it is guaranteed to be in any Linux container.

```bash
# Compress with zstd (on the host, one-time)
zstd -19 officeqa_corpus.sqlite3 -o officeqa_corpus.sqlite3.zst

# Or with gzip
gzip -9 -k officeqa_corpus.sqlite3
```

---

## Fallback strategies

If `172.17.0.1` does not work (e.g., Arena uses a custom Docker network):

```bash
# Try these in order:
HOSTS="172.17.0.1 host.docker.internal $(hostname -I | awk '{print $1}')"
for h in $HOSTS; do
    wget -q --timeout=3 "http://${h}:9123/officeqa_corpus.sqlite3.zst" -O /tmp/db.zst && break
done
```

If Docker host access is blocked entirely, fall back to an external URL
(GitHub Release, S3, etc.) -- see alternatives below.

---

## Alternatives Comparison

| Option | Speed from container | Setup effort | Cost | Reliability |
|--------|---------------------|-------------|------|-------------|
| **Droplet HTTP (localhost)** | ~2-5s (bridge) | Low | Free | High |
| GitHub Releases | 10-60s (varies) | Low | Free (<2GB) | Medium |
| S3/R2/B2 | 5-30s | Medium | ~$0.01/download | High |
| Bake into Docker image | 0s (pre-loaded) | High | Free | Highest |

### Baking into the Docker image (long-term best)

The `docker_image` in task.toml is `ghcr.io/sentient-agi/harbor/officeqa-corpus:latest`.
If we control this image, we could bake the DB right into it. Then there is
zero download time. But we likely do not control this image (it is the Arena's
base image). If we did control it:

```dockerfile
FROM ghcr.io/sentient-agi/harbor/officeqa-corpus:latest
COPY officeqa_corpus.sqlite3 /app/corpus/
```

### GitHub Releases

```bash
# Upload (one-time, from local machine)
gh release create db-v1 officeqa_corpus.sqlite3.zst \
    --repo youruser/officeqa-arena \
    --title "Database v1" --notes "Compressed SQLite corpus"

# Download (from container)
wget -q "https://github.com/youruser/officeqa-arena/releases/download/db-v1/officeqa_corpus.sqlite3.zst"
```

Limit: 2GB per asset. Speed varies (10-60s for 1GB).

---

## Quick-Start Checklist

1. SSH into the droplet: `ssh sentient`
2. Verify Docker bridge gateway: `docker network inspect bridge | grep Gateway`
3. Place compressed DB in `/srv/officeqa-data/`
4. Start file server: `python3 -m http.server 9123 --bind 0.0.0.0`
5. Test from a container: `docker run --rm alpine wget -qO /dev/null http://172.17.0.1:9123/officeqa_corpus.sqlite3.zst`
6. Add download logic to `run_mcp.sh` (before the Python exec)
7. Persist with systemd for reboots
