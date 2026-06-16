# Install Prep50 Coverage on Ubuntu (office LAN)

Native install (no Docker) on a single Ubuntu server, deployed to
`/var/www/prep50-coverage`, served to every machine on the office LAN through
**one Nginx port (80)**. The frontend and the API live behind the same Nginx,
so other computers on the network just need the server's IP — no per-device
configuration, no broken API calls from remote browsers.

Tested on Ubuntu 22.04 LTS and 24.04 LTS.

---

## Why your current setup breaks on other computers

The bug you're hitting is real and has one specific cause. When you build the
Next.js frontend, the API URL gets **baked into the JavaScript bundle**. If
you build it with `NEXT_PUBLIC_API_URL=http://localhost:8000`, every browser
that loads your site — including the one on the computer down the hall —
will try to call `http://localhost:8000` from **its own machine**, not from
the server. That's why those computers see the page but get no data.

There are two ways to fix it:

1. **Bake the server's IP into the bundle** (`NEXT_PUBLIC_API_URL=http://192.168.1.10:8000`). Works, but breaks when the IP changes and forces you to open two firewall ports.
2. **Use Nginx as a reverse proxy** so the frontend and the API share **one origin** (`http://192.168.1.10`). Then `NEXT_PUBLIC_API_URL` is just blank, every browser calls `/api/...` on the same server it loaded the page from, and there are no IP gotchas. This is the standard production approach.

This guide uses option 2.

---

## 1. Architecture

```
Browser on any office computer
        │
        │ http://<server-LAN-IP>/
        ▼
┌────────────────────────────────────┐
│  Office server (Ubuntu)            │
│                                    │
│  Nginx :80    ─┬─►  /          ─►  Next.js  (127.0.0.1:3000)
│                └─►  /api/...   ─►  FastAPI  (127.0.0.1:8000)
└────────────────────────────────────┘
        │
        ▼
   Postgres (DigitalOcean managed, or local)
```

Three pieces, all on the same server:

| Service | Where | Bound to |
|---|---|---|
| FastAPI | `/var/www/prep50-coverage` (runs from `.venv`) | `127.0.0.1:8000` — local only |
| Next.js | `/var/www/prep50-coverage/frontend` (`npm run start`) | `127.0.0.1:3000` — local only |
| Nginx | system-installed | `0.0.0.0:80` — the only public-facing port |

You only open **one port** on the firewall (80). All LAN clients reach
`http://<server-LAN-IP>/`.

---

## 2. Prerequisites you need before starting

| What | Where to get it |
|---|---|
| Ubuntu server with a static LAN IP | Ask your IT lead. Example used below: `192.168.1.10`. |
| `sudo` access on the server | Either as root or a user in the sudo group. |
| The server's IP fixed in your router | Otherwise the IP will drift and browsers will break. Get the IT team to reserve it by MAC. |
| `vertex_key.json` (GCP service account) | Copy from the laptop where it currently lives. |
| `OPENAI_API_KEY` | The key you already have. |
| Postgres connection details | The DigitalOcean credentials from `.env`. |

Find the server's LAN IP once you're logged in:

```bash
hostname -I | awk '{print $1}'
```

Use that value everywhere this guide says `192.168.1.10`.

---

## 3. Install system packages

```bash
sudo apt-get update
sudo apt-get install -y \
  python3.12 python3.12-venv python3-pip \
  build-essential libpq-dev pkg-config \
  git curl nginx ufw
```

Node 22 (from NodeSource, the official supported route):

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
```

Sanity check:

```bash
python3 --version       # 3.12.x
node --version          # v22.x
npm --version
nginx -v
```

---

## 4. Prepare the deploy folder

You're already running services as the existing user **`deacons-publishers`**.
This guide assumes that user exists; you only need to create the directory
and hand it to them.

```bash
sudo mkdir -p /var/www/prep50-coverage
sudo chown deacons-publishers:deacons-publishers /var/www/prep50-coverage
```

Optional — let yourself `su` into that user without typing a password every time:

```bash
sudo usermod -aG deacons-publishers $USER   # log out + back in for it to take effect
```

---

## 5. Clone the code

Switch to the service user before doing this, so all files end up with the
right ownership:

```bash
sudo -iu deacons-publishers
cd /var/www/prep50-coverage
git clone https://github.com/deaconsed/prep50-coverage.git .
```

(The `.` at the end clones into the current directory rather than a subfolder.)

---

## 6. Configure secrets

Still as the `deacons-publishers` user, in `/var/www/prep50-coverage`:

```bash
cp .env.example .env
nano .env       # or vim — fill in real values
```

Fill in the real values:

```dotenv
# Database — your DigitalOcean managed Postgres
DB_HOST=143.198.141.149
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=<the real password>
DB_NAME=prep50
DB_SSLMODE=require

# Vertex AI — same project you've been using
GOOGLE_CLOUD_PROJECT=rising-area-483510-j7
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/var/www/prep50-coverage/vertex_key.json

# OpenAI — for the AI rerank step
OPENAI_API_KEY=sk-...

# Optional rerank tuning (defaults are fine)
# AI_RERANK_ENABLED=true
# AI_RERANK_MODEL=gpt-4o-mini
# AI_RERANK_TOP_K=20

# CORS — Nginx proxies same-origin so this can stay empty. Listed here for clarity.
FRONTEND_ORIGINS=http://127.0.0.1,http://localhost
```

Drop `vertex_key.json` into the project root. From your laptop:

```bash
scp vertex_key.json deacons-publishers@192.168.1.10:/var/www/prep50-coverage/
```

Lock down permissions on both files:

```bash
chmod 600 .env vertex_key.json
```

---

## 7. Frontend env — the critical bit

Create `frontend/.env.local` (still as the `deacons-publishers` user):

```bash
cat > /var/www/prep50-coverage/frontend/.env.local <<'EOF'
# Empty value → fetch calls become "/api/..." which Nginx proxies to FastAPI
# on the same origin. THIS is what makes other computers work.
NEXT_PUBLIC_API_URL=
NEXT_PUBLIC_SHOW_TECHNICAL=false
EOF
```

**Important**: the empty value isn't a typo. Leaving `NEXT_PUBLIC_API_URL=`
empty makes the frontend issue requests relative to the host it was loaded
from (same-origin). When a browser on another office computer opens
`http://192.168.1.10/`, the frontend calls `http://192.168.1.10/api/...`
which Nginx routes to FastAPI. Other computers don't need to know anything
about port 8000 or `localhost`.

---

## 8. Python virtualenv + dependencies

```bash
cd /var/www/prep50-coverage
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
```

---

## 9. Frontend build

```bash
cd /var/www/prep50-coverage/frontend
npm ci
npm run build
```

`npm run build` produces `.next/standalone` and `.next/static` — production
artifacts that `npm run start` serves. Roughly 60 seconds end-to-end on a
modest server.

---

## 10. Database — apply the migration once

If you're pointing `.env` at the already-populated DigitalOcean Postgres,
you've already done this. Skip ahead to step 11.

If this is a fresh database, apply the migration:

```bash
cd /var/www/prep50-coverage
PGPASSWORD=<password> psql -h <DB_HOST> -U postgres -d prep50 \
  -f migrations/prod_001_question_embeddings.sql
```

If the embeddings table is empty, run the one-time backfill (~20 minutes for
~30k questions; uses Vertex quota):

```bash
source .venv/bin/activate
python scripts/enrich_questions.py
deactivate
```

---

## 11. systemd services

Two service units. Both run as the `deacons-publishers` user and restart on failure.

Save as `/etc/systemd/system/prep50-api.service`:

```ini
[Unit]
Description=Prep50 Coverage API (FastAPI)
After=network.target

[Service]
Type=simple
User=deacons-publishers
Group=deacons-publishers
WorkingDirectory=/var/www/prep50-coverage
EnvironmentFile=/var/www/prep50-coverage/.env
ExecStart=/var/www/prep50-coverage/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --proxy-headers
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Save as `/etc/systemd/system/prep50-frontend.service`:

```ini
[Unit]
Description=Prep50 Coverage Frontend (Next.js)
After=network.target prep50-api.service

[Service]
Type=simple
User=deacons-publishers
Group=deacons-publishers
WorkingDirectory=/var/www/prep50-coverage/frontend
Environment=NODE_ENV=production
Environment=PORT=3000
Environment=HOSTNAME=127.0.0.1
ExecStart=/usr/bin/npm run start
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable + start both:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prep50-api prep50-frontend
sudo systemctl status prep50-api prep50-frontend --no-pager
```

You should see both `active (running)`. If either is `failed`, jump to
section 14 (Troubleshooting).

---

## 12. Nginx reverse proxy — the part that ties it together

Save as `/etc/nginx/sites-available/prep50-coverage`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name _;            # match any hostname / IP

    client_max_body_size 25M; # CSV uploads — generous

    # FastAPI under /api/*
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";

        # SSE streaming for /api/batches/{id}/events — critical
        proxy_buffering off;
        proxy_read_timeout 1h;
        proxy_send_timeout 1h;
    }

    # Everything else → Next.js
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Enable the site, disable the default, reload:

```bash
sudo ln -sf /etc/nginx/sites-available/prep50-coverage \
            /etc/nginx/sites-enabled/prep50-coverage
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t          # syntax check — must say "ok"
sudo systemctl reload nginx
```

---

## 13. Firewall

Open only port 80 to the LAN. Block everything else.

```bash
sudo ufw allow OpenSSH                # don't lock yourself out
sudo ufw allow 80/tcp                 # Nginx
sudo ufw --force enable
sudo ufw status verbose
```

If your office has a separate VLAN policy, ask IT to allow port 80 from the
office network to `192.168.1.10`.

**Ports 3000 and 8000 stay closed** — they're only accessible to the local
loopback (127.0.0.1) and shouldn't be reachable from outside the server.
That's by design.

---

## 14. Verify

On the server:

```bash
# Both services up
sudo systemctl is-active prep50-api prep50-frontend nginx

# API health (through Nginx)
curl -s http://127.0.0.1/api/health
# → {"status":"ok"}

# Frontend (through Nginx)
curl -sI http://127.0.0.1/
# → HTTP/1.1 200 OK
```

From another office computer:

```bash
# Replace with your server IP
curl http://192.168.1.10/api/corpus/stats
```

Then open a browser to `http://192.168.1.10/` from any office machine. You
should see the hero, the recent runs strip, and be able to upload a CSV +
watch verdicts stream.

---

## 15. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Other computers see the page but API never responds | Frontend was built with a hardcoded `NEXT_PUBLIC_API_URL` instead of being left blank | Set `NEXT_PUBLIC_API_URL=` (empty) in `frontend/.env.local`, then `npm run build` and `sudo systemctl restart prep50-frontend` |
| `502 Bad Gateway` on `/` | `prep50-frontend.service` isn't running | `sudo journalctl -u prep50-frontend -n 50` to read the error |
| `502 Bad Gateway` only on `/api/...` | `prep50-api.service` isn't running, or it can't reach the database | `sudo journalctl -u prep50-api -n 50` |
| SSE (live results) hangs and then dumps everything at once | Nginx `proxy_buffering` defaulted to on | Make sure your config has `proxy_buffering off;` under `location /api/` |
| `WebSocket /_next/webpack-hmr ... failed` errors in browser | You're running `npm run dev` instead of `npm run start` — HMR is a dev-only feature | Use the production build via systemd as documented |
| Connection refused to DB after a few minutes of idle | DigitalOcean managed Postgres closes idle connections | Already handled — the API auto-reconnects |
| AI rerank quietly disabled | `OPENAI_API_KEY` didn't make it into the systemd service env | Confirm with `sudo systemctl show prep50-api -p Environment` and that `EnvironmentFile=` points at the right `.env` |
| `Permission denied` on a file path | `deacons-publishers` user can't read it | `sudo chown -R deacons-publishers:deacons-publishers /var/www/prep50-coverage` |
| Browser caches the old broken bundle | Old build still served | Hard reload with `Ctrl+Shift+R` after a deploy |

Logs you'll want:

```bash
sudo journalctl -u prep50-api -f          # follow API logs
sudo journalctl -u prep50-frontend -f     # follow frontend logs
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

---

## 16. Updating after a code change

From any developer machine, push to GitHub. Then on the server:

```bash
sudo -iu deacons-publishers
cd /var/www/prep50-coverage
git pull

# If Python deps changed
source .venv/bin/activate
pip install -r requirements.txt
deactivate

# If frontend changed
cd frontend
npm ci                    # only if package.json changed; otherwise skip
npm run build
cd ..

exit                      # back to your sudo user

sudo systemctl restart prep50-api prep50-frontend
```

The whole loop is about 2 minutes for code-only changes.

---

## 17. Backups (worth doing once)

The `ingestion_batches/` folder holds every coverage report you've ever run.
Back it up to S3 or another disk weekly:

```bash
# Append to crontab via `sudo crontab -e`
0 2 * * * tar czf /backups/prep50-batches-$(date +\%F).tar.gz /var/www/prep50-coverage/ingestion_batches
```

The database itself should also be backed up — DigitalOcean managed Postgres
does this for you. If you've moved to a self-hosted DB, use `pg_dump` on a
schedule.

---

## 18. Adding HTTPS later (optional)

For an office-only deployment, HTTP is usually fine. If you want HTTPS later
(e.g., serving the tool externally), `certbot` handles it in five minutes:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d coverage.yourdomain.com
```

Certbot will edit the Nginx config in place, force-redirect HTTP → HTTPS,
and renew automatically.

---

## 19. Cheat sheet

```
/var/www/prep50-coverage/
├── .env                       # secrets (chmod 600, owned by deacons-publishers)
├── vertex_key.json            # GCP service account (chmod 600)
├── .venv/                     # Python virtualenv
├── api/                       # FastAPI service
├── frontend/                  # Next.js app
│   ├── .env.local             # NEXT_PUBLIC_API_URL= (EMPTY!) for same-origin
│   ├── .next/                 # build output (from `npm run build`)
│   └── ...
├── scripts/                   # CLI tools (enrich, docx_to_csv, etc.)
└── ingestion_batches/         # historical reports (back this up)

/etc/systemd/system/
├── prep50-api.service
└── prep50-frontend.service

/etc/nginx/sites-available/prep50-coverage
/etc/nginx/sites-enabled/prep50-coverage → ../sites-available/...
```

Daily commands:

```bash
# Status of everything
sudo systemctl status prep50-api prep50-frontend nginx --no-pager

# Restart after a config change
sudo systemctl restart prep50-api prep50-frontend

# Tail logs
sudo journalctl -u prep50-api -f
```

That's it. One server, one open port, one URL for everyone in the office.
