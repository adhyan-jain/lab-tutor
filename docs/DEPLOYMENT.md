# Deployment and operations

How to run Catalyst for a class (~70 concurrent students), what to configure, and
what to do when something fails. Architecture is in [ARCHITECTURE.md](ARCHITECTURE.md);
LLM budget, caching and latency are in [llm.md](llm.md).

## Topology

| Piece | Where | Notes |
|---|---|---|
| Backend (FastAPI, uvicorn, 2 workers) | one VM, Docker Compose | long-running, streams chat over SSE; **not** a fit for Vercel serverless |
| Postgres 16 | same VM (compose `db` service) or a remote DB | no managed DB is required at this scale |
| Caddy | same VM | HTTPS, single origin for `/api/*` and the app |
| Frontend (Next.js) | the same compose stack, **or** Vercel | see below |

A small VM (2 vCPU / 8 GB, e.g. GCE e2-standard-2) is enough: only side questions
call the model; walkthrough steps, hints and navigation make no model call. The
real limit is the model provider's quota, not the server.

## Quick start (single host)

```bash
cp .env.example .env          # fill in every CHANGEME value
docker compose --env-file .env -f infra/docker-compose.yml up -d --build
```

Brings up backend, frontend, Postgres and Caddy; only the proxy is published. Keep
`--env-file .env`: without it Compose reads `${VAR}` substitutions from `infra/.env`, so the
database gets the default password while the backend gets yours, and the proxy serves `localhost`.
Migrations run on every backend start (`alembic upgrade head`).

Before a real session:

1. Register the Google OAuth client with redirect URI
   `{LABTUTOR_PUBLIC_URL}/api/auth/callback`.
2. `LABTUTOR_SESSION_SECRET` = `openssl rand -hex 32`; `LABTUTOR_ENV=production`
   (makes the session cookie `Secure` and refuses the dev secret).
3. Set the student/faculty/admin domain and email lists.
4. Rebuild images after pulling new code: containers do not pick up source changes.

Stop / start without losing data: `docker compose --env-file .env -f infra/docker-compose.yml stop|start`.
`down -v` **deletes the database volume**; do not run it unless you mean to.

## Frontend on Vercel (optional)

The browser only ever calls relative `/api/*`; `frontend/next.config.mjs` rewrites
that to `BACKEND_INTERNAL_URL`, which is baked in at **build** time.

1. Run the backend + Caddy on the VM with a DNS name (own domain or `<ip>.sslip.io`).
2. In Vercel, import `frontend/` and set `BACKEND_INTERNAL_URL=https://<vm-domain>`.
3. On the VM set `LABTUTOR_PUBLIC_URL=https://<vercel-url>` and add
   `https://<vercel-url>/api/auth/callback` to the Google OAuth redirect URIs.
4. **Test streaming through the Vercel rewrite** (tokens arrive incrementally and
   long answers are not cut). If they are buffered or cut off, serve the frontend
   from the VM through Caddy instead: it is one origin and needs no CORS or
   cross-site cookie handling.

## Configuration that matters at 70 users

| Setting | Guidance |
|---|---|
| `LABTUTOR_LLM_MAX_CONCURRENCY` | Per **process** (asyncio semaphore); 2 workers = 2x. With a large provider quota set high (e.g. 150). A request that cannot get a slot waits `LABTUTOR_LLM_QUEUE_TIMEOUT_SECONDS`, then falls back to the extractive answer. |
| `LABTUTOR_DB_POOL_SIZE` / `_MAX_OVERFLOW` | Per worker. Keep workers x (pool + overflow) below Postgres `max_connections` (100 default). |
| Chat rate limit | In-memory per process (`backend/ratelimit.py`), so the effective limit is up to workers x configured. Fine on one VM; needs Redis for multiple replicas. |
| Cloud Run / multi-instance | Not the default path: the limiter and LLM semaphore are per instance, and summary jobs are in-process tasks. If used: min instances 1, CPU always allocated, small DB pool. |

## Running a class session

A class session is tied to one experiment. Faculty pick the experiment when
starting the session; students in that classroom get that experiment only
(`POST /api/chat/*` returns 400 for any other `experiment_id`). Inside the chat
the tutor answers from the chosen experiment and redirects a question that
names, or is clearly about, a different one ("This session is for Experiment 2...").
For a class doing two experiments back to back (e.g. Exp 2 then Exp 4), end the
first session and start a new one for the second; each has its own threads.

Classes without apparatus (theory only) need no extra setup: `LABTUTOR_PHONE_ONLY`
defaults to true, so Exp 2, 4 and 7 run in theory mode. Set it to `false` only for a class
that has the equipment.

## Health checks

- `GET /health`: process and database. Does not call the model.
- `GET /health/llm`: inference connectivity, separate so a provider outage does not
  make the container look dead and get restarted.

## Remote database (optional)

Set `LABTUTOR_DATABASE_URL`; it overrides every `POSTGRES_*` value. For Supabase use
the direct connection (port 5432), not the pgbouncer pooler on 6543 (it does not
reliably support the prepared statements the async psycopg driver issues). Migrations
run on backend start; with several instances starting at once they can race.

## Load test before the session

```bash
python infra/loadtest.py --students 70 --turns 6      # --dry-run exercises the harness
```

Reports p50/p95/p99 and error rate; exits non-zero past its thresholds. Also check the
provider's RPM/TPM limits cover ~70 users x ~12 messages/minute. Run it against the
real backend and Postgres before the first session, not during it.

## Inference backends and rollback

`LABTUTOR_LLM_BACKEND` / `GPT` select the provider: OpenAI (`GPT=true`,
`OPENAI_API_KEY`), Vertex (Gemini), any OpenAI-compatible `hosted` endpoint, or
local `ollama` (development and degraded mode only; one machine will not serve a
section, so read p95 from `infra/loadtest.py` before considering it).

Catalyst degrades rather than failing: every model call phrases something already
decided, so an outage costs polish, never correctness. With no model reachable,
diagnoses, hints, step verification, the reveal and navigation are unaffected
(deterministic templates); only free-form Q&A degrades to extractive answers.

If the provider fails mid-session: (1) with `LABTUTOR_LLM_AUTO_FALLBACK=true` a failed
call retries against Ollama if reachable
(`docker compose --env-file .env -f infra/docker-compose.yml --profile ollama up -d`); (2) set
`LABTUTOR_LLM_BACKEND=ollama` and restart `backend`; (3) change nothing and let
template mode finish the lab; (4) if the backend itself is unhealthy, stop it and let
Caddy serve the error, and students fall back to the paper procedure.

## Poor student connectivity

Known weaknesses (verified by reading the code, not yet fixed):

- A dropped chat stream cancels the server turn (`backend/api/chat_routes.py`), so
  the tutor reply, and likely the student message, can be lost; the client then
  offers a resend.
- Chat sends are not idempotent, so a resend makes a second model call.
- Plain API requests have no timeout or retry; there is no offline mode.

Mitigations in place: the client reloads the thread after a late drop and shows a saved
reply if one exists (`ChatWorkspace.tsx`); stream idle timeout is 90 s. Until the fixes
land, advise students on a weak network to use mobile data and to wait for a reply
before resending. Planned fixes: finish and save the turn even if the client
disconnects, idempotent sends, retry/backoff and a "reconnecting" state, and no gzip on
`text/event-stream` in the Caddyfile.

## Backups

`pg_dump` nightly to a bucket or another host; containers restart automatically
(`restart: unless-stopped`). Summary jobs are in-process and lost on restart; re-running
is idempotent.
