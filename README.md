# KisanSaathi

Market intelligence and transaction platform connecting Maharashtra farmers and FPOs
with verified buyers. FastAPI + PostgreSQL behind nginx, React + TypeScript in front,
six roles, a full lot-to-cash workflow, and an AI assistant that is read-only by
construction.

**Status:** Days 1 and 2 complete and verified on SQLite and PostgreSQL. 78 backend
tests, 100 API contract checks, all eight demo accounts walked in a real browser.

| | |
| --- | --- |
| **Run it** | `make up` → http://localhost:8080 · `make dev` → http://localhost:5173 |
| **Check it** | `make verify` |
| **Deploy it** | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) |
| **Configure it** | [Configuration](#configuration) below, `.env.example` |
| **Read the code** | [`docs/DAY1.md`](docs/DAY1.md) backend · [`docs/DAY2.md`](docs/DAY2.md) frontend |
| **Reference** | [`docs/API.md`](docs/API.md) 129 operations · [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) 33 tables · [`docs/AI_BOUNDARY.md`](docs/AI_BOUNDARY.md) |
| **Progress** | [`docs/PROGRESS.md`](docs/PROGRESS.md), including what is not finished |

---

## Quick start

Needs Docker with Compose; nothing else to install. `make help` lists every target.

```bash
make up          # build both images, start Postgres, migrate, seed, wait, print the URL
make verify      # tests, lint, types, build, API contract, real-browser sweep
make logs        # follow the containers      make down  # stop, keep the database
```

`make up` writes `.env` with a generated `JWT_SECRET_KEY` and `POSTGRES_PASSWORD` if
it is not there, then serves the built frontend from nginx on one origin with `/api`
proxied to the backend. Postgres is never published. The demo accounts are listed on
the sign-in screen and all use `Demo@1234`.

For frontend work, or without Docker at all:

```bash
make dev         # uvicorn on :8000 and Vite on :5173 in one terminal, SQLite underneath
```

`make dev` installs dependencies, runs `alembic upgrade head` and the seeder (both
idempotent), then starts both processes; Ctrl-C stops both. By hand it is
`python3.13 -m venv ../.venv && pip install -r requirements-dev.txt` in `backend/`
(3.13 or lower: the pinned `psycopg-binary` has no 3.14 wheel) plus `npm install` and
`npm run dev` in `frontend/`.

## Commands

| Command | Does |
| --- | --- |
| `make up` | Build and run the whole stack, wait for `/ready`, print the URL |
| `make dev` | API and Vite locally on SQLite, one terminal |
| `make check` | 78 tests, `ruff check`, `ruff format --check`, typecheck, lint, build |
| `make verify` | `check`, then the API contract and the browser sweep |
| `make down` / `make reset` | Stop / stop and destroy the database, then rebuild and reseed |
| `make env` / `make secrets` | Create `.env` with generated secrets / list every credential in full |
| `make rotate-jwt` | New signing key, which signs everyone out |
| `make install` / `make build` / `make clean` | Dependencies / images only / build output and caches |
| `make logs` / `make ps` / `make psql` | Container logs (`SERVICE=backend`) / status / psql prompt |
| `make test` / `make contract` / `make ui` | Individual checks, e.g. `make ui PHONE=9000000005` |

Overridable: `APP_URL`, `READY_TIMEOUT`, `PYTHON`, `SERVICE`, `PHONE`.

## What it does

| Role | Workflows |
| --- | --- |
| Farmer | Create and publish lots, accept offers, schedule pickup, confirm delivery, raise grievances |
| FPO | As farmer, plus organisation profile and aggregate member view |
| Buyer | Post demands, make offers, verification status, payments due, disputes |
| Logistics partner | Assigned shipments, pickup and delivery status |
| Quality inspector | Inspections, per-commodity parameter definitions, grade suggestions |
| Admin | Users and roles, buyer verification, catalogue and market upkeep, grievance resolution, audit log |

All under `/api/v1`: auth and RBAC, catalogue, market prices and arrivals, lots,
demands, matching, offers, orders, logistics, storage, quality, payments,
grievances, notifications, dashboards, AI.

## Architecture

```
backend/app/   api/v1 18 routers · core config/RBAC/errors · db session, models, seeder
               repositories SQL · schemas Pydantic · services rules · integrations providers
backend/alembic  33 tables, one initial migration
frontend/src/  lib api client, types, i18n dictionaries · auth session + role routes
               components shared UI · hooks useAsync, permission-aware nav · pages one per screen
scripts/       verify_api.mjs contract · browser_check.mjs, browser_sweep.mjs real Chrome
               gen_config_table.py, write_secrets_doc.py docs and secrets
```

Layering: routers parse and authorise, services hold the rules, repositories own the
SQL. 134 registered routes, of which 129 are documented operations across 109 paths
(`GET /` and the health and docs routes are deliberately hidden).

**Frontend.** React 19, Vite, TypeScript strict, Tailwind 4, React Router 7. No
component library and no state container: a typed `fetch` wrapper, one session
context, and a `useAsync` hook for server state. 120 kB of JavaScript gzipped, 6 kB
of CSS, three runtime dependencies (`react`, `react-dom`, `react-router-dom`).
Navigation is derived from the permission strings the backend already sends in
`/auth/me`, so changing `app/core/rbac.py` changes the UI with no frontend edit.
English and Marathi live in one typed dictionary, so a missing translation is a
compile error.

**API conventions.** Prefix `/api/v1`. Success responses are bare objects, not
envelopes. Lists return `{items, meta: {total_items, ...}}` — paginate on
`total_items`, not `items.length`. Errors return
`{"success": false, "error": {"code", "message"}, "request_id"}`, and the same
`request_id` is in the `X-Request-ID` header and the logs. Auth is
`Authorization: Bearer <access_token>`.

## Configuration

Environment driven, and real environment variables always win. Dotenv files are read
from the paths in `app/core/config.py` (`.env`, then `../.env`) relative to the
working directory, and the later file wins: with the API started from `backend/`, as
the Makefile does, the repo-root `.env` overrides `backend/.env`. `make env` creates
that root `.env` from `.env.example` with generated secrets. Two values are
mandatory: `JWT_SECRET_KEY` (the API raises without it in `staging` and `production`;
compose fails too) and `POSTGRES_PASSWORD` (compose fails without it).

The database URL the API resolves, per mode:

```
local dev    sqlite+pysqlite:///./kisansaathi_dev.db
compose      postgresql+psycopg://kisan:<password>@db:5432/kisansaathi
managed      postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
```

Every variable, with its default read from `app/core/config.py`:

<!-- config-table:begin -->

**App**

| Variable | Default | Notes |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development`, `test`, `staging` or `production`. Only `production` enforces the startup checks. |
| `LOG_LEVEL` | `INFO` | Standard Python levels. |
| `LOG_JSON` | `true` | One JSON object per line, for a log shipper. Off reads better locally. |
| `DEBUG` | `true` | FastAPI debug returns tracebacks. Keep false anywhere public. |

**Database**

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `unset` | Overrides the `POSTGRES_*` parts. `postgres://` is rewritten to psycopg. |
| `POSTGRES_USER` | `kisan` | Role the API authenticates as. |
| `POSTGRES_PASSWORD` | `kisan` | **Secret.** Required by compose. Changing it here does not change an existing volume: see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). |
| `POSTGRES_DB` | `kisansaathi` | Database name. |
| `POSTGRES_HOST` | `localhost` | `db` in Compose, `localhost` locally. |
| `POSTGRES_PORT` | `5432` | Postgres port. |
| `SQLITE_PATH` | `./kisansaathi_dev.db` | Only used on the SQLite path, i.e. outside Docker in development. |
| `DB_POOL_SIZE` | `10` | Postgres only; SQLite ignores the pool. |
| `DB_MAX_OVERFLOW` | `20` | Extra connections above the pool size. |
| `DB_POOL_TIMEOUT` | `30` | Seconds to wait for a connection before failing. |
| `DB_ECHO` | `false` | Logs every statement and its parameters. Never on in production. |

**Security and tokens**

| Variable | Default | Notes |
| --- | --- | --- |
| `JWT_SECRET_KEY` | `unset` | **Secret, required in production.** Signs every token. `make rotate-jwt`. |
| `JWT_ALGORITHM` | `HS256` | Symmetric: anyone holding the key can mint tokens. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Eight hours, so a field user is not forced to sign in daily. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `14` | Refresh tokens rotate; replaying a rotated token revokes the chain. |
| `PASSWORD_MIN_LENGTH` | `8` | Enforced at registration. Raise it for a real deployment. |
| `PBKDF2_ITERATIONS` | `390000` | Password hash cost. Higher is slower to attack and slower to log in. |

**CORS**

| Variable | Default | Notes |
| --- | --- | --- |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated. Not consulted in the Compose stack, which is one origin. |
| `CORS_ALLOW_CREDENTIALS` | `true` | Never pair with `*`. |

**Cache and rate limiting**

| Variable | Default | Notes |
| --- | --- | --- |
| `REDIS_URL` | `unset` | **Secret** if it carries a password. Unused: no code reads it yet. Declared for a limiter that is not implemented. |
| `CACHE_TTL_SECONDS` | `120` | Unused: no code reads it, and there is no response cache. |
| `RATE_LIMIT_ENABLED` | `false` | **Unused: there is no rate limiter in the code.** Compose sets it to `true` and nothing acts on it. Limit at the proxy instead: see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). |
| `RATE_LIMIT_REQUESTS` | `240` | Unused, same as `RATE_LIMIT_ENABLED`. |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Unused, same as `RATE_LIMIT_ENABLED`. |

**AI assistant**

| Variable | Default | Notes |
| --- | --- | --- |
| `AI_PROVIDER` | `nvidia` | Provider name; the adapter is in `app/integrations/`. |
| `NVIDIA_API_KEY` | `unset` | **Secret.** Empty is not an error: the assistant falls back to the deterministic rules engine. |
| `NVIDIA_BASE_URL` | `https://integrate.api.nvidia.com/v1` | NVIDIA NIM endpoint. |
| `NVIDIA_MODEL` | `meta/llama-3.3-70b-instruct` | Chat model. |
| `NVIDIA_EMBEDDING_MODEL` | `nvidia/nv-embedqa-e5-v5` | Unused: the assistant has no embedding or retrieval path. It reads the database, not a vector store. |
| `NVIDIA_TIMEOUT_SECONDS` | `45.0` | Per-request timeout. |
| `NVIDIA_MAX_RETRIES` | `2` | Retries before the rules engine answers instead. |
| `AI_ASSISTANT_ENABLED` | `true` | Needs `NVIDIA_API_KEY` too, and gates the model client: `false` pins every answer to the rules engine. It does not remove the route, so `/ai/chat` still answers. |
| `AI_TEMPERATURE` | `0.25` | Low on purpose. The assistant explains, it does not negotiate. |
| `AI_MAX_TOKENS` | `900` | Answer cap. See [`docs/AI_BOUNDARY.md`](docs/AI_BOUNDARY.md). |

**Integrations**

| Variable | Default | Notes |
| --- | --- | --- |
| `MARKET_DATA_PROVIDER` | `demo` | `demo` is the seeded synthetic dataset. |
| `MARKET_DATA_BASE_URL` | `unset` | Required by a real provider. |
| `MARKET_DATA_API_KEY` | `unset` | **Secret.** Unused while the provider is `demo`. |
| `LOGISTICS_PROVIDER` | `demo` | Unused: quotes always come from the in-process `DemoLogisticsProvider`. Pass a provider to `LogisticsService` to change that. |
| `LOGISTICS_BASE_URL` | `unset` | Unused, same as `LOGISTICS_PROVIDER`. |
| `LOGISTICS_API_KEY` | `unset` | **Secret.** Unused, same as `LOGISTICS_PROVIDER`. |
| `NOTIFICATION_PROVIDER` | `database` | Unused: notifications are always written to the database and read back through the API. |

**Media**

| Variable | Default | Notes |
| --- | --- | --- |
| `MEDIA_ROOT` | `./media` | Unused: there is no upload endpoint. Grievance evidence is external URLs. Declared for a future media store, so no volume is needed today. |
| `MAX_UPLOAD_BYTES` | `5242880` | Unused, same as `MEDIA_ROOT`. |
| `ALLOWED_IMAGE_TYPES` | `image/jpeg,image/png,image/webp` | Unused, same as `MEDIA_ROOT`. `settings.allowed_image_types` parses it, but no code calls that property. |

**Demo and seeding**

| Variable | Default | Notes |
| --- | --- | --- |
| `DEMO_MODE` | `true` | Seeds 8 demo accounts, 120 days of synthetic prices and a sample order, and shows the demo banner. `false` loads only reference data. |

**API surface**

| Variable | Default | Notes |
| --- | --- | --- |
| `DOCS_ENABLED` | `true` | `false` hides `/api/docs` and `/api/redoc`. Already false in Compose. |

**Compose and build time**

| Variable | Default | Notes |
| --- | --- | --- |
| `FRONTEND_PORT` | `unset` | Host port for nginx. |
| `VITE_SHOW_DEMO_ACCOUNTS` | `unset` | Lists the demo accounts on the sign-in screen. Unset means on in dev, and `DEMO_MODE` in Compose. `false` compiles them out of the bundle. |
| `VITE_API_BASE_URL` | `unset` | **Read by nothing today**: the client is hardcoded to the same origin, `/api/v1`. |
| `VITE_BACKEND_ORIGIN` | `unset` | Dev-server proxy target only. Ignored in a production build. |
<!-- config-table:end -->

### Credentials and secrets

Secrets are `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `NVIDIA_API_KEY`,
`MARKET_DATA_API_KEY`, `LOGISTICS_API_KEY` and `REDIS_URL`. The demo password
`Demo@1234` is public by design: the sign-in screen prints it when
`VITE_SHOW_DEMO_ACCOUNTS` is on.

| Secret | Generate | Rotate |
| --- | --- | --- |
| `JWT_SECRET_KEY` | `openssl rand -hex 32` | `make rotate-jwt && make up`. Invalidates every session. |
| `POSTGRES_PASSWORD` | `openssl rand -base64 18` | Edit `.env` **and** `ALTER ROLE kisan WITH PASSWORD '...';`. Editing `.env` alone changes nothing in an existing volume. |
| `NVIDIA_API_KEY` | console.nvidia.com | Issue, set, `make up` |
| `REDIS_URL` | provider | Rotate in Redis, update `.env`, `make up` |

To see the values currently in effect, in full: `make secrets` writes
`SECRETS.local.md`, which is git-ignored, and prints them redacted. The README holds
no live values on purpose, because it is a tracked file.

## Deployment

Three services, all non-root, all healthchecked, one published port.

| Service | Image | Runs as | Port | Published |
| --- | --- | --- | --- | --- |
| `db` | `postgres:16-alpine` | uid 70 | 5432 | no |
| `backend` | `backend/Dockerfile` | uid 10001 | 8000 | no |
| `frontend` | `frontend/Dockerfile`, `nginx-unprivileged` | uid 101 | 8080 | `${FRONTEND_PORT:-8080}` |

The backend command applies migrations and seeds before serving, so a fresh volume
comes up with a working schema. nginx serves the SPA, falls back to `index.html` for
client-side routes, proxies `/api`, `/health` and `/ready`, caches hashed assets
immutably and `index.html` not at all, and the config is checked with `nginx -t`
during the image build. Compose gates the frontend on the backend's `/ready`, so
nginx never starts in front of a dead API.

Before it goes anywhere public — the full runbook is
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md):

- [ ] `DEMO_MODE=false`, `SEED_ON_START=false`, then `python -m app.db.seed --no-demo`
- [ ] `VITE_SHOW_DEMO_ACCOUNTS=false` **and rebuild**; it is baked in at build time
- [ ] `DOCS_ENABLED=false`, `DEBUG=false`, `DB_ECHO=false`
- [ ] `CORS_ORIGINS` set to the real origin, nothing else
- [ ] A rate limiter in front of the stack. There is none in the application:
      `RATE_LIMIT_ENABLED` and `REDIS_URL` are declared and set by compose, but no
      code reads them. Rate-limit `POST /api/v1/auth/login` hardest
- [ ] Nothing to do about media: there is no upload endpoint, so no volume to back up
- [ ] TLS terminated in front; only the frontend port reachable from outside
- [ ] Fresh `JWT_SECRET_KEY` and `POSTGRES_PASSWORD` from a secret store
- [ ] A database backup taken, and the restore rehearsed

### The first administrator

`POST /api/v1/auth/register` accepts only `FARMER`, `FPO` and `BUYER`. The three staff
roles come into existence only through `POST /api/v1/users`, which needs an admin's
token, and the web UI has no screen for it. With `DEMO_MODE=false` the seeder writes
roles and reference data and **no accounts**, so nothing can call that endpoint. The
first admin is promoted in a shell:

```bash
# 1. The account self-registers over the API.
curl -X POST http://localhost:8080/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"full_name":"Ops Admin","phone":"9000000009","password":"<strong-password>",
       "role":"FARMER","district":"Pune"}'

# 2. Promote it. primary_role_id is a foreign key into roles; there is no role column.
docker compose exec db psql -U kisan -d kisansaathi -c \
  "UPDATE users SET primary_role_id = (SELECT id FROM roles WHERE name = 'ADMIN')
   WHERE phone = '9000000009';"
```

After that `POST /api/v1/users` creates the other staff accounts. The alternative,
which never touches the database, is to deploy once with `DEMO_MODE=true`, sign in as
the seeded `9000000001`, and promote through the API.

## Testing

```bash
make check      # 78 tests, ruff check + format, typecheck, oxlint, production build
make verify     # the above, plus 100 API contract checks and a browser sweep
```

78 backend tests cover the service and permission layer for every domain, HTTP
integration through `TestClient`, seeder idempotency, and a regression per bug found
along the way. `verify_api.mjs` signs in as all eight demo accounts and calls every
endpoint a screen uses; its two 403s are asserted, not tolerated, because storage
options are seller-only. The two browser scripts drive the installed Chrome over the
DevTools Protocol with no new dependency: they sign in, walk every route the account
can reach, and fail on an uncaught exception or a console error. That is the check
that catches a blank page, which typecheck, lint, the build and the contract check all
passed while one existed. No frontend unit-test runner yet; all known limits, in
[`docs/PROGRESS.md`](docs/PROGRESS.md).

## What this is not

- **The assistant cannot transact.** It reads the platform and explains the answer,
  and with no `NVIDIA_API_KEY` it answers from a deterministic rules engine, so a
  provider outage changes nothing a user sees. [`docs/AI_BOUNDARY.md`](docs/AI_BOUNDARY.md)
- **Payments are a ledger, not a gateway.** It records what is owed and settled.
- **Money is `FLOAT`.** It cannot represent 0.10 exactly: fine for a demo, wrong for
  settlement. The fix is `NUMERIC(14, 2)`, in [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md).
- **Demo prices are synthetic** and labelled as such on every screen that shows one.
- **There are no file uploads.** Grievance evidence is an external URL, `MEDIA_ROOT`
  and `MAX_UPLOAD_BYTES` are read by no code, and the `media` volume compose
  declares stays empty. The backend is stateless, so it scales horizontally as it
  stands.
- **Nothing is rate limited.** `RATE_LIMIT_*` and `REDIS_URL` are declared in
  `config.py` and set by compose, but no code reads them and nginx has no
  `limit_req`. A public deployment needs a limiter at the edge; the runbook says
  where to put it.
