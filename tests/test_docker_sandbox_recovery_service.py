"""Lost HTTP receipts forwarded to a real Docker daemon, not fabricated task state."""

import asyncio
import os
import socketserver
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler

import httpx
import pytest

import relf_agent as r

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_DOCKER_IMAGE"), reason="requires explicit actual local Docker fixture"
)


@pytest.mark.parametrize("window", ["create", "start"])
def test_actual_lost_native_receipt_queries_original_container_without_duplicate_start(window):
    counts, dropped = {"create": 0, "start": 0}, threading.Event()

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def forward(self):
            size = int(self.headers.get("Content-Length", "0"))
            assert 0 <= size <= 1048576
            payload = self.rfile.read(size)
            with httpx.Client(
                transport=httpx.HTTPTransport(uds=os.environ["RALF_TEST_DOCKER_SOCKET"]),
                timeout=10,
                trust_env=False,
            ) as client:
                response = client.request(
                    self.command,
                    "http://localhost" + self.path,
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )
            kind = (
                "create"
                if "/containers/create?" in self.path
                else "start"
                if self.path.endswith("/start")
                else None
            )
            if kind is not None and self.command == "POST":
                counts[kind] += 1
                if kind == window and not dropped.is_set():
                    dropped.set()
                    self.close_connection = True
                    return  # Native daemon accepted; this owned proxy loses only its reply.
            self.send_response(response.status_code)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = forward
        do_POST = forward
        do_DELETE = forward

    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    with (
        tempfile.TemporaryDirectory(prefix="ralf-sbx-proxy-", dir="/tmp") as directory,
        Server(directory + "/docker.sock", Proxy) as server,
    ):
        path = directory + "/docker.sock"
        thread = threading.Thread(target=server.serve_forever)
        thread.start()

        async def run():
            provider = r.DockerSandbox(
                str(path), os.environ["RALF_TEST_DOCKER_IMAGE"], version="lost-receipt"
            )
            identity = "lost-" + uuid.uuid4().hex
            try:
                await provider.aopen()
                result = await provider.run(
                    r.Scope(),
                    r.SandboxRequest(["/bin/sh", "-c", "echo accepted; sleep 0.1"]),
                    invocation_id=identity,
                )
                assert result.exit_code == 0 and result.stdout == "accepted\n"
                assert result.observation.state == "stopped"
                assert (await provider.observe(r.Scope(), identity)).state == "not_found"
                assert dropped.is_set() and counts == {"create": 1, "start": 1}
            finally:
                await provider.aclose(wait_timeout=15)

        try:
            asyncio.run(run())
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive(), "owned native receipt proxy failed to stop"
