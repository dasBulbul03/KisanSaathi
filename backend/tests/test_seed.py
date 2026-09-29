"""Tests for the database seeder.

The seeder is the first thing anyone runs, so its contract is worth pinning down:
it must be repeatable, it must not invent a second copy of anything, and it must
produce a database the app can actually serve.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import OrderStatus, UserRole, VerificationStatus
from app.core.rbac import ROLE_PERMISSIONS
from app.db.seed import DEMO_ACCOUNTS, DEMO_DEMANDS, DEMO_LOTS, DEMO_PASSWORD, seed_all
from app.db.seed_data import COMMODITIES, MARKETS
from app.models import (
    BuyerDemand,
    BuyerProfile,
    Commodity,
    FarmLot,
    Market,
    MarketDataSyncLog,
    MarketPrice,
    Order,
    QualityAttribute,
    Role,
    StorageFacility,
    Transaction,
    User,
)


def _count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def _seeded(session: Session) -> dict:
    return seed_all(session, price_days=7)


class TestReferenceData:
    def test_seed_data_codes_are_unique(self) -> None:
        """Codes are the join key for collected price history, so they are stable."""
        commodity_codes = [c.code for c in COMMODITIES]
        market_codes = [m.code for m in MARKETS]
        assert len(commodity_codes) == len(set(commodity_codes))
        assert len(market_codes) == len(set(market_codes))

    def test_commodity_codes_are_upper_snake(self) -> None:
        for seed in COMMODITIES:
            assert seed.code == seed.code.upper()
            assert " " not in seed.code and "-" not in seed.code

    def test_grade_thresholds_are_ordered(self) -> None:
        """Grade thresholds mean "at or above", so they exist only where that is true.

        For a lower-is-better parameter (rot, moisture, impurity) a threshold
        would grade the worst produce as Grade A, so none may be set.
        """
        for seed in COMMODITIES:
            for attribute in seed.attributes:
                assert attribute.ideal_min <= attribute.ideal_max, attribute.code
                if not attribute.higher_is_better:
                    assert attribute.grade_a_min is None, attribute.code
                    assert attribute.grade_b_min is None, attribute.code
                    continue
                assert attribute.grade_a_min is not None, attribute.code
                assert attribute.grade_b_min is not None, attribute.code
                assert attribute.ideal_min <= attribute.grade_b_min <= attribute.grade_a_min
                assert attribute.grade_a_min <= attribute.ideal_max, attribute.code

    def test_catalogue_is_created(self, session: Session) -> None:
        report = _seeded(session)
        assert report["commodities"] == len(COMMODITIES)
        assert report["markets"] == len(MARKETS)
        assert _count(session, Commodity) == len(COMMODITIES)
        assert _count(session, Market) == len(MARKETS)

    def test_every_commodity_has_quality_attributes(self, session: Session) -> None:
        _seeded(session)
        with_attrs = session.execute(
            select(func.count(func.distinct(QualityAttribute.commodity_id)))
        ).scalar_one()
        assert with_attrs == len(COMMODITIES)
        # Two per commodity is the floor: the auto-grader needs parameters to judge.
        assert _count(session, QualityAttribute) >= 2 * len(COMMODITIES)

    def test_roles_match_the_code_permission_matrix(self, session: Session) -> None:
        _seeded(session)
        rows = session.execute(select(Role)).scalars().all()
        assert {r.name for r in rows} == set(UserRole)
        for row in rows:
            assert list(row.permissions) == list(ROLE_PERMISSIONS[row.name])

    def test_no_demo_flag_skips_accounts_and_prices(self, session: Session) -> None:
        report = seed_all(session, include_demo=False)
        assert report["accounts_created"] == 0
        assert report["traded"] is False
        assert _count(session, User) == 0
        assert _count(session, MarketPrice) == 0
        # Reference data is still there: an unseeded catalogue is not a useful start.
        assert _count(session, Commodity) == len(COMMODITIES)


class TestDemoAccounts:
    def test_all_demo_accounts_exist_and_can_authenticate(self, session: Session) -> None:
        """The printed credentials are only useful if they actually sign in."""
        from app.schemas.user import LoginRequest
        from app.services.auth_service import AuthService

        _seeded(session)
        assert _count(session, User) == len(DEMO_ACCOUNTS)
        service = AuthService(session)
        for spec in DEMO_ACCOUNTS:
            user, tokens = service.login(
                LoginRequest(identifier=spec["phone"], password=DEMO_PASSWORD)
            )
            assert tokens.access_token
            assert user.full_name == spec["full_name"]

    def test_every_role_is_represented(self, session: Session) -> None:
        _seeded(session)
        roles = {user.primary_role.name for user in session.execute(select(User)).scalars().all()}
        assert roles == set(UserRole)

    def test_buyers_start_unverified(self, session: Session, roles: dict[UserRole, Role]) -> None:
        """Verification is an admin action, so the seeder must not pre-approve buyers."""
        _seeded(session)
        rows = (
            session.execute(
                select(BuyerProfile).where(
                    BuyerProfile.user_id.in_(
                        select(User.id).where(User.primary_role_id == roles[UserRole.BUYER].id)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        assert all(r.verification_status is VerificationStatus.PENDING for r in rows)

    def test_farmer_profiles_are_created(self, session: Session) -> None:
        from app.models import FarmerProfile

        _seeded(session)
        assert _count(session, FarmerProfile) >= 2


class TestDemoWorkflow:
    def test_full_trade_path_exists(self, session: Session) -> None:
        report = _seeded(session)
        assert report["traded"] is True
        # One published lot per demo farmer, so no account signs in to an empty app.
        assert report["lots"] == len(DEMO_LOTS)
        assert report["demands"] == len(DEMO_DEMANDS)
        order = session.execute(select(Order)).scalar_one()
        transaction = session.execute(select(Transaction)).scalar_one()
        assert transaction.order_id == order.id
        assert order.total_value > 0

    def test_the_trade_owner_is_the_first_farmer_listed(self, session: Session) -> None:
        """The demo order must belong to the account the README lists first."""
        _seeded(session)
        order = session.execute(select(Order)).scalar_one()
        seller = session.get(User, order.seller_user_id)
        assert seller is not None
        assert seller.phone == DEMO_LOTS[0]["phone"] == DEMO_ACCOUNTS[1]["phone"]
        assert DEMO_LOTS[0]["phone"] == "9000000002"

    def test_every_farmer_account_has_a_lot(self, session: Session) -> None:
        _seeded(session)
        farmer_ids = [
            row.id
            for row in session.execute(
                select(User).where(User.primary_role.has(name=UserRole.FARMER))
            )
            .unique()
            .scalars()
        ]
        assert len(farmer_ids) == 2
        lots = session.execute(select(FarmLot.seller_user_id)).scalars().all()
        assert set(lots) == set(farmer_ids)

    def test_every_buyer_account_has_a_demand(self, session: Session) -> None:
        _seeded(session)
        demand_buyers = set(session.execute(select(BuyerDemand.buyer_user_id)).scalars())
        assert len(demand_buyers) == len(DEMO_DEMANDS)

    def test_order_sits_mid_pipeline(self, session: Session) -> None:
        """A demo order at a mid state is demonstrable; one at creation is not."""
        from app.services.order_service import ORDER_TRANSITIONS

        _seeded(session)
        order = session.execute(select(Order)).scalar_one()
        assert order.status is OrderStatus.PICKUP_SCHEDULED
        assert ORDER_TRANSITIONS[order.status], "the demo order must have a next step"

    def test_storage_covers_private_and_shared(self, session: Session) -> None:
        _seeded(session)
        facilities = session.execute(select(StorageFacility)).scalars().all()
        assert len(facilities) == 2
        assert {f.is_private for f in facilities} == {True, False}
        for facility in facilities:
            assert facility.capacity_quintal > facility.occupied_quintal

    def test_price_history_is_generated_through_the_sync_service(self, session: Session) -> None:
        report = _seeded(session)
        assert report["price_rows"] == len(COMMODITIES) * len(MARKETS) * 7
        log = session.execute(select(MarketDataSyncLog)).scalar_one()
        assert log.status == "SUCCESS"
        assert log.records_inserted == report["price_rows"]

    def test_prices_cover_several_days_per_market(self, session: Session) -> None:
        """Price discovery charts need a series, not one point per market."""
        _seeded(session)
        market = session.execute(select(Market).limit(1)).scalar_one()
        days = session.execute(
            select(func.count(func.distinct(MarketPrice.price_date))).where(
                MarketPrice.market_id == market.id
            )
        ).scalar_one()
        assert days == 7


class TestIdempotency:
    def test_second_run_creates_nothing_new(self, session: Session) -> None:
        first = _seeded(session)
        counts = {
            model: _count(session, model)
            for model in (Role, User, Commodity, Market, QualityAttribute, MarketPrice)
        }
        second = _seeded(session)
        assert second["roles_created"] == 0
        assert second["accounts_created"] == 0
        for model, before in counts.items():
            assert _count(session, model) == before, f"{model.__name__} was duplicated"
        assert first["traded"] is True and second["traded"] is True

    def test_second_run_does_not_duplicate_the_trade(self, session: Session) -> None:
        _seeded(session)
        _seeded(session)
        assert _count(session, Order) == 1
        assert _count(session, Transaction) == 1
        assert _count(session, FarmLot) == len(DEMO_LOTS)
        assert _count(session, BuyerDemand) == len(DEMO_DEMANDS)
        assert _count(session, StorageFacility) == 2

    def test_catalogue_edits_are_applied_not_reverted(self, session: Session) -> None:
        """Re-running is also how a release ships reference-data changes."""
        _seeded(session)
        onion = session.execute(select(Commodity).where(Commodity.code == "ONION")).scalar_one()
        onion.name = "Onion (edited)"
        session.flush()
        _seeded(session)
        assert onion.name == "Onion"


class TestUnmigratedDatabase:
    def test_clear_error_when_schema_is_missing(self, session: Session, monkeypatch) -> None:
        """An unmigrated database is a deployment mistake worth naming, not a stack trace."""
        from app.db import seed as seed_module

        monkeypatch.setattr(seed_module, "_existing_table_names", lambda _s: {"django_migrations"})
        with pytest.raises(SystemExit, match="alembic upgrade head"):
            seed_module._require_schema(session)

    def test_an_empty_database_is_left_to_alembic(self, session: Session, monkeypatch) -> None:
        """A fresh file database has no tables at all; that is not an error here."""
        from app.db import seed as seed_module

        monkeypatch.setattr(seed_module, "_existing_table_names", lambda _s: set())
        seed_module._require_schema(session)
