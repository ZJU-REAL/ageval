"""Lock / materialize / import path for plugin_requires."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ageval.config.errors import ConfigError
from ageval.plugins.install import install_from_local
from ageval.plugins.store import install_from_path, uninstall

ROOT = Path(__file__).resolve().parents[2]
PROBE_DB = ROOT / "tests/fixtures/datasets/probe-min"
HOST_PROBE = ROOT / "tests/fixtures/plugins/host-probe"


def _write_plugin(
    root: Path,
    plugin_id: str,
    *,
    requires: list[str] | None = None,
    module: str = "demo",
    extra_py: str = "",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    rows = ""
    if requires:
        req_yaml = "\n".join(f"  - plugin_id: {pid}" for pid in requires)
        rows = f"plugin_requires:\n{req_yaml}\n"
    (root / "plugin.yaml").write_text(
        (
            "format: ageval.plugin/1\n"
            f"plugin_id: {plugin_id}\n"
            "version: 0.1.0\n"
            f"{rows}"
            "slots:\n"
            "  chain:\n"
            "    - id: after_environment_ready\n"
            "      priority: 120\n"
            f"      entry: {module}.hooks:build\n"
        ),
        encoding="utf-8",
    )
    src = root / "src" / module
    src.mkdir(parents=True)
    (src / "__init__.py").write_text('VALUE = "ok"\n', encoding="utf-8")
    (src / "hooks.py").write_text(
        extra_py + "def build(**_k):\n"
        "    async def h(ctx, value, nxt):\n"
        "        return await nxt(value)\n"
        "    return h\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def ageval_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ageval-home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    from ageval.plugins import bootstrap as boot
    from ageval.plugins.registry import reset_global_registry

    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()
    install_from_path(HOST_PROBE)
    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()
    return home


def _profiles(tmp: Path, extra_plugin: str) -> Path:
    path = tmp / "profiles.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "format": "ageval.profiles/1",
                "agent_profiles": {
                    "solver": {
                        "executor": "host-probe",
                        "extensions": [
                            {"plugin": "host-probe"},
                            {"plugin": extra_plugin},
                        ],
                        "model": {"id": "none"},
                        "api_key": "${PROBE_API_KEY}",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_lock_fails_when_required_plugin_missing(
    ageval_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del ageval_home
    monkeypatch.setenv("PROBE_API_KEY", "x")
    plugins = tmp_path / "plugins"
    _write_plugin(plugins / "needs-neighbor", "needs-neighbor", requires=["neighbor"])
    install_from_path(plugins / "needs-neighbor")
    from ageval.application.composition import build_lock_command

    with pytest.raises(ConfigError) as ei:
        build_lock_command().run(
            dataset_root=PROBE_DB,
            task_id="l0-task",
            profiles_path=_profiles(tmp_path, "needs-neighbor"),
        )
    assert ei.value.error_code == "plugin_requires_unsatisfied"


def test_lock_ok_when_required_plugin_installed(
    ageval_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del ageval_home
    monkeypatch.setenv("PROBE_API_KEY", "x")
    plugins = tmp_path / "plugins"
    _write_plugin(plugins / "neighbor", "neighbor")
    _write_plugin(plugins / "needs-neighbor", "needs-neighbor", requires=["neighbor"])
    install_from_local(plugins / "needs-neighbor")
    from ageval.application.composition import build_lock_command

    summary = build_lock_command().run(
        dataset_root=PROBE_DB,
        task_id="l0-task",
        profiles_path=_profiles(tmp_path, "needs-neighbor"),
    )
    chain = (
        summary["extension_bindings"]["solver"]["slots"].get("after_environment_ready") or {}
    ).get("chain") or []
    plugins_in_chain = {item.get("plugin") for item in chain}
    assert "needs-neighbor" in plugins_in_chain


def test_materialize_can_import_required_module(ageval_home: Path, tmp_path: Path) -> None:
    del ageval_home
    plugins = tmp_path / "plugins"
    _write_plugin(plugins / "neighbor", "neighbor", module="neighbor_mod")
    _write_plugin(
        plugins / "needs-neighbor",
        "needs-neighbor",
        requires=["neighbor"],
        module="needs_neighbor",
        extra_py="from neighbor_mod import VALUE\nassert VALUE == 'ok'\n",
    )
    install_from_local(plugins / "needs-neighbor")
    from ageval.plugins import bootstrap as boot
    from ageval.plugins.registry import reset_global_registry

    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()
    from ageval.plugins.bootstrap import ensure_bootstrapped

    ensure_bootstrapped()
    import neighbor_mod  # type: ignore[import-not-found]

    assert neighbor_mod.VALUE == "ok"


def test_uninstall_depender_lock_still_works_with_dep(
    ageval_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del ageval_home
    monkeypatch.setenv("PROBE_API_KEY", "x")
    plugins = tmp_path / "plugins"
    _write_plugin(plugins / "neighbor", "neighbor")
    _write_plugin(plugins / "needs-neighbor", "needs-neighbor", requires=["neighbor"])
    install_from_local(plugins / "needs-neighbor")
    assert uninstall("needs-neighbor") is True
    from ageval.application.composition import build_lock_command

    summary = build_lock_command().run(
        dataset_root=PROBE_DB,
        task_id="l0-task",
    )
    assert summary["task_id"] == "l0-task"
