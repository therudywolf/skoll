<!-- Conventional Commits in title: feat(phase-N): summary (#issue) -->

## Summary

<!-- What does this PR do? One paragraph. -->

## Linked Issue

Closes #

## How to test

<!-- Step-by-step. Reviewer should be able to copy-paste. -->

## Security considerations

<!-- Required. If "none", explain why. New tools or endpoints MUST update docs/THREAT_MODEL.md. -->

## Checklist

- [ ] Title in Conventional Commits format
- [ ] `make check` passes locally
- [ ] New tools have a `contracts/tools/*.json` schema
- [ ] Prompts added/changed live under `prompts/` (not hardcoded)
- [ ] If FS / shell / network is touched, threat model updated
- [ ] If user-visible behavior changes, README updated
- [ ] Migrations regenerated if `db/schema.sql` changed
