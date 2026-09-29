"""Audit trail service. Every state change on a business entity is recorded."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.core.logging import get_logger
from app.models import AuditLog
from app.repositories.operations import AuditRepository

logger = get_logger(__name__)

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
actor_id_var: ContextVar[uuid.UUID | None] = ContextVar("actor_id", default=None)

SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "upi_id",
    "ifsc_code",
    "bank_account",
    "pan_number",
    "gst_number",
    "document_url",
    "token",
    "refresh_token",
    "access_token",
}


def _sanitise(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Never write secrets or financial identifiers into the audit log."""
    if payload is None:
        return None
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if key in SENSITIVE_KEYS:
            clean[key] = "***redacted***"
        elif isinstance(value, uuid.UUID):
            clean[key] = str(value)
        elif hasattr(value, "isoformat"):
            clean[key] = value.isoformat()
        else:
            clean[key] = value
    return clean


class AuditService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = AuditRepository(AuditLog, session)

    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID | str | None = None,
        actor_user_id: uuid.UUID | None = None,
        actor_role: UserRole | str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        note: str | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        try:
            # SAVEPOINT so a failed audit insert never rolls back business data.
            with self.session.begin_nested():
                self.repo.create(
                    action=action,
                    entity_type=entity_type,
                    entity_id=str(entity_id) if entity_id is not None else None,
                    actor_user_id=actor_user_id or actor_id_var.get(),
                    actor_role=str(actor_role) if actor_role else None,
                    before_state=_sanitise(before),
                    after_state=_sanitise(after),
                    note=note,
                    request_id=request_id or request_id_var.get(),
                    ip_address=ip_address,
                )
                self.session.flush()
        except Exception as exc:  # audit failures must never break the request
            logger.warning("audit.record.failed", error=str(exc), action=action)


__all__ = ["AuditService", "actor_id_var", "request_id_var"]
