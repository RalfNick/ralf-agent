import asyncio

import pytest

from ralf_agent.errors import IdempotencyConflict, ValidationError
from ralf_agent.types import Scope

from . import test_redis_memory_adapter as redis_test_helpers

redis_service = redis_test_helpers.redis_service


def test_memory_bus_dedup_claim_binding_and_capacity():
    from ralf_agent.messaging import InMemoryMessageBus, MessageBusError, MessageEnvelope

    async def check():
        bus = InMemoryMessageBus(max_entries=1)
        scope = Scope()
        msg = MessageEnvelope("stable", "commands", {"n": 9007199254740997})
        await bus.ensure_group(scope, "commands", "workers")
        first = await bus.publish(scope, msg)
        assert await bus.publish(scope, msg) == first
        with pytest.raises(IdempotencyConflict):
            await bus.publish(scope, MessageEnvelope("stable", "commands", {}))
        with pytest.raises(MessageBusError):
            await bus.publish(scope, MessageEnvelope("second", "commands", {}))
        old = (await bus.receive(scope, "commands", "workers", "one"))[0]
        new = (await bus.claim(scope, "commands", "workers", "two", min_idle_ms=0))[0]
        assert old.broker_id == new.broker_id
        assert await bus.ack(scope, "commands", "workers", old) == 0
        with pytest.raises(ValidationError):
            await bus.ack(Scope(principal="other"), "commands", "workers", new)
        assert await bus.ack(scope, "commands", "workers", new) == 1
        assert await bus.claim(scope, "commands", "workers", "three", min_idle_ms=0) == []
        assert await bus.ack(scope, "commands", "workers", new) == 0
        await bus.aclose()
        with pytest.raises(MessageBusError):
            await bus.publish(scope, msg)

    asyncio.run(check())


@pytest.mark.parametrize("decode", [False, True])
def test_real_redis_pel_claim_group_scope_and_dedup(redis_service, decode):
    from redis.asyncio import Redis

    from ralf_agent.messaging import MessageBusError, MessageEnvelope
    from ralf_agent.redis_streams import RedisStreamsBus

    async def check():
        client = Redis.from_url(redis_service, decode_responses=decode)
        bus = RedisStreamsBus(client, backend_id="test", prefix=f"test:{decode}", max_entries=1)
        scope = Scope("工作区{A}", "owner")
        try:
            await bus.ensure_group(scope, "commands", "g")
            await bus.ensure_group(scope, "commands", "g")
            message = MessageEnvelope("稳定", "commands", {"n": 9007199254740997, "text": "你好"})
            identity = await bus.publish(scope, message)
            assert await bus.publish(scope, message) == identity
            with pytest.raises(IdempotencyConflict):
                await bus.publish(scope, MessageEnvelope("稳定", "commands", {"changed": True}))
            with pytest.raises(MessageBusError):
                await bus.publish(scope, MessageEnvelope("other", "commands", {}))
            delivery = (await bus.receive(scope, "commands", "g", "dead-worker"))[0]
            assert delivery.message.payload == message.payload
            assert await bus.receive(scope, "commands", "g", "other") == []
            claimed = (await bus.claim(scope, "commands", "g", "replacement", min_idle_ms=0))[0]
            assert claimed.broker_id == identity
            assert await bus.ack(scope, "commands", "g", delivery) == 0
            assert await bus.ack(scope, "commands", "g", claimed) == 1
            assert await bus.claim(scope, "commands", "g", "replacement", min_idle_ms=0) == []
            await bus.ensure_group(scope, "commands", "independent")
            assert len(await bus.receive(scope, "commands", "independent", "reader")) == 1
            other = Scope(scope.workspace, "other")
            await bus.ensure_group(other, "commands", "g")
            assert await bus.receive(other, "commands", "g", "reader") == []
            await bus.aclose()
            assert await client.ping()  # borrowed client remains alive
        finally:
            await client.aclose()

    asyncio.run(check())


def test_owned_close_retries_and_errors_are_safe():
    from ralf_agent.messaging import MessageBusError
    from ralf_agent.redis_streams import RedisStreamsBus

    class Client:
        closed = 0

        async def eval(self, *args):
            raise RuntimeError("password-secret")

        async def aclose(self):
            self.closed += 1
            if self.closed == 1:
                raise RuntimeError("password-secret")

    async def check():
        client = Client()
        bus = RedisStreamsBus(client, backend_id="test", owns_client=True)
        with pytest.raises(MessageBusError, match="operation failed") as error:
            await bus.publish(
                Scope(),
                __import__("ralf_agent.messaging", fromlist=["MessageEnvelope"]).MessageEnvelope(
                    "m", "t", {}
                ),
            )
        assert "secret" not in str(error.value)
        with pytest.raises(MessageBusError, match="close failed"):
            await bus.aclose()
        await bus.aclose()
        await bus.aclose()
        assert client.closed == 2

    asyncio.run(check())


def test_envelope_rejects_unsafe_and_oversized_json():
    from ralf_agent.messaging import MessageEnvelope

    for payload in ({"n": float("nan")}, {"text": "\ud800"}, {"text": "x" * 262145}):
        with pytest.raises(ValidationError):
            MessageEnvelope("id", "topic", payload)
    payload = {"items": []}
    message = MessageEnvelope("id", "topic", payload)
    payload["items"].append("changed")
    message.payload["items"].append("other")
    assert message.payload == {"items": []}


def test_real_redis_process_crash_after_engine_acceptance_replays_once(redis_service, tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from ralf_agent import AgentSpec, LocalEngine, ToolRegistry
    from ralf_agent.handoff import (
        EngineCommandDispatcher,
        LocalCommandAdapter,
        SQLiteInbox,
        consume_delivery,
    )
    from ralf_agent.messaging import MessageEnvelope
    from ralf_agent.redis_streams import RedisStreamsBus
    from ralf_agent.storage import SQLiteStore

    from .helpers import ScriptedProvider

    async def seed():
        bus = await RedisStreamsBus.connect(redis_service, backend_id="crash", prefix="crash")
        await bus.ensure_group(Scope(), "commands", "g")
        await bus.publish(
            Scope(),
            MessageEnvelope(
                "submit-stable", "commands", {"kind": "submit", "spec": "a", "input": {}}
            ),
        )
        await bus.aclose()

    asyncio.run(seed())
    script = """import asyncio,os,sys
from pathlib import Path
from ralf_agent import AgentSpec,LocalEngine,ToolRegistry,Scope
from ralf_agent.handoff import SQLiteInbox,EngineCommandDispatcher,LocalCommandAdapter
from ralf_agent.redis_streams import RedisStreamsBus
from ralf_agent.storage import SQLiteStore
class Provider:
 identity={'kind':'unused','version':'1'}
 async def complete(self,messages,tools): pass
async def main():
 directory=Path(sys.argv[2])
 bus=await RedisStreamsBus.connect(sys.argv[1],backend_id='crash',prefix='crash')
 delivery=(await bus.receive(Scope(),'commands','g','dead'))[0]
 inbox=SQLiteInbox(directory/'inbox.db')
 inbox.accept(Scope(),delivery.message)
 runtime=LocalEngine(SQLiteStore(directory/'runs.db'),providers={'default':Provider()},tools=ToolRegistry())
 dispatcher=EngineCommandDispatcher(LocalCommandAdapter(runtime),specs={'a':AgentSpec('a','x')})
 await dispatcher.dispatch(Scope(),delivery.message)
 os._exit(41)
asyncio.run(main())
"""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    result = subprocess.run(
        [sys.executable, "-c", script, redis_service, str(tmp_path)],
        env=env,
        check=False,
        timeout=10,
    )
    assert result.returncode == 41
    runtime = LocalEngine(
        SQLiteStore(tmp_path / "runs.db"),
        providers={"default": ScriptedProvider([])},
        tools=ToolRegistry(),
    )
    inbox = SQLiteInbox(tmp_path / "inbox.db")
    dispatcher = EngineCommandDispatcher(
        LocalCommandAdapter(runtime), specs={"a": AgentSpec("a", "x")}
    )

    async def recover():
        bus = await RedisStreamsBus.connect(redis_service, backend_id="crash", prefix="crash")
        try:
            delivery = (await bus.claim(Scope(), "commands", "g", "replacement", min_idle_ms=0))[0]
            result = await consume_delivery(
                bus, inbox, dispatcher, Scope(), "commands", "g", delivery
            )
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
            assert await bus.claim(Scope(), "commands", "g", "another", min_idle_ms=0) == []
        finally:
            await bus.aclose()

    asyncio.run(recover())
    inbox.close()
    runtime.close()


def test_real_redis_concurrent_publish_and_idle_claim(redis_service):
    from ralf_agent.messaging import MessageEnvelope
    from ralf_agent.redis_streams import RedisStreamsBus

    async def check():
        bus = await RedisStreamsBus.connect(redis_service, backend_id="race", prefix="race")
        try:
            message = MessageEnvelope("stable", "commands", {"value": 1})
            identities = await asyncio.gather(*[bus.publish(Scope(), message) for _ in range(20)])
            assert len(set(identities)) == 1
            await bus.ensure_group(Scope(), "commands", "g")
            delivery = (await bus.receive(Scope(), "commands", "g", "active"))[0]
            assert await bus.claim(Scope(), "commands", "g", "new", min_idle_ms=10000) == []
            assert await bus.ack(Scope(), "commands", "g", delivery) == 1
        finally:
            await bus.aclose()

    asyncio.run(check())


def test_real_connect_timeout_overrides_url_query(redis_service):
    import time

    from redis.asyncio import Redis

    from ralf_agent.messaging import MessageBusError
    from ralf_agent.redis_streams import RedisStreamsBus

    async def check():
        client = Redis.from_url(redis_service)
        try:
            await client.execute_command("CLIENT", "PAUSE", 400, "ALL")
            start = time.monotonic()
            with pytest.raises(MessageBusError, match="connection failed"):
                await RedisStreamsBus.connect(
                    redis_service + "?socket_timeout=10&socket_connect_timeout=10",
                    backend_id="paused",
                    timeout=0.03,
                )
            assert time.monotonic() - start < 0.25
        finally:
            await client.aclose()

    asyncio.run(check())


def test_real_outbox_crash_after_publish_before_mark_replays_one_entry(redis_service, tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from ralf_agent.handoff import SQLiteOutbox
    from ralf_agent.redis_streams import RedisStreamsBus

    script = """import asyncio,os,sys
from ralf_agent import Scope
from ralf_agent.handoff import SQLiteOutbox
from ralf_agent.messaging import MessageEnvelope
from ralf_agent.redis_streams import RedisStreamsBus
async def main():
 outbox=SQLiteOutbox(sys.argv[2])
 outbox.enqueue(Scope(),MessageEnvelope('outbox-stable','commands',{'kind':'submit','spec':'a','input':{}}))
 bus=await RedisStreamsBus.connect(sys.argv[1],backend_id='outbox',prefix='outbox-crash')
 class CrashAfterPublish:
  async def publish(self,scope,message):
   await bus.publish(scope,message)
   os._exit(42)
 await outbox.flush(CrashAfterPublish(),Scope())
asyncio.run(main())
"""
    path = tmp_path / "outbox.db"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    result = subprocess.run(
        [sys.executable, "-c", script, redis_service, str(path)], env=env, check=False, timeout=10
    )
    assert result.returncode == 42
    outbox = SQLiteOutbox(path)
    assert [message.message_id for message in outbox.pending(Scope())] == ["outbox-stable"]

    async def check():
        bus = await RedisStreamsBus.connect(
            redis_service, backend_id="outbox", prefix="outbox-crash"
        )
        try:
            assert await outbox.flush(bus, Scope()) == 1
            await bus.ensure_group(Scope(), "commands", "g")
            deliveries = await bus.receive(Scope(), "commands", "g", "reader", limit=10)
            assert [item.message.message_id for item in deliveries] == ["outbox-stable"]
            assert await outbox.flush(bus, Scope()) == 0
        finally:
            await bus.aclose()

    asyncio.run(check())
    outbox.close()
