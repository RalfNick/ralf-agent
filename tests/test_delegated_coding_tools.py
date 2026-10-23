import asyncio
import copy

import pytest

from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.executors import DispatchEnvelope, PythonToolExecutor
from relf_agent.tools import ToolRegistry, ToolSpec
from relf_agent.types import InvocationContext, Scope


class Runner:
    identity = {"kind": "fixture-runner", "version": "1"}
    active_operations = 0

    async def execute(self, envelope, authority):
        raise AssertionError("The ordinary executor must not start native work")

    async def reconcile(self, envelope, authority):
        raise AssertionError("The ordinary executor must not query native work")

    async def stop_existing(self, envelope, authority):
        return None

    async def aclose(self, *, wait_timeout=30):
        return None


def helper():
    from relf_agent import delegated_coding

    return delegated_coding


def test_native_wrapper_requires_completed_async_lifecycle_and_detached_identity():
    module = helper()
    runner = Runner()
    handler = module.CodingToolHandler(runner)
    assert handler.runner is runner
    snapshot = handler.identity
    snapshot["version"] = "changed"
    assert handler.identity == Runner.identity
    runner.identity = {"kind": "replaced", "version": "1"}
    with pytest.raises(DefinitionMismatch):
        handler.check()
    with pytest.raises(DefinitionMismatch):
        _ = handler.runner


def test_method_replacement_is_rejected_before_generic_or_native_dispatch():
    module = helper()
    runner = Runner()
    handler = module.CodingToolHandler(runner)

    async def changed(envelope, authority):
        return None

    runner.execute = changed
    with pytest.raises(DefinitionMismatch):
        handler.check()


def test_missing_and_lazy_lifecycle_cannot_register():
    module = helper()
    with pytest.raises(ValidationError):
        module.CodingToolHandler(object())
    runner = Runner()
    runner.execute = lambda *args: None
    with pytest.raises(ValidationError):
        module.CodingToolHandler(runner)


def test_ordinary_callable_cannot_add_a_delegated_marker():
    registry = ToolRegistry()
    spec = ToolSpec(
        "pretend",
        "invalid native marker",
        {"type": "object"},
        effect="queryable_write",
        requires_approval=True,
        config={"delegated_runner": {"version": 1, "runner": Runner.identity}},
    )
    with pytest.raises(ValidationError):
        registry.register(spec, lambda args, context: {"done": True})


def test_wrapper_cannot_be_registered_without_approval_or_its_exact_manifest():
    module = helper()
    handler = module.CodingToolHandler(Runner())
    for effect, approval, config in [
        ("read_only", True, {"delegated_runner": {"version": 1, "runner": handler.identity}}),
        (
            "queryable_write",
            False,
            {"delegated_runner": {"version": 1, "runner": handler.identity}},
        ),
        ("queryable_write", True, {}),
        ("queryable_write", True, {"delegated_runner": {"version": 1, "runner": {"other": True}}}),
    ]:
        with pytest.raises(ValidationError):
            ToolRegistry().register(
                ToolSpec(
                    "coding",
                    "coding",
                    copy.deepcopy(module.CODING_INPUT_SCHEMA),
                    effect=effect,
                    requires_approval=approval,
                    config=config,
                ),
                handler,
            )


def test_generic_executor_and_direct_handler_reject_even_a_valid_envelope():
    module = helper()
    registry = ToolRegistry()
    handler = module.register_coding_tool(registry, Runner())
    tool = registry.get("coding")
    assert module.registered_coding_tool(tool) is handler
    envelope = DispatchEnvelope(
        InvocationContext(Scope(), "run", "action", "attempt", "effect", "epoch"),
        tool.manifest,
        {"task": "write a small module"},
        "operation",
    )
    with pytest.raises(AuthorizationDenied):
        handler(envelope.arguments, envelope.context)

    async def scenario():
        executor = PythonToolExecutor(registry)
        with pytest.raises(AuthorizationDenied):
            await executor.execute(envelope)
        with pytest.raises(AuthorizationDenied):
            await executor.reconcile(envelope)

    asyncio.run(scenario())


def test_coding_registration_supports_custom_registry_subclasses():
    class CustomRegistry(ToolRegistry):
        pass

    registry = CustomRegistry()
    handler = helper().register_coding_tool(registry, Runner())
    assert helper().registered_coding_tool(registry.get("coding")) is handler
