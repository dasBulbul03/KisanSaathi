"""Human readable reference code generation."""

from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime

_ALPHABET = string.ascii_uppercase + string.digits


def _token(length: int = 6) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def today_prefix() -> str:
    return datetime.now(UTC).strftime("%y%m%d")


def lot_code() -> str:
    return f"LOT{today_prefix()}{_token(5)}"


def demand_code() -> str:
    return f"DEM{today_prefix()}{_token(5)}"


def offer_code() -> str:
    return f"OFF{today_prefix()}{_token(5)}"


def order_number() -> str:
    return f"ORD{today_prefix()}{_token(6)}"


def transaction_reference() -> str:
    return f"TXN{today_prefix()}{_token(6)}"


def logistics_reference() -> str:
    return f"LOG{today_prefix()}{_token(5)}"


def grievance_ticket() -> str:
    return f"GRV{today_prefix()}{_token(5)}"


def farmer_id_code() -> str:
    return f"MH-FMR-{_token(8)}"
