# ageval Dataset Registry service

Standalone HTTP(S) JSON service for **Dataset package** publish/get/list and
**Attempt result** upload/get. **Not** ageval Core. Local path workflows never
require this process.

## Quick start (compose: Postgres + RustFS)

```bash
# from repo root
docker compose -f services/registry/docker-compose.yml up -d

# optional: copy and fill secrets
cp services/registry/.env.example services/registry/.env
# set AGEVAL_GITHUB_CLIENT_ID / AGEVAL_GITHUB_CLIENT_SECRET for ageval login

uv sync --extra registry
# Public start is fail-closed: Postgres + S3 env must be set (see .env.example).
uv run --extra registry python -m services.registry.app --host 127.0.0.1 --port 8700
# stderr prints bootstrap token once — or use ageval login after OAuth is configured
```

Public mode **refuses to start** without `AGEVAL_REGISTRY_DATABASE_URL` and
`AGEVAL_REGISTRY_S3_ENDPOINT`. There is no silent SQLite fallback.

Whole-object publish/upload on the ASGI pipe streams the multipart body to a
spool file (hash/validate from disk, then BlobStore put). JSON bodies stay
small. Proxy `client_max_body_size` must still match `MAX_UPLOAD_BYTES`.

## Zero-dep / tests

```bash
python -m services.registry.app --local --host 127.0.0.1 --port 8700
# or --memory-blob for tests
```

`--local` / `--memory-blob` are the only SQLite paths. They are for
dev and tests, not a public Hub.

## Public deploy (proxy + workers)

Do **not** put the Python port on the public internet. Terminate TLS and
connection limits on nginx or Caddy, then proxy to uvicorn workers.

| Knob | Where | Same number |
| --- | --- | --- |
| Body limit | Proxy `client_max_body_size` / Caddy `request_body.max_size` | Application `MAX_UPLOAD_BYTES` (512 MiB) |
| In-flight uploads | Proxy concurrent-request cap (optional) | `workers × AGEVAL_REGISTRY_UPLOAD_SLOTS` |
| Workers | `--workers` / `AGEVAL_REGISTRY_WORKERS` (default 2 in public mode) | One process per worker; each has its own slot pool |

Schema init (`CREATE` / `ALTER`) is serialized with a Postgres transaction
advisory lock. Without it, two workers racing `ALTER TABLE` take
`AccessExclusiveLock` on different tables and deadlock on startup.

```bash
export AGEVAL_REGISTRY_WORKERS=4
export AGEVAL_REGISTRY_UPLOAD_SLOTS=4
# 4 × 4 = 16 in-flight uploads across the process group
uv run --extra registry python -m services.registry.app --host 127.0.0.1 --port 8700
# or: uvicorn services.registry.asgi:app_factory --factory --host 127.0.0.1 --port 8700 --workers 4
```

Example Caddyfile: [`Caddyfile`](Caddyfile). nginx equivalent:

```nginx
client_max_body_size 512m;
proxy_read_timeout 900s;
proxy_send_timeout 900s;
location / {
    proxy_pass http://127.0.0.1:8700;
}
```

Replace / blob GC under several workers is Postgres-authoritative. Do not run
public mode on SQLite.

## CLI

```bash
export AGEVAL_REGISTRY_URL=http://127.0.0.1:8700

# Interactive (GitHub Device Flow) — writes ~/.ageval/credentials (0600)
uv run ageval login

# CI / bootstrap
export AGEVAL_REGISTRY_TOKEN=<token>

# Orgs (packages must belong to an org; results belong to the uploader)
uv run ageval registry org-create my-lab --display-name "My Lab"
uv run ageval registry org-list
# Reserved official slugs (AGEVAL_OFFICIAL_ORGS, default official): admin only.
# Bootstrap token stays with operators; add owners by GitHub login.
# uv run ageval registry org-create official --display-name Official
# uv run ageval registry org-add-member official alice --role owner
# uv run ageval registry org-set-role official alice --role owner
# uv run ageval registry org-transfer official alice
# uv run ageval registry org-remove-member official alice

uv run ageval publish tests/fixtures/datasets/publish-min --org my-lab
# Same version again conflicts (409) unless explicit replace (org owner):
# uv run ageval publish … --org my-lab --replace
uv run ageval registry list
uv run ageval registry show 'test/publish-min@0.1.0'
uv run ageval registry set-visibility 'test/publish-min@0.1.0' --visibility public
# uv run ageval registry delete 'test/publish-min@0.1.0' --yes
uv run ageval lock 'test/publish-min@0.1.0' --task hello

# After a local run produced .ageval/runs/<run_id>/
uv run ageval results upload <dataset> --run <run_id>
# uv run ageval results upload … --run <run_id> --replace   # owner overwrite
uv run ageval results get <run_id> --out /tmp/restored
uv run ageval results list
uv run ageval results set-visibility <run_id> --kind attempt --visibility public
# Share / unshare a private result (owner only)
uv run ageval results share <run_id> --kind attempt --share-org my-lab
uv run ageval results unshare <run_id> --kind attempt --share-org my-lab
# uv run ageval results delete <run_id> --kind attempt --yes

# After a suite run produced .ageval/suite-runs/<suite_run_id>/summary.json
uv run ageval results upload-suite <dataset> --suite-run <suite_run_id> [--public] [--agent x] [--model y]
# Optional: also pack each task's Attempt tree (Hub can open Job detail)
uv run ageval results upload-suite <dataset> --suite-run <suite_run_id> --with-attempts
# uv run ageval results upload-suite … --suite-run <id> --replace
# Patch one slot (current + previous[]); not whole-row --replace:
# uv run ageval results upload-suite … --suite-run <id> --task <task_id> [--run <run_id>]
uv run ageval results get-suite <suite_run_id> [--out /tmp/restored-suite]
uv run ageval results list-suites [--dataset-id <id>]
# Suite delete keeps attempts by default; optional cascade:
# uv run ageval results delete <suite_run_id> --kind suite --yes
# uv run ageval results delete <suite_run_id> --kind suite --with-attempts --yes
# Local fallback (no registry process):
uv run ageval results list-suites --local <dataset>
uv run ageval results get-suite <suite_run_id> --local <dataset>

# Suite task_refs get has_attempt_content when Attempt blobs exist and are visible.
# Hub Jobs: clickable when true; grey "Not uploaded" otherwise.

uv run ageval cache list
uv run ageval cache purge all --yes
```

## Credentials file

`~/.ageval/credentials` (0600):

```json
{
  "registry": {
    "url": "http://127.0.0.1:8700",
    "token": "…"
  }
}
```

Env overrides: `AGEVAL_REGISTRY_URL`, `AGEVAL_REGISTRY_TOKEN`, optional
`AGEVAL_RESULTS_URL`. Never put tokens in lock/evidence.

## Digests / media types

| Kind | Digest | Media type |
| --- | --- | --- |
| Dataset package | packageDigest + blobDigest | `application/vnd.ageval.dataset.v1.tar+gzip` |
| Plugin package | packageDigest + blobDigest | `application/vnd.ageval.plugin.v1.tar+gzip` |
| Agent package | packageDigest + blobDigest | `application/vnd.ageval.agent.v1.tar+gzip` |
| Attempt result | blobDigest of archive | `application/vnd.ageval.attempt-result.v1.tar+gzip` |
| Suite/job result | blobDigest of suite-run tree | `application/vnd.ageval.suite-result.v1.tar+gzip` |

### CORS (Hub SPA)

Set `AGEVAL_REGISTRY_CORS_ORIGIN` (default `*` when unset) so a browser Hub on
another origin can call `/v1/*` with `Authorization`. Local Hub dev usually
proxies via Vite (`apps/hub`) and does not need CORS.

### Package files API

Browse published package contents **without** downloading the whole tar to the browser:

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/v1/packages/{id}/by-digest/{dig}/files` | same as package get |
| GET | `/v1/packages/{id}/by-digest/{dig}/files/{path}` | same |
| GET | `/v1/packages/{id}/versions/{ver}/files` | resolves to digest |
| GET | `/v1/packages/{id}/versions/{ver}/files/{path}` | resolves to digest |

List/get package meta (`GET /v1/packages`, versions, by-digest) includes
`package_kind` (`dataset` | `plugin` | `agent`, derived from media type). List
accepts optional `?package_kind=dataset|plugin|agent`. Unknown media types are
not classified as dataset.


- List JSON: `{ dataset_id, digest, version, items: [{path, type, size}, …] }`
- File JSON: `{ path, size, encoding: "utf-8"|"base64", content, truncated }`
- **Hard top:** single file default **2 MiB** (`MAX_FILE_BYTES`); larger → **413**
- Path rules: reject `..`, absolute paths, empty segments
- Private unauthorized → **404** (not 403)
- Server indexes tar on first access (process LRU by digest); does not change upload format

### Organizations + ACL

| Surface | Ownership | Private read | Delete / set-visibility / replace |
| --- | --- | --- | --- |
| Package release | **org** (`org_id` required on publish) | org members (or `admin`) | **org owner** (or `admin`) |
| Attempt / suite result | **uploader** (`uploaded_by` server-set) | owner, share→org/user, or `admin` | **uploader** (or `admin`) |

Joining an org does **not** reveal private results until the owner shares them.
Publish may be done by any org **member**; destructive package ops require **owner**.

| Method | Path |
| --- | --- |
| POST/GET | `/v1/orgs` |
| GET | `/v1/orgs/{id}` |
| DELETE | `/v1/orgs/{id}` (dissolve; fails if packages remain) |
| POST | `/v1/orgs/join` body `{ "invite_key" }` |
| POST | `/v1/orgs/{id}/leave` |
| POST | `/v1/orgs/{id}/claim` |
| GET/POST | `/v1/orgs/{id}/members` |
| DELETE | `/v1/orgs/{id}/members/{user}` |
| GET/POST | `/v1/orgs/{id}/invite-keys` (owner; create returns `invite_key` **once**) |
| DELETE | `/v1/orgs/{id}/invite-keys/{key_id}` (revoke) |
| POST | `/v1/packages` (optional metadata `replace: true` → overwrite same version) |
| DELETE | `/v1/packages/{id}/versions/{ver}` (org owner) |
| PATCH | `/v1/packages/{id}/versions/{ver}` body `{ "visibility" }` |
| DELETE | `/v1/results/attempts/{run_id}` (uploader) |
| PATCH | `/v1/results/attempts/{run_id}` body `{ "visibility" }` |
| DELETE | `/v1/results/suites/{id}[?with_attempts=1]` (uploader; cascade optional) |
| PATCH | `/v1/results/suites/{id}` body `{ "visibility" }` |
| POST | `/v1/results/suites/{id}/slots` (uploader; one new Attempt + `previous[]`; not `--replace`) |
| GET/POST/DELETE | `/v1/results/attempts\|suites/{id}/shares` |

**Replace policy:** same `dataset_id@version` / `run_id` / `suite_run_id` defaults
to **409 conflict**. Explicit `replace: true` (CLI `--replace`) deletes the prior
row then inserts: blob, digests, metrics/labels, and visibility from the new
upload. No silent overwrite. Slot append (`POST …/slots` / `upload-suite --task`)
updates current + `previous[]` in place and never deletes old Attempt blobs.

**Blob GC:** meta (+ result shares) deleted first; blob object removed only when
no remaining row references that digest (packages / attempt / suite prefixes
separately).

**Invite keys:** store only `token_hash` + `token_prefix`. Redeem hashes the
submitted key; `max_uses` uses a conditional `UPDATE` so concurrent joins cannot
over-admit. Create returns full `invite_key` once; list/revoke never return it again.

### Attempt file browse

When Attempt archives exist for a suite (e.g. suite upload with `--with-attempts`,
or a later `results upload`), `task_refs[].has_attempt_content` is set only if
the caller may read that attempt. File paths follow the same rules as package
files (no `..`, 2 MiB cap, **413** when larger):

| Method | Path |
| --- | --- |
| GET | `/v1/results/attempts/{run_id}/files` |
| GET | `/v1/results/attempts/{run_id}/files/{path}` |

### Suite results API

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/results/suites` | `results:upload` (+ user identity); optional `replace` |
| GET | `/v1/results/suites` | public ∪ owner ∪ share hit ∪ `admin` |
| GET | `/v1/results/suites/{suite_run_id}` | same visibility rules as attempts |
| DELETE | `/v1/results/suites/{suite_run_id}` | uploader (or `admin`); `?with_attempts=1` cascades owned attempts |
| PATCH | `/v1/results/suites/{suite_run_id}` | uploader (or `admin`); `{ "visibility" }` |
| PATCH | `/v1/results/suites/{suite_run_id}/agent-ref` | uploader (or `admin`); `{ "agent", "role?" }` after `_binding_role_key` match |
| GET | `/v1/results/suites/{suite_run_id}/content` | same |
| GET | `/v1/requests` | Inbox (`?inbox=1`) or suite (`?suite_run_id=`) |
| POST | `/v1/requests` | `{ "kind", "suite_run_id", "agent?" }` |
| POST | `/v1/requests/decide` | `{ "ids", "action": "approve"|"reject" }` |

Public board (`board=1`) is complete + release-bound + `board_listed`. Listing is
not visibility.

### Agent appearances (derived)

Read-only. No Runtime table, no appearance table, and no upload. Source rows
are **public**, **complete**, **release-bound** suites on an official Dataset
**with Agent-org consent** (owner attach or an approved `agent_appearance`
request). Group key is the published Hub id ``org/name`` parsed from
``job_overlay.agent_profiles.*.agent_ref``. ``file:`` / ``local/`` refs and
hand-written ``--profiles`` suites do not attach. ``GET /v1/runtimes`` is gone
(404). Scores are the source suite's observational metrics.

``GET /v1/packages/{org/name}`` includes ``appearances`` for ``package_kind=agent``.
Overlay bytes preview via the existing Agent package files API. Public official
board suite JSON may include ``agent_refs`` (``role``, ``package_id``); other
suites omit it.

Row fields: `dataset_id`, `dataset_version`, `pass_rate`, `mean_score`, `metrics`,
`task_refs`, optional `agent_label` / `model_label`, `exit_code`, and optional
config-comparability projection (`config_fingerprint`, `config_homogeneous`,
`actors_summary`) written at suite-run time — **not** invented at upload.
**No suite-level PASS** is stored or accepted (client keys `pass` / `verdict` / `suite_pass` → 400).
Leaderboard should refuse comparable ranking when `config_homogeneous` is
false; missing fingerprint on legacy rows degrades to labels-only.

Result archives keep layout `.ageval/runs/<run_id>/…` so download extracts into a
browsable tree.

## Scopes

| Scope | Capability |
| --- | --- |
| `registry:publish` | POST /v1/packages; also list/get private packages |
| `read-private` | List/get private package releases |
| `results:upload` | POST /v1/results/attempts only (**not** private read) |
| `results:read` | List/get private attempt results |
| `admin` | All |

`ageval login` issues tokens with publish + read-private + results upload/read.
Scopes are independent: upload-only tokens cannot list private results.
Private unauthorized reads return **404** (not 403).
Visibility is only **`public` | `private`**. Packages require **`org_id`**; private package
read is **org member** (or `admin`). Result private read is owner / share / admin
(see Organizations + ACL above).

## GitHub OAuth

Create a **GitHub OAuth App** (Settings → Developer settings → OAuth Apps).

| Setting | Local Hub / CLI |
| --- | --- |
| Homepage URL | e.g. `http://127.0.0.1:8700/` (informational) |
| Authorization callback URL | **`http://127.0.0.1:5174/login/callback`** (and `http://localhost:5174/login/callback` if you use that host) |
| Enable Device Flow | **On** (required for CLI `ageval login`) |

Put in `services/registry/.env` (gitignored):

- `AGEVAL_GITHUB_CLIENT_ID` / `AGEVAL_GITHUB_CLIENT_SECRET`
- `AGEVAL_GITHUB_LOGIN_ALLOWLIST=yourlogin` (comma-separated; **required** — empty deny)
- optional `AGEVAL_GITHUB_WEB_REDIRECT_URIS=…` for extra Hub callback origins

### CLI — Device Flow

```bash
export AGEVAL_REGISTRY_URL=http://127.0.0.1:8700
uv run ageval login
# Open https://github.com/login/device and enter the printed user code
```

Writes `~/.ageval/credentials` (0600). On success, Registry also stores a **user profile**
snapshot (`login` / display name / avatar) for Hub members list.

### Hub SPA — browser OAuth (Authorization Code)

1. Registry: `POST /v1/auth/github/web/start` with Hub `redirect_uri`
2. Browser opens GitHub authorize → user clicks **Authorize**
3. GitHub redirects to Hub `/login/callback?code=&state=`
4. Hub: `POST /v1/auth/github/web/callback` → Registry API token in `localStorage`

No device user code on Hub. Restart Registry after changing OAuth env.

CI continues to use `AGEVAL_REGISTRY_TOKEN` (bootstrap/admin) without a browser.
