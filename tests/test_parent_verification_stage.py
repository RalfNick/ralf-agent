"""Managed verification declares one tool-free Agent and validates its proposal."""

import pytest

from ralf_agent.binding_definitions import AgentDefinition
from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.types import AgentSpec
from tests.test_parent_completion import AcceptGate, request


def test_default_model_stage_disables_unmetered_auxiliary_capabilities():
    from ralf_agent.parent_verification_stage import ModelParentVerificationStage

    stage = ModelParentVerificationStage(provider="verifier", model_credits=2)
    assert type(stage.agent) is AgentDefinition
    assert stage.agent.spec.provider == "verifier"
    assert stage.agent.spec.max_decisions == 1
    assert stage.agent.spec.model_credits == 2
    assert stage.agent.spec.tools == ()
    for role in (
        "facts",
        "knowledge",
        "stage_policy",
        "session",
        "model_history",
        "verifier",
        "artifacts",
        "workspace",
        "skills",
        "sandbox",
        "tool_set",
    ):
        assert getattr(stage.agent.bindings, role).mode == "disabled"


def test_model_stage_requires_exact_bounded_verdict_and_existing_ids():
    from ralf_agent.parent_verification_stage import ModelParentVerificationStage

    stage, value = ModelParentVerificationStage(), request()
    valid = {"status": "accept", "feedback": None, "evidence_ids": [value.children[0]["id"]]}
    assert stage.interpret(value, valid).status == "accept"
    for output in (
        {"status": "accept"},
        {**valid, "candidate": {"total": 999}},
        {**valid, "evidence_ids": ["tool:" + "f" * 64]},
        {**valid, "status": "retry"},
        {**valid, "feedback": "replace answer"},
    ):
        with pytest.raises(ValidationError):
            stage.interpret(value, output)


def test_stage_prepare_freezes_full_source_and_refuses_context_overflow():
    from ralf_agent.parent_verification_stage import ModelParentVerificationStage

    value = request()
    prepared = ModelParentVerificationStage().prepare(value)
    assert prepared == value.to_dict()
    prepared["candidate"]["total"] = 999
    assert value.candidate == {"total": 20}
    with pytest.raises(ValidationError):
        ModelParentVerificationStage(max_context_chars=256).prepare(value)


def test_custom_stage_can_replace_prepare_and_interpret_without_tools():
    from ralf_agent.parent_completion import (
        PARENT_COMPLETION_VERDICT_SCHEMA,
        ParentCompletionPolicy,
    )
    from ralf_agent.parent_completion_protocol import interpret_stage_output, prepare_stage_input

    class CustomStage:
        identity = {"kind": "custom-stage", "version": "1"}
        agent = AgentSpec(
            "reviewer",
            "Return a verdict",
            max_decisions=1,
            output_schema=PARENT_COMPLETION_VERDICT_SCHEMA,
        )

        def prepare(self, request):
            return {"candidate": request.candidate, "ids": [c["id"] for c in request.children]}

        def interpret(self, request, output):
            from ralf_agent.parent_completion import ParentCompletionVerdict

            return ParentCompletionVerdict("reject", feedback="Domain policy rejects it")

    policy = ParentCompletionPolicy(AcceptGate(), model_stage=CustomStage())
    assert prepare_stage_input(policy, request())["candidate"] == {"total": 20}
    assert (
        interpret_stage_output(
            policy, request(), {"status": "reject", "feedback": None, "evidence_ids": []}
        ).status
        == "reject"
    )


def test_policy_rejects_stage_tools_decisions_and_insufficient_credits():
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.parent_verification_stage import ModelParentVerificationStage

    with pytest.raises(ValidationError):
        ParentCompletionPolicy(
            AcceptGate(),
            model_stage=ModelParentVerificationStage(model_credits=2),
            verifier_budget=1,
        )

    class InvalidStage:
        identity = {"kind": "invalid-stage", "version": "1"}
        agent = AgentSpec("bad", "Bad", tools=("lookup",), max_decisions=2)

        def prepare(self, request):
            return request.to_dict()

        def interpret(self, request, output):
            return output

    with pytest.raises(ValidationError):
        ParentCompletionPolicy(AcceptGate(), model_stage=InvalidStage())


def test_stage_bindings_allow_explicit_context_but_reject_auxiliary_inheritance():
    from ralf_agent.parent_verification_stage import ModelParentVerificationStage

    binding = AgentBindingDescriptor(context=BindingSelection.ref("pure-context", "1"))
    stage = ModelParentVerificationStage(bindings=binding)
    assert stage.agent.bindings.context.component_id == "pure-context"
    assert stage.agent.bindings.facts.mode == "disabled"
    with pytest.raises(ValidationError):
        ModelParentVerificationStage(
            bindings=AgentBindingDescriptor(facts=BindingSelection.ref("memory", "1"))
        )


def test_stage_helpers_reject_lazy_preparation_and_agent_drift():
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.parent_completion_protocol import prepare_stage_input
    from ralf_agent.parent_verification_stage import ModelParentVerificationStage

    class LazyStage(ModelParentVerificationStage):
        def prepare(self, request):
            return iter([request.to_dict()])

    with pytest.raises(ValidationError):
        prepare_stage_input(
            ParentCompletionPolicy(AcceptGate(), model_stage=LazyStage()), request()
        )
    stage = ModelParentVerificationStage()
    policy = ParentCompletionPolicy(AcceptGate(), model_stage=stage)
    stage.agent = AgentDefinition(AgentSpec("changed", "Changed", max_decisions=1))
    with pytest.raises(DefinitionMismatch):
        prepare_stage_input(policy, request())


def test_stage_helper_validates_original_schema_before_custom_interpretation():
    from ralf_agent.parent_completion import (
        PARENT_COMPLETION_VERDICT_SCHEMA,
        ParentCompletionPolicy,
    )
    from ralf_agent.parent_completion_protocol import interpret_stage_output

    class BlindStage:
        identity = {"kind": "blind-stage", "version": "1"}
        agent = AgentSpec(
            "reviewer", "Review", max_decisions=1, output_schema=PARENT_COMPLETION_VERDICT_SCHEMA
        )

        def prepare(self, request):
            return request.to_dict()

        def interpret(self, request, output):
            from ralf_agent.parent_completion import ParentCompletionVerdict

            return ParentCompletionVerdict("accept")

    policy = ParentCompletionPolicy(AcceptGate(), model_stage=BlindStage())
    with pytest.raises(ValidationError):
        interpret_stage_output(policy, request(), {"status": "accept", "candidate": {"total": 999}})


def test_stage_schema_must_bound_each_evidence_id():
    from ralf_agent.parent_completion import (
        PARENT_COMPLETION_VERDICT_SCHEMA,
        ParentCompletionPolicy,
    )
    from ralf_agent.parent_verification_stage import ModelParentVerificationStage

    stage = ModelParentVerificationStage()
    schema = {
        **PARENT_COMPLETION_VERDICT_SCHEMA,
        "properties": {
            **PARENT_COMPLETION_VERDICT_SCHEMA["properties"],
            "evidence_ids": {"type": "array", "uniqueItems": True, "maxItems": 256, "items": {}},
        },
    }
    stage.agent = AgentDefinition(
        AgentSpec("reviewer", "Review", max_decisions=1, output_schema=schema)
    )
    with pytest.raises(ValidationError):
        ParentCompletionPolicy(AcceptGate(), model_stage=stage)


def test_non_verdict_schema_enum_is_rejected_before_registration():
    from ralf_agent.parent_completion import (
        PARENT_COMPLETION_VERDICT_SCHEMA,
        ParentCompletionPolicy,
    )
    from ralf_agent.parent_verification_stage import ModelParentVerificationStage

    schema = {
        **PARENT_COMPLETION_VERDICT_SCHEMA,
        "properties": {**PARENT_COMPLETION_VERDICT_SCHEMA["properties"], "status": {"enum": [{}]}},
    }
    stage = ModelParentVerificationStage()
    stage.agent = AgentDefinition(
        AgentSpec("reviewer", "Review", max_decisions=1, output_schema=schema)
    )
    with pytest.raises(ValidationError):
        ParentCompletionPolicy(AcceptGate(), model_stage=stage)
