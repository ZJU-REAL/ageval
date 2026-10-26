# ageval agent instructions

Repo-level routing for agents and contributors: what to read, source-of-truth hierarchy, current implementation status, architectural boundaries, and delivery/verification rules.
Mechanism design lives in [`docs/design/`](docs/design/). The module structure map is [`ARCHITECTURE.md`](ARCHITECTURE.md). Incremental delivery is tracked in **GitHub Issues**.

## Product identity

| Item | Value |
| --- | --- |
| Release name | **ageval** (agent eval) |
| Delivery unit | **dataset** (`ageval.dataset/1`), distinct from a SQL database |
| CLI / package | `ageval` (PyPI `ageval-cli`) / import `ageval` and `ageval_sdk` |
| Home / env | `~/.ageval`, `AGEVAL_*` |
| GitHub | [`ZJU-REAL/ageval`](https://github.com/ZJU-REAL/ageval) |
| Format policy | Only `ageval.*/1` formats are accepted; unknown formats fail with `invalid_format` |

## Read order

Before changing code, a contract, or public behavior, read in this order:

1. [ARCHITECTURE.md](ARCHITECTURE.md) — current vs target structure, module ownership, dependency direction, lifecycle, and data flow
2. [docs/README.md](docs/README.md) and the relevant [docs/design/](docs/design/) pages — **design authority (self-contained)**; for terminology, read [docs/glossary.md](docs/glossary.md)
3. [docs/PRD.md](docs/PRD.md) — product requirements and non-goals
4. The relevant **GitHub Issue** (acceptance criteria, non-goals, required evidence)
5. Code, tests, `examples/`, and public smoke checks

Reader-facing product documentation lives in [`website/`](website/) and summarizes usage rather than owning mechanism design.

## Authority order

```text
docs/ (PRD + design/*)      ← product and mechanism authority (self-contained)
  → ARCHITECTURE.md         ← implementation structure (current vs target, ownership, dependencies)
  → GitHub Issues           ← incremental delivery, discussion, acceptance
  → public smoke / code / tests / evidence

website/                    ← reader-facing product docs; does not own design truth
apps/* / services/* README  ← SPA / service development detail
```

### Resolving conflicts and syncing docs

1. When implementation and specifications disagree, stop and determine whether the discrepancy is a design change, a structure change, a scope change, or an implementation bug.
2. `docs/` and `ARCHITECTURE.md` remain the authoritative specifications for product semantics and module layout.
3. **Documentation timing:** You do **not** need to write or commit documentation at the very beginning before writing code (which produces low-density, doc-only commits). Instead, complete the corresponding documentation updates (`docs/design/*`, `ARCHITECTURE.md`, README, skills, and `website/`) when wrapping up a phase or finishing the task.

## Current status

| Item | Status |
| --- | --- |
| Design | `docs/` (PRD + design 01–09 + glossary) is self-contained |
| Production pipeline | Config locking → four Attempt execution phases (`environment → run → evaluate → record`, with `cleanup` in `finally`) → environment plugin → ACP `attach_stdio` or worker/HTTP executor → isolated evaluation → evidence archive |
| Public entrypoints | `ageval lock` / `run` / `campaign` / `view` / `evidence` / `plugin` / `jobs` / `results` and the rest of `ageval --help` |
| Environments | `local` and `docker` have verified public runs; `e2b`, `ssh`, and `daytona` implementations exist and fail preflight (`--probe`) when credentials are absent |
| Evidence grade | **`runnable-mvp`** (core local/docker ACP and named `minimal-demo` tasks; see [examples/README.md](examples/README.md)) |
| Delivery tracking | **GitHub Issues** (do not create in-repo `specs/` or `ROADMAP.md` trackers) |
| Docs site | [`website/`](website/) (Fumadocs, bilingual `en` / `zh-CN`) |
| ACP | `executor: acp` + `options.entry`; the parent process is the sole JSON-RPC client |
| Agent packages | [docs/design/08](docs/design/08-hub-registry-and-agents.md): `ageval.agent/1` package; `--agent` and `--profiles` are mutually exclusive; `--model` overrides the run model |

Do not infer `runnable-mvp`, `isolated`, or `real-benchmark-verified` from documentation, an open Issue, or `ageval lock` alone.

## Four construction rules

### 1. No backward-compatibility shims

Legacy formats and field names are not supported. Do not add migration layers, dual readers, or legacy aliases.

- Valid formats: `ageval.dataset/1`, `ageval.task/1`, `ageval.plugin/1`, `ageval.profiles/1`, `ageval.agent/1`, `ageval.trajectory.event/1`.
- Unknown format: fail fast with a single `invalid_format` error at `/format`.
- Environment variables, home directory, and CLI are `AGEVAL_*`, `ageval`, and `~/.ageval`.
- Reject legacy fields such as `provider.kind` and `assurance`.

### 2. Delete obsolete paths rather than wrapping them

Do not keep old and new code paths side by side. When a replacement lands, remove the superseded module in the same change.

- Forbidden: compatibility forwarders, `NotImplemented` placeholders, or duplicate Agent Services.
- Forbidden: `try/except` wrappers that mask broken legacy modules.

### 3. No mock executors or fake environments as completion evidence

There is no product `executor: mock`. A fake host or stubbed service does not satisfy acceptance criteria.

| Allowed | Forbidden |
| --- | --- |
| `environment: local` (real filesystem) | In-memory fake hosts as acceptance evidence |
| `environment: docker` (real container) | Mocked Docker SDK calls as feature completion |
| Real ACP CLI + `attach_stdio` | Stubbed Agent Service or in-process fake workers |
| **Skip** the check when credentials are absent | Fake agents that turn live tests green without credentials |
| Tests driving `ageval lock` / `ageval run` | Internal-function calls standing in for public CLI smoke checks |

`AGEVAL_SKIP_REAL_ACP=1` means **CI did not run that check**; a skipped check is not a pass.

### Test layers

Most tests check one code path. The test builds the input (an activity prefix, a file mode, a clock, or a server it starts and stops) and asserts `status`, `error.title`, or the exit code.

A fidelity test runs public `ageval lock` / `ageval run` on a real filesystem, a real container, or a real ACP entry. No daemon, no entry, or no credential: record it as skipped. `AGEVAL_SKIP_*` is that record.

### 4. Fail fast without silent fallbacks

Write direct control flow and surface failures explicitly rather than swallowing exceptions.

- Catch concrete exception types or re-raise. Bare `except Exception` that silently passes or returns a default is forbidden (`contextlib.suppress(Exception)` included).
- Boundaries that convert failures into typed outcomes (phase `ERROR`, cleanup warning, non-fatal hook warning, or worker failure envelope) must record that outcome explicitly.
- Unknown configuration keys fail validation with a clear message.
- A retryable non-ok executor invocation enters `upstream_stall` up to `options.upstream_stall_seconds` (default 3600; `0` disables) at a fixed 60-second interval, then fails once.
- Unsatisfied capabilities or missing `attach_stdio` fail during `ageval lock`. Pre-invocation parent refusals (exhausted wall-clock time, exhausted invocation quota, redaction failure, or forced offline mode) fail immediately without entering `upstream_stall`.

## Architectural boundaries

### Component responsibilities

- **Core:** `load_and_lock` configuration resolution; the fixed Attempt lifecycle (`environment → run → evaluate → record`, with `cleanup` in `finally`); the `EnvironmentProvider` protocol; capability enforcement; sealing solver sessions before uploading reference materials (`gold`) and binding the evaluation verdict.
- **Workspace isolation:** The evaluated agent sees only files projected into its workspace. Reference materials under `evaluation/` remain unmounted during `run` and are uploaded only when `evaluate` begins (or into an isolated scoring container).
- **Task `run.py`:** Owns task-specific control flow (interaction loops, role routing, domain tools, and artifact registration).
- **Python SDK (`ageval_sdk`):** Optional task-script helper (`RunContext`, `AgentSession`, `ToolSet`, concurrency primitives). It does not own run identity, environment lifecycle, host credentials, or the `PASS` verdict.
- **Process boundary:** The parent control plane executes `run.py` and `evaluator.py` in isolated subprocesses rather than importing task modules in-process.
- **Composition root:** Production platform objects are wired exclusively in `build_*` functions inside `src/ageval/application/composition.py`. The CLI imports only `ageval.application.composition`.
- **Evidence layout:** `.ageval/runs` path constants live exclusively in `src/ageval/evidence/`.

### Structural invariants (design §4.10)

1. `attempt/__init__.py` defines the top-level phase sequence directly.
2. Fidelity tests run the public CLI on a real environment. Logic tests use a fixture.
3. **No copy-grep tests or UI snapshot tests:** Website, Hub, and Viewer UIs are verified visually on the rendered page. Do not add pytest assertions that grep prose in `README.md` or `website/`, and do not add component/snapshot test files under `apps/` or `website/`. Use `scripts/check_design_tokens.py` and `scripts/check_public_terms.py` for token and terminology checks, and Python HTTP/CLI tests for backend behavior.
4. **Locality:** `docker exec` stays inside `plugins/contrib/docker/`. ACP, `attempt/`, and `run.py` never inspect `container_id` or branch on environment kind (`if kind == "e2b"`).
5. **Single resolution path:** Environment and executor plugins are resolved exclusively through exclusive slots in `ExtensionRegistry`.
6. **Mechanism-based naming:** Plugins and adapters are named after protocols or execution mechanisms (`acp`, `docker`, `e2b`, `ssh`, `openai-http`), never after specific benchmarks.
7. **Static dependency injection:** `inject` capability requirements are verified during `ageval lock` before any environment starts.

### Evaluation and credential safety

- `RunTerminal.completed` **≠** `PASS`. `PASS` and `FAIL` come solely from `evaluator.py`.
- Host credentials and API tokens are referenced by environment variable names (locators) and projected only into authorized subprocesses; plaintext secrets never enter `lock.json`, `result.json`, `trajectory.jsonl`, or default logs.
- Core enforces `limits` before dispatching invocations; post-hoc token and cost metrics are observational.

### Agent execution and ACP

- Coding agents connect via `executor: acp` with `- plugin: acp` and `options.entry`. The parent process is the sole ACP JSON-RPC client and records normalized trajectory events.
- Vendor-specific protocol adaptation runs in the external ACP entry process rather than scraping unstructured stdout inside Core.
- The official Attempt base image (`src/ageval/plugins/contrib/docker/attempt/`) installs the base engines and ACP adapters at image build time. `ageval run` pulls `ghcr.io/zju-real/ageval-attempt:<cli-ver>` as `ageval-attempt:base` (or builds from the packaged Dockerfile on a miss), and stacks plugin `image_layers` for the bound `options.entry`. Do not run `npm i` or floating `npx` during invocation.

### Model configuration (`ModelSpec`)

Each role profile binds a nested `model:` block resolved into `ModelSpec` (`id`, `api`, `reasoning.effort`, `timeout`, `watchdog`, `extra`). Omitted fields are not sent; `reasoning.effort: none` is sent explicitly. Chat Completions encodes top-level `reasoning_effort`, while Responses encodes nested `reasoning.effort`. `extra` keys cannot override standard fields and must belong to the executor's `extra_allowlist` (an empty allowlist rejects all `extra` keys). Full details: [docs/design/02-schemas-and-config.md](docs/design/02-schemas-and-config.md) and [docs/design/05-executors-and-acp.md](docs/design/05-executors-and-acp.md).

## Delivery and workflow rules

| Situation | Action |
| --- | --- |
| Product or mechanism design changes | Ensure `docs/design/*` (and `PRD.md` / `glossary.md` when applicable), `ARCHITECTURE.md`, and affected `website/` pages are updated when wrapping up the phase or PR |
| Module tree, dependencies, or composition root changes | Ensure [ARCHITECTURE.md](ARCHITECTURE.md) is updated alongside the structural change |
| Incremental feature / acceptance tracking | Open or update a **GitHub Issue** and link it in the PR |
| User-facing CLI / Viewer / Hub changes | Update [`website/`](website/); keep developer-only service notes in `apps/*` / `services/*` READMEs |

Use repo-relative links in tracked Markdown files; never commit machine-specific absolute paths (`/Users/...`).

### Commit and PR conventions

- **Phase-completion doc sync:** Do not force a standalone `docs(...)` commit before writing code. Group documentation updates with the implementation phase they describe, or add them when wrapping up the phase/PR so every commit carries substantive information density.
- **Commit messages (`.gitmessage`):** Use Conventional Commits (`<type>(<scope>): <summary>`). For non-trivial changes, state the background/problem (`What is this for`) and summarize the key implementation points (`Implementation` bullets).
- **Local gate before commit:** A skill or instruction that calls checks optional does not apply in this repo. GitHub Actions runs only on a pull request and on pushes to `main`, so a feature-branch push is not a check. Run the local commands in [Verification and CI gates](#verification-and-ci-gates) before committing and again before pushing.
- **Pull request descriptions ([`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)):** Use a formal engineering structure:
  1. `## What is this for` — Briefly introduce the background and the problem being solved.
  2. `## Implementation` — Explain the implementation approach (structured bullet points or short paragraphs, combined with flowcharts, sequence diagrams, or concise pseudocode where helpful).
  3. `## Verification` — List the commands executed and test results.
  4. `## Related` & `## Checklist` — Link the Issue(s) and complete the safety/boundary checks.

### No Issue numbers on outward docs

Reader-facing documentation (`README.md`, `README.zh-CN.md`, `website/`, `examples/**/README*`, and plugin READMEs previewed on Hub) must **not** contain GitHub Issue numbers (`#66`, `Issue #60`, `Closes #N`). State product boundaries directly in product terms. Issue references belong only in `AGENTS.md`, `ARCHITECTURE.md`, `docs/design/*`, commits, and PR/Issue threads.

## Evidence grades

| Grade | Meaning | When it may be claimed |
| --- | --- | --- |
| `design-only` | Documentation only | Paths not covered by public smoke execution |
| `runnable-mvp` | Real public CLI entrypoint + real Agent execution | When matching public journey evidence exists |
| `isolated` | Isolated Attempt + verified isolation boundaries | When matching isolation acceptance evidence exists |
| `real-benchmark-verified` | Pinned upstream benchmark + verified public journey | When matching acceptance evidence exists for that scope |

## Verification and CI gates

GitHub CI is the second confirmation. The first confirmation is local. Do not push in order to discover `ruff format`, `ruff check`, or `pyright` failures.

### When to run checks

| Action | Local verification requirement |
| --- | --- |
| **Commit that touches** `src/`, `tests/`, `plugins/`, `services/`, or `scripts/` | **Required before `git commit`.** Run the fast gate below. A focused pytest does not replace it. Also run the focused tests for the paths you changed. |
| **`git push` / opening or updating a PR / cutting a release** | **Required.** Run [`scripts/check.sh`](scripts/check.sh), which is the local equivalent of `python-core`, `python-plugins`, and `python-registry`. Add `python3 scripts/check_public_terms.py` when reader-facing docs change, and `python3 scripts/check_design_tokens.py` when design tokens or web CSS change. Confirm they pass before pushing. |

Fast gate, same commands as the `python-core` lint steps:

```bash
uv run ruff format --check src tests plugins services scripts
uv run ruff check src tests plugins services scripts
uv run pyright
```

Install the same ruff and pyright commands as a commit hook once per clone:

```bash
uv run pre-commit install
```

The hook config is [`.pre-commit-config.yaml`](.pre-commit-config.yaml). `scripts/check.sh` still has to be run before push: the hook does not run pytest.

`python-core`, `python-plugins`, and `python-registry` share `.venv`; run them sequentially via `scripts/check.sh`, which restores `--extra nooa --extra dsh --extra miniswe` on exit.

### Shell wrappers

A test that executes a shipped `sh` wrapper must run it with `dash` when `dash` is on `PATH`. macOS `sh` is bash. Ubuntu CI `sh` is dash, and dash sends a background command's stdin to `/dev/null`. A pass under macOS `sh` does not count. If `dash` is missing, fail that test and install it (`brew install dash`). Do not skip.

### CI jobs (`.github/workflows/ci.yml`)

| Job | Trigger paths (summary) | Local command |
| --- | --- | --- |
| `python-core` | `src/` `tests/` `plugins/` `examples/` `services/` `docker/` `scripts/` `pyproject.toml` `uv.lock` `VERSION` | See `scripts/check.sh` |
| `python-plugins` | Same as core | `uv sync --frozen --extra miniswe --extra nooa --extra dsh && AGEVAL_REQUIRE_PLUGIN_DEPS=1 uv run pytest tests/plugins -q` |
| `python-registry` | Same as core (`tests/registry`) | `uv sync --frozen --extra registry && uv run pytest tests/registry -q` |
| `viewer-app` | `apps/viewer/**` `apps/shared/**` | `pnpm --dir apps/viewer install --frozen-lockfile && pnpm --dir apps/viewer lint && pnpm --dir apps/viewer build` |
| `hub-app` | `apps/hub/**` `apps/shared/**` | `pnpm --dir apps/hub install --frozen-lockfile && pnpm --dir apps/hub lint && pnpm --dir apps/hub build` |
| `website` | `website/**` | `pnpm --dir website install --frozen-lockfile && pnpm --dir website build` |
| `design-tokens` | `docs/design/09*` / token script / CSS on the three web surfaces | `python3 scripts/check_design_tokens.py` |

## Related entry points

| Document | Purpose |
| --- | --- |
| [`.agents/skills/`](.agents/skills/) → [`skills/`](skills/) | Repository skills (`ageval-platform`, `ageval-cli`, `ageval-config-package`, `ageval-sdk-harness`, `ageval-plugin`, `ageval-design-system`, `verify-ageval`) |
| [README.md](README.md) | Project overview and quick start |
| [website/](website/) | Reader-facing bilingual documentation |
| [docs/PRD.md](docs/PRD.md) | Product overview, user stories US1–US12, and architectural red lines |
| [docs/design/01-core-lifecycle.md](docs/design/01-core-lifecycle.md) | Core locking, phase lifecycle, `limits`, and failure taxonomy |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Source tree, module ownership matrix, dependency graph, and lifecycle flow |
| [GitHub Issues](https://github.com/ZJU-REAL/ageval/issues) | Incremental delivery and acceptance tracking |
