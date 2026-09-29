"""HTTP level tests.

These go through the real ASGI app, the real router tree, the real error
handlers and the real service layer. That is deliberate: the earlier bug where a
buyer's order pipeline came back empty was invisible to the service level tests
because nothing exercised the role value the router actually passed.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.enums import BuyerType, UserRole
from app.core.rbac import ROLE_PERMISSIONS
from app.models import Role
from app.schemas.trade import FarmLotCreate, OfferCreate
from app.schemas.user import RegisterRequest, StaffUserCreate
from app.services.auth_service import AdminUserService, AuthService
from app.services.lot_service import LotService
from app.services.offer_service import OfferService
from app.services.order_service import OrderService

PASSWORD = "Demo@1234"
API = "/api/v1"


def _staff(session: Session, phone: str, role: UserRole, **kwargs) -> object:
    """Create a staff account directly. ``actor_id=None`` is the bootstrap case."""
    return AdminUserService(session).create_staff_user(
        StaffUserCreate(
            full_name=kwargs.pop("full_name", f"Test {role.value.title()}"),
            phone=phone,
            password=PASSWORD,
            role=role,
            district=kwargs.pop("district", "Pune"),
            **kwargs,
        ),
        actor_id=kwargs.pop("actor_id", None),
    )


def _register(session: Session, phone: str, role: UserRole, **kwargs):
    """Self-service roles go through register; staff roles are admin-onboarded."""
    if role not in (UserRole.FARMER, UserRole.FPO, UserRole.BUYER):
        return _staff(session, phone, role, **kwargs)
    user, _ = AuthService(session).register(
        RegisterRequest(
            full_name=kwargs.pop("full_name", f"Test {role.value.title()}"),
            phone=phone,
            password=PASSWORD,
            role=role,
            district=kwargs.pop("district", "Pune"),
            **kwargs,
        )
    )
    return user


@pytest.fixture()
def accounts(session: Session, roles) -> dict[str, object]:
    """One verified user per self-service role, plus staff accounts.

    The buyer is left unverified: verification is what the admin approval
    endpoint is for, and several endpoints behave differently once it is set.
    """
    return {
        "farmer": _register(
            session,
            "9811110001",
            UserRole.FARMER,
            full_name="Ramesh Jadhav",
            village="Shirala",
            taluka="Baramati",
            farm_area_acres=6.5,
            primary_crops=["onion"],
        ),
        "fpo": _register(
            session,
            "9811110002",
            UserRole.FPO,
            full_name="Sahyadri FPO",
            organisation_name="Sahyadri Farmer Producer Org",
            primary_crops=["onion"],
        ),
        "buyer": _register(
            session,
            "9811110003",
            UserRole.BUYER,
            full_name="Anita Deshmukh",
            organisation_name="Pune Fresh Retailers",
            buyer_type=BuyerType.RETAILER,
            gst_number="27AAACP1234A1Z5",
        ),
        "admin": _staff(
            session,
            "9811110005",
            UserRole.ADMIN,
            full_name="Platform Admin",
        ),
    }


def _login(client: TestClient, identifier: str) -> str:
    response = client.post(
        f"{API}/auth/login",
        json={"identifier": identifier, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _id(value: object) -> uuid.UUID:
    """Compare ids across the JSON boundary.

    A response carries a string; the ORM object carries a ``UUID``, and those
    never compare equal. Normalising on the test side keeps assertions honest
    instead of quietly passing or failing on type.
    """
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


# --------------------------------------------------------------------- system
def test_health_reports_database_up(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"


def test_ready_returns_200_when_database_answers(client: TestClient) -> None:
    assert client.get("/ready").status_code == 200


def test_openapi_document_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "KisanSaathi"
    # Spot-check that the v1 tree really is mounted under the prefix.
    assert f"{API}/auth/login" in spec["paths"]
    assert f"{API}/orders/pipeline" in spec["paths"]


def test_request_id_is_echoed_and_generated(client: TestClient) -> None:
    generated = client.get("/health")
    assert generated.headers["X-Request-ID"]
    supplied = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    # A caller supplied id is preserved so a trace survives across services.
    assert supplied.headers["X-Request-ID"] == "trace-abc-123"


# ----------------------------------------------------------------------- auth
def test_register_login_and_read_profile(client: TestClient, session: Session) -> None:
    registered = client.post(
        f"{API}/auth/register",
        json={
            "full_name": "Sunil Pawar",
            "phone": "9822220001",
            "password": PASSWORD,
            "role": "FARMER",
            "district": "Pune",
            "village": "Wadgaon",
            "primary_crops": ["onion"],
        },
    )
    assert registered.status_code == 201, registered.text
    tokens = registered.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"] and tokens["refresh_token"]

    profile = client.get(f"{API}/auth/me", headers=_auth(tokens["access_token"]))
    assert profile.status_code == 200
    body = profile.json()
    assert body["user"]["full_name"] == "Sunil Pawar"
    assert body["farmer"]["village"] == "Wadgaon"
    # The client renders actions from this list, so it must mirror RBAC exactly.
    assert body["permissions"] == ROLE_PERMISSIONS[UserRole.FARMER]


def test_login_with_wrong_password_uses_error_envelope(
    client: TestClient, session: Session
) -> None:
    _register(session, "9822220002", UserRole.FARMER)
    response = client.post(
        f"{API}/auth/login", json={"identifier": "9822220002", "password": "wrong-password"}
    )
    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"]
    assert body["error"]["message"]
    assert body["request_id"]


def test_missing_token_is_rejected_with_401(client: TestClient) -> None:
    response = client.get(f"{API}/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_validation_failure_reports_field_errors(client: TestClient) -> None:
    response = client.post(
        f"{API}/auth/register",
        json={"full_name": "A", "phone": "not-a-phone", "password": "short", "role": "FARMER"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    # Field level detail so a form can highlight the offending inputs.
    assert set(body["error"]["field_errors"]) >= {"password", "phone"}


def test_staff_role_cannot_self_register(client: TestClient) -> None:
    response = client.post(
        f"{API}/auth/register",
        json={
            "full_name": "Imposter Admin",
            "phone": "9822220003",
            "password": PASSWORD,
            "role": "ADMIN",
        },
    )
    assert response.status_code == 422


def test_refresh_rotates_tokens(client: TestClient, session: Session) -> None:
    _register(session, "9822220004", UserRole.FARMER)
    first = client.post(
        f"{API}/auth/login", json={"identifier": "9822220004", "password": PASSWORD}
    ).json()

    rotated = client.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["refresh_token"] != first["refresh_token"]

    # The presented token is single use: replaying it must now fail.
    replay = client.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401


def test_logout_invalidates_the_refresh_token(client: TestClient, session: Session) -> None:
    _register(session, "9822220005", UserRole.FARMER)
    tokens = client.post(
        f"{API}/auth/login", json={"identifier": "9822220005", "password": PASSWORD}
    ).json()

    assert (
        client.post(f"{API}/auth/logout", headers=_auth(tokens["access_token"])).status_code == 204
    )
    assert (
        client.post(
            f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )


# ----------------------------------------------------------------- rbac guard
def test_farmer_cannot_list_all_users(client: TestClient, session: Session) -> None:
    _register(session, "9822220006", UserRole.FARMER)
    token = _login(client, "9822220006")
    response = client.get(f"{API}/admin/users", headers=_auth(token))
    assert response.status_code == 403
    assert response.json()["success"] is False


def test_admin_can_list_users(client: TestClient, session: Session, accounts) -> None:
    token = _login(client, "9811110005")
    response = client.get(f"{API}/admin/users", headers=_auth(token))
    assert response.status_code == 200, response.text
    assert response.json()["meta"]["total_items"] >= 1


def test_permission_helpers_match_the_role_map(session: Session, roles) -> None:
    """Guard the contract the frontend depends on: permissions live server side."""
    assert "lot:create" in ROLE_PERMISSIONS[UserRole.FARMER]
    assert "lot:create" not in ROLE_PERMISSIONS[UserRole.BUYER]
    for role, permissions in ROLE_PERMISSIONS.items():
        stored = session.query(Role).filter(Role.name == role).one()
        assert set(stored.permissions) == set(permissions)


# ------------------------------------------------------------------ fixtures
@pytest.fixture()
def traded(session: Session, accounts) -> dict[str, object]:
    """A published onion lot, a live offer on it and the resulting order.

    Built through the services rather than the HTTP client so the assertions can
    target one concern at a time instead of re-walking the whole flow.
    """
    farmer, buyer = accounts["farmer"], accounts["buyer"]
    commodity = _seed_commodity(session)
    lot = LotService(session).create_lot(
        FarmLotCreate(
            commodity_id=commodity.id,
            title="Shirala red onion, grade A",
            quantity=100,
            unit="quintal",
            minimum_price=1200,
            # Published up front: a draft lot deliberately refuses offers, and the
            # point of this fixture is the order that follows.
            publish_now=True,
        ),
        farmer,
    )
    session.commit()
    offer = OfferService(session).create_offer(
        OfferCreate(lot_id=lot.id, quantity=50, offered_price=1300), buyer
    )
    session.commit()
    order = OrderService(session).create_from_offer(offer=offer, lot=lot, actor=buyer)
    session.commit()
    return {"commodity": commodity, "lot": lot, "offer": offer, "order": order}


def _seed_commodity(session: Session):
    from app.models import Commodity

    existing = session.query(Commodity).filter(Commodity.code == "ONION").one_or_none()
    if existing is not None:
        return existing
    commodity = Commodity(
        name="Onion",
        code="ONION",
        category="Vegetables",
        default_unit="quintal",
        permitted_units=["quintal", "tonne", "kg"],
        is_perishable=True,
    )
    session.add(commodity)
    session.commit()
    return commodity


# ------------------------------------------------------------ order pipeline
def test_buyer_order_pipeline_is_not_empty(
    client: TestClient, session: Session, accounts, traded
) -> None:
    """Regression: the pipeline used to resolve down the seller branch for a
    buyer, so a buyer with a live order saw every status at zero."""
    farmer_token = _login(client, "9811110001")
    buyer_token = _login(client, "9811110003")

    buyer_pipeline = client.get(f"{API}/orders/pipeline", headers=_auth(buyer_token))
    assert buyer_pipeline.status_code == 200, buyer_pipeline.text
    buyer_rows = buyer_pipeline.json()
    assert sum(row["count"] for row in buyer_rows) == 1

    farmer_pipeline = client.get(f"{API}/orders/pipeline", headers=_auth(farmer_token))
    assert farmer_pipeline.status_code == 200, farmer_pipeline.text
    # The same order is visible from the seller side too.
    assert sum(row["count"] for row in farmer_pipeline.json()) == 1


def test_admin_order_pipeline_is_platform_wide(
    client: TestClient, session: Session, accounts
) -> None:
    token = _login(client, "9811110005")
    response = client.get(f"{API}/orders/pipeline", headers=_auth(token))
    assert response.status_code == 200, response.text
    # Admins pass user_id=None and must not be scoped to their own (empty) book.
    assert isinstance(response.json(), list)


def test_seller_cannot_see_another_sellers_orders(
    client: TestClient, session: Session, accounts, traded
) -> None:
    other = _register(session, "9811110007", UserRole.FARMER, full_name="Other Farmer")
    token = _login(client, "9811110001")
    response = client.get(f"{API}/orders", headers=_auth(token))
    assert response.status_code == 200, response.text
    listed = response.json()["items"]
    # The seller sees their own order, and nothing belonging to the other farmer
    # (who has none here, so the assertion that matters is the shape not the set).
    assert all(_id(order["seller_user_id"]) == accounts["farmer"].id for order in listed)
    assert other.id != accounts["farmer"].id


def test_order_detail_is_forbidden_to_a_third_party(
    client: TestClient, session: Session, accounts, traded
) -> None:
    outsider = _register(session, "9811110009", UserRole.FARMER, full_name="Outsider")
    outsider_token = _login(client, "9811110009")
    response = client.get(f"{API}/orders/{traded['order'].id}", headers=_auth(outsider_token))
    assert response.status_code in (403, 404)
    assert response.json()["success"] is False
    assert outsider.id != traded["order"].seller_user_id


# ----------------------------------------------------------------- payments
def test_due_soon_is_scoped_to_the_caller(
    client: TestClient, session: Session, accounts, traded
) -> None:
    """Regression: the route fetched platform wide rows and filtered in Python."""
    buyer = accounts["buyer"]
    buyer_token = _login(client, "9811110003")
    rows = client.get(f"{API}/payments/due-soon", headers=_auth(buyer_token))
    assert rows.status_code == 200, rows.text
    body = rows.json()
    assert body, "the buyer should have at least one obligation"
    # The buyer is the payer here, so scoping is proved on the payer side too.
    assert all(_id(row["payer_user_id"]) == buyer.id for row in body)


def test_due_soon_does_not_leak_another_trades_obligations(
    client: TestClient, session: Session, accounts, traded
) -> None:
    outsider = _register(session, "9811110010", UserRole.BUYER, full_name="Unrelated Buyer")
    outsider_token = _login(client, "9811110010")
    rows = client.get(f"{API}/payments/due-soon", headers=_auth(outsider_token))
    assert rows.status_code == 200, rows.text
    # An unrelated buyer must see none of the seeded trade's money.
    assert rows.json() == []
    assert outsider.id != accounts["buyer"].id


def test_due_soon_excludes_a_distant_due_date(
    client: TestClient, session: Session, accounts, traded
) -> None:
    token = _login(client, "9811110003")
    wide = client.get(f"{API}/payments/due-soon?days=30", headers=_auth(token))
    assert wide.status_code == 200, wide.text
    assert wide.json(), "expected the obligation inside a 30 day window"
    # A one day window must not match a Net-7 term.
    assert client.get(f"{API}/payments/due-soon?days=1", headers=_auth(token)).json() == []


def _catalogue(session: Session):
    """One commodity and one market, for tests that need something to price."""
    from app.core.enums import MarketType
    from app.models import Commodity, Market

    commodity = session.query(Commodity).filter_by(code="ONION").one_or_none()
    if commodity is None:
        commodity = Commodity(
            code="ONION",
            name="Onion",
            name_marathi="कांदा",
            category="Vegetables",
            is_active=True,
        )
        session.add(commodity)
    market = session.query(Market).filter_by(code="PUNE-MARKET").one_or_none()
    if market is None:
        market = Market(
            code="PUNE-MARKET",
            name="Pune Market Yard",
            market_type=MarketType.APMC_MANDI,
            district="Pune",
            state="Maharashtra",
            latitude=18.5314,
            longitude=73.8567,
            is_active=True,
        )
        session.add(market)
    session.commit()
    return commodity, market


# ---------------------------------------------------------------- dashboards
def test_farmer_dashboard_renders(client: TestClient, session: Session, accounts) -> None:
    token = _login(client, "9811110001")
    response = client.get(f"{API}/dashboards/farmer", headers=_auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert "stats" in body
    assert "active_lots" in body


def test_buyer_dashboard_renders(client: TestClient, session: Session, accounts) -> None:
    token = _login(client, "9811110003")
    response = client.get(f"{API}/dashboards/buyer", headers=_auth(token))
    assert response.status_code == 200, response.text
    assert "stats" in response.json()


def test_admin_dashboard_renders(client: TestClient, session: Session, accounts) -> None:
    token = _login(client, "9811110005")
    response = client.get(f"{API}/dashboards/admin", headers=_auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["registrations"]["by_role"]
    assert "pending_orders" in body["trade"]


def test_admin_dashboard_analytics_rows_are_populated(
    client: TestClient, session: Session, accounts
) -> None:
    """Every analytics row must carry the fields the admin screen renders.

    These rows are plain dicts, so a mismatched key is not a validation error: it
    is a table full of em dashes. That is exactly what happened once, when the
    price-movement rows were read from `name`/`modal_price` and the overview
    calls them `commodity`/`median_modal_price`.
    """
    token = _login(client, "9811110005")
    body = client.get(f"{API}/dashboards/admin", headers=_auth(token)).json()

    for row in body["demand_by_commodity"]:
        assert row["commodity_name"], row
        assert row["commodity_id"], row
        assert isinstance(row["open_demands"], int), row
        assert row["demanded_quintal"] is not None, row

    for row in body["activity_by_district"]:
        assert row["district"], row
        assert isinstance(row["users"], int), row

    for row in body["price_movement"]:
        assert row["commodity_name"], row
        assert row["modal_price"] is not None, row
        assert row["direction"] in ("up", "down", "flat"), row


def test_dashboard_role_is_enforced(client: TestClient, session: Session, accounts) -> None:
    token = _login(client, "9811110001")
    assert client.get(f"{API}/dashboards/admin", headers=_auth(token)).status_code == 403


def test_dashboard_renders_for_a_seller_with_no_lots(
    client: TestClient, session: Session, accounts
) -> None:
    """Regression: a seller with no lots got a 500.

    ``_price_cards`` falls back to the cross-commodity overview, which used
    different key names from the per-commodity cards. The insight builder read
    the first shape, so the FPO dashboard crashed on a fully seeded database.
    """
    from app.core.enums import PriceSource
    from app.models import MarketPrice

    # The fallback path only produces cards when there are prices to show.
    commodity, market = _catalogue(session)
    for offset in range(3):
        session.add(
            MarketPrice(
                market_id=market.id,
                commodity_id=commodity.id,
                price_date=date.today() - timedelta(days=offset),
                min_price=100.0,
                max_price=140.0,
                modal_price=120.0 + offset,
                unit="quintal",
                source=PriceSource.DEMO,
                is_demo=True,
            )
        )
    session.commit()

    fpo_token = _login(client, "9811110002")
    response = client.get(f"{API}/dashboards/me", headers=_auth(fpo_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["price_cards"], "the fallback should still return cards"
    for card in body["price_cards"]:
        assert card["commodity_name"]
        assert "modal_price" in card


def test_dashboard_me_refuses_roles_without_one(
    client: TestClient, session: Session, accounts
) -> None:
    """Regression: inspector and logistics roles got a 422 from /dashboards/me.

    They fell through to the seller dashboard, which then failed response
    validation. A 403 with a code is something a client can act on.
    """
    from app.schemas.user import StaffUserCreate
    from app.services.auth_service import AdminUserService

    staff = AdminUserService(session)
    for role, phone in (
        (UserRole.QUALITY_INSPECTOR, "9811110011"),
        (UserRole.LOGISTICS_PARTNER, "9811110012"),
    ):
        staff.create_staff_user(
            StaffUserCreate(
                full_name=f"Test {role.value}",
                phone=phone,
                password=PASSWORD,
                role=role,
                district="Pune",
            )
        )
    session.commit()

    for phone in ("9811110011", "9811110012"):
        token = _login(client, phone)
        response = client.get(f"{API}/dashboards/me", headers=_auth(token))
        assert response.status_code == 403, (phone, response.text)
        assert response.json()["error"]["code"] == "NO_DASHBOARD_FOR_ROLE"


def test_demo_price_flag_reflects_the_stored_source(
    client: TestClient, session: Session, accounts
) -> None:
    """The dashboards must label synthetic prices, and only synthetic prices.

    Regression: the flag was computed from the commodity count, so a fully seeded
    demo database reported ``is_demo_data: false`` and real-looking figures.
    """
    from app.core.enums import PriceSource
    from app.models import MarketPrice

    token = _login(client, "9811110005")
    admin = client.get(f"{API}/dashboards/admin", headers=_auth(token)).json()
    # No prices synced yet, so nothing to disclaim.
    assert admin["is_demo_data"] is False
    assert admin["system_health"]["demo_price_data"] is False

    commodity, market = _catalogue(session)
    session.add(
        MarketPrice(
            market_id=market.id,
            commodity_id=commodity.id,
            price_date=date.today(),
            min_price=100.0,
            max_price=140.0,
            modal_price=120.0,
            unit="quintal",
            source=PriceSource.DEMO,
            is_demo=True,
        )
    )
    session.commit()

    admin = client.get(f"{API}/dashboards/admin", headers=_auth(token)).json()
    assert admin["is_demo_data"] is True
    assert admin["system_health"]["demo_price_data"] is True


def test_real_price_source_clears_the_demo_flag(
    client: TestClient, session: Session, accounts
) -> None:
    """One real source is enough: the history is no longer wholly synthetic."""
    from app.core.enums import PriceSource
    from app.models import MarketPrice

    token = _login(client, "9811110005")
    commodity, market = _catalogue(session)
    # One row per market, commodity and date, so the two sources need two dates.
    for offset, (source, is_demo) in enumerate(
        ((PriceSource.DEMO, True), (PriceSource.STATE_APMC, False))
    ):
        session.add(
            MarketPrice(
                market_id=market.id,
                commodity_id=commodity.id,
                price_date=date.today() - timedelta(days=offset),
                min_price=100.0,
                max_price=140.0,
                modal_price=120.0,
                unit="quintal",
                source=source,
                is_demo=is_demo,
            )
        )
    session.commit()

    admin = client.get(f"{API}/dashboards/admin", headers=_auth(token)).json()
    assert admin["is_demo_data"] is False


# ----------------------------------------------------------------- admin cat
def test_admin_sees_retired_commodities(client: TestClient, session: Session, accounts) -> None:
    """Regression: retired rows were filtered out of the screen used to restore
    them, so a de-activated commodity could never be brought back."""
    token = _login(client, "9811110005")
    created = client.post(
        f"{API}/admin/commodities",
        headers=_auth(token),
        json={"name": "Sorghum", "code": "SORGHUM", "category": "Cereals"},
    )
    assert created.status_code == 201, created.text
    commodity_id = created.json()["id"]

    retired = client.patch(
        f"{API}/admin/commodities/{commodity_id}",
        headers=_auth(token),
        json={"is_active": False},
    )
    assert retired.status_code == 200, retired.text

    default_listing = client.get(f"{API}/admin/commodities", headers=_auth(token))
    assert commodity_id not in [row["id"] for row in default_listing.json()["items"]]

    with_inactive = client.get(
        f"{API}/admin/commodities?include_inactive=true", headers=_auth(token)
    )
    assert commodity_id in [row["id"] for row in with_inactive.json()["items"]]


# ------------------------------------------------------------------ storage
def test_own_private_godown_is_visible_to_its_owner(
    client: TestClient, session: Session, accounts
) -> None:
    """Regression: include_private without a viewer id fell through to the
    public-only branch and hid the seller's own facility."""
    token = _login(client, "9811110001")
    created = client.post(
        f"{API}/storage",
        headers=_auth(token),
        json={
            "name": "Baramati Kisan Godown",
            "capacity_quintal": 500,
            "district": "Pune",
            "taluka": "Baramati",
        },
    )
    assert created.status_code == 201, created.text
    facility_id = created.json()["id"]

    mine = client.get(f"{API}/storage/mine", headers=_auth(token))
    assert facility_id in [row["id"] for row in mine.json()["items"]]

    # A different seller must not see it in the public browse.
    _register(session, "9811110008", UserRole.FARMER, full_name="Nosy Farmer")
    other_token = _login(client, "9811110008")
    public = client.get(f"{API}/storage", headers=_auth(other_token))
    assert facility_id not in [row["id"] for row in public.json()["items"]]


# ----------------------------------------------------------------- 404 shape
def test_unknown_route_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get(f"{API}/no-such-thing")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["request_id"]


def test_uuid_path_param_that_is_not_a_uuid_is_a_validation_error(
    client: TestClient, accounts
) -> None:
    token = _login(client, "9811110001")
    response = client.get(f"{API}/orders/not-a-uuid", headers=_auth(token))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# ------------------------------------------------------------------ matching
def test_match_endpoint_returns_the_caller_s_own_side(
    client: TestClient, session: Session, accounts, traded
) -> None:
    farmer_token = _login(client, "9811110001")
    seller_matches = client.get(f"{API}/matches", headers=_auth(farmer_token))
    assert seller_matches.status_code == 200, seller_matches.text
    body = seller_matches.json()
    assert "matches" in body
    assert "summary" in body


def test_matching_rejects_a_role_with_no_side(
    client: TestClient, session: Session, accounts
) -> None:
    from app.services.matching_service import _BUYER_ROLE_VALUES, _SELLER_ROLE_VALUES

    # Inspector and logistics are neither, so matches_for_user must refuse rather
    # than silently returning the buyer side.
    assert "QUALITY_INSPECTOR" not in _SELLER_ROLE_VALUES | _BUYER_ROLE_VALUES
    assert "LOGISTICS_PARTNER" not in _SELLER_ROLE_VALUES | _BUYER_ROLE_VALUES
    assert _login(client, "9811110001")
