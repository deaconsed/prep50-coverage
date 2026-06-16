# Prep50 Coverage

Drop in any exam paper and see how much of it already lives in the Prep50
archive of historical WAEC questions. Combines exact-template matching with
semantic similarity so we can flag word-for-word repeats, close variants, and
genuinely new questions in seconds.

See `PRODUCT_PLAN.md` for the full design. This README is a runbook.

## What's here

```
api/             FastAPI service (HTTP + SSE wrapper over the Python pipeline)
frontend/        Next.js 16 + React 19 + Tailwind v4 + shadcn/ui app
scripts/         Production-tested Python pipeline (ingest_batch, check_duplicates, …)
dashboard/       Legacy Streamlit app (kept for fallback / comparison)
ingestion_batches/  JSON reports written by check / ingest runs
normalize.py     Pure-Python text normalization (HTML + Markdown aware)
migrations/      pgvector side-table schema
```

## Run the new stack (Docker, recommended)

Requires Docker Desktop + a populated `.env` and `vertex_key.json` at the project root.

```powershell
docker compose up -d --build
# Frontend:  http://localhost:3000
# API:       http://localhost:8000  (OpenAPI at /docs)
# DB (optional, only if you use local Docker Postgres): localhost:15433
```

Logs:

```powershell
docker compose logs -f api frontend
```

Stop:

```powershell
docker compose down            # keep DB volume
docker compose down -v         # nuke DB volume too
```

## Run the new stack (local dev)

Two terminals.

**API**:

```powershell
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

**Frontend**:

```powershell
cd frontend
npm install        # first time
npm run dev        # http://localhost:3000
```

## Run the legacy Streamlit dashboard

Kept alongside the new stack until React is fully validated.

```powershell
pip install streamlit pandas
streamlit run dashboard\app.py
```

## Environment

The `.env` file at the project root drives both the legacy dashboard and the
new API. Either local Docker or DigitalOcean Postgres works — just swap the
DB block.

```dotenv
# Database — choose one block
# Local Docker:
DB_HOST=localhost
DB_PORT=15433
DB_USER=postgres
DB_PASSWORD=localdev
DB_NAME=prep50
DB_SSLMODE=prefer

# Or DigitalOcean Postgres:
# DB_HOST=143.198.141.149
# DB_PORT=5432
# DB_USER=postgres
# DB_PASSWORD=<…>
# DB_NAME=prep50
# DB_SSLMODE=require

# Vertex AI
GOOGLE_CLOUD_PROJECT=<…>
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=vertex_key.json
```

## Common tasks

| Task | Command |
|---|---|
| Smoke-test the API end-to-end | `curl http://localhost:8000/api/corpus/stats` |
| Inspect the FastAPI OpenAPI | open `http://localhost:8000/docs` |
| Trigger an instant check from anywhere in the UI | press `Ctrl+K` (or `⌘K` on macOS) |
| Toggle technical detail (cosine numbers, model strings) | click the footer toggle, or append `?tech=1` to any URL |
| Re-render an old JSON report as the HTML demo view | `python scripts\render_dup_report.py --json <path>` |
| Backfill prod embeddings (one-time) | `python scripts\enrich_questions.py` (see `ingest_batch.py` constants) |

## Key URLs

| Page | Purpose |
|---|---|
| `/` | Landing + corpus stats + recent runs |
| `/check` | Upload CSV → live SSE results → review |
| `/batches` | History of all past runs |
| `/batches/<id>` | Saved batch detail (same review UI, read-only) |
| `/docs` (api port) | FastAPI auto-generated API documentation |
