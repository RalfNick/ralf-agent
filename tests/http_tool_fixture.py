"""Owned loopback business endpoint; actual sockets, no external network."""

import json
import socket
import sqlite3
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@contextmanager
def endpoint(root=None):
    calls, started, release = [], threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            calls.append({"path": self.path, "headers": dict(self.headers), "body": body})
            started.set()
            if self.path in {"/write", "/write-lost"}:
                assert root is not None
                arguments = json.loads(body)
                with sqlite3.connect(root / "business.sqlite") as connection:
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS effects (effect_key TEXT PRIMARY KEY, result TEXT NOT NULL)"
                    )
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT result FROM effects WHERE effect_key=?", (arguments["effect_key"],)
                    ).fetchone()
                    if row:
                        result = json.loads(row[0])
                    else:
                        result = {
                            "value": arguments["value"],
                            "effect_key": arguments["effect_key"],
                        }
                        connection.execute(
                            "INSERT INTO effects VALUES (?,?)",
                            (arguments["effect_key"], json.dumps(result)),
                        )
                if self.path == "/write-lost" and len(calls) == 1:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                body = json.dumps(result).encode()
            if self.path == "/hang":
                release.wait(5)
            status, content, extra = 200, body, {}
            if self.path == "/redirect":
                status, content, extra = 307, b"", {"Location": "/normal"}
            elif self.path == "/nonzero":
                status, content = 503, b"private-response-secret"
            elif self.path == "/invalid":
                content = b"private-invalid-json"
            elif self.path == "/unicode":
                content = b'{"value":"\\ud800"}'
            elif self.path == "/duplicate":
                content = b'{"value":1,"value":2}'
            elif self.path == "/nan":
                content = b'{"value":NaN}'
            elif self.path == "/schema":
                content = b"[1]"
            elif self.path == "/oversized":
                content = b"x" * 65536
            elif self.path == "/compressed":
                extra["Content-Encoding"] = "gzip"
            self.send_response(status)
            self.send_header("Content-Length", str(len(content)))
            for key, value in extra.items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, started, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()
