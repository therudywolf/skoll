# ROADMAP — phased delivery with Issues

Every line item below is a candidate GitHub Issue. Treat them as the work backlog. Each Issue must be created with the template from `.github/ISSUE_TEMPLATE/phase-task.yml` and tagged with the matching phase label.

---

## Phase 0 — Walking skeleton (1 week, single dev)

**Goal:** browser sends "hi", non-streaming response comes back from LM Studio.

| # | Title | Files touched | Acceptance criteria |
|---|---|---|---|
| 0.1 | Bootstrap monorepo configs | All root config files | `make install` succeeds; `make check` passes on empty repo |
| 0.2 | Backend skeleton with health endpoint | `backend/src/skoll/app.py`, `backend/pyproject.toml` | `curl http://localhost:8000/api/health` returns `{"status":"ok"}` |
| 0.3 | LM Studio async client (adapt from ForestOptiLM) | `backend/src/skoll/lm/client.py`, `lm/config.py` | Unit test passes with fixture; integration test against running LM Studio answers a one-shot prompt |
| 0.4 | Non-streaming chat endpoint | `backend/src/skoll/api/chat.py` | `POST /api/chat` with `{messages:[...]}` returns model response |
| 0.5 | Frontend skeleton with single textarea | `frontend/src/App.tsx` | Page loads, sending text shows response in a `<pre>` block |
| 0.6 | Wire up CORS, env config, structlog | `backend/src/skoll/config.py`, `app.py` | Logs are JSON; no secrets in logs; CORS allows only `:5173` in dev |

**Definition of done:** demo video (or screenshot) — type "hello" in the browser, see model reply. CI green.

---

## Phase 1 — Chat with streaming + RAG + sandbox (2 weeks)

**Goal:** streaming chat, file upload, codebase search tool, sandbox enforced for the one tool we have.

| # | Title | Files touched | Acceptance criteria |
|---|---|---|---|
| 1.1 | SSE streaming endpoint with event protocol | `backend/src/skoll/api/chat.py`, `contracts/events.yaml` | Events match `contracts/events.yaml` schema; ping every 15s |
| 1.2 | Tool-call JSON delta accumulator | `backend/src/skoll/agent/streaming.py` | Unit tests against captured LM Studio SSE traces |
| 1.3 | Reasoning model detection + `reasoning: off` | `backend/src/skoll/lm/reasoning.py` | qwen3/r1/nemotron auto-detected from `/api/v1/models` metadata |
| 1.4 | Agent ReAct loop (read-only tools only) | `backend/src/skoll/agent/loop.py` | Loop terminates on either final answer or `max_iterations`; logs each iteration |
| 1.5 | Tool registry + schema loader | `backend/src/skoll/agent/tools/registry.py` | Reads `contracts/tools/*.json` at startup; rejects tools without schema |
| 1.6 | RAG: chunking + extractors (adapt from ForestOptiLM) | `backend/src/skoll/rag/` | Test corpus indexed in <30s; chunks within token budget |
| 1.7 | RAG: embeddings via LM Studio | `backend/src/skoll/rag/embeddings.py` | Embedding model dynamically selected from LM Studio model list |
| 1.8 | FAISS in-memory index + SQLite metadata | `backend/src/skoll/rag/retrieval.py`, `db/schema.sql` | Top-5 search returns matches with file path and chunk id |
| 1.9 | Tool: `codebase_search` | `backend/src/skoll/agent/tools/codebase_search.py` | Integration: ask "where is auth?" on a fixture repo, agent cites real files |
| 1.10 | Sandbox: gVisor Dockerfile + control socket | `sandbox/Dockerfile`, `backend/src/skoll/sandbox/` | Sandbox boots in <500ms; network egress to non-allowlisted host blocked |
| 1.11 | Untrusted content wrapper | `backend/src/skoll/security/untrusted.py` | All file/URL content passes through `wrap()` before LLM sees it |
| 1.12 | Gitleaks-style scrubbing | `backend/src/skoll/security/secrets.py` | API keys and JWT tokens in files are redacted before LLM |
| 1.13 | Frontend: React + Vite + Monaco read-only + ChatPane | `frontend/src/` | Streaming text renders incrementally; Monaco loads syntax-highlighted file |
| 1.14 | Frontend: file upload drag-drop | `frontend/src/components/FileTree.tsx` | Drag a folder, see files appear, `codebase_search` works on them |
| 1.15 | Session persistence | `backend/src/skoll/db/` | Refreshing page resumes session; messages and tool calls preserved |

**Definition of done:** drop a code folder, ask a question about it, agent answers with file citations. CI green. Threat model items 1-3 verified.

---

## Phase 2 — Agent edits + sandbox shell (2-3 weeks)

**Goal:** agent can read, write, diff files; run bash in sandbox; web search; approval UI.

| # | Title | Files | Acceptance |
|---|---|---|---|
| 2.1 | Tool: `read_file` | `backend/src/skoll/agent/tools/read_file.py` | Path validated; secrets scrubbed; untrusted wrap applied |
| 2.2 | Tool: `write_file` (with approval) | `agent/tools/write_file.py` | Requires approval; diff shown to user before write |
| 2.3 | Tool: `apply_diff` with SEARCH/REPLACE format (port from Aider) | `agent/tools/apply_diff.py` + `prompts/edit_format.md` | Matches Aider's SEARCH/REPLACE block format; fuzzy match fallback |
| 2.4 | Tool: `run_bash` in sandbox | `agent/tools/run_bash.py` | Timeout enforced; stdout+stderr+exit_code returned; egress blocked |
| 2.5 | Approval UI: ToolCallCard | `frontend/src/components/ToolCallCard.tsx` | Shows args, diff for writes; approve/reject/edit buttons |
| 2.6 | Tool: `web_search` (SearXNG primary, DDG fallback) | `agent/tools/web_search.py`, `search/` | SearXNG queried first; falls back on 5xx or timeout |
| 2.7 | Tool: `read_url` (Jina Reader + Trafilatura fallback) | `agent/tools/read_url.py` | URL → markdown; content wrapped as untrusted |
| 2.8 | Frontend: Monaco DiffEditor for write previews | `frontend/src/components/EditorPane.tsx` | Diff view inline in chat; full-pane diff on click |
| 2.9 | Tool-call recovery on bad JSON | `backend/src/skoll/agent/recovery.py` + `prompts/tool_call_recovery.md` | Synthetic error message appended; agent retries; metric counter exposed |
| 2.10 | Settings: per-tool auto-approve | `frontend/src/components/Settings.tsx`, `backend/src/skoll/config.py` | Toggles persist in localStorage; backend validates on each tool call |
| 2.11 | E2E test: bug-fix scenario | `tests/e2e/test_bugfix.py` | Given fixture repo with failing test, agent reads, edits, runs pytest, iterates to green |

**Definition of done:** "fix the bug in `auth.py`, make tests pass" — agent does it autonomously with approval gates. Threat model items 4-7 verified.

---

## Phase 3 — Production UX (3-4 weeks)

| # | Title | Acceptance |
|---|---|---|
| 3.1 | LSP: pylsp via monaco-languageclient over WS | Autocomplete + hover docs work for Python files in workspace |
| 3.2 | LSP: typescript-language-server | Same for TS/JS |
| 3.3 | Terminal: xterm.js + node-pty in sandbox | Interactive shell tied to current workspace |
| 3.4 | Git operations (`git_diff`, `git_commit`, optional `git_push`) | Agent can stage and commit; user approves messages |
| 3.5 | Tool: `analyze_corpus` (Map-Reduce from ForestOptiLM `processor.py`) | Ask question over 100k+ token folder; agent produces structured report |
| 3.6 | Tool: `analyze_image` (vision pipeline from PhotoAISorter) | Drop screenshot into chat; agent describes / classifies / OCRs |
| 3.7 | File watcher for incremental RAG re-index | New files indexed within 5s; deleted files purged |
| 3.8 | Layout persistence (mosaic state in localStorage) | Refresh restores pane layout, open tabs, agent session |
| 3.9 | Theming (dark/light, accent color) | Theme persists; respects `prefers-color-scheme` |
| 3.10 | Production Docker compose with reverse proxy | Single command `make deploy` brings up full stack behind Caddy |

**Definition of done:** publishable v0.1.0 release. README has a 60-second demo GIF.

---

## Backlog (no phase yet)

- Migration to Theia (if VS Code extension compat is needed)
- WASM-based LSP (no backend LSP server)
- Multi-session UI (multiple agent conversations in tabs)
- Conversation export to markdown / share link
- Custom tool plugins via YAML descriptors
- Integration with Ollama as alternative LLM backend

---

## How to claim an Issue

1. Comment `taking this` on the Issue.
2. Branch: `phase-{N}/{issue-number}-{short-slug}`.
3. PR title: `feat(phase-{N}): {summary} (#{issue-number})`.
4. Mark Issue as `in-progress` (label).
5. On merge, Issue auto-closes via PR body keyword.
