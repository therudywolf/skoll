# HANDOFF.md — onboarding for the next AI agent (or human)

> You just opened this folder. You're going to build Skoll.
> Read this file completely before touching anything else. It will take 5 minutes.

## What this folder is

A **specification + skeleton** for Skoll — a local-first agentic web IDE for LM Studio.

- No application code is written yet.
- Every architectural decision is already made.
- Every file you might want to create has either a docstring telling you what it does, or a JSON schema, or both.

Your job is to fill in the `NotImplementedError`s, in the order specified by `docs/ROADMAP.md` and `docs/ISSUES.md`.

## Mandatory reading order (5 minutes total)

1. **`AGENTS.md`** — house rules, stack, security rules. Non-negotiable.
2. **`docs/ARCHITECTURE.md`** — system diagram and component responsibilities.
3. **`docs/ROADMAP.md`** — what to build in what order.
4. **`docs/THREAT_MODEL.md`** — security threats and required mitigations.
5. **`docs/TESTED_MODELS.md`** — LM Studio model quirks you must know.

The original research and rationale is in the file `../Skoll_research_and_blueprint.md` (one folder up). Skim it if the above leaves a question unanswered.

## What's already done (you don't need to redo these)

- ✅ Stack chosen (Python 3.12 + FastAPI + React + Monaco + gVisor)
- ✅ Repo layout designed
- ✅ All config files written (pyproject, package.json, docker-compose, .gitignore, .pre-commit, .gitleaks, CI)
- ✅ DB schema (`db/schema.sql`)
- ✅ Full API contract (`contracts/openapi.yaml`)
- ✅ SSE event types (`contracts/events.yaml`)
- ✅ JSON schemas for all 11 agent tools (`contracts/tools/*.json`)
- ✅ All prompt templates (`prompts/*.md`)
- ✅ Sandbox image Dockerfile + network policy
- ✅ Backend module skeleton with docstrings (50+ files, all stubs with TODOs)
- ✅ Frontend skeleton (Vite + React + TypeScript)
- ✅ Issue templates + PR template
- ✅ Pre-written Issue text for all of Phase 0 (`docs/ISSUES.md`)

## What you do first

1. `cd Skoll`
2. `git init && git add . && git commit -m "chore: bootstrap Skoll handoff package"`
3. Add as git submodules:
   - `git submodule add https://github.com/therudywolf/ForestOptiLM vendor/ForestOptiLM`
   - `git submodule add https://github.com/therudywolf/PhotoAISorter vendor/PhotoAISorter`
4. `cp .env.example .env` and fill in LM Studio URL.
5. `make install` (this will fail until you've actually populated dependencies — that's fine, the configs are pinned).
6. Open `docs/ISSUES.md`, take Issue **0.1**, follow the workflow in §5 of `AGENTS.md`.

## What you don't do

- **Don't redesign.** Decisions are frozen in `AGENTS.md`. If you have an objection, open an `arch-debate`-labeled Issue first, don't change the stack in a PR.
- **Don't add new tools without a JSON schema.** Schema in `contracts/tools/` comes first, implementation second.
- **Don't bypass approval gates.** `write_file`, `apply_diff`, `run_bash`, `git_commit` are gated. If you find yourself working around the gate, you're solving the wrong problem.
- **Don't `pip install` at runtime in the sandbox.** All deps at image build time.
- **Don't use `subprocess(shell=True)`.** Ever.

## Help — I'm stuck

| Symptom | Where to look |
|---|---|
| "What does this module do?" | The module's docstring, then `docs/ARCHITECTURE.md` |
| "What should this tool return?" | `contracts/tools/<name>.json` `result_schema` |
| "How should the API behave?" | `contracts/openapi.yaml` is the source of truth |
| "Is this safe?" | `docs/THREAT_MODEL.md`, and `§3 The Golden Rules` in `AGENTS.md` |
| "Which model should I test against?" | `docs/TESTED_MODELS.md` |
| "Why was this decided?" | `../Skoll_research_and_blueprint.md` |

If a question isn't answered anywhere, open an Issue tagged `clarification-needed`. Do not guess in a PR.

## Done?

When all Phase 3 Issues close:
1. Bump version to `0.1.0`
2. Replace this file with a real `CONTRIBUTING.md` for human contributors
3. Add a 60-second demo GIF to README.md
4. Tag v0.1.0 and publish

Good luck. The wolf is hungry.
