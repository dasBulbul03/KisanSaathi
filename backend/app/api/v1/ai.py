"""Assistant, price discovery and recommendation endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from app.ai.recommendation_engine import DiscoveryInput, PriceDiscoveryEngine
from app.api.deps import CurrentUser, DbSession, require_permissions
from app.core.enums import QualityGrade
from app.core.rbac import AI_CHAT, AI_RECOMMEND
from app.models import BuyerDemand, FarmLot, User
from app.repositories.trade import DemandRepository, LotRepository
from app.schemas.ai import (
    AIChatRequest,
    AIChatResponse,
    AIConversationOut,
    AIRecommendationOut,
    PriceDiscoveryResponse,
)
from app.services.assistant_service import AssistantService
from app.services.market_service import MarketService

router = APIRouter(prefix="/ai", tags=["ai"])

ChatUser = Annotated[User, Depends(require_permissions(AI_CHAT))]
RecommendUser = Annotated[User, Depends(require_permissions(AI_RECOMMEND))]


class PriceDiscoveryRequest(BaseModel):
    """What the seller is holding, so the engine can price it against the market."""

    commodity_id: uuid.UUID
    district: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    quality_grade: QualityGrade = QualityGrade.GRADE_A
    quantity_quintal: float = Field(default=0.0, ge=0)
    has_storage: bool = False


@router.post("/chat", response_model=AIChatResponse, summary="Ask the assistant")
def chat(payload: AIChatRequest, session: DbSession, user: ChatUser) -> AIChatResponse:
    """Answer a question using the caller's own platform and mandi data.

    The service resolves the topic, runs the matching deterministic tool and
    stores both turns, so every answer is reproducible and traceable. Omit
    ``conversation_id`` to start a new thread.
    """
    return AssistantService(session).chat(user, payload)


@router.get(
    "/conversations",
    response_model=list[AIConversationOut],
    summary="List own conversations",
)
def list_conversations(
    session: DbSession,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100, description="How many threads to return"),
) -> list[AIConversationOut]:
    """The caller's assistant threads, most recent first, without message bodies."""
    return AssistantService(session).list_conversations(user, limit=limit)


@router.get(
    "/conversations/{conversation_id}",
    response_model=AIConversationOut,
    summary="Conversation transcript",
)
def get_conversation(
    conversation_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> AIConversationOut:
    """A full transcript. Threads owned by somebody else are reported as missing."""
    return AssistantService(session).get_conversation(user, conversation_id)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a conversation",
)
def delete_conversation(
    conversation_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> Response:
    """Remove the thread and its messages; there is no archive state."""
    AssistantService(session).delete_conversation(user, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/recommendations",
    response_model=list[AIRecommendationOut],
    summary="List own recommendations",
)
def list_recommendations(
    session: DbSession,
    user: RecommendUser,
    kind: str | None = Query(None, description="Restrict to one recommendation kind"),
) -> list[AIRecommendationOut]:
    """Advice previously generated for the caller, newest first."""
    service = AssistantService(session)
    return [
        AIRecommendationOut.model_validate(recommendation)
        for recommendation in service.recent_recommendations(user, kind=kind)
    ]


@router.post(
    "/price-discovery",
    response_model=PriceDiscoveryResponse,
    summary="Estimate a fair price",
)
def price_discovery(
    payload: PriceDiscoveryRequest, session: DbSession, user: RecommendUser
) -> PriceDiscoveryResponse:
    """Price a lot against live mandi rates, arrivals and open buyer demand.

    The estimate is deterministic and every contribution is reported in
    ``factors`` so the number can be argued with. Supplying coordinates and a
    quantity is what turns it into a net realisation per quintal.
    """
    engine = PriceDiscoveryEngine(
        MarketService(session),
        DemandRepository(BuyerDemand, session),
        LotRepository(FarmLot, session),
    )
    return engine.discover(
        DiscoveryInput(
            commodity_id=payload.commodity_id,
            district=payload.district,
            latitude=payload.latitude,
            longitude=payload.longitude,
            quality_grade=payload.quality_grade,
            quantity_quintal=payload.quantity_quintal,
            has_storage=payload.has_storage,
        )
    ).response


__all__ = ["router"]
