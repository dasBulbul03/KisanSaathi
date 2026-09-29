"""Populate a database with everything the app needs to be demonstrable.

Run it as a module from ``backend/``::

    python -m app.db.seed              # reference data + demo accounts
    python -m app.db.seed --no-demo    # reference data only, no accounts
    python -m app.db.seed --reset      # drop and rebuild first (destructive)

Design notes:

* **Idempotent.** Every step upserts on a natural key, so re-running is safe and
  is the supported way to pick up a new release's reference data.
* **Money is never moved.** Payments are recorded as obligations only; see
  ``docs/ai.md`` for the boundary this project keeps around automation.
* **Roles come from ``core.rbac``.** The permission matrix in code is the single
  source of truth, and the seeder copies it into the ``roles`` table rather than
  restating it.
* **Demo data is clearly marked.** Market prices, lots, offers and orders carry
  ``is_demo`` / synthetic sources so the frontend can label them and a real
  deployment can exclude them.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import (
    BuyerType,
    OrderStatus,
    QualityGrade,
    StorageType,
    UserRole,
)
from app.core.logging import get_logger
from app.core.rbac import ROLE_DESCRIPTIONS, ROLE_PERMISSIONS
from app.db.seed_data import COMMODITIES, MARKETS
from app.db.session import get_engine, session_scope
from app.models import (
    BuyerDemand,
    Commodity,
    FarmLot,
    Market,
    Order,
    QualityAttribute,
    Role,
    StorageFacility,
    User,
)
from app.schemas.trade import (
    BuyerDemandCreate,
    FarmLotCreate,
    OfferCreate,
    OrderStatusUpdate,
)
from app.schemas.user import RegisterRequest, StaffUserCreate
from app.services.auth_service import AdminUserService, AuthService
from app.services.demand_service import DemandService
from app.services.lot_service import LotService
from app.services.market_sync_service import MarketDataSyncService
from app.services.offer_service import OfferService
from app.services.order_service import OrderService

logger = get_logger(__name__)

#: Accounts the demo always needs. Passwords satisfy the strength policy.
DEMO_PASSWORD = "Demo@1234"
DEMO_ACCOUNTS: tuple[dict[str, Any], ...] = (
    {
        "full_name": "Platform Admin",
        "phone": "9000000001",
        "role": UserRole.ADMIN,
        "district": "Pune",
        "staff": True,
    },
    {
        "full_name": "Ramesh Jadhav",
        "phone": "9000000002",
        "role": UserRole.FARMER,
        "district": "Pune",
        "village": "Shirala",
        "taluka": "Baramati",
        "farm_area_acres": 6.5,
        "primary_crops": ["ONION", "SOYBEAN"],
    },
    {
        "full_name": "Sunita Patil",
        "phone": "9000000003",
        "role": UserRole.FARMER,
        "district": "Solapur",
        "village": "Kadegaon",
        "taluka": "Solapur",
        "farm_area_acres": 4.0,
        "primary_crops": ["TURMERIC", "SOYBEAN"],
    },
    {
        "full_name": "Sahyadri FPO",
        "phone": "9000000004",
        "role": UserRole.FPO,
        "district": "Nashik",
        "organisation_name": "Sahyadri Farmer Producer Organisation",
        "member_count": 145,
        "primary_crops": ["ONION", "TOMATO", "CHILLI"],
    },
    {
        "full_name": "Anita Deshmukh",
        "phone": "9000000005",
        "role": UserRole.BUYER,
        "district": "Pune",
        "organisation_name": "Pune Fresh Retailers Pvt Ltd",
        "buyer_type": BuyerType.RETAILER,
        "gst_number": "27AAACP1234A1Z5",
    },
    {
        "full_name": "BulkMart Sourcing",
        "phone": "9000000006",
        "role": UserRole.BUYER,
        "district": "Mumbai",
        "organisation_name": "BulkMart Sourcing LLP",
        "buyer_type": BuyerType.WHOLESALER,
        "gst_number": "27AACCB9876A1Z2",
    },
    {
        "full_name": "Quality Inspector",
        "phone": "9000000007",
        "role": UserRole.QUALITY_INSPECTOR,
        "district": "Pune",
        "staff": True,
    },
    {
        "full_name": "Sahyadri Logistics",
        "phone": "9000000008",
        "role": UserRole.LOGISTICS_PARTNER,
        "district": "Pune",
        "organisation_name": "Sahyadri Roadlines",
        "staff": True,
    },
)


# --------------------------------------------------------------------- helpers
def _existing(session: Session, model: type, **filters) -> Any | None:
    stmt = select(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return session.execute(stmt).scalars().first()


def _upsert(session: Session, model: type, filters: dict, values: dict) -> tuple[Any, bool]:
    """Fetch by natural key, else create. Returns (row, created)."""
    row = _existing(session, model, **filters)
    if row is None:
        row = model(**filters, **values)
        session.add(row)
        return row, True
    for key, value in values.items():
        setattr(row, key, value)
    return row, False


# ------------------------------------------------------------------ 1. roles
def seed_roles(session: Session) -> int:
    """Copy the in-code permission matrix into the roles table.

    ``ROLE_PERMISSIONS`` in ``core.rbac`` is the single source of truth. Copying
    it here means a permission change needs one edit, not two, and a fresh
    database cannot end up with a different matrix than the running code.
    """
    created = 0
    for role in UserRole:
        display_name, description = ROLE_DESCRIPTIONS.get(role, (role.value.title(), ""))
        existing = _existing(session, Role, name=role)
        permissions = list(ROLE_PERMISSIONS.get(role, []))
        if existing is None:
            session.add(
                Role(
                    name=role,
                    display_name=display_name,
                    description=description,
                    permissions=permissions,
                )
            )
            created += 1
        else:
            existing.display_name = display_name
            existing.description = description
            existing.permissions = permissions
    session.flush()
    logger.info("seed.roles", created=created, total=len(UserRole))
    return created


# ------------------------------------------------- 2. commodities and markets
def seed_catalogue(session: Session) -> tuple[dict[str, Commodity], dict[str, Market]]:
    commodities: dict[str, Commodity] = {}
    for seed in COMMODITIES:
        commodity, _ = _upsert(
            session,
            Commodity,
            {"code": seed.code},
            {
                "name": seed.name,
                "name_marathi": seed.name_marathi,
                "category": seed.category,
                "shelf_life_days": seed.shelf_life_days,
                "seasonality_note": seed.seasonality_note,
                "description": seed.description,
                "min_price_floor": seed.min_price_floor,
                "is_active": True,
            },
        )
        commodities[seed.code] = commodity
        # Flushed per commodity: the quality attributes need commodity.id, and a
        # single flush at the end would leave them unset at insert time.
        session.flush()
        for attribute in seed.attributes:
            _upsert(
                session,
                QualityAttribute,
                {"commodity_id": commodity.id, "code": attribute.code},
                {
                    "label": attribute.label,
                    "unit": attribute.unit,
                    "ideal_min": attribute.ideal_min,
                    "ideal_max": attribute.ideal_max,
                    # Only higher-is-better parameters get grade thresholds; see
                    # AttributeSeed for why setting them the other way is wrong.
                    "grade_a_min": attribute.grade_a_min,
                    "grade_b_min": attribute.grade_b_min,
                    "is_active": True,
                },
            )
    session.flush()

    markets: dict[str, Market] = {}
    for seed in MARKETS:
        market, _ = _upsert(
            session,
            Market,
            {"code": seed.code},
            {
                "name": seed.name,
                "market_type": seed.market_type,
                "district": seed.district,
                "taluka": seed.taluka,
                "state": "Maharashtra",
                "latitude": seed.latitude,
                "longitude": seed.longitude,
                "apmc_number": seed.apmc_number,
                "has_storage": seed.has_storage,
                "has_weighbridge": True,
                "trading_hours": seed.trading_hours,
                "is_active": True,
            },
        )
        markets[seed.code] = market
    session.flush()
    logger.info("seed.catalogue", commodities=len(commodities), markets=len(markets))
    return commodities, markets


# ------------------------------------------------------------- 3. demo users
def seed_accounts(session: Session) -> tuple[dict[str, User], dict[str, User], int]:
    """Create the demo accounts. Returns (by phone, by role, created count).

    Two maps because they answer different questions. By phone identifies an
    account; by role picks the one account that owns the linked demo trade. For
    the role map the **first** account listed for a role wins, so the demo trade
    belongs to the account printed first rather than whichever was seeded last.
    Buyer verification is deliberately left to an admin action so the
    verify-buyer flow stays demonstrable.
    """
    auth = AuthService(session)
    staff_service = AdminUserService(session)
    by_phone: dict[str, User] = {}
    by_role: dict[str, User] = {}
    created = 0

    for spec in DEMO_ACCOUNTS:
        phone = spec["phone"]
        user = _existing(session, User, phone=phone)
        if user is not None:
            by_phone[phone] = user
            by_role.setdefault(spec["role"].value, user)
            continue
        if spec.get("staff"):
            user = staff_service.create_staff_user(
                StaffUserCreate(
                    full_name=spec["full_name"],
                    phone=phone,
                    password=DEMO_PASSWORD,
                    role=spec["role"],
                    district=spec.get("district", "Pune"),
                    organisation_name=spec.get("organisation_name"),
                ),
                # None is the documented bootstrap case for the first admin.
                actor_id=None,
            )
        else:
            user, _ = auth.register(
                RegisterRequest(
                    full_name=spec["full_name"],
                    phone=phone,
                    password=DEMO_PASSWORD,
                    role=spec["role"],
                    district=spec.get("district", "Pune"),
                    village=spec.get("village"),
                    taluka=spec.get("taluka"),
                    farm_area_acres=spec.get("farm_area_acres"),
                    primary_crops=spec.get("primary_crops") or [],
                    organisation_name=spec.get("organisation_name"),
                    buyer_type=spec.get("buyer_type"),
                    gst_number=spec.get("gst_number"),
                    member_count=spec.get("member_count"),
                )
            )
        by_phone[phone] = user
        by_role.setdefault(spec["role"].value, user)
        created += 1
    session.flush()
    logger.info("seed.accounts", created=created, expected=len(DEMO_ACCOUNTS))
    return by_phone, by_role, created


# --------------------------------------------------------- 4. prices and demo
def seed_market_prices(session: Session, days: int = 120) -> dict[str, Any]:
    """Fill market prices through the real sync service.

    Going through ``MarketDataSyncService`` rather than writing rows directly
    means the demo data is produced by the same code path the app uses, so the
    demo provider's pairing and source-stamping rules stay honest.
    """
    result = MarketDataSyncService(session).sync(
        days=days,
        history_days=days,
        include_arrivals=True,
        triggered_by_user_id=None,
    )
    logger.info(
        "seed.market_prices",
        status=result.get("status"),
        processed=result.get("records_processed"),
        inserted=result.get("records_inserted"),
        updated=result.get("records_updated"),
        arrivals=result.get("arrivals_written"),
    )
    return result


#: A published lot per demo farmer, so no account signs in to an empty app.
DEMO_LOTS: tuple[dict[str, Any], ...] = (
    {
        "phone": "9000000002",
        "commodity": "ONION",
        "title": "Shirala red onion, Grade A",
        "quantity": 120,
        "minimum_price": 1450.0,
        "expected_price": 1600.0,
        "quality_grade": QualityGrade.GRADE_A,
        "village": "Shirala",
        "taluka": "Baramati",
        "district": "Pune",
        "description": "Freshly lifted, cured for 4 days, sorted and graded.",
    },
    {
        "phone": "9000000003",
        "commodity": "TURMERIC",
        "title": "Kadegaon Salem turmeric, unpolished",
        "quantity": 40,
        "minimum_price": 8200.0,
        "expected_price": 8800.0,
        "quality_grade": QualityGrade.GRADE_B,
        "village": "Kadegaon",
        "taluka": "Solapur",
        "district": "Solapur",
        "description": "Unpolished fingers, curcumin tested at 3.4%.",
    },
)

#: An open demand per demo buyer, so the matching screen has something to match.
DEMO_DEMANDS: tuple[dict[str, Any], ...] = (
    {
        "phone": "9000000005",
        "commodity": "ONION",
        "required_quantity": 80,
        "district": "Pune",
        "delivery_location": "Pune Market Yard",
        "required_in_days": 10,
    },
    {
        "phone": "9000000006",
        "commodity": "SOYBEAN",
        "required_quantity": 300,
        "district": "Mumbai",
        "delivery_location": "Vashi APMC, Navi Mumbai",
        "required_in_days": 14,
    },
)


def seed_demo_lots(session: Session, users_by_phone: dict[str, User]) -> dict[str, FarmLot]:
    """Create one published lot per demo farmer. Returns the first lot by phone."""
    lots: dict[str, FarmLot] = {}
    service = LotService(session)
    for spec in DEMO_LOTS:
        seller = users_by_phone[spec["phone"]]
        if _existing(session, FarmLot, seller_user_id=seller.id, title=spec["title"]):
            continue
        lots[spec["phone"]] = service.create_lot(
            FarmLotCreate(
                commodity_id=_commodity_id(session, spec["commodity"]),
                title=spec["title"],
                quantity=spec["quantity"],
                unit="quintal",
                quality_grade=spec["quality_grade"],
                minimum_price=spec["minimum_price"],
                expected_price=spec["expected_price"],
                harvest_date=date.today() - timedelta(days=3),
                available_from=date.today() - timedelta(days=1),
                village=spec["village"],
                taluka=spec["taluka"],
                district=spec["district"],
                storage_available=True,
                pickup_available=True,
                publish_now=True,
                description=spec["description"],
            ),
            seller,
        )
    return lots


def _commodity_id(session: Session, code: str) -> uuid.UUID:
    commodity = _existing(session, Commodity, code=code)
    if commodity is None:  # pragma: no cover - the catalogue always seeds first
        raise SystemExit(f"Commodity {code} is missing. Run the seeder without --no-demo.")
    return commodity.id


def seed_demo_demands(session: Session, users_by_phone: dict[str, User]) -> dict[str, BuyerDemand]:
    """Create one open demand per demo buyer."""
    demands: dict[str, BuyerDemand] = {}
    service = DemandService(session)
    for spec in DEMO_DEMANDS:
        buyer = users_by_phone[spec["phone"]]
        if _existing(
            session,
            BuyerDemand,
            buyer_user_id=buyer.id,
            delivery_location=spec["delivery_location"],
        ):
            continue
        demands[spec["phone"]] = service.create_demand(
            BuyerDemandCreate(
                commodity_id=_commodity_id(session, spec["commodity"]),
                required_quantity=spec["required_quantity"],
                unit="quintal",
                min_grade=QualityGrade.GRADE_B,
                max_price_per_unit=None,
                delivery_location=spec["delivery_location"],
                district=spec["district"],
                required_by_date=date.today() + timedelta(days=spec["required_in_days"]),
            ),
            buyer,
        )
    return demands


def seed_demo_trading(
    session: Session, accounts: dict[str, User], commodities, lots: dict[str, FarmLot]
) -> None:
    """Accept one offer against the first farmer's lot, producing the demo order.

    Enough for every dashboard, notification and ledger screen to have real rows
    to render instead of empty states.
    """
    farmer = accounts.get(UserRole.FARMER.value)
    buyer = accounts.get(UserRole.BUYER.value)
    lot = lots.get(DEMO_LOTS[0]["phone"]) or _existing(
        session, FarmLot, title=DEMO_LOTS[0]["title"]
    )
    if farmer is None or buyer is None or lot is None:
        logger.warning("seed.trading.skipped", reason="missing farmer, buyer or lot")
        return
    if _existing(session, Order, lot_id=lot.id):
        logger.info("seed.trading.already_present")
        return
    onion = commodities["ONION"]

    # The buyer's own demand from DEMO_DEMANDS, so the accepted offer is linked to
    # a real open demand rather than an orphan row created just for this order.
    demand = _existing(
        session,
        BuyerDemand,
        buyer_user_id=buyer.id,
        delivery_location=DEMO_DEMANDS[0]["delivery_location"],
    )
    if demand is None:
        demand = DemandService(session).create_demand(
            BuyerDemandCreate(
                commodity_id=onion.id,
                required_quantity=DEMO_DEMANDS[0]["required_quantity"],
                unit="quintal",
                min_grade=QualityGrade.GRADE_A,
                min_price_per_unit=1400.0,
                max_price_per_unit=1800.0,
                delivery_location=DEMO_DEMANDS[0]["delivery_location"],
                district=DEMO_DEMANDS[0]["district"],
                required_by_date=date.today() + timedelta(days=DEMO_DEMANDS[0]["required_in_days"]),
                requires_verified_buyer=False,
            ),
            buyer,
        )

    offer = OfferService(session).create_offer(
        OfferCreate(
            lot_id=lot.id,
            demand_id=demand.id,
            quantity=60,
            offered_price=1620.0,
            notes="Deliver to Pune Market Yard, morning preferred.",
        ),
        buyer,
    )

    order = OrderService(session).create_from_offer(offer=offer, lot=lot, actor=buyer)
    session.flush()

    # Leave the order mid-pipeline rather than at creation: every dashboard and
    # pipeline bar then shows a realistic state, and the demo still has a next
    # step for whoever is demonstrating logistics.
    OrderService(session).update_status(
        order.id,
        OrderStatusUpdate(
            status=OrderStatus.PICKUP_SCHEDULED,
            pickup_date=date.today() + timedelta(days=1),
            note="Truck booked for the morning slot.",
        ),
        farmer,
    )
    logger.info(
        "seed.trading",
        lot=lot.lot_code,
        demand=demand.reference_code,
        offer=offer.reference_code,
        order=order.order_number,
    )


def seed_storage(session: Session, accounts: dict[str, User]) -> None:
    """Two godowns: one private to the farmer, one public FPO store."""
    farmer = accounts.get(UserRole.FARMER.value)
    fpo = accounts.get(UserRole.FPO.value)
    if farmer is None:
        return
    own_godown = _existing(
        session, StorageFacility, owner_user_id=farmer.id, name="Shirala Kisan Godown"
    )
    if own_godown is None:
        session.add(
            StorageFacility(
                owner_user_id=farmer.id,
                name="Shirala Kisan Godown",
                storage_type=StorageType.OWN_GODOWN,
                capacity_quintal=500,
                occupied_quintal=120,
                village="Shirala",
                taluka="Baramati",
                district="Pune",
                latitude=18.2676,
                longitude=74.7205,
                storage_cost_per_quintal_month=18.0,
                temperature_controlled=False,
                supports_commodities=["ONION", "SOYBEAN"],
                amenities=["Weighbridge", "Tarpaulin"],
                contact_person="Ramesh Jadhav",
                contact_phone=farmer.phone,
                is_private=True,
            )
        )
    if (
        fpo is not None
        and _existing(session, StorageFacility, owner_user_id=fpo.id, name="Sahyadri FPO Store")
        is None
    ):
        session.add(
            StorageFacility(
                owner_user_id=fpo.id,
                name="Sahyadri FPO Store",
                storage_type=StorageType.FPO_STORE,
                capacity_quintal=1200,
                occupied_quintal=300,
                district="Nashik",
                taluka="Niphad",
                latitude=20.0499,
                longitude=73.7833,
                storage_cost_per_quintal_month=22.0,
                temperature_controlled=True,
                supports_commodities=["ONION", "CHILLI", "TOMATO"],
                amenities=["Cold room", "Grader", "Loading bay"],
                is_private=False,
            )
        )
    session.flush()


# ------------------------------------------------------------------- entrypoint
def _existing_table_names(session: Session) -> set[str]:
    """Table names in the connected database. Split out so it can be faked in tests."""
    from sqlalchemy import inspect

    return set(inspect(session.get_bind()).get_table_names())


def _require_schema(session: Session) -> None:
    """Fail with an instruction rather than a bare "no such table" error.

    The seeder never creates tables itself. Schema ownership belongs to Alembic,
    so an unmigrated database is a deployment mistake worth naming explicitly. A
    completely empty database is left alone: it is the normal state before the
    first ``alembic upgrade head``, and the upserts will be no-ops anyway.
    """
    tables = _existing_table_names(session)
    if tables and "roles" not in tables:
        raise SystemExit(
            "This database has no KisanSaathi schema. Run the migrations first:\n"
            "    alembic upgrade head"
        )


def seed_all(
    session: Session, *, include_demo: bool = True, price_days: int = 120
) -> dict[str, Any]:
    """Seed into an existing session. The caller owns the transaction.

    Split out from :func:`seed` so tests can run the whole thing inside their own
    rollback boundary instead of opening a second connection.
    """
    report: dict[str, Any] = {}
    _require_schema(session)
    report["roles_created"] = seed_roles(session)
    commodities, markets = seed_catalogue(session)
    report["commodities"] = len(commodities)
    report["markets"] = len(markets)

    if not include_demo:
        report["accounts_created"] = 0
        report["traded"] = False
        return report

    by_phone, by_role, created = seed_accounts(session)
    report["accounts_created"] = created
    report["accounts_total"] = len(DEMO_ACCOUNTS)
    prices = seed_market_prices(session, days=price_days)
    report["price_rows"] = prices.get("records_processed", 0)
    report["arrivals"] = prices.get("arrivals_written", 0)
    seed_storage(session, by_role)

    # Lots and demands are keyed by phone, so the second farmer and the second
    # buyer each get their own data instead of sharing the first one's.
    lots = seed_demo_lots(session, by_phone)
    seed_demo_demands(session, by_phone)
    report["lots"] = session.execute(select(func.count()).select_from(FarmLot)).scalar_one()
    report["demands"] = session.execute(select(func.count()).select_from(BuyerDemand)).scalar_one()
    seed_demo_trading(session, by_role, commodities, lots)
    report["traded"] = True
    return report


def seed(*, include_demo: bool = True, price_days: int = 120) -> dict[str, Any]:
    """Run the whole seed in its own transaction. Safe to call repeatedly."""
    with session_scope() as session:
        return seed_all(session, include_demo=include_demo, price_days=price_days)


def _reset() -> None:
    """Drop and recreate every table. Refuses to touch a non-demo database."""
    import app.models  # noqa: F401  (registers the metadata)
    from app.core.config import settings
    from app.db.base import Base

    url = settings.resolved_database_url()
    if settings.ENVIRONMENT == "production" or ("postgres" in url and "localhost" not in url):
        raise SystemExit(f"Refusing to reset {url}: --reset is only for local and demo databases.")
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    logger.warning("seed.reset", database=url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the KisanSaathi database.")
    parser.add_argument(
        "--no-demo",
        action="store_true",
        help="Reference data and roles only; no demo accounts or prices.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop all tables first. Destructive; refuses on production databases.",
    )
    parser.add_argument(
        "--price-days",
        type=int,
        default=120,
        help="How many days of market price history to generate (default 120).",
    )
    args = parser.parse_args(argv)

    if args.reset:
        _reset()

    report = seed(include_demo=not args.no_demo, price_days=args.price_days)
    logger.info("seed.done", **report)
    if not args.no_demo:
        lot_phones = {lot["phone"] for lot in DEMO_LOTS}
        demand_phones = {d["phone"] for d in DEMO_DEMANDS}
        trade_lot_phone, trade_buyer_phone = DEMO_LOTS[0]["phone"], DEMO_DEMANDS[0]["phone"]
        storage_notes = {
            "9000000002": "private godown",
            "9000000004": "shared FPO store",
        }
        print(f"\nDemo accounts ready. Password for all of them: {DEMO_PASSWORD}\n")
        for spec in DEMO_ACCOUNTS:
            phone = spec["phone"]
            marks: list[str] = []
            # Ordered most specific first so an account gets one clear description.
            if phone == trade_lot_phone:
                marks.append("published lot + live order")
            elif phone in lot_phones:
                marks.append("published lot")
            if phone == trade_buyer_phone:
                marks.append("open demand + live order")
            elif phone in demand_phones:
                marks.append("open demand")
            if phone in storage_notes:
                marks.append(storage_notes[phone])
            suffix = f"  ({', '.join(marks)})" if marks else ""
            print(f"  {spec['role'].value:<18} {phone}  {spec['full_name']}{suffix}")
        print(
            "\nThe seeded order sits at pickup-scheduled, so logistics and delivery "
            "have somewhere to go next."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
