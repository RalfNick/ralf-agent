"""Complete session history follows original sync/async component assembly."""

import asyncio

import pytest

import ralf_agent
from ralf_agent import CompleteModelHistory, RuntimeBuilder, RuntimeProfile
from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection
from ralf_agent.errors import ValidationError
from ralf_agent.runtime_builder import ComponentRegistry
from ralf_agent.temporal_builder import TemporalRuntimeBuilder
from ralf_agent.temporal_profile import TemporalProfile

PROVIDERS = {"default": {"adapter": "offline-echo"}}


def history_declaration(scope="session"):
    return {"adapter": "complete", "config": {"scope": scope}}


def binding(scope="session"):
    return {
        "role": "model_history",
        "component_id": "native",
        "version": "2",
        "component": history_declaration(scope),
    }


@pytest.mark.parametrize("asynchronous", [False, True])
def test_local_complete_session_configuration_builds_default_and_borrowed_selection(
    tmp_path,
    asynchronous,
):
    profile = RuntimeProfile(
        "history",
        "1",
        PROVIDERS,
        {
            "model_continuation": {"adapter": "native"},
            "model_history": history_declaration(),
        },
        binding_components=[binding("run")],
    )

    def check(instance):
        assert instance.model_history.identity["scope"] == "session"
        choice = AgentBindingDescriptor(model_history=BindingSelection.ref("native", "2"))
        selected, record = instance.binding_catalog.resolve(
            "model_history", choice.model_history, instance.scope
        )
        assert "scope" not in selected.identity
        assert record["identity"]["identity"]["version"] == "1"

    async def run():
        instance = await RuntimeBuilder().abuild(profile, tmp_path / "runs.sqlite")
        try:
            check(instance)
        finally:
            await instance.aclose()

    if asynchronous:
        asyncio.run(run())
    else:
        with RuntimeBuilder().build(profile, tmp_path / "runs.sqlite") as instance:
            check(instance)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_binding_history_without_continuation_refuses_before_store_creation(tmp_path, asynchronous):
    profile = RuntimeProfile("history", "1", PROVIDERS, binding_components=[binding("run")])
    path = tmp_path / "not-created.sqlite"
    with pytest.raises(ValidationError, match="continuation"):
        if asynchronous:
            asyncio.run(RuntimeBuilder().abuild(profile, path))
        else:
            RuntimeBuilder().build(profile, path)
    assert not path.exists()


@pytest.mark.parametrize("scope", [None, False, "conversation", 1, []])
def test_invalid_complete_scope_refuses_before_store_creation(tmp_path, scope):
    profile = RuntimeProfile(
        "history",
        "1",
        PROVIDERS,
        {
            "model_continuation": {"adapter": "native"},
            "model_history": history_declaration(scope),
        },
    )
    path = tmp_path / "not-created.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile, path)
    assert not path.exists()


def test_session_history_unknown_custom_authority_requires_a_declared_source(tmp_path):
    def unsupported_store(path):
        raise AssertionError("invalid source must fail before creating the execution authority")

    profile = RuntimeProfile(
        "history",
        "1",
        PROVIDERS,
        {
            "model_continuation": {"adapter": "native"},
            "model_history": history_declaration(),
        },
    )
    with pytest.raises(ValidationError, match="Session"):
        RuntimeBuilder(store_factory=unsupported_store).build(profile, tmp_path / "absent.sqlite")


def test_temporal_binding_history_also_requires_explicit_continuation():
    with pytest.raises(ValidationError, match="continuation"):
        TemporalProfile("history", "1", PROVIDERS, binding_components=[binding("run")])


def test_temporal_session_history_requires_a_session_source_or_original_history():
    with pytest.raises(ValidationError, match="Session"):
        TemporalProfile(
            "history",
            "1",
            PROVIDERS,
            {"model_history": history_declaration()},
            execution={"model_continuation": True},
        )


@pytest.mark.parametrize("external", [False, True])
def test_temporal_session_configuration_uses_history_or_explicit_session_source(tmp_path, external):
    components = {"model_history": history_declaration()}
    if external:
        components["session_store"] = {"adapter": "in-memory"}
    profile = TemporalProfile(
        "history",
        "1",
        PROVIDERS,
        components,
        execution={"model_continuation": True, "enable_sessions": not external},
    )

    async def run():
        assembly = await TemporalRuntimeBuilder().abuild(profile, data_path=tmp_path / "data")
        try:
            assert assembly._runtime.model_history.identity["scope"] == "session"
        finally:
            await assembly.aclose()

    asyncio.run(run())


def test_async_custom_binding_history_uses_existing_owned_resource_lifetime(tmp_path):
    events = []
    registry = ComponentRegistry()

    class Resource:
        async def aclose(self):
            events.append("owned")

    class BorrowedHistory(CompleteModelHistory):
        def close(self):
            events.append("borrowed")

    async def construct(config, context):
        context.own_async(Resource())
        return BorrowedHistory()

    registry.register_async("model_history", "business", construct)
    declaration = binding("run")
    declaration["component"] = {"adapter": "business"}
    profile = RuntimeProfile(
        "history",
        "1",
        PROVIDERS,
        {"model_continuation": {"adapter": "native"}},
        binding_components=[declaration],
    )

    async def run():
        instance = await RuntimeBuilder(registry).abuild(profile, tmp_path / "runs.sqlite")
        await instance.aclose()

    asyncio.run(run())
    assert events == ["owned"]


def test_sdk_exports_native_history_helpers_for_replacement_components():
    assert ralf_agent.native_history_address("a" * 64) == "ralf-native-model-history-v1:" + "a" * 64
    for name in (
        "native_history_envelope",
        "validate_native_history_envelope",
        "validate_model_history_frame",
        "read_native_history",
    ):
        assert callable(getattr(ralf_agent, name))
