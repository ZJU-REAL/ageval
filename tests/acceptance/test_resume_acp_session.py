"""Kill an ACP prompt and resume it through the public CLI."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_SERVER = """\
#!{python}
import json
import sys
import time
from pathlib import Path

TRACE = Path({trace!r})
PHASE = Path({phase!r})
SESSION = "native-1"


def send(payload):
    sys.stdout.buffer.write((json.dumps(payload) + "\\n").encode())
    sys.stdout.buffer.flush()


def note(method):
    with TRACE.open("a", encoding="utf-8") as handle:
        handle.write(method + "\\n")


def tool_updates(session_id):
    base = {{"jsonrpc": "2.0", "method": "session/update"}}
    send({{
        **base,
        "params": {{
            "sessionId": session_id,
            "update": {{
                "sessionUpdate": "tool_call",
                "toolCallId": "call_1",
                "title": "read",
                "kind": "read",
                "status": "pending",
                "rawInput": {{"path": "note.txt"}},
            }},
        }},
    }})
    send({{
        **base,
        "params": {{
            "sessionId": session_id,
            "update": {{
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call_1",
                "title": "read",
                "kind": "read",
                "status": "completed",
                "rawOutput": "kept\\n",
            }},
        }},
    }})


def main():
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return
        try:
            msg = json.loads(line.decode())
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {{}}
        if isinstance(method, str):
            note(method)
        if method == "initialize" and msg_id is not None:
            send({{
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {{
                    "protocolVersion": 1,
                    "agentCapabilities": {{"loadSession": True}},
                    "agentInfo": {{"name": "scripted-acp", "version": "1.0.0"}},
                }},
            }})
            continue
        if method == "session/new" and msg_id is not None:
            cwd = Path(str(params.get("cwd") or "."))
            target = cwd / "note.txt"
            if target.exists():
                target.write_text(target.read_text(encoding="utf-8") + "again\\n", encoding="utf-8")
            else:
                target.write_text("kept\\n", encoding="utf-8")
            send({{"jsonrpc": "2.0", "id": msg_id, "result": {{"sessionId": SESSION}}}})
            continue
        if method == "session/load" and msg_id is not None:
            send({{"jsonrpc": "2.0", "id": msg_id, "result": {{}}}})
            continue
        if method == "session/prompt" and msg_id is not None:
            if PHASE.is_file():
                send({{"jsonrpc": "2.0", "id": msg_id, "result": {{"stopReason": "end_turn"}}}})
                continue
            PHASE.write_text("blocked\\n", encoding="utf-8")
            tool_updates(str(params.get("sessionId") or SESSION))
            time.sleep(120)
            continue
        if msg_id is not None:
            send({{"jsonrpc": "2.0", "id": msg_id, "result": {{}}}})


if __name__ == "__main__":
    main()
"""

_NPM = """\
#!{python}
import json
import sys

if "root" in sys.argv:
    print({root!r})
else:
    print(json.dumps({{"dependencies": {{"scripted-acp": {{"version": "1.0.0"}}}}}}))
"""


def _prefix(tmp_path: Path, trace: Path, phase: Path) -> Path:
    root = tmp_path / "npm-root"
    package = root / "scripted-acp"
    package.mkdir(parents=True)
    server = package / "server.py"
    server.write_text(
        _SERVER.format(python=sys.executable, trace=str(trace), phase=str(phase)),
        encoding="utf-8",
    )
    server.chmod(0o755)
    (package / "package.json").write_text(
        json.dumps(
            {
                "name": "scripted-acp",
                "version": "1.0.0",
                "bin": {"scripted-acp": "server.py"},
            }
        ),
        encoding="utf-8",
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    link = bindir / "scripted-acp"
    link.symlink_to(server)
    npm = bindir / "npm"
    npm.write_text(_NPM.format(python=sys.executable, root=str(root)), encoding="utf-8")
    npm.chmod(0o755)
    return bindir


def _dataset(dataset: Path) -> None:
    task = dataset / "tasks" / "note"
    task.mkdir(parents=True)
    (dataset / "ageval.yaml").write_text(
        "format: ageval.dataset/1\ndataset_id: examples/acp-resume\n"
        "version: '0.1.0'\ntasks:\n  root: tasks\n",
        encoding="utf-8",
    )
    (task / "task.yaml").write_text(
        "\n".join(
            [
                "format: ageval.task/1",
                "task_id: note",
                "parameters:",
                "  active_profile: solver",
                "agent_profiles:",
                "  - id: solver",
                "limits:",
                "  wall_time_seconds: 180",
                "  environment_seconds: 60",
                "  agent_invocations: 1",
                "artifacts:",
                "  publishable:",
                "    - id: note",
                "      path: artifacts/note.txt",
                "evaluation:",
                "  inputs:",
                "    - artifact: note",
                "      target: artifacts/note.txt",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (task / "run.py").write_text(
        textwrap.dedent(
            """\
            from ageval_sdk import RunContext, RunTerminal

            async def run(ctx: RunContext) -> RunTerminal:
                path = ctx.workspace_root / "note.txt"
                async with ctx.agent.session("solver", max_turns=1) as session:
                    invoked = await session.invoke("write the note")
                if not invoked.get("ok"):
                    return RunTerminal.failed(str(invoked.get("error") or "failed"))
                if not path.is_file() or path.read_text(encoding="utf-8") != "kept\\n":
                    return RunTerminal.failed("note_missing")
                ctx.publish_file("note", path)
                return RunTerminal.completed("note")
            """
        ),
        encoding="utf-8",
    )
    (task / "evaluator.py").write_text(
        textwrap.dedent(
            """\
            from pathlib import Path

            def evaluate(inputs):
                raw = (inputs.get("artifacts") or {}).get("note")
                text = Path(str(raw)).read_text(encoding="utf-8") if raw else ""
                ok = text == "kept\\n"
                status = "PASS" if ok else "FAIL"
                return {"status": status, "score": 1.0 if ok else 0.0, "metrics": {}}
            """
        ),
        encoding="utf-8",
    )


def _entry(home: Path) -> None:
    (home / "acp-entries.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "entry_id": "scripted-acp",
                        "integration_mode": 2,
                        "execution_mode": "acp-stdio",
                        "engine_detect_commands": ["scripted-acp"],
                        "acp_command": ["scripted-acp"],
                        "acp_detect_commands": ["scripted-acp"],
                        "acp_package": "scripted-acp",
                        "acp_version": "1.0.0",
                        "install_command": "npm install -g scripted-acp@1.0.0",
                        "runtime": {"node": ">=16.0.0"},
                        "credential_env_names": ["OPENAI_API_KEY"],
                        "model_binding": "entry-default-only",
                        "platforms": ["darwin", "linux"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_acp_resume_loads_the_native_session(tmp_path: Path) -> None:
    trace = tmp_path / "methods.log"
    phase = tmp_path / "phase"
    bindir = _prefix(tmp_path, trace, phase)
    home = tmp_path / "home"
    home.mkdir()
    _entry(home)
    dataset = tmp_path / "ds"
    _dataset(dataset)
    profiles = dataset / "profiles.yaml"
    profiles.write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "environment: local",
                "agent_profiles:",
                "  solver:",
                "    executor: acp",
                "    model: {id: entry-default}",
                "    api_key: ${OPENAI_API_KEY}",
                "    options: {entry: scripted-acp}",
                "    extensions:",
                "      - plugin: acp",
                "      - plugin: local",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    env["AGEVAL_HOME"] = str(home)
    env["OPENAI_API_KEY"] = "ci-loopback-placeholder"
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    err = tmp_path / "run.err"
    out = tmp_path / "run.out"
    err_handle = err.open("w", encoding="utf-8")
    out_handle = out.open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ageval.cli.main",
                "run",
                str(dataset),
                "--task",
                "note",
                "--profiles",
                str(profiles),
            ],
            cwd=str(dataset),
            env=env,
            stdout=out_handle,
            stderr=err_handle,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 90
            attempt = None
            while time.monotonic() < deadline:
                attempt = _unsealed_with_tool(dataset)
                if attempt is not None:
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.2)
            preview = ""
            if attempt is None:
                preview = out.read_text(encoding="utf-8")[-1000:]
                preview += err.read_text(encoding="utf-8")[-1000:]
                if trace.is_file():
                    preview = preview + "\n" + trace.read_text(encoding="utf-8")
            assert attempt is not None, preview
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)
        except Exception:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
            raise
    finally:
        out_handle.close()
        err_handle.close()
    resumed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ageval.cli.main",
            "run",
            str(dataset),
            "--task",
            "note",
            "--profiles",
            str(profiles),
            "--resume",
            attempt.name,
        ],
        cwd=str(dataset),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    methods = trace.read_text(encoding="utf-8") if trace.is_file() else ""
    assert resumed.returncode == 0, (resumed.stdout, resumed.stderr, methods)
    assert methods.splitlines().count("session/new") == 1
    assert "session/load" in methods.splitlines()
    result = json.loads((attempt / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert (attempt / "trajectory.jsonl").is_file()
    header_lines = (attempt / "activity.jsonl").read_text(encoding="utf-8").splitlines()
    native = [
        json.loads(line)["payload"].get("native_session_id")
        for line in header_lines
        if json.loads(line).get("kind") == "session"
    ]
    assert native == ["native-1"]


def _unsealed_with_tool(dataset: Path) -> Path | None:
    runs = dataset / ".ageval" / "runs"
    if not runs.is_dir():
        return None
    for path in runs.iterdir():
        log = path / "activity.jsonl"
        if not path.is_dir() or not log.is_file() or (path / "result.json").is_file():
            continue
        for line in log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") == "tool_call" and row.get("status") == "completed":
                return path
    return None
