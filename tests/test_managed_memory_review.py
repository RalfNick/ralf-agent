import asyncio
import functools
import time

import httpx
import pytest

from ralf_agent import (
    AgentSpec,
    InMemoryMemory,
    LocalEngine,
    MemoryAdmissionPolicy,
    MemoryPipeline,
    ModelResponse,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.errors import ValidationError
from ralf_agent.providers import DeepSeekChatProvider
from ralf_agent.temporal_activities import TemporalRuntime


class Provider:
    identity = {"kind": "review-source-fixture", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output={"project": "RALF"})


@pytest.mark.parametrize("during_write", [False, True])
def test_expired_memory_does_not_receive_success_receipt(tmp_path, monkeypatch, during_write):
    clock = {"now": 99.0}
    monkeypatch.setattr(time, "time", lambda: clock["now"])

    class Memory(InMemoryMemory):
        async def put_fact(self, *args, **kwargs):
            version = super().put_fact(*args, **kwargs)
            if args[1] == "auto-memory" and during_write:
                clock["now"] = 101.0
            return version

    async def run():
        with LocalEngine(
            SQLiteStore(tmp_path / "run.sqlite"),
            providers={"default": Provider()},
            tools=ToolRegistry(),
        ) as engine:
            memory = Memory()
            policy = MemoryAdmissionPolicy(
                {"project": ("result", "project")}, expires_at=100.0 if during_write else 98.0
            )
            result = await MemoryPipeline(engine, memory=memory, policy=policy).run(
                AgentSpec("a", "Observe"), "project", command_id="one"
            )
            assert result["task"]["state"] == "succeeded"
            assert result["memory"]["status"] == "failed"
            assert memory.facts(engine.scope, "auto-memory") == []

    asyncio.run(run())


def test_lazy_temporal_context_is_rejected_without_executing_generator():
    executed = []

    class Builder:
        identity = {"kind": "lazy-context-review", "version": "1"}

        def assemble(self, history, references, max_chars):
            def lazy():
                executed.append("executed")
                yield history
                yield {}

            return lazy()

    async def run():
        runtime = TemporalRuntime(
            providers={"default": Provider()}, tools=ToolRegistry(), context_builder=Builder()
        )
        response = await runtime.prepare_context(
            {
                "runtime_manifest": runtime.manifest,
                "scope": {"workspace": "default", "principal": "local-owner"},
                "step": {"name": "a", "instructions": "Answer"},
                "messages": [
                    {"role": "system", "content": "Answer"},
                    {"role": "user", "content": "task"},
                ],
            }
        )
        assert response == {"ok": False, "code": "validation_error"}
        assert executed == []

    asyncio.run(run())


def test_different_dynamic_context_code_has_different_release():
    def builder(text):
        namespace = {"__name__": "dynamic_context_plugin"}
        exec(
            "class Builder:\n identity = {'kind':'dynamic-context','version':'1'}\n def assemble(self, history, references, max_chars):\n  return history, {'marker':"
            + repr(text)
            + "}\n",
            namespace,
        )
        return namespace["Builder"]()

    first = TemporalRuntime(
        providers={"default": Provider()}, tools=ToolRegistry(), context_builder=builder("first")
    )
    second = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        context_builder=builder("different"),
    )
    assert first.manifest != second.manifest


def test_different_context_wrappers_have_different_release():
    def builder(marker):
        def original(self, history, references, max_chars):
            return history, {}

        @functools.wraps(original)
        def wrapped(self, history, references, max_chars):
            messages, identity = original(self, history, references, max_chars)
            return messages, {**identity, "marker": marker}

        return type(
            "Builder",
            (),
            {"identity": {"kind": "wrapped-context", "version": "1"}, "assemble": wrapped},
        )()

    first = TemporalRuntime(
        providers={"default": Provider()}, tools=ToolRegistry(), context_builder=builder("first")
    )
    second = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        context_builder=builder("different"),
    )
    assert first.manifest != second.manifest


def test_explicit_streaming_under_json_mode_refused_before_http():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"not JSON"}}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = DeepSeekChatProvider(
                "model", api_key="fixture", json_mode=True, client=client
            )
            with pytest.raises(ValidationError):
                async for _ in provider.stream([{"role": "user", "content": "Return JSON"}], []):
                    pass
        assert requests == []

    asyncio.run(run())


def test_lazy_memory_extraction_not_iterated(tmp_path):
    executed = []

    class Extractor:
        identity = {"kind": "lazy-extractor", "version": "1"}

        async def extract(self, *args, **kwargs):
            def lazy():
                executed.append(True)
                yield []
                yield None

            return lazy()

    async def run():
        with LocalEngine(
            SQLiteStore(tmp_path / "run.sqlite"),
            providers={"default": Provider()},
            tools=ToolRegistry(),
        ) as engine:
            pipeline = MemoryPipeline(engine, extractor=Extractor())
            result = await pipeline.run(AgentSpec("a", "Observe"), "project", command_id="one")
            assert result["memory"]["status"] == "failed"
            assert executed == []

    asyncio.run(run())


def test_memory_duplicate_recall_cannot_exceed_page_allowance(tmp_path):
    from ralf_agent.recall import RecallPage

    class Memory(InMemoryMemory):
        oversized = False

        def recall(self, *args, **kwargs):
            page = super().recall(*args, **kwargs)
            if self.oversized and page.items:
                items = page.items * 17
                from ralf_agent.types import canonical

                return RecallPage(items, None, len(canonical(items)), 17, 0, page.snapshot_id)
            return page

    async def run():
        with LocalEngine(
            SQLiteStore(tmp_path / "run.sqlite"),
            providers={"default": Provider()},
            tools=ToolRegistry(),
        ) as engine:
            memory = Memory()
            pipeline = MemoryPipeline(engine, memory=memory)
            result = await pipeline.run(AgentSpec("a", "Observe"), "project", command_id="one")
            assert result["memory"]["status"] == "completed"
            memory.oversized = True
            with pytest.raises(ValidationError):
                await pipeline.consolidate(result["task"]["run_id"], command_id="one:memory")

    asyncio.run(run())
