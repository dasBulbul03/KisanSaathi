"""Engine and session management."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_is_sqlite = False
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _build_engine() -> Engine:
    global _is_sqlite
    url = settings.resolved_database_url()
    _is_sqlite = url.startswith("sqlite")
    kwargs: dict = {"echo": settings.DB_ECHO, "future": True, "pool_pre_ping": True}
    if _is_sqlite:
        # A pooled SQLite connection can be handed to whichever worker thread
        # needs it next. The driver's own same-thread guard would reject that,
        # which breaks any threaded ASGI server and TestClient alike.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
        )
    engine = create_engine(url, **kwargs)
    if _is_sqlite:

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _build_engine()
        _SessionLocal = sessionmaker(
            bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False
        )
        logger.info("database.engine.ready", dialect=_engine.dialect.name)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def configure_for_tests(database_url: str) -> None:
    """Point the engine at a throwaway database (used by the test session)."""
    global _engine, _SessionLocal, _is_sqlite
    _is_sqlite = database_url.startswith("sqlite")
    _engine = create_engine(
        database_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False} if _is_sqlite else {},
    )
    if _is_sqlite:

        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    _SessionLocal = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request scoped session."""
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for scripts, seeders and background jobs."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - depends on infra
        logger.error("database.health.failed", error=str(exc))
        return False
