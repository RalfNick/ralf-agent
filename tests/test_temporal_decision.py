import asyncio
import copy
from contextlib import contextmanager
from dataclasses import asdict

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    DecisionProposal,
    ModelRequest,
    ModelResponse,
    NativeHarness,
    Scope,
    ToolRegistry,
    ToolSpec,
)
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import normalize_request
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import digest, submission_request
from tests.test_temporal_memory_bindings import grant


class Provider:
    identity = {"kind": "decision-test-provider", "version": "1"}

    def __init__(self):
        self.calls = []
        self.after = None

    async def complete(self, messages, tools):
        self.calls.append(copy.deepcopy([messages, tools]))
        if self.after is not None:
            self.after()
        return ModelResponse(output="raw", usage={"total_tokens": 3})


class Policy:
    def __init__(self, label="host"):
        self.identity = {"kind": "decision-test-policy", "version": "1", "label": label}
        self.calls = []

    def prepare(self, spec, messages, tools):
        self.calls.append(["prepare", spec.name])
        return ModelRequest(
            [*messages, {"role": "system", "content": self.identity["label"]}], tools[:1]
        )

    def propose(self, spec, response):
        self.calls.append(["propose", spec.name])
        return DecisionProposal(
            output={"answer": response.output, "policy": self.identity["label"]}
        )


async def read(arguments, context):
    return "evidence"


def setup(policy=None, *, selected=False, max_context_chars=4096, provider=None):
    host, chosen = policy or Policy(), Policy("chosen")
    catalog = BindingCatalog(scope=Scope()) if selected else None
    if catalog is not None:
        catalog.register("decision_policy", "chosen", "1", chosen)
    tools = ToolRegistry()
    for name in ["read", "other"]:
        tools.register(ToolSpec(name, "Read", {"type": "object"}), read)
    provider = Provider() if provider is None else provider
    runtime = TemporalRuntime(
        providers={"default": provider}, tools=tools, harness=host, binding_catalog=catalog
    )
    definition = AgentSpec("a", "answer", ("read", "other"), max_context_chars=max_context_chars)
    if selected:
        definition = AgentDefinition(
            definition,
            AgentBindingDescriptor(decision_policy=BindingSelection.ref("chosen", "1")),
        )
    state = TemporalRunState(
        "run",
        asdict(Scope()),
        "submit",
        normalize_request(submission_request(definition, {"target": 1})),
        runtime.manifest,
    )
    return runtime, state, provider, host, chosen


async def model(runtime, state):
    action, request = state.next_operation()
    assert action["kind"] == "model"
    response = await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r))
    return action, request, response


@pytest.mark.parametrize("selected", [False, True])
def test_policy_prepares_actual_request_and_proposes_original_history_output(selected):
    async def run():
        runtime, state, provider, host, chosen = setup(selected=selected)
        action, request, response = await model(runtime, state)
        assert response["ok"]
        label = "chosen" if selected else "host"
        assert provider.calls[0][0][-1] == {"role": "system", "content": label}
        assert [t["function"]["name"] for t in provider.calls[0][1]] == ["read"]
        assert runtime.manifest["decision_protocol"] == 1
        assert runtime.capabilities["custom_harness"]
        evidence = response["decision_evidence"]
        assert evidence["request_digest"] == digest(request)
        assert evidence["prepared_request"] == {
            "messages": provider.calls[0][0],
            "tools": provider.calls[0][1],
        }
        assert evidence["registration"] == state.step_manifest["decision_registration"]
        state.accept_model(action["id"], response)
        assert state.result == {"answer": "raw", "policy": label}
        assert action["received_response"]["output"] == "raw"
        assert action["received_response"]["usage"] == {"total_tokens": 3}
        assert (chosen if selected else host).calls == [["prepare", "a"], ["propose", "a"]]
        assert not (host if selected else chosen).calls

    asyncio.run(run())


@contextmanager
def lazy_context():
    raise AssertionError("must not enter lazy policy")
    yield


async def lazy_async():
    raise AssertionError("must not await lazy policy")


def lazy_generator():
    raise AssertionError("must not iterate lazy policy")
    yield


def lazy_value(mode):
    return {
        "dict": lambda: {},
        "coroutine": lazy_async,
        "generator": lazy_generator,
        "context": lazy_context,
    }[mode]()


class LazyPolicy(Policy):
    def __init__(self, phase, mode):
        super().__init__()
        self.identity.update(phase=phase, mode=mode)

    def prepare(self, spec, messages, tools):
        return (
            lazy_value(self.identity["mode"])
            if self.identity["phase"] == "prepare"
            else ModelRequest(messages, tools)
        )

    def propose(self, spec, response):
        return lazy_value(self.identity["mode"])


@pytest.mark.parametrize("phase", ["prepare", "propose"])
@pytest.mark.parametrize("mode", ["dict", "coroutine", "generator", "context"])
def test_lazy_policy_never_succeeds(phase, mode):
    async def run():
        runtime, state, provider, _, _ = setup(LazyPolicy(phase, mode))
        action, _, response = await model(runtime, state)
        assert not response["ok"] and response["code"] == "validation_error"
        assert len(provider.calls) == (phase == "propose")
        state.accept_model(action["id"], response)
        assert state.state == "failed" and state.result is None
        assert ("received_response" in action) == (phase == "propose")

    asyncio.run(run())


class UnsafeRequest(Policy):
    def __init__(self, mode):
        super().__init__()
        self.identity["mode"] = mode

    def prepare(self, spec, messages, tools):
        mode = self.identity["mode"]
        if mode == "unknown-tool":
            tools[0]["function"]["name"] = "forbidden"
        elif mode == "changed-schema":
            tools[0]["function"]["parameters"] = {"type": "string"}
        elif mode == "duplicate":
            tools.append(copy.deepcopy(tools[0]))
        elif mode == "context":
            messages.append({"role": "system", "content": "x" * spec.max_context_chars})
        else:
            messages = []
        return ModelRequest(messages, tools)


@pytest.mark.parametrize(
    "mode", ["unknown-tool", "changed-schema", "duplicate", "context", "empty"]
)
def test_prepared_request_cannot_expand_grant_schema_or_context(mode):
    async def run():
        runtime, state, provider, _, _ = setup(UnsafeRequest(mode))
        action, _, response = await model(runtime, state)
        assert not response["ok"] and not response["dispatched"]
        assert response["code"] == "validation_error" and not provider.calls
        state.accept_model(action["id"], response)
        assert state.state == "failed" and state.result is None

    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["identity", "prepare", "propose", "instance"])
@pytest.mark.parametrize("after_model", [False, True])
def test_actual_policy_drift_blocks_dispatch_or_adoption(mutation, after_model):
    async def run():
        runtime, state, provider, host, _ = setup()

        def change():
            if mutation == "identity":
                host.identity["label"] = "changed"
            elif mutation == "prepare":
                host.prepare = lambda s, m, t: ModelRequest(m, t)
            elif mutation == "propose":
                host.propose = lambda s, r: DecisionProposal(output="changed")
            else:
                runtime.harness = Policy()

        if after_model:
            provider.after = change
        else:
            change()
        action, _, response = await model(runtime, state)
        assert not response["ok"] and response["code"] == "definition_mismatch"
        assert len(provider.calls) == after_model
        state.accept_model(action["id"], response)
        assert state.state == "failed" and state.result is None
        assert ("received_response" in action) == after_model

    asyncio.run(run())


def test_default_native_manifest_stays_protocol_off():
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
    assert runtime.manifest["kernel"] == "temporal-1"
    assert "decision_protocol" not in runtime.manifest
    assert runtime.manifest["harness"] == NativeHarness.identity


@pytest.mark.parametrize(
    "mutation",
    ["missing", "registration", "request", "received", "proposal", "tools", "messages", "legacy"],
)
def test_original_history_rejects_mismatched_decision_evidence(mutation):
    async def run():
        runtime, state, _, _, _ = setup()
        action, _, response = await model(runtime, state)
        if mutation == "missing":
            response.pop("decision_evidence")
        elif mutation == "registration":
            response["decision_evidence"]["registration"]["identity"]["label"] = "foreign"
        elif mutation == "request":
            response["decision_evidence"]["request_digest"] = "foreign"
        elif mutation == "received":
            response["received_response"]["output"] = "foreign"
        elif mutation == "proposal":
            response["output"] = "foreign"
        elif mutation == "legacy":
            response.pop("model_evidence_version")
        elif mutation == "tools":
            response["decision_evidence"]["prepared_request"]["tools"][0]["function"]["name"] = (
                "forbidden"
            )
        else:
            response["decision_evidence"]["prepared_request"]["messages"] = []
        state.accept_model(action["id"], response)
        assert state.state == "failed" and state.result is None
        assert state.error["code"] == "validation_error"
        assert "received_response" in action
        assert state.next_operation() is None

    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["boolean", "missing", "digest", "identity"])
def test_invalid_decision_protocol_is_refused_before_dispatch(mutation):
    from ralf_agent.errors import DefinitionMismatch, ValidationError
    from ralf_agent.temporal_state import validate_manifest

    runtime, _, _, _, _ = setup()
    value = runtime.manifest
    if mutation == "boolean":
        value["decision_protocol"] = True
    elif mutation == "missing":
        value.pop("decision_registration")
    elif mutation == "digest":
        value["decision_registration"]["prepare_digest"] = "opaque"
    else:
        value["decision_registration"]["identity"] = {"kind": "foreign"}
    with pytest.raises((ValidationError, DefinitionMismatch)):
        validate_manifest(value)


def test_cancelled_model_keeps_policy_evidence_without_finishing():
    async def run():
        runtime, state, _, _, _ = setup()
        action, _, response = await model(runtime, state)
        state.command("cancel", {"scope": state.scope, "kind": "cancel"})
        state.accept_model(action["id"], response)
        assert state.state == "cancelled" and state.result is None
        assert action["response"]["decision_evidence"] == response["decision_evidence"]
        assert state.quiescent

    asyncio.run(run())


def test_reconfigured_native_instance_uses_explicit_decision_protocol():
    native = NativeHarness()
    native.propose = lambda spec, response: DecisionProposal(output="custom")
    runtime, _, _, _, _ = setup(native)
    assert runtime.manifest["decision_protocol"] == 1


class DelegatingPolicy(NativeHarness):
    identity = {"kind": "delegating-native-policy", "version": "1"}

    def prepare(self, spec, messages, tools):
        return super().prepare(spec, messages, tools)

    def propose(self, spec, response):
        return super().propose(spec, response)


def test_native_subclass_can_delegate_to_super_with_frozen_base_implementation():
    async def run():
        runtime, state, provider, _, _ = setup(DelegatingPolicy())
        action, _, response = await model(runtime, state)
        assert response["ok"]
        assert len(provider.calls) == 1
        state.accept_model(action["id"], response)
        assert state.result == "raw"

    asyncio.run(run())


def test_super_base_method_drift_is_pinned_after_model(monkeypatch):
    async def run():
        runtime, state, provider, _, _ = setup(DelegatingPolicy())
        provider.after = lambda: monkeypatch.setattr(
            NativeHarness, "propose", lambda s, r: DecisionProposal(output="changed")
        )
        action, _, response = await model(runtime, state)
        assert not response["ok"] and response["code"] == "definition_mismatch"
        state.accept_model(action["id"], response)
        assert state.state == "failed" and action["received_response"]["output"] == "raw"

    asyncio.run(run())


class GovernedPolicy(Policy):
    def propose(self, spec, response):
        if self.identity["label"] == "undeclared":
            from ralf_agent import ToolCall

            return DecisionProposal(tool_calls=(ToolCall("forbidden", {}),))
        if self.identity["label"] == "limit":
            from ralf_agent import ToolCall

            return DecisionProposal(tool_calls=(ToolCall("read", {}), ToolCall("other", {})))
        return DecisionProposal(output={"answer": "shaped"})


@pytest.mark.parametrize(
    "mode,code",
    [
        ("undeclared", "authorization_denied"),
        ("limit", "agent_limit_exceeded"),
        ("schema", "validation_error"),
    ],
)
def test_custom_decision_cannot_bypass_original_schema_grants_or_tool_limits(mode, code):
    from ralf_agent import FixedAgentLimits

    async def run():
        original, _, provider, policy, _ = setup(GovernedPolicy(mode))
        runtime = TemporalRuntime(
            providers={"default": provider},
            tools=original.tools,
            harness=policy,
            limits=FixedAgentLimits(max_tool_actions=1),
        )
        spec = AgentSpec(
            "a",
            "answer",
            ("read", "other"),
            output_schema={"type": "string"} if mode == "schema" else None,
        )
        state = TemporalRunState(
            "run", asdict(Scope()), "s", submission_request(spec, "task"), runtime.manifest
        )
        action, request = state.next_operation()
        state.accept_limits(action["id"], await runtime.propose_limits(request))
        action, _, response = await model(runtime, state)
        state.accept_model(action["id"], response)
        assert state.state == "failed" and state.error["code"] == code
        assert not any(a["kind"] == "tool" for a in state.actions)
        assert action["received_response"]["output"] == "raw"

    asyncio.run(run())


class MutatingProvider(Provider):
    async def complete(self, messages, tools):
        response = await super().complete(messages, tools)
        messages[-1]["content"] = "provider-mutated"
        tools.clear()
        return response


def test_prepared_evidence_is_frozen_before_provider_can_mutate_its_inputs():
    async def run():
        runtime, state, provider, _, _ = setup(provider=MutatingProvider())
        action, _, response = await model(runtime, state)
        assert response["ok"]
        assert response["decision_evidence"]["prepared_request"] == {
            "messages": provider.calls[0][0],
            "tools": provider.calls[0][1],
        }
        assert response["decision_evidence"]["prepared_request"]["tools"]
        state.accept_model(action["id"], response)
        assert state.result == {"answer": "raw", "policy": "host"}

    asyncio.run(run())


class DirectClassAccess(NativeHarness):
    identity = {"kind": "direct-class-access", "version": "1"}
    label = "before"

    def propose(self, spec, response):
        original = super().propose(spec, response)
        return DecisionProposal(output={"label": __class__.label, "raw": original.output})


def test_super_capture_does_not_permit_unpinned_direct_class_access():
    from ralf_agent.errors import ValidationError

    with pytest.raises(ValidationError):
        setup(DirectClassAccess())
