"""Sole-review I2 against actual original native duplicate ownership."""

import asyncio
import os

import pytest

import ralf_agent as r

from .test_sandbox_tools import context

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_DOCKER_IMAGE"), reason="requires actual local Docker fixture"
)


def test_rejected_duplicate_source_close_cannot_stop_original_live_native_call():
    async def run():
        port = r.DockerSandbox(
            os.environ["RALF_TEST_DOCKER_SOCKET"],
            os.environ["RALF_TEST_DOCKER_IMAGE"],
            version="source-duplicate-review",
        )
        await port.aopen()
        first, second = (
            r.SandboxToolSource(port, version="1"),
            r.SandboxToolSource(port, version="1"),
        )
        task = None
        try:
            descriptor = (await first.list_tools())[0]
            arguments = {"argv": ["/bin/sleep", "30"]}
            task = asyncio.create_task(first.call_tool(descriptor, arguments, context()))
            for _ in range(500):
                if first._calls:
                    identifier = next(iter(first._calls))
                    if (await port.observe(r.Scope(), identifier)).state == "running":
                        break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Original native container never reported running")
            with pytest.raises(r.SandboxUnavailable):
                await second.call_tool(descriptor, arguments, context())
            await second.aclose(wait_timeout=5)
            assert first._calls and not task.done()
            assert (await port.observe(r.Scope(), identifier)).state == "running"
            assert second._calls == {}
        finally:
            await first.aclose(wait_timeout=15)
            await second.aclose(wait_timeout=15)
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await port.aclose(wait_timeout=15)

    asyncio.run(run())


def test_native_cleaned_failure_releases_original_engine_shutdown(tmp_path):
    import socketserver
    import tempfile
    import threading
    from http.server import BaseHTTPRequestHandler

    import httpx

    faulted = threading.Event()
    counts = {"create": 0}

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
            if self.command == "POST" and "/containers/create?" in self.path:
                counts["create"] += 1
            data = response.content
            if self.command == "GET" and "/logs?" in self.path and not faulted.is_set():
                assert response.status_code == 200
                faulted.set()
                data = b"invalid Docker log frame"
            self.send_response(response.status_code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = forward
        do_POST = forward
        do_DELETE = forward

    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    with (
        tempfile.TemporaryDirectory(prefix="ralf-sbx-cleaned-", dir="/tmp") as directory,
        Server(directory + "/docker.sock", Proxy) as server,
    ):
        thread = threading.Thread(target=server.serve_forever)
        thread.start()

        async def run():
            port = r.DockerSandbox(
                directory + "/docker.sock",
                os.environ["RALF_TEST_DOCKER_IMAGE"],
                version="cleaned-error-review",
            )
            source = None
            engine = None
            try:
                await port.aopen()
                source = r.SandboxToolSource(port, version="1")
                tools = r.ToolRegistry()
                await r.register_tool_source(
                    tools,
                    source,
                    policies={
                        "sandbox_run": r.ToolPolicy(
                            "1", effect="read_only", requires_approval=False
                        )
                    },
                )
                from .helpers import ScriptedProvider

                model = ScriptedProvider(
                    [
                        r.ModelResponse(
                            tool_calls=(
                                r.ToolCall("sandbox_run", {"argv": ["/bin/echo", "cleanup"]}),
                            )
                        )
                    ]
                )
                engine = r.LocalEngine(
                    r.SQLiteStore(tmp_path / "runs.sqlite"),
                    providers={"default": model},
                    tools=tools,
                )
                h = engine.submit(
                    r.AgentSpec("invalid-control", "Execute", tools=("sandbox_run",)),
                    "task",
                    command_id="invalid",
                )
                result = await engine.drive(h.run_id)
                assert result.state == "waiting_reconciliation", result
                assert faulted.is_set() and counts == {"create": 1}
                assert source._calls == {} and port._jobs == {}
                await asyncio.wait_for(engine.wait_for_threads(), 5)
                engine.close()
            finally:
                if source is not None:
                    await source.aclose(wait_timeout=15)
                await port.aclose(wait_timeout=15)
                if engine is not None:
                    engine.close()

        try:
            asyncio.run(run())
        finally:
            server.shutdown()
            thread.join(5)
            assert not thread.is_alive()
