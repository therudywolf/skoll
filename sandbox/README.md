# sandbox/

The sandbox container hosts the agent's shell tool and any process the agent spawns. It is **never trusted**.

## Runtime selection

| Env value | Use case | Security |
|---|---|---|
| `runsc` (gVisor) | **Production. Default.** | Strong: user-space kernel intercepts syscalls. Container escape exploits in Linux kernel do not give host access. |
| `runc` (default Docker) | Dev only, when gVisor unavailable | **Weak.** Container shares host kernel. Acceptable for local dev with no untrusted workspaces; the backend logs a loud warning. |
| `kata` (Kata Containers) | If you already run Kata | Strong (microVM). Backend supports it, but no first-class testing. |

Set via `SKOLL_SANDBOX_RUNTIME` in `.env`. Production deployments must set `runsc` and the backend refuses to start with anything else unless `SKOLL_DEV_MODE=true` is also set.

## Network policy

Default: **DROP all egress**. Allowlist via `SKOLL_SANDBOX_NETWORK_ALLOWLIST=host:port,host:port,...`.

Typical allowlist for Skoll:
- `host.docker.internal:1234` — LM Studio on host
- `searxng:8080` — local SearXNG container
- `r.jina.ai:443` — Jina Reader (optional)

See `init-network.sh` and `network-policy.md`.

## Filesystem

- `/workspace` — bind-mounted from the host (the user's project folder). Read-write but path-validated by the backend before any operation.
- `/tmp` — tmpfs, 256 MB cap.
- Everything else — read-only.

## User

The container runs as UID 1001 (`wolf`). No `sudo`. No setuid binaries kept (build step removes them).

## Resource limits

Applied via Docker `--memory`, `--cpus`, `--pids-limit`:
- Memory: 512 MB (configurable via `SKOLL_SANDBOX_MEMORY`)
- CPUs: 1.0
- PIDs: 256

## How the backend talks to the sandbox

The backend launches one ephemeral sandbox container per active agent session. Container stdin/stdout speaks the JSON protocol defined in `entrypoint.py`. There is no TCP control channel.

## Image build

```bash
docker build -t skoll/sandbox:dev sandbox/
```

The base image digest is pinned in the `Dockerfile`. Don't unpin — supply chain matters.

## Verifying the runtime

```bash
docker info --format '{{.Runtimes}}'    # should include "runsc"
docker run --runtime=runsc --rm skoll/sandbox:dev dmesg | head -5  # gVisor prints its banner
```
