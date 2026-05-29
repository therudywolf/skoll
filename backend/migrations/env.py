"""Alembic environment for Skoll (issue phase-1.15).

Async-aware: builds an aiosqlite engine whose URL comes from
:attr:`skoll.config.Settings.db_path` (overriding the placeholder in ``alembic.ini``).
``Base.metadata`` is the autogenerate target, so ``alembic revision --autogenerate`` and
the schema-parity test both see the ORM models in :mod:`skoll.db.models`.

NOTE: this module lives under ``backend/migrations/`` which is OUTSIDE the mypy ``files``
set (``backend/src``), so its looser Alembic-idiomatic typing does not affect
``mypy --strict src/skoll/db``. Keep migration code here, never under ``src/``.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from skoll.config import get_settings
from skoll.db.engine import sqlite_url_from_path
from skoll.db.models import Base

# Alembic Config object — access to values in alembic.ini.
config = context.config

# Override the placeholder URL with the runtime-resolved aiosqlite URL.
config.set_main_option("sqlalchemy.url", sqlite_url_from_path(get_settings().db_path))

# Set up Python logging from the .ini (if present).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate / parity target.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DBAPI connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite needs batch mode for ALTER operations
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # SQLite: enforce FKs and use batch mode for any future ALTERs.
    connection.exec_driver_sql("PRAGMA foreign_keys = ON")
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through a sync-bridged connection."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        # The aiosqlite connection holds the migration in an open transaction; commit it
        # explicitly so DDL + the schema_meta seed persist (run_sync does not auto-commit).
        await connection.commit()
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
