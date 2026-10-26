# docs/RFCs

RFCs in this directory are architectural and mechanism proposals. A `Draft` RFC has not yet landed in `docs/design/` or `ARCHITECTURE.md` and does not describe current shipped behavior. An `Accepted` RFC has been folded into those pages and remains the decision record. Product and mechanism truth lives in [`docs/design/`](../design/), and module layout lives in the root [`ARCHITECTURE.md`](../../ARCHITECTURE.md).

One RFC decides one mechanism. Name the file `NNNN-short-name.md`, starting at `0001`. Put the status, date, and decision summary in the metadata table at the top of the file. Valid statuses are `Draft`, `Accepted`, and `Superseded`.

## When to write an RFC

Write an RFC before changing Attempt identity, phase order, evidence schemas, `EnvironmentProvider` or `BaseExecutor` contracts, or cross-process protocols. Edit the existing design pages directly for wording improvements, examples, and reader-facing documentation.

When an RFC is accepted, fold its normative rules into the `docs/design/` pages and `ARCHITECTURE.md` sections listed at the end of the RFC. Mark the RFC `Accepted` and link those updated pages so two documents never claim conflicting current behaviors. If a later RFC replaces an earlier one, mark the older RFC `Superseded` and link the replacement.

## Standard RFC structure

Organize each RFC into the following sections (omit a section only when it genuinely does not apply):

1. **Metadata and Decision Summary**: Status, date, `Decides` (the core mechanism and contract changes), and `Does not decide` (explicit non-goals and deferred follow-ups).
2. **Motivation and Current Limitations**: State the concrete problem, how the current codebase behaves, and why incremental patching is insufficient. Define the core terms (`Attempt`, phases, evidence files) so a reader can understand the proposal without opening five other files first.
3. **High-Level Architecture and Data Flow**: Present end-to-end Mermaid diagrams (control flow and data/storage flow) before diving into field-level rules. Introduce every component and state shown in the diagrams.
4. **Data Schemas and SPI Contracts**:
   - **Data schemas**: Give exact file paths, `ageval.*/1` format identifiers, field tables with types and invariants, state transition rules, and a realistic JSON or YAML example.
   - **SPI contracts and component matrix**: Specify the exact method signatures added or changed on `BaseExecutor`, `EnvironmentProvider`, `ParentAgentService`, or `ageval_sdk`, followed by an adaptation matrix showing how each existing plugin category implements the contract.
5. **Execution Paths and Reference Pseudocode**: Provide readable Python-style pseudocode (4-space indentation) for the live execution path, recovery or fallback path, and invariant checks. Pseudocode specifies behavioral semantics and branch conditions rather than line-by-line implementation boilerplate.
6. **Failure Modes, Quotas, and Trade-offs**: Tabulate deterministic outcomes for crashes, timeouts, corrupted state, concurrency, and `limits` accounting, and explain why the chosen mechanism was preferred over alternatives.
7. **Target Specifications to Update on Acceptance**: List the exact `docs/design/` pages and `ARCHITECTURE.md` sections that will be updated when the RFC is accepted.

## Terminology and style rules

- **Canonical terminology**: Follow [`docs/glossary.md`](../glossary.md). Call one task execution an `Attempt` (`.ageval/runs/<attempt_id>/`). Call a multi-task dataset run a `suite` (`.ageval/suite-runs/<suite_run_id>/`). Use `jobs` only for the run list in Hub and Viewer. Never call an Attempt a job, never call `profiles.yaml` a job document, and never call an environment or container a `box` in prose.
- **Mechanism-based naming**: Name plugins and contracts after protocols or execution mechanisms (`acp`, `docker`, `e2b`, `ssh`, `openai-http`), never after benchmarks or vendor products. When adopting durability or protocol rules from an external design (such as Pi Durable), credit the source and state the concrete rules taken from it.
- **Credential safety**: Never write plaintext credential values into `activity.jsonl`, `lock.json`, `result.json`, `trajectory.jsonl`, or checkpoints.
- **Clear engineering prose**: Write in clear English or Chinese consistent with the target design docs. State the subject, action, condition, and outcome explicitly. Use normal causal and conditional clauses (`because`, `when`, `if ... then`, `otherwise`) so state transitions and invariants read naturally without telegraphic fragmentation.
- **Hygiene**: Do not use em dashes, contrastive filler clichés, GitHub Issue numbers (put Issue links in the PR description), or machine-specific absolute paths (`/Users/...`).
