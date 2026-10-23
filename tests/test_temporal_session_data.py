import asyncio
from dataclasses import asdict

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    InMemoryMemory,
    Scope,
    SessionBindingResource,
    ToolRegistry,
)
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_bindings import normalize_request
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import submission_request

from .test_temporal_facts import Provider


def setup(*, selected="ref", backend=None, managed=False):
    from relf_agent import ManagedContextPipeline

    scope = Scope("sessions", "alice")
    backend = backend or InMemoryMemory(backend_id="session-source")
    catalog = BindingCatalog(scope=scope)
    catalog.register(
        "session",
        "private",
        "1",
        SessionBindingResource(backend, namespaces=("red",), default_namespace="red"),
    )
    provider = Provider()
    runtime = TemporalRuntime(
        providers={"default": provider},
        tools=ToolRegistry(),
        binding_catalog=catalog,
        context_builder=ManagedContextPipeline() if managed else None,
    )
    choice = (
        BindingSelection.ref("private", "1") if selected == "ref" else BindingSelection.disabled()
    )
    definition = AgentDefinition(AgentSpec("a", "Answer"), AgentBindingDescriptor(session=choice))
    state = TemporalRunState(
        "run",
        asdict(scope),
        "command",
        normalize_request(submission_request(definition, "task")),
        runtime.manifest,
    )
    return runtime, state, backend, provider, scope


def test_session_role_registers_an_opt_in_fixed_read_protocol():
    runtime, state, _, _, _ = setup()
    assert runtime.manifest["session_data_protocol"] == 1
    assert runtime.capabilities["session_data_reads"]
    assert not runtime.capabilities["external_session_store"]
    assert state.step_manifest["session_data"]["identity"]["kind"] == "session-binding-resource"


def test_scoped_read_is_bounded_does_not_call_full_read(monkeypatch):
    from relf_agent.temporal_session_data import private_address

    async def run():
        runtime, state, backend, _, scope = setup()
        address = (
            SessionBindingResource(backend, namespaces=("red",), default_namespace="red")
            .select({}, scope)
            .storage_key(private_address("run", 0))
        )
        backend.append(
            scope,
            address,
            {"role": "assistant", "task": "previous", "content": "visible"},
            expected_revision=0,
            message_id="m",
        )
        backend.append(
            Scope("sessions", "bob"),
            address,
            {"content": "secret"},
            expected_revision=0,
            message_id="m",
        )
        monkeypatch.setattr(
            backend,
            "read",
            lambda *a: pytest.fail("bounded Session reads cannot call full history"),
        )
        action, request = state.next_operation()
        assert action["kind"] == "context"
        evidence = await runtime.prepare_context(request)
        assert evidence["ok"], evidence
        assert evidence["session_data"]["address"] == address
        assert evidence["session_data"]["page"]["items"][0]["content"] == "visible"
        assert "secret" not in str(evidence)
        assert evidence["references"] == []
        state.accept_context(action["id"], evidence)
        assert state.context_snapshot["session_data"] == evidence["session_data"]

    asyncio.run(run())


def test_replacing_session_source_with_same_declared_identity_is_rejected():
    runtime, _, _, _, _ = setup()
    original = runtime.binding_catalog._entries[("session", "private", "1")]
    runtime.binding_catalog._entries[("session", "private", "1")] = (
        SessionBindingResource(
            InMemoryMemory(backend_id="session-source"),
            namespaces=("red",),
            default_namespace="red",
        ),
        original[1],
    )
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


def test_bound_session_namespace_escape_rejected_before_read():
    runtime, _, _, _, scope = setup()
    definition = AgentDefinition(
        AgentSpec("a", "Answer"),
        AgentBindingDescriptor(
            session=BindingSelection.ref("private", "1", selector={"namespace": "secret"})
        ),
    )
    with pytest.raises(AuthorizationDenied):
        TemporalRunState(
            "run",
            asdict(scope),
            "command",
            normalize_request(submission_request(definition, "task")),
            runtime.manifest,
        )


def test_no_default_protocol_change():
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
    assert "session_data_protocol" not in runtime.manifest
    assert runtime.manifest["kernel"] == "temporal-1"


def test_disabled_session_role_removes_only_its_data_source():
    runtime, state, _, _, _ = setup(selected="disabled")
    assert "session_data" not in state.step_manifest
    action, _ = state.next_operation()
    assert action["kind"] == "model"


def test_session_requires_native_bounded_port():
    backend = InMemoryMemory(backend_id="unbounded")
    backend.read_page = None
    with pytest.raises(ValidationError, match="bounded"):
        setup(backend=backend)


@pytest.mark.parametrize("managed", [False, True])
def test_original_session_snapshot_survives_data_changes_before_model_and_restore(managed):
    import copy

    from relf_agent.temporal_session_data import private_address

    from .test_temporal_binding_isolation import advance

    async def run():
        runtime, state, backend, provider, scope = setup(managed=managed)
        view = SessionBindingResource(backend, namespaces=("red",), default_namespace="red").select(
            {}, scope
        )
        backend.append(
            scope,
            view.storage_key(private_address("run", 0)),
            {"role": "assistant", "task": "old", "content": "original"},
            expected_revision=0,
            message_id="m",
        )
        for _ in range(12):
            if state.context_snapshot is not None:
                break
            await advance(runtime, state)
        assert state.context_snapshot is not None
        original = copy.deepcopy(state.context_snapshot)
        backend.append(
            scope,
            view.storage_key(private_address("run", 0)),
            {"content": "new after accepted snapshot"},
            expected_revision=1,
            message_id="m2",
        )
        restored = copy.deepcopy(state)
        await advance(runtime, restored)
        assert restored.state == "succeeded", restored.snapshot()
        assert restored.context_snapshot == original
        assert len(provider.messages) == 1
        assert "original" in str(provider.messages[0])
        assert "new after accepted snapshot" not in str(provider.messages[0])
        assert (
            backend.inspect_message(scope, view.storage_key(private_address("run", 0)), "m2")[
                "receipt"
            ]["revision"]
            == 2
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "damage", ["address", "scope", "revision", "query", "reference", "missing"]
)
def test_original_history_refuses_changed_session_read_evidence(damage):
    import copy

    async def run():
        runtime, state, _, provider, _ = setup()
        action, request = state.next_operation()
        response = await runtime.prepare_context(request)
        assert response["ok"], response
        response = copy.deepcopy(response)
        if damage == "missing":
            response.pop("session_data")
        elif damage == "reference":
            response["session_data_references"] = [{"session": []}]
        elif damage == "scope":
            response["session_data"]["scope"]["principal"] = "other"
        elif damage == "query":
            response["session_data"]["query"]["max_items"] += 1
        elif damage == "revision":
            response["session_data"]["revision"] = True
        else:
            response["session_data"]["address"] = "other"
        with pytest.raises((DefinitionMismatch, ValidationError)):
            state.accept_context(action["id"], response)
        assert not provider.messages and state.context_snapshot is None

    asyncio.run(run())


def test_memory_instance_identity_differs_for_equal_declared_backend_names():
    one = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        session_store=InMemoryMemory(backend_id="same"),
    )
    two = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        session_store=InMemoryMemory(backend_id="same"),
    )
    assert one.manifest["session_data"]["physical"] != two.manifest["session_data"]["physical"]


def test_private_read_cannot_be_mistaken_for_a_durable_history_session():
    from relf_agent.temporal_session_state import validate_binding

    runtime, state, _, _, scope = setup()
    # Turn admission must fail before command reservation, Model or data I/O.
    manifest = {**runtime.manifest, "session_protocol": 1}
    with pytest.raises(ValidationError, match="external"):
        validate_binding(
            {
                "request": state.request,
                "manifest": manifest,
                "task_queue": "q",
                "activity_timeout": 5,
            },
            asdict(scope),
        )


def test_composite_session_binding_is_not_enabled_without_stable_child_addresses():
    from relf_agent import BoundDefinition, TeamSpec
    from relf_agent.temporal_parent_state import TemporalParentState

    runtime, _, _, _, scope = setup()
    spec = BoundDefinition(
        TeamSpec("team", {"a": AgentSpec("a", "Answer")}),
        {"team/members/a": AgentBindingDescriptor(session=BindingSelection.ref("private", "1"))},
    )
    with pytest.raises(ValidationError, match="external"):
        TemporalParentState(
            "run",
            asdict(scope),
            "command",
            normalize_request(submission_request(spec, "task")),
            runtime.orchestration_release,
        )


@pytest.mark.parametrize("query", [False, 0, "untyped"])
def test_host_session_query_rejects_untyped_configuration(query):
    with pytest.raises(ValidationError):
        TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            session_store=InMemoryMemory(),
            session_query=query,
        )


def test_same_identity_client_replacement_is_rejected():
    from types import SimpleNamespace

    class Custom(InMemoryMemory):
        def __init__(self):
            super().__init__(backend_id="same")
            self._client = SimpleNamespace(address="same")

    backend = Custom()
    runtime = TemporalRuntime(
        providers={"default": Provider()}, tools=ToolRegistry(), session_store=backend
    )
    backend._client = SimpleNamespace(address="same")
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


def test_threaded_wrapped_source_replacement_is_rejected_before_read():
    from relf_agent import ThreadedMemoryAdapter

    bridge = ThreadedMemoryAdapter(InMemoryMemory(backend_id="same"))
    runtime = TemporalRuntime(
        providers={"default": Provider()}, tools=ToolRegistry(), session_store=bridge
    )
    bridge.backend = InMemoryMemory(backend_id="same")
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


def test_catalog_session_sources_allow_an_explicit_read_budget():
    from relf_agent.recall import RecallQuery

    scope = Scope()
    catalog = BindingCatalog(scope=scope)
    catalog.register("session", "data", "1", InMemoryMemory(backend_id="source"))
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        binding_catalog=catalog,
        session_query=RecallQuery(max_items=2, max_chars=256, scan_limit=4),
    )
    assert (
        next(iter(runtime.manifest["binding_catalog"]["records"].values()))["configuration"][
            "session_data"
        ]["query"]["max_items"]
        == 2
    )


def test_threaded_session_requires_original_bounded_port_without_legacy_fallback():
    from relf_agent import ThreadedMemoryAdapter

    source = InMemoryMemory()
    source.read_page = None
    source.read = lambda *args: pytest.fail("must reject before full history read")
    with pytest.raises(ValidationError, match="bounded"):
        TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            session_store=ThreadedMemoryAdapter(source),
        )


def test_threaded_original_bounded_method_replacement_rejected():
    from relf_agent import ThreadedMemoryAdapter

    source = InMemoryMemory()
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        session_store=ThreadedMemoryAdapter(source),
    )
    source.read_page = lambda *args: pytest.fail("replaced method cannot execute")
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


@pytest.mark.parametrize("nested", [False, True])
def test_dynamic_model_planner_external_session_is_checked_before_admission(nested):
    from relf_agent import BoundDefinition, DynamicWorkflowSpec, TeamSpec
    from relf_agent.temporal_parent_state import TemporalParentState

    runtime = TemporalRuntime(
        providers={"default": Provider()}, tools=ToolRegistry(), session_store=InMemoryMemory()
    )
    dynamic = DynamicWorkflowSpec("d", {"a": AgentSpec("a", "Answer")}, planner="model")
    spec = TeamSpec("t", {"d": dynamic}) if nested else dynamic
    path = "team/members/d/dynamic/members/a" if nested else "dynamic/members/a"
    spec = BoundDefinition(
        spec, {path: AgentBindingDescriptor(session=BindingSelection.disabled())}
    )
    with pytest.raises(ValidationError, match="external"):
        TemporalParentState(
            "run",
            asdict(Scope()),
            "c",
            normalize_request(submission_request(spec, "task")),
            runtime.orchestration_release,
        )
