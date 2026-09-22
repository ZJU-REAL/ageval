# ageval agent instructions

Repo-level routing for agents and contributors: what to read, what wins, the current facts, the boundaries, and how to deliver and check the work.
Mechanism design lives in [`docs/design/`](docs/design/). The structure map is [`ARCHITECTURE.md`](ARCHITECTURE.md). Incremental delivery is **GitHub Issues**.

## Product name

| Item | Value |
| --- | --- |
| Release name | **ageval** (agent eval) |
| Delivery unit | **dataset** (`ageval.dataset/1`). A SQL database is a different thing. |
| CLI / package | `ageval` / import `ageval` |
| Home / env | `~/.ageval`, `AGEVAL_*` |
| GitHub | [`ZJU-REAL/ageval`](https://github.com/ZJU-REAL/ageval) |
| Generation | greenfield; incompatible with archived v1; unknown format is `invalid_format` |
| v1 reference | Local archived v1 is read-only. Do not import it. Do not assume API compatibility. |

## Read order

Before changing code, a contract, or public behavior, read in this order:

1. [ARCHITECTURE.md](ARCHITECTURE.md) — current vs target structure, module ownership, dependency direction, lifecycle, data flow
2. [docs/README.md](docs/README.md) and the relevant [docs/design/](docs/design/) pages — **design authority (self-contained)**; for words, read [docs/glossary.md](docs/glossary.md) first (canonical name + Avoid + surface)
3. [docs/PRD.md](docs/PRD.md) — product spec and non-goals
4. The relevant **GitHub Issue** (Acceptance / non-goals / evidence required)
5. Code, tests, `examples/`, public smoke

Reader-facing product docs live in [`website/`](website/) (optional). They do not own design truth.

## Authority order

```text
docs/ (PRD + design/*)      ← product and mechanism authority; self-contained
  → ARCHITECTURE.md         ← implementation structure (current vs target, ownership, dependencies)
  → GitHub Issues           ← incremental delivery, discussion, acceptance (main track)
  → public smoke / code / tests / evidence

website/                    ← reader-facing product docs (rewrite); does not own design truth
apps/* / services/* README  ← SPA / service development detail; not the product-tutorial authority
```

### Conflicts

1. Stop the conflicting implementation.
2. Decide whether this is a design change, a structure change, a scope change, or an implementation drift.
3. **Change the highest authority artifact first** (design → `docs/`; structure → Architecture; delivery tracking → Issue; implementation → code).
4. In the same change, update the downstream copies (README, skills, the relevant website pages, tests, evidence claims).

### Historical SDD scaffold

The in-repo `specs/` tree (Active Spec / ROADMAP / constitution / BLOCKED) **has been removed**.
History is still in Git. Day to day, **do not** create a new Spec workspace or a checkbox tracker.
Settled design lives in `docs/` (self-contained). Delivery tracking lives in Issues.

An out-of-repo BRIEF was a one-time construction brief. **The product model now lives in this repo's `docs/`.** Do not read a vault or a BRIEF as authority. Do not keep two designs.

## Current facts

| Item | Status |
| --- | --- |
| Design | `docs/` (PRD + design 00–14 + glossary) is **self-contained**. Do not read an out-of-repo BRIEF. |
| Production source | Config → five phases of `attempt.run_attempt` → environment kind → ACP `attach_stdio` → in-environment evaluate → evidence; registry + contrib under `src/ageval/plugins/`; external `plugins/` |
| Public entrypoints | `ageval lock` / `run` / `campaign` / `view` / `evidence` / `plugin` / `jobs` / `results` and the rest of `ageval --help`. `ageval run` prints a `logs` locator. |
| Environments | `local` / `docker` have a public real run. `e2b` / `ssh` / `daytona` code exists; without credentials `--probe` fails and the run must not start. **Do not** mark those done. |
| Evidence grade | **Limited to `runnable-mvp`** (core local/docker ACP, and the examples `minimal-demo` names). See [examples/README.md](examples/README.md). **Do not** widen that to a full-suite `isolated` claim. |
| Delivery tracking | **GitHub Issues** |
| Docs site | [`website/`](website/) is reader-facing Fumadocs. Mechanism authority stays in `docs/`. |
| ACP | `executor: acp` + `options.entry`. The parent is the only JSON-RPC client. |
| Agent Hub | [docs/design/14](docs/design/14-agent-hub.md): `ageval.agent/1` harness. `--agent` and `--profiles` are mutually exclusive. `--model` is a run parameter. |

**Do not** infer `runnable-mvp` / `isolated` / `real-benchmark-verified` from a doc existing, an Issue existing, a successful `ageval lock`, or a design sketch.

## Four hard rules (construction)

### 1. No backward compatibility

Old names are not supported. No migration layer, no dual read, no alias for an old name.

- Formats are only `ageval.dataset/1`, `ageval.task/1`, `ageval.plugin/1`, `ageval.profiles/1`.
- Unknown format: **one** error (`invalid_format` at `/format`), then stop. Do not teach a mapping in the error.
- Env vars, home directory, and CLI are only `AGEVAL_*`, `ageval`, `~/.ageval`.
- `provider.kind` and `assurance`: reject or delete. Do not translate them.

### 2. Delete rather than patch over

An old path and a new path do not coexist. When the new path runs, delete the old files in the same change.

- Forbidden: a `compose_from_*` alias, an empty forwarder, a `NotImplemented` placeholder, two Agent Services side by side.
- Forbidden: a `try/except` wrapper that hides an old module so the suite stays green.
- On `EnvironmentManager` or `wrap_docker_exec`: delete them. Move the logic to the place design names, or do not do it.

### 3. No mock / fake

There is no product `executor: mock`. A `FakeHost` or an empty `AgentService` is not completion evidence.

| Allowed | Forbidden |
| --- | --- |
| `environment: local` (real filesystem) | `FakeHost`, or an in-memory environment, as acceptance |
| `environment: docker` (real container) | A mock docker SDK as completion of that surface |
| A real ACP CLI + `attach_stdio` | A stub Agent Service, an in-process fake worker |
| **Skip** the job when credentials are missing | A fake agent that turns the test green and then marks the work done |
| Tests that call real `ageval lock` / `ageval run` | An internal-function test standing in for a public smoke |

`AGEVAL_SKIP_REAL_ACP=1` means **CI did not run that check**. Not run is not a pass.

### 4. No defensive programming

Write the straight path. A failure fails.

- Do not build a friendly error-code table for every old field. An unknown key is rejected, with one message.
- Do not catch `Exception` and continue as `{"status":"ERROR"}` (the evaluate boundary records a phase failure; that case is the exception).
- Do not add an unproven probe, retry, or compatibility layer.
- Missing quota, capability, credentials, or `attach_stdio`: lock or invoke fails **once**.

## Project boundaries (agents must not cross)

### Architecture and ownership

- **Core:** Config `load_and_lock`; the five Attempt phases; the environment Protocol; Capability; stop writing, then score, and bind the result.
- **The agent sees only the files it is allowed to see.** That is a capability. Gold stays unmounted and is uploaded before evaluate. Deleting a field in config is not isolation.
- **Dataset `run.py`** owns the in-Attempt business workflow (loop, roles, local Tools, handoff).
- The **SDK** is optional. An upstream framework may replace it. It does **not** own Run identity, environment control, credentials, or final PASS.
- The control plane does **not** import or execute a dataset `run.py` or an evaluator **module**. It calls across a process or adapter boundary.
- Concrete platform objects are wired only in the **production composition root** (`build_*` in `application/composition.py`).
- A third-party agent or workflow SDK is not the authority for Core identity, effects, or the verdict.
- **No marker lifecycle:** `cleanup` / `evaluate` / `bind` must not return an empty `_fact` while production has a separate real implementation.
- One Attempt allows one `IdentityFactory.new_run` (test doubles excepted).
- The CLI imports only `ageval.application.composition`.
- `.ageval/runs` layout strings live only in `evidence/`.
- A new public `application` use case has a `build_*`.
- A Registry handler does not touch `state.meta` or call `_bearer` again. The work lives in a `*Service`.

### Structure red lines (design §4.10)

1. Opening `attempt/__init__.py` names the phases. Do not split the lifecycle into files by isolation tier.
2. The test surface is **a real kind + the public CLI**. A docker / e2b seam holds when two real winners exist. A FakeHost does not establish it.
3. **No copy-grep tests, and no UI component tests.** A person accepts website, Hub, and Viewer UI by looking at the rendered page. Do not `read_text` a landing page, a `website/` snippet, or a README and then `assert "some string" in/not in text`. Changing a slogan would go false-red. Do not add a component, snapshot, or browser test file under `apps/` or `website/`. Do not add a pytest that asserts visible copy, a class, a DOM id, or HTML the test itself wrote (a hand-written `index.html` asserted for its title or `id="root"` is this case). When the reader-facing copy is right, edit the doc. Behavior behind the page is a Python HTTP / CLI test (`ageval lock` / `run` / an environment method). Tokens and glossary terms stay on `scripts/check_design_tokens.py` and `scripts/check_public_terms.py`. Architecture tests pin runtime red lines only (imports, slots, the composition root).
4. Locality: `docker exec` lives only in the docker contrib. ACP / `attempt` / `run.py` do not see `container_id` and do not branch on `if kind == e2b`.
5. One path. Choosing an environment or an executor goes through the exclusive slot only. No second resolve.
6. Platform objects are wired only in `build_*` inside `application/composition.py`.
7. The control plane does not import dataset modules.
8. PASS, identity, and cleanup are not plugin services. Cleanup runs in `try/finally`.
9. Adapters are named by mechanism. Do not branch on a benchmark or task name.
10. Layout strings live only in `evidence/`. Lock and evidence do not store a host token.
11. Inject finishes during lock. Missing `attach_stdio` fails the lock.

### Safety and evaluation

- `RunTerminal.completed` **≠** PASS. PASS comes only from an independent evaluator.
- Runtime outcome, the agent result, evaluator raw, and the final evaluation stay **independent facts**.
- Do not copy, serialize, or write a host credential or token into lock, evidence, or a dataset's default environment. A scoped projection goes only to a process that is allowed to have it.
- Runtime enforces `limits` **before** execution. `run.py` cannot raise its own. Token and cost after the fact are observational by default.
- Adapters and plugins are named by **protocol, resource type, or execution mechanism**. **Do not** branch on a benchmark, task, or domain name.
- The plugin model is an entry point plus a package install. It is **not** an open app store. Agent Service stays in this repo.

### Agent backend / ACP

- Coding-agent **target inlet**: `executor: acp` plus `- plugin: acp` / `options.entry`. The parent is the **only** ACP JSON-RPC client, and that client writes evidence.
- Vendor-private format translation lives **outside the process**, in the ACP entry (Mode 1 shim / Mode 2 native / Mode 3 vendor package). **Do not** add a second vendor stdout scrape inside ageval.
- The **official Attempt image** under `src/ageval/plugins/contrib/docker/attempt/` bakes, **at build time**, the engine and ACP entry for the minimum entry set (Mode 1 installs **both** the engine and the adapter: codex / claude / **pi**, each with its adapter). The recipe ships in the wheel. `ageval run` pulls `ghcr.io/zju-real/ageval-attempt:<cli-ver>` to the local tag `ageval-attempt:base`, and builds from the packaged Dockerfile only when that pull misses. It does not depend on a cwd checkout. A dataset recipe then stacks ACP `image_layers` and bakes only the bound `options.entry`. Do not `npm i` or float `npx` at invoke time. The Python ACP SDK stays **on the parent only**. It does not enter the Attempt image.
- Pi: the official registry id is **`pi-acp`** (npm `pi-acp`, bridging `pi --mode rpc`). Do not confuse it with the reverse bridge `pi-shell-acp`.
- **Visibility:** mount + `docker exec -u/-w` + UID/GID (docker contrib only). **Permission:** batch ACP auto-approves by default. It does not raise privileges and does not cross a path that was not projected. Evidence records the decision.
- Authority: [docs/design/05-runtime/agent-service.md](docs/design/05-runtime/agent-service.md).

### Multi-agent scheduling

- On docker, multiple actors use the same SDK surface as local: `Agent.session(...).invoke`. Do not silently move that back onto the host.
- YAML declares logical isolation only (`shared-container` / `container-per-group`, groups, actors, `shared_write`). The Runtime owns the container id and the UID.
- See [`docs/design/05-runtime/`](docs/design/05-runtime/) and ARCHITECTURE Current. This round does **not** promise a real multi-group scheduling run (a lock that carries topology is enough).

### Package and config

- The canonical delivery unit is a **dataset** (root `ageval.yaml` / `ageval.dataset/1`). Each task is a member `task.yaml`. Config Core is the only canonical reader.
- `parameters` go to `run.py` (`ctx.params`). Envelope, profiles, and limits go to the Runtime. `run.py` must not read a second "real config" that overrides the lock.
- Environment variables are locators. They do not replace a production mechanism.
- A job picks its environment from `environment:` in `profiles.yaml`, not from `provider.kind`.

### Delivery and evidence

- **New work opens a GitHub Issue by default** (Acceptance / non-goals / evidence). **Do not** create an in-repo Active Spec or ROADMAP.
- A fixture or mock may back an automated regression. It **cannot** by itself be a public smoke or a reason to raise the evidence grade.
- Do not write a pytest that checks whether a landing page, README, or website snippet contains a sentence. Do not add a component, snapshot, or browser test for website, Hub, or Viewer, and do not add a pytest that asserts visible copy, a class, a DOM id, or HTML the test itself wrote. See structure red line 3.
- A safe, reversible choice during implementation can proceed. Ask the user, or write it in the Issue, when the change needs a new permission, is hard to reverse, or changes a product safety meaning.
- `docs/reference/` is an archive. It is **not** authority, and it is not a vault entrance.
- **Having `website/` does not** raise the evidence grade.

## Delivery rules (operations)

| Situation | What to do |
| --- | --- |
| Product or mechanism design changes | Edit `docs/design/*` first (and PRD / glossary when needed), then Architecture / code / the relevant website pages |
| Module tree, dependencies, or the composition root changes | Edit [ARCHITECTURE.md](ARCHITECTURE.md) first |
| Incremental feature / acceptance tracking | Open or update a **GitHub Issue**. Implementation and the PR link the Issue |
| Teaching use (CLI / Viewer / Hub) | Update [`website/`](website/). Development detail stays in `apps/*` / `services/*` READMEs |
| Unauthorized implementation | **Do not** invent a production behavior change with no basis, and do not run a smoke that pretends the work is done |

Tracking Markdown uses **repo-relative links**. Do not put a machine-only absolute path in AGENTS or Architecture as an authority link (an archive path may be named in prose).

### No Issue numbers on outward docs (hard rule)

**Reader-facing / outward docs must not contain a GitHub Issue number** (`#66`, `#59`, `Issue #60`, `Closes #xx` wording).

| Applies | Does not apply (Issue references may stay) |
| --- | --- |
| Root `README.md` / `README.zh-CN.md` | `AGENTS.md`, `ARCHITECTURE.md` (contributor routing) |
| All reader-facing body in [`website/`](website/) (Chinese and English) | `docs/design/*`, internal PR / Issue discussion |
| `examples/**/README*` and in-package reader notes | `Closes #N` in an implementation or PR description |
| Product site, tutorials, public smoke narrative | A test name or a code comment that only developers see (still keep those scarce) |

**How to write it:** state the boundary in product terms (example: "the monorepo ships only the reduced tau3-airline-5; a larger bench goes through Hub"). Do not use a delivery-tracking number such as "the #66 delivery boundary" as a heading or a body marker.
If an outward surface already has a `#digits` Issue trace, **delete it before merging**. Keep Chinese and English in sync.

## Evidence grades

| Grade | Meaning | When it may be claimed |
| --- | --- | --- |
| `design-only` | Docs only | A path public smoke does not cover |
| `runnable-mvp` | A real public entrypoint plus a real Agent path | When the matching public journey evidence exists |
| `isolated` | An isolated Attempt plus the isolation red lines | When the matching isolation acceptance evidence exists |
| `real-benchmark-verified` | A fixed upstream plus a scoped public journey | When the matching acceptance evidence exists. Do not widen it to the full suite. |

## Checks

### When to run the CI gate

| Action | Run the equivalent CI locally first? |
| --- | --- |
| **Ordinary local commit** | **No** full CI every time. Run the gate that matches the paths you changed. |
| **`git push`** (especially a branch that will merge to `main`) | **Yes.** The relevant jobs in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) pass locally first. |
| **Opening or updating a PR, cutting a release, tagging, publishing** | **Required.** Confirm the CI jobs that will fire will pass, then push / open the PR / release. |

Before helping with a push, a PR, or a release, an agent **must not** skip the gate because "it imports locally" or "only docs changed". Run the **CI-equivalent commands** for the paths below, or say which ones already passed. Fix failures before pushing.

### CI gates (path-filtered parallel jobs)

| Job | Trigger paths (summary) | Local equivalent |
| --- | --- | --- |
| `python-core` | `src/` `sdk/` `tests/` `examples/` `services/` `docker/` `scripts/` `pyproject.toml` `uv.lock` `VERSION` … | Python core, below |
| `python-registry` | Same as core (parallel; `tests/registry` only) | `uv sync --frozen --extra registry` + `pytest tests/registry` |
| `viewer-app` | `apps/viewer/**` `apps/shared/**` | `pnpm --dir apps/viewer install --frozen-lockfile && pnpm --dir apps/viewer lint && pnpm --dir apps/viewer build` |
| `hub-app` | `apps/hub/**` `apps/shared/**` | `pnpm --dir apps/hub install --frozen-lockfile && pnpm --dir apps/hub lint && pnpm --dir apps/hub build` |
| `website` | `website/**` | `pnpm --dir website install --frozen-lockfile && pnpm --dir website build` |
| `design-tokens` | `docs/design/13*` / token script / CSS on the three web surfaces | `python3 scripts/check_design_tokens.py` |

A change to `.github/workflows/ci.yml` reruns every job. A SPA-only or website-only change does **not** run the full Python suite.
Default CI has **no** real Docker e2e, **no** real Agent/API e2e, and **no** real E2B/SSH. A skip is **not** an Acceptance pass.

#### Python core (`python-core`)

```bash
uv sync --frozen
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
export AGEVAL_OFFLINE_AGENT=1 AGEVAL_SKIP_DOCKER=1
export AGEVAL_SKIP_REAL_CODEX=1 AGEVAL_SKIP_REAL_PI=1
export AGEVAL_SKIP_REAL_OPENCODE=1 AGEVAL_SKIP_REAL_ACP=1
# The pytest --ignore list must match job python-core in .github/workflows/ci.yml
uv run pytest --ignore=tests/registry -q
```

#### Python registry (`python-registry`)

```bash
uv sync --frozen --extra registry
export AGEVAL_OFFLINE_AGENT=1 AGEVAL_SKIP_DOCKER=1
uv run pytest tests/registry -q
```

If the change touches docker, a real Agent, e2b, or ssh, run the extra checks the Issue or the related tests name. Those are **not** in default CI.
Branch protection required checks must include the job names above.

## Related entry points

| Doc | Use |
| --- | --- |
| [`.agents/skills/`](.agents/skills/) → [`skills/`](skills/) | Skills discoverable after clone (ageval-platform / cli / config-package / sdk-harness / plugin) |
| [README.md](README.md) | Human entry and status |
| [website/](website/) | Reader-facing product docs (Chinese / English) |
| [docs/design/00-overview-and-product.md](docs/design/00-overview-and-product.md) | Product model, US1–US12, naming |
| [docs/design/01-ageval-core.md](docs/design/01-ageval-core.md) | Core: lock + five phases + environment |
| [docs/design/09-owner-matrix-and-structure.md](docs/design/09-owner-matrix-and-structure.md) | Owner matrix |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Source tree, dependencies, lifecycle diagram |
| [GitHub Issues](https://github.com/ZJU-REAL/ageval/issues) | Incremental delivery and acceptance tracking |
