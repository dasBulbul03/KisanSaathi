# Day 1 deliverable

What exists and works as of 28 September 2026. This is the answer to "what is
done now", written at the point of completion rather than reconstructed later.

**Everything below is verified by the 74-test suite or by running it.** Nothing on
this list is a stub.

---

## 1. The API

129 routes, 109 OpenAPI paths, all under `/api/v1`. 18 routers, aggregated in
`app/api/v1/__init__.py`.

### Auth and identity (8)
Register with role-specific onboarding fields, login by phone or email, refresh
with rotation, logout, `/auth/me`, profile update, password change, and the
available-roles list for the registration form.

Refresh tokens rotate on every use. Presenting an already-rotated token revokes
the whole chain, so a stolen refresh token cannot outlive one refresh.

### Dashboards (4)
`/dashboards/me` resolves by role: farmer, FPO, buyer or admin. Each is built from
the viewer's own pipeline counts, not platform-wide totals.

A quality inspector or logistics partner has no dashboard, and `/dashboards/me`
says so with a `403 NO_DASHBOARD_FOR_ROLE` rather than a validation error. Those
roles work through their own endpoints.

### Markets and prices (13)
Commodity catalogue with quality attributes, market list and detail, districts,
price snapshot, latest prices, trend series, cross-market comparison, arrivals,
and an overview for the landing screen.

Prices and arrivals come from a provider behind an interface. The bundled `demo`
provider generates deterministic synthetic data, clearly labelled as such, and
sync runs are logged.

### Lots (11)
Create, edit, publish, cancel, delete, browse, own lots, stats, matches on a lot,
and similar-lot suggestions.

### Demands (7)
Create, edit, close, browse, own demands, and per-demand matches.

### Matching (3)
Suggestion summary, browse suggestions, and suggestions for one commodity. Roles
are normalised before matching, so a farmer and an FPO are both on the seller
side and never silently treated as buyers.

### Offers (10)
Make, preflight, counter, accept, reject, withdraw, browse, per-lot offers, and
full counter-offer history.

Accepting an offer is what creates the order.

### Orders and transactions (7)
Browse, role-scoped pipeline, detail, allowed transitions for the current user,
logistics and transaction records, and status transitions.

Transitions are validated in one place (`ORDER_TRANSITIONS`) and gated by role
(`TRANSITION_ROLES`), so the API can never move an order into a state the caller
has no business reaching. Details are party-checked.

### Logistics (8)
Request, quote, assign, update, cancel, browse, and per-order view.

### Storage (7)
Register a godown, edit, delete, browse, own facilities, and storage options for
a seller. Private facilities are visible to their owner only.

### Quality (7)
Record an inspection, verify it, browse, pending queue, per-commodity attribute
definitions, and a grade suggestion from measured parameters.

Grade suggestion uses ideal ranges only, so it is direction-agnostic: low moisture
is good, high curcumin is good, and neither needs special-casing.

### Payments (6)
Browse, detail, due-soon, personal summary, platform summary, and status updates.
All scoped to the viewer's own side of the trade.

### Grievances (8)
Raise, comment, escalate, update, browse, summary, and per-ticket comments, with
party and staff permissions applied.

### Notifications (4)
List, unread count, mark one read, mark all read.

### AI assistance (6)
Chat, price discovery, recommendations, and conversation history. **Disabled
until `NVIDIA_API_KEY` is set.** The assistant drafts and advises; it never moves
an order, a payment or a price.

### Admin (18)
User list, detail, counts, seller directory, create staff user, activate or
suspend, verify buyer, commodity and market CRUD including retired rows, audit
logs, sync logs, trigger a sync, and a health endpoint.

### System (2)
`/health` and `/ready` at the root.

---

## 2. Cross-cutting behaviour

**Permissions.** `app/core/rbac.py` holds the matrix for all six roles. It is
enforced in the services, so a rule cannot be bypassed by calling a service
directly from a test or a script. The seeder copies the matrix into the `roles`
table, so the database and the code cannot disagree.

**Errors.** One envelope for every failure:
`{success: false, error: {code, message}, request_id}`. Domain errors carry stable
codes like `INVALID_TRANSITION`, `PHONE_ALREADY_REGISTERED` and
`ROLE_NOT_SEEDED`, so the frontend can branch on the code rather than parsing
prose.

**Request tracing.** Every request gets an ID, returned in `X-Request-ID`, in the
error body, and in the structured logs.

**Audit log.** State-changing actions record the actor, their role, and the
before/after values.

**Notifications.** Domain events write in-app notifications, so a seeded demo has
a populated notification list on both sides of the trade.

---

## 3. Data

**Schema.** 33 tables via one reviewed Alembic migration. `alembic check` is clean
and `downgrade base` removes everything.

**Catalogue.** 10 commodities with Marathi names, seasonality notes and price
floors; 9 markets across APMC mandi, farm gate, collection centre, organic mandi
and private hub; 26 quality parameters.

Quality parameters carry an explicit direction. `grade_a_min` and `grade_b_min`
mean "at or above", so they exist only for higher-is-better parameters like oil
content, curcumin and staple length. Rot percentage, moisture and impurity get an
ideal band and no grade threshold. Without that distinction the grader would award
Grade A to the worst produce in the lot.

**Demo data.** 8 accounts across all 6 roles, 120 days of prices and arrivals for
every commodity and market, 2 godowns (one private, one shared), and one complete
trade: published onion lot → buyer demand → accepted offer → order → scheduled
pickup. The order stops mid-pipeline deliberately, so a demo has a next step.

Both farmers get their own published lot and both buyers their own open demand, so
no account signs in to an empty app. The seeder prints which account carries what.

Re-running the seeder changes nothing. It upserts on natural keys.

---

## 4. Quality gate

```
74 passed          pytest
clean              ruff check app tests alembic
91 files formatted ruff format --check app tests alembic
3.4s               full seed from an empty database
```

Test breakdown: service and permission tests per domain, HTTP integration tests
through `TestClient` covering the error envelope, RBAC denials, role-scoped
pipelines, payments and private storage, and seeder tests pinning idempotency and
the grading data.

---

## 5. Not done

- **Frontend.** Empty. Bilingual English + Marathi with a toggle was chosen; the
  stack is still an open decision.
- **Deployment.** No Dockerfile, compose, `.env.example` or `.gitignore`.
- **Postgres.** Installed and configured, but never actually run against a live
  PostgreSQL instance. Everything is verified on SQLite.
- **No `.gitignore`**, so the SQLite dev database created by the quick start is
  currently untracked-but-unprotected. Add one before `git init`.
- **Git.** Not initialised.
