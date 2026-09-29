"""Geographic helpers (haversine distance) - no external geo service required."""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088

# Approximate coordinates for Maharashtra districts, used to backfill demo data
# and to resolve district centroids when a record has no GPS coordinates.
MAHARASHTRA_DISTRICT_COORDS: dict[str, tuple[float, float]] = {
    "Pune": (18.5204, 73.8567),
    "Nashik": (19.9975, 73.7898),
    "Nagpur": (21.1458, 79.0882),
    "Kolhapur": (16.7050, 74.2433),
    "Sangli": (16.8524, 74.5815),
    "Satara": (17.6805, 73.9931),
    "Ahilyanagar": (19.0948, 74.7480),
    "Ahmednagar": (19.0948, 74.7480),
    "Solapur": (17.6599, 75.9064),
    "Chhatrapati Sambhajinagar": (19.8762, 75.3433),
    "Aurangabad": (19.8762, 75.3433),
    "Amravati": (20.9374, 77.7796),
    "Akola": (20.7002, 77.0076),
    "Jalgaon": (21.0077, 75.5626),
    "Dhule": (20.9026, 74.7749),
    "Nanded": (19.1383, 77.3210),
    "Latur": (18.4088, 76.5604),
    "Beed": (18.4983, 77.3791),
    "Jalna": (19.8410, 75.8860),
    "Parbhani": (19.2687, 76.7740),
    "Hingoli": (19.7147, 77.7496),
    "Washim": (20.1067, 77.5411),
    "Buldhana": (20.9911, 76.7494),
    "Yavatmal": (20.3500, 78.1200),
    "Wardha": (20.7480, 78.6200),
    "Bhandara": (21.1670, 79.9450),
    "Gondia": (21.5980, 80.1980),
    "Gadchiroli": (19.5940, 80.8140),
    "Thane": (19.2183, 72.9781),
    "Palghar": (19.4250, 72.8450),
    "Raigad": (18.5200, 73.1200),
    "Ratnagiri": (16.9900, 73.3120),
    "Sindhudurg": (16.0000, 73.7000),
    "Osmanabad (Dharashiv)": (18.5000, 76.2000),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return round(2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a)), 2)


def district_coords(district: str | None) -> tuple[float | None, float | None]:
    if not district:
        return None, None
    return MAHARASHTRA_DISTRICT_COORDS.get(district.strip(), (None, None))


@dataclass(frozen=True)
class DistanceResult:
    km: float | None
    basis: str

    @property
    def is_known(self) -> bool:
        return self.km is not None


def distance_between(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
    district1: str | None = None,
    district2: str | None = None,
) -> DistanceResult:
    """Distance between two points, falling back to district centroids."""
    if None not in (lat1, lon1, lat2, lon2):
        return DistanceResult(haversine_km(lat1 or 0, lon1 or 0, lat2 or 0, lon2 or 0), "gps")
    d1_lat, d1_lon = district_coords(district1)
    d2_lat, d2_lon = district_coords(district2)
    if None not in (d1_lat, d1_lon, d2_lat, d2_lon):
        return DistanceResult(
            haversine_km(d1_lat or 0, d1_lon or 0, d2_lat or 0, d2_lon or 0), "district_centroid"
        )
    return DistanceResult(None, "unknown")
