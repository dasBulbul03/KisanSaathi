"""Shared pytest fixtures.

Each test runs inside an outer connection-level transaction that is rolled back
at teardown, so tests stay isolated while still exercising real SQL (including
foreign keys and the SQLite/PostgreSQL type behaviour).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-kisansaathi-tests-only")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.core.enums import UserRole
from app.core.rbac import ROLE_DESCRIPTIONS, ROLE_PERMISSIONS
from app.db.base import Base
from app.db.session import get_engine
from app.models import Role


@pytest.fixture(scope="session", autouse=True)
def engine() -> Iterator[Engine]:
    """Create every table once; the in-memory SQLite DB lives with the engine."""
    eng = get_engine()

    # The pysqlite driver does not emit BEGIN for DDL/SELECT and commits DML on
    # its own, which breaks outer-transaction rollback. Hand transaction control
    # to SQLAlchemy so SAVEPOINT-based per-test isolation works.
    if eng.dialect.name == "sqlite":

        @event.listens_for(eng, "connect")
        def _disable_driver_autocommit(dbapi_connection, _record) -> None:
            # check_same_thread is already handled by the engine's connect_args.
            dbapi_connection.isolation_level = None

        @event.listens_for(eng, "begin")
        def _emit_begin(connection) -> None:
            connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture()
def session(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    outer = connection.begin()
    # ``create_savepoint`` keeps session.commit() inside the outer transaction,
    # which is what makes per-test rollback possible.
    factory = sessionmaker(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    db = factory()
    try:
        yield db
    finally:
        db.close()
        outer.rollback()
        connection.close()


@pytest.fixture()
def roles(session: Session) -> dict[UserRole, Role]:
    """Seed the six system roles required by ``AuthService``."""
    seeded: dict[UserRole, Role] = {}
    for role in UserRole:
        existing = session.query(Role).filter(Role.name == role).one_or_none()
        if existing is None:
            display_name, description = ROLE_DESCRIPTIONS.get(role, (role.value, ""))
            existing = Role(
                name=role,
                display_name=display_name,
                description=description,
                permissions=ROLE_PERMISSIONS.get(role, []),
            )
            session.add(existing)
            seeded[role] = existing
    session.commit()
    return seeded


@pytest.fixture()
def client(session: Session, roles) -> Iterator[TestClient]:
    """A TestClient wired to the same transactional session as the test.

    ``get_db`` is overridden so the app and the test share one session inside the
    outer transaction. Without this the app would open its own connection, the
    test's writes would be invisible to it, and the teardown rollback would not
    undo anything the app committed.
    """
    from app.db.session import get_db
    from app.main import create_app

    def _override_get_db():
        yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    # The lifespan only logs the dialect; nothing to do for an in-memory DB.
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
