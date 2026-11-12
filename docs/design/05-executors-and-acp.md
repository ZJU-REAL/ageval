# 05 — Agent Executors, ACP Protocol, and Option Tables

Each role in `profiles.yaml` (`agent_profiles.<role>`) independently binds an implementation of the `executor` exclusive slot (for example, `solver` may bind `executor: acp` while `judge` binds `executor: openai-http`). Every executor plugin subclasses `BaseExecutor` (`src/ageval/plugins/base.py`) and is mediated by `ParentAgentService` (`src/ageval/runtime/parent_agent.py`).

---

## 1. `BaseExecutor` Abstract Base Class Contract

```python
class BaseExecutor(ABC):
    kind: str
    requires_environment: bool = True
    supported_apis: frozenset[str]
    supported_model_fields: frozenset[str]
    extra_allowlist: frozenset[str]

    @classmethod
    @abstractmethod
    def supports_model(cls, spec: ModelSpec) -> None: ...

    @abstractmethod
    def bind_model(self, spec: ModelSpec) -> None: ...

    @abstractmethod
    def invoke(
        self,
        prompt: str,
        *,
        timeout: float = 60.0,
        collect_dir: str | None = None,
        redaction_sentinels: tuple[str, ...] | list[str] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
    ) -> AgentResult: ...

    @abstractmethod
    def close(self) -> None: ...

    def open(self, **kwargs: Any) -> None: ...
```

| Attribute / Method | Normative Requirement |
| --- | --- |
| `kind: str` | Unique executor identifier (`"acp"`, `"openai-http"`, `"anthropic-http"`, `"miniswe"`, `"terminus-2"`, `"openhands"`, `"dsh"`, `"nooa"`, `"acp-oneshot"`). |
| `requires_environment: bool` | Defaults to `True`; set to `False` on parent-egress HTTP executors (`openai-http`, `anthropic-http`). |
| `supported_apis` / `supported_model_fields` / `extra_allowlist` | Explicit `frozenset` attributes required on the class body (`frozenset()` rejects all `model.extra` keys). Missing attributes raise `PluginContractError` at import time. |
| `supports_model(cls, spec: ModelSpec)` | Invoked statically on the class during `ageval lock` without instantiation; raises `ModelConfigError` (`kind="model_config"`) on mismatch. |

---

## 2. Coding Agent Access Paths (`acp` vs. `acp-oneshot`)

| Executor | JSON-RPC Client Location | Required Environment Capability | Completion Signal |
| --- | --- | --- | --- |
| `executor: acp` | **Host parent process** (sole ACP JSON-RPC client over `host.attach_stdio`) | `attach_stdio` | ACP `PromptResponse.stopReason` frame |
| `executor: acp-oneshot` | **In-environment** wrapper process + ACP stdio server (`plugins/acp-oneshot`) | `exec` | Wrapper subprocess exit |

### 2.1 `executor: acp` (Parent-Process Client)

```yaml
# profiles.yaml
environment: docker
agent_profiles:
  solver:
    executor: acp
    model:
      id: openai/gpt-4.1-mini
      api: chat
    api_key: ${OPENAI_API_KEY}   # Env var locator; plaintext never enters lock.json
    options:
      entry: pi                  # pi | codex | claude-code | opencode | grok-build
    extensions:
      - plugin: acp
      - plugin: docker
```

The `acp` plugin declares `inject: [service: environment, capabilities: [attach_stdio]]`. Switching coding agent harnesses requires changing only `options.entry`; never write `executor: pi` or `executor: codex`.

### 2.2 `executor: acp-oneshot` (In-Environment Wrapper)
`acp-oneshot` (`plugins/acp-oneshot`) requires only `exec`. Each `invoke` runs a single `host.exec` wrapper inside the environment that spawns the target `entry`'s ACP stdio server, completes `initialize` → `session/new` → `session/prompt`, and exits; `trajectory_collect` maps the recorded events into `ageval.trajectory.event/1`.

### 2.3 Fatal Invoke Propagation

`AgentResult.failure` is the executor-to-parent signal for an invoke that cannot produce a capability verdict. It carries `ModelConfigError` for authentication, quota, bad request/model binding, or another non-retryable 4xx; `TransportStall` for timeouts, rate limits, connection failures, or 5xx responses; and `StallExhausted` when a parent-loop executor has consumed its retry budget. `agent_invoke_failed` is the Core error title derived from that typed failure, so `evaluator.py` never turns an upstream outage into `FAIL`.

Worker-based executors (`openhands`, `dsh`, `nooa`, and `acp-oneshot`) serialize an optional bounded `fatal_invoke: {kind, detail}` object beside their ordinary JSON result. The in-environment worker derives `kind` from provider-native signals: OpenHands conversation-error classification, DSH `turn/end` failure `code`/`status`, ACP request or binding errors, and LiteLLM/OpenAI status codes. The container decoder turns the marker back into a typed `AgentResult.failure`; it never promotes an unknown exception or ordinary task failure into a fatal provider error. The parent `acp` executor creates the same typed failure directly from its session and prompt errors.

---

<a id="executor-placement"></a>

## 3. Executor Placement Matrix (`acp`, `miniswe`, `terminus-2`, `openhands`)

All four harnesses implement the `executor` exclusive slot and reference credentials solely by environment variable name. Neither `terminus-2` nor `openhands` depends on the Harbor CLI on the host machine.

| Dimension | `acp` | `miniswe` | `terminus-2` | `openhands` |
| --- | --- | --- | --- | --- |
| **Model loop location** | ACP entry process inside the Attempt environment; parent is the sole JSON-RPC client | Host parent process | Host parent process | OpenHands SDK worker inside the Attempt environment |
| **Tool execution** | Native tools inside the entry process | Parent dispatches bash commands via `environment.exec` | Parent sends keystrokes and reads pane text via `environment.exec` against in-environment `tmux` | SDK `LocalWorkspace` executing tools in-process inside the Attempt environment |
| **On-demand runtime provisioning** | Runs entry `install_command` during `after_environment_ready` if probe misses | None (uses standard `/bin/bash` in Attempt environment) | Installs `tmux` via environment package manager (`apt-get`, `apk`, `dnf`, `microdnf`, `yum`) if `tmux -V` fails | Installs pinned `openhands-sdk` and `openhands-tools` via in-environment `pip` if import fails |
| **`inject` capabilities** | `attach_stdio` | `exec` | `exec` | `exec`, `upload`, `download` |
| **Trajectory capture** | ACP `session/update` events mapped to `ageval.trajectory.event/1` | `trajectory_collect` from `miniswe` message history | `trajectory_collect` from `tmux` episode steps | Worker writes `openhands.trajectory/1`, mapped to `ageval.trajectory.event/1` during `record` |

---

## 4. Native HTTP Executors, Credential Modes (BYOK / BYOA), and ACP Runtime Probe

1. **`openai-http` and `anthropic-http`**:
   - `openai-http` supports `api: chat` (`/chat/completions`, top-level `reasoning_effort`) and `api: responses` (`/responses`, nested `reasoning.effort` and flat function tool declarations), and never falls back from `responses` to `chat` on error.
   - `openai-http` native streaming is opt-in with `options.stream: true` (default `false`) and applies to both APIs. The non-streaming path keeps one JSON body and is unchanged. Chat consumes `chat.completion.chunk` SSE frames; Responses consumes typed `response.*` events and requires an explicit `response.completed`, `response.incomplete`, or `response.failed` terminal. A Responses stream never interprets Chat chunks or falls back to Chat Completions.
   - Shared framing (`plugins/http_stream.py`) handles incremental UTF-8, split/coalesced frames, CRLF, comments, multi-line `data:` fields, and bounded buffers. Provider assembly lives in `openai_http/stream.py`: Chat merges content and reasoning separately and tool-call id/name/argument fragments by choice/tool index; Responses assembles typed text, reasoning-summary/reasoning-text, and function-argument events, preferring the terminal response `output` when present. A valid tool-only turn is accepted without invented answer text. `[DONE]` alone does not establish an answer.
   - Clock precedence for streaming: the outer invoke timeout/watchdog ceiling is fixed at request start and arriving chunks never extend it; `options.stream_first_event_timeout_seconds` then bounds time to the first SSE data frame, and `options.stream_idle_timeout_seconds` bounds time since the last meaningful text/thought/tool fragment. Comments and heartbeats reset neither the first-event nor the semantic idle clock. Cancellation aborts the reader and closes the local response/socket, including before response headers. The per-read `model.timeout` still bounds a single socket operation.
   - Streaming failure taxonomy: first-event, idle, and outer timeouts are repeatable `TransportStall`; malformed frames, missing terminals, unfinished tool arguments, and `stream_empty_answer` are non-retryable parse `ProtocolError`s; in-stream provider error events and `response.failed` are non-retryable upstream `ProtocolError:stream_upstream_error`; cancellation is `invoke_cancelled`. Provider error details use a bounded allowlist (`type`, `code`, `status_code`, `request_id`, `message`), redacted for credentials and whole URLs: SSE errors under `metadata.stream_error`, HTTP rejections under `metadata.http_error` instead of the raw body. `metadata.error_origin` distinguishes `upstream`, `provider_incomplete`, `parse`, `timeout`, `transport`, `http`, and `cancelled`. `metadata.stream_correlation` carries the exchange id and request/response identifiers (`x-client-request-id`, `x-litellm-call-id`, `x-request-id`); the progress journal records only outcome/origin, counts, and timing, never bodies, messages, URLs, or provider IDs. A length/incomplete ending keeps partial text in `result.text`/events and reports `metadata.stop_reason` with `ok: false`. Streaming completion is never `PASS`.
   - Streaming usage is adopted only when the provider reports it; otherwise it is `unavailable` (`not_reported`, or a partial/lost reason on failure), never zero. Live fragments are appended as redacted `model_turn/delta` activity rows under the running step; exactly one `completed` or `aborted` row seals that step. Incremental activity redaction retains unfinished tokens, credential introductions and explicit sentinel prefixes across SSE frames, timer flushes and output chunks. Safe prefixes are released live; the terminal flush redacts the remaining suffix before writing. Sealed invocation text events use the same incremental redaction context. `backend_raw/stream-progress.jsonl` records counts and monotonic timing only, never fragments or credentials.
   - `anthropic-http` implements `POST /messages` (`api: chat` only), converting OpenAI-shaped `tools` and `messages` into Anthropic `input_schema`, `tool_use`, and `tool_result` blocks, and supports `model.extra.thinking`.
   - Both HTTP executors accept `bind_activity`. Each model call is bracketed in `activity.jsonl` as a `model_turn`. When the caller omits `messages`, the next request is projected from that session's completed turns, skipping history replaced by a `compaction` record.
   - `miniswe` and `terminus-2` log each internal model query as a `model_turn` and each bash or tmux batch as a `tool_call`. A resumed invoke replays those completed steps from the log. `terminus-2` reuses a live tmux session when the environment was reattached, and starts tmux again when the box was rebuilt from a checkpoint.
   - `ageval replay` does not resume that loop and does not call the model. The bound executor's terminal adapter re-executes recorded bash actions through `environment.exec` and stores the new observation. `replay_safe` on a tool call is not permission for that path. An executor without the adapter is `terminal_replay_unsupported`.
   - `acp` writes each `session/update` tool call and assistant chunk into `activity.jsonl` before `session/prompt` returns, and stores the ACP session id on the session record. A resumed invoke loads that native session when the entry supports it, and otherwise continues from the logged transcript. `acp-oneshot`, `openhands`, `dsh`, and `nooa` append the same step lines to `$AGEVAL_STATE_DIR/steps.jsonl` while the worker is still running, or to `/tmp/.ageval-state/steps.jsonl` when that variable is unset. That `host.exec` is registered under the invoke `request_id`, so `probe` stays `busy` for the life of the worker process. `openhands` resumes the conversation id stored under `/attempt/home/openhands`. `dsh` resumes the harness session id stored under `/attempt/home/dsh-sessions` with `session/resume`. `nooa` has no session; a resumed invoke continues from a transcript of the completed `model_turn` and `tool_call` rows. `acp-oneshot` loads its ACP session the same way `acp` does.
   - `trajectory.jsonl` is the whole invoke. When `acp`, `acp-oneshot`, `openhands`, `dsh`, `nooa`, or `terminus-2` builds `AgentResult.events`, completed `model_turn` and `tool_call` rows for that `invoke_request_id` that the fresh buffer skipped are inserted in `seq` order. The fresh buffer's own events stay where they are.
   - **Anthropic Messages SSE:** `options.stream: true` requests native Messages SSE; default `false` preserves JSON delivery. `options.omit_temperature: true` explicitly omits the formerly fixed `temperature: 0` for endpoints requiring their default. First-event and semantic-output idle thresholds are optional positive seconds; the idle clock starts at response headers, pings/comments never reset it, and neither threshold extends the outer invoke/watchdog/task limits. Text/thinking/signatures/redacted blocks and fragmented tool arguments are assembled by index; terminal usage updates replace cumulative counters rather than sum them.
   - While a streaming Anthropic turn is in flight, the executor appends throttled `model_turn/in_flight` snapshots containing cumulative `partial_text`, `partial_thought`, `partial_tool_calls` (block index, id, name and unfinished `partial_json`), and `stream_event_count` under the same model-turn request id. Activity redaction applies to the complete cumulative snapshot. A final snapshot is flushed before sealing, including on cancellation and protocol failure. Each snapshot preserves the original input delta. Existing activity projection takes only completed turns and the latest input delta, so snapshots do not duplicate conversation history. Exactly one completed/aborted record seals the turn. Signatures/redacted thinking are not projected as answer text.
   - Messages SSE requires `message_stop`, closed blocks, a usable answer/tool call and a valid stop reason. Provider errors, truncation, malformed or incomplete streams are failed invocations with retained partial evidence, never successful answers or PASS. Failure usage is explicitly partial. Cancellation shuts down established sockets before or after headers; DNS/TCP/TLS setup can remain bounded by HTTP timeout, with `reader_stopped: false` reported rather than hidden. The transport remains local to `anthropic_http/messages_stream.py` and has no optional-plugin dependency.
2. **BYOK, BYOA (`keyless_auth`), and Loopback rules**:
   - **BYOK**: Projects allowlisted credential environment variables (`credential_env_names` and profile `api_key` locator) into the authorized child environment; missing credentials fail fast during `preflight` or `invoke`.
   - **BYOA (`keyless_auth`)**: Copies allowlisted host subscription files (`keyless_auth_paths` under declared `home_dirs`) into `/attempt/home` without mounting the host `$HOME`.
   - **Loopback exemption**: When `base_url` resolves to `127.0.0.1`, `localhost`, or `::1`, HTTP-based executors (`openai-http`, `anthropic-http`, `dsh`, `nooa`, `miniswe`, `terminus-2`, `openhands`) allow an omitted or empty `api_key`.
3. **ACP runtime configuration and probe (`after_environment_ready`)**:
   - Merges packaged `src/ageval/plugins/contrib/acp/acp_entries.json` with optional `$AGEVAL_HOME/acp-entries.json` (user entries cannot override packaged IDs).
   - Writes secret-free config overlays under `/attempt/home` (`.pi/agent/models.json`, `.config/opencode/opencode.json`, `.codex/config.toml`, `.claude/settings.json`).
   - Runs `node -v` (failing with `acp_runtime_node` if below `runtime.node`), checks `npm ls -g --depth=0` and binary `realpath`, and performs a stdio JSON-RPC `initialize` handshake. On a miss, runs the pinned `install_command` once and re-probes, failing with `acp_runtime_install_failed` or `acp_runtime_missing` if still unsatisfied.

---

## 5. Generated Executor Option Tables

The tables below are generated from each executor's frozen `Options` dataclass and `CLOCKS` by `python3 scripts/gen_param_tables.py` (`--check` enforced in CI):

### openai-http

<!-- ageval:param-table executor=openai-http -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.stream` | false | Opt-in native SSE for api: chat and api: responses. false keeps one JSON body. |
| `options.stream_first_event_timeout_seconds` | unset | Deadline from request start to the first SSE data event. Comments and heartbeats do not satisfy it. Unset disables. |
| `options.stream_idle_timeout_seconds` | unset | Deadline from the last meaningful text/thought/tool fragment. Heartbeats do not reset it. Unset disables. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### anthropic-http

<!-- ageval:param-table executor=anthropic-http -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.max_tokens` | 4096 | Required Messages max_tokens. Positive int. Non-int values are rejected. |
| `options.anthropic_version` | 2023-06-01 | anthropic-version request header. Non-string values are rejected. |
| `options.omit_temperature` | false | Omit temperature for providers requiring their default. |
| `options.stream` | false | Opt-in native Messages SSE; false retains a single JSON response. |
| `options.stream_first_event_timeout_seconds` | unset | First SSE data deadline; None disables. |
| `options.stream_idle_timeout_seconds` | unset | Semantic output idle deadline; pings do not reset it. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### acp

<!-- ageval:param-table executor=acp -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.entry` | *(required)* | ACP entry id. Shipped: codex, claude-code, pi, opencode, grok-build. Missing fails lock with acp_entry_required. |
| `options.idle_timeout_seconds` | unset | Stall ceiling during session/prompt. Any session_update or request_permission resets it. Unset or a non-positive value leaves only the wall-clock invoke timeout. Fires acp_idle_timeout. Non-numeric fails lock with acp_idle_timeout_invalid. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### miniswe

<!-- ageval:param-table executor=miniswe -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.stream` | `true` on `api: chat` | Chat Completions use SSE when true. false sends one JSON body. An omitted key is true, so AGEVAL_MINISWE_CHAT_STREAM=0 does not turn a profile run off. Responses ignores this. |
| `options.step_limit` | 30 | Agent step cap. 0 is unlimited. Negative values are rejected. |
| `options.cost_limit` | 0 | Cost cap. 0 is unlimited. Negative values are rejected. |
| `options.cmd_timeout` | 30 | Seconds per host.exec bash action. Negative values are rejected. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### terminus-2

<!-- ageval:param-table executor=terminus-2 -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.parser` | json | Command batch format: json or xml. Anything else is rejected. |
| `options.step_limit` | 30 | Model turns before the episode stops. 0 is unlimited. |
| `options.cmd_timeout` | 60 | Seconds per environment.exec, including tmux install and pane capture. |
| `options.pane_width` | 160 | tmux pane width in columns. |
| `options.pane_height` | 40 | tmux pane height in rows. |
| `options.max_format_errors` | 3 | Malformed replies returned to the model before the episode stops. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### nooa

<!-- ageval:param-table executor=nooa -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.agent` | *(required)* | Package-local module:Class (subclass nooa.Agent, or a deterministic class). Missing fails lock with nooa_options_agent_required. |
| `options.method` | run | Method invoked on that class. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### dsh

<!-- ageval:param-table executor=dsh -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.composition` | slim | Bundled compositions/<name>.cordis.yml. Path separators and a leading dot are rejected. Setting permission with omit or slim switches to sandboxed. |
| `options.permission` | unset | read-only, workspace-write, or danger-full-access. Omit keeps unrestricted slim tools. Invalid values are rejected. Sets DSH_PERMISSION_MODE. File-tool writes are fenced; bash redirect can still write. |
| `options.max_tokens` | unset | Omit, blank, or null does not pass max_tokens. A positive int is forwarded. A non-positive int, bool, string, or float is rejected. |
| `options.provider` | deepseek-official | Provider id on initialize. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### openhands

<!-- ageval:param-table executor=openhands -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.version` | 1.56.0 | Exact openhands-sdk and openhands-tools version (X.Y.Z). Omit uses the packaged pin. Ranges, blanks, and non-pins are rejected. |
| `options.max_iterations` | 40 | Cap on SDK iterations for one invoke. A non-positive value, bool, or non-integer is rejected. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### acp-oneshot

<!-- ageval:param-table executor=acp-oneshot -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.entry` | *(required)* | ACP entry id (codex, claude-code, pi, opencode, grok-build). Missing or unknown fails materialize. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->
