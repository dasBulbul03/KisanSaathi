# Progress log

Update this file at the end of every working session. The README links here, so
this is the single place to look to answer "where are we?".

## Day 1 — 28 September 2026

### Delivered

**Backend API, complete and tested**

- 18 routers aggregated in `app/api/v1/__init__.py`, 134 routes, 109 OpenAPI
  paths. Auth, users and admin, markets, lots, demands, matching, offers, orders,
  logistics, storage, quality, payments, grievances, notifications, AI and
  dashboards.
- `app/main.py`: lifespan, CORS, request IDs, structured logging, a single error
  envelope, OpenAPI metadata, `/health`, `/ready` and `/`.
- Permission matrix in `app/core/rbac.py` is the single source of truth for what
  each of the six roles may do. It is enforced in the services, not just the
  routers.
- Layering: routers parse and authorise, services hold rules, repositories own
  SQL. 85 Python modules under `app/`.

**Migrations**

- Alembic configured and verified. The initial migration creates 33 tables.
- `alembic check` reports no pending operations. `alembic downgrade base` removes
  every application table.

**Data**

- `app/db/seed_data.py` holds the catalogue as reviewable data: 10 commodities,
  9 markets across 5 market types, and 26 quality parameters.
- `app/db/seed.py` seeds roles, catalogue, 8 demo accounts, 120 days of market
  prices and arrivals, two godowns, a published lot per farmer, an open demand per
  buyer, and one full trade path (lot → demand → accepted offer → order → scheduled
  pickup).
- The seeder is idempotent and is the supported way to ship reference-data
  changes. `--no-demo` gives reference data only, `--reset` rebuilds (and refuses
  to touch production).

**Tests**

- 74 passing: service and permission tests, HTTP integration tests through
  `TestClient`, and seeder tests.

**Docs**

- `README.md`: quick start, demo accounts, architecture, conventions, commands,
  configuration and the project's boundaries.

### Bugs found and fixed today

Mostly found by writing the tests and the seeder, not by reading the code.

- `quality_attributes.commodity_id` was `NULL` on insert: the seeder built a batch
  of attributes before the parent commodities were flushed.
- Quality grading was inverted for lower-is-better parameters. `grade_a_min` and
  `grade_b_min` are "at or above" thresholds, so seeding them for rot percentage
  and moisture would have graded the worst onions as Grade A. The seed data is now
  direction-aware and a test enforces it.
- `QualityService._band` returned `"C"` for any parameter with no grade
  thresholds, inventing a bad grade for rot and moisture. It now returns `None`.
- `MarketService.create_sync_log` built the log object but never added it to the
  session, so **every** market sync log was silently discarded and callers got
  `sync_log_id: None`.
- The dashboards reported `is_demo_data: false` on a fully seeded demo database.
  The flag was computed from the commodity count, so it meant "the catalogue is
  empty" and inverted the answer. It now reads the stored `market_prices.source`
  and only reports synthetic prices when every recorded row came from the demo
  provider. The market endpoints already did this correctly; the dashboards were
  the odd ones out.
- The demo trade landed on the wrong farmer. Accounts were keyed by role, so the
  second farmer overwrote the first and the lot belonged to the account the README
  lists second. Now keyed by phone, and the first account per role owns the trade.
- The FPO dashboard returned 500 on a fully seeded database. With no lots,
  `_price_cards` fell back to the cross-commodity overview, which names its fields
  `commodity` and `median_modal_price`, while the insight builder read
  `commodity_name` and `modal_price`. The fallback is now reshaped to the same
  card contract. Found by signing in as the FPO against a live server; the unit
  tests had only ever used sellers who owned lots.
- `/dashboards/me` returned 422 for quality inspectors and logistics partners,
  because those roles fell through to the seller dashboard and then failed
  response validation. It now returns `403 NO_DASHBOARD_FOR_ROLE`, which is an
  answer a client can act on.
- `/payments/due-soon` was not scoped to the current user.
- Order search and pipeline counts ignored the viewer's role, showing buyers and
  staff each other's orders.
- Matching silently treated an unsupported role as a buyer.
- Private storage was listed to its own owner and to seller options without a
  viewer id, so private godowns leaked into public search.
- Market sync dropped the market half of the `(PriceRecord, Market)` pair from
  the demo provider, so every price was written without a market.
- Admin commodity and market lists could not show retired rows.
- SQLAlchemy eager-loaded a non-existent `Transaction.commodity`, and
  `PaymentService.enrich` read `payment.order` instead of the transaction's order.
- Order detail endpoints did not check that the caller was a party to the order.
- SQLite needed `check_same_thread=False` for the threaded ASGI test client.
- Ruff was configured in `pytest.ini`, where it never ran. Moved to
  `backend/ruff.toml`; the whole tree is now linted and formatted.

### Decisions taken

- **Roles in code, not in the database.** The permission matrix lives in
  `app/core/rbac.py`; the seeder copies it into the `roles` table. One edit, not
  two, and a fresh database cannot disagree with the running code.
- **Prices go through the real sync service.** The seeder does not insert price
  rows directly, so the demo data is produced by the same code path the app uses
  and the provider's pairing rules stay honest.
- **Demo orders stop mid-pipeline.** A seeded order sits at pickup-scheduled with
  a next step, not at creation, so the demo has somewhere to go.
- **Every demo account gets data.** Both farmers have a published lot and both
  buyers an open demand, so signing in as any of them shows a working screen
  rather than an empty state. The seeder prints what each account carries.
- **Buyers are seeded unverified**, leaving the admin verify-buyer flow
  demonstrable.
- **The UI will be bilingual (English + Marathi) with a language toggle.**
  Confirmed today.
- **The frontend stack is not decided yet.** Open question for Day 2. Node 26 and
  npm 11 are available.

### Carried into Day 2

1. **Frontend.** Empty directory. Needs: stack decision, scaffold, login and
   token refresh, role-aware navigation, and a dashboard per role. Bilingual with
   a toggle. Suggested starting point is React + Vite + TypeScript + Tailwind, but
   this was not confirmed.
2. **Deployment.** No Dockerfile, compose file, `.env.example` or `.gitignore`.
   The README already documents the settings they will need to cover.
3. **Remaining docs.** `README.md`, `docs/PROGRESS.md` and `docs/DAY1.md` are
   written. Still missing: an API reference beyond the generated `/docs`, a data
   model document, and an AI-boundary note. The README summarises the boundaries;
   they need their own document.
4. **No git repository.** `git init` has not been run. Worth doing before Day 2
   work so changes are recoverable.
5. **Postgres not exercised.** Everything so far is verified on SQLite. The
   psycopg driver is installed but no run against a real PostgreSQL instance has
   happened.

### Verified by hand, not only by tests

The live walkthrough on Day 1 signed in as all eight demo accounts and called the
dashboard endpoint for each. That is what caught the FPO 500 and the 422, neither
of which the test suite could see. Do the same before calling a day finished.

### Things a future session should not break

- Read `meta.total_items` for pagination, not `items.length`.
- Keep successful responses unwrapped; only errors use the envelope.
- Keep the seeder idempotent. If a step cannot be made repeatable, say so
  explicitly rather than leaving a duplicate-on-rerun path.
- Grade thresholds are "at or above". Do not set them on a lower-is-better
  parameter.
- One `BlockingPortal` deprecation warning from Starlette's `TestClient` is known
  and harmless; do not chase it.
- The card dictionaries returned by `_price_cards` have one shape. Anything that
  feeds it a differently-named dict will 500 the seller dashboard.

---

## Day 2 — 29 September 2026

Every item carried into Day 2 is now closed. The detail is in
[`DAY2.md`](DAY2.md); this is the log.

### Delivered

**Frontend, complete and integrated**

- Stack decided and built: React 19, Vite 8, TypeScript 6 strict, Tailwind CSS 4,
  React Router 7. Four runtime dependencies, ~123 kB gzipped, no component
  library and no state container.
- 21 page modules covering 23 screens, each routed behind a role guard, with
  English and Marathi in one typed dictionary and a language toggle.
- Navigation derives from the permission strings `/auth/me` already returns, so
  `app/core/rbac.py` is still the only place a role's abilities are written down.
- The API layer is a typed fetch wrapper with single-flight token refresh: six
  parallel dashboard requests share one refresh instead of rotating the token six
  times and locking the user out.
- Signed in as all eight demo accounts and walked every screen, which is how most
  of the bugs below were found.

**Deployment**

- `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`,
  `docker-compose.yml`, `.env.example` and `.gitignore`.
- Three services: Postgres 16, the FastAPI app, and nginx serving the built SPA
  and proxying `/api` to the same origin. Migrations and seeding run in the
  backend entrypoint, so a fresh volume comes up working.
- Both containers run as non-root: uid 10001 for the API, uid 101 for nginx.
  nginx therefore listens on 8080 inside the container and compose maps
  `${FRONTEND_PORT:-8080}` to it.
- PostgreSQL is now genuinely exercised, not merely installed: migrated, seeded,
  and the full API contract check run against it. That closes item 5 from Day 1.

**Documentation**

- `docs/API.md` regenerated from the running OpenAPI document: 129 operations
  across 109 paths, grouped by area, with the error codes and which routes are
  public.
- `docs/DATA_MODEL.md` written from the SQLAlchemy metadata: 33 tables, the
  conventions, the five uniqueness constraints that carry business meaning, and
  the CASCADE / SET NULL / RESTRICT rule.
- `docs/AI_BOUNDARY.md` written: what the assistant reads, that it cannot write,
  and that with no `NVIDIA_API_KEY` it answers from a deterministic engine so a
  provider outage changes nothing.
- `README.md` and `docs/DAY2.md` brought in line with the above.

**Repository**

- `git init` on `main`; `.gitignore` covers secrets, SQLite files, media,
  dependencies and build output. Nothing is committed yet.

### Bugs found and fixed today

Frontend:

- **Sign-in was broken for everyone.** The client posted `{phone, password}`; the
  field is `identifier`.
- **The price snapshot is an object, not a list.** Two screens called `.map` on
  it and would have thrown on every market view.
- **Trend points use `date` and comparison rows use `change_pct_7d`,** not
  `price_date` and `rank` as the types claimed.
- **Match endpoints return a bare array,** not the `{summary, results}` envelope
  the client expected, so match tables rendered empty.
- **Storage options were shown to roles that get 403.** Nav and route are now
  seller-only, matching the API's own scoping.
- **Role dropdowns held React elements cast to strings,** which renders as
  `[object Object]`.
- **The demand unit default was `QUINTAL`,** where the API and the seed use
  `quintal`, so a demand created through the form would never have matched a lot.
- **Sellers were sent to the buyer's demand edit form** from the match list. They
  now get a read-only detail screen.
- **Two screens linked to a lot form that did not exist.** Built, covering create
  and edit, with the market benchmark shown while pricing.
- **Demo accounts were listed in production builds.** Now opt-in, and a
  production build tree-shakes the credential list out of the bundle.

Backend:

- **A demand with only one price bound crashed the match list,** and with it both
  the seller and buyer dashboards. `price_range` is now emitted only when both
  bounds exist, with a regression test.
- **Every notification link pointed at a route that does not exist**
  (`/farmer/lots`, `/buyer/offers`, `/buyer/profile`, `/quality`). Corrected at
  the source, with a test asserting every emitted link is a real route.

Deployment:

- **nginx ran as root.** Swapped to `nginxinc/nginx-unprivileged`, moved the
  listener to 8080, and validated the config during the image build so a bad
  config fails the build instead of crash-looping after deploy.
- **Every SPA response was served without security headers.** `index.html` sets
  its own `add_header Cache-Control`, and nginx replaces an inherited
  `add_header` set instead of merging it, so `X-Content-Type-Options`,
  `X-Frame-Options` and `Referrer-Policy` were dropped from the app and its
  assets. The headers moved to a snippet that every cache-setting location
  includes. Found by reading the response headers of the running container, not
  by any test.
- **`.env.example` listed only port 5173 in CORS,** which is the Vite dev origin,
  not the Docker one.

### Decisions taken

- **React + Vite + TypeScript + Tailwind, deliberately light.** The target is a
  low-end Android phone on 3G, and a component library would have had to be
  themed around the bilingual agricultural context anyway.
- **Navigation filters on permissions, not roles,** so the backend matrix stays
  authoritative.
- **One typed dictionary for both languages,** so a missing Marathi string is a
  compile error rather than a silent English fallback.
- **nginx is the only public origin.** The browser never makes a cross-origin
  request and the bearer tokens stay same-origin.
- **The demo panel follows `DEMO_MODE` in Compose** but is a separate build-time
  flag, because Vite bakes `import.meta.env` into the bundle and there is nothing
  to read at runtime.
- **The floating-point money columns stay for now and are documented,** rather
  than being quietly carried. `NUMERIC(14, 2)` is the fix before settlement.

### Verification

77 tests, up from 74: two client-contract tests for the notification routes and
the match shape, and one regression test for the one-sided price bound.

```bash
pytest -q                             # 77 passed
ruff check app tests alembic          # clean
ruff format --check app tests alembic # clean
npm run lint                          # no errors
npm run typecheck                     # strict, clean
npm run build                         # 123 kB gzipped
node scripts/verify_api.mjs           # 100 checks, 0 failed, 2 expected 403s
```

Run against the Docker stack as well as the local processes: the same 100 checks
pass through nginx on port 8080, and the seeded row counts are identical on
PostgreSQL and SQLite.

### Day 2, later: the blank page after login, found by driving a browser

The buyer account rendered a blank screen after signing in. Types, lint, the build
and the 100-check contract run all passed, so nothing in the toolchain had seen it.

`scripts/browser_check.mjs` and `scripts/browser_sweep.mjs` drive the installed
Chrome over the DevTools Protocol with no new dependencies: they sign in as a demo
account, visit every route that role can reach, and report uncaught exceptions and
console errors alongside the rendered text. That is what made the failure legible.

Three real defects, all of the same kind: a field name the UI invented.

- `BuyerDashboardPage` read `data.price_cards` and `data.insights` from a response
  that has neither, then called `.length` on the missing array. Now the page reads
  `/markets/overview` and converts each row into a price card explicitly.
- The admin dashboard's `demand_by_commodity` and `activity_by_district` tables
  asked for `commodity`, `demand`, `quantity` and `orders`. The backend returns
  `commodity_name`, `open_demands`, `demanded_quintal`, `active_lots` and
  `trade_value`, so both tables drew rows of em dashes. Keying the first by
  `row.commodity`, which was always undefined, is also what produced React's
  "unique key" warning.
- `DashboardService._price_movement` read `name` and `modal_price` off
  `commodity_price_overview` rows, which call them `commodity` and
  `median_modal_price`. Every row went out with a null name and price.

Only the first crashed. The other two rendered something, which is why they
survived a green test run: nothing about a table full of dashes looks like a
failure. `test_admin_dashboard_analytics_rows_are_populated` now asserts every
analytics row carries the fields the screen reads, because these rows are plain
dicts and a wrong key cannot be caught by response validation.

`ErrorBoundary` is mounted at the root of the app for the same reason. A render
crash unmounts everything and there is nothing else to show the user, so a crash
is now a readable screen with the error, the component stack, a real reload and
sign-out. Verified by throwing inside a page and loading it: the boundary caught
it. The button reloads the document rather than clearing boundary state, which
would re-render the same crashing tree.

`/demands/new` was never a bug, only my sweep's mistake: it visits a route that
does not exist, so it landed on `/demands/:id` with the id `new` and the API
correctly rejected it with a UUID validation error. The create routes are
`/my-demands/new` and `/my-lots/new`. The sweep now visits those.

Final state: 78 backend tests pass, Ruff clean, frontend typecheck, lint and build
clean, `100 checks, 0 failed, 2 expected denials` against both the dev API and
the Docker stack, and all eight demo accounts render every route they can reach on
ports 5173 and 8080 with no console errors.

### Day 2, later still: a Makefile, and documentation that matches the code

`make up` now builds both images and runs the whole stack: it creates `.env` with
generated secrets if needed, starts Postgres, waits for it, migrates, seeds, waits
for the API, and prints the URL. `make dev` runs uvicorn and Vite in one terminal
on SQLite, which was otherwise two shells. `make check` is the fast gate and
`make verify` adds the contract check and the browser sweep. `make down` stops,
`make reset` wipes the database behind a typed confirmation.

Two things the Makefile had to know that the README did not say. `python3` on this
machine is 3.14, and the pinned `psycopg-binary` has no 3.14 wheel, so `install`
picks 3.13, 3.12 or 3.11 in order rather than assuming. And `pytest` needed
`PYTHONPATH=.` to import the app at all, which the README's own `pytest -q`
instruction did not have; `pythonpath = .` in `pytest.ini` fixes it once for
everyone, so the documented command now works as written.

Documentation was then brought back in line with the code, which had drifted in
two directions. `.env.example` documented about a third of the variables the app
reads, so all 54 are now there, each with its default and its consequence; the
README gained the same reference as grouped tables, a credentials section, and a
deployment checklist. `VITE_API_BASE_URL` turned out to be read by nothing, since
the client is hardcoded to the same origin, and it is now documented as the unused
knob it is rather than left looking functional. `docs/DEPLOYMENT.md` is the
runbook: pre-flight, first deploy, migrations, TLS, backups, upgrade and rollback,
secret rotation, monitoring, scaling, troubleshooting.

Live credentials are deliberately not in the README, because the README is a
tracked file. They live in `.env`, and `make secrets` renders them, in full, into
`SECRETS.local.md`, which is git-ignored; `--check` fails when that file drifts
from `.env`. Every secret is documented with how to generate it and how to rotate
it, and the one with a trap is called out: editing `POSTGRES_PASSWORD` does not
change the password inside an existing volume.

### Open

- No frontend unit-test runner. Strict types, lint, the production build, the
  contract check and the browser sweep stand in until Vitest and Testing Library
  are added.
- No visual or responsive verification. The browser scripts read the rendered
  DOM and the console, not pixels, so layout, overflow and small-screen
  behaviour are still unverified.
- There are no file uploads at all. `MEDIA_ROOT`, `MAX_UPLOAD_BYTES` and
  `ALLOWED_IMAGE_TYPES` are declared in `config.py`, compose mounts a `media`
  volume, and nginx sets `client_max_body_size 12m`, but no endpoint accepts a
  file: grievance evidence is a list of URLs. `settings.allowed_image_types`
  exists and nothing calls it. The docs used to describe a writable, backed-up
  media directory as a deployment requirement, which was wrong.
- Nine other settings are read by nothing: the three `RATE_LIMIT_*`, `REDIS_URL`,
  `CACHE_TTL_SECONDS`, the three `LOGISTICS_*`, `NOTIFICATION_PROVIDER` and
  `NVIDIA_EMBEDDING_MODEL`. `scripts/gen_config_table.py` holds the verified
  list in `UNUSED` and fails if it drifts, so the next session that wires one
  of them up has to update the note in the same commit.
- The NVIDIA path in the assistant has never been called against the live API.
- Rate limiting does not exist. `RATE_LIMIT_ENABLED`, `RATE_LIMIT_REQUESTS`,
  `RATE_LIMIT_WINDOW_SECONDS`, `REDIS_URL` and `CACHE_TTL_SECONDS` are declared in
  `config.py` and set by compose, but no code reads them, and there is no cache
  and no `limit_req` in nginx. The `RATE_LIMITED` exception class in
  `core/exceptions.py` is never raised. A public deployment must limit at the
  proxy. The docs used to claim this worked; that was wrong, and it is now stated
  in the README, the runbook and the config table.
- There is no first-run bootstrap. `--no-demo` seeds zero accounts, staff
  registration is admin-only, and there is no web screen for `POST /api/v1/users`,
  so a `DEMO_MODE=false` deployment has to promote the first admin with a direct
  `UPDATE users SET primary_role_id = ...`. The runbook documents the statement;
  the API does not offer a supported way to do it. A CLI subcommand
  (`python -m app.db.promote_admin 9000000009`) or a screen would close it.
- `git` has an initialised repository and no commit.

### Things a future session should not break

- Carried over from Day 1, still true: read `meta.total_items` for pagination;
  successful responses stay unwrapped; the seeder stays idempotent; grade
  thresholds are "at or above"; ignore the `BlockingPortal` warning; every dict
  fed to `_price_cards` must have the one card shape. A second row shape exists:
  `commodity_price_overview` rows are named `commodity` and `median_modal_price`,
  unlike the per-commodity price cards. Conflating them yields null-filled
  tables, not errors.
- `scripts/browser_sweep.mjs` and `browser_check.mjs` are the only checks that
  execute the UI. A green typecheck and a green contract run have both coexisted
  with a blank page, so run them before believing a frontend change works.
- The README documents every environment variable, and the check that keeps it
  honest is comparing the names in `.env.example` against the fields in
  `app/core/config.py`. A variable in one and not the other is a documentation
  bug, and a knob in neither is worse.
- `SECRETS.local.md` and `.env` are git-ignored and must stay that way. The
  README names every secret and says how to make and rotate one, and holds no
  values.
- Route counts: 134 routes registered on the app, 129 of them documented
  operations across 109 paths. The 5 that are not: `GET /`, which is deliberately
  hidden from the document, plus `/health`, `/ready` and the two docs mounts. Use
  the OpenAPI number, 129, in documentation.
- The two `storage/options` 403s in `verify_api.mjs` are asserted, not tolerated.
  If a role can suddenly read storage options, that is a leak, not a fix.
- Demo accounts are opt-in now. Do not make the panel appear because
  `import.meta.env.DEV` is true in a development build that someone deploys.
