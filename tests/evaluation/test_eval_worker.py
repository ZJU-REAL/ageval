"""Parent evaluator worker: same Agent Service socket as run.py."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.evaluation.package_evaluator import evaluate_in_box
from ageval.evidence.store import AttemptEvidenceStore
from ageval.runtime.eval_worker import _published
from ageval.runtime.task_launch import _eval_gold_dir, _eval_workspace


def test_published_includes_file_stems_and_tree_dirs(tmp_path: Path) -> None:
    (tmp_path / "reply.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "a.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / "evaluation.json").write_text("{}\n", encoding="utf-8")
    found = _published(tmp_path)
    assert found["reply"].endswith("reply.json")
    assert found["repo"].endswith("repo")
    assert "evaluation" not in found


def test_eval_workspace_prefers_scoring_host_bind_mount(tmp_path: Path) -> None:
    mapped = tmp_path / "box" / "workspace"
    mapped.mkdir(parents=True)
    host = SimpleNamespace(
        host_path=lambda dest: mapped if dest.endswith("workspace") else tmp_path
    )
    ctx = SimpleNamespace(scoring_host=host, host=SimpleNamespace())
    assert _eval_workspace(ctx) == mapped


def test_eval_gold_dir_reads_parent_evaluation_src(tmp_path: Path) -> None:
    gold = tmp_path / "evaluation"
    gold.mkdir()
    ctx = SimpleNamespace(evaluation_src=gold, scoring_host=SimpleNamespace(), evidence=None)
    assert _eval_gold_dir(ctx) == gold


def test_eval_gold_dir_named_map_does_not_mkdir_on_agent(tmp_path: Path) -> None:
    agent_eval = tmp_path / "agent" / "evaluation"
    host = SimpleNamespace(
        host_path=lambda dest: agent_eval if str(dest).endswith("evaluation") else tmp_path
    )
    evidence = SimpleNamespace(path=lambda rel: tmp_path / "run" / rel)
    ctx = SimpleNamespace(
        evaluation_src=None,
        scoring_host=host,
        host=host,
        evidence=evidence,
        lock=SimpleNamespace(
            resolved_references={
                "evaluation_environments": {
                    "audit": {"dockerfile": "environment/evaluate/audit/Dockerfile"}
                }
            }
        ),
    )
    gold = _eval_gold_dir(ctx)
    assert gold == tmp_path / "run" / "evaluation"
    assert gold.is_dir()
    assert not agent_eval.exists()


def test_eval_workspace_named_map_does_not_use_agent_bind_mount(tmp_path: Path) -> None:
    agent_ws = tmp_path / "agent" / "workspace"
    agent_ws.mkdir(parents=True)
    staged = tmp_path / "run" / "task-artifacts"
    snap = staged / "repo"
    snap.mkdir(parents=True)
    (snap / "src.py").write_text("from snapshot\n", encoding="utf-8")
    host = SimpleNamespace(host_path=lambda dest: agent_ws)
    evidence = SimpleNamespace(path=lambda rel: tmp_path / "run" / rel)
    ctx = SimpleNamespace(
        scoring_host=host,
        host=host,
        evidence=evidence,
        lock=SimpleNamespace(
            resolved_references={
                "evaluation_environments": {
                    "audit": {"dockerfile": "environment/evaluate/audit/Dockerfile"}
                },
                "artifacts": [{"id": "repo", "path": "workspace", "kind": "tree"}],
                "evaluation_inputs": [{"artifact": "repo", "target": "workspace"}],
            }
        ),
    )
    assert _eval_workspace(ctx) == snap


@pytest.mark.asyncio
async def test_evaluate_in_box_runs_parent_worker(tmp_path: Path) -> None:
    task = tmp_path / "task"
    task.mkdir()
    (task / "evaluator.py").write_text(
        "def evaluate(inputs):\n"
        "    return {'status': 'PASS', 'score': 1.0, 'metrics': {'via': 'parent'}}\n",
        encoding="utf-8",
    )
    evidence = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    host = SimpleNamespace(host_path=lambda dest: workspace)

    class Lock:
        resolved_references = {
            "evaluation_entrypoint": "evaluator:evaluate",
            "evaluation_inputs": [],
        }
        parameters = {}

    ctx = SimpleNamespace(
        lock=Lock(),
        task_root=task,
        dataset_root=tmp_path,
        attempt_id="a",
        trial_id="t",
        run_id="r",
        evidence=evidence,
        scoring_host=host,
        host=host,
        evaluation_src=None,
        agent_service=None,
        remaining_seconds=lambda: 30.0,
        record_fact=lambda *_a, **_k: None,
    )
    verdict = await evaluate_in_box(ctx)
    assert verdict["status"] == "PASS"
    assert verdict["metrics"]["via"] == "parent"
    assert not (tmp_path / "run" / "evaluation" / "checks.json").exists()


@pytest.mark.asyncio
async def test_evaluate_in_box_persists_opt_in_checks(tmp_path: Path) -> None:
    task = tmp_path / "task"
    task.mkdir()
    (task / "evaluator.py").write_text(
        "def evaluate(inputs):\n"
        "    return {\n"
        "        'status': 'PASS',\n"
        "        'score': 1.0,\n"
        "        'checks': [\n"
        "            {'id': 'audit', 'status': 'FAIL', 'score': 0.0},\n"
        "            {'id': 'files', 'status': 'PASS', 'score': 1.0},\n"
        "        ],\n"
        "    }\n",
        encoding="utf-8",
    )
    evidence = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    host = SimpleNamespace(host_path=lambda dest: workspace)

    class Lock:
        resolved_references = {
            "evaluation_entrypoint": "evaluator:evaluate",
            "evaluation_inputs": [],
        }
        parameters = {}

    ctx = SimpleNamespace(
        lock=Lock(),
        task_root=task,
        dataset_root=tmp_path,
        attempt_id="a",
        trial_id="t",
        run_id="r",
        evidence=evidence,
        scoring_host=host,
        host=host,
        evaluation_src=None,
        agent_service=None,
        remaining_seconds=lambda: 30.0,
        record_fact=lambda *_a, **_k: None,
    )
    verdict = await evaluate_in_box(ctx)
    assert verdict["status"] == "PASS"
    path = tmp_path / "run" / "evaluation" / "checks.json"
    assert path.is_file()
    body = json.loads(path.read_text(encoding="utf-8"))
    assert [row["id"] for row in body["checks"]] == ["audit", "files"]
    assert body["checks"][0]["status"] == "FAIL"


class _ExecHost:
    def __init__(self, stdout: str = "ok-from-box\n") -> None:
        self.kind = "docker"
        self.started = False
        self.uploads: list[tuple[Path, str]] = []
        self.execs: list[list[str]] = []
        self._stdout = stdout

    async def preflight(self) -> None:
        return None

    async def start(self, *, force_build: bool = False) -> None:
        del force_build
        self.started = True

    async def upload(self, source: Path, dest: str) -> None:
        self.uploads.append((Path(source), dest))

    async def exec(self, command, **kwargs):
        del kwargs
        self.execs.append([str(part) for part in command])
        from ageval.environments.protocol import ExecResult

        return ExecResult(exit_code=0, stdout=self._stdout)


@pytest.mark.asyncio
async def test_evaluate_in_box_execs_named_host(tmp_path: Path) -> None:
    from ageval.attempt.ctx import AttemptCtx
    from ageval.plugins.defaults import register_defaults
    from ageval.plugins.protocol import BindingIntent, ExplicitBinding
    from ageval.plugins.registry import ExtensionRegistry
    from ageval.plugins.resolve import resolve
    from ageval.plugins.services import ServiceTable
    from ageval.plugins.slots import EVALUATION_RUNTIME
    from ageval.runtime.cancellation import CancellationSignal

    task = tmp_path / "task"
    task.mkdir()
    (task / "evaluator.py").write_text(
        "async def evaluate(inputs):\n"
        "    scoring = inputs['scoring']\n"
        "    result = await scoring.exec('audit', ['echo', 'ok'])\n"
        "    return {\n"
        "        'status': 'PASS' if result.exit_code == 0 else 'FAIL',\n"
        "        'score': 1.0 if result.ok else 0.0,\n"
        "        'metrics': {'stdout': result.stdout.strip()},\n"
        "    }\n",
        encoding="utf-8",
    )
    gold = tmp_path / "evaluation"
    gold.mkdir()
    (gold / "hidden.txt").write_text("secret\n", encoding="utf-8")
    evidence = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    audit = _ExecHost()
    unused = _ExecHost(stdout="should-not-run\n")
    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(
        BindingIntent(
            profile_id="solver",
            extensions=[ExplicitBinding(slot=EVALUATION_RUNTIME, plugin="default")],
        ),
        registry,
    )
    lock = SimpleNamespace(
        force_build=False,
        resolved_references={
            "evaluation_entrypoint": "evaluator:evaluate",
            "evaluation_inputs": [],
            "evaluation_environments": {
                "audit": {"dockerfile": "environment/evaluate/audit/Dockerfile"},
                "unused": {"dockerfile": "environment/evaluate/unused/Dockerfile"},
            },
        },
        parameters={},
        limits={"wall_time_seconds": 30},
    )
    ctx = AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=lock,  # type: ignore[arg-type]
        profile_id="solver",
        bindings=graph,
        registry=registry,
        services=ServiceTable(),
        host=_ExecHost(),  # type: ignore[arg-type]
        evidence=evidence,
        cancellation=CancellationSignal(),
        task_root=task,
        dataset_root=tmp_path,
        evaluate_hosts={"audit": audit, "unused": unused},  # type: ignore[arg-type]
        evaluation_src=gold,
    )
    ctx.mark_writers_stopped()
    ctx.phase = "evaluate"
    verdict = await evaluate_in_box(ctx)
    assert verdict["status"] == "PASS"
    assert verdict["metrics"]["stdout"] == "ok-from-box"
    assert audit.started is True
    assert unused.started is False
    assert audit.execs == [["echo", "ok"]]
    assert not (tmp_path / "run" / "evaluation" / "checks.json").exists()


@pytest.mark.asyncio
async def test_evaluate_in_box_unknown_exec_name_fails_closed(tmp_path: Path) -> None:
    from ageval.attempt.ctx import AttemptCtx
    from ageval.plugins.defaults import register_defaults
    from ageval.plugins.protocol import BindingIntent, ExplicitBinding
    from ageval.plugins.registry import ExtensionRegistry
    from ageval.plugins.resolve import resolve
    from ageval.plugins.services import ServiceTable
    from ageval.plugins.slots import EVALUATION_RUNTIME
    from ageval.runtime.cancellation import CancellationSignal

    task = tmp_path / "task"
    task.mkdir()
    (task / "evaluator.py").write_text(
        "async def evaluate(inputs):\n"
        "    await inputs['scoring'].exec('nope', ['echo', 'ok'])\n"
        "    return {'status': 'PASS', 'score': 1.0}\n",
        encoding="utf-8",
    )
    evidence = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    audit = _ExecHost()
    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(
        BindingIntent(
            profile_id="solver",
            extensions=[ExplicitBinding(slot=EVALUATION_RUNTIME, plugin="default")],
        ),
        registry,
    )
    lock = SimpleNamespace(
        force_build=False,
        resolved_references={
            "evaluation_entrypoint": "evaluator:evaluate",
            "evaluation_inputs": [],
            "evaluation_environments": {
                "audit": {"dockerfile": "environment/evaluate/audit/Dockerfile"},
            },
        },
        parameters={},
        limits={"wall_time_seconds": 30},
    )
    ctx = AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=lock,  # type: ignore[arg-type]
        profile_id="solver",
        bindings=graph,
        registry=registry,
        services=ServiceTable(),
        host=_ExecHost(),  # type: ignore[arg-type]
        evidence=evidence,
        cancellation=CancellationSignal(),
        task_root=task,
        dataset_root=tmp_path,
        evaluate_hosts={"audit": audit},  # type: ignore[arg-type]
    )
    ctx.mark_writers_stopped()
    ctx.phase = "evaluate"
    with pytest.raises(RuntimeError, match="unknown_evaluate_environment"):
        await evaluate_in_box(ctx)
    assert audit.started is False


@pytest.mark.asyncio
async def test_evaluate_in_box_exec_without_named_map_uses_scoring_host(tmp_path: Path) -> None:
    from ageval.attempt.ctx import AttemptCtx
    from ageval.plugins.defaults import register_defaults
    from ageval.plugins.protocol import BindingIntent, ExplicitBinding
    from ageval.plugins.registry import ExtensionRegistry
    from ageval.plugins.resolve import resolve
    from ageval.plugins.services import ServiceTable
    from ageval.plugins.slots import EVALUATION_RUNTIME
    from ageval.runtime.cancellation import CancellationSignal

    task = tmp_path / "task"
    task.mkdir()
    (task / "evaluator.py").write_text(
        "async def evaluate(inputs):\n"
        "    result = await inputs['scoring'].exec('verifier', ['echo', 'ok'])\n"
        "    return {\n"
        "        'status': 'PASS' if result.exit_code == 0 else 'FAIL',\n"
        "        'score': 1.0 if result.ok else 0.0,\n"
        "        'metrics': {'stdout': result.stdout.strip()},\n"
        "    }\n",
        encoding="utf-8",
    )
    evidence = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    singular = _ExecHost()
    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(
        BindingIntent(
            profile_id="solver",
            extensions=[ExplicitBinding(slot=EVALUATION_RUNTIME, plugin="default")],
        ),
        registry,
    )
    lock = SimpleNamespace(
        force_build=False,
        resolved_references={
            "evaluation_entrypoint": "evaluator:evaluate",
            "evaluation_inputs": [],
        },
        parameters={},
        limits={"wall_time_seconds": 30},
    )
    ctx = AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=lock,  # type: ignore[arg-type]
        profile_id="solver",
        bindings=graph,
        registry=registry,
        services=ServiceTable(),
        host=_ExecHost(),  # type: ignore[arg-type]
        evidence=evidence,
        cancellation=CancellationSignal(),
        task_root=task,
        dataset_root=tmp_path,
        evaluate_host=singular,  # type: ignore[arg-type]
    )
    ctx.mark_writers_stopped()
    ctx.phase = "evaluate"
    verdict = await evaluate_in_box(ctx)
    assert verdict["status"] == "PASS"
    assert verdict["metrics"]["stdout"] == "ok-from-box"
    assert singular.started is False
    assert singular.execs == [["echo", "ok"]]
