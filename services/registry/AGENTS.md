# services/registry — layout rules

Standing rule for files added or moved in this package. The structure map is [`ARCHITECTURE.md`](../../ARCHITECTURE.md). Product behavior stays in `docs/design/`. The Hub client stays in `src/ageval/registry/`.

## Call order

```text
http/<aggregate>.py  →  <aggregate>/service.py  →  <aggregate>/store.py  →  <aggregate>/queries.py
```

`app.py` is the composition root: `RegistryState` wires services to stores. `asgi.py` is the process adapter. `db/schema.open_stores` is the only schema init and the only constructor of the five stores (packages, results, shares, orgs, inbox).

A handler calls `state.<service>`. A service receives stores as constructor arguments. A store runs a named statement from its own `queries.py` through `db/sql_adapter.py`.

## Where a file goes

| The code owns | Put it in |
| --- | --- |
| Rows of one aggregate | That aggregate directory |
| HTTP methods for one aggregate | `http/<aggregate>.py`, plus a row in `http/routes.py` |
| Blob bytes | `content/` |
| SQL dialect, connection adapter, schema bootstrap | `db/` |
| Login, GitHub OAuth, API tokens | `auth/` |
| Derived agent performance (no table) | `runtimes/service.py` |
| A read policy that spans aggregates | `access.py` |
| A helper several aggregates already share | Package root (`errors.py`, `dataset.py`, `paging.py`, `clock.py`, `envload.py`, `upload_slots.py`, `spool.py`) |
| Process start, public-vs-local backend, deploy | `app.py`, `asgi.py`, `backend.py`, `Dockerfile`, `docker-compose.yml`, `Caddyfile`, `README.md` |

A new persisted concept joins the aggregate that owns the table, or becomes a new aggregate directory with the same shape. It does not land as a new `services/registry/<name>.py`.

Role directories (`services/`, `stores/` as the package shape) are not this layout. `http/` is the dispatcher plus one module per aggregate.

A persisted aggregate contains:

| File | Owns |
| --- | --- |
| `service.py` | Use cases, `RegistryAppError`, auth decisions |
| `store.py` | Reads and writes for that aggregate's protocol |
| `protocol.py` | That store's protocol. One protocol per aggregate |
| `queries.py` | SQL text: `SCHEMA_STATEMENTS`, `SCHEMA_MIGRATIONS`, `SCHEMA_INTEGER_FLAGS` when the aggregate has integer flags |
| `rows.py` | Row types, and helpers a store must call |
| `dto.py` | Response shapes, when the aggregate has them |
| `__init__.py` | A one-line docstring |

`orgs/users.py` is the user use cases of the org aggregate. `orgs/official.py`, `inbox/maintainers.py`, and the package catalogs (`builtin_agents`, `builtin_plugins`, `brand_marks`) stay beside the aggregate that owns them. A JSON catalog loads with `Path(__file__).with_name(...)` and moves with its module.

## Imports

Import the module that defines the name:

```python
from services.registry.packages.service import PackageService
```

`__init__.py` does not re-export. There is no root `store.py`, `queries.py`, `protocols.py`, or `rows.py`.

| From | May import | Leaves alone |
| --- | --- | --- |
| `http/*` | Its service via `state`, `errors`, dispatch helpers | `*.store`, `db.schema`, `content.blobs`, `state.stores`, `state.meta`, `state.blobs` |
| `<aggregate>/service.py` | Its rows and dto, public functions of another aggregate, package-root helpers | Opening a database, constructing a store |
| `<aggregate>/store.py` | Its `queries`, `protocol`, `rows`; `clock`; another aggregate's row helper | Another store, any service, `http` |
| `db/schema.py` | Each aggregate's `queries` and `store` | Business decisions |
| `db/sql_adapter.py` | Dialect only | Aggregate `CREATE TABLE` text |

A helper that a store calls lives on `rows.py` or on a package-root helper such as `clock`. It does not live on `service.py`: the service imports the store, so the store cannot import the service. `normalize_user_id` stays on `orgs/rows.py` for that reason.

Cross-aggregate work uses a public function on the owning module, or a store instance `RegistryState` passed in. A private `_name` on a sibling service is not an interface.

When a name moves, retarget every importer in the same change and delete the old module. Fix `Path(__file__).parents` in that change. Do not add a second search path, a re-export, or a compatibility alias.

## SQL

Statement text lives in the aggregate `queries.py`. The store calls `self._adapter.execute(conn, Q.<NAME>, params)`. `db/schema.init_schema` concatenates each aggregate's `SCHEMA_STATEMENTS`, `SCHEMA_MIGRATIONS`, and `SCHEMA_INTEGER_FLAGS`. A new flag list is added to the aggregate and to that concatenation together.

`api_tokens` is the exception: its DDL and writes stay in `auth/tokens.py` (`PersistentTokenStore`). Aggregate schema init does not create that table.

`CREATE TABLE IF NOT EXISTS releases` appears once, in `packages/queries.py`. Sqlite and Postgres stay behind `db/sql_adapter.py` and `db/dialect.py`.

Snapshot-share rows belong to `shares/`. `results/` does not read or write them. `RequestService.apply` asks the shares store before kind and auth.

## HTTP shape

`http/dispatch.py` holds `RegistryHttpApi.dispatch`, `_bearer`, `_caught`, `write_http_result`, and the body readers. `_bearer(` appears only there.

Each `http/<aggregate>.py` is one mixin of handler methods. `RegistryHttpApi` subclasses those mixins. Dispatch resolves `getattr(self, f"_{route.name}")`, so the route name and the method stay paired. Inbox routes live in `http/requests.py` (`InboxHandlers`) because the route family is `/v1/requests`.

Handler mixins import `HttpResult`, `_caught`, and `json_result` from `dispatch`. Those imports in `dispatch.py` stay below the helper definitions.

These classes stay whole: `PackageService`, `ResultService`, `ShareService`, `OrgService`, `RequestService`, `AuthService`, `UserService`, `RuntimeService`.

## Leave in place

- `python -m services.registry.app` and the ASGI entry.
- Deploy files at this directory. `envload.py` stays beside `.env`.
- `app.py` stays here so `_REPO = Path(__file__).resolve().parents[2]` is the repo root.
- `src/ageval/registry/` (the Hub client).
- `docs/design/` on a layout-only change.

A layout change does not add a repository framework, a god store protocol, a mock store, or a second dispatcher.

## Checks

`tests/architecture/test_attempt_seams.py` pins this layout:

- `test_handler_methods_do_not_touch_store` scans `app.py` `Handler` and every `http/*.py` except `__init__.py` and `routes.py`.
- `test_bearer_is_only_used_by_dispatch`
- `test_store_has_no_sql_literals` scans every `store.py` under this package. The expected set is the five aggregate stores.
- `test_queries_own_single_releases_ddl` requires `packages/queries.py` and rejects a root `queries.py`.

```bash
uv sync --frozen --extra registry
uv run pytest tests/registry tests/architecture/test_attempt_seams.py -q
```
