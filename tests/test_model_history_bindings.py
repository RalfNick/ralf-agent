"""Model history choices retain legacy DTO bytes and pin actual pure policies."""

import copy
from dataclasses import asdict

import pytest

from relf_agent import AgentSpec, CompleteModelHistory, Scope, TeamSpec, WorkflowSpec
from relf_agent.binding_catalog import BindingCatalog
from relf_agent.binding_definitions import AgentDefinition, BoundDefinition, decode_definition
from relf_agent.binding_paths import member_spec
from relf_agent.binding_runtime import descriptor_for, unwrap_definition
from relf_agent.binding_types import AgentBindingDescriptor, BindingSelection
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.memory import ThreadedMemoryAdapter
from relf_agent.model_history import model_history_registration
from relf_agent.recall import LegacyMemoryRecallAdapter

from .test_binding_execution import engine
from .test_sandbox_bindings import registered as registered

LEGACY_ROLES = (
    "provider",
    "decision_policy",
    "context",
    "session",
    "facts",
    "knowledge",
    "artifacts",
    "tool_set",
    "workspace",
    "sandbox",
    "skills",
    "verifier",
    "stage_policy",
    "limits",
)


class SessionPolicy(CompleteModelHistory):
    @property
    def identity(self):
        return {
            "kind": "business-model-history",
            "version": "2",
            "scope": "session",
            "allow_tool_result_projection": False,
        }

    def assemble_frame(self, frame, references, max_chars, *, context):
        return copy.deepcopy(frame["history"]), {}

    def validate_frame(self, frame, messages):
        return None


def test_default_descriptor_retains_v1_bytes_and_implicit_history_inheritance():
    descriptor = AgentBindingDescriptor()
    legacy = {"schema_version": 1, **{role: {"mode": "inherit"} for role in LEGACY_ROLES}}
    assert descriptor.to_dict() == legacy
    assert "model_history" not in descriptor._json
    assert descriptor.model_history == BindingSelection.inherit()
    assert AgentBindingDescriptor.from_dict(legacy)._json == descriptor._json


@pytest.mark.parametrize(
    "selection",
    [BindingSelection.inherit(), BindingSelection.disabled(), BindingSelection.ref("history", "2")],
)
def test_explicit_history_choice_roundtrips_only_as_descriptor_two(selection):
    descriptor = AgentBindingDescriptor(model_history=selection)
    assert descriptor.to_dict() == {
        "schema_version": 2,
        **{role: {"mode": "inherit"} for role in LEGACY_ROLES},
        "model_history": selection.to_dict(),
    }
    assert AgentBindingDescriptor.from_dict(descriptor.to_dict()).model_history == selection


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": 1, "model_history": {"mode": "inherit"}},
        {"schema_version": 2},
        {"schema_version": True},
        {"schema_version": 3},
        {"schema_version": 2, "model_history": None},
        {"schema_version": 2, "model_history": {"mode": "inherit"}, "other": {}},
    ],
)
def test_descriptor_versions_reject_missing_or_cross_version_history_role(value):
    with pytest.raises(ValidationError):
        AgentBindingDescriptor.from_dict(value)


def test_bound_sequence_and_nested_codec_preserve_each_history_selection():
    first, second = AgentSpec("first", "Answer"), AgentSpec("second", "Answer")
    explicit = AgentBindingDescriptor(model_history=BindingSelection.disabled())
    restored = decode_definition(AgentDefinition(first, explicit).to_dict())
    assert restored.bindings.model_history.mode == "disabled"
    bound = BoundDefinition(
        WorkflowSpec("steps", [first, second]),
        {
            "sequence/steps/1": explicit,
        },
    )
    definition = unwrap_definition(bound.to_dict())
    assert descriptor_for(definition, 0).to_dict()["schema_version"] == 1
    assert descriptor_for(definition, 1).model_history.mode == "disabled"
    nested = BoundDefinition(
        TeamSpec("team", {"member": bound.definition}),
        {
            "team/members/member/sequence/steps/1": explicit,
        },
    )
    child = member_spec(unwrap_definition(nested.to_dict()), "member")
    child_definition = unwrap_definition(child.to_dict())
    assert descriptor_for(child_definition, 0).to_dict()["schema_version"] == 1
    assert descriptor_for(child_definition, 1).model_history.mode == "disabled"


def test_catalog_history_records_full_registration_and_rejects_method_receiver_drift():
    policy, other = SessionPolicy(), SessionPolicy()
    catalog = BindingCatalog(scope=Scope())
    catalog.register("model_history", "history", "2", policy)
    choice = BindingSelection.ref("history", "2")
    actual, record = catalog.resolve("model_history", choice, Scope())
    assert actual is policy
    assert record["identity"] == model_history_registration(policy)
    registration = copy.deepcopy(record["identity"])
    policy.assemble_frame = other.assemble_frame
    assert model_history_registration(policy) == registration
    with pytest.raises(DefinitionMismatch):
        catalog.resolve("model_history", choice, Scope())


def test_catalog_rejects_lazy_history_and_resource_selectors():
    class LazyPolicy(CompleteModelHistory):
        async def assemble(self, history, references, max_chars, *, context):
            return history, {}

    catalog = BindingCatalog(scope=Scope())
    with pytest.raises(ValidationError):
        catalog.register("model_history", "lazy", "1", LazyPolicy())
    catalog.register("model_history", "history", "1", CompleteModelHistory())
    with pytest.raises(ValidationError):
        catalog.resolve(
            "model_history",
            BindingSelection.ref("history", "1", selector={"namespace": "other"}),
            Scope(),
        )


def test_resolver_uses_host_reference_and_disabled_history_without_v1_records(tmp_path):
    host, selected = CompleteModelHistory(), SessionPolicy()
    catalog = BindingCatalog(scope=Scope())
    catalog.register("model_history", "history", "2", selected)
    with engine(
        tmp_path / "runs.sqlite", catalog, model_continuation=True, model_history=host
    ) as runtime:
        step = asdict(AgentSpec("agent", "Answer"))
        inherited, records = runtime._bindings.resolve(step, AgentBindingDescriptor())
        assert inherited.model_history is host and "model_history" not in records
        ref, records = runtime._bindings.resolve(
            step, AgentBindingDescriptor(model_history=BindingSelection.ref("history", "2"))
        )
        assert ref.model_history is selected
        assert records["model_history"]["identity"] == model_history_registration(selected)
        disabled, records = runtime._bindings.resolve(
            step, AgentBindingDescriptor(model_history=BindingSelection.disabled())
        )
        assert disabled.model_history is None and records["model_history"] == {"mode": "disabled"}


def test_selected_history_requires_explicit_host_continuation(tmp_path):
    catalog = BindingCatalog(scope=Scope())
    catalog.register("model_history", "history", "1", CompleteModelHistory())
    with engine(tmp_path / "runs.sqlite", catalog) as runtime:
        with pytest.raises(ValidationError, match="continuation"):
            runtime._bindings.resolve(
                asdict(AgentSpec("agent", "Answer")),
                AgentBindingDescriptor(model_history=BindingSelection.ref("history", "1")),
            )


@pytest.mark.parametrize("drift", ["receiver", "object"])
def test_host_history_receiver_and_policy_object_are_fixed_before_resolution(tmp_path, drift):
    host, other = CompleteModelHistory(), CompleteModelHistory()
    with engine(
        tmp_path / "runs.sqlite",
        BindingCatalog(scope=Scope()),
        model_continuation=True,
        model_history=host,
    ) as runtime:
        if drift == "receiver":
            host.assemble = other.assemble
        else:
            runtime.model_history = other
        with pytest.raises(DefinitionMismatch):
            runtime._bindings.resolve(
                asdict(AgentSpec("agent", "Answer")), AgentBindingDescriptor()
            )


def test_session_history_cannot_use_explicitly_disabled_session_source(tmp_path):
    catalog = BindingCatalog(scope=Scope())
    catalog.register("model_history", "history", "2", SessionPolicy())
    with engine(tmp_path / "runs.sqlite", catalog, model_continuation=True) as runtime:
        with pytest.raises(ValidationError, match="Session"):
            runtime._bindings.resolve(
                asdict(AgentSpec("agent", "Answer")),
                AgentBindingDescriptor(
                    session=BindingSelection.disabled(),
                    model_history=BindingSelection.ref("history", "2"),
                ),
            )


@pytest.mark.parametrize("wrapper", ["original", "legacy", "threaded-legacy"])
def test_session_history_requires_a_real_bounded_page_port_before_resolution(tmp_path, wrapper):
    class LegacySession:
        backend_id = "legacy-session"

        def read(self, scope, address):
            return []

        def append(self, scope, address, message, *, expected_revision, message_id):
            return expected_revision + 1

    catalog = BindingCatalog(scope=Scope())
    catalog.register("model_history", "history", "2", SessionPolicy())
    backend = LegacySession()
    if wrapper != "original":
        backend = LegacyMemoryRecallAdapter(backend)
    if wrapper == "threaded-legacy":
        backend = ThreadedMemoryAdapter(backend)
    catalog.register("session", "legacy", "1", backend)
    with engine(tmp_path / "runs.sqlite", catalog, model_continuation=True) as runtime:
        with pytest.raises(ValidationError, match="Session"):
            runtime._bindings.resolve(
                asdict(AgentSpec("agent", "Answer")),
                AgentBindingDescriptor(
                    session=BindingSelection.ref("legacy", "1"),
                    model_history=BindingSelection.ref("history", "2"),
                ),
            )


def test_temporal_joint_eight_keeps_native_sandbox_binding_guard(registered):
    from relf_agent.binding_sandbox import validate_sandbox_protocol

    registry, _ = registered
    manifest = {
        "kernel": "temporal-3",
        "binding_protocol": 8,
        "sandbox_binding_protocol": 1,
        "tool_execution_protocol": 1,
        "tools": registry.manifests(["a_sandbox_run"]),
    }
    assert validate_sandbox_protocol(manifest) is None
