# Pre-built Issues — copy/paste into GitHub

> Each entry below maps to one row of `ROADMAP.md`. Copy the block into a new Issue using the `phase-task` template.
> AI agents: pick the next `ready` Issue from this list, follow the workflow in §5 of `AGENTS.md`.

Labels applied to every Issue:
- `phase-N` (matching the phase number)
- `ready` (when prerequisites done) or `blocked`
- `kind/feat`, `kind/infra`, `kind/sec` as appropriate

---

## Phase 0 — Walking skeleton

### Issue 0.1 — Bootstrap monorepo configs

**Phase:** 0
**Roadmap id:** 0.1
**Goal:** A fresh checkout passes `make install` and `make check` on an empty repo (no source files yet — just configs).

**Files to touch:**
- All root config files (pyproject.toml, package.json, etc.) — already laid down; verify they install cleanly
- Add empty placeholder `backend/src/skoll/__init__.py` test
- Add `frontend/src/main.tsx` minimal hello-world

**Acceptance criteria:**
- [ ] `uv sync` succeeds inside `backend/`
- [ ] `pnpm install` succeeds at repo root
- [ ] `make lint` passes (no source files to lint yet, but tooling is wired)
- [ ] CI workflow runs to completion green
- [ ] `make docker-up` brings up SearXNG; `curl http://localhost:8089/search?q=test&format=json` returns JSON

**Security considerations:** None (configs only). Verify `.gitleaks.toml` patterns don't false-positive on `.env.example`.

**Dependencies:** none.

---

### Issue 0.2 — Backend skeleton with health endpoint

**Phase:** 0
**Roadmap id:** 0.2
**Goal:** `GET /api/health` returns `{"status": "ok", "version": "0.1.0a0", "lm_studio_reachable": <bool>}`.

**Files to touch:**
- `backend/src/skoll/app.py` — implement `create_app()` and `lifespan`
- `backend/src/skoll/api/health.py` — implement handler
- `backend/tests/test_health.py` — new file

**Acceptance criteria:**
- [ ] `make backend` starts the server
- [ ] `curl http://127.0.0.1:8000/api/health` returns 200 with the schema
- [ ] Unit test passes without LM Studio running (mock the probe)
- [ ] `lm_studio_reachable` is `false` when LM Studio is down, `true` when up
- [ ] No secrets logged at any level

**Security considerations:** Probe must use a 1s timeout — don't let a hung LM Studio block the health endpoint.

**Dependencies:** 0.1.

---

### Issue 0.3 — LM Studio async client

**Phase:** 0
**Roadmap id:** 0.3
**Goal:** `LMStudioClient` with `list_models()` and non-streaming `chat()`; both modes supported.

**Files to touch:**
- `backend/src/skoll/lm/client.py` — implement `LMStudioClient`
- `backend/src/skoll/lm/reasoning.py` — implement `is_reasoning()` and `strip_think_block()`
- `backend/scripts/capture.py` — new file: capture LM Studio responses to fixtures
- `backend/tests/test_lm_client.py` — unit tests using respx
- `backend/tests/fixtures/lm_studio/models_list.json` — captured fixture
- `backend/tests/fixtures/lm_studio/chat_simple_nontool.json` — captured fixture

**Acceptance criteria:**
- [ ] `LMStudioClient.from_settings()` constructs from `SKOLL_LMSTUDIO_*` env
- [ ] `list_models()` parses both native and openai-compat response shapes
- [ ] `chat()` works in both modes with same call signature
- [ ] `is_reasoning("qwen3-coder-32b")` → True; `is_reasoning("qwen2.5-coder-32b")` → False
- [ ] Auth header redacted in any error logging
- [ ] Integration test (marked `@pytest.mark.integration`) passes against running LM Studio

**Security considerations:** Never log Authorization header. Verify with a test that intentionally fails and asserts the header is not in `caplog.text`.

**Dependencies:** 0.1, 0.2.

---

### Issue 0.4 — Non-streaming chat endpoint

**Phase:** 0
**Roadmap id:** 0.4
**Goal:** `POST /api/chat` body `{messages: [...], model: "..."}` returns the model response.

**Files to touch:**
- `backend/src/skoll/api/chat.py` — dev endpoint
- `backend/tests/test_chat_nonstream.py`

**Acceptance criteria:**
- [ ] POST with one user message returns 200 with assistant content
- [ ] Bad model id returns 400 with `LMStudioError` shape
- [ ] Request body validated by Pydantic — extra fields rejected

**Security considerations:** Body size limit 1 MB. Don't echo user content back in error messages (leak vector).

**Dependencies:** 0.3.

---

### Issue 0.5 — Frontend skeleton with single textarea

**Phase:** 0
**Roadmap id:** 0.5
**Goal:** Page at `:5173` has textarea + send button. Sending hits `/api/chat`, response shown in `<pre>`.

**Files to touch:**
- `frontend/src/App.tsx` — wire up fetch
- `frontend/src/lib/api/client.ts` — new file: typed fetch wrapper

**Acceptance criteria:**
- [ ] `pnpm dev` starts dev server, page loads
- [ ] Sending text shows response within reasonable time
- [ ] CORS works (proxy via vite.config.ts)
- [ ] No `any` in TypeScript

**Security considerations:** None new.

**Dependencies:** 0.4.

---

### Issue 0.6 — CORS, env config, structlog

**Phase:** 0
**Roadmap id:** 0.6
**Goal:** Production-grade middleware in place: CORS limited to `:5173` in dev, structlog JSON output, request ID in every log line.

**Files to touch:**
- `backend/src/skoll/app.py` — add middleware
- `backend/src/skoll/log.py` — new: structlog setup
- `backend/src/skoll/config.py` — implement `_validate_production_safety`

**Acceptance criteria:**
- [ ] All logs are JSON when `SKOLL_LOG_FORMAT=json`
- [ ] Every log line has `request_id` (UUID) for HTTP-originated logs
- [ ] CORS rejects unknown origins
- [ ] Backend refuses to start with `SKOLL_SANDBOX_RUNTIME=runc` unless `SKOLL_DEV_MODE=true`

**Security considerations:** This Issue is THE gate that enforces production safety. Tests must verify refusal paths.

**Dependencies:** 0.5.

---

## Phase 1 — Chat + RAG + sandbox

(One Issue per row of ROADMAP.md §Phase 1. Same template. To keep this document scannable, only headlines are listed here; the full text follows the same pattern as Phase 0 Issues. Owner: copy the row, expand into a full Issue using the `phase-task` template.)

- **1.1** SSE streaming endpoint with event protocol
- **1.2** Tool-call JSON delta accumulator (with regression fixtures)
- **1.3** Reasoning model detection + `reasoning: off`
- **1.4** Agent ReAct loop (read-only tools only)
- **1.5** Tool registry + schema loader (validates contracts/tools/*.json matches modules)
- **1.6** RAG: chunking + extractors (port from ForestOptiLM)
- **1.7** RAG: embeddings via LM Studio (with on-disk cache)
- **1.8** FAISS in-memory index + SQLite metadata
- **1.9** Tool: `codebase_search` (first end-to-end agent capability)
- **1.10** Sandbox: gVisor Dockerfile + control socket
- **1.11** Untrusted content wrapper (apply to every external content path)
- **1.12** Gitleaks-style scrubbing (load patterns from `.gitleaks.toml`)
- **1.13** Frontend: React + Vite + Monaco read-only + ChatPane
- **1.14** Frontend: file upload drag-drop → workspace
- **1.15** Session persistence (DB models + Alembic migration)

## Phase 2 — Agent edits + sandbox shell

- **2.1** Tool: `read_file`
- **2.2** Tool: `write_file` (with approval)
- **2.3** Tool: `apply_diff` (SEARCH/REPLACE)
- **2.4** Tool: `run_bash` in sandbox
- **2.5** Approval UI: ToolCallCard
- **2.6** Tool: `web_search` (SearXNG primary, DDG fallback)
- **2.7** Tool: `read_url` (Jina + Trafilatura fallback)
- **2.8** Frontend: Monaco DiffEditor for write previews
- **2.9** Tool-call recovery on bad JSON
- **2.10** Settings: per-tool auto-approve
- **2.11** E2E test: bug-fix scenario

## Phase 3 — Production UX

- **3.1** LSP: pylsp via monaco-languageclient over WS
- **3.2** LSP: typescript-language-server
- **3.3** Terminal: xterm.js + node-pty in sandbox
- **3.4** Git operations (`git_diff`, `git_commit`)
- **3.5** Tool: `analyze_corpus` (Map-Reduce from ForestOptiLM `processor.py`)
- **3.6** Tool: `analyze_image` (vision pipeline from PhotoAISorter)
- **3.7** File watcher for incremental RAG re-index
- **3.8** Layout persistence (mosaic state)
- **3.9** Theming
- **3.10** Production Docker compose

---

## How an AI agent picks the next Issue

1. Look in this file. Pick the lowest-numbered Issue whose dependencies are all `closed`.
2. Confirm in `docs/ROADMAP.md` that the description matches.
3. Open the Issue using the `phase-task` template (use this file's text as the body).
4. Comment `taking this`. Branch. PR. Done.
