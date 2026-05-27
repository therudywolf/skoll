# 🐺 Sköll

> Local-first agentic web IDE for LM Studio. AGPL-3.0.

*Sköll (Old Norse: Skǫll, "Mockery / Treachery") — the wolf who pursues the sun across the sky in Norse mythology. The project name uses ASCII `Skoll` in all code, CLI commands, paths, and identifiers; `Sköll` appears only in branding.*

Sköll is a browser-based code editor with an autonomous AI agent that runs entirely on your machine via [LM Studio](https://lmstudio.ai). No cloud APIs, no telemetry, no paid services — every external dependency is either self-hosted or has a permanent free tier.

This repository is currently **a handoff package** prepared for AI coding agents (Claude Code, Cursor, etc.). The application code is not implemented yet — the project is fully specified through:

- [`AGENTS.md`](AGENTS.md) — house rules for AI agents working on this repo (start here)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system design
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — phased delivery plan with linked Issues
- [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) — STRIDE threat model + mitigations
- [`docs/TESTED_MODELS.md`](docs/TESTED_MODELS.md) — LM Studio model compatibility matrix
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — local setup
- [`contracts/`](contracts/) — OpenAPI spec + JSON Schemas for every agent tool
- [`prompts/`](prompts/) — every LLM prompt template
- The accompanying research document `../Skoll_research_and_blueprint.md`

## What makes Skoll different

| | OpenWebUI | Cursor / Void | Aider | **Skoll** |
|---|---|---|---|---|
| Browser-native | ✅ | ❌ Electron | ❌ CLI | ✅ |
| Local LLMs only | ✅ | ❌ | partial | ✅ (LM Studio) |
| Agentic loop (read/write/exec) | ❌ | ✅ | ✅ | ✅ |
| Sandbox by default (gVisor) | ❌ | ❌ | ❌ | ✅ |
| Map-Reduce over huge folders | ❌ | ❌ | ❌ | ✅ (via ForestOptiLM) |
| Vision tools (drag-drop images) | partial | partial | partial | ✅ (via PhotoAISorter) |
| Free web search built-in | ❌ | needs key | needs key | ✅ (SearXNG + Jina) |
| AGPL-3.0 | — | Apache 2.0 | Apache 2.0 | ✅ |

## Quick start (when the code exists)

```bash
# 1. Install LM Studio, load a tool-calling model, start the server
# 2. Clone with submodules (ForestOptiLM, PhotoAISorter)
git clone --recurse-submodules https://github.com/therudywolf/Skoll
cd Skoll

# 3. Bring up the dev stack
docker compose up -d searxng sandbox
make dev    # starts backend (uv) and frontend (pnpm) in watch mode

# 4. Open http://localhost:5173
```

## For AI coding agents starting work here

1. Read [`AGENTS.md`](AGENTS.md) end-to-end. Twice.
2. Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
3. Pick an Issue from [`docs/ROADMAP.md`](docs/ROADMAP.md) labeled `phase-0` and 