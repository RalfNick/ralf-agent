"""Owned actual HTTP MCP peer; no external credentials or service."""

import json
import socket
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ralf_agent import ToolDescriptor


def descriptor(write=False):
    properties = {"value": {"type": "integer"}}
    if write:
        properties["effect_key"] = {"type": "string"}
    return ToolDescriptor(
        "write" if write else "read",
        "MCP fixture",
        {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        {"type": "object"},
    )


def remote_tool(write=False):
    d = descriptor(write)
    return {
        "name": d.name,
        "description": d.description,
        "inputSchema": d.input_schema,
        "outputSchema": d.output_schema,
    }


@contextmanager
def peer(mode="json", *, root=None, write=False):
    calls, sessions = [], {}
    protocol = mode if mode in {"2025-06-18", "2025-03-26"} else "2025-11-25"
    lock = threading.Lock()
    started, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, data=b"", *, content="application/json", session=None):
            self.send_response(status)
            self.send_header("Content-Type", content)
            self.send_header("Content-Length", str(len(data)))
            if session is not None:
                self.send_header("MCP-Session-Id", session)
            if mode == "compressed":
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_DELETE(self):
            with lock:
                calls.append({"verb": "DELETE", "headers": dict(self.headers), "message": None})
                sessions.pop(self.headers.get("MCP-Session-Id"), None)
            self.respond(405 if mode == "delete-405" else 204)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            message = json.loads(raw)
            with lock:
                calls.append({"verb": "POST", "headers": dict(self.headers), "message": message})
            method = message.get("method")
            if method == "initialize":
                session = uuid.uuid4().hex
                if mode == "bad-session":
                    session = "bad session"
                sessions[session] = False
                result = {
                    "protocolVersion": "2099-01-01" if mode == "version" else protocol,
                    "capabilities": {} if mode == "no-tools" else {"tools": {}},
                    "serverInfo": {"name": "owned-peer", "version": "1"},
                }
            else:
                session = self.headers.get("MCP-Session-Id")
                assert session in sessions, "Original session required"
                assert self.headers.get("MCP-Protocol-Version") == protocol
                if method == "notifications/initialized":
                    sessions[session] = True
                    self.respond(202)
                    return
                assert sessions[session]
                if method is None:
                    self.respond(202)
                    return
                if method == "tools/list":
                    tool = remote_tool(write)
                    if mode == "drift":
                        tool["description"] = "changed"
                    if mode.startswith("external-"):
                        field = "inputSchema" if "input" in mode else "outputSchema"
                        key = "$dynamicRef" if "dynamic" in mode else "$ref"
                        tool[field] = {
                            "type": "object",
                            key: "http://metadata.invalid/private-schema",
                        }
                    elif mode == "local-ref":
                        for field in ("inputSchema", "outputSchema"):
                            tool[field] = {
                                "type": "object",
                                "$id": "https://schema.invalid/self",
                                "$defs": {"number": {"type": "integer"}},
                                "properties": {"value": {"$ref": "#/$defs/number"}},
                                "required": ["value"],
                            }
                    if mode in {"pagination", "unsolicited"} and not message["params"].get(
                        "cursor"
                    ):
                        result = {"tools": [], "nextCursor": "session-cursor"}
                    else:
                        result = {"tools": [tool]}
                elif method == "tools/call":
                    started.set()
                    if mode == "hang":
                        release.wait(5)
                    if mode == "404":
                        self.respond(404, b"private-peer-error")
                        return
                    output = message["params"]["arguments"]
                    if write:
                        assert root is not None
                        with sqlite3.connect(root / "business.sqlite") as connection:
                            connection.execute(
                                "CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, result TEXT NOT NULL)"
                            )
                            connection.execute("BEGIN IMMEDIATE")
                            row = connection.execute(
                                "SELECT result FROM effects WHERE key=?", (output["effect_key"],)
                            ).fetchone()
                            if row:
                                output = json.loads(row[0])
                            else:
                                connection.execute(
                                    "INSERT INTO effects VALUES (?,?)",
                                    (output["effect_key"], json.dumps(output)),
                                )
                        if (
                            mode == "write-lost"
                            and sum(
                                c["message"] is not None
                                and c["message"].get("method") == "tools/call"
                                for c in calls
                            )
                            == 1
                        ):
                            self.connection.shutdown(socket.SHUT_RDWR)
                            self.connection.close()
                            return
                    result = {
                        "content": [{"type": "text", "text": "confirmed"}],
                        "structuredContent": output,
                    }
                else:
                    raise AssertionError(method)
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": result}
            if mode == "wrong-id":
                reply["id"] = 99
            elif mode == "bool-id":
                reply["id"] = True
            elif mode == "both":
                reply["error"] = {"code": -1, "message": "private-peer-error"}
            elif mode == "error":
                reply = {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -1, "message": "private-peer-error"},
                }
            elif mode == "array":
                reply["result"] = []
            raw = json.dumps(reply, ensure_ascii=False).encode()
            if mode == "invalid":
                raw = b"private-invalid-json"
            elif mode == "duplicate":
                raw = b'{"jsonrpc":"2.0","id":1,"id":1,"result":{}}'
            elif mode == "nan":
                raw = b'{"jsonrpc":"2.0","id":1,"result":{"invalid":NaN}}'
            elif mode == "surrogate":
                raw = b'{"jsonrpc":"2.0","id":1,"result":{"invalid":"\\ud800"}}'
            elif mode == "oversized":
                raw = b"x" * 65536
            content = "application/json"
            if (
                mode in {"sse", "ping", "elicitation", "sse-eof"}
                or mode == "unsolicited"
                and method == "tools/list"
            ):
                content = "text/event-stream"
                prefix = b": keepalive\r\n\r\ndata:\r\n\r\n"
                if method == "tools/call" and mode in {"ping", "elicitation"}:
                    request = {
                        "jsonrpc": "2.0",
                        "id": "server-1",
                        "method": "ping" if mode == "ping" else "elicitation/create",
                        "params": {},
                    }
                    prefix += (
                        b"event: message\r\ndata: " + json.dumps(request).encode() + b"\r\n\r\n"
                    )
                if mode == "unsolicited":
                    for index in range(100):
                        message_id = f"server-{message['id']}-{index}"
                        request = {"jsonrpc": "2.0", "id": message_id, "method": "ping"}
                        prefix += b"data: " + json.dumps(request).encode() + b"\r\n\r\n"
                raw = (
                    prefix
                    if mode == "sse-eof"
                    else prefix + b"event: message\r\ndata: " + raw + b"\r\n\r\n"
                )
            changed = "another-session" if mode == "rotate" and method != "initialize" else None
            self.respond(
                200, raw, content=content, session=session if method == "initialize" else changed
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp", calls, started, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()
