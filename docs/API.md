# API reference

Generated from the running application's OpenAPI document: **129 operations** across 109 paths.

## Conventions

- Base path `/api/v1`. Interactive docs at `/docs`, machine-readable schema at
  `/openapi.json`.
- Successful responses are the object itself, not an envelope.
- Paginated responses are `{"items": [...], "meta": {"total_items": n, ...}}`.
  Read `meta.total_items` for the count, not `items.length`.
- Errors are
  `{"success": false, "error": {"code": "...", "message": "...", "field_errors": {...}}, "request_id": "..."}`.
  `request_id` is also returned in the `X-Request-ID` header and appears in the
  logs, so a user-visible failure can be traced to its cause.
- Supply `X-Request-ID` and it is honoured end to end.
- Routes marked *public* need no token. Everything else takes
  `Authorization: Bearer <access_token>`.

## Error codes

| Code | Meaning |
| --- | --- |
| `VALIDATION_ERROR` | Malformed body or query. `field_errors` names the offending fields. |
| `UNAUTHENTICATED` | Missing, expired or revoked token. |
| `ROLE_NOT_ALLOWED` | Authenticated, but this role may not use the route. |
| `PERMISSION_DENIED` | Role is allowed in principle but lacks the specific permission. |
| `NOT_FOUND` | No such record, or it exists but is not visible to this caller. |
| `CONFLICT` | The move is not legal from the record's current state. |
| `BUSINESS_RULE` | The action is well-formed but the domain forbids it. |
| `RATE_LIMITED` | Too many requests. See `Retry-After`. |

## Authentication and session

Registration, sign-in, token refresh and the current profile. The only routes that work without a token, apart from the system probes.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/change-password` | Change own password | bearer |
| `POST` | `/api/v1/auth/login` | Log in | public |
| `POST` | `/api/v1/auth/logout` | Log out | bearer |
| `GET` | `/api/v1/auth/me` | Current profile | bearer |
| `PATCH` | `/api/v1/auth/me` | Update own profile | bearer |
| `POST` | `/api/v1/auth/refresh` | Refresh an access token | public |
| `POST` | `/api/v1/auth/register` | Register a new account | public |
| `GET` | `/api/v1/auth/roles` | List platform roles | public |

## Dashboards

A precomputed view per role. Each returns the stats, recent activity and next actions that role needs.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/dashboards/admin` | Administrator dashboard | bearer |
| `GET` | `/api/v1/dashboards/buyer` | Buyer dashboard | bearer |
| `GET` | `/api/v1/dashboards/farmer` | Farmer dashboard | bearer |
| `GET` | `/api/v1/dashboards/me` | Dashboard for the caller's role | bearer |

## Lots

The seller's inventory. A lot is one batch of produce offered for sale, and carries grade, quantity, location and pickup terms.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/lots` | Browse lots | bearer |
| `POST` | `/api/v1/lots` | Create a lot | bearer |
| `GET` | `/api/v1/lots/mine` | List own lots | bearer |
| `GET` | `/api/v1/lots/stats` | Lot status counts | bearer |
| `GET` | `/api/v1/lots/{lot_id}` | Lot detail | bearer |
| `PATCH` | `/api/v1/lots/{lot_id}` | Update a lot | bearer |
| `DELETE` | `/api/v1/lots/{lot_id}` | Delete a lot | bearer |
| `POST` | `/api/v1/lots/{lot_id}/cancel` | Cancel a lot | bearer |
| `GET` | `/api/v1/lots/{lot_id}/matches` | Demands matching a lot | bearer |
| `POST` | `/api/v1/lots/{lot_id}/publish` | Publish a draft lot | bearer |
| `GET` | `/api/v1/lots/{lot_id}/similar` | Similar lots | bearer |

## Demands

What buyers want: a commodity, a quantity, a grade floor, a price ceiling and a date by which it is needed.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/demands` | Browse demands | bearer |
| `POST` | `/api/v1/demands` | Create a demand | bearer |
| `GET` | `/api/v1/demands/mine` | List own demands | bearer |
| `GET` | `/api/v1/demands/{demand_id}` | Demand detail | bearer |
| `PATCH` | `/api/v1/demands/{demand_id}` | Update a demand | bearer |
| `POST` | `/api/v1/demands/{demand_id}/close` | Close a demand | bearer |
| `GET` | `/api/v1/demands/{demand_id}/matches` | Lots for a demand | bearer |

## Matching

Scored matches between the caller's own side of the trade and the other side. Scores are advisory and carry a disclaimer.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/matches` | Personalised matches | bearer |
| `GET` | `/api/v1/matches/commodity/{commodity_id}` | Commodity shortlist | bearer |
| `GET` | `/api/v1/matches/summary` | Match summary | bearer |

## Offers

A price for a lot, or a counter-offer against an earlier one. Accepting one creates the order.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `POST` | `/api/v1/offers` | Create an offer | bearer |
| `GET` | `/api/v1/offers` | List offers | bearer |
| `GET` | `/api/v1/offers/lot/{lot_id}` | Offers on a lot | bearer |
| `POST` | `/api/v1/offers/preflight` | Validate an offer before submitting | bearer |
| `GET` | `/api/v1/offers/{offer_id}` | Offer detail | bearer |
| `POST` | `/api/v1/offers/{offer_id}/accept` | Accept an offer | bearer |
| `POST` | `/api/v1/offers/{offer_id}/counter` | Counter an offer | bearer |
| `GET` | `/api/v1/offers/{offer_id}/history` | Offer negotiation history | bearer |
| `POST` | `/api/v1/offers/{offer_id}/reject` | Reject an offer | bearer |
| `POST` | `/api/v1/offers/{offer_id}/withdraw` | Withdraw an offer | bearer |

## Orders

Confirmed trades and their status pipeline, from acceptance through pickup, transit and delivery.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/orders` | List orders | bearer |
| `GET` | `/api/v1/orders/pipeline` | Order pipeline counts | bearer |
| `GET` | `/api/v1/orders/{order_id}` | Order detail | bearer |
| `GET` | `/api/v1/orders/{order_id}/allowed-transitions` | Statuses the caller may advance to | bearer |
| `GET` | `/api/v1/orders/{order_id}/logistics` | Logistics job for an order | bearer |
| `POST` | `/api/v1/orders/{order_id}/status` | Advance an order status | bearer |
| `GET` | `/api/v1/orders/{order_id}/transactions` | Ledger transactions for an order | bearer |

## Market data

Commodities, markets, price snapshots, trends across time and comparison between markets for a single day.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/markets/arrivals` | Arrival series | bearer |
| `GET` | `/api/v1/markets/commodities` | List commodities | bearer |
| `GET` | `/api/v1/markets/commodities/{commodity_id}` | Commodity detail | bearer |
| `GET` | `/api/v1/markets/commodities/{commodity_id}/attributes` | Grading attributes for a commodity | bearer |
| `GET` | `/api/v1/markets/districts` | List market districts | bearer |
| `GET` | `/api/v1/markets/markets` | List markets | bearer |
| `GET` | `/api/v1/markets/markets/{market_id}` | Market detail | bearer |
| `GET` | `/api/v1/markets/overview` | Cross-commodity overview | bearer |
| `GET` | `/api/v1/markets/price-snapshot` | Commodity price snapshot | bearer |
| `GET` | `/api/v1/markets/prices` | Search price records | bearer |
| `GET` | `/api/v1/markets/prices/comparison` | Compare markets on a date | bearer |
| `GET` | `/api/v1/markets/prices/latest` | Latest price board | bearer |
| `GET` | `/api/v1/markets/prices/trend` | Price trend for a commodity | bearer |

## Quality and inspections

Inspections, per-commodity quality parameters, recorded grades and grade suggestions.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/quality/attributes/{commodity_id}` | Quality parameters for a commodity | bearer |
| `POST` | `/api/v1/quality/grade-suggestion` | Suggest a grade from measurements | bearer |
| `GET` | `/api/v1/quality/inspections` | List inspections | bearer |
| `POST` | `/api/v1/quality/inspections` | Submit an inspection | bearer |
| `GET` | `/api/v1/quality/inspections/pending` | Inspections awaiting verification | bearer |
| `GET` | `/api/v1/quality/inspections/{inspection_id}` | Inspection detail | bearer |
| `POST` | `/api/v1/quality/inspections/{inspection_id}/verify` | Verify a submitted grade | bearer |

## Logistics

Transport requests, quotes from providers, assignment and status updates.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/logistics` | List logistics jobs | bearer |
| `POST` | `/api/v1/logistics` | Request transport for an order | bearer |
| `GET` | `/api/v1/logistics/orders/{order_id}` | Logistics job for an order | bearer |
| `POST` | `/api/v1/logistics/quotes` | Price a transport lane | bearer |
| `GET` | `/api/v1/logistics/{request_id}` | Logistics job detail | bearer |
| `PATCH` | `/api/v1/logistics/{request_id}` | Update a logistics job | bearer |
| `POST` | `/api/v1/logistics/{request_id}/assign` | Assign a transporter | bearer |
| `POST` | `/api/v1/logistics/{request_id}/cancel` | Cancel a logistics job | bearer |

## Storage

Godowns and cold storage, with the capacity a seller can actually book for a lot.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/storage` | Browse storage | bearer |
| `POST` | `/api/v1/storage` | Register a storage facility | bearer |
| `GET` | `/api/v1/storage/mine` | List own storage | bearer |
| `GET` | `/api/v1/storage/options` | Storage options for a seller | bearer |
| `GET` | `/api/v1/storage/{facility_id}` | Storage facility detail | bearer |
| `PATCH` | `/api/v1/storage/{facility_id}` | Update a facility | bearer |
| `DELETE` | `/api/v1/storage/{facility_id}` | Delete a facility | bearer |

## Payments

The obligation ledger: what is owed, what has been recorded as settled, and what is overdue. Not a payment gateway.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/payments` | List payments | bearer |
| `GET` | `/api/v1/payments/due-soon` | Payments due soon | bearer |
| `GET` | `/api/v1/payments/summary` | Payment summary for the caller | bearer |
| `GET` | `/api/v1/payments/summary/platform` | Platform-wide payment totals | bearer |
| `GET` | `/api/v1/payments/{payment_id}` | Payment detail | bearer |
| `PATCH` | `/api/v1/payments/{payment_id}/status` | Record a payment status change | bearer |

## Grievances

Disputes raised by any party, with a comment thread and evidence attachments.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/grievances` | List grievances | bearer |
| `POST` | `/api/v1/grievances` | Raise a grievance | bearer |
| `GET` | `/api/v1/grievances/summary` | Grievance counts by status | bearer |
| `GET` | `/api/v1/grievances/{grievance_id}` | Grievance detail | bearer |
| `PATCH` | `/api/v1/grievances/{grievance_id}` | Update a grievance | bearer |
| `POST` | `/api/v1/grievances/{grievance_id}/comments` | Add a comment to a grievance | bearer |
| `GET` | `/api/v1/grievances/{grievance_id}/comments` | Comment thread for a grievance | bearer |
| `POST` | `/api/v1/grievances/{grievance_id}/escalate` | Escalate a grievance | bearer |

## Notifications

The in-app feed, with an unread tally and a link to the relevant record.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/notifications` | List own notifications | bearer |
| `POST` | `/api/v1/notifications/read-all` | Mark every notification as read | bearer |
| `GET` | `/api/v1/notifications/unread-count` | Unread notification count | bearer |
| `POST` | `/api/v1/notifications/{notification_id}/read` | Mark one notification as read | bearer |

## AI assistance

The assistant and its recommendations. Advisory only; see `docs/AI_BOUNDARY.md`.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `POST` | `/api/v1/ai/chat` | Ask the assistant | bearer |
| `GET` | `/api/v1/ai/conversations` | List own conversations | bearer |
| `GET` | `/api/v1/ai/conversations/{conversation_id}` | Conversation transcript | bearer |
| `DELETE` | `/api/v1/ai/conversations/{conversation_id}` | Delete a conversation | bearer |
| `POST` | `/api/v1/ai/price-discovery` | Estimate a fair price | bearer |
| `GET` | `/api/v1/ai/recommendations` | List own recommendations | bearer |

## Administration

Platform operations: users and roles, buyer verification, the commodity and market catalogue, market data sync, price overrides and the audit trail.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/api/v1/admin/audit-logs` | Search the audit trail | bearer |
| `GET` | `/api/v1/admin/audit-logs/{entity_type}/{entity_id}` | History for one entity | bearer |
| `GET` | `/api/v1/admin/commodities` | List catalogue commodities | bearer |
| `POST` | `/api/v1/admin/commodities` | Add a commodity | bearer |
| `PATCH` | `/api/v1/admin/commodities/{commodity_id}` | Edit a commodity | bearer |
| `GET` | `/api/v1/admin/health` | Platform health | bearer |
| `POST` | `/api/v1/admin/market-data/sync` | Run a market data sync | bearer |
| `GET` | `/api/v1/admin/market-data/sync-logs` | Recent sync runs | bearer |
| `GET` | `/api/v1/admin/markets` | List markets | bearer |
| `POST` | `/api/v1/admin/markets` | Add a market | bearer |
| `PATCH` | `/api/v1/admin/markets/{market_id}` | Edit a market | bearer |
| `GET` | `/api/v1/admin/users` | Search user accounts | bearer |
| `POST` | `/api/v1/admin/users` | Create a staff account | bearer |
| `GET` | `/api/v1/admin/users/counts` | User totals | bearer |
| `GET` | `/api/v1/admin/users/sellers` | Newest accounts | bearer |
| `GET` | `/api/v1/admin/users/{user_id}` | Account detail | bearer |
| `PATCH` | `/api/v1/admin/users/{user_id}/status` | Change account status | bearer |
| `POST` | `/api/v1/admin/users/{user_id}/verify-buyer` | Approve or reject a buyer | bearer |

## System and health

Liveness, readiness and the OpenAPI document itself.

| Method | Path | What it does | Auth |
| --- | --- | --- | --- |
| `GET` | `/health` | Liveness and readiness | public |
| `GET` | `/ready` | Readiness probe | public |
