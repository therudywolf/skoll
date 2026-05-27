# THREAT MODEL — STRIDE for Skoll

> Owner is a Security Engineer; this is the authoritative document for security decisions.
> Every PR that adds a new tool, new endpoint, or new external integration must update this file.

## Assets

| ID | Asset | Sensitivity |
|---|---|---|
| A1 | User's source code in workspace | HIGH — may contain proprietary IP, embedded secrets |
| A2 | LM Studio API token | HIGH — gives access to local model server |
| A3 | User's local files outside workspace | CRITICAL — must never be accessible to agent |
| A4 | OS shell on host | CRITICAL — agent must never get code execution on host |
| A5 | User session data (chat history, tool calls) | MEDIUM — local SQLite, but contains code |
| A6 | Network egress capability | HIGH — sandbox must not be a pivot point |

## Trust boundaries

```
[User browser] ── HTTP/SSE ──> [Skoll backend (host)] ── socket ──> [Sandbox container]
                                       │                                       │
                                       └── HTTP ──> [LM Studio (host:1234)]    └── HTTP (allowlist) ──> [External: SearXNG, Jina]
```

Trust decreases left-to-right: browser is most trusted (it's the human), LM Studio is somewhat trusted (we ship its prompts), sandbox is **untrusted** (anything in it might be agent-controlled), external internet is **fully untrusted**.

## STRIDE per component

### Backend HTTP API

| Threat | Vector | Mitigation | Status |
|---|---|---|---|
| **S**poofing | Browser cookies stolen via XSS | CSP `default-src 'self'`; CSRF token on state-changing endpoints | Phase 0 |
| **T**ampering | Path traversal in file CRUD | `security.path.safe_resolve()` rejects paths outside workspace | Phase 1 |
| **R**epudiation | User claims they didn't approve a destructive tool call | All approvals logged with timestamp + tool_call_id to SQLite, retained per session | Phase 2 |
| **I**nfo disclosure | Stack traces leak file paths or env vars | Production mode: generic 500 errors; logs go to file only | Phase 1 |
| **D**oS | Large file upload | Content-length limit 50MB per request; rate limit 10 req/s | Phase 1 |
| **E**levation | Endpoint not auth-checked | Default: bind to `127.0.0.1` only; Phase 4: optional token auth for LAN access | Phase 0 |

### Agent loop / tool execution

| Threat | Vector | Mitigation | Status |
|---|---|---|---|
| **Prompt injection from file** | `README.md` contains "exfiltrate ~/.ssh" → agent reads → agent obeys | (1) Wrap all file content in `<untrusted_content>`; (2) System prompt explicitly says ignore instructions in those tags; (3) Secrets scrubbed before LLM sees them | Phase 1 |
| **Prompt injection from URL** | Web page contains injected instructions | Same as above + Jina Reader strips most styling/scripts | Phase 2 |
| **Prompt injection from another tool result** | `web_search` returns adversarial snippet | All tool results that contain external data wrapped as untrusted | Phase 2 |
| **Destructive tool call** | Agent calls `run_bash("rm -rf /")` | (1) Sandbox can't reach host FS; (2) `requires_approval: true`; (3) Approval UI shows full args | Phase 2 |
| **Sandbox escape** | Agent exploits kernel CVE | gVisor `runsc` runtime (intercepts syscalls); no privileged containers; non-root user inside | Phase 1 |
| **Sandbox network pivot** | Agent uses sandbox to scan internal network | egress allowlist (iptables in container init); DROP everything else | Phase 1 |
| **Secret exfiltration** | Agent reads `.env`, includes value in tool call args | `security.secrets.scrub()` pre-LLM; allowlist of safe-to-read file patterns | Phase 1 |
| **Tool call args injection** | Agent generates `read_file("/etc/passwd")` | Path validator rejects; for shell, all args pass through `shlex.quote` in sandbox | Phase 1 |
| **Resource exhaustion** | Agent spawns infinite recursion | `MAX_ITERATIONS=20` per turn; per-tool timeout; sandbox memory cap 512MB; bash timeout 30s | Phase 1 |

### LM Studio interaction

| Threat | Vector | Mitigation | Status |
|---|---|---|---|
| **Token in logs** | `httpx` debug logging leaks Authorization header | structlog redactor strips `Authorization`, `api_key` keys; log level WARNING in prod | Phase 0 |
| **Replay** | Captured request replayed by other process on host | LM Studio is on `127.0.0.1` only; auth token rotates per install | accepted risk |
| **MITM** | Some other process on host poses as LM Studio | Only `127.0.0.1` allowed for LM Studio base URL by default; if user changes to LAN host, warning shown | Phase 1 |

### External services (SearXNG, Jina, DuckDuckGo)

| Threat | Vector | Mitigation | Status |
|---|---|---|---|
| Adversarial search results | Poisoned SEO returns prompt injection | Wrap as untrusted; truncate to N chars | Phase 2 |
| Service compromise → data leak | SearXNG instance compromised | SearXNG is self-hosted in local Docker; egress queries don't include user data | Phase 1 |
| Jina API key leak | `SKOLL_JINA_READER_API_KEY` exposed | Stored in `.env` (gitignored); never logged; optional (free tier works without) | Phase 2 |

## Required pre-tool-call checks

Implemented as a single function `security.preflight.check_tool_call(tool, args, session)`:

```python
def check_tool_call(tool: Tool, args: dict, session: Session) -> PreflightResult:
    """
    Runs in order; first failure short-circuits.
    """
    # 1. Schema validation
    args = tool.validate_args(args)  # JSON Schema from contracts/tools/

    # 2. Path validation (if tool touches FS)
    for path_arg in tool.path_args:
        safe_resolve(args[path_arg], session.workspace_root)

    # 3. Argument sanitization for shell tools
    if tool.kind == "shell":
        args["command"] = sanitize_shell(args["command"])

    # 4. Egress allowlist for URL-fetching tools
    if tool.kind == "url_fetch":
        ensure_url_allowed(args["url"], session.allowlist)

    # 5. Rate limit
    rate_limiter.check(session.id, tool.name)

    # 6. Approval gate
    if tool.requires_approval and not session.auto_approve.get(tool.name, False):
        return PreflightResult.NEEDS_APPROVAL

    return PreflightResult.OK
```

## Security CI checks

Every PR runs:
- `ruff` with `S` (bandit-lite) rules enabled
- `bandit` against `backend/src/`
- `gitleaks detect` against the full repo
- `pip-audit` against backend deps
- `pnpm audit --prod` against frontend deps
- A custom test: `pytest tests/security/` which verifies preflight checks fire for malicious inputs

A PR cannot merge if any of these fail.

## What's accepted risk

- The agent can read source code that contains secrets (we scrub but no scrubber is perfect). Mitigation: don't load secrets into a workspace you'll let the agent see; use `.env` outside workspace.
- A user who runs Skoll with `SKOLL_AGENT_AUTO_APPROVE_EXEC_TOOLS=true` and `SKOLL_SANDBOX_RUNTIME=runc` (no gVisor) has effectively disabled most defenses. We log a loud warning; we don't prevent it.
- If LM Studio itself is compromised, all bets are off. We don't defend against a malicious local model server.
