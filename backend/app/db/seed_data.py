"""Reference data for the catalogue.

Separated from the seeder itself so the commodity, market and quality-attribute
lists can be reviewed as data rather than as a wall of constructor calls. Codes
are stable: they are the join key for any price history already collected, so a
commodity's ``code`` must not change once it has been traded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import MarketType


@dataclass(frozen=True)
class AttributeSeed:
    """One quality parameter for a commodity.

    ``higher_is_better`` matters: the grading helper reads ``grade_a_min`` and
    ``grade_b_min`` as "at or above", so a parameter like rot percentage or
    moisture must carry an ideal band and *no* grade thresholds. Setting them
    anyway would grade the worst onions as Grade A.
    """

    code: str
    label: str
    unit: str
    ideal_min: float
    ideal_max: float
    higher_is_better: bool
    grade_a_min: float | None = None
    grade_b_min: float | None = None


@dataclass(frozen=True)
class CommoditySeed:
    code: str
    name: str
    name_marathi: str
    category: str
    shelf_life_days: int | None
    seasonality_note: str
    description: str
    min_price_floor: float | None = None
    attributes: tuple[AttributeSeed, ...] = field(default_factory=tuple)


COMMODITIES: tuple[CommoditySeed, ...] = (
    CommoditySeed(
        code="ONION",
        name="Onion",
        name_marathi="कांदा",
        category="Vegetables",
        shelf_life_days=45,
        seasonality_note="Peak arrivals Oct-Jan; prices soften with heavy arrivals.",
        description="Red and yellow onion, graded by size and skin tightness.",
        min_price_floor=800.0,
        attributes=(
            AttributeSeed("SIZE", "Bulb diameter", "mm", 40.0, 75.0, True, 60.0, 45.0),
            AttributeSeed("MOISTURE", "Moisture content", "%", 8.0, 14.0, False),
            AttributeSeed("ROTTEN", "Rotten bulbs", "%", 0.0, 3.0, False),
        ),
    ),
    CommoditySeed(
        code="TOMATO",
        name="Tomato",
        name_marathi="टोमॅटो",
        category="Vegetables",
        shelf_life_days=7,
        seasonality_note="Highly perishable; price can halve in a week in peak season.",
        description="Vine-ripened and firm hybrids for retail and processing.",
        min_price_floor=600.0,
        attributes=(
            AttributeSeed("SIZE", "Fruit diameter", "mm", 35.0, 70.0, True, 55.0, 45.0),
            AttributeSeed("RIPENESS", "Ripeness grade", "grade", 3.0, 5.0, True, 4.0, 3.0),
            AttributeSeed("MOISTURE", "Moisture content", "%", 85.0, 95.0, False),
        ),
    ),
    CommoditySeed(
        code="SOYBEAN",
        name="Soybean",
        name_marathi="सोयाबीन",
        category="Pulses & Oilseeds",
        shelf_life_days=270,
        seasonality_note="Kharif crop; arrivals peak Oct-Nov, storage is easy.",
        description="Non-GMO and organic-certified lots are tracked separately.",
        min_price_floor=3500.0,
        attributes=(
            AttributeSeed("MOISTURE", "Moisture content", "%", 8.0, 12.0, False),
            AttributeSeed("OIL", "Oil content", "%", 16.0, 22.0, True, 19.0, 17.0),
            AttributeSeed("IMPURITY", "Impurity", "%", 0.0, 3.0, False),
        ),
    ),
    CommoditySeed(
        code="WHEAT",
        name="Wheat",
        name_marathi="गहू",
        category="Cereals",
        shelf_life_days=365,
        seasonality_note="Rabi crop; procurement demand keeps prices firm Mar-May.",
        description="Sharbati and Lokwan varieties for milling and atta.",
        min_price_floor=1800.0,
        attributes=(
            AttributeSeed("MOISTURE", "Moisture content", "%", 8.0, 13.0, False),
            AttributeSeed("HEAVY_GRAIN", "Heavy grain", "%", 0.0, 5.0, False),
            AttributeSeed("IMPURITY", "Impurity", "%", 0.0, 3.0, False),
        ),
    ),
    CommoditySeed(
        code="PADDY",
        name="Paddy (Rice)",
        name_marathi="भात",
        category="Cereals",
        shelf_life_days=270,
        seasonality_note="Harvest Nov-Jan; mills buy heavily right after arrival.",
        description="Common and fine varieties, mostly for processing.",
        min_price_floor=1500.0,
        attributes=(
            AttributeSeed("MOISTURE", "Moisture content", "%", 12.0, 18.0, False),
            AttributeSeed("ADVANCE", "Advance given", "days", 0.0, 500.0, False),
            AttributeSeed("IMPURITY", "Impurity", "%", 0.0, 4.0, False),
        ),
    ),
    CommoditySeed(
        code="TURMERIC",
        name="Turmeric",
        name_marathi="हळद",
        category="Spices",
        shelf_life_days=365,
        seasonality_note="Curry leaf / Salem varieties; export demand is seasonal.",
        description="Polished and unpolished fingers with curcumin content noted.",
        min_price_floor=7000.0,
        attributes=(
            AttributeSeed("MOISTURE", "Moisture content", "%", 8.0, 14.0, False),
            AttributeSeed("CURCUMIN", "Curcumin", "%", 2.0, 6.0, True, 4.0, 3.0),
        ),
    ),
    CommoditySeed(
        code="GARLIC",
        name="Garlic",
        name_marathi="कांद्याचा वाजारा",
        category="Vegetables",
        shelf_life_days=120,
        seasonality_note="Stored well; prices often lag onion in the same season.",
        description="Big and medium bulbs for retail and processing.",
        min_price_floor=3500.0,
        attributes=(
            AttributeSeed("MOISTURE", "Moisture content", "%", 8.0, 14.0, False),
            AttributeSeed("SIZE", "Bulb diameter", "mm", 35.0, 65.0, True, 50.0, 42.0),
        ),
    ),
    CommoditySeed(
        code="SUGARCANE",
        name="Sugarcane",
        name_marathi="ऊस",
        category="Cash Crops",
        shelf_life_days=5,
        seasonality_note="Harvest Nov-Mar; mills set rates per cutting.",
        description="Sold to mills by weight; freight distance drives the price.",
        min_price_floor=260.0,
        attributes=(
            AttributeSeed("RECOVERABLE", "Sugar recovery", "%", 8.0, 12.0, True, 10.5, 9.5),
            AttributeSeed("FIBRE", "Fibre content", "%", 12.0, 16.0, True, 14.0, 13.0),
        ),
    ),
    CommoditySeed(
        code="CHILLI",
        name="Chilli",
        name_marathi="मिरची",
        category="Spices",
        shelf_life_days=180,
        seasonality_note="Guntur and Byadgi varieties; export demand moves the market.",
        description="Dry chilli with stalk and cleanliness graded separately.",
        min_price_floor=8000.0,
        attributes=(
            AttributeSeed("MOISTURE", "Moisture content", "%", 8.0, 12.0, False),
            AttributeSeed(
                "CUPS_PER_KG",
                "Capsaicin cups per kg",
                "count",
                8000.0,
                40000.0,
                True,
                30000.0,
                18000.0,
            ),
        ),
    ),
    CommoditySeed(
        code="COTTON",
        name="Cotton",
        name_marathi="कापूस",
        category="Cash Crops",
        shelf_life_days=365,
        seasonality_note="Kharif arrival Oct-Dec; ginning mill demand sets the staple.",
        description="Medium and long staple, gin ratio recorded per lot.",
        min_price_floor=6000.0,
        attributes=(
            AttributeSeed("STAPLE", "Staple length", "mm", 24.0, 32.0, True, 29.0, 26.0),
            AttributeSeed("GIN_OUT", "Gin out turn", "%", 55.0, 65.0, True, 62.0, 58.0),
            AttributeSeed("MOISTURE", "Moisture content", "%", 5.0, 9.0, False),
        ),
    ),
)


@dataclass(frozen=True)
class MarketSeed:
    code: str
    name: str
    market_type: MarketType
    district: str
    taluka: str | None
    latitude: float
    longitude: float
    apmc_number: str | None = None
    has_storage: bool = True
    trading_hours: str = "07:00-14:00"


MARKETS: tuple[MarketSeed, ...] = (
    MarketSeed(
        code="PUNE-MARKET",
        name="Pune Market Yard",
        market_type=MarketType.APMC_MANDI,
        district="Pune",
        taluka="Haveli",
        latitude=18.5314,
        longitude=73.8567,
        apmc_number="MH-18-APMC-001",
    ),
    MarketSeed(
        code="PUNE-GIRDA",
        name="Girda Market Yard",
        market_type=MarketType.APMC_MANDI,
        district="Pune",
        taluka="Haveli",
        latitude=18.4479,
        longitude=73.8688,
        apmc_number="MH-18-APMC-002",
    ),
    MarketSeed(
        code="SOLAPUR-APMC",
        name="Solapur APMC",
        market_type=MarketType.APMC_MANDI,
        district="Solapur",
        taluka="Solapur",
        latitude=17.6599,
        longitude=75.9064,
        apmc_number="MH-13-APMC-001",
    ),
    MarketSeed(
        code="NASHIK-APMC",
        name="Nashik APMC",
        market_type=MarketType.APMC_MANDI,
        district="Nashik",
        taluka="Nashik",
        latitude=19.9975,
        longitude=73.7898,
        apmc_number="MH-15-APMC-001",
    ),
    MarketSeed(
        code="NAGPUR-APMC",
        name="Nagpur APMC",
        market_type=MarketType.APMC_MANDI,
        district="Nagpur",
        taluka="Nagpur",
        latitude=21.1458,
        longitude=79.0882,
        apmc_number="MH-22-APMC-001",
    ),
    MarketSeed(
        code="KOLHAPUR-FG",
        name="Kolhapur Farm Gate",
        market_type=MarketType.FARM_GATE,
        district="Kolhapur",
        taluka="Panhala",
        latitude=16.7050,
        longitude=74.2433,
    ),
    MarketSeed(
        code="AHMEDNAGAR-CC",
        name="Ahmednagar Collection Centre",
        market_type=MarketType.COLLECTION_CENTRE,
        district="Ahmednagar",
        taluka="Sangamner",
        latitude=19.0948,
        longitude=74.7480,
    ),
    MarketSeed(
        code="NASHIK-ORGANIC",
        name="Nashik Organic Hub",
        market_type=MarketType.ORGANIC_MANDI,
        district="Nashik",
        taluka="Niphad",
        latitude=20.0499,
        longitude=73.7833,
    ),
    MarketSeed(
        code="PUNE-HUB",
        name="Pune Private Hub",
        market_type=MarketType.PRIVATE_HUB,
        district="Pune",
        taluka="Baramati",
        latitude=18.1509,
        longitude=74.1184,
        has_storage=True,
    ),
)
