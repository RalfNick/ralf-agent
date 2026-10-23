import asyncio
from functools import partial

from relf_agent import Scope, ToolRegistry, ToolSpec
from relf_agent.tools import invoke
from relf_agent.types import InvocationContext, digest


def test_registered_spec_and_manifest_are_defensive_snapshots():
    def handler(arguments, context):
        return arguments

    registry = ToolRegistry()
    original = ToolSpec(
        "lookup",
        "Lookup",
        {"type": "object", "properties": {"id": {"type": "integer"}}},
        config={"endpoint": {"name": "approved"}},
    )
    registry.register(original, handler)
    pinned = registry.manifests(["lookup"])
    view = registry.get("lookup")
    view.spec.config["endpoint"]["name"] = "changed"
    view.spec.input_schema["properties"]["id"]["type"] = "string"
    view.manifest["config"]["endpoint"]["name"] = "changed-again"
    original.config["endpoint"]["name"] = "original-changed"
    assert registry.manifests(["lookup"]) == pinned
    registry.get("lookup").validate({"id": 1})


def test_stateful_callables_use_declared_version_and_configuration():
    class Lookup:
        def __init__(self, value):
            self.value = value

        async def __call__(self, arguments, context):
            return {"value": self.value}

        def method(self, arguments, context):
            return {"value": self.value}

    def lookup(arguments, context, *, value):
        return {"value": value}

    handlers = (Lookup(1), Lookup(2).method, partial(lookup, value=3))
    registry = ToolRegistry()
    for index, handler in enumerate(handlers, 1):
        registry.register(
            ToolSpec(
                f"lookup{index}",
                "Lookup",
                {"type": "object"},
                version="lookup-v2",
                config={"value": index},
            ),
            handler,
        )

    async def exercise():
        context = InvocationContext(Scope(), "run", "action", "attempt", "effect", "epoch")
        for index in range(1, 4):
            registered = registry.get(f"lookup{index}")
            assert await invoke(registered.handler, {}, context) == {"value": index}
            assert registered.manifest["version"] == "lookup-v2"
            assert registered.manifest["config"] == {"value": index}

    asyncio.run(exercise())

    first = ToolRegistry()
    second = ToolRegistry()
    for target, value in ((first, 1), (second, 2)):
        target.register(
            ToolSpec("lookup", "Lookup", {"type": "object"}, config={"value": value}),
            Lookup(value),
        )
    assert digest(first.manifests(["lookup"])) != digest(second.manifests(["lookup"]))


def test_callable_reconciler_is_supported():
    class Reconciler:
        def __call__(self, arguments, context):
            return None

    def handler(arguments, context):
        return arguments

    registry = ToolRegistry()
    registry.register(
        ToolSpec("lookup", "Lookup", {"type": "object"}, version="v2"),
        handler,
        reconciler=Reconciler(),
    )
    assert registry.get("lookup").reconciler is not None
