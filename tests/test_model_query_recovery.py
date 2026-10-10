import json
import os
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import ralf_agent


@pytest.fixture
def model_query_endpoint():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            if self.path == "/v1/chat/completions":
                assert body["model"] == "queries" and not body.get("tools")
                assert json.loads(body["messages"][1]["content"]) == {"query": "car"}
                assert "automobile servicing" not in str(body) and "automobile manual" not in str(
                    body
                )
                response = {
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": '{"queries":["automobile"]}',
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 6},
                }
            else:
                assert self.path == "/v1/embeddings" and body["model"] == "fixture"
                response = {
                    "object": "list",
                    "model": "fixture",
                    "data": [
                        {"index": i, "object": "embedding", "embedding": [1, 0]}
                        for i, text in enumerate(body["input"])
                    ],
                    "usage": {
                        "prompt_tokens": len(body["input"]),
                        "total_tokens": len(body["input"]),
                    },
                }
            data = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_received_model_recovery_reuses_model_query_and_embedding_preparation(
    tmp_path, model_query_endpoint
):
    endpoint, requests = model_query_endpoint
    fixture = Path(__file__).with_name("model_query_crash_fixture.py")
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join(
            [str(Path(ralf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
        ),
        "QUERY_FIXTURE_KEY": "fixture-key",
    }
    for mode, expected in (("crash", 77), ("waiting", 0), ("finish", 0)):
        result = subprocess.run(
            [sys.executable, str(fixture), str(tmp_path), endpoint, mode],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == expected, result.stderr
        if mode != "crash":
            assert json.loads(result.stdout)["state"] == (
                "waiting_approval" if mode == "waiting" else "succeeded"
            )
        turns = 2 if mode == "finish" else 1
        assert sum(path == "/v1/chat/completions" for path, _ in requests) == 2 * turns
        assert sum(path == "/v1/embeddings" for path, _ in requests) == turns
        with sqlite3.connect(tmp_path / "business.sqlite") as db:
            assert db.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == turns
    with sqlite3.connect(tmp_path / "business.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
