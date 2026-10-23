"""Connected native publication owns current bodies and the same finite topology."""

import copy

import pytest

from relf_agent import temporal_coding_protocol as native
from relf_agent.errors import DefinitionMismatch
from tests.test_sandbox_bindings import registered as registered
from tests.test_temporal_coding_configuration import manifest


def current_leaf():
    value = manifest()
    value["binding_protocol"] = 22
    value["coding_execution_protocol"]["version"] = 6
    for resource in value["coding_execution_protocol"]["tools"].values():
        resource["implementation"]["_make_transport"] = "c" * 64
    return value


def current_composition():
    from tests.test_temporal_coding_composition_configuration import composition_manifest

    value = composition_manifest()
    value["binding_protocol"] = 23
    value["coding_execution_protocol"] = current_leaf()["coding_execution_protocol"]
    value["coding_composition_protocol"]["version"] = 7
    return value


@pytest.mark.parametrize("binding", [20, 21])
@pytest.mark.parametrize("native_version", [5, 6])
def test_current_worker_refuses_immutable_dev112_selected_publication(binding, native_version):
    """Original 20/21 Histories require their matching dev112 Worker."""
    value = current_leaf() if binding == 20 else current_composition()
    value["binding_protocol"] = binding
    value["coding_execution_protocol"]["version"] = native_version
    if binding == 21:
        value["coding_composition_protocol"].update(
            version=6 if native_version == 5 else 7,
            topology="bounded-agent-orchestration"
            if native_version == 5
            else "bounded-recursive-orchestration",
        )
    with pytest.raises(DefinitionMismatch):
        native.validate_protocol(value)


@pytest.mark.parametrize("release", [current_leaf, current_composition])
def test_current_publication_accepts_complete_current_metadata(release):
    native.validate_protocol(release())


@pytest.mark.parametrize("binding", [11, 12, 13, 14, 15, 16, 17, 18, 19])
def test_current_worker_refuses_previous_selected_native_metadata(binding):
    value = current_composition() if binding in (12, 13, 15, 17, 19) else current_leaf()
    value["binding_protocol"] = binding
    value["coding_execution_protocol"]["version"] = 2 if binding in (14, 15) else 1
    if binding in (11, 12, 13):
        for resource in value["coding_execution_protocol"]["tools"].values():
            resource["implementation"].pop("_make_transport")
    if binding in (12, 13, 15):
        value["coding_composition_protocol"]["version"] = (
            1 if binding == 12 else 3 if binding == 15 else 2
        )
    elif binding in (16, 17, 18, 19):
        value["coding_execution_protocol"]["version"] = 3 if binding in (16, 17) else 4
        if binding in (17, 19):
            value["coding_composition_protocol"]["version"] = 4 if binding == 17 else 5
    with pytest.raises(DefinitionMismatch):
        native.validate_protocol(value)


def test_current_publication_requires_transport_construction_hook_pin():
    value = current_leaf()
    native.validate_protocol(value)
    value["coding_execution_protocol"]["tools"]["coding"]["implementation"].pop("_make_transport")
    with pytest.raises(DefinitionMismatch, match="resource registration"):
        native.validate_protocol(value)


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6, True, 8])
def test_current_composition_refuses_foreign_version(version):
    value = current_composition()
    native.validate_protocol(value)
    value["coding_composition_protocol"]["version"] = version
    with pytest.raises(DefinitionMismatch):
        native.validate_protocol(value)


@pytest.mark.parametrize("binding", [22, 23])
@pytest.mark.parametrize(
    "kind", ["context", "tool", "artifacts", "continuation", "history", "parent", "input"]
)
def test_current_joint_publication_retains_optional_capability_gates(binding, kind):
    from relf_agent import (
        temporal_artifact_bindings,
        temporal_context_read_protocol,
        temporal_decision_state,
        temporal_parent_completion_state,
        temporal_tool_execution,
        temporal_user_input,
    )
    from tests.test_temporal_coding_joint_protocols import candidate

    validators = {
        "context": temporal_context_read_protocol.validate_protocol,
        "tool": temporal_tool_execution.validate_protocol,
        "artifacts": temporal_artifact_bindings.validate_protocol,
        "continuation": temporal_decision_state.validate_continuation_protocol,
        "history": temporal_decision_state.validate_model_history_protocol,
        "parent": temporal_parent_completion_state.validate_protocol,
        "input": temporal_user_input.validate_protocol,
    }
    value = copy.deepcopy(candidate(kind))
    value.update(kernel="temporal-3", binding_protocol=binding, dispatch_admission="history-1")
    validators[kind](value)


@pytest.mark.parametrize("binding", [22, 23])
def test_current_joint_publication_keeps_sandbox_gate(registered, binding):
    from relf_agent.binding_sandbox import validate_sandbox_protocol
    from tests.test_sandbox_temporal_protocol import runtime_for

    value = copy.deepcopy(runtime_for(registered[0]).manifest)
    value["binding_protocol"] = binding
    validate_sandbox_protocol(value)


def test_current_composition_keeps_shared_runner_capacity_until_physical_stop():
    from tests.test_temporal_coding_parallel_state import resource_parent

    state = resource_parent()
    state.manifest.update(current_composition())
    calls = state.next_calls()
    assert [call["member"] for call in calls] == ["a"]
    assert len(state.children) == 1


def test_current_composition_state_requires_explicit_version_seven():
    from relf_agent.temporal_coding_composition_state import enabled

    assert enabled(current_composition())
    value = current_composition()
    value["coding_composition_protocol"]["version"] = 2
    assert not enabled(value)


def test_current_api_capabilities_admit_team_dynamic_and_recursive_nesting():
    from relf_agent.temporal import TemporalEngine

    engine = object.__new__(TemporalEngine)
    engine._release = {**current_composition(), "orchestration": {"version": "1"}}
    assert engine.capabilities["coding_composition"] == "bounded-recursive-orchestration"
    assert engine.capabilities["graph"]
    assert engine.capabilities["team"] and engine.capabilities["dag"]
    assert engine.capabilities["nesting"]
    assert engine.binding_capabilities["supported_definition_kinds"] == [
        "agent",
        "sequence",
        "graph",
        "team",
        "dynamic",
    ]


def test_current_api_capabilities_refuse_missing_composition_publication():
    from relf_agent.temporal_bindings import capabilities

    value = current_composition()
    value.pop("coding_composition_protocol")
    with pytest.raises(DefinitionMismatch, match="publication is missing"):
        capabilities(value)


def test_current_sdk_control_requires_explicit_version_seven():
    from relf_agent.temporal_coding_composition_control import selected

    assert selected(current_composition())
    value = current_composition()
    value["coding_composition_protocol"]["version"] = 2
    assert not selected(value)


def test_current_parent_records_an_explicit_version_seven_history_marker(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from temporalio.exceptions import ApplicationError

    from relf_agent import temporal_parent_workflow

    markers = []

    def unavailable(name):
        markers.append(name)
        return False

    instance = object.__new__(temporal_parent_workflow.TemporalParentWorkflow)
    instance.state = SimpleNamespace(manifest=current_composition())
    monkeypatch.setattr(temporal_parent_workflow.workflow, "patched", unavailable)
    with pytest.raises(ApplicationError, match="History marker unavailable"):
        asyncio.run(instance.run({"activity_timeout": 1}))
    assert markers == ["ralf-coding-composition-v7"]


@pytest.mark.parametrize("binding", [12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23])
def test_joint_sdk_context_timeout_keeps_original_read_unknown(monkeypatch, binding):
    import asyncio

    from temporalio.exceptions import ActivityError, TimeoutError, TimeoutType

    from relf_agent import temporal_workflow

    class LoopFinished(BaseException):
        pass

    class State:
        manifest = {
            "kernel": "temporal-3",
            "binding_protocol": binding,
            "model_history_protocol": 1,
            "context_read_protocol": {},
        }
        pending_acks, reconcile_requests = [], []

        def __init__(self):
            self.response = None

        def next_operation(self):
            if self.response is not None:
                raise LoopFinished()
            return {"id": "read", "kind": "context", "phase": "context", "attempts": []}, {}

        def accept_context(self, action_id, response):
            self.response = response

    async def no_session():
        return None

    async def timeout(*args, **kwargs):
        error = ActivityError(
            "read timed out",
            scheduled_event_id=1,
            started_event_id=2,
            identity="worker",
            activity_type="context",
            activity_id="read",
            retry_state=None,
        )
        error.__cause__ = TimeoutError(
            "server timeout", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[]
        )
        raise error

    instance = object.__new__(temporal_workflow.TemporalRunWorkflow)
    instance.state, instance.wake_revision = State(), 0
    instance._notify_session = no_session
    monkeypatch.setattr(
        temporal_workflow.workflow,
        "patched",
        lambda name: name == "ralf-unowned-tool-end-evidence-v1",
    )
    monkeypatch.setattr(temporal_workflow.workflow, "execute_activity", timeout)
    with pytest.raises(LoopFinished):
        asyncio.run(instance.run({"activity_timeout": 1}))
    assert instance.state.response["code"] == "activity_outcome_unknown"


@pytest.mark.parametrize(
    "connected,mutation",
    [(False, "hook"), (True, "hook"), (True, "model_fields"), (True, "inventory")],
)
@pytest.mark.parametrize("composition", [False, True])
def test_actual_shared_postgres_publication_refuses_changed_connection_implementation(
    tmp_path, monkeypatch, connected, mutation, composition
):
    import asyncio

    from relf_agent.codex_connected_runner import ConnectedCodexCodingRunner
    from relf_agent.codex_runner import CodexCodingRunner
    from relf_agent.delegated_coding import register_coding_tool
    from relf_agent.postgres_runner_journal import PostgresRunnerJournal
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.temporal_journal import PostgresEffectJournal
    from relf_agent.tools import ToolRegistry
    from tests.test_codex_connected_runner import connection
    from tests.test_temporal_coding_factories import Connection, entry, publish_initialization
    from tests.test_temporal_engine import Provider

    events = []
    publish_initialization(monkeypatch, events)
    options = entry(tmp_path)
    cls = ConnectedCodexCodingRunner if connected else CodexCodingRunner

    async def run():
        effect = PostgresEffectJournal(Connection(events), owns_connection=True)
        journal = PostgresRunnerJournal(effect, identity={"publication": "current"})
        await journal.initialize()
        runner = None
        try:
            runner = cls(
                options["runner_root"],
                journal=journal,
                docker_executable=options["docker_executable"],
                docker_host=options["docker_host"],
                **({"connection": connection()} if connected else {}),
            )
            tools = ToolRegistry()
            register_coding_tool(tools, runner)
            runtime = TemporalRuntime(
                providers={"default": Provider()},
                tools=tools,
                journal=effect,
                coding_execution=True,
                coding_composition=composition,
            )
            runtime.validate_release()
            release = runtime.manifest
            assert release["binding_protocol"] == (23 if composition else 22)
            assert release["coding_execution_protocol"]["version"] == 6
            if composition:
                assert release["coding_composition_protocol"]["version"] == 7
            assert (
                "_make_transport"
                in release["coding_execution_protocol"]["tools"]["coding"]["implementation"]
            )
            assert list((tmp_path / "runner").iterdir()) == []

            def changed(self, owner, environment):
                raise AssertionError("Publication allowed a substituted native constructor")

            if mutation == "hook":
                monkeypatch.setattr(cls, "_make_transport", changed)
            elif mutation == "model_fields":
                from relf_agent import codex_model_connection

                # to_dict already includes reasoning_effort independently, so
                # this changes constructor/source fields without changing the
                # current connection identity. The Worker must pin those rules.
                monkeypatch.setattr(
                    codex_model_connection,
                    "_FIELDS",
                    codex_model_connection._FIELDS | {"reasoning_effort"},
                )
            else:
                from relf_agent import codex_connected_runner

                original_inventory = copy.deepcopy(runner.identity["connection_implementation"])

                def stale_inventory():
                    return copy.deepcopy(original_inventory)

                monkeypatch.setattr(
                    codex_connected_runner, "connection_implementation", stale_inventory
                )
            with pytest.raises(DefinitionMismatch):
                runtime.validate_release()
            assert not (tmp_path / "native").exists()
        finally:
            if runner is not None:
                await runner.aclose()
            await journal.aclose()
            await effect.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("foreign", ["subclass", "effect_owner"])
def test_current_publication_refuses_foreign_runner_or_postgres_owner(
    tmp_path, monkeypatch, foreign
):
    import asyncio
    from types import SimpleNamespace

    from relf_agent.codex_runner import CodexCodingRunner
    from relf_agent.delegated_coding import register_coding_tool
    from relf_agent.errors import ValidationError
    from relf_agent.postgres_runner_journal import PostgresRunnerJournal
    from relf_agent.temporal_journal import PostgresEffectJournal
    from relf_agent.tools import ToolRegistry
    from tests.test_temporal_coding_factories import Connection, entry, publish_initialization

    class ForeignRunner(CodexCodingRunner):
        pass

    events = []
    publish_initialization(monkeypatch, events)
    options = entry(tmp_path)

    async def run():
        effect = PostgresEffectJournal(Connection(events), owns_connection=True)
        journal = PostgresRunnerJournal(effect, identity={"publication": "current"})
        await journal.initialize()
        cls = ForeignRunner if foreign == "subclass" else CodexCodingRunner
        runner = cls(
            options["runner_root"],
            journal=journal,
            docker_executable=options["docker_executable"],
            docker_host=options["docker_host"],
        )
        try:
            tools = ToolRegistry()
            register_coding_tool(tools, runner)
            runtime = SimpleNamespace(
                tools=tools, journal=effect if foreign == "subclass" else None
            )
            with pytest.raises(ValidationError, match="exact shared PostgreSQL journal"):
                native.registration(runtime)
            assert not (tmp_path / "native").exists()
        finally:
            await runner.aclose()
            await journal.aclose()
            await effect.aclose()

    asyncio.run(run())
