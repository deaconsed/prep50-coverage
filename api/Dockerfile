# FastAPI service. Built from the project root so we can include scripts/
# and normalize.py alongside the api/ package.
#
#   docker build -f api/Dockerfile -t prep50-api .
#
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# psycopg2-binary, google-cloud-aiplatform are wheel-only — no compiler needed.
# Keep the slim image small; uvicorn[standard] pulls in uvloop on Linux.

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Application source. .env + vertex_key.json are mounted at runtime, not baked.
COPY api /app/api
COPY scripts /app/scripts
COPY normalize.py /app/normalize.py
# ingestion_batches/ is a bind-mount volume — empty in the image.
RUN mkdir -p /app/ingestion_batches

EXPOSE 8000

# Use --proxy-headers so /api works correctly behind a reverse proxy.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
