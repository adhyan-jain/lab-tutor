# LabTutor backend
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so a code change does not reinstall the world.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
# alembic.ini lives at the repo root, not under backend/ -- without this
# line `alembic upgrade head` inside the container has no config file at
# all (backend/migrations/env.py's script_location is relative to it).
COPY alembic.ini /app/alembic.ini

# Docker Compose mounts the manual read-only at runtime
# (../manual:/app/manual:ro); a platform with no host-volume equivalent
# (e.g. Cloud Run) needs it baked into the image instead. Baking it in
# here doesn't change Compose's behavior -- its bind-mount still overlays
# this same path at container start, taking precedence over image
# content, so local dev keeps editing the manual live exactly as before.
COPY manual /app/manual

# backend/sources/manifest.py refuses to ingest anything not declared in
# docs/source_manifest.json, and every document that manifest marks
# "present: true" must actually exist at that path -- found live via a
# deployed-service smoke test: the very first real chat message 500'd
# with ManifestError because none of these three were in the image
# (only manual/ was, from the fix above). Only the manifest itself is
# copied out of docs/ -- the rest of that folder is internal handoff/
# audit notes with no runtime purpose.
COPY docs/source_manifest.json /app/docs/source_manifest.json
COPY knowledge/adjacent /app/knowledge/adjacent
COPY golden_dataset/qa /app/golden_dataset/qa
COPY sources/tier_b /app/sources/tier_b

# Runs unprivileged.
RUN useradd --create-home --uid 10001 labtutor \
    && chown -R labtutor:labtutor /app
USER labtutor

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

# Migrations run once, on container start, before the app takes traffic --
# `backend.main`'s startup deliberately does NOT call create_all() in
# production (see its lifespan()), so this is the only thing that builds
# or updates the schema there. Worker count is env-driven (default 2,
# matching Docker Compose's single always-on container) because each
# worker is a separate process with its OWN DB connection pool
# (backend/db.py) -- a platform that already scales horizontally by
# adding container instances (e.g. Cloud Run) should run ONE worker per
# instance and let the platform's own autoscaling do the rest, or the
# real connection ceiling multiplies twice over.
ENV UVICORN_WORKERS=2
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS}"]
