# Day 2 — frontend, deployment and documentation

Backend was finished, migrated, seeded and tested on Day 1 (see
[`DAY1.md`](DAY1.md)). This document covers what was added on Day 2 and the
decisions behind it.

## Summary

| Area | State |
| --- | --- |
| Frontend | 21 page modules, routed and permission-gated, English and Marathi |
| Deployment | Docker Compose stack: Postgres, API, nginx-served frontend |
| Documentation | API reference, data model, AI boundary, this file |
| Verification | 77 backend tests, strict TypeScript, 100 API contract checks |

## Frontend

### Stack

React 19, Vite 8, TypeScript 6 in strict mode, Tailwind CSS 4, React Router 7.
Four runtime dependencies in total. No component library, no data-fetching
library, no global state container.

The alternative was a heavier stack with a component library. That was rejected
for two reasons: the app targets low-end Android phones on 3G, where every
kilobyte of framework is real latency, and a component library would have had to
be themed around the bilingual agricultural context anyway. Tailwind gives the
same result with nothing shipped at runtime.

### Layout

```
frontend/src/
  lib/
    api.ts           token storage, single-flight refresh, typed ApiError
    endpoints.ts     one wrapper per API route
    types.ts         types transcribed from the OpenAPI schema
    i18n.tsx         provider, formatters, language switch
    dictionaries.ts  every UI string, English and Marathi
  auth/AuthContext   session state, sign-in, role landing routes
  hooks/             useAsync, permission-filtered nav, media queries
  components/        shared UI, form controls, AppLayout, dashboard pieces
  pages/             one module per screen
```

### Two decisions worth explaining

**Navigation is filtered by permission, not by role.** `app/core/rbac.py` is the
single source of truth for what each role may do, and `/auth/me` already returns
that permission list. The nav filters on those strings directly, so adding a
permission on the server surfaces the corresponding link in the UI with no
frontend change, and removing one hides it everywhere at once.

**Translations are one typed dictionary.** English and Marathi live together in a
`Record<TranslationKey, string>`. A missing Marathi string is a compile error,
not a runtime fallback to English, which means a half-translated screen cannot
ship. The alternative, per-key files, makes it easy to add one language and
forget the other.

### Screens

| Module | Screens |
| --- | --- |
| Auth | Sign in, self-registration (farmer, FPO, buyer) |
| Dashboards | Farmer and FPO, buyer, admin |
| Trade | Lot browser, lot detail, lot create and edit, demand browser, demand create and edit, demand detail, offers, order list, order detail |
| Market | Market prices with trend and market comparison, storage options, payments |
| Operations | Logistics, quality inspections, grievances, notifications |
| Admin | Platform dashboard, user management |
| Account | Profile |

That is 21 page modules covering 23 screens: the lot form serves both create and
edit, and the demand form serves both create and edit, so each is one module and
two routes.

Each role sees only its own subset, enforced twice: the nav hides links the role
cannot use, and every route has a `RequireRole` guard so a hand-typed URL lands
on that role's own dashboard rather than an error page.

### The API layer

`lib/api.ts` owns token storage and refresh. On a 401 it attempts exactly one
refresh, and concurrent 401s share that single refresh rather than each starting
their own, which is what stops a dashboard with six parallel requests from
rotating the refresh token six times and locking the user out. If the refresh
itself fails, tokens are cleared and the app returns to sign-in.

`lib/endpoints.ts` and `lib/types.ts` were written from the OpenAPI schema by
hand. That is the weak point of the frontend, so it is checked mechanically:
`scripts/verify_api.mjs` signs in as all eight demo accounts and calls every
endpoint a screen uses, verifying both status and response shape. A bare list
where the client expects an object is caught there rather than as a blank screen.

## Bugs found and fixed

Frontend:

- **Sign-in was broken for every user.** The client posted `{phone, password}`;
  the API field is `identifier`. Nobody could log in.
- **The price snapshot response is an object, not a list.** Two screens called
  `.map` and `.some` on it and would have thrown on every market view.
- **Trend points use `date`, not `price_date`,** and comparison rows have
  `change_pct_7d` instead of a `rank`. Both were wrong in the types.
- **Match endpoints return a bare array,** not the `{summary, results}` envelope
  the client expected, so the match table on a lot would have been empty.
- **Storage options were shown to roles that get 403** from that endpoint. The
  nav and route are now seller-only, matching the API's own scoping.
- **Role `<select>` options held React elements cast to strings,** which renders
  as `[object Object]` in the dropdown. Replaced with a plain-text hook.
- **The unit default was `QUINTAL`,** where the API and seed data use
  `quintal`. A demand created through the form would not have matched a lot.
- **Sellers were linked to the buyer's demand edit screen** from the match list.
  They now get a read-only detail view.
- **There was no lot create or edit form,** though two screens linked to it.
- **The buyer dashboard read fields the API does not send.** It took
  `price_cards` and `insights` from `/dashboards/buyer`, which returns neither,
  and called `.length` on the missing array: signing in as a buyer produced a
  blank page. The screen now reads `/markets/overview` and converts the rows.
- **The admin analytics tables asked for the wrong field names.**
  `demand_by_commodity` and `activity_by_district` wanted `commodity`, `demand`,
  `quantity` and `orders`; the API returns `commodity_name`, `open_demands`,
  `demanded_quintal`, `active_lots` and `trade_value`. Both tables rendered rows
  of em dashes, and the `undefined` key on the first one triggered React's
  "unique key" warning on every admin page.
- **Admin price movement was entirely null.** `_price_movement` read `name` and
  `modal_price` from `commodity_price_overview` rows, which are named `commodity`
  and `median_modal_price`. Nothing crashed; the numbers were simply missing.
- **A render crash had no recovery path.** A thrown error unmounted the tree and
  left a blank page. A root `ErrorBoundary` now shows the message, the component
  stack, a document reload and sign-out. Its first version cleared boundary state
  instead of reloading, which would have re-thrown the same error for any
  state-dependent crash.
- **Demo accounts were listed on every build,** not just development. The
  credentials are now opt-in: they render in `npm run dev`, in a Docker stack
  built with `DEMO_MODE=true`, and nowhere else. A production build with the
  variable unset tree-shakes the account list out of the bundle entirely, so the
  working credentials are not in the shipped JavaScript at all.

Backend:

- **A demand with only a price ceiling crashed the match list,** and with it the
  farmer and buyer dashboards: a one-sided price range failed validation on the
  whole response. Found by the contract check, fixed, and covered by a new test.
- **Notification links pointed at routes that do not exist** (`/farmer/lots`,
  `/buyer/offers`, `/buyer/profile`, `/quality`). Following one dropped the user
  into a redirect with no explanation. Corrected at the source, and a new test
  asserts every emitted link is a real app route.

## Deployment

`docker compose up --build` brings up Postgres 16, the API and an
nginx-served frontend on http://localhost:8080.

```
docker compose up --build        # migrate, seed, serve
docker compose logs -f backend   # follow the seed
docker compose down -v           # stop and discard the volume
```

Details:

- **Migrations run before the app serves.** The backend entrypoint applies
  `alembic upgrade head` and seeds, so a fresh volume comes up with a working
  schema and demo data rather than an empty database.
- **One origin.** nginx serves the SPA and proxies `/api` to the backend, so the
  browser never makes a cross-origin request and the bearer tokens in
  localStorage stay same-origin.
- **Both images are non-root** and carry healthchecks: the API as uid 10001,
  nginx as uid 101. nginx therefore listens on 8080 inside the container, which
  a non-root process is allowed to bind, and `docker-compose.yml` maps that to
  `${FRONTEND_PORT:-8080}` on the host. The nginx config is validated during the
  image build, so a bad config is a failed build rather than a container that
  crash-loops after deploy. Compose gates the frontend on the backend's `/ready`,
  so nginx never starts in front of a dead API.
- **Cache and security headers.** Hashed assets are immutable for a year;
  `index.html` is never cached, so a deploy cannot leave stale asset URLs in a
  browser. The security headers live in their own snippet that every location
  which sets its own `Cache-Control` includes, because nginx replaces an
  inherited `add_header` set rather than merging it — without that, every SPA
  response was being served with no `X-Content-Type-Options` at all.
- **Demo data is opt-out.** `DEMO_MODE=false` seeds reference data only;
  `SEED_ON_START=false` skips seeding entirely. `VITE_SHOW_DEMO_ACCOUNTS` controls
  the sign-in panel independently and follows `DEMO_MODE` unless set, because the
  flag is baked into the bundle at build time rather than read at runtime.

## Verification

Everything below was run against the real stack, not asserted.

```bash
# Backend
pytest -q                              # 78 passed
ruff check app tests alembic           # clean
ruff format --check app tests alembic  # clean

# Frontend
npm run typecheck                      # strict, clean
npm run lint                           # no errors
npm run build                          # 123 kB gzipped

# Contract, dev API and Docker API
node scripts/verify_api.mjs            # 100 checks, 0 failed, 2 expected 403s

# UI, in real Chrome, all eight accounts, dev and Docker
node scripts/browser_check.mjs http://localhost:5173 9000000005
node scripts/browser_sweep.mjs http://localhost:8080   # all routes rendered

# PostgreSQL
docker compose up -d
docker compose exec db psql -U kisan -d kisansaathi \
  -c "select count(*) from market_prices;"   # 10800
```

The last two scripts are the ones that found the blank page. They attach to the
installed Chrome over the DevTools Protocol, sign in, walk every route the
account can reach, and fail on an uncaught exception or a console error. The
three field-name defects above all passed typecheck, lint, the build and the
contract check, because a wrong key in a `dict` is not a type error and a table
full of em dashes is not a failing response.

The seeded dataset is intact on PostgreSQL: 8 demo accounts, 10 commodities,
10,800 price rows, 10,800 arrival rows, 2 lots, 2 demands, 2 godowns, 1 order.

## Operating it

`Makefile` is the entry point. `make up` builds both images and runs the stack,
waiting for the API before it prints the URL; `make dev` runs uvicorn and Vite in
one terminal on SQLite; `make check` is tests, lint, types and the production
build; `make verify` adds the contract check and the real-browser sweep.
`make down` stops, `make reset` destroys the database behind a typed confirmation,
`make secrets` writes every live credential to the git-ignored `SECRETS.local.md`.

`docs/DEPLOYMENT.md` is the production runbook, and the README carries the full
configuration reference for all 54 environment variables.

## Known limits

- **No frontend unit tests.** The screens are covered by strict types, lint, the
  production build and the API contract check, not by component tests. Adding
  Vitest and Testing Library is the obvious next step.
- **`react/only-export-components` is off for five files.** The provider-plus-hook
  pattern is idiomatic React, and the rule only protects Fast Refresh
  granularity, which is a dev-server nicety. `npm run lint` is otherwise silent.
- **No visual regression testing.** The browser scripts read the rendered DOM and
  the console, not pixels. Screenshots exist but nothing compares them, so layout,
  overflow and small-screen behaviour remain unverified.
- **Media uploads are configured but untested end to end.** `MEDIA_ROOT` is a
  writable volume in Compose, and the type and size limits are enforced, but no
  test exercises a real upload through nginx.
- **The AI assistant is untested against a live provider.** It degrades to the
  deterministic rules engine without `NVIDIA_API_KEY`, which is what the test
  suite covers. The NVIDIA path has never been called.
- **There is no rate limiting.** `RATE_LIMIT_ENABLED` and `REDIS_URL` are declared
  in `config.py` and set by compose, but no code reads them, so nothing is limited.
  A public deployment needs a limiter at the proxy. Documented in the runbook.
- **Money is floating point.** Prices and amounts are `FLOAT` columns, so they
  cannot represent 0.10 exactly. Fine for a demo, wrong for settlement; the fix
  is `NUMERIC(14, 2)`, noted in [`DATA_MODEL.md`](DATA_MODEL.md).
- **The assistant answers in English only.** The endpoint accepts and stores a
  `language` field, but the deterministic formatter does not yet produce
  Marathi output.
