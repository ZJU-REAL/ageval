## What is this for

<!-- Briefly describe the background and the problem this PR solves (what scenario, limitation, or defect is being addressed, and why). -->

## Implementation

<!-- Summarize how the change is implemented (use bullet points or short paragraphs; include flowcharts, sequence diagrams, or concise pseudocode where helpful to clarify control flow, phase boundaries, or data structures). -->

## Verification

```bash
# Commands actually run and summary of results (e.g. bash scripts/check.sh, pytest, ageval lock|run)
```

## Related

- Issue:
- Evidence grade (if claimed):

## Checklist

- [ ] No credentials or plaintext tokens in YAML, lock, evidence, or examples
- [ ] Trajectory or `RunTerminal.completed` is not treated as `PASS`
- [ ] Corresponding documentation (`docs/design/*`, `ARCHITECTURE.md`, `website/`) is updated when wrapping up changes to product semantics, module structure, or user-facing behavior
- [ ] Regression tests or public smoke checks cover the changed path; a fixture alone is not `runnable-mvp`
