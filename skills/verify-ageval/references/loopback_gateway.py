"""Scripted OpenAI chat gateway on 127.0.0.1. Prints the base URL and serves.

The tool script matches the minimal-demo tau2-dialog-min task. Stop the
process when the run finishes. This is not a product executor.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

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


def main() -> None:
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
                            "function": {"name": name, "arguments": json.dumps(arguments)},
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

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address[:2]
    print(f"http://{host}:{port}/v1", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
