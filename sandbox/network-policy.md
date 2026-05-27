# Sandbox network policy

> Default: DENY ALL OUTBOUND. Add hosts to the allowlist only with security review.

## Default allowlist (`.env.example`)

```
SKOLL_SANDBOX_NETWORK_ALLOWLIST=host.docker.internal:1234,r.jina.ai:443,searxng:8080
```

## Adding a host requires:

1. **Why is it needed?** Be specific. "Tool X fetches data from Y" — link the tool's schema.
2. **What does the host return?** If user-controlled / scraped data, also document the untrusted-content wrap.
3. **Is there a self-hosted alternative?** Prefer it (e.g., SearXNG over Brave Search API).
4. **What's the egress volume?** If unbounded, add a rate limiter in the corresponding tool.

## Hosts considered and rejected

| Host | Reason for rejection |
|---|---|
| `api.openai.com` | Project policy: no cloud LLMs. |
| `api.anthropic.com` | Same. |
| `api.brave.com/search` | Paid as of 2026-02. Use SearXNG. |
| `pypi.org`, `registry.npmjs.org` | Agent should not install packages at runtime. All deps installed at image build. |
| `github.com` (generic) | Allowed only if user explicitly enables a "github access" tool (Phase 4+). Default no. |

## DNS

The allowlist resolves hostnames at container init. Subsequent DNS lookups inside the container ARE allowed (UDP/TCP 53) so apps can resolve other hosts — but the egress firewall blocks the resulting traffic. This makes failures obvious in logs without breaking name resolution unexpectedly.

## What's intentionally NOT enforced

- Per-tool egress restriction. The whole sandbox shares one allowlist. If a tool needs a different allowlist, run it in a different sandbox (Phase 3+).
- Egress to localhost from inside the sandbox. The sandbox cannot reach the host directly; `host.docker.internal` is provided by Docker.
