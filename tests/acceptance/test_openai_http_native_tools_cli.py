"""Public lock/run: tau2-dialog-min on openai-http native tools (loopback mock)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

REPO = Path(__file__).resolve().parents[2]
JOURNEYS = REPO / "examples" / "datasets" / "minimal-demo"
TASK = "tau2-dialog-min"

_SERVICE_SCRIPT: list[tuple[str, dict[str, Any]]] = [
    ("find_customer", {"email": "alex@example.com"}),
    ("get_order", {"order_id": "#W1001"}),
    ("get_product", {"item_id": "item_headphones"}),
    (
        "request_exchange",
        {
            "order_id": "#W1001",
            "from_item_ids": ["item_headphones"],
            "to_item_ids": ["item_headphones_black"],
        },
    ),
    ("done", {"note": "exchange requested"}),
]


def _ageval(env: dict[str, str], *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=180,
    )


def _serve_scripted() -> tuple[ThreadingHTTPServer, str]:
    state = {"service": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            tools = body.get("tools") if isinstance(body.get("tools"), list) else []
            if tools:
                idx = min(state["service"], len(_SERVICE_SCRIPT) - 1)
                name, arguments = _SERVICE_SCRIPT[idx]
                state["service"] += 1
                message: dict[str, Any] = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{idx + 1}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
            else:
                message = {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "message": (
                                "Hi, I'm Alex. My email is alex@example.com and "
                                "order #W1001 arrived with the wrong color headphones; "
                                "I want the black variant instead."
                            )
                        }
                    ),
                }
            raw = json.dumps({"choices": [{"message": message}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/v1"


def test_tau2_dialog_min_openai_http_native_tools(tmp_path: Path) -> None:
    dataset = Path(
        shutil.copytree(
            JOURNEYS, tmp_path / "minimal-demo", ignore=shutil.ignore_patterns(".ageval", ".env")
        )
    )
    server, base = _serve_scripted()
    profiles = dataset / "profiles.openai-http.yaml"
    profiles.write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "environment: local",
                "agent_profiles:",
                "  user:",
                "    executor: openai-http",
                "    model: {id: mock}",
                f"    base_url: {base}",
                "    api_key: ${OPENAI_API_KEY}",
                "    extensions:",
                "      - plugin: openai-http",
                "      - plugin: local",
                "  service:",
                "    executor: openai-http",
                "    model: {id: mock}",
                f"    base_url: {base}",
                "    api_key: ${OPENAI_API_KEY}",
                "    extensions:",
                "      - plugin: openai-http",
                "      - plugin: local",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    env["OPENAI_API_KEY"] = "ci-loopback-placeholder"
    try:
        locked = _ageval(
            env,
            "lock",
            str(dataset),
            "--task",
            TASK,
            "--profiles",
            str(profiles),
            cwd=dataset,
        )
        assert locked.returncode == 0, locked.stderr
        lock_doc = json.loads(locked.stdout)
        dumped = json.dumps(lock_doc)
        assert "ci-loopback-placeholder" not in dumped
        assert "sk-" not in dumped.lower()
        assert lock_doc["task_id"] == TASK

        ran = _ageval(
            env,
            "run",
            str(dataset),
            "--task",
            TASK,
            "--profiles",
            str(profiles),
            cwd=dataset,
        )
        assert ran.returncode == 0, (ran.stdout, ran.stderr)
        result = json.loads(ran.stdout)
        assert result["status"] == "PASS"
        assert "Tool " not in ran.stderr
        assert "not found" not in ran.stderr.lower()
        states = list(dataset.rglob("final-state.json"))
        assert states, "published final-state missing"
        final = json.loads(states[0].read_text(encoding="utf-8"))
        assert int(final.get("tool_calls") or 0) > 0
        used = final.get("tools_used") or []
        assert "find_customer" in used
    finally:
        server.shutdown()
        server.server_close()


def test_tau2_dialog_min_acp_lock_does_not_require_tools() -> None:
    env = os.environ.copy()
    env.setdefault("ZHIPU_API_KEY", "ci-offline-placeholder")
    locked = _ageval(env, "lock", str(JOURNEYS), "--task", TASK, cwd=REPO)
    assert locked.returncode == 0, locked.stderr
    doc = json.loads(locked.stdout)
    assert doc["task_id"] == TASK
    overlay = doc.get("job_overlay") or {}
    profiles = overlay.get("agent_profiles") or {}
    for row in profiles.values():
        if isinstance(row, dict):
            assert row.get("executor") == "acp"
