import asyncio
import importlib.util

from ralf_agent import Scope


def test_default_bus_delivers_once_per_acknowledged_group():
    assert importlib.util.find_spec("ralf_agent.messaging"), "Missing MessageBus defaults"
    from ralf_agent.messaging import InMemoryMessageBus, MessageEnvelope

    async def scenario():
        bus = InMemoryMessageBus()
        scope = Scope()
        await bus.ensure_group(scope, "commands", "workers")
        identity = await bus.publish(
            scope, MessageEnvelope("first", "commands", {"command": "test"})
        )
        deliveries = await bus.receive(scope, "commands", "workers", "worker-1", limit=1)
        assert len(deliveries) == 1 and deliveries[0].broker_id == identity
        assert deliveries[0].message.payload == {"command": "test"}
        await bus.ack(scope, "commands", "workers", deliveries[0])
        assert await bus.receive(scope, "commands", "workers", "worker-1", limit=1) == []

    asyncio.run(scenario())
