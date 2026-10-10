import asyncio
import copy
import json
from dataclasses import asdict

import pytest

from ralf_agent import (
    AgentSpec,
    InMemoryMemory,
    ManagedMemoryPolicy,
    ManagedModelMemoryPolicy,
    MemoryAdmissionPolicy,
    ModelResponse,
    Scope,
    ToolRegistry,
    WorkflowSpec,
)
from ralf_agent.errors import MemoryBackendError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import canonical, submission_request
from tests.test_temporal_memory_bindings import grant


class Provider:
    identity = {"kind": "temporal-memory-fixture", "version": "1"}

    def __init__(self):
        self.business = self.selectors = 0

    async def complete(self, messages, tools):
        if messages[0]["content"].startswith("memory-field-selector:"):
            self.selectors += 1
            assert tools == []
            return ModelResponse(output={"keys": ["name"]})
        self.business += 1
        return ModelResponse(output={"name": messages[0]["content"]})


def setup(mode="rule", *, memory=None, provider=None, budget=16, sequence=False):
    memory = InMemoryMemory(backend_id="facts") if memory is None else memory
    provider = Provider() if provider is None else provider
    policy = (ManagedMemoryPolicy if mode == "rule" else ManagedModelMemoryPolicy)(
        memory,
        admission=MemoryAdmissionPolicy({"name": ("result", "name")}),
        namespace="observations",
    )
    runtime = TemporalRuntime(
        providers={"default": provider}, tools=ToolRegistry(), stage_policy=policy
    )
    spec = (
        WorkflowSpec("w", [AgentSpec("a", "first"), AgentSpec("b", "second")])
        if sequence
        else AgentSpec("a", "first")
    )
    state = TemporalRunState(
        "run",
        asdict(Scope()),
        "s",
        submission_request(spec, "task", budget=budget),
        json.loads(canonical(runtime.manifest)),
    )
    return runtime, state, provider, memory


async def step(runtime, state):
    operation = state.next_operation()
    if operation is None:
        return None
    action, request = operation
    if action["kind"] == "managed_memory":
        value = await runtime.manage_memory(request, dispatch_guard=lambda r: grant(state, r))
        state.accept_memory(action["id"], value)
    else:
        value = await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r))
        state.accept_model(action["id"], value)
    return action, request


async def finish(runtime, state):
    for _ in range(60):
        if state.state in {"succeeded", "failed", "cancelled"} and state.active_action is None:
            break
        await step(runtime, state)
    assert state.state == "succeeded", state.snapshot()


@pytest.mark.parametrize("mode", ["rule", "model"])
@pytest.mark.parametrize("sequence", [False, True])
def test_history_memory_writes_grounded_distinct_facts_before_completion(mode, sequence):
    async def run():
        runtime, state, provider, memory = setup(mode, sequence=sequence)
        await finish(runtime, state)
        facts = memory.facts(Scope(), "observations")
        assert len(facts) == (2 if sequence else 1)
        assert {f["value"]["value"] for f in facts} == (
            {"first", "second"} if sequence else {"first"}
        )
        assert len({f["key"] for f in facts}) == len(facts)
        assert all(f["value"]["trust"] == "completed-result-observation" for f in facts)
        assert provider.business == len(facts)
        assert provider.selectors == (len(facts) if mode == "model" else 0)
        assert state.budget["spent"] == len(facts) * (3 if mode == "model" else 2)
        assert state.budget["unknown"] == state.budget["reserved"] == 0
        assert state.quiescent
        restored = copy.deepcopy(state)
        assert restored.next_operation() is None
        assert restored.result == state.result

    asyncio.run(run())


def test_received_selector_response_adopts_after_restart_without_calling_model():
    async def run():
        runtime, state, provider, memory = setup("model")
        for _ in range(10):
            if any(a.get("phase") == "select" for a in state.actions):
                break
            await step(runtime, state)
        assert provider.selectors == 1
        state = copy.deepcopy(state)
        await finish(runtime, state)
        assert provider.selectors == 1 and provider.business == 1
        assert len(memory.facts(Scope(), "observations")) == 1

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["rule", "model"])
def test_optional_memory_budget_exhaustion_preserves_business_result(mode):
    async def run():
        runtime, state, provider, memory = setup(mode, budget=1)
        await finish(runtime, state)
        assert state.result == {"name": "first"}
        assert provider.business == 1 and provider.selectors == 0
        assert memory.facts(Scope(), "observations") == []
        assert state.budget["spent"] == 1 and state.quiescent

    asyncio.run(run())


def test_lost_cas_ack_recovery_reads_only_and_settles_original_credit():
    class LostAck(InMemoryMemory):
        writes = 0

        def put_fact(self, *args, **kwargs):
            self.writes += 1
            super().put_fact(*args, **kwargs)
            raise MemoryBackendError("lost acknowledgement")

    async def run():
        memory = LostAck(backend_id="facts")
        runtime, state, provider, _ = setup(memory=memory)
        await finish(runtime, state)
        assert memory.writes == 1 and len(memory.facts(Scope(), "observations")) == 1
        assert state.budget["unknown"] == 0 and state.budget["spent"] == 2
        assert state.quiescent

    asyncio.run(run())


def test_cancel_during_inspection_never_dispatches_cas():
    class CancelOnRead(InMemoryMemory):
        writes = 0

        async def inspect_fact(self, *args):
            state.command("cancel", {"kind": "cancel", "scope": asdict(Scope())})
            return None

        def put_fact(self, *args, **kwargs):
            self.writes += 1
            return super().put_fact(*args, **kwargs)

    async def run():
        nonlocal state
        runtime, state, provider, memory = setup(memory=CancelOnRead())
        for _ in range(8):
            await step(runtime, state)
            if state.state == "cancelled":
                break
        assert state.state == "cancelled" and memory.writes == 0
        assert state.next_operation() is None
        assert state.budget["reserved"] == state.budget["unknown"] == 0

    state = None
    asyncio.run(run())


def test_cas_timeout_fact_proof_never_proves_remote_handler_stopped():
    async def run():
        runtime, state, provider, memory = setup()
        while True:
            operation = state.next_operation()
            action, request = operation
            if action.get("phase") == "memory-write":
                fact = request["fact"]
                memory.put_fact(
                    Scope(), "observations", fact["key"], fact["value"], expected_version=0
                )
                state.accept_memory(
                    action["id"],
                    {
                        "ok": False,
                        "dispatched": True,
                        "execution_uncertain": True,
                        "code": "activity_outcome_unknown",
                    },
                )
                break
            if action["kind"] == "model":
                state.accept_model(
                    action["id"],
                    await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
                )
            else:
                state.accept_memory(
                    action["id"],
                    await runtime.manage_memory(request, dispatch_guard=lambda r: grant(state, r)),
                )
        await finish(runtime, state)
        assert state.budget["spent"] == 2 and state.budget["unknown"] == 0
        assert not state.quiescent and state.remote_uncertain

    asyncio.run(run())


def test_unknown_selector_keeps_original_credit_and_business_result():
    async def run():
        runtime, state, provider, memory = setup("model")
        await step(runtime, state)
        await step(runtime, state)
        action, request = state.next_operation()
        assert action["phase"] == "select"
        state.accept_memory(
            action["id"], {"ok": False, "dispatched": True, "code": "activity_outcome_unknown"}
        )
        await finish(runtime, state)
        assert state.result == {"name": "first"} and state.budget["unknown"] == 1
        assert not state.quiescent and memory.facts(Scope(), "observations") == []
        assert provider.selectors == 0

    asyncio.run(run())


@pytest.mark.parametrize("output", [{"keys": ["invented"]}, {"keys": ["name", "name"]}, "", None])
def test_invalid_selector_never_writes_but_received_credit_settles(output):
    class Invalid(Provider):
        async def complete(self, messages, tools):
            if messages[0]["content"].startswith("memory-field-selector:"):
                self.selectors += 1
                return ModelResponse(output=output)
            return await super().complete(messages, tools)

    async def run():
        runtime, state, provider, memory = setup("model", provider=Invalid())
        await finish(runtime, state)
        assert state.result == {"name": "first"}
        assert memory.facts(Scope(), "observations") == []
        assert provider.selectors == 1
        assert state.budget["spent"] == 2 and state.budget["unknown"] == 0

    asyncio.run(run())


def test_same_backend_identity_swap_during_read_fails_before_cas():
    class Drift(InMemoryMemory):
        async def inspect_fact(self, *args):
            runtime.stage_policy.memory = replacement
            return None

    async def run():
        nonlocal runtime
        runtime, state, provider, memory = setup(memory=Drift(backend_id="facts"))
        await finish(runtime, state)
        assert state.memory_stages["0"]["error"]["code"] == "definition_mismatch"
        assert (
            memory.facts(Scope(), "observations")
            == replacement.facts(Scope(), "observations")
            == []
        )

    runtime, replacement = None, InMemoryMemory(backend_id="facts")
    asyncio.run(run())


def test_unknown_fact_terminal_drive_only_reads_original_target():
    class LostWrite(InMemoryMemory):
        writes = 0

        def put_fact(self, *args, **kwargs):
            self.writes += 1
            raise MemoryBackendError("no evidence")

    async def run():
        memory = LostWrite(backend_id="facts")
        runtime, state, provider, _ = setup(memory=memory)
        await finish(runtime, state)
        assert state.budget["unknown"] == 1
        fact = state.memory_stages["0"]["facts"][0]
        # Simulate the downstream write becoming visible after a lost acknowledgement.
        InMemoryMemory.put_fact(
            memory, Scope(), "observations", fact["key"], fact["value"], expected_version=0
        )
        before = (memory.writes, provider.business, provider.selectors)
        state.retry_blocked()
        assert state.next_operation()[0]["phase"] == "verify"
        action = state.actions[-1]
        from ralf_agent.temporal_memory_state import _request

        request = _request(state, state.memory_stages["0"], action)
        state.accept_memory(action["id"], await runtime.manage_memory(request))
        assert state.state == "succeeded" and state.budget["unknown"] == 0
        assert state.budget["spent"] == 2
        assert before == (memory.writes, provider.business, provider.selectors)

    asyncio.run(run())


def test_cancel_after_cas_grant_keeps_late_receipt_and_original_budget():
    class CancelOnWrite(InMemoryMemory):
        writes = 0

        def put_fact(self, *args, **kwargs):
            self.writes += 1
            result = super().put_fact(*args, **kwargs)
            state.command("cancel", {"kind": "cancel", "scope": asdict(Scope())})
            return result

    async def run():
        nonlocal state
        runtime, state, provider, memory = setup(memory=CancelOnWrite())
        for _ in range(8):
            await step(runtime, state)
            if state.state == "cancelled":
                break
        assert memory.writes == 1 and state.budget["unknown"] == 1
        state.retry_blocked()
        await step(runtime, state)
        assert state.state == "cancelled" and state.budget["unknown"] == 0
        assert memory.writes == 1 and provider.business == 1

    state = None
    asyncio.run(run())


def test_per_agent_disabled_memory_does_not_inherit_host_write_target():
    async def run():
        runtime, _, provider, memory = setup("model")
        from ralf_agent import AgentBindingDescriptor, AgentDefinition, BindingSelection
        from ralf_agent.temporal_bindings import normalize_request

        request = normalize_request(
            submission_request(
                AgentDefinition(
                    AgentSpec("a", "first"),
                    AgentBindingDescriptor(stage_policy=BindingSelection.disabled()),
                ),
                "task",
            )
        )
        state = TemporalRunState("run", asdict(Scope()), "s", request, runtime.manifest)
        await finish(runtime, state)
        assert state.memory_stages == {} and provider.selectors == 0
        assert memory.facts(Scope(), "observations") == []
        assert state.budget["spent"] == 1

    asyncio.run(run())


def test_legacy_recall_without_exact_inspection_is_refused_at_registration():
    memory = InMemoryMemory()
    memory.fact_inspection_version = None
    from ralf_agent.errors import ValidationError

    with pytest.raises(ValidationError):
        setup(memory=memory)


def test_terminal_sequence_recovers_earlier_member_target_after_next_member_finished():
    class LostWrite(InMemoryMemory):
        writes = 0

        def put_fact(self, *args, **kwargs):
            self.writes += 1
            raise MemoryBackendError("not visible")

    async def run():
        from ralf_agent import (
            AgentBindingDescriptor,
            BindingCatalog,
            BindingSelection,
            BoundDefinition,
        )
        from ralf_agent.temporal_bindings import normalize_request

        first, second = LostWrite(backend_id="first"), InMemoryMemory(backend_id="second")
        admission = MemoryAdmissionPolicy({"name": ("result", "name")})
        catalog = BindingCatalog(scope=Scope())
        catalog.register(
            "stage_policy",
            "first",
            "1",
            ManagedMemoryPolicy(first, admission=admission, namespace="one"),
        )
        catalog.register(
            "stage_policy",
            "second",
            "1",
            ManagedModelMemoryPolicy(second, admission=admission, namespace="two"),
        )

        def descriptor(name):
            return AgentBindingDescriptor(stage_policy=BindingSelection.ref(name, "1"))

        spec = BoundDefinition(
            WorkflowSpec("w", [AgentSpec("same", "first"), AgentSpec("same", "second")]),
            {"sequence/steps/0": descriptor("first"), "sequence/steps/1": descriptor("second")},
        )
        provider = Provider()
        runtime = TemporalRuntime(
            providers={"default": provider}, tools=ToolRegistry(), binding_catalog=catalog
        )
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "s",
            normalize_request(submission_request(spec, "task")),
            json.loads(canonical(runtime.manifest)),
        )
        await finish(runtime, state)
        assert (
            state.result == {"name": "second"}
            and state.budget["unknown"] == 1
            and not state.quiescent
        )
        fact = state.memory_stages["0"]["facts"][0]
        InMemoryMemory.put_fact(
            first, Scope(), "one", fact["key"], fact["value"], expected_version=0
        )
        state.retry_blocked()
        await step(runtime, state)
        assert state.quiescent and state.budget["unknown"] == 0
        assert state.budget["spent"] == 5 and first.writes == 1 and provider.selectors == 1
        assert first.facts(Scope(), "one")[0]["value"]["value"] == "first"
        assert second.facts(Scope(), "two")[0]["value"]["value"] == "second"

    asyncio.run(run())
