"""Cross-side matchmaking endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.trade import FarmLotOut, MatchSummary
from app.services.lot_service import LotService
from app.services.matching_service import MatchingService

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("", response_model=dict[str, Any], summary="Personalised matches")
def my_matches(
    session: DbSession,
    user: CurrentUser,
    commodity_id: uuid.UUID | None = Query(None, description="Restrict to a commodity"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Ranked matches for the caller's side of the marketplace plus a score summary.

    Sellers see buyer demands that fit their lots; buyers see lots that fit their
    demands. ``summary`` is the aggregate of the returned matches, not a global stat.
    """
    service = MatchingService(session)
    matches = service.matches_for_user(
        user.id, role=user.role.value, commodity_id=commodity_id, limit=limit
    )
    return {
        "matches": [result.model_dump(mode="json") for result in matches],
        "summary": service.summary(matches),
    }


@router.get("/summary", response_model=MatchSummary, summary="Match summary")
def match_summary(
    session: DbSession,
    user: CurrentUser,
    commodity_id: uuid.UUID | None = Query(None, description="Restrict to a commodity"),
    limit: int = Query(20, ge=1, le=100),
) -> MatchSummary:
    """Aggregate counts for the caller's current match shortlist."""
    service = MatchingService(session)
    matches = service.matches_for_user(
        user.id, role=user.role.value, commodity_id=commodity_id, limit=limit
    )
    stats = service.summary(matches)
    return MatchSummary(
        direction="demand_to_lot" if user.role.value == "BUYER" else "lot_to_demand",
        total_candidates=stats["total_candidates"],
        strong_matches=stats["strong_matches"],
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/commodity/{commodity_id}",
    response_model=list[FarmLotOut],
    summary="Commodity shortlist",
)
def commodity_shortlist(
    commodity_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
) -> list[FarmLotOut]:
    """A commodity shortlist, NOT scored matches.

    Unlike the scored endpoints this is a plain list of currently available lots
    for the commodity, so callers can eyeball supply before drilling into details.
    """
    service = LotService(session)
    items, _ = service.list_lots(commodity_id=commodity_id, page=1, page_size=limit)
    return [FarmLotOut.model_validate(service.enrich(lot)) for lot in items]


__all__ = ["router"]
