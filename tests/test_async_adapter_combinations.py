"""Native async callable replacements exercise existing public execution paths."""

import asyncio
import inspect

import pytest

from ralf_agent import (
    AgentSpec,
    InMemoryArtifactStore,
    InvocationContext,
    LocalEngine,
    ModelResponse,
    Scope,
    SQLiteStore,
    ToolCall,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
    register_tool_source,
)
from ralf_agent.errors import ValidationError
from ralf_agent.ports import validate_engine

from .helpers import ScriptedProvider


class AsyncOperation:
    def __init__(self, operation):
        self.operation = operation

    async def __call__(self, *args, **kwargs):
        value = self.operation(*args, **kwargs)
        return await value if inspect.isawaitable(value) else value


class SyncOperation:
    """A lazy sync factory is deliberately not an async port."""

    def __init__(self, operation):
        self.operation = operation
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.operation(*args, **kwargs)


def test_callable_engine_operations_work_through_the_existing_local_service(tmp_path):
    import httpx

    from ralf_agent.a2a import A2AClient
    from ralf_agent.handoff import SQLiteInbox
    from ralf_agent.service_lifecycle import LocalA2AService

    class EngineView:
        def __init__(self, engine):
            self.original = engine
            self.drive = AsyncOperation(engine.drive)
            self.wait_for_threads = AsyncOperation(engine.wait_for_threads)

        def __getattr__(self, name):
            return getattr(self.original, name)

    async def run():
        engine = LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            tools=ToolRegistry(),
            providers={"default": ScriptedProvider([ModelResponse(output="done")])},
        )
        inbox = SQLiteInbox(tmp_path / "inbox.sqlite")
        service = None
        try:
            view = EngineView(engine)
            assert validate_engine(view) is view

            async def authenticate(headers):
                return Scope()

            service = LocalA2AService(
                engine=view,
                inbox=inbox,
                spec=AgentSpec("reader", "Answer"),
                authenticate=authenticate,
                url="http://test/rpc",
            )
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service)) as http:
                client = A2AClient("http://test/rpc", client=http)
                accepted = await client.send_message("original", {"q": "q"})
                async with asyncio.timeout(2):
                    # The supported remote protocol polls committed Task state.
                    while (done := await client.get_task(accepted["id"]))["status"][  # noqa: ASYNC110
                        "state"
                    ] != "completed":
                        await asyncio.sleep(0.01)
                assert done["artifacts"][0]["parts"][0]["data"]["result"] == "done"
                await client.aclose()
            await service.aclose()
            assert service.closed and service.errors == ()
        finally:
            if service is not None:
                await service.aclose()
            else:
                engine.close()
                inbox.close()

    asyncio.run(run())


def test_callable_tool_source_retains_approval_and_single_dispatch_after_restart(tmp_path):
    import ralf_agent

    from .test_tool_sources import Source, descriptor

    async def run():
        source = Source([descriptor(ralf_agent)])
        source.list_tools = AsyncOperation(source.list_tools)
        source.call_tool = AsyncOperation(source.call_tool)
        registry = ToolRegistry()
        await register_tool_source(registry, source, policies={"write": ToolPolicy("1")})
        spec = AgentSpec("writer", "Write", ("write",))
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            tools=registry,
            providers={
                "default": ScriptedProvider(
                    [ModelResponse(tool_calls=[ToolCall("write", {"value": 7})])]
                ),
            },
        ) as first:
            handle = first.submit(spec, "q", command_id="original")
            paused = await first.drive(handle.run_id)
            assert paused.state == "waiting_approval" and source.calls == []
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            tools=registry,
            providers={
                "default": ScriptedProvider([ModelResponse(output="done")]),
            },
        ) as second:
            assert second.submit(spec, "q", command_id="original") == handle
            target = paused.pending[0]
            receipt = second.approve(
                handle.run_id, target["action_id"], target["digest"], command_id="approve"
            )
            assert (
                second.approve(
                    handle.run_id, target["action_id"], target["digest"], command_id="approve"
                )
                == receipt
            )
            assert (await second.drive(handle.run_id)).state == "succeeded"
            assert len(source.calls) == 1 and source.calls[0][1] == {"value": 7}

    asyncio.run(run())


def test_callable_mcp_transport_discovers_and_executes_the_pinned_tool():
    from ralf_agent.mcp import MCPToolSource

    class Transport:
        identity = {"kind": "offline-callable-mcp", "version": "1"}

        def __init__(self):
            self.request = AsyncOperation(self.respond)
            self.writes = 0

        async def respond(self, method, params, *, expected_tool=None):
            if method == "tools/list":
                return {
                    "tools": [
                        {"name": "read", "description": "Read", "inputSchema": {"type": "object"}}
                    ]
                }
            assert method == "tools/call" and expected_tool["name"] == "read"
            self.writes += 1
            return {"content": [{"type": "text", "text": "result"}]}

    async def run():
        transport = Transport()
        source = MCPToolSource(transport)
        tool = (await source.list_tools())[0]
        result = await source.call_tool(
            tool, {}, InvocationContext(Scope(), "run", "action", "attempt", "key", "epoch")
        )
        assert result == {"content": [{"type": "text", "text": "result"}]}
        assert transport.writes == 1

    asyncio.run(run())


def test_callable_memory_extractor_retains_grounding_and_duplicate_consolidation(tmp_path):
    from ralf_agent.memory_extraction import MemoryAdmissionPolicy, RuleMemoryExtractor
    from ralf_agent.memory_pipeline import MemoryPipeline

    async def run():
        provider = ScriptedProvider([ModelResponse(output={"language": "中文"})])
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            tools=ToolRegistry(),
            providers={"default": provider},
        ) as engine:
            policy = MemoryAdmissionPolicy({"language": ("result", "language")})
            extractor = RuleMemoryExtractor(policy)
            extractor.extract = AsyncOperation(extractor.extract)
            pipeline = MemoryPipeline(engine, policy=policy, extractor=extractor)
            result = await pipeline.run(AgentSpec("reader", "Answer"), "q", command_id="s")
            assert result["memory"]["status"] == "completed"
            await pipeline.consolidate(result["task"]["run_id"], command_id="s:memory")
            facts = engine.memory.facts(Scope(), "auto-memory")
            assert len(facts) == 1 and facts[0]["value"]["value"] == "中文"
            assert provider.calls == 1

    asyncio.run(run())


def test_callable_artifact_ports_offload_without_losing_raw_tool_evidence(tmp_path):
    from ralf_agent.data_context import ManagedDataContext

    class Artifacts:
        def __init__(self):
            self.base = InMemoryArtifactStore(backend_id="callable-artifacts")
            self.put = AsyncOperation(self.base.put)
            self.get = AsyncOperation(self.base.get)
            self.backend_id = self.base.backend_id
            self.identity = self.base.identity

    async def run():
        artifacts = Artifacts()
        try:
            builder = ManagedDataContext(artifacts, tool_result_chars=1024, preview_chars=64)
            tools = ToolRegistry()
            raw = "ORIGINAL" * 1500
            tools.register(ToolSpec("read", "Read", {"type": "object"}), lambda args, ctx: raw)
            provider = ScriptedProvider(
                [
                    ModelResponse(tool_calls=[ToolCall("read", {}, "original-call")]),
                    ModelResponse(output="done"),
                ]
            )
            with LocalEngine(
                SQLiteStore(tmp_path / "runs.sqlite"),
                tools=tools,
                providers={"default": provider},
                context_assembler=builder,
            ) as engine:
                handle = engine.submit(
                    AgentSpec("reader", "Answer", ("read",), max_context_chars=2000),
                    "q",
                    command_id="s",
                )
                assert (await engine.drive(handle.run_id)).state == "succeeded"
                references = engine.context_artifacts(handle.run_id)
                assert references
                from ralf_agent import ArtifactReference
                from ralf_agent.types import canonical

                assert artifacts.base.get(
                    Scope(), ArtifactReference.from_dict(references[0]["intent"]["reference"])
                ) == canonical(raw)
                assert len(str(provider.messages[-1])) < len(raw)
        finally:
            artifacts.base.close()

    asyncio.run(run())


def test_callable_generation_ports_preserve_existing_index_maintenance_receipts(tmp_path):
    from ralf_agent import RecallQuery

    from .test_fact_index_maintenance_tools import NAME, NS, SCOPE, ctx, run_ports

    class View:
        def __init__(self, original, names):
            self.original = original
            for name in names:
                setattr(self, name, AsyncOperation(getattr(original, name)))

        def __getattr__(self, name):
            return getattr(self.original, name)

    async def run(ports):
        ports.seed(1)
        original = ports.index
        ports.index = View(original, ("source_snapshot", "rebuild_for_snapshot"))
        ports.index.original_catalog = View(original.original_catalog, ("load", "save"))
        tool = (await ports.registry()).get(NAME)
        first = await tool.handler({}, ctx())
        assert first["status"] == "ready"
        calls = ports.embedding.calls
        assert await tool.handler({}, ctx()) == first
        assert ports.embedding.calls == calls
        page = await ports.index.recall(SCOPE, NS, RecallQuery(text="violet target"))
        assert [item["key"] for item in page.items] == ["0"]

    run_ports(tmp_path, run)


@pytest.mark.parametrize("port", ["engine", "source", "mcp", "extractor", "artifacts"])
def test_sync_factories_are_refused_before_their_lazy_operations_are_entered(tmp_path, port):
    from ralf_agent.data_context import ManagedDataContext
    from ralf_agent.mcp import MCPToolSource
    from ralf_agent.memory_extraction import RuleMemoryExtractor
    from ralf_agent.memory_pipeline import MemoryPipeline

    from .test_tool_sources import Source

    async def unused(*args, **kwargs):
        raise AssertionError("Invalid lazy factory must never be entered")

    async def run():
        bad = SyncOperation(unused)
        artifacts = InMemoryArtifactStore(backend_id="mixed-artifacts")
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            tools=ToolRegistry(),
            providers={"default": ScriptedProvider([])},
        ) as engine:
            try:
                with pytest.raises(ValidationError):
                    if port == "engine":

                        class EngineView:
                            drive = bad

                            def __getattr__(self, name):
                                return getattr(engine, name)

                        validate_engine(EngineView())
                    elif port == "source":
                        source = Source([])
                        source.list_tools = bad
                        await register_tool_source(
                            ToolRegistry(), source, policies={"read": ToolPolicy("1")}
                        )
                    elif port == "mcp":

                        class Transport:
                            identity = {"kind": "invalid-sync", "version": "1"}
                            request = bad

                        MCPToolSource(Transport())
                    elif port == "extractor":
                        extractor = RuleMemoryExtractor()
                        extractor.extract = bad
                        MemoryPipeline(engine, extractor=extractor)
                    else:

                        class MixedArtifacts:
                            backend_id = artifacts.backend_id
                            identity = artifacts.identity
                            put = bad
                            get = AsyncOperation(artifacts.get)

                        ManagedDataContext(MixedArtifacts())
                assert bad.calls == 0
            finally:
                artifacts.close()

    asyncio.run(run())
