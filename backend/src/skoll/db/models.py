"""SQLAlchemy models — mirror db/schema.sql 1:1.

Issue: phase-1.15.

Keep in sync with db/schema.sql. CI has a check (TODO) that diffs the generated DDL.
"""

from __future__ import annotations

# TODO(phase-1.15): define Session, Message, ToolCall, Attachment, RagChunk, IndexJob,
# ApprovalLog, PreflightLog as SQLAlchemy 2.0 DeclarativeBase models.
