# Skoll — Architecture

> This document is the detailed companion to `../AGENTS.md`. Read both.
> The original research and decisions are in `../../Skoll_research_and_blueprint.md` (one folder up from the project root).

## 1. System diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│  BROWSER  (Vite dev server :5173, prod served by FastAPI as static)    │
│                                                                        │
│  React 18 + TypeScript + Zustand + TanStack Query                      │
│                                                                        │
│  ┌──────────┐  ┌────────────────────────┐  ┌────────────────────────┐  │
│  │ FileTree │  │ Monaco (editor + diff) │  │ ChatPane               │  │
│  │          │  │  + LSP via WS          │  │  - SSE stream consumer │  │
│  │          │  │                        │  │  - ToolCallCard with   │  │
│  │          │  │                        │  │    approve/reject UI   │  │
│  └──────────┘  └────────────────────────┘  └────────────────────────┘  │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ HTTP + SSE
                                     │ (single backend origin)
┌────────────────────────────────────▼───────────────────────────────────┐
│  BACKEND  FastAPI 0.135+ on uvicorn (Python 3.12, pure async)          │
│                                                                        │
│  api/                                                                  │
│   ├── chat.py       POST /api/sessions/{id}/messages  → SSE stream     │
│   ├── files.py      CRUD over workspace files (path-validated)         │
│   ├── tools.py      POST /api/sessions/{id}/tool-calls/{id}/approve    │
│   ├── lsp.py        WS /lsp/{language} → pylsp / typescript-ls         │
│   └── exec.py       (Phase 2) WS /exec/{session_id} → sandbox PTY      │
│                                                                        │
│  agent/  ReAct loop with tool registry                                 │
│   loop.py — observe-think-act, max iterations, recovery on bad JSON    │
│   tools/ — one module per tool, each implements ToolProtocol           │
│                                                                        │
│  lm/  LM Studio adapter                                                │
│   client.py — async, supports native + openai-compat, streaming        │
│   reasoning.py — detect r1/qwen3, set `reasoning: off` for tools       │
│                                                                        │
│  rag/  FAISS-based codebase indexing                                   │
│   chunking.py, embeddings.py, retrieval.py (adapted from ForestOptiLM) │
│                                                                        │
│  search/  Free web search & extraction                                 │
│   searxng.py, duckduckgo.py, jina_reader.py, trafilatura_extract.py    │
│                                                                        │
│  security/  Defense layer                                              │
│   path.py — workspace-relative path validation                         │
│   untrusted.py — wrap external content in <untrusted_content>          │
│   secrets.py — gitleaks-style scrubbing before LLM sees content        │
│   approval.py — human-in-the-loop gate for write/exec tools            │
│                                                                        │
│  db/  SQLite via aiosqlite + Alembic migrations                        │
│   models.py — Session, Message, ToolCall, FileIndexEntry               │
│                                                                        │
└──────────────┬─────────────────────────────────────────┬───────────────┘
               │                                         │
       ┌───────▼────────┐                       ┌────────▼───────────┐
       │ LM Studio      │                       │ Sandbox container  │
       │ on host        │                       │ gVisor `runsc`     │
       │ :1234          │                       │ workspace mount    │
       │                │                       │ egress allowlist   │
       └────────────────┘                       └────────────────────┘
                                                  ▲
              ┌───────────────────────────────────┘
              │ ephemeral, spawned per session
              │
       ┌──────┴───────────┐
       │  SearXNG (Docker)│  (also reachable from sandbox if allowlisted)
       │  :8089           │
       └──────────────────┘
```

## 2. Trust boundaries

| Boundary | What crosses | Defense |
|---|---|---|
| Browser → Backend | User messages, file uploads, approvals | CORS (same-origin only), CSRF token for state-changing requests, content-length limits |
| Backend → LM Studio | Prompts, tool definitions | Auth token from env, no request bodies logged at INFO+, response size cap |
| Backend → Sandbox | Bash commands, file paths | All commands JSON-encoded over a control socket; sandbox cannot reach host FS outside the mount |
| Sandbox → Internet | Tool fetches (web_search, read_url) | iptables allowlist enforced at container init; default DROP |
| File system → LLM context | File contents, URL contents | `security.untrusted.wrap()` → tagged; `security.secrets.scrub()` → redacted |
| LLM output → Tool execution | Tool call JSON | Schema validation against `contracts/tools/*.json`; human approval for write/exec |

## 3. The agent loop (detailed)

```
async def agent_loop(session_id, user_message):
    history = await db.load_history(session_id)
    history.append({"role": "user", "content": user_message})

    for iteration in range(MAX_ITERATIONS):
        # 1. THINK: ask LM Studio
        stream = lm_client.chat_stream(
            messages=history,
            tools=tool_registry.openai_schemas(),
            reasoning="off" if reasoning_models.is_reasoning(model) else None,
        )

        # 2. STREAM to client + accumulate
        message = await emit_stream_to_client(stream, session_id)
        history.append(message)

        # 3. ACT: if tool_calls present
        if not message.tool_calls:
            break  # final answer

        for tc in message.tool_calls:
            tool = tool_registry.get(tc.function.name)
            args = tool.validate_args(tc.function.arguments)  # raises on bad JSON

            if tool.requires_approval:
                approval = await wait_for_human_approval(session_id, tc)
                if approval.action == "reject":
                    history.append(tool.format_rejection(tc, approval.reason))
                    continue
                if approval.action == "edit_args":
                    args = approval.edited_args

            # 4. OBSERVE: execute in sandbox if needed, else direct
            try:
                result = await tool.execute(args, session=session_id)
            except ToolError as e:
                result = tool.format_error(e)

            history.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    return history
```

**Recovery cases:**
- LM returns malformed `tool_calls.function.arguments` JSON → append synthetic tool result with error message, ask LM to retry. See `prompts/tool_call_recovery.md`.
- LM Studio disconnects mid-stream → reconnect with `Last-Event-ID`, replay missing chunks if backend buffered.
- Tool times out → mark as failed, continue loop.

## 4. SSE event protocol

The client opens an `EventSource` on `POST /api/sessions/{id}/messages` and receives a stream of named events. Full schema in `contracts/events.yaml`. Summary:

| Event | Payload | When |
|---|---|---|
| `message_start` | `{message_id, role}` | LM begins responding |
| `text_delta` | `{delta: string}` | Streamed assistant text chunk |
| `tool_call_start` | `{tool_call_id, name}` | Model decided on a tool |
| `tool_call_args_delta` | `{tool_call_id, args_delta: string}` | Streamed tool args |
| `tool_call_ready` | `{tool_call_id, requires_approval, args}` | Args fully accumulated; waiting for approval or executing |
| `tool_call_approved` / `tool_call_rejected` | `{tool_call_id, by}` | Human action |
| `tool_call_result` | `{tool_call_id, result, duration_ms}` | Tool finished |
| `message_end` | `{stop_reason}` | LM stream ended |
| `error` | `{code, message}` | Recoverable or fatal error |
| `ping` | `{}` | Keep-alive every 15s |

## 5. RAG indexing

Triggered when:
- User uploads files via drag-drop
- User opens a folder → `POST /api/workspaces/{path}/index`
- File watcher detects changes (Phase 3)

Pipeline (adapted from ForestOptiLM):

```
file → extractors.detect_type → parser.to_text → chunking.split
                                                       ↓
                                               embeddings.embed (LM Studio)
                                                       ↓
                                              FAISS index + SQLite metadata
```

Embeddings model is whatever the user has loaded in LM Studio with `embeddings: true` capability. Default suggestion: `nomic-embed-text-v1.5`.

## 6. What's intentionally NOT in the architecture

- **Multi-user / multi-tenant.** Single user, local-first. Auth is "is this request from localhost".
- **Cloud sync.** Workspaces are local. If user wants sync, they use git.
- **Plugin marketplace.** No. Adding plugins is editing the source. After Phase 3 we may consider a VS Code extension compatibility layer (via migration to Theia), but not before.
- **Custom model finetuning.** Out of scope. Users bring their own models to LM Studio.
- **Telemetry.** None.
