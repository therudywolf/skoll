# Contributing to Sköll

Sköll is in early-stage development. Most work is being driven through AI coding agents (Claude Code, Cursor, etc.) following the workflow in [`AGENTS.md`](AGENTS.md). Human contributions are equally welcome and held to the same standards.

## Before you start

1. Read [`AGENTS.md`](AGENTS.md). It defines stack, rules, and conventions. They apply to human contributors too.
2. Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/ROADMAP.md`](docs/ROADMAP.md).
3. For security-sensitive changes, read [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Workflow

1. Find an unassigned Issue labeled `ready` (or open a new one for unplanned work).
2. Comment `taking this`.
3. Branch from `main`: `phase-{N}/{issue-number}-{short-slug}`.
4. Commit using Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `sec:`).
5. Push and open a PR using the template. Link the Issue.
6. CI must be green. `make check` runs the same suite locally.
7. Review: at least one approval required before merge. Security-tagged PRs require maintainer review.

## Code style

Frozen in `AGENTS.md` §4. Summary:
- Python: ruff + mypy strict, type hints required, `async def` for I/O, Pydantic v2 for DTOs.
- TypeScript: strict mode, no `any`, function components only.
- Tests: pytest (backend), vitest (frontend). LM Studio is mocked in unit tests.

## Security

If your contribution touches the filesystem, shell execution, network, or LLM prompts:

- Update `docs/THREAT_MODEL.md` with the new threat and mitigation.
- Add tests under `backend/tests/security/` that exercise the malicious-input case.
- Tag the PR with `kind/sec`.
- Expect a thorough review.

See [`SECURITY.md`](SECURITY.md) for reporting vulnerabilities (which is different from contributing fixes).

## License

By contributing, you agree your work is licensed under **AGPL-3.0-or-later**, matching the project license. Sköll inherits AGPL from its dependency on [ForestOptiLM](https://github.com/therudywolf/ForestOptiLM) and [PhotoAISorter](https://github.com/therudywolf/PhotoAISorter); this is not negotiable.

## Code of Conduct

Be respectful. Disagree on technical grounds. No personal attacks. Maintainers reserve the right to remove offensive content and block bad-faith actors.

## Questions

If something isn't covered in `AGENTS.md`, `docs/`, or this file, open an Issue tagged `clarification-needed`. Better to ask than to guess in a PR.
