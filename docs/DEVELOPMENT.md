# DEVELOPMENT.md — local setup

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.12+ | [python.org](https://www.python.org/downloads/) or `pyenv install 3.12` |
| Node.js | 20.11+ | [nodejs.org](https://nodejs.org/) or `nvm install 20` |
| uv | 0.4+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| pnpm | 9.12+ | `npm install -g pnpm@9.12` or `corepack enable pnpm` |
| Docker | 24+ | [docs.docker.com/get-docker](https://docs.docker.com/get-docker/) |
| gVisor (`runsc`) | latest | [gvisor.dev/docs/user_guide/install/](https://gvisor.dev/docs/user_guide/install/) — for Phase 1+ sandbox |
| LM Studio | 0.3.6+ | [lmstudio.ai](https://lmstudio.ai) — load a tool-calling model, start the local server |

## First-time setup

```bash
git clone --recurse-submodules https://github.com/<owner>/Skoll.git
cd Skoll
cp .env.example .env
# Edit .env: set SKOLL_LMSTUDIO_BASE_URL and (if auth enabled) SKOLL_LMSTUDIO_API_KEY

make install        # uv sync + pnpm install
make docker-up      # brings up searxng
```

## Day-to-day

```bash
make dev            # runs backend (uvicorn, hot reload) and frontend (vite) in parallel
# Backend: http://127.0.0.1:8000
# Frontend dev server: http://127.0.0.1:5173 (proxies /api and /ws to backend)
```

Open http://127.0.0.1:5173. The frontend dev server proxies `/api/*` and `/ws/*` to the backend so you don't fight CORS.

## Before pushing

```bash
make check          # ruff + ruff format + mypy + pytest + bandit + gitleaks + frontend typecheck + frontend test
```

The same command runs in CI. If it's green locally, it's green in CI.

## Working with vendored submodules

`vendor/ForestOptiLM` and `vendor/PhotoAISorter` are git submodules. **Don't edit files inside them.** Adapters live in `backend/src/skoll/`.

To update a submodule:

```bash
cd vendor/ForestOptiLM
git pull origin main
cd ../..
git add vendor/ForestOptiLM
git commit -m "chore: bump ForestOptiLM submodule"
```

## Regenerating types from contracts

After editing `contracts/openapi.yaml` or `contracts/tools/*.json`:

```bash
make gen-types      # produces frontend/src/lib/api/types.gen.ts + backend Python models
```

## Running the sandbox without gVisor (dev only)

If you're developing on macOS where gVisor is awkward, set in `.env`:

```
SKOLL_SANDBOX_RUNTIME=runc
```

Backend will print a loud warning and refuse to start unless `SKOLL_DEV_MODE=true`. Never set `runc` in production.

## Debugging LM Studio integration

The backend has a built-in probe:

```bash
cd backend
uv run python -m skoll.lm.probe --base-url http://127.0.0.1:1234 --model qwen2.5-coder-32b-instruct
```

This runs the same suite that `TESTED_MODELS.md` uses. Useful when adding a new model.

## VS Code recommended extensions

If you happen to use VS Code while building Skoll (irony noted):

- `ms-python.python`
- `charliermarsh.ruff`
- `ms-python.mypy-type-checker`
- `dbaeumer.vscode-eslint`
- `bradlc.vscode-tailwindcss` (if Tailwind is later adopted)

Settings (`.vscode/settings.json` — NOT committed):

```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "editor.formatOnSave": true,
  "[python]": {"editor.defaultFormatter": "charliermarsh.ruff"},
  "[typescript]": {"editor.defaultFormatter": "esbenp.prettier-vscode"}
}
```

## Common gotchas

- **`make backend` fails with "no module skoll"** → run `cd backend && uv sync` first.
- **Frontend can't reach backend** → check `frontend/vite.config.ts` proxy target matches `SKOLL_PORT`.
- **LM Studio streaming hangs** → ensure model has tool calling enabled in LM Studio UI.
- **`mypy` is slow** → run `uv run mypy src/skoll/<changed_module>` instead of full project.
