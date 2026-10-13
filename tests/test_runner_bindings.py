"""Explicit borrowed Runner selection pins original Coding tool resources."""

import copy
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, Scope, ToolRegistry, ToolSpec, WorkflowSpec
from ralf_agent.binding_catalog import BindingCatalog
from ralf_agent.binding_definitions import AgentDefinition, BoundDefinition
from ralf_agent.binding_runtime import unwrap_definition
from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection
from ralf_agent.delegated_coding import register_coding_tool
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError

from .test_binding_execution import engine


class BorrowedRunner:
    def __init__(self, label="first"):
        self.identity = {"kind": "test-coding-runner", "version": "1", "label": label}
        self.active_operations = 0
        self.calls = []

    async def execute(self, *args, **kwargs):
        self.calls.append("execute")

    async def reconcile(self, *args, **kwargs):
        self.calls.append("reconcile")

    async def stop_existing(self, *args, **kwargs):
        self.calls.append("stop")

    async def aclose(self):
        self.calls.append("close")


def registry(*runners):
    tools = ToolRegistry()
    tools.register(ToolSpec("plain", "Plain", {"type": "object"}), lambda a, c: "plain")
    for index, runner in enumerate(runners):
        register_coding_tool(tools, runner, name=f"coding_{index}")
    return tools


@pytest.mark.parametrize("mode", ["inherit", "ref", "disabled"])
@pytest.mark.parametrize("history", [False, True])
def test_explicit_runner_descriptor_schema_three_roundtrip_and_optional_history(mode, history):
    choice = BindingSelection.ref("first", "1") if mode == "ref" else BindingSelection(mode)
    selections = {"runner": choice}
    if history:
        selections["model_history"] = BindingSelection.disabled()
    descriptor = AgentBindingDescriptor(**selections)
    value = descriptor.to_dict()
    assert value["schema_version"] == 3 and value["runner"] == choice.to_dict()
    assert ("model_history" in value) is history
    assert AgentBindingDescriptor.from_dict(value)._json == descriptor._json


def test_omitted_runner_preserves_exact_legacy_descriptor_bytes():
    for selections in ({}, {"model_history": BindingSelection.disabled()}):
        descriptor = AgentBindingDescriptor(**selections)
        assert "runner" not in descriptor.to_dict()
        assert descriptor.to_dict()["schema_version"] == (2 if selections else 1)
        assert descriptor.runner == BindingSelection.inherit()
        assert AgentBindingDescriptor.from_dict(descriptor.to_dict())._json == descriptor._json


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": 1, "runner": {"mode": "inherit"}},
        {"schema_version": 2, "model_history": {"mode": "inherit"}, "runner": {"mode": "inherit"}},
        {"schema_version": 3},
        {"schema_version": 3, "runner": None},
        {
            "schema_version": 3,
            "runner": {
                "mode": "ref",
                "component_id": "r",
                "version": "1",
                "selector": {"namespace": "x"},
            },
        },
    ],
)
def test_runner_schema_requires_explicit_selector_free_choice(value):
    with pytest.raises(ValidationError):
        AgentBindingDescriptor.from_dict(value)


@pytest.mark.parametrize("decode", [False, True])
def test_runner_rejects_even_empty_serialized_selector(decode):
    choice = {"mode": "ref", "component_id": "first", "version": "1", "selector": {}}
    with pytest.raises(ValidationError, match="selector"):
        if decode:
            AgentBindingDescriptor.from_dict({"schema_version": 3, "runner": choice})
        else:
            AgentBindingDescriptor(runner=choice)


@pytest.mark.parametrize("drift", ["identity", "receiver", "object"])
def test_runner_catalog_pins_actual_resource_and_methods_without_io(drift):
    runner, other = BorrowedRunner(), BorrowedRunner()
    catalog = BindingCatalog(scope=Scope())
    catalog.register("runner", "first", "1", runner)
    choice = BindingSelection.ref("first", "1")
    actual, record = catalog.resolve("runner", choice, Scope())
    assert actual is runner and record["identity"]["runner"] == runner.identity
    if drift == "identity":
        runner.identity["label"] = "changed"
    elif drift == "receiver":
        runner.execute = other.execute
    else:
        catalog._entries[("runner", "first", "1")] = (other, copy.deepcopy(record))
    with pytest.raises(DefinitionMismatch):
        catalog.resolve("runner", choice, Scope())
    assert runner.calls == other.calls == []


def test_runner_catalog_rejects_selector_and_lazy_lifecycle():
    catalog = BindingCatalog(scope=Scope())
    runner = BorrowedRunner()
    catalog.register("runner", "first", "1", runner)
    with pytest.raises(ValidationError):
        catalog.resolve("runner", BindingSelection.ref("first", "1", selector={"x": 1}), Scope())
    runner.execute = lambda: None
    with pytest.raises(ValidationError):
        catalog.register("runner", "lazy", "1", runner)


def test_inherit_derives_original_tool_resource_and_disabled_rejects_selected_coding(tmp_path):
    runner = BorrowedRunner()
    with engine(
        tmp_path / "runs.sqlite", BindingCatalog(scope=Scope()), tools=registry(runner)
    ) as runtime:
        step = asdict(AgentSpec("agent", "Act", tools=("coding_0", "plain")))
        components, records = runtime._bindings.resolve(
            step, AgentBindingDescriptor(runner=BindingSelection.inherit())
        )
        assert components.runner is runner and components.tools == ("coding_0", "plain")
        assert records["runner"]["mode"] == "inherit"
        assert records["runner"]["identity"]["runner"] == runner.identity
        with pytest.raises(AuthorizationDenied):
            runtime._bindings.resolve(
                step, AgentBindingDescriptor(runner=BindingSelection.disabled())
            )
        with pytest.raises(ValidationError, match="explicit"):
            runtime._bindings.resolve(step, AgentBindingDescriptor())
    assert runner.calls == []


def test_reference_requires_same_object_even_when_identity_matches(tmp_path):
    runner, other = BorrowedRunner(), BorrowedRunner()
    catalog = BindingCatalog(scope=Scope())
    catalog.register("runner", "other", "1", other)
    catalog.register("runner", "first", "1", runner)
    with engine(tmp_path / "runs.sqlite", catalog, tools=registry(runner)) as runtime:
        step = asdict(AgentSpec("agent", "Act", tools=("coding_0",)))
        components, records = runtime._bindings.resolve(
            step, AgentBindingDescriptor(runner=BindingSelection.ref("first", "1"))
        )
        assert components.runner is runner and records["runner"]["component_id"] == "first"
        with pytest.raises(DefinitionMismatch):
            runtime._bindings.resolve(
                step, AgentBindingDescriptor(runner=BindingSelection.ref("other", "1"))
            )
    assert runner.calls == other.calls == []


def test_inherit_rejects_multiple_actual_runners_but_accepts_same_resource_tools(tmp_path):
    first, second = BorrowedRunner(), BorrowedRunner("second")
    tools = registry(first, second)
    register_coding_tool(tools, first, name="coding_again")
    with engine(tmp_path / "runs.sqlite", BindingCatalog(scope=Scope()), tools=tools) as runtime:
        descriptor = AgentBindingDescriptor(runner=BindingSelection.inherit())
        with pytest.raises(ValidationError, match="unique"):
            runtime._bindings.resolve(
                asdict(AgentSpec("agent", "Act", tools=("coding_0", "coding_1"))), descriptor
            )
        components, _ = runtime._bindings.resolve(
            asdict(AgentSpec("agent", "Act", tools=("coding_0", "coding_again"))), descriptor
        )
        assert components.runner is first


def test_runner_resolves_after_tool_subset_and_legacy_records_do_not_change(tmp_path):
    runner = BorrowedRunner()
    catalog = BindingCatalog(scope=Scope())
    catalog.register("tool_set", "plain", "1", ["plain"])
    with engine(tmp_path / "runs.sqlite", catalog, tools=registry(runner)) as runtime:
        step = asdict(AgentSpec("agent", "Act", tools=("coding_0", "plain")))
        components, records = runtime._bindings.resolve(
            step, AgentBindingDescriptor(tool_set=BindingSelection.ref("plain", "1"))
        )
        assert (
            components.runner is None and components.tools == ("plain",) and "runner" not in records
        )
        disabled, records = runtime._bindings.resolve(
            step,
            AgentBindingDescriptor(
                tool_set=BindingSelection.ref("plain", "1"), runner=BindingSelection.disabled()
            ),
        )
        assert disabled.runner is None and records["runner"] == {"mode": "disabled"}


@pytest.mark.parametrize("choice", [BindingSelection.inherit(), BindingSelection.disabled()])
def test_explicit_runner_without_coding_uses_binding_release_without_delegated_store_protocol(
    tmp_path, choice
):
    with engine(tmp_path / "runs.sqlite", BindingCatalog(scope=Scope())) as runtime:
        wrapped = AgentDefinition(
            AgentSpec("ordinary", "Answer"), AgentBindingDescriptor(runner=choice)
        )
        manifest = runtime._bindings.manifest(unwrap_definition(wrapped.to_dict()))
        assert manifest["kernel"] == "local-bindings-18"
        assert manifest["runner_binding_protocol"] == 1
        assert "delegated_execution_protocol" not in manifest
        assert "delegated_coding_tools" not in manifest


def test_runner_coexists_with_explicit_disabled_model_history(tmp_path):
    from ralf_agent import CompleteModelHistory

    runner, history = BorrowedRunner(), CompleteModelHistory()
    with engine(
        tmp_path / "runs.sqlite",
        BindingCatalog(scope=Scope()),
        tools=registry(runner),
        model_continuation=True,
        model_history=history,
    ) as runtime:
        components, records = runtime._bindings.resolve(
            asdict(AgentSpec("coding", "Act", tools=("coding_0",))),
            AgentBindingDescriptor(
                runner=BindingSelection.inherit(), model_history=BindingSelection.disabled()
            ),
        )
        assert components.runner is runner and components.model_history is None
        assert records["model_history"] == {"mode": "disabled"}
        assert records["runner"]["identity"]["runner"] == runner.identity


def test_explicit_manifest_releases_only_runner_declarations_and_sequence_keeps_distinct_resources(
    tmp_path,
):
    first, second = BorrowedRunner(), BorrowedRunner("second")
    catalog = BindingCatalog(scope=Scope())
    catalog.register("runner", "first", "1", first)
    catalog.register("runner", "second", "1", second)
    specs = [
        AgentSpec("first", "Act", tools=("coding_0",)),
        AgentSpec("second", "Act", tools=("coding_1",)),
    ]
    wrapped = BoundDefinition(
        WorkflowSpec("pipeline", specs),
        {
            f"sequence/steps/{i}": AgentBindingDescriptor(runner=BindingSelection.ref(label, "1"))
            for i, label in enumerate(("first", "second"))
        },
    )
    with engine(tmp_path / "runs.sqlite", catalog, tools=registry(first, second)) as runtime:
        manifest = runtime._bindings.manifest(unwrap_definition(wrapped.to_dict()))
        assert (
            manifest["kernel"] == "local-bindings-18" and manifest["runner_binding_protocol"] == 1
        )
        assert manifest["delegated_execution_protocol"] == 1
        assert set(manifest["delegated_coding_tools"]) == {"coding_0", "coding_1"}
        steps = manifest["agent_bindings"]["steps"]
        assert (
            steps["sequence/steps/0"]["resolved"]["runner"]["identity"]["runner"] == first.identity
        )
        assert (
            steps["sequence/steps/1"]["resolved"]["runner"]["identity"]["runner"] == second.identity
        )
        legacy = runtime._bindings.manifest(
            unwrap_definition(
                AgentDefinition(AgentSpec("ordinary", "Answer"), AgentBindingDescriptor()).to_dict()
            )
        )
        assert legacy["kernel"] == "local-bindings-1" and "runner_binding_protocol" not in legacy
    assert first.calls == second.calls == []
