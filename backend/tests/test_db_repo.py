"""Tests for SessionRepository (issue phase-1.15).

Covers the chat-flow round-trips: create a session, append ordered messages, load history
in order, record a tool call + its result, update session/tool-call status. In-memory
aiosqlite (StaticPool) with the FK pragma enabled.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from skoll.db.engine import _register_sqlite_pragmas
from skoll.db.models import Base
from skoll.db.repo import SessionRepository, new_id
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    _register_sqlite_pragmas(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, expire_on_commit=False
    )
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def repo() -> SessionRepository:
    return SessionRepository()


def test_new_id_is_uuid4() -> None:
    import uuid

    parsed = uuid.UUID(new_id())
    assert parsed.version == 4


async def test_create_and_get_session(db: AsyncSession, repo: SessionRepository) -> None:
    sess = await repo.create_session(
        db,
        model="qwen2.5-coder-32b",
        title="hello",
        auto_approve={"read_file": True},
        system_prompt_overrides={"tone": "terse"},
    )
    assert sess.id
    assert sess.state == "idle"
    # JSON columns serialised correctly.
    assert json.loads(sess.auto_approve) == {"read_file": True}
    assert sess.system_prompt_overrides is not None
    assert json.loads(sess.system_prompt_overrides) == {"tone": "terse"}

    fetched = await repo.get_session(db, sess.id)
    assert fetched is not None
    assert fetched.id == sess.id
    assert fetched.title == "hello"


async def test_get_missing_session_returns_none(db: AsyncSession, repo: SessionRepository) -> None:
    assert await repo.get_session(db, "does-not-exist") is None


async def test_append_messages_and_load_ordered_history(
    db: AsyncSession, repo: SessionRepository
) -> None:
    sess = await repo.create_session(db, model="m")

    m1 = await repo.append_message(
        db, session_id=sess.id, role="user", iteration=0, content="first"
    )
    m2 = await repo.append_message(
        db, session_id=sess.id, role="assistant", iteration=1, content="second"
    )
    m3 = await repo.append_message(
        db,
        session_id=sess.id,
        role="tool",
        iteration=1,
        content='{"ok":true}',
        tool_call_id="tc-1",
    )

    history = await repo.load_history(db, sess.id)
    assert [m.id for m in history] == [m1.id, m2.id, m3.id]
    assert [m.role for m in history] == ["user", "assistant", "tool"]
    assert history[0].content == "first"
    assert history[2].tool_call_id == "tc-1"


async def test_append_message_bad_session_raises_integrity_error(
    db: AsyncSession, repo: SessionRepository
) -> None:
    with pytest.raises(IntegrityError):
        await repo.append_message(db, session_id="ghost", role="user", iteration=0, content="x")


async def test_record_tool_call_and_result_roundtrip(
    db: AsyncSession, repo: SessionRepository
) -> None:
    sess = await repo.create_session(db, model="m")
    msg = await repo.append_message(db, session_id=sess.id, role="assistant", iteration=1)

    tc = await repo.record_tool_call(
        db,
        tool_call_id="call_abc",
        message_id=msg.id,
        session_id=sess.id,
        name="codebase_search",
        arguments={"query": "where is foo"},
        requires_approval=True,
    )
    assert tc.id == "call_abc"
    assert tc.status == "ready"
    assert tc.requires_approval == 1
    assert json.loads(tc.arguments) == {"query": "where is foo"}

    updated = await repo.record_tool_result(
        db,
        "call_abc",
        result={"hits": [1, 2, 3]},
        duration_ms=42,
    )
    assert updated is not None
    assert updated.status == "completed"
    assert updated.duration_ms == 42
    assert updated.result is not None
    assert json.loads(updated.result) == {"hits": [1, 2, 3]}
    assert updated.error is None


async def test_record_tool_call_accepts_raw_json_string(
    db: AsyncSession, repo: SessionRepository
) -> None:
    """The SSE accumulator passes args as an already-serialised string."""
    sess = await repo.create_session(db, model="m")
    msg = await repo.append_message(db, session_id=sess.id, role="assistant", iteration=1)
    tc = await repo.record_tool_call(
        db,
        tool_call_id="call_raw",
        message_id=msg.id,
        session_id=sess.id,
        name="read_file",
        arguments='{"path":"a.py"}',
    )
    assert tc.arguments == '{"path":"a.py"}'


async def test_record_tool_result_unknown_id_returns_none(
    db: AsyncSession, repo: SessionRepository
) -> None:
    assert await repo.record_tool_result(db, "missing", result={"x": 1}) is None


async def test_record_tool_result_failure_path(db: AsyncSession, repo: SessionRepository) -> None:
    sess = await repo.create_session(db, model="m")
    msg = await repo.append_message(db, session_id=sess.id, role="assistant", iteration=1)
    await repo.record_tool_call(
        db,
        tool_call_id="call_fail",
        message_id=msg.id,
        session_id=sess.id,
        name="run_bash",
        arguments="{}",
        status="executing",
    )
    updated = await repo.record_tool_result(db, "call_fail", error="boom", status="failed")
    assert updated is not None
    assert updated.status == "failed"
    assert updated.error == "boom"
    assert updated.result is None


async def test_update_session_state_and_iteration(
    db: AsyncSession, repo: SessionRepository
) -> None:
    sess = await repo.create_session(db, model="m")
    await repo.update_session_state(db, sess.id, state="running", last_iteration=3)
    refreshed = await repo.get_session(db, sess.id)
    assert refreshed is not None
    await db.refresh(refreshed)
    assert refreshed.state == "running"
    assert refreshed.last_iteration == 3


async def test_set_tool_call_status_approval_fields(
    db: AsyncSession, repo: SessionRepository
) -> None:
    sess = await repo.create_session(db, model="m")
    msg = await repo.append_message(db, session_id=sess.id, role="assistant", iteration=1)
    tc = await repo.record_tool_call(
        db,
        tool_call_id="call_appr",
        message_id=msg.id,
        session_id=sess.id,
        name="write_file",
        arguments="{}",
        status="awaiting_approval",
        requires_approval=True,
    )
    await repo.set_tool_call_status(
        db, tc.id, status="approved", approved_by="user", approved_at="2026-05-29 00:00:00"
    )
    await db.refresh(tc)
    assert tc.status == "approved"
    assert tc.approved_by == "user"


async def test_list_sessions_returns_all(db: AsyncSession, repo: SessionRepository) -> None:
    for _ in range(3):
        await repo.create_session(db, model="m")
    sessions = await repo.list_sessions(db, limit=10)
    assert len(sessions) == 3


async def test_invalid_enum_values_raise_value_error(
    db: AsyncSession, repo: SessionRepository
) -> None:
    with pytest.raises(ValueError, match="invalid session state"):
        await repo.create_session(db, model="m", state="bogus")
    sess = await repo.create_session(db, model="m")
    with pytest.raises(ValueError, match="invalid message role"):
        await repo.append_message(db, session_id=sess.id, role="bogus", iteration=0)
