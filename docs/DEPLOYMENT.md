# Deployment runbook

Everything needed to put KisanSaathi somewhere real, in the order it has to
happen. Written against the compose stack in this repository: Postgres, the
FastAPI backend and nginx serving the built frontend on one origin.

Related: [`../README.md`](../README.md) for the configuration reference,
[`DATA_MODEL.md`](DATA_MODEL.md) for the schema, [`PROGRESS.md`](PROGRESS.md) for
what is and is not finished.

---

## 1. What you are deploying

| Service | Image | Runs as | Port | Published |
| --- | --- | --- | --- | --- |
| `db` | `postgres:16-alpine` | uid 70 (`postgres`) | 5432 | no, `expose` only |
| `backend` | built from `backend/Dockerfile` | uid 10001 | 8000 | no, `expose` only |
| `frontend` | built from `frontend/Dockerfile` | uid 101, `nginx-unprivileged` | 8080 | `${FRONTEND_PORT:-8080}` |

The browser only ever talks to the frontend. nginx serves the SPA, falls back to
`index.html` for client-side routes, and proxies `/api`, `/health` and `/ready`
to the backend, so the API is never directly reachable and CORS is not consulted
in production. Postgres is not published at all. Nothing in the stack runs as
root, and both built images carry a `HEALTHCHECK`.

## 2. Pre-flight

The stack refuses to start without `JWT_SECRET_KEY` and `POSTGRES_PASSWORD`, and
in production the API raises on startup if the signing key is missing. That is the
floor, not the checklist.

- [ ] `DEMO_MODE=false` — no demo accounts, no synthetic prices, no demo banner.
- [ ] `SEED_ON_START=false` — nothing seeded at start. Reference data (roles,
      commodities, markets, quality parameters) must be loaded deliberately with
      `docker compose exec backend python -m app.db.seed --no-demo`.
- [ ] `VITE_SHOW_DEMO_ACCOUNTS=false` — compiled out of the bundle, so the
      working demo credentials are not in the shipped JavaScript at all. It is a
      build-time value: set it before `make up`, and rebuild to change it.
- [ ] `DOCS_ENABLED=false` — `/api/docs` and `/api/redoc` are not public. Already
      the compose default.
- [ ] `CORS_ORIGINS` — your real origin only. Never `*` with credentials enabled.
- [ ] A rate limiter in front of the stack. There is no limiter in the application:
      `RATE_LIMIT_ENABLED` and `REDIS_URL` are declared in `config.py` and set by
      compose, but no code reads them, so they limit nothing. Until that is
      implemented, put `limit_req` in the proxy, or a managed WAF in front of it, and
      rate-limit `POST /api/v1/auth/login` hardest, which is where credential
      stuffing lands. An in-memory limiter is not a limit once you run two replicas.
- [ ] `JWT_SECRET_KEY` and `POSTGRES_PASSWORD` freshly generated, in your secret
      store, not in the repository. `make env` generates them for local use.
- [ ] Nothing to do about media. There is no upload endpoint: grievance evidence is
      an external URL, `MEDIA_ROOT` is read by no code, and the `media` volume
      compose declares stays empty. The checklist item that used to ask for a
      writable, backed-up media directory was wrong.
- [ ] `PASSWORD_MIN_LENGTH` raised if your users can manage it (default 8).
- [ ] `DEBUG` and `DB_ECHO` both false.
- [ ] TLS terminating in front of the stack, HTTP to the origin on a private
      network only.
- [ ] A database backup taken, and the restore rehearsed before you need it.
- [ ] `make verify` green against a staging copy of the real configuration.

## 3. First deploy

```bash
git clone <repo> && cd kisansaathi
make env                     # writes .env with generated secrets
$EDITOR .env                 # apply the pre-flight list above
make up                      # build, start, wait for /ready, print the URL
```

`make up` builds both images, starts the three services, and polls
`http://localhost:8080/ready` until the API answers, failing after
`READY_TIMEOUT` seconds (300 by default) with the container status and the last
40 lines of the backend log. A cold start seeds nothing when
`SEED_ON_START=false`, so it is quick.

Then load reference data once:

```bash
docker compose exec backend python -m app.db.seed --no-demo
```

Create the first administrator by hand. `--no-demo` seeds roles and reference data
and **no accounts** (`accounts_created: 0`), and `POST /api/v1/auth/register` only
accepts `FARMER`, `FPO` and `BUYER`: `SELF_SERVICE_ROLES` in `app/schemas/user.py`
rejects the other three with a 422, and a test asserts it. Staff accounts can only be
created by an existing admin through `POST /api/v1/users`, which has no web screen, so
with no accounts there is nobody who can call it. Promote one in a shell:

```bash
# 1. Self-register over the API as a role that is allowed to.
curl -X POST http://localhost:8080/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"full_name":"Ops Admin","phone":"9000000009","password":"<strong-password>",
       "role":"FARMER","district":"Pune"}'

# 2. Promote it. The role lives in roles.name; users holds primary_role_id.
docker compose exec db psql -U kisan -d kisansaathi -c \
  "UPDATE users SET primary_role_id = (SELECT id FROM roles WHERE name = 'ADMIN')
   WHERE phone = '9000000009';"
```

Then `POST /api/v1/users` with that admin's token creates the remaining staff
accounts. The alternative is to deploy once with `DEMO_MODE=true`, sign in as the
seeded `9000000001` and promote through the API, then redeploy with it off — the demo
mode is the only bootstrap path that never touches the database directly.

Check the deployment before pointing anyone at it:

```bash
curl -fsS https://your-host/health
# {"status":"ok","service":"KisanSaathi","version":"1.0.0","environment":"production",
#  "database":"up","demo_mode":false}

curl -fsS https://your-host/ready
# {"ready":true,"database":"up"}

curl -fsSI https://your-host/ | head -20    # 200 plus the security headers
```

`/health` is liveness and answers even when a dependency is unhappy, which is what
makes it usable as a container health check. `/ready` checks the database, so alert
on that one. Both are proxied through nginx on the same origin, so neither needs
publishing the API.

## 4. Migrations and schema changes

The backend command runs `alembic upgrade head` before serving, so a new image
migrates itself on start. That is convenient and it is also a hazard: a migration
that takes a lock will hold up the health check, and `make up` will time out.

- Every schema change ships as a migration in `backend/alembic/versions/`.
- `alembic check` fails if a model has no migration. `make check` does not run
  it, so put it in CI: `cd backend && ../.venv/bin/alembic check`.
- Test a migration against a copy of production data before shipping it.
- `alembic downgrade base` drops everything. Local only.

## 5. TLS and the edge

The stack speaks plain HTTP and expects a proxy in front of it.

- Terminate TLS at a load balancer, ingress, or Caddy/ nginx on the host, and
  forward to `${FRONTEND_PORT}`.
- Redirect HTTP to HTTPS, and send `X-Forwarded-Proto`. The app does not need it
  today, but the assistant and any future absolute-URL link will.
- Add `Strict-Transport-Security` at the proxy. It is not set in
  `security-headers.conf` because an HSTS header served over plain HTTP is
  ignored, and a wrong `max-age` is hard to undo.
- Keep Postgres and the API unpublished. Only the frontend port should be
  reachable from outside.
- A WebSocket or SSE endpoint would need an `Upgrade` block in
  `frontend/nginx.conf`; none is used today.

## 6. Backups

One thing holds state: the `pgdata` volume. The `media` volume is declared and
mounted, but nothing writes to it, because there is no upload endpoint.

```bash
# Logical backup, the one to keep
docker compose exec -T db pg_dump -U kisan -d kisansaathi -Fc > kisansaathi-$(date +%F).dump

# Restore into an empty database
docker compose exec -T db pg_dropdb -U kisan --if-exists kisansaathi
docker compose exec -T db createdb -U kisan kisansaathi
docker compose exec -T db pg_restore -U kisan -d kisansaathi --clean --if-exists < kisansaathi-2026-01-01.dump
```

Back up `pgdata` with a volume snapshot if you prefer, but a `pg_dump` is
portable between hosts and Postgres versions. Test a restore, not just the backup.
If an upload endpoint is added later, media becomes user content that lives
outside the database, and this section needs a volume copy alongside the dump.

## 7. Upgrades and rollback

```bash
git pull && make up        # rebuild, migrate, restart
make verify                # the full gate against the running stack
```

Rollback is `git checkout <previous-tag> && make up`. The catch is schema: if the
new release migrated forward, rolling the image back leaves the new code against
the new schema. Roll the database back too, or deploy a migration that is
backward compatible. Write migrations that way in advance.

## 8. Rotating secrets

| Secret | Effect of rotation | How |
| --- | --- | --- |
| `JWT_SECRET_KEY` | Every session dies; everyone signs in again | `make rotate-jwt`, then `make up` |
| `POSTGRES_PASSWORD` | None until the new value is used | Edit `.env`, then `ALTER ROLE kisan WITH PASSWORD '...';`, then `make up`. Editing `.env` alone changes nothing inside an existing volume. |
| `NVIDIA_API_KEY` | Assistant falls back to the rules engine until the new key lands | Issue, set, `make up` |
| `REDIS_URL` | Nothing: no code reads it | Unused today. Kept in the rotation list so it is not set and forgotten. |

`make secrets` writes every current credential, in full, to `SECRETS.local.md`,
which is git-ignored. It is the fastest way to answer "what is this deployment
actually using", and `python3 scripts/write_secrets_doc.py --check` fails when
that file has drifted from `.env`.

## 9. Monitoring

- `/health` is liveness, `/ready` is readiness, and both are proxied through
  nginx. `/ready` also checks the database, so it is the one to alert on.
- Logs are JSON, one object per line, with `event`, `level` and `logger`. Ship
  them; do not tail a container in production.
- Watch for: 5xx rate, p95 latency on `/api/v1/markets/overview`, and error rate on
  `/api/v1/auth/login`, which is where credential stuffing lands. If a limiter is
  running in the proxy, alert on rejects as well, and raise its ceiling before your
  users feel it.

## 10. Scaling

- The backend is stateless: no session store, no local files. Scale it with
  replicas behind the proxy, and give every replica the same `JWT_SECRET_KEY` or
  tokens will fail to verify between them.
- Rate limiting is a proxy concern, and only because the app has none. Whatever you
  put in front has to be configured per proxy, not per worker.
- Nothing writes to the filesystem yet, so replicas are interchangeable as they
  stand. This becomes the first scaling constraint the moment an upload endpoint
  lands: local media is not shared, so it needs a single replica, a shared volume
  or object storage. It is the first thing
  that will bite at two replicas.
- The frontend is a static bundle behind nginx. It scales by adding containers and
  a load balancer, or by moving to a CDN.

## 11. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `make up` times out with backend logs | Migration failed, or seeding is still running | Read the last 40 lines it printed. A cold seed of 120 days of prices is the slow path. |
| Frontend restarts in a loop | nginx config rejected | The image build runs `nginx -t`, so this is usually a mounted config: `docker compose exec frontend nginx -t` |
| 502 from `/api` | Backend not ready | `docker compose ps`, then `make logs SERVICE=backend` |
| Signed in, then signed out | `JWT_SECRET_KEY` differs between replicas, or was rotated | One value everywhere, from the secret store |
| Login returns 401 for a known demo account | `DEMO_MODE=false`, so it was never seeded | Expected. Load reference data with `--no-demo`. |
| CORS error in the browser | `CORS_ORIGINS` missing the origin | The stack is one origin, so this means something is calling the API cross-origin |
| Assistant answers in rules-engine mode | `NVIDIA_API_KEY` unset, so `ai_enabled` is false | Expected, and the app is fully usable. Set the key and `make up`. `docker compose exec backend printenv NVIDIA_API_KEY` to see what the container got. |
