"""Actual Session address admission, original evidence and managed descendants."""

import asyncio

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingSelection,
    BoundDefinition,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    InMemoryMemory,
    ModelResponse,
    Scope,
    TeamSpec,
    ToolCall,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
)
from ralf_agent.errors import DefinitionMismatch, ValidationError

from .helpers import ScriptedProvider
from .test_binding_execution import RecordingProvider, bound_catalog, engine
from .test_session_binding_resources import resource_type


def session_agent(component="history", namespace=None):
    selection = BindingSelection.ref(
        component, "1", selector={} if namespace is None else {"namespace": namespace}
    )
    return AgentDefinition(AgentSpec("worker", "Answer"), AgentBindingDescriptor(session=selection))


def test_selected_session_is_used_and_host_session_is_not_written(tmp_path):
    catalog = bound_catalog()
    backend = InMemoryMemory(backend_id="selected")
    backend.append(
        Scope(), "shared", {"text": "selected history"}, expected_revision=0, message_id="seed"
    )
    catalog.register("session", "history", "1", backend)
    with engine(tmp_path / "run.sqlite", catalog) as runtime:
        h = runtime.submit(session_agent(), "q", session_id="shared", command_id="s")
        done = asyncio.run(runtime.drive(h.run_id))
        assert done.state == "succeeded" and "selected history" in done.result["request"]
        assert backend.read(Scope(), "shared")[0] == 2
        assert runtime.sessions.read(Scope(), "shared") == (0, [])
        assert runtime.diagnostics(h.run_id).manifest["kernel"] == "local-bindings-3"


def test_catalog_aliases_hold_same_resource_across_restart_but_separate_resources_are_independent(
    tmp_path,
):
    catalog = bound_catalog()
    backend = InMemoryMemory(backend_id="same")
    for name in ("history", "alias"):
        catalog.register("session", name, "1", backend)
    catalog.register("session", "other", "1", InMemoryMemory(backend_id="other"))
    path = tmp_path / "run.sqlite"
    with engine(path, catalog) as runtime:
        h = runtime.submit(session_agent(), "q", session_id="shared", command_id="first")
    with engine(path, catalog) as runtime:
        with pytest.raises(ValidationError):
            runtime.submit(session_agent("alias"), "q", session_id="shared", command_id="busy")
        other = runtime.submit(session_agent("other"), "q", session_id="shared", command_id="other")
        assert asyncio.run(runtime.drive(other.run_id)).state == "succeeded"
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        fresh = runtime.submit(session_agent("alias"), "q", session_id="shared", command_id="after")
        assert asyncio.run(runtime.drive(fresh.run_id)).state == "succeeded"


@pytest.mark.parametrize("ref_first", [False, True])
def test_ref_and_inherited_default_share_admission(tmp_path, ref_first):
    catalog = bound_catalog()
    path = tmp_path / "run.sqlite"
    with engine(path, catalog) as runtime:
        catalog.register("session", "history", "1", runtime.sessions)
        one, two = (
            (session_agent(), AgentSpec("legacy", "Answer"))
            if ref_first
            else (AgentSpec("legacy", "Answer"), session_agent())
        )
        runtime.submit(one, "q", session_id="shared", command_id="one")
        with pytest.raises(ValidationError):
            runtime.submit(two, "q", session_id="shared", command_id="two")


def test_namespace_isolation_and_direct_physical_alias_cannot_bypass_ownership(tmp_path):
    catalog = bound_catalog()
    path = tmp_path / "run.sqlite"
    with engine(path, catalog) as runtime:
        resource = resource_type()(
            runtime.sessions, namespaces=(None, "red", "blue"), default_namespace=None
        )
        catalog.register("session", "history", "1", resource)
        h = runtime.submit(session_agent(namespace="red"), "q", session_id="same", command_id="red")
        blue = runtime.submit(
            session_agent(namespace="blue"), "q", session_id="same", command_id="blue"
        )
        view, _ = catalog.resolve(
            "session", BindingSelection.ref("history", "1", selector={"namespace": "red"}), Scope()
        )
        with pytest.raises(ValidationError):
            runtime.submit(
                AgentSpec("legacy", "Answer"),
                "q",
                session_id=view.storage_key("same"),
                command_id="alias",
            )
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert asyncio.run(runtime.drive(blue.run_id)).state == "succeeded"


@pytest.mark.parametrize("kind", ["sequence", "graph", "team", "dynamic", "nested"])
def test_composite_leaves_keep_selected_sessions(tmp_path, kind):
    catalog = bound_catalog()
    backend = InMemoryMemory(backend_id="selected")
    catalog.register("session", "history", "1", backend)
    a = AgentSpec("worker", "Answer")
    graph = GraphWorkflowSpec(
        "graph", [GraphNode("one", agent=a), GraphNode("two", agent=a)], max_concurrency=2
    )
    spec, path = {
        "sequence": (WorkflowSpec("sequence", [a]), "sequence/steps/0"),
        "graph": (graph, "graph/nodes/one"),
        "team": (TeamSpec("team", {"worker": a}), "team/members/worker"),
        "dynamic": (
            DynamicWorkflowSpec("dynamic", {"worker": a}, plan_mode="dag"),
            "dynamic/members/worker",
        ),
        "nested": (
            TeamSpec("outer", {"inner": graph}, child_budget=16),
            "team/members/inner/graph/nodes/one",
        ),
    }[kind]
    wrapped = BoundDefinition(
        spec, {path: AgentBindingDescriptor(session=BindingSelection.ref("history", "1"))}
    )
    with engine(tmp_path / "run.sqlite", catalog) as runtime:
        h = runtime.submit(wrapped, "q", command_id="s", budget=24)
        done = asyncio.run(runtime.drive(h.run_id))
        assert done.state == "succeeded", done.error
        if kind in {"sequence", "graph"}:
            session = h.run_id if kind == "sequence" else h.run_id + ":node:one"
        else:
            child = runtime.diagnostics(h.run_id).workflow["children"][0]
            session = runtime.store.run(child["run_id"])["session_id"] + (
                ":node:one" if kind == "nested" else ""
            )
        assert backend.read(Scope(), session)[0] == 1
        assert runtime.sessions.read(Scope(), session) == (0, [])
        assert runtime.diagnostics(h.run_id).budget["held"] == 0


def test_session_binding_replay_precedes_registry_lookup_and_missing_admission_is_refused(tmp_path):
    catalog = bound_catalog()
    catalog.register("session", "history", "1", InMemoryMemory(backend_id="selected"))
    with engine(tmp_path / "run.sqlite", catalog) as runtime:
        h = runtime.submit(session_agent(), "q", command_id="s")
        catalog.unregister("session", "history", "1")
        assert runtime.submit(session_agent(), "q", command_id="s") == h
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(h.run_id))
    catalog.register("session", "history", "1", InMemoryMemory(backend_id="selected"))
    with engine(tmp_path / "missing.sqlite", catalog) as runtime:
        runtime.store.session_resource_owner = None
        with pytest.raises(ValidationError):
            runtime.submit(session_agent(), "q", command_id="s")


def test_session_resource_is_held_at_approval_and_duplicate_control_restarts_once(tmp_path):
    catalog = bound_catalog()
    backend = InMemoryMemory(backend_id="selected")
    catalog.register("session", "history", "1", backend)
    provider = ScriptedProvider(
        [ModelResponse(tool_calls=(ToolCall("write", {}),)), ModelResponse(output="done")]
    )
    catalog.register("provider", "writer", "1", provider)
    writes = []
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "write", "Write", {"type": "object"}, requires_approval=True, effect="unqueryable_write"
        ),
        lambda a, c: writes.append(c.effect_key) or "written",
    )
    spec = AgentDefinition(
        AgentSpec("writer", "Act", tools=("write",)),
        AgentBindingDescriptor(
            session=BindingSelection.ref("history", "1"),
            provider=BindingSelection.ref("writer", "1"),
        ),
    )
    path = tmp_path / "run.sqlite"
    with engine(path, catalog, tools=tools) as runtime:
        h = runtime.submit(spec, "q", session_id="shared", command_id="s")
        assert asyncio.run(runtime.drive(h.run_id)).state == "waiting_approval"
        action = runtime.store.run(h.run_id)["actions"][-1]
    with engine(path, catalog, tools=tools) as runtime:
        with pytest.raises(ValidationError):
            runtime.submit(session_agent(), "q", session_id="shared", command_id="busy")
        receipt = runtime.approve(h.run_id, action["id"], action["digest"], command_id="approve")
        assert (
            runtime.approve(h.run_id, action["id"], action["digest"], command_id="approve")
            == receipt
        )
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert len(writes) == 1 and backend.read(Scope(), "shared")[0] == 1


def test_binding_capabilities_reflect_actual_execution_authority(tmp_path):
    with engine(tmp_path / "run.sqlite", bound_catalog()) as runtime:
        assert runtime.binding_capabilities["session_resource_admission"] is True
        assert runtime.binding_capabilities["resource_selectors"] is True
        runtime.store.session_resource_owner = None
        assert runtime.binding_capabilities["session_resource_admission"] is False
        assert runtime.binding_capabilities["resource_selectors"] is True
        assert "session" not in runtime.binding_capabilities["resource_selector_roles"]
        assert "ref" not in runtime.binding_capabilities["session_modes"]


def test_serial_sequence_reserves_future_selected_and_inherited_session_resources(tmp_path):
    catalog = bound_catalog()
    backend = InMemoryMemory(backend_id="selected")
    catalog.register("session", "history", "1", backend)
    spec = BoundDefinition(
        WorkflowSpec("mixed", [AgentSpec("a", "Answer"), AgentSpec("b", "Answer")]),
        {"sequence/steps/1": AgentBindingDescriptor(session=BindingSelection.ref("history", "1"))},
    )
    with engine(tmp_path / "run.sqlite", catalog) as runtime:
        h = runtime.submit(spec, "q", session_id="shared", command_id="s")
        with pytest.raises(ValidationError):
            runtime.submit(session_agent(), "q", session_id="shared", command_id="busy")
        with pytest.raises(ValidationError):
            runtime.submit(
                AgentSpec("a", "Answer"), "q", session_id="shared", command_id="default-busy"
            )
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"


def test_binding_drift_preserves_received_response_before_adoption(tmp_path):
    catalog = bound_catalog()
    backend = InMemoryMemory(backend_id="original")
    catalog.register("session", "history", "1", backend)

    class Provider(RecordingProvider):
        async def complete(self, messages, tools):
            backend.backend_id = "changed"
            return ModelResponse(output="received")

    catalog.register("provider", "drift", "1", Provider("selected"))
    spec = AgentDefinition(
        AgentSpec("worker", "Answer"),
        AgentBindingDescriptor(
            session=BindingSelection.ref("history", "1"),
            provider=BindingSelection.ref("drift", "1"),
        ),
    )
    with engine(tmp_path / "run.sqlite", catalog) as runtime:
        h = runtime.submit(spec, "q", command_id="s")
        done = asyncio.run(runtime.drive(h.run_id))
        assert done.state == "failed" and done.error["code"] == "definition_mismatch"
        assert (
            runtime.store.run(h.run_id)["actions"][0]["received_response"]["output"] == "received"
        )


@pytest.mark.parametrize("threaded_first", [False, True])
def test_threaded_bridge_and_raw_backend_share_session_ownership(tmp_path, threaded_first):
    from ralf_agent import ThreadedMemoryAdapter

    catalog = bound_catalog()
    backend = InMemoryMemory(backend_id="physical")
    catalog.register("session", "history", "1", backend)
    catalog.register("session", "threaded", "1", ThreadedMemoryAdapter(backend))
    with engine(tmp_path / "threaded.sqlite", catalog) as runtime:
        first, second = ("threaded", "history") if threaded_first else ("history", "threaded")
        runtime.submit(session_agent(first), "q", session_id="shared", command_id="s")
        with pytest.raises(ValidationError):
            runtime.submit(session_agent(second), "q", session_id="shared", command_id="busy")


def test_selected_view_is_refused_as_host_default_before_run_acceptance(tmp_path):
    from contextlib import closing

    from ralf_agent import LocalEngine, SQLiteStore

    resource = resource_type()(
        InMemoryMemory(backend_id="physical"), namespaces=("red",), default_namespace="red"
    )
    with closing(SQLiteStore(tmp_path / "default.sqlite")) as store:
        with pytest.raises(ValidationError):
            LocalEngine(
                store,
                providers={"default": RecordingProvider("offline")},
                tools=ToolRegistry(),
                session_store=resource.select({}, Scope()),
            )
        assert store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


@pytest.mark.parametrize("kind", ["closable", "noncallable", "raising"])
def test_invalid_authority_result_does_not_close_borrowed_resources(tmp_path, kind):
    class Borrowed:
        closed = False

        def close(self):
            self.closed = True
            if kind == "raising":
                raise RuntimeError("borrowed close must not run")

    borrowed = Borrowed()
    if kind == "noncallable":
        borrowed.close = 1
    catalog = bound_catalog()
    catalog.register("session", "history", "1", InMemoryMemory(backend_id="selected"))
    with engine(tmp_path / "owner.sqlite", catalog) as runtime:
        runtime.store.session_resource_owner = lambda scope, resource: borrowed
        with pytest.raises(ValidationError):
            runtime.submit(session_agent(), "q", command_id="s")
        assert borrowed.closed is False
        assert runtime.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
