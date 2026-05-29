"""Async SQLAlchemy engine + session factory (aiosqlite).

Issue: phase-1.15.

The engine is created from :class:`skoll.config.Settings` (``db_path``). SQLite does NOT
enforce foreign keys unless ``PRAGMA foreign_keys = ON`` is issued on every connection, so
we register a ``connect`` listener to set it — without this the ON DELETE CASCADE / SET NULL
rules in ``db/schema.sql`` would silently no-op. WAL journal mode is also set to match the
DDL's ``PRAGMA journal_mode = WAL`` (skipped automatically for in-memory test DBs).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from skoll.config import Settings, get_settings

__all__ = [
    "build_engine",
    "make_sessionmaker",
    "session_scope",
    "sqlite_url_from_path",
]


def sqlite_url_from_path(db_path: Path | str) -> str:
    """Build an aiosqlite URL from a filesystem path.

    Pass the literal string ``":memory:"`` for an in-memory database (used by tests).
    """
    if str(db_path) == ":memory:":
        return "sqlite+aiosqlite:///:memory:"
    # ``Path.as_posix`` keeps the URL well-formed on Windows (forward slashes).
    return f"sqlite+aiosqlite:///{Path(db_path).as_posix()}"


def _register_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Enforce foreign keys (+ WAL for file DBs) on every new connection."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, _record: Any) -> None:  # noqa: ANN401
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            # WAL is meaningless for ``:memory:`` and can error; only set it for files.
            if getattr(dbapi_connection, "database", None) not in (None, "", ":memory:"):
                cursor.execute("PRAGMA journal_mode = WAL")
        finally:
            cursor.close()


def build_engine(settings: Settings | None = None, *, echo: bool = False) -> AsyncEngine:
    """Create the async engine from settings (or the global singleton).

    Ensures the parent directory of a file-backed DB exists before connecting.
    """
    settings = settings or get_settings()
    db_path = settings.db_path
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(sqlite_url_from_path(db_path), echo=echo, future=True)
    _register_sqlite_pragmas(engine)
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build an ``async_sessionmaker`` bound to ``engine``.

    ``expire_on_commit=False`` keeps ORM instances usable after commit, which the SSE/chat
    flow relies on (it reads attributes off returned models after the unit of work closes).
    """
    return async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Transactional scope: commit on success, rollback on error, always close."""
    session = sessionmaker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
