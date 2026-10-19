# Authority & documentation sync

## Source-of-truth hierarchy

```text
docs/design/*  →  ARCHITECTURE.md  →  GitHub Issues  →  code/tests/examples
```

`docs/` is self-contained. `ARCHITECTURE.md` defines the current source tree, dependency graph, Attempt state machine, extension emit map, data flow, and failure boundaries. Construction rules and CI gates live in root `AGENTS.md`.

`website/` is reader-facing product documentation; `apps/*` and `services/*` READMEs document SPA and service development details.

## Conflict resolution and doc sync timing

1. When implementation and specifications disagree, stop and classify the discrepancy: design change, structure change, delivery scope, or implementation bug.
2. `docs/` and `ARCHITECTURE.md` are the authoritative specifications for product semantics and module structure.
3. **Phase-completion doc sync:** Do not force a standalone doc-only commit at the start of a task before writing code. Update the corresponding documentation (`docs/design/*`, `ARCHITECTURE.md`, `README*`, `website/`, and skills) when wrapping up a phase or completing the PR.

## What skills are not

- Not a replacement for `docs/design/` or `ARCHITECTURE.md`.
- Not a license to claim unverified surfaces as complete.
- Not allowed to invent `ageval` subcommands or flags absent from `src/ageval/cli/main.py`.
