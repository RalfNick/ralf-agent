"""Continuation is completed model evidence, adopted only by original History."""

import asyncio
import copy
import json
from dataclasses import asdict

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    DecisionProposal,
    ModelResponse,
    NativeHarness,
    Scope,
    ToolCall,
    ToolRegistry,
)
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_bindings import normalize_request, provider_alias
from relf_agent.temporal_profile import TemporalProfile
from relf_agent.temporal_state import TemporalRunState, validate_manifest
from relf_agent.types import digest, submission_request
from tests.test_temporal_memory_bindings import grant


class SignedProvider:
    identity = {"kind": "signed-history-fixture", "version": "1"}

    def __init__(self):
        self.calls = []
        self.after = None
        self.owner = digest(self.identity)

    @property
    def continuation_identity(self):
        return {"protocol": "history-signature-1", "owner_digest": self.owner}

    async def complete(self, messages, tools):
        from relf_agent.model_continuation import ContinuedModelResponse, ModelContinuation

        self.calls.append(copy.deepcopy(messages))
        if self.after is not None:
            self.after()
        if any(m.get("role") == "tool" for m in messages):
            return ModelResponse(output={"amount": 6})
        calls = [ToolCall("calculate", {"quantity": 3}, "native-call")]
        raw = {"output": None, "tool_calls": [asdict(call) for call in calls]}
        return ContinuedModelResponse(
            tool_calls=calls,
            continuation=ModelContinuation(
                "history-signature-1",
                self.owner,
                digest(raw),
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {"name": "calculate", "args": {"quantity": 3}},
                                "thoughtSignature": "original-private-signature",
                            }
                        ],
                    },
                    "call_ids": ["native-call"],
                },
            ),
        )


def calculate(quantity: int, price: int = 2):
    return quantity * price


def setup(*, enabled=True, harness=None, selected=False, **options):
    provider = SignedProvider()
    tools = ToolRegistry()
    tools.register_function(calculate, effect="read_only", requires_approval=True)
    catalog = BindingCatalog(scope=Scope()) if selected else None
    default = SignedProvider() if selected else provider
    if catalog is not None:
        catalog.register("provider", "signed", "1", provider)
    runtime = TemporalRuntime(
        providers={"default": default},
        tools=tools,
        harness=harness,
        binding_catalog=catalog,
        model_continuation=enabled,
        **options,
    )
    definition = AgentSpec("account", "Calculate", tools=("calculate",))
    if selected:
        definition = AgentDefinition(
            definition, AgentBindingDescriptor(provider=BindingSelection.ref("signed", "1"))
        )
    state = TemporalRunState(
        "run",
        asdict(Scope()),
        "submit",
        normalize_request(submission_request(definition, "3 units", budget=10)),
        runtime.manifest,
    )
    return runtime, state, provider


async def complete(runtime, state):
    action, request = state.next_operation()
    assert action["kind"] == "model"
    response = await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r))
    if response.get("model_receipt_version") == 1:
        state.accept_model(action["id"], response)
        if state.state not in {"failed", "cancelled", "succeeded"}:
            _, adoption_request = state.next_operation()
            response = await runtime.adopt_model(adoption_request)
    return action, request, response


def accept(state, action, response):
    adoption = next(
        (
            a
            for a in state.actions
            if a["id"] == state.active_action and a["kind"] == "model_adoption"
        ),
        None,
    )
    if adoption is not None:
        state.accept_model_adoption(adoption["id"], response)
    elif action.get("status") != "rejected":
        state.accept_model(action["id"], response)


def test_continuation_opt_in_publishes_joint_manifest_without_forcing_other_features():
    runtime, state, provider = setup()
    assert runtime.manifest["binding_protocol"] == 6
    assert runtime.manifest["model_continuation_protocol"] == 1
    assert runtime.manifest["provider_continuations"]["default"] == provider.continuation_identity
    assert "tool_execution_protocol" not in runtime.manifest
    assert "context_read_protocol" not in runtime.manifest
    assert "artifacts_binding_protocol" not in runtime.manifest
    assert state.state == "queued"


def test_default_false_has_original_release_and_profile_payload():
    provider, tools = SignedProvider(), ToolRegistry()
    old = TemporalRuntime(providers={"default": provider}, tools=tools)
    explicit = TemporalRuntime(
        providers={"default": provider}, tools=tools, model_continuation=False
    )
    assert old.manifest == explicit.manifest
    assert old.manifest["kernel"] == "temporal-1"
    assert "model_continuation_protocol" not in old.manifest
    values = dict(name="a", version="1", providers={"default": {"adapter": "echo"}})
    original = TemporalProfile(**values)
    assert (
        original.to_dict()
        == TemporalProfile(**values, execution={"model_continuation": False}).to_dict()
    )
    assert "model_continuation" not in original.execution
    enabled = TemporalProfile(**values, execution={"model_continuation": True})
    assert enabled.execution["model_continuation"] is True


@pytest.mark.parametrize("value", [None, 1, "true", {}])
def test_opt_in_requires_ordinary_boolean(value):
    with pytest.raises(ValidationError):
        setup(enabled=value)


@pytest.mark.parametrize("selected", [False, True])
def test_history_preserves_signed_raw_message_and_adopts_resolved_defaults(selected):
    async def run():
        runtime, state, provider = setup(selected=selected)
        action, _, response = await complete(runtime, state)
        assert response["ok"], response
        accept(state, action, response)
        assert (
            action["received_response"]["continuation"]["data"]["content"]["parts"][0][
                "thoughtSignature"
            ]
            == "original-private-signature"
        )
        proposed = next(a for a in state.actions if a["kind"] == "tool")
        assert proposed["arguments"] == {"quantity": 3, "price": 2}
        assistant = state.messages[-1]
        assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"quantity": 3}
        assert assistant["model_continuation"] == response["received_response"]["continuation"]
        assert assistant["tool_calls"][0]["id"] == "native-call"
        alias = provider_alias(BindingSelection.ref("signed", "1")) if selected else "default"
        assert state.step["provider"] == alias
        assert runtime.manifest["provider_continuations"][alias] == provider.continuation_identity
        assert state.next_operation() is None and state.state == "waiting_approval"
        recovered = copy.deepcopy(state)
        approval = recovered.snapshot()["pending"][0]
        recovered.command(
            "approve",
            {
                "kind": "approve",
                "scope": asdict(Scope()),
                "action_id": approval["action_id"],
                "digest": approval["digest"],
                "approved": True,
            },
        )
        tool, request = recovered.next_operation()
        assert tool["arguments"] == {"quantity": 3, "price": 2}
        recovered.accept_tool(tool["id"], await runtime.execute_tool(request))
        finished, _, result = await complete(runtime, recovered)
        assert provider.calls[-1][-2] == assistant
        accept(recovered, finished, result)
        assert recovered.state == "succeeded" and recovered.result == {"amount": 6}
        assert len(provider.calls) == 2
        assert copy.deepcopy(recovered).next_operation() is None

    asyncio.run(run())


def test_unenabled_response_is_recorded_and_never_adopted_or_retried():
    async def run():
        runtime, state, provider = setup(enabled=False)
        action, _, response = await complete(runtime, state)
        assert not response["ok"] and "received_response" in response
        accept(state, action, response)
        assert state.state == "failed" and not any(a["kind"] == "tool" for a in state.actions)
        assert action["status"] == "rejected" and "continuation" in action["received_response"]
        assert state.next_operation() is None and len(provider.calls) == 1

    asyncio.run(run())


class ChangedHarness(NativeHarness):
    identity = {"kind": "changed-history-harness", "version": "1"}

    def propose(self, spec, response):
        return DecisionProposal(tool_calls=(ToolCall("calculate", {"quantity": 4}, "native-call"),))


def test_changed_harness_cannot_adopt_signed_model_call():
    async def run():
        runtime, state, provider = setup(harness=ChangedHarness())
        action, _, response = await complete(runtime, state)
        assert not response["ok"], response
        accept(state, action, response)
        assert state.state == "failed" and action["status"] == "rejected"
        assert action["received_response"]["tool_calls"][0]["arguments"] == {"quantity": 3}
        assert not any(a["kind"] == "tool" for a in state.actions)
        assert len(provider.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation", ["owner", "decision", "protocol", "call", "default", "proposal"]
)
def test_original_history_rejects_forged_continuation_or_adopted_parameters(mutation):
    async def run():
        runtime, state, _ = setup()
        action, _, response = await complete(runtime, state)
        assert response["ok"]
        if mutation in {"owner", "decision", "protocol"}:
            key = {"owner": "owner_digest", "decision": "decision_digest", "protocol": "protocol"}[
                mutation
            ]
            response["received_response"]["continuation"][key] = "f" * 64
        elif mutation == "call":
            response["tool_calls"][0]["arguments"]["quantity"] = 5
        elif mutation == "default":
            response["tool_calls"][0]["arguments"]["price"] = 99
        else:
            response["continuation_proposal"]["tool_calls"][0]["arguments"]["quantity"] = 4
        accept(state, action, response)
        assert state.state == "failed" and action["status"] == "rejected"
        assert not any(a["kind"] == "tool" for a in state.actions)

    asyncio.run(run())


def test_provider_continuation_identity_drift_is_refused_before_dispatch():
    runtime, _, provider = setup()
    provider.owner = "e" * 64
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


@pytest.mark.parametrize(
    "mutate", ["missing", "wrong", "legacy", "identity", "alias", "typed-defaults"]
)
def test_joint_release_has_complete_original_protocol_and_provider_registration(mutate):
    runtime, _, _ = setup()
    manifest = runtime.manifest
    if mutate == "missing":
        manifest.pop("model_continuation_protocol")
    elif mutate == "wrong":
        manifest["model_continuation_protocol"] = True
    elif mutate == "legacy":
        manifest["binding_protocol"] = 5
    elif mutate == "identity":
        manifest["provider_continuations"]["default"] = {"protocol": "x", "owner_digest": "bad"}
    elif mutate == "alias":
        manifest["provider_continuations"].clear()
    else:
        manifest["continuation_tool_defaults"]["calculate"]["implementation_digest"] = "x" * 64
    with pytest.raises((DefinitionMismatch, ValidationError)):
        validate_manifest(manifest)


def test_joint_continuation_retains_context_and_tool_execution_owners():
    from relf_agent.tool_execution import ToolExecutionOwner

    async def run():
        runtime, _, _ = setup(
            context_reads=True, tool_execution=ToolExecutionOwner(version="test-1")
        )
        assert runtime.manifest["binding_protocol"] == 6
        assert "context_read_protocol" in runtime.manifest
        assert "tool_execution_protocol" in runtime.manifest
        assert validate_manifest(runtime.manifest) == runtime.manifest
        await runtime.close_context_execution(wait_timeout=1)

    asyncio.run(run())


def test_joint_continuation_keeps_artifact_selection_and_recovery_contract():
    from relf_agent.temporal_bindings import effective_manifest, selected_runtime
    from tests.test_artifact_binding_temporal import host, request

    old, stores = host()
    runtime = TemporalRuntime(
        providers=old.providers,
        tools=old.tools,
        context_builder=old.context,
        binding_catalog=old.binding_catalog,
        model_continuation=True,
    )
    assert runtime.manifest["binding_protocol"] == 6
    assert runtime.manifest["artifacts_binding_protocol"] == 1
    req = request()
    selected = effective_manifest(runtime.manifest, req["agent_bindings"]["agent"])
    actual = selected_runtime(
        runtime, {**req, "scope": asdict(Scope()), "step_bindings": req["agent_bindings"]["agent"]}
    )
    assert selected["context_builder"] == actual.context.identity
    assert selected["managed_context"]["policy"]["artifacts"]["backend_id"] == "alpha"
    state = TemporalRunState("run", asdict(Scope()), "s", req, runtime.manifest)
    assert copy.deepcopy(state).manifest == runtime.manifest
    assert all(not store._records for store in stores.values())


def test_joint_continuation_keeps_original_sandbox_grants(registered):
    from relf_agent.binding_sandbox import SandboxBindingResource
    from relf_agent.temporal_bindings import effective_step
    from tests.test_sandbox_binding_execution import Reader

    registry, _ = registered
    catalog = BindingCatalog(scope=Scope())
    catalog.register("sandbox", "a", "1", SandboxBindingResource(registry, names=["a_sandbox_run"]))
    runtime = TemporalRuntime(
        providers={"default": Reader()},
        tools=registry,
        binding_catalog=catalog,
        context_reads=True,
        model_continuation=True,
    )
    manifest = runtime.manifest
    assert manifest["binding_protocol"] == 6 and manifest["sandbox_binding_protocol"] == 1
    chosen = effective_step(
        asdict(AgentSpec("a", "Run", tools=("a_sandbox_run", "b_sandbox_run", "business"))),
        manifest,
        AgentBindingDescriptor(sandbox=BindingSelection.ref("a", "1")).to_dict(),
    )
    assert chosen["tools"] == ["a_sandbox_run", "business"]
    invalid = copy.deepcopy(manifest)
    invalid.pop("tool_execution_protocol")
    with pytest.raises(DefinitionMismatch):
        validate_manifest(invalid)
    asyncio.run(runtime.close_context_execution(wait_timeout=1))


def test_history_rejects_legacy_response_without_original_evidence_under_joint_release():
    runtime, state, _ = setup()
    action, _ = state.next_operation()
    state.accept_model(
        action["id"], {"ok": True, "output": "forged", "tool_calls": [], "usage": None}
    )
    assert state.state == "failed" and state.result is None
    assert not any(a["kind"] == "tool" for a in state.actions)


# Reuse the original native Sandbox fixture; no service or sandbox process starts.
from tests.test_sandbox_bindings import registered as registered  # noqa: E402,F401


def test_dispatch_completion_identity_drift_retains_original_response_and_stops():
    async def run():
        runtime, state, provider = setup()
        provider.after = lambda: setattr(provider, "owner", "e" * 64)
        action, _, response = await complete(runtime, state)
        assert not response["ok"] and response["code"] == "definition_mismatch"
        assert "continuation" in response["received_response"]
        accept(state, action, response)
        assert state.state == "failed" and state.budget["spent"] == 1
        assert state.next_operation() is None and len(provider.calls) == 1

    asyncio.run(run())


def test_plain_provider_is_allowed_and_cannot_claim_an_unregistered_continuation():
    class PlainProvider(SignedProvider):
        continuation_identity = None

    async def run():
        provider = PlainProvider()
        tools = ToolRegistry()
        tools.register_function(calculate, effect="read_only")
        runtime = TemporalRuntime(
            providers={"default": provider}, tools=tools, model_continuation=True
        )
        assert runtime.manifest["provider_continuations"] == {"default": None}
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "s",
            submission_request(AgentSpec("a", "Read", tools=("calculate",)), "3 units"),
            runtime.manifest,
        )
        action, _, response = await complete(runtime, state)
        assert response["ok"] is True and response["model_receipt_version"] == 1
        assert action["status"] == "rejected" and state.error["code"] == "validation_error"
        assert state.state == "failed" and not any(a["kind"] == "tool" for a in state.actions)

    asyncio.run(run())


@pytest.mark.parametrize(
    "field", ["model_continuation_protocol", "provider_continuations", "continuation_tool_defaults"]
)
def test_old_release_cannot_accept_partial_continuation_markers(field):
    provider = SignedProvider()
    legacy = TemporalRuntime(providers={"default": provider}, tools=ToolRegistry()).manifest
    values = {
        "model_continuation_protocol": 1,
        "provider_continuations": {"default": provider.continuation_identity},
        "continuation_tool_defaults": {},
    }
    legacy[field] = values[field]
    with pytest.raises(DefinitionMismatch):
        validate_manifest(legacy)


def test_temporal_continuation_configuration_uses_execution_flag_only():
    with pytest.raises(ValidationError, match="Local execution components"):
        TemporalProfile(
            "a",
            "1",
            {"default": {"adapter": "echo"}},
            components={"model_continuation": {"adapter": "native"}},
        )


@pytest.mark.parametrize("change", ["none", "extra", "wrong-type", "remote-ref"])
def test_joint_defaults_metadata_malformed_fails_as_domain_error_before_io(change):
    runtime, _, _ = setup()
    manifest = runtime.manifest
    record = manifest["continuation_tool_defaults"]["calculate"]
    if change == "none":
        manifest["continuation_tool_defaults"]["calculate"] = None
    elif change == "extra":
        record["defaults"]["unknown"] = 1
    elif change == "wrong-type":
        record["defaults"]["price"] = "wrong"
    else:
        manifest["tools"]["calculate"]["input_schema"]["properties"]["price"] = {
            "$ref": "https://should-never-resolve.example/schema"
        }
    with pytest.raises((DefinitionMismatch, ValidationError)):
        validate_manifest(manifest)


def test_history_rejects_missing_raw_proposal_without_losing_completed_evidence():
    async def run():
        runtime, state, _ = setup()
        action, _, response = await complete(runtime, state)
        response.pop("continuation_proposal")
        accept(state, action, response)
        assert state.state == "failed"
        assert action["received_response"]["continuation"]["data"]["call_ids"] == ["native-call"]
        assert state.budget["spent"] == 1 and state.budget["unknown"] == 0
        assert copy.deepcopy(state).next_operation() is None

    asyncio.run(run())


def test_approval_control_receipt_repeats_while_signed_group_remains_original():
    async def run():
        runtime, state, provider = setup()
        action, _, response = await complete(runtime, state)
        accept(state, action, response)
        assert state.next_operation() is None
        pending = state.snapshot()["pending"][0]
        payload = {
            "kind": "approve",
            "scope": asdict(Scope()),
            "action_id": pending["action_id"],
            "digest": pending["digest"],
            "approved": True,
        }
        receipt = state.command("same-approval", payload)
        assert state.command("same-approval", payload) == receipt
        assert len([a for a in state.actions if a["kind"] == "tool"]) == 1
        assert (
            state.messages[-1]["model_continuation"]
            == response["received_response"]["continuation"]
        )
        assert len(provider.calls) == 1

    asyncio.run(run())


def test_completed_model_receipt_is_in_history_before_harness_proposal():
    class CountingHarness(NativeHarness):
        identity = {"kind": "receipt-counting-harness", "version": "1"}

        def __init__(self):
            self.proposals = 0

        def propose(self, spec, response):
            self.proposals += 1
            return super().propose(spec, response)

    async def run():
        policy = CountingHarness()
        runtime, state, provider = setup(harness=policy)
        action, request = state.next_operation()
        receipt = await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r))
        assert receipt["model_receipt_version"] == 1
        assert policy.proposals == 0 and len(provider.calls) == 1
        assert "tool_calls" not in receipt
        state.accept_model(action["id"], receipt)
        assert action["received_response"]["tool_calls"][0]["arguments"] == {"quantity": 3}
        assert state.budget["spent"] == 1 and state.budget["reserved"] == 0
        assert not any(a["kind"] == "tool" for a in state.actions)
        restored = copy.deepcopy(state)
        adoption, adoption_request = restored.next_operation()
        assert adoption["kind"] == "model_adoption" and adoption["model_action_id"] == action["id"]
        result = await runtime.adopt_model(adoption_request)
        assert len(provider.calls) == 1 and policy.proposals == 1
        restored.accept_model_adoption(adoption["id"], result)
        assert restored.budget["spent"] == 1 and restored.budget["unknown"] == 0
        assert next(a for a in restored.actions if a["kind"] == "tool")["arguments"] == {
            "quantity": 3,
            "price": 2,
        }
        assert (
            restored.messages[-1]["model_continuation"]
            == receipt["received_response"]["continuation"]
        )

    asyncio.run(run())


def test_lost_pure_adoption_does_not_make_received_model_unknown():
    async def run():
        runtime, state, provider = setup()
        model, request = state.next_operation()
        receipt = await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r))
        state.accept_model(model["id"], receipt)
        adoption, _ = state.next_operation()
        state.accept_model_adoption(
            adoption["id"], {"ok": False, "code": "activity_outcome_unknown"}
        )
        assert state.state == "failed" and state.budget["unknown"] == 0
        assert model["received_response"] == receipt["received_response"]
        assert state.budget["spent"] == 1 and state.quiescent
        assert copy.deepcopy(state).next_operation() is None and len(provider.calls) == 1

    asyncio.run(run())


def test_native_joint_receipt_binds_original_pure_harness_registration():
    async def run():
        runtime, state, _ = setup()
        action, request = state.next_operation()
        receipt = await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r))
        assert receipt["decision_registration"] == runtime.manifest["decision_registration"]
        receipt["decision_registration"]["prepare_digest"] = "f" * 64
        state.accept_model(action["id"], receipt)
        assert state.state == "failed" and "received_response" in action
        assert not any(a["kind"] == "model_adoption" for a in state.actions)

    asyncio.run(run())


@pytest.mark.parametrize("corruption", ["request", "messages", "tools"])
def test_invalid_prepared_receipt_never_creates_adoption_or_tool(corruption):
    async def run():
        runtime, state, provider = setup()
        model, request = state.next_operation()
        receipt = await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r))
        if corruption == "request":
            receipt["request_digest"] = "f" * 64
        elif corruption == "messages":
            receipt["prepared_request"]["messages"] = []
        else:
            receipt["prepared_request"]["tools"][0]["function"]["name"] = "forbidden"
        state.accept_model(model["id"], receipt)
        assert state.state == "failed" and state.budget["spent"] == 1
        assert not any(a["kind"] in {"tool", "model_adoption"} for a in state.actions)
        assert len(provider.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize("window", ["before_receipt", "before_adoption", "during_adoption"])
def test_cancelled_history_preserves_received_model_without_tool_proposals(window):
    async def run():
        runtime, state, provider = setup()
        model, request = state.next_operation()
        receipt = await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r))
        if window == "before_receipt":
            state.command("cancel", {"kind": "cancel", "scope": state.scope})
            state.accept_model(model["id"], receipt)
        else:
            state.accept_model(model["id"], receipt)
            operation = state.next_operation() if window == "during_adoption" else None
            state.command("cancel", {"kind": "cancel", "scope": state.scope})
            if operation is not None:
                adoption, request = operation
                response = await runtime.adopt_model(request)
                state.accept_model_adoption(adoption["id"], response)
        assert state.state == "cancelled" and state.budget["spent"] == 1
        assert model["received_response"] == receipt["received_response"]
        assert not any(a["kind"] == "tool" for a in state.actions)
        assert state.next_operation() is None and state.quiescent
        assert len(provider.calls) == 1

    asyncio.run(run())
