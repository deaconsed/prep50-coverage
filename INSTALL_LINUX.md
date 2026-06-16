# Install Prep50 Coverage on Linux

Practical install guide for Ubuntu 22.04 / Debian 12 / similar. Two paths:
**Docker (recommended)** or **native install**. Pick one.

The Docker path needs ~10 minutes, no system-level Python or Node tweaks, and
ships everything as containers. The native path is what you'd run in dev or
on a host where Docker isn't available.

---

## 1. Prerequisites

You'll need:

| What | Why |
|---|---|
| Linux box with at least 2 GB RAM and 5 GB disk | Runs the API, the Next.js frontend, and (optionally) a local Postgres |
| A Postgres database with `pgvector` 0.8+ enabled | Stores the question_embeddings side table. Either local Docker, a self-hosted instance, or a managed service (DigitalOcean / Supabase / RDS). |
| **Vertex AI** service account JSON | Used for the embedding model (`text-embedding-005`) |
| **OpenAI API key** | Used for the AI rerank step (`gpt-4o-mini` by default) |
| Domain or LAN IP | Where the app will be reachable from |

Both API keys are required for full coverage checks. If you skip the OpenAI
key the app still works — the rerank step degrades to cosine-only.

---

## 2. Path A — Docker (recommended)

### 2.1 Install Docker

Ubuntu / Debian:

```bash
# Add the official Docker apt repo
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Run docker without sudo
sudo usermod -aG docker $USER
newgrp docker
```

RHEL / Fedora: `sudo dnf install -y docker docker-compose-plugin && sudo systemctl enable --now docker`.

Smoke-test:

```bash
docker run --rm hello-world
```

### 2.2 Get the code

```bash
cd /opt   # or wherever you keep services
git clone <repo-url> Prep50-vector
cd Prep50-vector
```

### 2.3 Provide the secrets

Drop two files into the project root:

- `vertex_key.json` — your GCP service account JSON, with at minimum the
  `roles/aiplatform.user` role on the embedding project.
- `.env` — config + credentials. Template below.

`.env` template:

```dotenv
# --- Database (point at a Postgres with pgvector 0.8+) ---
DB_HOST=your-db-host
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=replace-me
DB_NAME=prep50
DB_SSLMODE=require   # 'require' for managed PG, 'prefer' for self-hosted

# --- Vertex AI (embedding model) ---
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=vertex_key.json

# --- OpenAI (AI rerank step) ---
OPENAI_API_KEY=sk-...

# --- Optional AI rerank tuning ---
# AI_RERANK_ENABLED=true       # set false to disable rerank entirely
# AI_RERANK_MODEL=gpt-4o-mini  # or gpt-4o for higher quality
# AI_RERANK_TOP_K=20           # how deep into ANN candidates to rerank
```

Permissions:

```bash
chmod 600 .env vertex_key.json
```

### 2.4 Build + run

```bash
# Build images and start API + frontend (+ optional local Postgres)
docker compose up -d --build

# Or just API + frontend if your Postgres is external
docker compose up -d --build api frontend
```

That brings up:

| Container | Port | What |
|---|---|---|
| `prep50_api` | `8000` | FastAPI + AI pipeline |
| `prep50_frontend` | `3000` | Next.js 16 app |
| `prep50_pg` (optional) | `15433` | Local Postgres with pgvector (only useful for dev) |

Logs:

```bash
docker compose logs -f api frontend
```

Stop:

```bash
docker compose down            # keeps any local Postgres volume
docker compose down -v         # nukes the local Postgres volume
```

### 2.5 Point the frontend bundle at your real public hostname

Important: `NEXT_PUBLIC_API_URL` is baked into the frontend at build time. The
default in `docker-compose.yml` is `http://localhost:8000` — that only works
when accessing from the same host as the API. For LAN / public access:

```yaml
# docker-compose.yml
frontend:
  build:
    args:
      NEXT_PUBLIC_API_URL: "http://203.0.113.10:8000"   # your public host
      NEXT_PUBLIC_SHOW_TECHNICAL: "false"
```

Then rebuild only the frontend:

```bash
docker compose up -d --build frontend
```

Also tell the API which origins to trust for CORS:

```yaml
# docker-compose.yml
api:
  environment:
    FRONTEND_ORIGINS: "http://203.0.113.10:3000,https://yourdomain.com"
```

```bash
docker compose up -d api
```

### 2.6 Open the firewall

```bash
# ufw
sudo ufw allow 3000/tcp
sudo ufw allow 8000/tcp

# firewalld
sudo firewall-cmd --permanent --add-port=3000/tcp
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

### 2.7 Verify

```bash
curl -s http://localhost:8000/api/health
# → {"status":"ok"}

curl -s http://localhost:8000/api/corpus/stats | python3 -m json.tool
# → totals + by_subject map

curl -sI http://localhost:3000/
# → HTTP/1.1 200 OK
```

Open `http://<host>:3000` in a browser. You should see the hero, your corpus
size, and the recent runs strip.

---

## 3. Path B — Native install (no Docker)

Best when you want to develop / hack on the code.

### 3.1 System packages

Ubuntu 22.04+:

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip \
                        build-essential libpq-dev curl git
```

Node 22 (via NodeSource):

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
```

Verify:

```bash
python3 --version   # >= 3.12
node --version      # v22.x
npm --version
```

### 3.2 Get the code

```bash
cd /opt
git clone <repo-url> Prep50-vector
cd Prep50-vector
```

### 3.3 Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.4 Frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 3.5 Configure secrets

Same `.env` and `vertex_key.json` as in section 2.3, both placed at the
project root. Then also add a `.env.local` under `frontend/`:

```dotenv
# frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SHOW_TECHNICAL=false
```

Replace `localhost` with your public host when going beyond local dev.

### 3.6 Run the services

API (terminal 1):

```bash
source .venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Frontend dev mode (terminal 2):

```bash
cd frontend
npm run dev:lan     # binds 0.0.0.0:3000
```

Or production mode:

```bash
cd frontend
npm run build
npm run start:lan
```

---

## 4. Database setup

### 4.1 If you already have a Postgres with pgvector

Just point `.env` at it, then apply the migration once:

```bash
psql "postgresql://USER:PASS@HOST:5432/DBNAME?sslmode=require" \
  -f migrations/prod_001_question_embeddings.sql
```

### 4.2 If you're using the bundled docker-compose `db` service (dev only)

`docker compose up -d db` brings up a fresh pgvector-enabled Postgres. To
populate it from a prod dump:

```bash
# Inside the running db container
docker exec -i prep50_pg psql -U postgres -d prep50 -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Restore your dump
pg_restore -U postgres -h localhost -p 15433 -d prep50 --no-owner --role=postgres prep50_dump.backup

# Apply the migration
psql "postgresql://postgres:localdev@localhost:15433/prep50" \
  -f migrations/prod_001_question_embeddings.sql
```

### 4.3 Populate the embeddings (one-time)

This runs the embedding backfill against whatever Postgres `.env` points at.
Expect ~20 minutes for ~30k questions and uses your Vertex quota.

```bash
source .venv/bin/activate
python scripts/enrich_questions.py
```

The script is idempotent — it skips questions already embedded with the
current `MODEL_NAME` / `MODEL_VERSION`.

---

## 5. Production deployment notes

### 5.1 Reverse proxy with Nginx + TLS

If exposing to the internet, terminate TLS at Nginx and proxy to the
containers on `127.0.0.1`. Example:

```nginx
server {
  listen 443 ssl http2;
  server_name coverage.yourdomain.com;

  ssl_certificate     /etc/letsencrypt/live/coverage.yourdomain.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/coverage.yourdomain.com/privkey.pem;

  # Frontend
  location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
  }

  # API — proxied under /api/* so the frontend can hit same-origin
  location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_buffering off;          # critical for SSE streaming
    proxy_read_timeout 1h;        # batch processing can take minutes
  }
}
```

After this, set `NEXT_PUBLIC_API_URL=https://coverage.yourdomain.com` and
rebuild the frontend.

### 5.2 systemd (native install only)

If you went native (no Docker), use systemd to keep services running.

`/etc/systemd/system/prep50-api.service`:

```ini
[Unit]
Description=Prep50 Coverage API
After=network.target

[Service]
Type=simple
User=prep50
WorkingDirectory=/opt/Prep50-vector
EnvironmentFile=/opt/Prep50-vector/.env
ExecStart=/opt/Prep50-vector/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/prep50-frontend.service`:

```ini
[Unit]
Description=Prep50 Coverage Frontend
After=network.target prep50-api.service

[Service]
Type=simple
User=prep50
WorkingDirectory=/opt/Prep50-vector/frontend
ExecStart=/usr/bin/npm run start:lan
Restart=on-failure
RestartSec=5
Environment=NODE_ENV=production
Environment=PORT=3000
Environment=HOSTNAME=0.0.0.0

[Install]
WantedBy=multi-user.target
```

Enable both:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prep50-api prep50-frontend
sudo systemctl status prep50-api prep50-frontend
```

### 5.3 Log rotation

Both services log to stdout. With Docker you get `docker logs`; with systemd
you get `journalctl`. To trim journal disk usage:

```bash
sudo journalctl --vacuum-time=14d
```

---

## 6. Verifying everything works end-to-end

After install:

```bash
# 1. API is up and can talk to the DB
curl http://localhost:8000/api/corpus/stats

# 2. Frontend renders
curl -sI http://localhost:3000/

# 3. End-to-end: open the UI, drop a CSV, run a coverage check
#    (or use the converter to make one from a DOCX)
python scripts/docx_to_csv.py --input "example.docx" --out example.csv
```

Open `http://<host>:3000` → drop the CSV → pick the subject → click **Run
coverage check**. Within seconds you should see verdicts streaming in,
followed by the **Corpus coverage** percentage banner once the run finishes.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `connection refused` from API to DB | wrong `DB_HOST` / port closed / SSL not negotiated | Verify with `psql "postgresql://..."` from the same host. Try `DB_SSLMODE=require` on managed PG. |
| `OPENAI_API_KEY not set — AI rerank disabled` | env var didn't make it into the API process | With Docker, restart `api` after editing `.env`. With native, ensure the systemd unit has `EnvironmentFile=`. |
| Frontend shows blank corpus stats | API URL baked into the bundle is wrong | Rebuild the frontend with the right `NEXT_PUBLIC_API_URL` (see 2.5). |
| `psycopg2.InterfaceError: connection already closed` mid-batch | DB closed an idle connection | Already handled — the API auto-reconnects. If it persists, your DB has an unusually short idle timeout; restart the API. |
| `Blocked cross-origin request to Next.js dev resource` | LAN host not in `allowedDevOrigins` | Add your host pattern to `frontend/next.config.ts` and restart. |
| Browser console: `WebSocket connection ... failed` | Same as above — only happens in dev mode | Same fix. Production (`npm run start:lan`) doesn't use HMR so this can't happen there. |
| 502 / connection reset on SSE batch streaming | Nginx buffering or short read timeout | Set `proxy_buffering off;` and `proxy_read_timeout 1h;` on the `/api/` location (see 5.1). |
| `Could not decode CSV with utf-8 / cp1252 / latin-1` | CSV is a truly exotic encoding | Resave the CSV from Excel as **CSV UTF-8 (Comma delimited)** and re-upload. |
| AI rerank step takes too long | gpt-4o-mini at default `AI_RERANK_TOP_K=20` is the bottleneck | Lower to 10, or set `AI_RERANK_ENABLED=false` to disable rerank entirely. |

---

## 8. Updating

```bash
cd /opt/Prep50-vector
git pull

# Docker
docker compose up -d --build

# Native
source .venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
sudo systemctl restart prep50-api prep50-frontend
```

---

## 9. What goes where (cheat sheet)

```
/opt/Prep50-vector/
├── .env                       # database + Vertex + OpenAI credentials (chmod 600)
├── vertex_key.json            # GCP service account JSON (chmod 600)
├── docker-compose.yml         # the compose file you actually edit for prod
├── api/                       # FastAPI service
├── frontend/                  # Next.js app
│   └── .env.local             # NEXT_PUBLIC_API_URL etc. (native install only)
├── scripts/                   # one-off CLI tools (enrich, convert DOCX, etc.)
├── migrations/                # apply once at install time
└── ingestion_batches/         # JSON reports — mount as a volume if you want them to survive container restarts
```
