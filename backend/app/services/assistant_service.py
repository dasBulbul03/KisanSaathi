"""Conversational assistant for farmers, buyers and administrators.

Design notes
------------
The assistant is intentionally *grounded and hedged* because its audience makes
financial decisions from its output. Three rules drive the implementation:

1. **Numbers always come from the database**, never from the language model.
   The model is only allowed to phrase facts the deterministic tools returned.
2. **Every answer carries a disclaimer** and reports ``is_fallback`` so the UI
   can visibly flag an unsourced reply.
3. **Deterministic first.** Tool selection is rule based off the message text.
   If a tool can answer the question, we answer from it and skip the LLM
   entirely - which is both faster and impossible to hallucinate.

When ``NVIDIA_API_KEY`` is configured the LLM rephrases the grounded facts into
a conversational reply. When it is missing or fails, the templated fallback is
returned instead, so the feature degrades rather than breaks.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import AIConversationMode, MessageRole, UserRole
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models import AIConversation, AIMessage, AIRecommendation, User
from app.repositories.ai import ConversationRepository, MessageRepository, RecommendationRepository
from app.schemas.ai import (
    AIChatRequest,
    AIChatResponse,
    AIConversationOut,
    AIMessageOut,
)
from app.services.lot_service import LotService
from app.services.market_service import MarketService
from app.services.matching_service import MatchingService
from app.services.order_service import OrderService

logger = get_logger(__name__)

DISCLAIMER = (
    "KisanSaathi's assistant gives informational guidance based on platform and "
    "mandi data. It is not financial, legal or agronomic advice, prices are not "
    "guaranteed, and you should verify anything that matters before you act."
)

SUGGESTIONS: dict[str, list[str]] = {
    "price": [
        "What is my best market to sell in?",
        "Is the price rising this week?",
        "How much storage cost should I expect?",
    ],
    "demand": [
        "Who is buying my crop right now?",
        "Show me matching buyer demands",
        "What quantity is demanded vs listed?",
    ],
    "logistics": [
        "Who can transport my lot?",
        "What will delivery cost me?",
    ],
    "orders": [
        "What are my open orders?",
        "What is the next step on my order?",
    ],
    "quality": [
        "Which grade will my produce fetch?",
        "What moisture is acceptable?",
    ],
    "general": [
        "What is a fair price for my crop?",
        "Show my recent lots",
        "How do payments work?",
    ],
}

# Cheap keyword routing - deliberately transparent and inspectable.
INTENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("logistics", ("transport", "truck", "tempo", "pickup", "delivery cost", "vehicle", "carrier")),
    ("orders", ("order", "shipment", "delivered", "payment pending", "status of my")),
    ("quality", ("grade", "quality", "moisture", "damaged", "a grade", "b grade", "c grade")),
    ("demand", ("demand", "buyer", "who wants", "requirement", "interested", "match")),
    ("price", ("price", "rate", "mandi", "sell", "market", "worth", " profitable", "profit")),
)


def _matches_intent(message: str) -> str:
    text = message.lower()
    for intent, keywords in INTENT_PATTERNS:
        if any(keyword in text for keyword in keywords):
            return intent
    return "general"


# --------------------------------------------------------------------- LLM
class ChatCompletionClient(Protocol):
    """Minimal chat-completion interface so the client is swappable in tests."""

    def complete(
        self, *, system: str, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> tuple[str, dict[str, int]]: ...


class NvidiaChatClient:
    """OpenAI-compatible chat client for NVIDIA NIM endpoints."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=settings.NVIDIA_BASE_URL,
            timeout=settings.NVIDIA_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {settings.NVIDIA_API_KEY}"},
        )

    def complete(
        self, *, system: str, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> tuple[str, dict[str, int]]:
        last_error: Exception | None = None
        for attempt in range(settings.NVIDIA_MAX_RETRIES + 1):
            try:
                response = self._client.post(
                    "/chat/completions",
                    json={
                        "model": settings.NVIDIA_MODEL,
                        "messages": [{"role": "system", "content": system}, *messages],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                usage = body.get("usage", {}) or {}
                return content.strip(), {
                    "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                    "completion_tokens": int(usage.get("completion_tokens", 0)),
                }
            except Exception as exc:  # network/HTTP/JSON - all retryable
                last_error = exc
                if attempt < settings.NVIDIA_MAX_RETRIES:
                    time.sleep(0.4 * (2**attempt))
        raise RuntimeError(f"NVIDIA chat completion failed: {last_error}")

    def close(self) -> None:
        self._client.close()


# ------------------------------------------------------------------ service
class AssistantService:
    """Grounded Q&A over the caller's own platform data."""

    def __init__(
        self,
        session: Session,
        *,
        client: ChatCompletionClient | None = None,
    ) -> None:
        self.session = session
        self.conversations = ConversationRepository(AIConversation, session)
        self.messages = MessageRepository(AIMessage, session)
        self.recommendations = RecommendationRepository(AIRecommendation, session)
        self._client = client
        if self._client is None and settings.ai_enabled:
            self._client = NvidiaChatClient()

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _mode_for(user: User) -> AIConversationMode:
        return {
            UserRole.FARMER: AIConversationMode.FARMER_ASSISTANT,
            UserRole.FPO: AIConversationMode.FPO_ASSISTANT,
            UserRole.BUYER: AIConversationMode.BUYER_ASSISTANT,
            UserRole.ADMIN: AIConversationMode.ADMIN_ANALYST,
        }.get(user.role, AIConversationMode.FARMER_ASSISTANT)

    def _origin(self, user: User) -> tuple[str | None, float | None, float | None]:
        """Return (district, latitude, longitude) for the caller."""
        district = user.district
        latitude = longitude = None
        profile = user.farmer_profile or user.fpo_profile or user.buyer_profile
        if profile is not None:
            latitude = getattr(profile, "latitude", None)
            longitude = getattr(profile, "longitude", None)
            district = district or getattr(profile, "district", None)
        return district, latitude, longitude

    def _primary_commodity(self, user: User) -> Any | None:
        """Best guess at the crop this user cares about, for grounding answers."""
        lots = LotService(self.session).list_lots(seller_user_id=user.id, page=1, page_size=1)[0]
        if lots:
            return lots[0].commodity
        return None

    # --------------------------------------------------------------- tools
    def _tool_price(self, user: User, request: AIChatRequest) -> dict[str, Any] | None:
        commodity = self._primary_commodity(user)
        if request.commodity_id is not None:
            commodity = MarketService(self.session).get_commodity(request.commodity_id)
        if commodity is None:
            return None
        district, latitude, longitude = self._origin(user)
        market = MarketService(self.session)
        snapshot = market.price_snapshot(
            commodity.id,
            district=district or request.context_district,
            origin_latitude=latitude,
            origin_longitude=longitude,
        )
        trend = market.trend(commodity.id, days=7, district=district)
        return {
            "tool": "market_prices",
            "commodity": commodity.name,
            "unit": commodity.default_unit,
            "modal_price": snapshot.get("modal_price"),
            "price_range": [snapshot.get("min_price"), snapshot.get("max_price")],
            "district": district,
            "trend_change_pct_7d": trend.overall_change_pct,
            "trend_direction": "rising"
            if (trend.overall_change_pct or 0) > 0
            else "falling"
            if (trend.overall_change_pct or 0) < 0
            else "stable",
            "as_of": str(snapshot.get("price_date") or datetime.now(UTC).date()),
            "top_markets": [
                {
                    "market": m["market_name"],
                    "district": m["district"],
                    "modal_price": m["modal_price"],
                    "distance_km": m.get("distance_km"),
                }
                for m in snapshot.get("markets", [])[:3]
            ],
        }

    def _tool_demand(self, user: User, request: AIChatRequest) -> dict[str, Any] | None:
        matches = MatchingService(self.session).matches_for_user(
            user.id, role=user.role.value, commodity_id=request.commodity_id, limit=5
        )
        direction = "buyer" if user.role is UserRole.BUYER else "seller"
        summary = MatchingService(self.session).summary(matches)
        return {
            "tool": "matching",
            "direction": direction,
            "match_count": len(matches),
            "strong_matches": summary.get("strong_matches"),
            "top_matches": [
                {
                    "title": m.title,
                    "score": m.score,
                    "score_label": m.score_label,
                    "quantity": m.quantity,
                    "unit": m.unit,
                    "district": m.district,
                    "price_range": m.price_range,
                }
                for m in matches[:3]
            ],
        }

    def _tool_orders(self, user: User) -> dict[str, Any] | None:
        orders = OrderService(self.session).list_orders(user=user, page=1, page_size=5)[0]
        if not orders:
            return {"tool": "orders", "orders": [], "message": "You have no orders yet."}
        return {
            "tool": "orders",
            "order_count": len(orders),
            "orders": [
                {
                    "order_number": o.order_number,
                    "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                    "commodity": o.commodity.name if o.commodity else None,
                    "quantity": o.quantity,
                    "unit": o.unit,
                    "total_value": o.total_value,
                }
                for o in orders
            ],
        }

    def _tool_quality(self, user: User, request: AIChatRequest) -> dict[str, Any] | None:
        commodity = (
            MarketService(self.session).get_commodity(request.commodity_id)
            if request.commodity_id
            else self._primary_commodity(user)
        )
        if commodity is None:
            return None
        from app.services.quality_service import QualityService

        attributes = QualityService(self.session).definitions_for_commodity(commodity.id)
        if not attributes:
            return None
        return {
            "tool": "quality_standards",
            "commodity": commodity.name,
            "attributes": [
                {
                    "label": a.label,
                    "unit": a.unit,
                    "grade_a_min": a.grade_a_min,
                    "grade_b_min": a.grade_b_min,
                    "max_value": a.max_value,
                }
                for a in attributes[:8]
            ],
        }

    def _tool_logistics(self, user: User, request: AIChatRequest) -> dict[str, Any] | None:
        from app.services.logistics_service import LogisticsService

        district, _, _ = self._origin(user)
        if not district:
            return None
        quantity = 50.0
        options = LogisticsService(self.session).quote_options(
            origin_district=district,
            destination_district=request.context_district or district,
            quantity=quantity,
        )
        return {
            "tool": "logistics_quotes",
            "origin_district": district,
            "quantity_quintal": quantity,
            "options": [
                {
                    "provider": o.provider_name,
                    "vehicle": o.vehicle_type.value
                    if hasattr(o.vehicle_type, "value")
                    else o.vehicle_type,
                    "cost": o.estimated_cost,
                    "transit_days": o.transit_days,
                    "rating": o.rating,
                }
                for o in options[:3]
            ],
        }

    def _run_tool(self, intent: str, user: User, request: AIChatRequest) -> dict[str, Any] | None:
        try:
            if intent == "price":
                return self._tool_price(user, request)
            if intent == "demand":
                return self._tool_demand(user, request)
            if intent == "orders":
                return self._tool_orders(user)
            if intent == "quality":
                return self._tool_quality(user, request)
            if intent == "logistics":
                return self._tool_logistics(user, request)
        except Exception as exc:  # a tool failure must not break the chat
            logger.warning("assistant.tool.failed", intent=intent, error=str(exc))
        return None

    # ------------------------------------------------------------- answers
    @staticmethod
    def _format_tool_answer(intent: str, tool: dict[str, Any]) -> str:
        """Render grounded facts as a readable, source-free answer."""
        name = tool.get("tool")
        if name == "market_prices":
            modal = tool.get("modal_price")
            low, high = tool.get("price_range", [None, None])
            change = tool.get("trend_change_pct_7d")
            direction = tool.get("trend_direction", "stable")
            if modal is None:
                return (
                    f"No mandi price is recorded for {tool.get('commodity')} yet. Once the "
                    "market feed runs, I can suggest a fair range."
                )
            lines = [
                f"{tool.get('commodity')} is trading around {float(modal):,.0f} per "
                f"{tool.get('unit', 'quintal')} as of {tool.get('as_of')}"
            ]
            if low is not None and high is not None:
                lines[0] += f", ranging {float(low):,.0f}-{float(high):,.0f}"
            lines[0] += "."
            if change is not None:
                lines.append(
                    f"That is {abs(float(change)):.1f}% {'up' if change > 0 else 'down'} "
                    f"over the last 7 days, so the trend is {direction}."
                )
            best = (tool.get("top_markets") or [None])[0]
            if best:
                distance = best.get("distance_km")
                where = f" ({distance:,.0f} km away)" if distance else ""
                lines.append(
                    f"The best rate in the feed is {best['market']} in {best['district']}"
                    f"{where} at {float(best['modal_price']):,.0f}."
                )
            return " ".join(lines)
        if name == "matching":
            count = tool.get("match_count", 0)
            if not count:
                return (
                    "I could not find open buyer requirements matching your current "
                    "listings. Publishing a lot with a clear grade and price usually "
                    "attracts the first offer."
                )
            lines = [
                f"I found {count} matching requirement(s), "
                f"{tool.get('strong_matches') or 0} of them strong matches."
            ]
            for match in tool.get("top_matches", []):
                prices = match.get("price_range")
                price_text = ""
                if prices and prices[0] is not None:
                    price_text = f" at {float(prices[0]):,.0f}-{float(prices[1]):,.0f}"
                lines.append(
                    f"- {match['title']}: {match['score_label']} match "
                    f"({match['score']:.0f}/100), {match['quantity']:,.0f} "
                    f"{match.get('unit') or 'quintal'}{price_text}"
                    + (f", {match['district']}" if match.get("district") else "")
                    + "."
                )
            return " ".join(lines)
        if name == "orders":
            if not tool.get("orders"):
                return "You have no orders yet. Accept an offer to create the first one."
            lines = [f"You have {len(tool['orders'])} recent order(s):"]
            for order in tool["orders"]:
                lines.append(
                    f"- {order['order_number']}: {order['status']} - "
                    f"{order['quantity']:,.0f} {order.get('unit') or 'quintal'} of "
                    f"{order.get('commodity') or 'produce'} worth "
                    f"{float(order.get('total_value') or 0):,.0f}."
                )
            return " ".join(lines)
        if name == "quality_standards":
            lines = [f"Published grading bands for {tool.get('commodity')}:"]
            for attribute in tool.get("attributes", []):
                bands = []
                if attribute.get("grade_a_min") is not None:
                    bands.append(f"Grade A from {float(attribute['grade_a_min']):,.2f}")
                if attribute.get("grade_b_min") is not None:
                    bands.append(f"Grade B from {float(attribute['grade_b_min']):,.2f}")
                if bands and attribute.get("unit"):
                    lines.append(
                        f"- {attribute['label']} ({attribute['unit']}): " + ", ".join(bands) + "."
                    )
            return (
                " ".join(lines)
                if len(lines) > 1
                else ("No published grading bands exist for this commodity yet.")
            )
        if name == "logistics_quotes":
            if not tool.get("options"):
                return "I could not find a transport quote for that route right now."
            lines = [f"Indicative quotes from {tool['origin_district']} for 50 quintal:"]
            for option in tool["options"]:
                lines.append(
                    f"- {option['provider']} ({option['vehicle']}): "
                    f"{float(option['cost']):,.0f}, {option['transit_days']} day(s), "
                    f"rated {option['rating']:.1f}."
                )
            return " ".join(lines)
        return "I gathered the relevant data but could not summarise it clearly."

    @staticmethod
    def _general_answer(user: User) -> str:
        first_name = (user.full_name or "").split(" ")[0] or "there"
        return (
            f"Hello {first_name}. I can help with your own data on KisanSaathi: what your "
            "crop is trading at today, which buyer requirements match your lots, where "
            "your orders stand, what quality grade your produce qualifies for, and what "
            "transport would cost. Try one of the questions below, or ask in your own words."
        )

    # ---------------------------------------------------------------- chat
    def chat(self, user: User, request: AIChatRequest) -> AIChatResponse:
        intent = _matches_intent(request.message)
        tool = self._run_tool(intent, user, request)
        suggestions = SUGGESTIONS.get(intent or "general", SUGGESTIONS["general"])

        conversation = self._resolve_conversation(user, request)
        user_message = AIMessage(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=request.message,
        )
        self.session.add(user_message)

        if tool is not None:
            fallback_answer = self._format_tool_answer(intent, tool)
        else:
            fallback_answer = self._general_answer(user)

        answer, usage, provider, model, is_fallback, latency = self._compose(
            user, request, intent, tool, fallback_answer
        )

        assistant_message = AIMessage(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=answer,
            tool_name=tool.get("tool") if tool else None,
            tool_arguments={"intent": intent},
            tool_result_summary=_summarise_tool_result(tool),
            provider=provider,
            model=model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency,
        )
        self.session.add(assistant_message)

        conversation.total_messages += 2
        conversation.last_message_at = datetime.now(UTC)
        if conversation.title == "New conversation":
            conversation.title = request.message.strip()[:80] + (
                "..." if len(request.message) > 80 else ""
            )
        self.session.commit()

        return AIChatResponse(
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            answer=answer,
            provider=provider or "deterministic",
            model=model,
            is_fallback=is_fallback,
            suggestions=suggestions,
            data_cards=self._data_cards(tool),
            tools_used=[tool["tool"]] if tool else [],
            disclaimer=DISCLAIMER,
            created_at=assistant_message.created_at,
        )

    def _compose(
        self,
        user: User,
        request: AIChatRequest,
        intent: str,
        tool: dict[str, Any] | None,
        fallback_answer: str,
    ) -> tuple[str, dict[str, int], str | None, str | None, bool, int]:
        """Return (answer, usage, provider, model, is_fallback, latency_ms)."""
        if self._client is None:
            return fallback_answer, {}, None, None, True, 0

        started = time.perf_counter()
        try:
            facts = json.dumps(tool, default=str) if tool else "No platform data matched."
            system = (
                "You are the KisanSaathi assistant, helping Indian farmers, FPOs and "
                "agri buyers trade on a produce marketplace. Answer ONLY from the DATA "
                "block below - never invent a price, quantity, buyer name or date. If "
                "the data does not answer the question, say so plainly and suggest what "
                "the user could do next. Be concise (3-6 sentences), practical, and use "
                "plain language with ₹ for rupees. Never give legal, financial or "
                "agronomic advice, and never guarantee a price. Always close by noting "
                "the user should verify details before trading."
            )
            messages = [
                {"role": "user", "content": f"QUESTION: {request.message}\n\nDATA:\n{facts}"}
            ]
            answer, usage = self._client.complete(
                system=system,
                messages=messages,
                temperature=settings.AI_TEMPERATURE,
                max_tokens=settings.AI_MAX_TOKENS,
            )
        except Exception as exc:
            logger.warning("assistant.llm.failed", error=str(exc))
            return (
                fallback_answer,
                {},
                None,
                None,
                True,
                int((time.perf_counter() - started) * 1000),
            )
        latency = int((time.perf_counter() - started) * 1000)
        return answer, usage, settings.AI_PROVIDER, settings.NVIDIA_MODEL, False, latency

    def _resolve_conversation(self, user: User, request: AIChatRequest) -> AIConversation:
        if request.conversation_id is not None:
            existing = self.conversations.owned_by(request.conversation_id, user.id)
            if existing is None:
                raise NotFoundError("Conversation not found.")
            return existing
        conversation = AIConversation(
            user_id=user.id,
            title="New conversation",
            mode=self._mode_for(user),
            language=request.language,
        )
        self.session.add(conversation)
        self.session.flush()
        return conversation

    @staticmethod
    def _data_cards(tool: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Structured cards the frontend can render next to the prose answer."""
        if not tool:
            return []
        name = tool.get("tool")
        if name == "market_prices":
            return [
                {
                    "kind": "price",
                    "title": f"{tool.get('commodity')} modal price",
                    "value": tool.get("modal_price"),
                    "unit": tool.get("unit"),
                    "trend_pct": tool.get("trend_change_pct_7d"),
                    "as_of": tool.get("as_of"),
                }
            ]
        if name == "matching":
            return [
                {
                    "kind": "match",
                    "title": match["title"],
                    "score": match["score"],
                    "score_label": match["score_label"],
                    "quantity": match["quantity"],
                    "unit": match.get("unit"),
                }
                for match in tool.get("top_matches", [])
            ]
        return []

    # ------------------------------------------------------------ history
    def list_conversations(self, user: User, *, limit: int = 20) -> list[AIConversationOut]:
        conversations = self.conversations.for_user(user.id, limit=limit)
        return [
            AIConversationOut(
                id=c.id,
                user_id=c.user_id,
                title=c.title,
                mode=c.mode,
                total_messages=c.total_messages,
                last_message_at=c.last_message_at,
                created_at=c.created_at,
            )
            for c in conversations
        ]

    def get_conversation(self, user: User, conversation_id: uuid.UUID) -> AIConversationOut:
        conversation = self.conversations.owned_by(conversation_id, user.id)
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        return _conversation_out(conversation, self.messages.recent(conversation.id, limit=200))

    def delete_conversation(self, user: User, conversation_id: uuid.UUID) -> None:
        conversation = self.conversations.owned_by(conversation_id, user.id)
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        self.session.delete(conversation)
        self.session.commit()

    def recent_recommendations(
        self, user: User, *, kind: str | None = None
    ) -> list[AIRecommendation]:
        return self.recommendations.for_user(user.id, kind=kind)


def _conversation_out(conversation: AIConversation, messages: list[AIMessage]) -> AIConversationOut:
    return AIConversationOut(
        id=conversation.id,
        user_id=conversation.user_id,
        title=conversation.title,
        mode=conversation.mode,
        total_messages=conversation.total_messages,
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        messages=[
            AIMessageOut(
                id=m.id,
                role=m.role.value if hasattr(m.role, "value") else str(m.role),
                content=m.content,
                tool_name=m.tool_name,
                data=m.tool_result_summary,
                provider=m.provider,
                model=m.model,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


def _summarise_tool_result(tool: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep a compact, non-sensitive trace of the facts an answer was built on."""
    if not tool:
        return None
    return {"tool": tool.get("tool"), "intent": tool.get("direction") or tool.get("tool")}
