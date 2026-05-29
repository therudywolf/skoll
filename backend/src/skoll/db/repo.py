"""Repository: the persistence operations the agent / chat flow needs.

Issue: phase-1.15.

This is a thin data-access layer over the ORM models in :mod:`skoll.db.models`. It is
deliberately Pydantic-free — it returns ORM instances (or ``None``) and leaves DTO mapping
to the API layer. JSON-typed columns (``auto_approve``, tool ``arguments``/``result``,
``system_prompt_overrides``) are serialised here so callers pass/receive plain Python.

Every method takes an :class:`~sqlalchemy.ext.asyncio.AsyncSession`; the caller owns the
transaction boundary (see :func:`skoll.db.engine.session_scope`). Methods ``flush`` so that
autoincrement PKs / server defaults are populated on returned instances, but do NOT commit.

Wiring note for ``api/sessions.py`` (phase-1.15 consumer): construct one ``SessionRepository``
per request (it is stateless) and pass the request-scoped ``AsyncSession``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from skoll.db.models import Message, Session, ToolCall

__all__ = ["SessionRepository", "new_id"]

# States accepted by the ``sessions.state`` CHECK constraint in schema.sql.
_SESSION_STATES = frozenset({"idle", "running", "error", "completed"})
# States accepted by the ``tool_calls.status`` CHECK constraint in schema.sql.
_TOOL_CALL_STATUSES = frozenset(
    {
        "pending_args",
        "ready",
        "awaiting_approval",
        "approved",
        "rejected",
        "executing",
        "completed",
        "failed",
    }
)
# Roles accepted by the ``messages.role`` CHECK constraint in schema.sql.
_MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})


def new_id() -> str:
    """Return a fresh UUID v4 string (the PK convention for TEXT-keyed tables)."""
    return str(uuid.uuid4())


def _dump_json(value: Mapping[str, Any] | None) -> str | None:
    """Serialise an optional mapping to a compact JSON string (or ``None``)."""
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


class SessionRepository:
    """CRUD for the chat/agent loop. Stateless; bind an ``AsyncSession`` per call."""

    # ----- sessions -------------------------------------------------------------------

    async def create_session(
        self,
        db: AsyncSession,
        *,
        model: str,
        title: str | None = None,
        workspace_id: str | None = None,
        system_prompt_overrides: Mapping[str, Any] | None = None,
        auto_approve: Mapping[str, bool] | None = None,
        state: str = "idle",
    ) -> Session:
        """Insert a new session row and return the populated ORM instance."""
        if state not in _SESSION_STATES:
            raise ValueError(f"invalid session state: {state!r}")
        session = Session(
            id=new_id(),
            title=title,
            workspace_id=workspace_id,
            model=model,
            system_prompt_overrides=_dump_json(system_prompt_overrides),
            auto_approve=_dump_json(auto_approve) or "{}",
            state=state,
        )
        db.add(session)
        await db.flush()
        await db.refresh(session)
        return session

    async def get_session(self, db: AsyncSession, session_id: str) -> Session | None:
        """Return the session by id, or ``None`` if it does not exist."""
        return await db.get(Session, session_id)

    async def list_sessions(self, db: AsyncSession, *, limit: int = 50) -> list[Session]:
        """Return sessions newest-first (matches ``idx_sessions_updated``)."""
        stmt = select(Session).order_by(Session.updated_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update_session_state(
        self,
        db: AsyncSession,
        session_id: str,
        *,
        state: str,
        last_iteration: int | None = None,
        touch: bool = True,
    ) -> None:
        """Update a session's ``state`` (and optionally ``last_iteration``).

        ``touch=True`` bumps ``updated_at`` to ``datetime('now')`` so the sessions list
        re-sorts. No-op-safe: updating a missing id simply affects zero rows.
        """
        if state not in _SESSION_STATES:
            raise ValueError(f"invalid session state: {state!r}")
        values: dict[str, Any] = {"state": state}
        if last_iteration is not None:
            values["last_iteration"] = last_iteration
        if touch:
            values["updated_at"] = _utcnow_sql()
        await db.execute(update(Session).where(Session.id == session_id).values(**values))

    # ----- messages -------------------------------------------------------------------

    async def append_message(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        role: str,
        iteration: int,
        content: str | None = None,
        tool_call_id: str | None = None,
        token_count: int | None = None,
    ) -> Message:
        """Append a message to a session and return it.

        The FK on ``session_id`` is enforced at the DB level (foreign_keys pragma is ON),
        so appending to a non-existent session raises an ``IntegrityError`` on flush.
        """
        if role not in _MESSAGE_ROLES:
            raise ValueError(f"invalid message role: {role!r}")
        message = Message(
            id=new_id(),
            session_id=session_id,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            iteration=iteration,
            token_count=token_count,
        )
        db.add(message)
        await db.flush()
        await db.refresh(message)
        return message

    async def load_history(self, db: AsyncSession, session_id: str) -> list[Message]:
        """Return all messages for a session in insertion order.

        Ordered by ``created_at`` then SQLite ``rowid``. ``datetime('now')`` only has
        one-second resolution, so several messages in one agent iteration share a
        timestamp; ``rowid`` (monotonic insertion counter) is the tiebreaker that keeps
        them in the order they were appended. The UUID PK is random and unusable for this.
        """
        stmt = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc(), text("rowid ASC"))
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ----- tool calls -----------------------------------------------------------------

    async def record_tool_call(
        self,
        db: AsyncSession,
        *,
        tool_call_id: str,
        message_id: str,
        session_id: str,
        name: str,
        arguments: Mapping[str, Any] | str,
        status: str = "ready",
        requires_approval: bool = False,
    ) -> ToolCall:
        """Insert a tool call (id == LM Studio ``tool_call_id``) and return it.

        ``arguments`` may be a mapping (serialised here) or an already-serialised JSON
        string (e.g. the raw accumulated args buffer from the SSE delta accumulator).
        """
        if status not in _TOOL_CALL_STATUSES:
            raise ValueError(f"invalid tool-call status: {status!r}")
        args_json = (
            arguments
            if isinstance(arguments, str)
            else json.dumps(arguments, separators=(",", ":"), ensure_ascii=False)
        )
        tool_call = ToolCall(
            id=tool_call_id,
            message_id=message_id,
            session_id=session_id,
            name=name,
            arguments=args_json,
            status=status,
            requires_approval=1 if requires_approval else 0,
        )
        db.add(tool_call)
        await db.flush()
        await db.refresh(tool_call)
        return tool_call

    async def record_tool_result(
        self,
        db: AsyncSession,
        tool_call_id: str,
        *,
        result: Mapping[str, Any] | str | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
        status: str = "completed",
    ) -> ToolCall | None:
        """Attach a result/error to a tool call and set its terminal status.

        Returns the updated ORM instance, or ``None`` if the id is unknown.
        """
        if status not in _TOOL_CALL_STATUSES:
            raise ValueError(f"invalid tool-call status: {status!r}")
        tool_call = await db.get(ToolCall, tool_call_id)
        if tool_call is None:
            return None
        if result is not None:
            tool_call.result = (
                result
                if isinstance(result, str)
                else json.dumps(result, separators=(",", ":"), ensure_ascii=False)
            )
        if error is not None:
            tool_call.error = error
        if duration_ms is not None:
            tool_call.duration_ms = duration_ms
        tool_call.status = status
        await db.flush()
        await db.refresh(tool_call)
        return tool_call

    async def set_tool_call_status(
        self,
        db: AsyncSession,
        tool_call_id: str,
        *,
        status: str,
        approved_by: str | None = None,
        approved_at: str | None = None,
        rejected_reason: str | None = None,
    ) -> None:
        """Update a tool call's approval status fields (used by the approval gate)."""
        if status not in _TOOL_CALL_STATUSES:
            raise ValueError(f"invalid tool-call status: {status!r}")
        values: dict[str, Any] = {"status": status}
        if approved_by is not None:
            values["approved_by"] = approved_by
        if approved_at is not None:
            values["approved_at"] = approved_at
        if rejected_reason is not None:
            values["rejected_reason"] = rejected_reason
        await db.execute(update(ToolCall).where(ToolCall.id == tool_call_id).values(**values))


def _utcnow_sql() -> str:
    """ISO-8601 UTC string matching SQLite's ``datetime('now')`` format.

    Used to bump ``updated_at`` from Python on UPDATE statements (server defaults only fire
    on INSERT). Format ``YYYY-MM-DD HH:MM:SS`` is exactly what ``datetime('now')`` emits.
    """
    import datetime as _dt

    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d %H:%M:%S")
