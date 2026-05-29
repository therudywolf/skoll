"""SQLAlchemy 2.0 typed models — mirror ``db/schema.sql`` 1:1.

Issue: phase-1.15.

Source of truth for the schema is ``db/schema.sql`` at the repo root. Every table,
column name, type, FK, nullability, default, CHECK constraint and index below mirrors
that DDL. Keep them in sync — ``tests/test_db_models.py`` (schema-parity test) diffs the
DDL produced by ``Base.metadata`` against an ``alembic upgrade head`` of a tmp SQLite DB.

Notes on the SQLite ↔ SQLAlchemy mapping:
- Text-typed UUID PKs use ``String``; the integer autoincrement PKs (rag_chunks,
  approval_log, preflight_log) use ``Integer`` with ``autoincrement=True``.
- Timestamps are stored as TEXT via SQLite ``datetime('now')`` (matching the DDL), so
  the server default is the literal SQL expression ``(datetime('now'))`` and the Python
  type is ``str``. We do NOT use ``DateTime`` — schema.sql stores ISO-8601 text.
- JSON columns are plain TEXT in the DDL (e.g. ``auto_approve``); they are typed ``str``
  here and the repository is responsible for ``json.dumps``/``json.loads``.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# The literal SQLite expression used by every ``*_at`` column in schema.sql.
_NOW = text("(datetime('now'))")


class Base(DeclarativeBase):
    """Shared declarative base for all Skoll ORM models."""


class Workspace(Base):
    """A folder the user opened — maps to ``workspaces`` in schema.sql."""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID v4
    name: Mapped[str] = mapped_column(Text, nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW)
    last_opened_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW)

    sessions: Mapped[list[Session]] = relationship(back_populates="workspace")
    rag_chunks: Mapped[list[RagChunk]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", passive_deletes=True
    )
    index_jobs: Mapped[list[IndexJob]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", passive_deletes=True
    )


class Session(Base):
    """An agent conversation — maps to ``sessions`` in schema.sql."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('idle', 'running', 'error', 'completed')",
            name="ck_sessions_state",
        ),
        Index("idx_sessions_workspace", "workspace_id"),
        Index("idx_sessions_updated", text("updated_at DESC")),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID v4
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)  # LM Studio model id
    system_prompt_overrides: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    auto_approve: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'{}'")
    )  # JSON {tool_name: bool}
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW)
    last_iteration: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'idle'"))

    workspace: Mapped[Workspace | None] = relationship(back_populates="sessions")
    messages: Mapped[list[Message]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
    )
    tool_calls: Mapped[list[ToolCall]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )


class Message(Base):
    """A single chat message — maps to ``messages`` in schema.sql."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('system', 'user', 'assistant', 'tool')",
            name="ck_messages_role",
        ),
        Index("idx_messages_session", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID v4
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    # nullable for tool-call-only assistant messages
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(Text, nullable=True)  # set when role='tool'
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    session: Mapped[Session] = relationship(back_populates="messages")
    tool_calls: Mapped[list[ToolCall]] = relationship(
        back_populates="message", cascade="all, delete-orphan", passive_deletes=True
    )
    attachments: Mapped[list[Attachment]] = relationship(back_populates="message")


class ToolCall(Base):
    """A tool invocation requested by the model — maps to ``tool_calls`` in schema.sql."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_args', 'ready', 'awaiting_approval', "
            "'approved', 'rejected', 'executing', 'completed', 'failed')",
            name="ck_tool_calls_status",
        ),
        Index("idx_toolcalls_session", "session_id", "created_at"),
        Index(
            "idx_toolcalls_status",
            "status",
            sqlite_where=text("status IN ('awaiting_approval', 'executing')"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)  # tool_call_id from LM Studio
    message_id: Mapped[str] = mapped_column(
        String, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    arguments: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    status: Mapped[str] = mapped_column(Text, nullable=False)
    requires_approval: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )  # 0/1
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)  # 'user'|'auto'|NULL
    approved_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON, until completed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW)

    message: Mapped[Message] = relationship(back_populates="tool_calls")
    session: Mapped[Session] = relationship(back_populates="tool_calls")


class Attachment(Base):
    """A file/image/url the user dropped into chat — maps to ``attachments``."""

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint("kind IN ('file', 'image', 'url')", name="ck_attachments_kind"),
        Index("idx_attachments_session", "session_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)  # workspace-rel or upload path
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW)

    session: Mapped[Session] = relationship(back_populates="attachments")
    message: Mapped[Message | None] = relationship(back_populates="attachments")


class RagChunk(Base):
    """RAG file-index metadata; ``id`` == FAISS row id — maps to ``rag_chunks``."""

    __tablename__ = "rag_chunks"
    __table_args__ = (
        Index("idx_rag_workspace_file", "workspace_id", "file_path"),
        Index("idx_rag_file_hash", "workspace_id", "file_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)  # workspace-relative
    file_hash: Mapped[str] = mapped_column(Text, nullable=False)  # sha256
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW)

    workspace: Mapped[Workspace] = relationship(back_populates="rag_chunks")


class IndexJob(Base):
    """Background RAG indexing job — maps to ``index_jobs`` in schema.sql."""

    __tablename__ = "index_jobs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed')",
            name="ck_index_jobs_state",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(Text, nullable=False)
    progress: Mapped[float] = mapped_column(nullable=False, server_default=text("0"))  # 0..1
    files_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_indexed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW)

    workspace: Mapped[Workspace] = relationship(back_populates="index_jobs")


class ApprovalLog(Base):
    """Security-relevant approval audit log — maps to ``approval_log``.

    NOTE: schema.sql intentionally does NOT declare FKs on this audit table (session_id /
    tool_call_id are plain TEXT) so the trail survives row deletion. Mirrored faithfully.
    """

    __tablename__ = "approval_log"
    __table_args__ = (
        CheckConstraint(
            "action IN ('approved', 'rejected', 'edited_and_approved', 'auto_approved')",
            name="ck_approval_log_action",
        ),
        Index("idx_approval_session", "session_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_call_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)  # 'user' | 'system'
    edited_args: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW)


class PreflightLog(Base):
    """Security preflight-check audit trail — maps to ``preflight_log``.

    Like ``approval_log``, schema.sql declares no FKs here (audit durability).
    """

    __tablename__ = "preflight_log"
    __table_args__ = (
        CheckConstraint("result IN ('pass', 'fail')", name="ck_preflight_log_result"),
        Index("idx_preflight_session", "session_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_call_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_name: Mapped[str] = mapped_column(Text, nullable=False)  # 'path_validation' etc.
    result: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW)


class SchemaMeta(Base):
    """Schema version / metadata key-value table — maps to ``schema_meta``."""

    __tablename__ = "schema_meta"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


__all__ = [
    "ApprovalLog",
    "Attachment",
    "Base",
    "IndexJob",
    "Message",
    "PreflightLog",
    "RagChunk",
    "SchemaMeta",
    "Session",
    "ToolCall",
    "Workspace",
]
