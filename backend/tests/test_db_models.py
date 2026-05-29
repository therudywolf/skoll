"""Tests for the SQLAlchemy models (issue phase-1.15).

Covers: table creation via ``Base.metadata.create_all`` on an aiosqlite engine, inserting
and querying a Workspace→Session→Message→ToolCall graph, FK enforcement, and ON DELETE
CASCADE / SET NULL behaviour. Also a schema-parity check that ``alembic upgrade head`` on a
tmp SQLite produces the same set of tables as ``Base.metadata``.

No external DB: in-memory aiosqlite (StaticPool keeps the single connection alive) for the
ORM tests, and a tmp-file SQLite for the Alembic parity test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from skoll.db.engine import _register_sqlite_pragmas
from skoll.db.models import (
    Attachment,
    Base,
    Message,
    Session,
    ToolCall,
    Workspace,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

# Resolved at import time so the parity test does no filesystem calls inline.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """In-memory aiosqlite engine with FK pragma enabled and all tables created."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    _register_sqlite_pragmas(eng)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, expire_on_commit=False
    )
    async with maker() as session:
        yield session


async def test_create_all_makes_every_table(engine: AsyncEngine) -> None:
    """All 10 schema.sql tables exist after create_all."""
    expected = {
        "workspaces",
        "sessions",
        "messages",
        "tool_calls",
        "attachments",
        "rag_chunks",
        "index_jobs",
        "approval_log",
        "preflight_log",
        "schema_meta",
    }
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        )
        names = {r[0] for r in rows}
    assert expected <= names


async def test_foreign_keys_are_enforced(db: AsyncSession) -> None:
    """The PRAGMA foreign_keys=ON listener rejects orphan rows."""
    db.add(Message(id="m-orphan", session_id="nope", role="user", iteration=0))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_insert_and_query_full_graph(db: AsyncSession) -> None:
    """Workspace→Session→Message→ToolCall round-trips and relationships resolve."""
    ws = Workspace(id="ws-1", name="demo", root_path="/abs/demo")
    sess = Session(id="s-1", model="qwen2.5-coder", workspace_id="ws-1")
    msg = Message(id="msg-1", session_id="s-1", role="assistant", iteration=1)
    tc = ToolCall(
        id="tc-1",
        message_id="msg-1",
        session_id="s-1",
        name="codebase_search",
        arguments='{"query":"x"}',
        status="ready",
    )
    db.add_all([ws, sess, msg, tc])
    await db.flush()
    db.expire_all()

    # Eager-load the relationship chain — async sessions cannot lazy-load on attribute
    # access, so the graph must be fetched up front with selectinload.
    stmt = (
        select(Session)
        .where(Session.id == "s-1")
        .options(
            selectinload(Session.workspace),
            selectinload(Session.messages).selectinload(Message.tool_calls),
        )
    )
    loaded = (await db.execute(stmt)).scalar_one()
    assert loaded.workspace is not None
    assert loaded.workspace.name == "demo"
    assert [m.id for m in loaded.messages] == ["msg-1"]
    assert loaded.messages[0].tool_calls[0].name == "codebase_search"
    # Server defaults populated on flush.
    assert loaded.state == "idle"
    assert loaded.auto_approve == "{}"
    assert loaded.last_iteration == 0
    assert loaded.created_at  # datetime('now') text


async def test_cascade_delete_session_removes_children(db: AsyncSession) -> None:
    """Deleting a session cascades to messages and tool_calls (ON DELETE CASCADE)."""
    sess = Session(id="s-2", model="m")
    msg = Message(id="msg-2", session_id="s-2", role="user", iteration=0)
    tc = ToolCall(
        id="tc-2",
        message_id="msg-2",
        session_id="s-2",
        name="read_file",
        arguments="{}",
        status="ready",
    )
    db.add_all([sess, msg, tc])
    await db.flush()

    # Use a Core DELETE so the DB-level cascade (not the ORM) is exercised.
    await db.execute(text("DELETE FROM sessions WHERE id = 's-2'"))
    await db.flush()
    db.expire_all()

    assert (await db.execute(select(Message).where(Message.session_id == "s-2"))).first() is None
    assert (await db.execute(select(ToolCall).where(ToolCall.session_id == "s-2"))).first() is None


async def test_attachment_message_set_null_on_message_delete(db: AsyncSession) -> None:
    """Deleting a message sets attachment.message_id to NULL (ON DELETE SET NULL)."""
    sess = Session(id="s-3", model="m")
    msg = Message(id="msg-3", session_id="s-3", role="user", iteration=0)
    att = Attachment(id="att-1", session_id="s-3", message_id="msg-3", kind="file", path="a.py")
    db.add_all([sess, msg, att])
    await db.flush()

    await db.execute(text("DELETE FROM messages WHERE id = 'msg-3'"))
    await db.flush()
    db.expire_all()

    reloaded = await db.get(Attachment, "att-1")
    assert reloaded is not None  # attachment survives
    assert reloaded.message_id is None  # FK nulled


async def test_check_constraints_reject_bad_enums(db: AsyncSession) -> None:
    """CHECK constraints from schema.sql reject out-of-domain values."""
    db.add(Session(id="s-bad", model="m", state="not-a-state"))
    with pytest.raises(IntegrityError):
        await db.flush()


def test_schema_parity_with_alembic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`alembic upgrade head` on a tmp DB yields the same tables as Base.metadata.

    Synchronous on purpose: ``command.upgrade`` drives env.py which calls ``asyncio.run``
    internally, so this test must NOT run inside an event loop. Alembic runs programmatically
    (no subprocess) against a tmp-file SQLite via ``SKOLL_DB_PATH`` so it exercises the exact
    env.py URL-resolution path.
    """
    import sqlite3

    import skoll.config as config_mod
    from alembic import command
    from alembic.config import Config

    db_file = tmp_path / "parity.sqlite"
    monkeypatch.setenv("SKOLL_DB_PATH", str(db_file))
    # Reset the cached settings singleton so env.py picks up the patched path.
    monkeypatch.setattr(config_mod, "_settings", None, raising=False)

    alembic_cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))

    command.upgrade(alembic_cfg, "head")

    con = sqlite3.connect(db_file)
    try:
        alembic_tables = {
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            )
        }
        # schema_meta seed rows from db/schema.sql must be present.
        meta = dict(con.execute("SELECT key, value FROM schema_meta").fetchall())
    finally:
        con.close()

    assert alembic_tables == set(Base.metadata.tables.keys())
    assert meta.get("schema_version") == "1"
    assert "created_at" in meta
