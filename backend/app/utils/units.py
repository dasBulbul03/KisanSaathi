"""Domain unit conversion helpers.

The platform stores prices per quintal (100 kg) which is the unit used by
Maharashtra APMC mandi boards. Quantities may be entered by users in quintal,
tonne or kg, so every price/quantity comparison happens after conversion.
"""

from __future__ import annotations

QUINTAL_TO_KG = 100.0
TONNE_TO_KG = 1000.0

WEIGHT_UNITS = {"kg", "quintal", "tonne", "tonnes", "t"}


def normalise_unit(unit: str) -> str:
    u = (unit or "quintal").strip().lower()
    return "tonne" if u in ("tonnes", "t", "ton") else u


def to_kg(quantity: float, unit: str) -> float:
    u = normalise_unit(unit)
    if u == "kg":
        return quantity
    if u == "quintal":
        return quantity * QUINTAL_TO_KG
    if u == "tonne":
        return quantity * TONNE_TO_KG
    raise ValueError(f"Unsupported unit: {unit}")


def from_kg(kg: float, unit: str) -> float:
    u = normalise_unit(unit)
    if u == "kg":
        return kg
    if u == "quintal":
        return kg / QUINTAL_TO_KG
    if u == "tonne":
        return kg / TONNE_TO_KG
    raise ValueError(f"Unsupported unit: {unit}")


def convert_quantity(quantity: float, from_unit: str, to_unit: str) -> float:
    return from_kg(to_kg(quantity, from_unit), to_unit)


def price_to_unit(price: float, from_unit: str, to_unit: str) -> float:
    """Convert a price expressed per ``from_unit`` into a price per ``to_unit``."""
    ratio = convert_quantity(1.0, to_unit, from_unit)
    return price * ratio


def format_inr(value: float | None, unit: str | None = None) -> str:
    if value is None:
        return "-"
    symbol = "₹"
    formatted = f"{value:,.0f}"
    return f"{symbol}{formatted} / {unit}" if unit else f"{symbol}{formatted}"
