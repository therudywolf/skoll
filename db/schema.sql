-- Skoll SQLite schema (canonical DDL)
-- Alembic migrations are generated from this; treat this file as the source of truth.
-- Run: `sqlite3 .skoll_cache/skoll.sqlite < db/schema.sql` to bootstrap a fresh DB.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---------- workspaces ----------
CREATE TABLE IF NOT EXISTS workspaces (
    id              TEXT PRIMARY KEY,                          -- UUID v4
    name            TEXT NOT NULL,
    root_path       TEXT NOT NULL UNIQUE,                      -- absolute host path
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_opened_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------- sessions (agent conversations) ----------
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,                          -- UUID v4
    title           TEXT,
    workspace_id    TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
    model           TEXT NOT NULL,                             -- LM Studio model id
    system_prompt_overrides TEXT,                              -- JSON object, nullable
    auto_approve    TEXT NOT NULL DEFAULT '{}',                -- JSON: {tool_name: bool}
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_iteration  INTEGER NOT NULL DEFAULT 0,
    state           TEXT NOT NULL DEFAULT 'idle'               -- idle | running | error | completed
        CHECK (state IN ('idle', 'running', 'error', 'completed'))
);
CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);

-- ---------- messages ----------
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,                          -- UUID v4
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content         TEXT,                                      -- nullable for tool-call-only assistant msgs
    tool_call_id    TEXT,                                      -- set when role='tool'
    iteration       INTEGER NOT NULL,                          -- which agent loop iteration produced this
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    token_count     INTEGER                                    -- optional metric
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);

-- ---------- tool_calls ----------
CREATE TABLE IF NOT EXISTS tool_calls (
    id              TEXT PRIMARY KEY,                          -- the tool_call_id from LM Studio
    message_id      TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    arguments       TEXT NOT NULL,                             -- JSON
    status          TEXT NOT NULL CHECK (status IN (
        'pending_args', 'ready', 'awaiting_approval',
        'approved', 'rejected', 'executing', 'completed', 'failed'
    )),
    requires_approval INTEGER NOT NULL DEFAULT 0,              -- 0/1
    approved_by     TEXT,                                      -- 'user' | 'auto' | NULL
    approved_at     TEXT,
    rejected_reason TEXT,
    result          TEXT,                                      -- JSON, nullable until completed
    error           TEXT,
    duration_ms     INTEGER,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_toolcalls_session ON tool_calls(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_toolcalls_status ON tool_calls(status) WHERE status IN ('awaiting_approval', 'executing');

-- ---------- attachments (files/images user dropped into chat) ----------
CREATE TABLE IF NOT EXISTS attachments (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id      TEXT REFERENCES messages(id) ON DELETE SET NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('file', 'image', 'url')),
    path            TEXT,                                      -- workspace-relative or upload-dir path
    url             TEXT,
    size_bytes      INTEGER,
    mime_type       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_attachments_session ON attachments(session_id);

-- ---------- RAG: file index metadata ----------
-- FAISS vectors live on disk under .skoll_cache/faiss/<workspace_id>.bin
-- This table maps FAISS row id ↔ source location.
CREATE TABLE IF NOT EXISTS rag_chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,         -- == FAISS row id
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    file_path       TEXT NOT NULL,                             -- workspace-relative
    file_hash       TEXT NOT NULL,                             -- sha256 for change detection
    chunk_index     INTEGER NOT NULL,
    start_line      INTEGER,
    end_line        INTEGER,
    token_count     INTEGER,
    embedding_model TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rag_workspace_file ON rag_chunks(workspace_id, file_path);
CREATE INDEX IF NOT EXISTS idx_rag_file_hash ON rag_chunks(workspace_id, file_hash);

-- ---------- RAG: index jobs (background work) ----------
CREATE TABLE IF NOT EXISTS index_jobs (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    state           TEXT NOT NULL CHECK (state IN ('queued', 'running', 'completed', 'failed')),
    progress        REAL NOT NULL DEFAULT 0,                   -- 0..1
    files_total     INTEGER,
    files_indexed   INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------- approval audit log (security-relevant) ----------
CREATE TABLE IF NOT EXISTS approval_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    tool_call_id    TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('approved', 'rejected', 'edited_and_approved', 'auto_approved')),
    actor           TEXT NOT NULL,                             -- 'user' or 'system'
    edited_args     TEXT,                                      -- JSON, nullable
    reason          TEXT,
    occurred_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_approval_session ON approval_log(session_id, occurred_at);

-- ---------- preflight checks (security audit trail) ----------
CREATE TABLE IF NOT EXISTS preflight_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    tool_call_id    TEXT,
    check_name      TEXT NOT NULL,                             -- 'path_validation', 'shell_sanitize', etc.
    result          TEXT NOT NULL CHECK (result IN ('pass', 'fail')),
    details         TEXT,
    occurred_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_preflight_session ON preflight_log(session_id, occurred_at);

-- ---------- schema version ----------
CREATE TABLE IF NOT EXISTS schema_meta (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL
);
INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', '1');
INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('created_at', datetime('now'));
