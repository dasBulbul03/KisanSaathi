"""Version 1 of the public API.

Every router is registered here so ``main.py`` has a single import point and the
surface can be versioned as a unit.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    ai,
    auth,
    dashboards,
    demands,
    grievances,
    logistics,
    lots,
    markets,
    matches,
    notifications,
    offers,
    orders,
    payments,
    quality,
    storage,
    users,
)

# Order matters for the generated OpenAPI document: authentication and reference
# data first, then the trading workflow, then analytics and administration.
api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(markets.router)
api_router.include_router(lots.router)
api_router.include_router(demands.router)
api_router.include_router(matches.router)
api_router.include_router(offers.router)
api_router.include_router(orders.router)
api_router.include_router(logistics.router)
api_router.include_router(storage.router)
api_router.include_router(quality.router)
api_router.include_router(payments.router)
api_router.include_router(grievances.router)
api_router.include_router(notifications.router)
api_router.include_router(ai.router)
api_router.include_router(dashboards.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]
