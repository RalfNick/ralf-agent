import asyncio
import os
import subprocess
import sys

import pytest

from relf_agent import AgentSpec, LocalEngine, Scope, ToolRegistry
from relf_agent.errors import IdempotencyConflict, ValidationError
from relf_agent.storage import SQLiteStore

from .helpers import ScriptedProvider


def test_outbox_and_inbox_reopen_preserve_scoped_identity(tmp_path):
    from relf_agent.handoff import SQLiteInbox, SQLiteOutbox
    from relf_agent.messaging import InMemoryMessageBus, MessageEnvelope

    scope = Scope()
    message = MessageEnvelope("stable", "commands", {"kind": "cancel", "run_id": "run"})
    path = tmp_path / "handoff.db"
    outbox = SQLiteOutbox(path)
    assert outbox.enqueue(scope, message) == "stable"
    outbox.close()
    outbox = SQLiteOutbox(path)
    assert len(outbox.pending(scope)) == 1
    with pytest.raises(IdempotencyConflict):
        outbox.enqueue(scope, MessageEnvelope("stable", "commands", {}))

    async def check():
        bus = InMemoryMessageBus()
        await bus.ensure_group(scope, "commands", "g")
        assert await outbox.flush(bus, scope) == 1
        assert await outbox.flush(bus, scope) == 0
        delivery = (await bus.receive(scope, "commands", "g", "worker"))[0]
        inbox = SQLiteInbox(path)
        assert inbox.accept(scope, delivery.message) is None
        inbox.complete(scope, delivery.message, {"ok": True})
        inbox.close()
        inbox = SQLiteInbox(path)
        assert inbox.accept(scope, delivery.message) == {"ok": True}
        inbox.close()
        await bus.aclose()

    asyncio.run(check())
    outbox.close()


def test_delivery_replay_after_command_accepted_before_inbox_result(tmp_path):
    from relf_agent.handoff import (
        EngineCommandDispatcher,
        LocalCommandAdapter,
        SQLiteInbox,
        consume_delivery,
    )
    from relf_agent.messaging import InMemoryMessageBus, MessageEnvelope

    scope = Scope()
    runtime = LocalEngine(
        SQLiteStore(tmp_path / "runs.db"),
        providers={"default": ScriptedProvider([])},
        tools=ToolRegistry(),
    )
    inbox = SQLiteInbox(tmp_path / "inbox.db")
    dispatcher = EngineCommandDispatcher(
        LocalCommandAdapter(runtime), specs={"test": AgentSpec("a", "x")}
    )

    async def check():
        bus = InMemoryMessageBus()
        await bus.ensure_group(scope, "commands", "g")
        message = MessageEnvelope(
            "submit-one", "commands", {"kind": "submit", "spec": "test", "input": "x"}
        )
        await bus.publish(scope, message)
        old = (await bus.receive(scope, "commands", "g", "dead"))[0]
        inbox.accept(scope, message)
        first = await dispatcher.dispatch(scope, message)
        # Simulated crash window: engine accepted, inbox completion and ack absent.
        replay = (await bus.claim(scope, "commands", "g", "replacement", min_idle_ms=0))[0]
        result = await consume_delivery(bus, inbox, dispatcher, scope, "commands", "g", replay)
        assert replay.broker_id == old.broker_id
        assert result["run_id"] == first["run_id"]
        assert len([e for e in runtime.events(first["run_id"]) if e.kind == "run_submitted"]) == 1
        assert runtime.status(first["run_id"]).state == "queued"  # control is not drive
        assert inbox.result(scope, message.message_id) == result
        assert await bus.claim(scope, "commands", "g", "other", min_idle_ms=0) == []
        assert (
            await consume_delivery(bus, inbox, dispatcher, scope, "commands", "g", replay) == result
        )
        with pytest.raises(ValidationError):
            await dispatcher.dispatch(Scope(principal="other"), message)

    asyncio.run(check())
    inbox.close()
    runtime.close()


def test_inbox_receive_survives_real_process_exit(tmp_path):
    from relf_agent.handoff import SQLiteInbox
    from relf_agent.messaging import MessageEnvelope

    path = tmp_path / "crash.db"
    script = """import os,sys
from relf_agent.handoff import SQLiteInbox
from relf_agent.messaging import MessageEnvelope
from relf_agent.types import Scope
inbox=SQLiteInbox(sys.argv[1])
inbox.accept(Scope(),MessageEnvelope('accepted','commands',{'kind':'cancel','run_id':'run'}))
os._exit(17)
"""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"),
    }
    result = subprocess.run([sys.executable, "-c", script, str(path)], env=env, check=False)
    assert result.returncode == 17
    inbox = SQLiteInbox(path)
    assert [m.message_id for m in inbox.pending(Scope())] == ["accepted"]
    inbox.complete(
        Scope(),
        MessageEnvelope("accepted", "commands", {"kind": "cancel", "run_id": "run"}),
        {"run_id": "run"},
    )
    assert inbox.pending(Scope()) == []
    inbox.close()


def test_dispatch_control_set_and_reject_async_engine_in_sync_adapter(tmp_path):
    from relf_agent.handoff import AsyncCommandAdapter, EngineCommandDispatcher, LocalCommandAdapter
    from relf_agent.messaging import MessageEnvelope

    calls = []

    class Remote:
        scope = Scope()

        async def submit(self, *a, **kw):
            calls.append(("submit", kw))
            return {"run_id": "r"}

        async def approve(self, *a, **kw):
            calls.append(("approve", kw))
            return {"run_id": "r"}

        async def cancel(self, *a, **kw):
            calls.append(("cancel", kw))
            return {"run_id": "r"}

        async def reconcile(self, *a, **kw):
            calls.append(("reconcile", kw))
            return {"run_id": "r"}

    with pytest.raises(ValidationError):
        LocalCommandAdapter(Remote())

    async def check():
        dispatcher = EngineCommandDispatcher(
            AsyncCommandAdapter(Remote()), specs={"a": AgentSpec("a", "x")}
        )
        for i, payload in enumerate(
            (
                {"kind": "submit", "spec": "a", "input": {}},
                {"kind": "approve", "run_id": "r", "action_id": "x", "target_digest": "d"},
                {"kind": "cancel", "run_id": "r"},
                {"kind": "reconcile", "run_id": "r", "action_id": "x", "result": {}},
            )
        ):
            await dispatcher.dispatch(Scope(), MessageEnvelope(str(i), "commands", payload))
        assert [call[0] for call in calls] == ["submit", "approve", "cancel", "reconcile"]
        assert [call[1]["command_id"] for call in calls] == ["0", "1", "2", "3"]
        with pytest.raises(ValidationError):
            await dispatcher.dispatch(
                Scope(),
                MessageEnvelope("bad", "commands", {"kind": "cancel", "run_id": "r", "scope": {}}),
            )

    asyncio.run(check())


def test_result_persistence_failure_never_acknowledges(tmp_path):
    from relf_agent.handoff import (
        EngineCommandDispatcher,
        HandoffError,
        LocalCommandAdapter,
        SQLiteInbox,
        consume_delivery,
    )
    from relf_agent.messaging import InMemoryMessageBus, MessageEnvelope

    class FailingInbox(SQLiteInbox):
        fail = True

        def complete(self, *args):
            if self.fail:
                raise HandoffError("Disk unavailable")
            return super().complete(*args)

    async def check():
        runtime = LocalEngine(
            SQLiteStore(tmp_path / "runs.db"),
            providers={"default": ScriptedProvider([])},
            tools=ToolRegistry(),
        )
        inbox = FailingInbox(tmp_path / "inbox.db")
        dispatcher = EngineCommandDispatcher(
            LocalCommandAdapter(runtime), specs={"a": AgentSpec("a", "x")}
        )
        bus = InMemoryMessageBus()
        await bus.ensure_group(Scope(), "commands", "g")
        await bus.publish(
            Scope(),
            MessageEnvelope("stable", "commands", {"kind": "submit", "spec": "a", "input": {}}),
        )
        delivery = (await bus.receive(Scope(), "commands", "g", "dead"))[0]
        with pytest.raises(HandoffError):
            await consume_delivery(bus, inbox, dispatcher, Scope(), "commands", "g", delivery)
        claimed = (await bus.claim(Scope(), "commands", "g", "recovery", min_idle_ms=0))[0]
        inbox.fail = False
        result = await consume_delivery(bus, inbox, dispatcher, Scope(), "commands", "g", claimed)
        assert (
            len(
                [
                    event
                    for event in runtime.events(result["run_id"])
                    if event.kind == "run_submitted"
                ]
            )
            == 1
        )
        assert await bus.claim(Scope(), "commands", "g", "other", min_idle_ms=0) == []
        inbox.close()
        runtime.close()

    asyncio.run(check())


class ComposedInbox:
    """Third-party port using composition rather than SQLite inheritance."""

    def __init__(self, path):
        from relf_agent.handoff import SQLiteInbox

        self.inner = SQLiteInbox(path)
        self.completions = 0
        self.closed = False

    def accept(self, scope, message):
        return self.inner.accept(scope, message)

    def complete(self, scope, message, result):
        self.inner.complete(scope, message, result)
        self.completions += 1

    def result(self, scope, message_id):
        return self.inner.result(scope, message_id)

    def pending(self, scope, *, limit=100):
        return self.inner.pending(scope, limit=limit)

    def close(self):
        self.inner.close()
        self.closed = True


class ComposedAsyncInbox:
    """Explicit async wrapper retaining the underlying durable implementation."""

    def __init__(self, path):
        self.inner = ComposedInbox(path)
        self.completed = False

    async def accept(self, scope, message):
        await asyncio.sleep(0)
        return self.inner.accept(scope, message)

    async def complete(self, scope, message, result):
        await asyncio.sleep(0)
        self.inner.complete(scope, message, result)
        self.completed = True

    async def result(self, scope, message_id):
        return self.inner.result(scope, message_id)

    async def pending(self, scope, *, limit=100):
        return self.inner.pending(scope, limit=limit)

    async def aclose(self):
        self.inner.close()


@pytest.mark.parametrize("asynchronous", [False, True])
def test_structural_inbox_and_command_adapter_finish_before_ack(tmp_path, asynchronous):
    from relf_agent.handoff import (
        AsyncInbox,
        CommandAdapter,
        EngineCommandDispatcher,
        Inbox,
        consume_delivery,
        validate_inbox,
    )
    from relf_agent.messaging import InMemoryMessageBus, MessageEnvelope

    inbox = (ComposedAsyncInbox if asynchronous else ComposedInbox)(tmp_path / "composed.db")
    invocations = []

    class Adapter:
        scope = Scope()

        async def invoke(self, kind, args, kwargs):
            invocations.append((kind, args, kwargs))
            return {"run_id": "real-authority-receipt", "command_id": kwargs["command_id"]}

    class ObservedBus(InMemoryMessageBus):
        async def ack(self, scope, topic, group, delivery):
            if asynchronous:
                assert inbox.completed
                result = await inbox.result(scope, delivery.message.message_id)
            else:
                assert inbox.completions == 1
                result = inbox.result(scope, delivery.message.message_id)
            assert result["run_id"] == "real-authority-receipt"
            return await super().ack(scope, topic, group, delivery)

    assert isinstance(inbox, AsyncInbox if asynchronous else Inbox)
    assert validate_inbox(inbox) is inbox
    assert isinstance(Adapter(), CommandAdapter)
    dispatcher = EngineCommandDispatcher(Adapter())

    async def check():
        bus = ObservedBus()
        await bus.ensure_group(Scope(), "commands", "g")
        await bus.publish(
            Scope(), MessageEnvelope("stable", "commands", {"kind": "cancel", "run_id": "r"})
        )
        delivery = (await bus.receive(Scope(), "commands", "g", "worker"))[0]
        result = await consume_delivery(bus, inbox, dispatcher, Scope(), "commands", "g", delivery)
        assert result["command_id"] == "stable"
        assert len(invocations) == 1
        assert await bus.claim(Scope(), "commands", "g", "replay", min_idle_ms=0) == []
        assert not (inbox.inner.closed if asynchronous else inbox.closed)
        if asynchronous:
            await inbox.aclose()
        else:
            inbox.close()

    asyncio.run(check())


@pytest.mark.parametrize("lazy", ["coroutine", "generator", "value", "nested_async"])
def test_malformed_structural_inbox_completion_never_acks(tmp_path, lazy):
    from relf_agent.handoff import EngineCommandDispatcher, consume_delivery
    from relf_agent.messaging import InMemoryMessageBus, MessageEnvelope

    entered = []

    async def not_durable():
        entered.append("coroutine-entered")

    def generator():
        entered.append("generator-entered")
        yield None

    if lazy == "nested_async":
        inbox = ComposedAsyncInbox(tmp_path / "bad.db")

        async def complete(*args):
            return not_durable()

        inbox.complete = complete
    else:
        inbox = ComposedInbox(tmp_path / "bad.db")

        def complete(*args):
            if lazy == "coroutine":
                return not_durable()
            if lazy == "generator":
                return generator()
            return {"durable": False}

        inbox.complete = complete

    class Adapter:
        scope = Scope()

        async def invoke(self, *args):
            return {"run_id": "r"}

    async def check():
        bus = InMemoryMessageBus()
        await bus.ensure_group(Scope(), "commands", "g")
        await bus.publish(
            Scope(), MessageEnvelope("stable", "commands", {"kind": "cancel", "run_id": "r"})
        )
        delivery = (await bus.receive(Scope(), "commands", "g", "worker"))[0]
        with pytest.raises(ValidationError, match="complete"):
            await consume_delivery(
                bus, inbox, EngineCommandDispatcher(Adapter()), Scope(), "commands", "g", delivery
            )
        assert entered == []
        assert len(await bus.claim(Scope(), "commands", "g", "recovery", min_idle_ms=0)) == 1
        if lazy == "nested_async":
            await inbox.aclose()
        else:
            inbox.close()

    asyncio.run(check())


def test_structural_ports_reject_mixed_or_fake_async_methods_before_io(tmp_path):
    from relf_agent.handoff import (
        EngineCommandDispatcher,
        Outbox,
        SQLiteOutbox,
        validate_inbox,
        validate_outbox,
    )

    inbox = ComposedInbox(tmp_path / "mixed.db")

    async def async_complete(*args):
        pytest.fail("Mixed inbox reached completion")

    inbox.complete = async_complete
    with pytest.raises(ValidationError, match="Inbox"):
        validate_inbox(inbox)

    class FakeAdapter:
        scope = Scope()

        def invoke(self, *args):
            pytest.fail("Synchronous adapter reached invocation")

    with pytest.raises(ValidationError, match="async"):
        EngineCommandDispatcher(FakeAdapter())
    outbox = SQLiteOutbox(tmp_path / "outbox.db")
    assert isinstance(outbox, Outbox)
    assert validate_outbox(outbox) is outbox
    inbox.close()
    outbox.close()


@pytest.mark.parametrize("asynchronous", [False, True])
def test_composed_outbox_ports_retain_identity_and_publish_once(tmp_path, asynchronous):
    from relf_agent.handoff import AsyncOutbox, Outbox, SQLiteOutbox, flush_outbox, validate_outbox
    from relf_agent.messaging import InMemoryMessageBus, MessageEnvelope

    inner = SQLiteOutbox(tmp_path / "outbox.db")

    class SyncWrapper:
        def enqueue(self, scope, message):
            return inner.enqueue(scope, message)

        def pending(self, scope, *, limit=100):
            return inner.pending(scope, limit=limit)

        def result(self, scope, message_id):
            return inner.result(scope, message_id)

        async def flush(self, bus, scope, *, limit=100):
            return await inner.flush(bus, scope, limit=limit)

        def close(self):
            inner.close()

    class AsyncWrapper:
        async def enqueue(self, scope, message):
            return inner.enqueue(scope, message)

        async def pending(self, scope, *, limit=100):
            return inner.pending(scope, limit=limit)

        async def result(self, scope, message_id):
            return inner.result(scope, message_id)

        async def flush(self, bus, scope, *, limit=100):
            return await inner.flush(bus, scope, limit=limit)

        async def aclose(self):
            inner.close()

    wrapper = AsyncWrapper() if asynchronous else SyncWrapper()
    assert isinstance(wrapper, AsyncOutbox if asynchronous else Outbox)
    assert validate_outbox(wrapper) is wrapper

    async def check():
        message = MessageEnvelope("stable", "commands", {})
        if asynchronous:
            assert await wrapper.enqueue(Scope(), message) == "stable"
        else:
            assert wrapper.enqueue(Scope(), message) == "stable"
        bus = InMemoryMessageBus()
        await bus.ensure_group(Scope(), "commands", "g")
        assert await flush_outbox(wrapper, bus, Scope()) == 1
        assert await flush_outbox(wrapper, bus, Scope()) == 0
        deliveries = await bus.receive(Scope(), "commands", "g", "reader", limit=10)
        assert [item.message.message_id for item in deliveries] == ["stable"]
        if asynchronous:
            await wrapper.aclose()
        else:
            wrapper.close()

    asyncio.run(check())


def test_custom_command_adapter_scope_drift_and_nested_lazy_receipt_are_rejected():
    from relf_agent.handoff import EngineCommandDispatcher
    from relf_agent.messaging import MessageEnvelope

    entered = []

    async def delayed():
        entered.append("entered")
        return {"run_id": "r"}

    class Adapter:
        scope = Scope()

        async def invoke(self, *args):
            return delayed()

    adapter = Adapter()
    dispatcher = EngineCommandDispatcher(adapter)
    message = MessageEnvelope("stable", "commands", {"kind": "cancel", "run_id": "r"})

    async def check():
        with pytest.raises(ValidationError, match="completed"):
            await dispatcher.dispatch(Scope(), message)
        assert entered == []
        adapter.scope = Scope(principal="different")
        with pytest.raises(ValidationError, match="Scope"):
            await dispatcher.dispatch(adapter.scope, message)

    asyncio.run(check())
