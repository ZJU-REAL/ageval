"""Regressions for the eight failures that already shipped once.

Each case is the fixed behavior. The commit named in the docstring is the
one that made that case pass; its parent fails the case. This file does not
read git history (CI checks out a single commit).

1. ``timeout`` 0 is rejected. ``invoke_timeout`` 0 still falls back to 300.
   Fixed in cbc601d7 and 46e22626.
2. ``ProtocolError`` kind ``bad_json`` is not retried. Fixed in 00412bfc.
3 and 4. After an idle timeout, usage lives on metadata, the record phase
   copies it onto the terminal row, then slim deletes metadata. Fixed in
   6d0765b0.
5. A hosted worker reads ``suite_run_id`` from the result file when stdout
   is not JSON. Fixed in 5f1a7f29 and 00412bfc.
6. A codex overlay writes ``base_url`` from a locator. Fixed in 00412bfc.
7. Lock rejects an option typo and names the field. Fixed in 58cfc58c.
8. Lock rejects a nooa ``model.extra`` key that is not allowlisted.
   Fixed in fc373fc2.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.attempt.test_eval_seal_phases import _ctx
from tests.helpers.lock import CONFIG_MIN, job_document, lock_task, lock_with_profiles

from ageval.config.errors import ConfigError
from ageval.evidence.invariants import usage_document_ok
from ageval.model.errors import ModelConfigError, ProtocolError
from ageval.plugins.bootstrap import ensure_bootstrapped
from ageval.plugins.contrib.acp.lock_overlay import overlays_for_entry
from ageval.plugins.defaults import register_defaults
from ageval.plugins.protocol import BindingIntent, InjectRequirement
from ageval.plugins.resolve import resolve
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR
from ageval.runtime.clocks import ClockError, parse_clock
from ageval.runtime.parent_agent import _result_repeatable

_ROOT = Path(__file__).resolve().parents[2]
_NOOA_SRC = _ROOT / "plugins" / "nooa" / "src"
if str(_NOOA_SRC) not in sys.path:
    sys.path.insert(0, str(_NOOA_SRC))

from nooa_plugin.factory import NooaExecutorSPI  # noqa: E402
from services.registry.hosted.prepare import PreparedRun  # noqa: E402
from services.registry.hosted.worker import AgevalCliRunner  # noqa: E402

from ageval.attempt.phases import record  # noqa: E402


def test_timeout_zero_is_rejected_and_invoke_timeout_still_falls_back() -> None:
    with pytest.raises(ClockError):
        parse_clock("timeout", 0)
    assert parse_clock("invoke_timeout", 0) == 300.0


def test_bad_json_is_not_retried() -> None:
    failure = ProtocolError("bad", kind="bad_json")
    assert _result_repeatable(SimpleNamespace(ok=False, failure=failure)) is False


def _job(*, entry: str, model: str, api_key: str, base_url: str) -> dict[str, object]:
    return {
        "agent_profiles": {
            "solver": {
                "executor": "acp",
                "model": {"id": model},
                "api_key": api_key,
                "base_url": base_url,
                "options": {"entry": entry},
                "extensions": [{"plugin": "acp"}, {"plugin": "docker"}],
            }
        }
    }


def test_codex_overlay_writes_locator_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("litellm_base_url", "https://gateway.example/v1")
    files = overlays_for_entry(
        "codex",
        _job(
            entry="codex",
            model="litellm/glm-5.3",
            api_key="OPENAI_API_KEY",
            base_url="litellm_base_url",
        ),
    )
    text = next(item.payload for item in files if item.dest == ".codex/config.toml")
    assert isinstance(text, str)
    assert 'base_url = "https://gateway.example/v1"' in text


def test_lock_rejects_an_option_typo() -> None:
    job = job_document(
        {
            "solver": {
                "executor": "acp",
                "model": {"id": "entry-default"},
                "options": {"entry": "pi", "idle_timeout_secnds": 30},
                "extensions": [{"plugin": "acp"}, {"plugin": "local"}],
            }
        }
    )
    with pytest.raises(ConfigError, match="idle_timeout_secnds") as raised:
        lock_task(CONFIG_MIN, "minimal", job=job)
    assert "idle_timeout_seconds" in str(raised.value)


def test_lock_rejects_unknown_nooa_model_extra(tmp_path: Path) -> None:
    reg = ensure_bootstrapped()
    saved = reg._injects.get("nooa")
    reg.exclusive(
        EXECUTOR, "nooa", NooaExecutorSPI, priority=110, source="installed", is_factory=True
    )
    reg.declare_inject(
        "nooa",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("exec", "upload")),),
    )
    task = tmp_path / "t"
    task.mkdir()
    (task / "task.yaml").write_text(
        "format: ageval.task/1\ntask_id: t\nagent_profiles:\n  - id: solver\n",
        encoding="utf-8",
    )
    (task / "run.py").write_text("async def run(ctx): pass\n", encoding="utf-8")
    (task / "evaluator.py").write_text("def evaluate(i): return {}\n", encoding="utf-8")
    try:
        with pytest.raises(ModelConfigError, match="model_extra_rejected:temperature"):
            lock_with_profiles(
                task,
                "t",
                {
                    "solver": {
                        "executor": "nooa",
                        "model": {"id": "openai/gpt-4.1-mini", "extra": {"temperature": 1}},
                        "options": {"agent": "lib.agents:FixedAnswerAgent"},
                    }
                },
            )
    finally:
        if saved is None:
            reg._injects.pop("nooa", None)
        else:
            reg._injects["nooa"] = saved


class _Proc:
    def __init__(self, stdout: str) -> None:
        self.returncode: int | None = None
        self._stdout = stdout

    def poll(self) -> int:
        return 0

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        del timeout
        self.returncode = 0
        return self._stdout, ""


def test_hosted_worker_reads_suite_id_when_stdout_is_noisy(tmp_path: Path) -> None:
    work = tmp_path / "work"
    dataset = tmp_path / "dataset"
    work.mkdir()
    dataset.mkdir()
    profiles = work / "profiles.yaml"
    profiles.write_text("format: ageval.profiles/1\n", encoding="utf-8")
    prepared = PreparedRun(
        work_dir=work,
        dataset_root=dataset,
        profiles_path=profiles,
        environment="e2b",
        model_locator="OPENAI_API_KEY",
        model_value="not-in-the-profiles-file",
        provider_locator="E2B_API_KEY",
        provider_value="also-not-in-the-profiles-file",
        max_concurrent_tasks=1,
        task_id="hello",
    )

    def popen(argv: list[str], **kwargs: object) -> _Proc:
        del kwargs
        path = Path(argv[argv.index("--result-file") + 1])
        path.write_text('{"suite_run_id":"from-file"}\n', encoding="utf-8")
        return _Proc("log line\n{not json\n")

    result = AgevalCliRunner(popen=popen).run(prepared, should_cancel=lambda: False)
    assert result.suite_run_id == "from-file"


@pytest.mark.asyncio
async def test_idle_timeout_usage_survives_slim(tmp_path: Path) -> None:
    registry = ensure_bootstrapped()
    register_defaults(registry)
    graph = resolve(BindingIntent(profile_id="solver"), registry)
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    inv = ctx.evidence.root / "agent" / "invocations" / "001"
    inv.mkdir(parents=True)
    (inv / "metadata.json").write_text(
        json.dumps(
            {
                "seq": 1,
                "status": "timeout",
                "error": "acp_idle_timeout",
                "latency_ms": 12,
                "profile_id": "solver",
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            }
        ),
        encoding="utf-8",
    )
    (inv / "request.json").write_text('{"messages":[{"content":"go"}]}', encoding="utf-8")
    (inv / "events.jsonl").write_text("", encoding="utf-8")
    await record.run(ctx)
    assert not (inv / "metadata.json").exists()
    last = json.loads((ctx.evidence.root / "trajectory.jsonl").read_text().splitlines()[-1])
    assert last["type"] == "terminal"
    assert last["error"] == "acp_idle_timeout"
    assert usage_document_ok(last["usage"])
    assert last["usage"]["prompt_tokens"] == 4
    assert last["usage"]["completion_tokens"] == 2
