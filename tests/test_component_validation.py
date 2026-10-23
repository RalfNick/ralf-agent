"""Local, Temporal and component assembly enforce the same pure port checks."""

import asyncio
from types import SimpleNamespace

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolRegistry
from relf_agent.binding_catalog import component_identity as binding_identity
from relf_agent.context import ContextAssembler
from relf_agent.errors import ValidationError
from relf_agent.runtime_builder import ComponentRegistry, RuntimeBuilder
from relf_agent.runtime_config import RuntimeProfile
from relf_agent.temporal_activities import component_identity as temporal_identity


class AsyncComplete:
    async def __call__(self, messages, tools):
        return ModelResponse(output="completed")


class CallableProvider:
    identity = {"kind": "callable-provider", "version": "1", "config": {"labels": ["a"]}}
    complete = AsyncComplete()


def local_identity(component):
    return LocalEngine._component_identity(component, ("complete",), False, "Provider")


@pytest.mark.parametrize("validate", [local_identity, temporal_identity, binding_identity])
def test_async_callable_provider_is_validated_without_invocation(validate):
    provider = CallableProvider()
    if validate is binding_identity:
        result = validate("provider", provider)
    elif validate is temporal_identity:
        result = validate(provider, ("complete",))
    else:
        result = validate(provider)
    assert result == {"kind": "callable-provider", "version": "1", "config": {"labels": ["a"]}}
    result["config"]["labels"].append("local-mutation")
    assert provider.identity["config"]["labels"] == ["a"]


@pytest.mark.parametrize("assembled", [False, True])
def test_callable_provider_completes_through_direct_and_registered_local_paths(tmp_path, assembled):
    if assembled:
        registry = ComponentRegistry()
        registry.register(
            "provider", "callable-provider", lambda config, context: CallableProvider()
        )
        profile = RuntimeProfile(
            name="callable", version="1", providers={"default": {"adapter": "callable-provider"}}
        )
        runtime = RuntimeBuilder(registry).build(profile, tmp_path / "assembled.sqlite")
    else:
        runtime = LocalEngine(
            SQLiteStore(tmp_path / "direct.sqlite"),
            providers={"default": CallableProvider()},
            tools=ToolRegistry(),
        )
    with runtime:
        run = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="callable")
        result = asyncio.run(runtime.drive(run.run_id))
        assert result.state == "succeeded"
        assert result.result == "completed"


def test_callable_provider_completes_through_async_registered_assembly(tmp_path):
    async def scenario():
        registry = ComponentRegistry()

        async def factory(config, context):
            return CallableProvider()

        registry.register_async("provider", "callable-provider", factory)
        profile = RuntimeProfile(
            name="callable", version="1", providers={"default": {"adapter": "callable-provider"}}
        )
        async with await RuntimeBuilder(registry).abuild(
            profile, tmp_path / "async.sqlite"
        ) as runtime:
            run = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="async-callable")
            result = await runtime.drive(run.run_id)
            assert result.state == "succeeded"
            assert result.result == "completed"

    asyncio.run(scenario())


@pytest.mark.parametrize("validate", [local_identity, temporal_identity])
def test_identity_property_errors_are_configuration_errors(validate):
    class BrokenProvider:
        complete = AsyncComplete()

        @property
        def identity(self):
            raise RuntimeError("unavailable identity")

    with pytest.raises(ValidationError):
        if validate is temporal_identity:
            validate(BrokenProvider(), ("complete",))
        else:
            validate(BrokenProvider())


@pytest.mark.parametrize("identity", [None, {}, [], {"invalid": float("nan")}])
@pytest.mark.parametrize("validate", [local_identity, temporal_identity])
def test_invalid_identity_is_rejected_before_any_component_call(validate, identity):
    provider = SimpleNamespace(identity=identity, complete=AsyncComplete())
    with pytest.raises(ValidationError):
        if validate is temporal_identity:
            validate(provider, ("complete",))
        else:
            validate(provider)


def synchronous(*args):
    raise AssertionError("validation must not execute methods")


def generator(*args):
    yield None


async def async_generator(*args):
    yield None


@pytest.mark.parametrize("method", [synchronous, generator, async_generator, None])
@pytest.mark.parametrize("validate", [local_identity, temporal_identity])
def test_non_coroutine_complete_is_rejected_without_execution(validate, method):
    provider = SimpleNamespace(identity={"kind": "invalid-provider"}, complete=method)
    with pytest.raises(ValidationError):
        if validate is temporal_identity:
            validate(provider, ("complete",))
        else:
            validate(provider)


@pytest.mark.parametrize("method", [synchronous, AsyncComplete(), generator, async_generator])
@pytest.mark.parametrize("backend", ["local", "temporal"])
def test_pure_sync_ports_reject_lazy_methods_without_entering_them(backend, method):
    component = SimpleNamespace(identity={"kind": "pure-policy"}, assemble=method)
    if method is synchronous:
        if backend == "local":
            result = LocalEngine._component_identity(component, ("assemble",), True, "Context")
        else:
            result = temporal_identity(component, ("assemble",), synchronous=True)
        assert result == {"kind": "pure-policy"}
    else:
        with pytest.raises(ValidationError):
            if backend == "local":
                LocalEngine._component_identity(component, ("assemble",), True, "Context")
            else:
                temporal_identity(component, ("assemble",), synchronous=True)


@pytest.mark.parametrize("method", [AsyncComplete(), generator, async_generator])
@pytest.mark.parametrize("assembled", [False, True])
def test_lazy_context_is_rejected_by_public_construction_paths(tmp_path, method, assembled):
    context = SimpleNamespace(identity={"kind": "invalid-context"}, assemble=method)
    path = tmp_path / "invalid-context.sqlite"
    if assembled:
        registry = ComponentRegistry()
        registry.register("context_assembler", "invalid-context", lambda config, owner: context)
        profile = RuntimeProfile(
            name="invalid-context",
            version="1",
            providers={"default": {"adapter": "offline-echo"}},
            components={"context_assembler": {"adapter": "invalid-context"}},
        )
        with pytest.raises(ValidationError):
            with RuntimeBuilder(registry).build(profile, path):
                pass
    else:
        with SQLiteStore(path) as store:
            with pytest.raises(ValidationError):
                with LocalEngine(
                    store, providers={}, tools=ToolRegistry(), context_assembler=context
                ):
                    pass
    with SQLiteStore(path) as store:
        assert store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        lease = store.create_coordinator()
        lease.acquire()
        lease.release()


@pytest.mark.parametrize("method", [AsyncComplete(), generator, async_generator])
def test_context_shape_change_before_submit_does_not_accept_a_run(tmp_path, method):
    context = ContextAssembler()
    with LocalEngine(
        SQLiteStore(tmp_path / "changed-context.sqlite"),
        providers={"default": CallableProvider()},
        tools=ToolRegistry(),
        context_assembler=context,
    ) as engine:
        context.assemble = method
        with pytest.raises(ValidationError):
            engine.submit(AgentSpec("a", "Answer"), "q", command_id="invalid-context")
        assert engine.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
