"""SQLAlchemy async setup + Alembic migrations.

Source of truth for schema: ``../../../db/schema.sql``.

Public surface (for the SSE/chat flow and ``api/sessions.py``)::

    from skoll.db import (
        Base, Session, Message, ToolCall,          # ORM models
        build_engine, make_sessionmaker, session_scope,  # async engine
        SessionRepository, new_id,                  # repository
    )

Typical wiring::

    engine = build_engine(get_settings())
    Sessionmaker = make_sessionmaker(engine)
    repo = SessionRepository()
    async with session_scope(Sessionmaker) as db:
        sess = await repo.create_session(db, model="qwen2.5-coder")
"""

from __future__ import annotations

from skoll.db.engine import (
    build_engine,
    make_sessionmaker,
    session_scope,
    sqlite_url_from_path,
)
from skoll.db.models import (
    ApprovalLog,
    Attachment,
    Base,
    IndexJob,
    Message,
    PreflightLog,
    RagChunk,
    SchemaMeta,
    Session,
    ToolCall,
    Workspace,
)
from skoll.db.repo import SessionRepository, new_id

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
    "SessionRepository",
    "ToolCall",
    "Workspace",
    "build_engine",
    "make_sessionmaker",
    "new_id",
    "session_scope",
    "sqlite_url_from_path",
]
