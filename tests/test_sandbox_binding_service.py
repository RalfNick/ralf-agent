"""Six actual Local native compositions keep approval and terminal recovery."""

import asyncio
import os

import pytest

import ralf_agent as r

from .test_sandbox_binding_execution import Reader, definition
from .test_workspace_binding_execution import finish

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_DOCKER_IMAGE"), reason="requires actual local Docker fixture"
)


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_actual_selected_native_members_restart_approval_and_completed_result(tmp_path, kind):
    observed = []

    class Tracked(r.DockerSandbox):
        async def run(self, scope, request, *, invocation_id):
            value = await super().run(scope, request, invocation_id=invocation_id)
            observed.append(value.stdout.strip())
            return value

    async def run():
        factories = r.ComponentRegistry()
        factories.register("provider", "reader", lambda c, ctx: Reader())

        async def tools(config, context):
            registry = r.ToolRegistry()
            for name in ("alpha", "beta"):
                port = context.own_async(
                    Tracked(
                        os.environ["RALF_TEST_DOCKER_SOCKET"],
                        os.environ["RALF_TEST_DOCKER_IMAGE"],
                        version=name,
                        scopes=[context.scope],
                    )
                )
                await port.aopen()
                source = context.own_async(r.SandboxToolSource(port, version="1"))
                await r.register_tool_source(
                    registry,
                    source,
                    prefix=name + "_",
                    policies={
                        "sandbox_run": r.ToolPolicy("1", effect="read_only", requires_approval=True)
                    },
                )
            registry.register(
                r.ToolSpec("business", "Business", {"type": "object"}), lambda a, c: "business"
            )
            return registry

        factories.register_async("tools", "native", tools)
        profile = r.RuntimeProfile(
            "native",
            "1",
            {"default": {"adapter": "reader"}},
            {"tools": {"adapter": "native"}},
            binding_components=[
                {
                    "role": "sandbox",
                    "component_id": name,
                    "version": "1",
                    "component": {
                        "adapter": "registered-tools",
                        "config": {"names": [name + "_sandbox_run"]},
                    },
                }
                for name in ("alpha", "beta")
            ],
        )
        original, saved = None, None
        for stage in range(3):
            runtime = await r.RuntimeBuilder(factories).abuild(profile, tmp_path / "runs.sqlite")
            try:
                handle = runtime.submit(definition(kind), "native", command_id="same", budget=64)
                if stage == 0:
                    original = handle
                    waiting = await runtime.drive(handle.run_id)
                    assert waiting.state == "waiting_approval" and observed == []
                else:
                    assert handle == original
                    done = await finish(runtime, handle.run_id)
                    assert done.state == "succeeded", done.error
                    assert (
                        runtime.diagnostics(handle.run_id).manifest["kernel"] == "local-bindings-14"
                    )
                    if stage == 1:
                        saved = done.result
                    else:
                        assert done.result == saved
            finally:
                await runtime.aclose()
        assert sorted(observed) == (["alpha"] if kind == "agent" else ["alpha", "beta"])

    asyncio.run(run())


def test_actual_local_cancel_keeps_coordinator_until_native_stop(tmp_path):
    from ralf_agent.errors import CoordinatorBusy, ValidationError

    async def run():
        port = r.DockerSandbox(
            os.environ["RALF_TEST_DOCKER_SOCKET"],
            os.environ["RALF_TEST_DOCKER_IMAGE"],
            version="local-cancel",
        )
        await port.aopen()
        source = r.SandboxToolSource(port, version="1")
        registry = r.ToolRegistry()
        await r.register_tool_source(
            registry,
            source,
            policies={
                "sandbox_run": r.ToolPolicy("1", effect="read_only", requires_approval=False)
            },
        )

        class Slow:
            identity = {"kind": "slow-native-reader", "version": "1"}

            async def complete(self, messages, tools):
                return r.ModelResponse(
                    tool_calls=[r.ToolCall("sandbox_run", {"argv": ["/bin/sleep", "30"]}, "native")]
                )

        path = tmp_path / "runs.sqlite"
        engine = r.LocalEngine(r.SQLiteStore(path), providers={"default": Slow()}, tools=registry)
        task = None
        try:
            handle = engine.submit(
                r.AgentSpec("native", "Run", tools=("sandbox_run",)), "q", command_id="submit"
            )
            task = asyncio.create_task(engine.drive(handle.run_id))
            for _ in range(1000):
                if task.done():
                    done = await task
                    pytest.fail(f"Native drive ended before running: {done.state} {done.error}")
                if source._calls:
                    identifier = next(iter(source._calls))
                    if (await port.observe(r.Scope(), identifier)).state == "running":
                        break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Original local native handler never started")
            receipt = engine.cancel(handle.run_id, command_id="cancel")
            assert engine.cancel(handle.run_id, command_id="cancel") == receipt
            with pytest.raises(ValidationError):
                engine.close()
            other = r.SQLiteStore(path)
            try:
                with pytest.raises(CoordinatorBusy):
                    r.LocalEngine(other, providers={"default": Slow()}, tools=registry)
            finally:
                other.close()
            assert (
                engine._threads.has_active
                and (await port.observe(r.Scope(), identifier)).state == "running"
            )
            await port.stop(r.Scope(), identifier)
            await task
            assert (
                engine.status(handle.run_id).state == "cancelled" and not engine._threads.has_active
            )
        finally:
            if source._calls:
                await source.aclose(wait_timeout=15)
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            engine.close()
            await source.aclose(wait_timeout=15)
            await port.aclose(wait_timeout=15)

    asyncio.run(run())
