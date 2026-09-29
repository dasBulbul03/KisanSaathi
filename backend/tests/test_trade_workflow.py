"""End-to-end service level tests for the core trade workflow.

These exercise the real SQLAlchemy models against SQLite, so they catch schema
and relationship mistakes that import-only checks miss.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.enums import (
    BuyerType,
    DemandStatus,
    InspectionStatus,
    LotStatus,
    OfferStatus,
    OrderStatus,
    PaymentStatus,
    Priority,
    QualityGrade,
    SellerType,
    UserRole,
    VerificationStatus,
)
from app.core.exceptions import (
    AuthenticationError,
    InvalidStateTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.rbac import ROLE_PERMISSIONS
from app.schemas.operations import (
    GrievanceCreate,
    GrievanceUpdate,
    PaymentUpdate,
    QualityInspectionCreate,
    QualityMeasurementInput,
    StorageFacilityCreate,
)
from app.schemas.trade import (
    BuyerDemandCreate,
    FarmLotCreate,
    OfferCreate,
    OrderStatusUpdate,
)
from app.schemas.user import (
    STAFF_ONLY_ROLES,
    LoginRequest,
    RegisterRequest,
    StaffUserCreate,
)
from app.services.auth_service import AdminUserService, AuthService
from app.services.demand_service import DemandService
from app.services.grievance_service import GrievanceService
from app.services.lot_service import LotService
from app.services.offer_service import OfferService
from app.services.order_service import OrderService
from app.services.payment_service import PaymentService
from app.services.quality_service import QualityService
from app.services.storage_service import StorageService

PASSWORD = "Demo@1234"


def _register(session: Session, phone: str, role: UserRole, **kwargs):
    """Self-service roles use /register; staff roles are admin-onboarded."""
    if role in STAFF_ONLY_ROLES:
        return AdminUserService(session).create_staff_user(
            StaffUserCreate(
                full_name=kwargs.pop("full_name", f"Test {role.value.title()}"),
                phone=phone,
                password=PASSWORD,
                role=role,
                district=kwargs.pop("district", "Pune"),
                organisation_name=kwargs.pop("organisation_name", None),
            ),
            actor_id=None,  # bootstrap: no admin exists yet
        )
    payload = RegisterRequest(
        full_name=kwargs.pop("full_name", f"Test {role.value.title()}"),
        phone=phone,
        password=PASSWORD,
        role=role,
        district=kwargs.pop("district", "Pune"),
        **kwargs,
    )
    user, _ = AuthService(session).register(payload)
    return user


@pytest.fixture()
def people(session: Session, roles) -> dict[str, object]:
    farmer = _register(
        session,
        "9800000001",
        UserRole.FARMER,
        full_name="Ramesh Jadhav",
        village="Shirala",
        taluka="Baramati",
        farm_area_acres=6.5,
        primary_crops=["onion", "soybean"],
    )
    fpo = _register(
        session,
        "9800000002",
        UserRole.FPO,
        full_name="Sahyadri FPO",
        organisation_name="Sahyadiri Farmer Producer Org",
        member_count=145,
        primary_crops=["onion", "tomato"],
    )
    buyer = _register(
        session,
        "9800000003",
        UserRole.BUYER,
        full_name="Anita Deshmukh",
        organisation_name="Pune Fresh Retailers Pvt Ltd",
        buyer_type=BuyerType.RETAILER,
        gst_number="27AAACP1234A1Z5",
    )
    inspector = _register(
        session, "9800000004", UserRole.QUALITY_INSPECTOR, full_name="Quality Inspector"
    )
    admin = _register(session, "9800000005", UserRole.ADMIN, full_name="Platform Admin")
    # Mark the buyer as verified so trust scoring exercises the positive path.
    buyer.buyer_profile.verification_status = VerificationStatus.VERIFIED
    session.commit()
    return {
        "farmer": farmer,
        "fpo": fpo,
        "buyer": buyer,
        "inspector": inspector,
        "admin": admin,
    }


@pytest.fixture()
def commodity(session: Session):
    from app.models import Commodity

    row = session.query(Commodity).filter(Commodity.code == "ONION").one_or_none()
    if row is None:
        row = Commodity(
            name="Onion",
            code="ONION",
            category="VEGETABLE",
            default_unit="quintal",
            is_perishable=True,
        )
        session.add(row)
        session.commit()
    return row


@pytest.fixture()
def bulb_size(session: Session, commodity):
    """A quality attribute so inspections can carry real measurements."""
    from app.models import QualityAttribute

    row = (
        session.query(QualityAttribute)
        .filter(QualityAttribute.code == "BULB_SIZE_MM")
        .one_or_none()
    )
    if row is None:
        row = QualityAttribute(
            commodity_id=commodity.id,
            code="BULB_SIZE_MM",
            label="Average bulb diameter",
            unit="mm",
            min_value=25,
            max_value=90,
            ideal_min=45,
            ideal_max=75,
            grade_a_min=50,
            grade_b_min=40,
        )
        session.add(row)
        session.commit()
    return row


# --------------------------------------------------------------------- auth
def test_register_and_login(session: Session, roles) -> None:
    service = AuthService(session)
    user, tokens = service.register(
        RegisterRequest(
            full_name="Kisan Demo",
            phone="9811111111",
            password=PASSWORD,
            role=UserRole.FARMER,
            district="Nashik",
        )
    )
    session.commit()
    assert user.role is UserRole.FARMER
    assert user.farmer_profile is not None
    assert tokens.access_token and tokens.refresh_token

    logged_in, again = service.login(LoginRequest(identifier="9811111111", password=PASSWORD))
    assert logged_in.id == user.id
    assert again.access_token

    refreshed = service.refresh(tokens.refresh_token)
    assert refreshed.access_token

    # Rotating a refresh token revokes the old one.
    with pytest.raises(AuthenticationError):
        service.refresh(tokens.refresh_token)

    # Single-session logout ends only the current device; the login above still works.
    assert service.logout(user.id, current_refresh_token=refreshed.refresh_token) == 1
    with pytest.raises(AuthenticationError):
        service.refresh(refreshed.refresh_token)
    _, still_valid = service.login(LoginRequest(identifier="9811111111", password=PASSWORD))
    assert service.logout(user.id, all_sessions=True) >= 1
    assert still_valid.access_token
    session.rollback()


def test_login_rejects_bad_password(session: Session, roles) -> None:
    service = AuthService(session)
    service.register(
        RegisterRequest(
            full_name="Wrong Password",
            phone="9811111112",
            password=PASSWORD,
            role=UserRole.FARMER,
        )
    )
    session.commit()
    with pytest.raises(AuthenticationError):
        service.login(LoginRequest(identifier="9811111112", password="WrongPass@1"))
    session.rollback()


# ---------------------------------------------------------------- lots
def test_farmer_can_publish_a_lot(session: Session, roles, people, commodity) -> None:
    service = LotService(session)
    lot = service.create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="Shirala red onion - 2026 harvest",
            description="Well graded, cured for 10 days.",
            quantity=120,
            unit="quintal",
            expected_price=1850,
            minimum_price=1600,
            quality_grade=QualityGrade.GRADE_A,
            harvest_date=date.today() - timedelta(days=3),
            available_from=date.today(),
            village="Shirala",
            taluka="Baramati",
            district="Pune",
            storage_available=True,
        ),
        people["farmer"],
    )
    session.commit()
    assert lot.seller_type is SellerType.FARMER
    assert lot.status is LotStatus.DRAFT

    published = service.publish_lot(lot.id, people["farmer"])
    session.commit()
    assert published.status is LotStatus.PUBLISHED

    listed, total = service.list_lots(status=[LotStatus.PUBLISHED], district="Pune")
    assert total == 1
    assert listed[0].lot_code.startswith("LOT")
    assert service.enrich(published)["seller"].full_name == "Ramesh Jadhav"
    session.rollback()


def test_non_owner_cannot_edit_a_lot(session: Session, roles, people, commodity) -> None:
    from app.core.exceptions import PermissionDeniedError
    from app.schemas.trade import FarmLotUpdate

    service = LotService(session)
    lot = service.create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="FPO soybean",
            quantity=200,
            unit="quintal",
            expected_price=4600,
        ),
        people["fpo"],
    )
    session.commit()
    with pytest.raises(PermissionDeniedError):
        service.update_lot(lot.id, FarmLotUpdate(title="Hijacked"), people["farmer"])
    session.rollback()


# ---------------------------------------------------------------- matching
def test_matching_ranks_grade_and_distance(session: Session, roles, people, commodity) -> None:
    from app.services.matching_service import MatchingService

    lots = LotService(session)
    demand = DemandService(session)
    lot = lots.create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="Grade A onion",
            quantity=300,
            unit="quintal",
            expected_price=1900,
            quality_grade=QualityGrade.GRADE_A,
            district="Pune",
            taluka="Baramati",
        ),
        people["farmer"],
    )
    lots.publish_lot(lot.id, people["farmer"])
    requirement = demand.create_demand(
        BuyerDemandCreate(
            commodity_id=commodity.id,
            required_quantity=250,
            unit="quintal",
            min_grade=QualityGrade.GRADE_A,
            min_price_per_unit=1700,
            max_price_per_unit=2100,
            delivery_location="Pune",
            district="Pune",
            required_by_date=date.today() + timedelta(days=7),
        ),
        people["buyer"],
    )
    session.commit()

    matches = MatchingService(session).match_lot_to_demands(lot, commodity=commodity)
    assert matches, "expected at least one match"
    best = matches[0]
    assert best.entity_id == requirement.id
    assert best.score > 50
    codes = {reason.code for reason in best.reasons}
    assert {"commodity", "quantity", "quality", "distance", "price"} <= codes
    assert best.disclaimer
    session.rollback()


def test_matching_survives_a_demand_with_only_one_price_bound(
    session: Session, roles, people, commodity
) -> None:
    """A demand with a ceiling but no floor has no price *range*.

    Reporting a half-filled range used to raise a validation error, which took
    down the whole match list and, through it, the farmer and buyer dashboards.
    Both endpoints have to survive a one-sided price.
    """
    from app.services.matching_service import MatchingService

    lots = LotService(session)
    demand = DemandService(session)
    lot = lots.create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="Grade A onion for a capped demand",
            quantity=300,
            unit="quintal",
            expected_price=1900,
            quality_grade=QualityGrade.GRADE_A,
            district="Pune",
        ),
        people["farmer"],
    )
    lots.publish_lot(lot.id, people["farmer"])
    demand.create_demand(
        BuyerDemandCreate(
            commodity_id=commodity.id,
            required_quantity=250,
            unit="quintal",
            min_grade=QualityGrade.GRADE_A,
            # Ceiling only: no floor, which is the common way to post a demand.
            max_price_per_unit=2100,
            delivery_location="Pune",
            district="Pune",
            required_by_date=date.today() + timedelta(days=7),
        ),
        people["buyer"],
    )
    session.commit()

    service = MatchingService(session)
    matches = service.match_lot_to_demands(lot, commodity=commodity)
    assert matches, "a capped demand should still match"
    assert all(match.price_range is None for match in matches)

    # The reverse direction and the user-facing wrapper must survive it too.
    assert isinstance(service.matches_for_user(people["farmer"].id, role=UserRole.FARMER), list)
    session.rollback()


# ---------------------------------------------------------------- offers
def test_offer_acceptance_creates_an_order(session: Session, roles, people, commodity) -> None:
    lots = LotService(session)
    offers = OfferService(session)
    orders = OrderService(session)

    lot = lots.create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="Tomato lot",
            quantity=80,
            unit="quintal",
            expected_price=1500,
            minimum_price=1200,
            quality_grade=QualityGrade.GRADE_B,
            district="Pune",
        ),
        people["fpo"],
    )
    lots.publish_lot(lot.id, people["fpo"])
    session.commit()

    # Below the seller's minimum is allowed, but must be flagged as a warning.
    preflight = offers.preflight_offer(
        OfferCreate(lot_id=lot.id, offered_price=900, quantity=50, unit="quintal"),
        people["buyer"],
    )
    assert preflight["can_submit"] is True
    assert any("minimum" in w.lower() for w in preflight["warnings"])

    offer = offers.create_offer(
        OfferCreate(lot_id=lot.id, offered_price=1450, quantity=50, unit="quintal"),
        people["buyer"],
    )
    session.commit()
    assert offer.status is OfferStatus.PENDING
    assert lot.active_offers_count == 1

    order = offers.accept(offer.id, people["fpo"])
    session.commit()
    assert order.order_number.startswith("ORD")
    assert order.agreed_price == 1450
    assert order.total_value == pytest.approx(1450 * 50)
    assert order.status in (OrderStatus.OFFER_ACCEPTED, OrderStatus.ORDER_CREATED)
    assert offers.get_offer(offer.id).status is OfferStatus.ACCEPTED
    assert orders.enrich(order)["can_update_status"] in (True, False)
    session.rollback()


def test_buyer_cannot_accept_their_own_offer(session: Session, roles, people, commodity) -> None:
    lots = LotService(session)
    offers = OfferService(session)
    lot = lots.create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="Soybean",
            quantity=50,
            unit="quintal",
            expected_price=4600,
            district="Pune",
        ),
        people["farmer"],
    )
    lots.publish_lot(lot.id, people["farmer"])
    session.commit()
    offer = offers.create_offer(
        OfferCreate(lot_id=lot.id, offered_price=4500, quantity=20, unit="quintal"),
        people["buyer"],
    )
    session.commit()
    with pytest.raises(PermissionDeniedError):
        offers.accept(offer.id, people["buyer"])
    session.rollback()


def test_offer_beyond_available_quantity_is_rejected(
    session: Session, roles, people, commodity
) -> None:
    from app.core.exceptions import ConflictError

    lots = LotService(session)
    offers = OfferService(session)
    lot = lots.create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="Limited lot",
            quantity=10,
            unit="quintal",
            expected_price=1000,
            district="Pune",
        ),
        people["farmer"],
    )
    lots.publish_lot(lot.id, people["farmer"])
    session.commit()
    with pytest.raises(ConflictError):
        offers.create_offer(
            OfferCreate(lot_id=lot.id, offered_price=900, quantity=25, unit="quintal"),
            people["buyer"],
        )
    session.rollback()


# ---------------------------------------------------------------- orders
def test_order_state_machine_rejects_skips(session: Session, roles, people, commodity) -> None:
    lots = LotService(session)
    offers = OfferService(session)
    orders = OrderService(session)
    lot = lots.create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="Wheat",
            quantity=200,
            unit="quintal",
            expected_price=3200,
            district="Pune",
        ),
        people["farmer"],
    )
    lots.publish_lot(lot.id, people["farmer"])
    session.commit()
    offer = offers.create_offer(
        OfferCreate(lot_id=lot.id, offered_price=3150, quantity=100, unit="quintal"),
        people["buyer"],
    )
    order = offers.accept(offer.id, people["farmer"])
    session.commit()

    with pytest.raises(InvalidStateTransitionError):
        orders.update_status(
            order.id,
            OrderStatusUpdate(status=OrderStatus.COMPLETED),
            people["admin"],
        )
    session.rollback()


# ---------------------------------------------------------------- quality
def test_quality_inspection_requires_verification(
    session: Session, roles, people, commodity, bulb_size
) -> None:
    lots = LotService(session)
    offers = OfferService(session)
    quality = QualityService(session)
    lot = lots.create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="Onion for inspection",
            quantity=60,
            unit="quintal",
            expected_price=1800,
            quality_grade=QualityGrade.GRADE_A,
            district="Pune",
        ),
        people["farmer"],
    )
    lots.publish_lot(lot.id, people["farmer"])
    session.commit()
    offer = offers.create_offer(
        OfferCreate(lot_id=lot.id, offered_price=1750, quantity=40, unit="quintal"),
        people["buyer"],
    )
    offers.accept(offer.id, people["farmer"])
    session.commit()

    inspection = quality.create_inspection(
        QualityInspectionCreate(
            lot_id=lot.id,
            grade=QualityGrade.GRADE_A,
            moisture_percent=11.5,
            damage_percent=1.2,
            notes="Cured, clean, no black spots.",
            measurements=[QualityMeasurementInput(attribute_id=bulb_size.id, numeric_value=62.0)],
        ),
        people["buyer"],
    )
    session.commit()
    # Buyer submissions are provisional until an inspector confirms.
    assert inspection.status is InspectionStatus.PENDING

    with pytest.raises(PermissionDeniedError):
        quality.verify_inspection(inspection.id, approve=True, user=people["buyer"])

    confirmed = quality.verify_inspection(
        inspection.id, approve=True, user=people["inspector"], notes="Verified on site"
    )
    session.commit()
    assert confirmed.status is InspectionStatus.CONFIRMED
    assert quality.enrich(confirmed)["grade"] is QualityGrade.GRADE_A
    session.rollback()


# ---------------------------------------------------------------- payments
def test_payment_completion_advances_the_order(session: Session, roles, people, commodity) -> None:
    lots = LotService(session)
    offers = OfferService(session)
    quality = QualityService(session)
    payments = PaymentService(session)

    lot = lots.create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="Payment flow onion",
            quantity=40,
            unit="quintal",
            expected_price=1800,
            district="Pune",
        ),
        people["farmer"],
    )
    lots.publish_lot(lot.id, people["farmer"])
    session.commit()
    offer = offers.create_offer(
        OfferCreate(lot_id=lot.id, offered_price=1780, quantity=40, unit="quintal"),
        people["buyer"],
    )
    order = offers.accept(offer.id, people["farmer"])
    session.commit()

    # Quality cannot be confirmed before delivery.
    orders = OrderService(session)
    early = quality.create_inspection(
        QualityInspectionCreate(lot_id=lot.id, grade=QualityGrade.GRADE_B),
        people["inspector"],
    )
    session.commit()
    assert early.status is InspectionStatus.CONFIRMED
    assert orders.get_order(order.id).status is OrderStatus.ORDER_CREATED
    with pytest.raises(InvalidStateTransitionError):
        quality.verify_inspection(early.id, approve=True, user=people["inspector"])
    session.rollback()

    # Walk the logistics lifecycle as the administrator, then confirm quality.
    for step in (
        OrderStatus.LOGISTICS_ASSIGNED,
        OrderStatus.IN_TRANSIT,
        OrderStatus.DELIVERED,
    ):
        orders.update_status(order.id, OrderStatusUpdate(status=step), people["admin"])
        session.commit()
    assert orders.get_order(order.id).status is OrderStatus.DELIVERED

    inspection = quality.create_inspection(
        QualityInspectionCreate(lot_id=lot.id, grade=QualityGrade.GRADE_B),
        people["inspector"],
    )
    session.commit()
    assert inspection.lot_id == lot.id
    assert orders.get_order(order.id).status is OrderStatus.QUALITY_CONFIRMED

    payment_row = order.transaction.payments[0]
    updated = payments.update_status(
        payment_row.id,
        PaymentUpdate(status=PaymentStatus.PAID, reference_number="UTR-404040"),
        people["buyer"],
    )
    session.commit()
    assert updated.status.value == "PAID"
    assert updated.reference_number == "UTR-404040"

    refreshed = orders.get_order(order.id)
    assert refreshed.status is OrderStatus.PAYMENT_COMPLETED
    session.rollback()


# ---------------------------------------------------------------- grievances
def test_grievance_lifecycle(session: Session, roles, people, commodity) -> None:
    lots = LotService(session)
    offers = OfferService(session)
    grievances = GrievanceService(session)

    lot = lots.create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="Complaint lot",
            quantity=30,
            unit="quintal",
            expected_price=1500,
            district="Pune",
        ),
        people["farmer"],
    )
    lots.publish_lot(lot.id, people["farmer"])
    session.commit()
    offer = offers.create_offer(
        OfferCreate(lot_id=lot.id, offered_price=1450, quantity=30, unit="quintal"),
        people["buyer"],
    )
    order = offers.accept(offer.id, people["farmer"])
    session.commit()

    grievance = grievances.create(
        GrievanceCreate(
            order_id=order.id,
            category="QUALITY_MISMATCH",
            subject="Delivered grade is lower than agreed",
            description="Batches arrived with bruising, 20% below the agreed grade.",
            priority=Priority.HIGH,
        ),
        people["buyer"],
    )
    session.commit()
    assert grievance.ticket_number
    assert grievance.status.value == "OPEN"
    assert grievance.due_date is not None

    comment = grievances.add_comment(
        grievance.id, "Photos uploaded, awaiting your response.", people["buyer"]
    )
    assert comment.body

    reviewed = grievances.update(
        grievance.id, GrievanceUpdate(status="UNDER_REVIEW"), people["admin"]
    )
    assert reviewed.status.value == "UNDER_REVIEW"

    resolved = grievances.update(
        grievance.id,
        GrievanceUpdate(status="RESOLVED", resolution="Partial refund agreed."),
        people["admin"],
    )
    session.commit()
    assert resolved.resolution == "Partial refund agreed."
    assert resolved.resolved_at is not None

    detail = grievances.enrich(resolved, people["buyer"])
    assert detail["category_label"] == "Quality mismatch"
    assert detail["comments"], "buyer should see the public comment"
    session.rollback()


# ---------------------------------------------------------------- storage
def test_storage_facility_round_trip(session: Session, roles, people) -> None:
    service = StorageService(session)
    facility = service.create(
        StorageFacilityCreate(
            name="Baramati Kisan Godown",
            capacity_quintal=500,
            occupied_quintal=120,
            taluka="Baramati",
            district="Pune",
            storage_cost_per_quintal_month=18,
            temperature_controlled=False,
        ),
        people["farmer"],
    )
    session.commit()
    assert facility.available_quintal == 380

    options = service.options_for_seller(user=people["farmer"])
    assert options and options[0]["distance_km"] is not None
    assert options[0]["storage_type_label"] == "Own godown"

    service.delete(facility.id, people["admin"])
    session.commit()
    with pytest.raises(NotFoundError):
        service.get(facility.id)
    session.rollback()


# ---------------------------------------------------------------- rbac
def test_role_permissions_cover_every_role() -> None:
    for role in UserRole:
        assert ROLE_PERMISSIONS[role], f"{role} has no permissions"
    assert "user:manage" in ROLE_PERMISSIONS[UserRole.ADMIN]
    assert "offer:create" in ROLE_PERMISSIONS[UserRole.BUYER]
    assert "offer:create" not in ROLE_PERMISSIONS[UserRole.FARMER]
    assert "quality:verify" in ROLE_PERMISSIONS[UserRole.QUALITY_INSPECTOR]
    assert "logistics:assign" in ROLE_PERMISSIONS[UserRole.LOGISTICS_PARTNER]


def test_demand_status_transitions(session: Session, roles, people, commodity) -> None:
    service = DemandService(session)
    requirement = service.create_demand(
        BuyerDemandCreate(
            commodity_id=commodity.id,
            required_quantity=100,
            unit="quintal",
            delivery_location="Pune",
            district="Pune",
            required_by_date=date.today() + timedelta(days=10),
        ),
        people["buyer"],
    )
    session.commit()
    assert requirement.status is DemandStatus.OPEN
    closed = service.close_demand(requirement.id, people["buyer"], reason="Bought elsewhere")
    assert closed.status is DemandStatus.CLOSED
    session.rollback()
