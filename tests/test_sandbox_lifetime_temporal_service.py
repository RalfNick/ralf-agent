"""Original History quiescence requires actual native stop, not cancelled waiting."""

import asyncio
import os
import uuid

import pytest

import ralf_agent as r
from ralf_agent.temporal import replay_temporal_history

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS") or not os.getenv("RALF_TEST_DOCKER_IMAGE"),
    reason="requires actual local Temporal and Docker fixtures",
)


def test_actual_cancel_close_retains_original_native_thread_and_history_end(tmp_path):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "sandbox-lifetime-" + uuid.uuid4().hex
        scope = r.Scope("sandbox-lifetime", queue)
        ports, sources, native_calls = [], [], []

        class Native(r.DockerSandbox):
            async def run(self, scope, request, *, invocation_id):
                native_calls.append((scope, invocation_id))
                return await super().run(scope, request, invocation_id=invocation_id)

        class Reader:
            identity = {"kind": "sandbox-lifetime-reader", "version": "1"}

            async def complete(self, messages, tools):
                return r.ModelResponse(
                    tool_calls=[r.ToolCall("sandbox_run", {"argv": ["/bin/sleep", "30"]}, "native")]
                )

        factories = r.ComponentRegistry()
        factories.register("provider", "reader", lambda c, ctx: Reader())

        async def tools(config, context):
            port = context.own_async(
                Native(
                    os.environ["RALF_TEST_DOCKER_SOCKET"],
                    os.environ["RALF_TEST_DOCKER_IMAGE"],
                    version="1",
                    scopes=[context.scope],
                )
            )
            await port.aopen()
            source = context.own_async(r.SandboxToolSource(port, version="1"))
            ports.append(port)
            sources.append(source)
            registry = r.ToolRegistry()
            await r.register_tool_source(
                registry,
                source,
                policies={
                    "sandbox_run": r.ToolPolicy("1", effect="read_only", requires_approval=True)
                },
            )
            return registry

        factories.register_async("tools", "native", tools)
        profile = r.TemporalProfile(
            "native",
            "1",
            {"default": {"adapter": "reader"}},
            {"tools": {"adapter": "native"}},
            binding_components=[
                {
                    "role": "sandbox",
                    "component_id": "native",
                    "version": "1",
                    "component": {
                        "adapter": "registered-tools",
                        "config": {"names": ["sandbox_run"]},
                    },
                }
            ],
        )
        assembly = await r.TemporalRuntimeBuilder(factories).abuild(profile, scope=scope)
        observer = None
        try:
            await assembly.start_worker(client, task_queue=queue)
            engine = assembly.create_engine(client, task_queue=queue, activity_timeout=45)
            observer = r.TemporalEngine(
                client, task_queue=queue, release=assembly.release, scope=scope, activity_timeout=45
            )
            spec = r.AgentDefinition(
                r.AgentSpec("native", "Execute", tools=("sandbox_run",)),
                r.AgentBindingDescriptor(sandbox=r.BindingSelection.ref("native", "1")),
            )
            handle = await engine.submit(spec, "native", command_id="submit")
            waiting = await engine.drive(handle.run_id, wait_seconds=15)
            assert waiting.state == "waiting_approval"
            pending = waiting.pending[0]
            await engine.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            for _ in range(1000):
                if (
                    native_calls
                    and (await ports[0].observe(scope, native_calls[0][1])).state == "running"
                ):
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("original native handler did not report running")
            receipt = await engine.cancel(handle.run_id, command_id="cancel")
            assert await engine.cancel(handle.run_id, command_id="cancel") == receipt
            blocked = await observer.diagnostics(handle.run_id)
            assert blocked.workflow["quiescent"] is False
            assert ports[0]._tracker.has_active and sources[0]._calls
            with pytest.raises(r.CloseIncomplete):
                await assembly.aclose(wait_timeout=0)
            assert assembly._worker_stop is None
            assert (await ports[0].observe(scope, native_calls[0][1])).state == "running"
            await ports[0].stop(scope, native_calls[0][1])
            assert await assembly._calls.wait(wait_timeout=15)
            assert await assembly._runtime.wait_context_executions(wait_timeout=15)
            for _ in range(500):
                done = await observer.diagnostics(handle.run_id)
                if done.workflow["quiescent"]:
                    break
                await asyncio.sleep(0.01)
            assert done.workflow["quiescent"] is True and done.snapshot.state == "cancelled"
            assert (
                not ports[0]._tracker.has_active
                and sources[0]._calls == {}
                and len(native_calls) == 1
            )
            await replay_temporal_history(
                await client.get_workflow_handle(handle.run_id).fetch_history()
            )
        finally:
            if native_calls:
                await ports[0].stop(scope, native_calls[0][1])
            await assembly.aclose(wait_timeout=30)
            if observer is not None:
                await observer.aclose()

    asyncio.run(run())
