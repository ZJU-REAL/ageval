# Isolation notes for package authors

Authority: `docs/design/06-capability-adapter-visibility.md`, `docs/design/05-runtime/environment.md`.

## Gold / evaluation material

- Put hidden labels under `evaluation/` (paths never mounted to Agent).
- Gold is uploaded at the start of evaluate, not during run. This is a cut in **time**, not `path_views`.
- Evaluator receives allowlisted staged inputs only after writer barrier.
- Optional LLM-as-judge: `Agent.session` is allowed **after** that upload. Solver profiles that already ran must not invoke. Judge prompts stay out of `evaluation/observation.jsonl` user rows.

## Box kind

- Job `environment: local | docker | e2b | ssh | daytona`.
- docker / e2b share `environment/Dockerfile` (or an image option). Official base:
  `FROM ageval-attempt:base` (`src/ageval/plugins/contrib/docker/attempt/`). Secrets never baked into layers.
- Coding agents: `executor: acp` + `options.entry`; parent ACP + `host.attach_stdio`.
- `setup.sh` is the last environment slot (`environment_setup`). No provision phase.

## Dockerfile depth (conversion)

| Tier | When | Pattern |
| --- | --- | --- |
| **Thin** | Official base already has engines + ACP entries | `FROM ageval-attempt:base` |
| **Heavy** | Extra apt/pip/lang | Same base **+ migrated `RUN`** at **build** time |

**Forbid as parity default:** runtime `apt-get` / floating `pip install` / `npm i` / `npx`
inside the Attempt after start. Bake deps in the image.

### Official base is not the upstream runtime

The official Attempt image is **CPython 3.12 + baked ACP entries**. It is **not**
the upstream bench’s Python or pinned wheels. If the package Dockerfile `FROM`s this base:

1. **Do not** copy upstream `pip install foo` unpinned.
2. **Pin to what the checkout imports.**
3. **Gate at image build**, not first eval: `python -c "from …"` so a bad pin fails `docker build`.
4. Collection / conftest ImportError is eval ERROR, not FAIL.
5. `host_requires` / `--probe` do not catch eval deps inside the image — those are the package Dockerfile’s job.

### `data/` seed

Put agent-visible files under `tasks/<id>/data/`. The environment phase uploads them to `/attempt/workspace`. Prefer this over baking content into image layers.

### `solution/` (offline fixture)

- Default: **not** seeded to Agent.
- Offline helper flags may copy `solution/*` into workspace — author-level only, not production default.

## Dataset `shared/`

- Import contract: Runtime injects **`[task_dir, dataset_root]`** — **not** the `shared/lib` leaf. Authors write `from shared.lib…`.
- `shared/lib` is for `run.py` / evaluator import only — **not** default Agent mount.
- Gold stays under `tasks/*/evaluation/` only; **forbid** gold / `.env` under `shared/`.
- Task members must **not** own top-level name `shared`.
- docker images: **no** Core implicit COPY of `shared/`. The same `evaluator.py` with `from shared.lib…` can pass on `environment: local` and ImportError on docker unless the Dockerfile `COPY`s `shared/` and puts the **dataset root** on `PYTHONPATH`.

```dockerfile
FROM ageval-attempt:base
COPY shared/ /attempt/shared/
ENV PYTHONPATH=/attempt:/attempt/task:${PYTHONPATH}
```

Do **not** `COPY` `tasks/*/evaluation/` gold into Agent-visible layers.

## Do not

- Rely on “delete field from yaml” as isolation.
- Mount gold into `run.py` “for convenience”.
- Put credentials in the package tree.
- Expect Core to auto-COPY `shared/` into docker images.
- Use runtime package installs as the default parity path.
- Treat `FROM ageval-attempt:base` + unpinned `pip install` as equivalent to the upstream instance image.
