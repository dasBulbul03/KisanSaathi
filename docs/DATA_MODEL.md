# Data model

33 tables, created by a single Alembic revision
(`20260928_2245_e639b37a45f7_initial_schema.py`). Verified on SQLite for
development and PostgreSQL 16 for deployment. There is no second migration
because the schema has not changed since the first day; when it does, add a
revision rather than editing the initial one.

Everything is generated from `app/models/`, so this document describes the
structure and the rules behind it rather than duplicating every column.

## Conventions

- **Primary keys** are UUIDs stored as `CHAR(32)`. Surrogate integers would leak
  row counts through an API and make a later sharding decision expensive.
- **Soft delete** on business records: `is_deleted` and `deleted_at`. A `lot` or
  an `order` is never removed, because a grievance may reference it later.
- **Timestamps** `created_at` and `updated_at` on every table, not null.
- **Money** is `FLOAT` for quantities and prices, never for settled amounts.
  PostgreSQL is a float for these columns, which is a real limitation: it cannot
  represent 0.10 exactly. A production deployment handling actual settlement
  should move to `NUMERIC(14, 2)`. It is recorded here rather than silently
  carried.
- **Enums** are `VARCHAR` with a Python enum, not a database enum type, so
  adding a status does not require a type migration.
- **JSON** is used for genuinely open shapes: `quality_specs`, sync payloads,
  assistant tool payloads. Anything queried or filtered is a real column.

## Entity map

```
                      ┌──────────────┐
                      │    users     │  1 role, 0..n role grants
                      └──────┬───────┘
             ┌───────────────┼───────────────┬──────────────┐
             │               │               │              │
     farmer_profiles   fpo_profiles   buyer_profiles   notifications
             │               │               │
             │          storage_facilities    │
             ▼               ▼               ▼
        farm_lots ◄── offers ──► buyer_demands
             │           │
             │           ▼
             │        orders ──► logistics_requests ──► logistics_quotes
             │           │              │
             │           ▼              │
             │      transactions        │
             │           │              │
             │           ▼              │
             │       payments           │
             │                          │
             ├──► quality_inspections ──► quality_measurements ──► quality_attributes
             │                  │
             └──► lot_images     │
                                ▼
                           grievances ──► grievance_comments, grievance_evidence
```

## Tables by area

### Identity and access

| Table | Columns | Notes |
| --- | --- | --- |
| `users` | 19 | Identity, phone and email unique, soft deleted, `created_by_user_id` records who provisioned the account |
| `roles` | 7 | The six fixed roles. `permissions` is a JSON list that mirrors `app/core/rbac.py`; a test asserts the two agree |
| `user_roles` | 7 | Role grants. One `primary_role_id` on the user plus these, so a person can hold more than one role |
| `refresh_tokens` | 9 | JTI, family and rotation. Reuse of a rotated token revokes the whole family, which is how token theft gets caught |

### Profiles

| Table | Columns | Notes |
| --- | --- | --- |
| `farmer_profiles` | 25 | Village, land, crops, bank and KCC details. Bank account is last-four only, never a full number |
| `fpo_profiles` | 29 | Organisation, registration, membership and aggregate storage. `member_count` and `women_member_count` |
| `buyer_profiles` | 29 | Buyer type, verification status, payment terms, purchasing locations. `verified_by_user_id` records who verified |

Each profile is a one-to-one extension of `users`, so the auth path never has to
join to read a person's name.

### Catalogue and market data

| Table | Columns | Notes |
| --- | --- | --- |
| `commodities` | 18 | `permitted_units` is a JSON list; `default_unit` seeds the form |
| `markets` | 19 | APMC mandis and private hubs, with `market_type` and facility flags |
| `market_prices` | 17 | Unique on `(market_id, commodity_id, price_date)` so a re-sync updates rather than duplicates |
| `market_arrivals` | 11 | Unique on `(market_id, commodity_id, arrival_date)`, same reason |
| `market_data_sync_logs` | 16 | One row per sync run: source, window, rows written, status. The Day 1 sync bug was logs being written and discarded, so this is asserted in tests |

### Trade

| Table | Columns | Notes |
| --- | --- | --- |
| `farm_lots` | 35 | `quantity` and `available_quantity` are separate: the first is the batch, the second what is still unsold. `active_offers_count` is denormalised for the list view |
| `lot_images` | 8 | One primary per lot, enforced in the service |
| `buyer_demands` | 29 | `min_grade` is a floor, not a preference, and matching honours that |
| `offers` | 23 | `parent_offer_id` makes a counter-offer a chain. `responded_by_user_id` and `decline_reason` record how it ended |
| `orders` | 27 | Unique on `offer_id`: one accepted offer produces exactly one order. `status_history` is JSON, appended by the service |

### Fulfilment

| Table | Columns | Notes |
| --- | --- | --- |
| `logistics_requests` | 36 | One per order that needs transport, with pickup and delivery addresses |
| `logistics_quotes` | 20 | Provider quotes against a request. The demo provider returns synthetic freight, labelled as such |
| `storage_facilities` | 26 | `is_private` and `owner_user_id` enforce the private-godown rule the API tests cover |
| `quality_attributes` | 17 | Per-commodity parameters. Unique on `(commodity_id, code)` |
| `quality_inspections` | 15 | Against a lot, an order, or both |
| `quality_measurements` | 8 | One row per measured attribute |

### Money

| Table | Columns | Notes |
| --- | --- | --- |
| `transactions` | 17 | The commercial record of a trade, separate from the payment obligation |
| `payments` | 19 | What is owed and what has settled. `payer_user_id`/`payee_user_id` and `due_date` drive the due-soon and overdue views |

### Support and operations

| Table | Columns | Notes |
| --- | --- | --- |
| `grievances` | 18 | Against an order or a transaction, or standalone. `assigned_to_user_id` and `against_user_id` cover both directions |
| `grievance_comments` | 7 | Thread |
| `grievance_evidence` | 10 | Attachments, uploaded to `MEDIA_ROOT` |
| `notifications` | 11 | Per user, with `link` pointing at a client route and `data` carrying the record id. A test asserts every `link` is a real route |
| `audit_logs` | 14 | Who changed what, when, from where |
| `ai_conversations` | 11 | Assistant threads |
| `ai_messages` | 16 | Messages within a thread |
| `ai_recommendations` | 18 | Cached recommendations, keyed by user and kind |

## Integrity

Five uniqueness constraints carry real business meaning, and the rest is indexes:

| Constraint | Why |
| --- | --- |
| `market_prices (market_id, commodity_id, price_date)` | A re-sync must update, not duplicate |
| `market_arrivals (market_id, commodity_id, arrival_date)` | Same |
| `quality_attributes (commodity_id, code)` | One parameter per commodity |
| `orders (offer_id)` | One accepted offer, one order |
| `user_roles (user_id, role_id)` | No duplicate grants |

214 indexes in total, the large majority single-column foreign keys. The
composite ones exist where a query filters on more than one: list views by owner
and status, dashboards by user and date, and the price lookups by commodity and
date.

## Foreign keys and referential actions

Destructive cascades are used only where a child row has no meaning without its
parent, and never on a table anyone might need to point at later.

| Action | Where | Why |
| --- | --- | --- |
| `CASCADE` | `lot_images`, `grievance_comments`, `grievance_evidence` from their parent; `quality_measurements` from an inspection; `ai_messages` from a conversation | Pure children with no independent life. Deleting a lot should not leave orphan photos |
| `SET NULL` | Optional attribution columns: `raised_by_user_id`, `assigned_to_user_id`, `resolved_by_user_id`, `verified_by_user_id`, `triggered_by_user_id`, and the optional `order_id` / `transaction_id` / `demand_id` on a grievance or inspection | The record stays meaningful after the person or linked record goes away. Losing the attribution is better than losing the grievance |
| `RESTRICT` | Core references: `farm_lots.seller_user_id`, `orders.buyer_user_id`, `orders.seller_user_id`, `offers.lot_id`, `buyer_demands.buyer_user_id` | A user, lot or demand cannot be deleted while a trade points at it. This is a guard rail, not a limitation: the path is a soft delete, and hard delete exists only for correcting a mistake before anything references the row |

The practical rule: **business records are soft deleted and their references are
never cascaded.** A payment that a grievance disputes must still be readable
years later, and `RESTRICT` on the chain that reaches it is what guarantees that.
