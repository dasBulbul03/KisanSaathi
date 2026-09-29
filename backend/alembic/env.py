"""Alembic runtime configuration.

The URL is taken from the application settings rather than ``alembic.ini`` so
that migrations and the app can never disagree about which database they are
talking to. ``sqlalchemy.url`` stays empty in the ini file for exactly that
reason: a stale hard-coded URL there is the classic way to migrate the wrong
database.

Metadata comes from ``Base.metadata``, so ``--autogenerate`` sees every model
without any per-module registration here.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

# Importing the models package attaches every model to Base.metadata, which is
# what makes ``--autogenerate`` able to see the schema. The noqa marks the
# import as intentional: nothing in this file references app.models directly.
import app.models  # noqa: F401
from alembic import context
from app.core.config import settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.resolved_database_url())

target_metadata = Base.metadata


#: Tables owned by the PostGIS extension rather than by this application.
#: Autogenerate must not try to create or drop them.
EXTERNAL_TABLES = frozenset({"spatial_ref_sys"})


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Keep Alembic's hands off anything that is not ours to migrate."""
    return not (type_ == "table" and name in EXTERNAL_TABLES)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    Used by ``alembic upgrade head --sql`` for review or for a DBA-run deploy.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        # Reuse the caller's connection: this is how the test suite runs
        # migrations inside a transaction it controls and rolls back.
        _configure(connectable)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        render_as_batch=connection.dialect.name == "sqlite",
    )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
