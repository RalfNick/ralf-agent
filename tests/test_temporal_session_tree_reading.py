"""Closed Coding Session trees retain every original SDK fact and one final origin read-set."""

import asyncio
import copy
from collections import Counter
from types import SimpleNamespace

import pytest

from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, TeamSpec
from ralf_agent import temporal_coding_composition_state as composition
from ralf_agent import temporal_deployment_execution as execution
from ralf_agent import temporal_deployment_execution_state as admission
from ralf_agent import temporal_deployment_release as release
from ralf_agent import temporal_deployment_release_state as closure
from ralf_agent import temporal_session_deployment_verification as verification
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_parent_state import PARENT_WORKFLOW_NAME, TemporalParentState
from ralf_agent.temporal_session_deployment_control import _CheckedClient
from ralf_agent.temporal_session_state import SESSION_ACTIVITY
from ralf_agent.temporal_state import WORKFLOW_NAME, TemporalRunState
from ralf_agent.types import digest
from tests import test_temporal_session_coding_child_identity as child_fixture
from tests.test_temporal_session_deployment_control import BusinessHandle, Client, Handle, Runtime
from tests.test_temporal_session_deployment_dto import origin
from tests.test_temporal_session_deployment_execution import admit, initialize


def tree_environment(monkeypatch, *, validation_class=None, nested_depth=1):
    captured = {}
    session_class = child_fixture.TemporalSessionState

    def session(*args, **kwargs):
        captured["session"] = session_class(*args, **kwargs)
        return captured["session"]

    monkeypatch.setattr(child_fixture, "TemporalSessionState", session)
    monkeypatch.setattr(
        child_fixture,
        "GraphWorkflowSpec",
        lambda *args: GraphWorkflowSpec(
            "three",
            [GraphNode(name, agent=AgentSpec(name, "answer")) for name in ("a", "b", "c")],
            max_concurrency=3,
        ),
    )
    definition = None
    if nested_depth > 1:
        definition = AgentSpec("leaf", "answer")
        for index in range(nested_depth):
            definition = TeamSpec(f"level-{index}", {"child": definition})
    parent, _ = child_fixture.original_child(definition)
    intent = captured["session"].deployment_turn().intent
    composition.adopt_admission(
        parent,
        {"namespace": intent["namespace"], "execution_epoch": parent.epoch, "admitted": True},
    )
    assert len(parent.children) == (3 if nested_depth == 1 else 1)
    states = {parent.run_id: parent}

    def close_tree(parent):
        for index, call in enumerate(parent.children):
            epoch = (
                f"child-{index}-epoch"
                if nested_depth == 1
                else f"child-{parent.depth}-{index}-epoch"
            )
            call.update(
                started=True,
                dispatch_started=True,
                settled=True,
                uncertain=False,
                state="succeeded",
                deployment_execution_epoch=epoch,
            )
            composition.pin_child_execution(
                parent,
                call["run_id"],
                {
                    "namespace": intent["namespace"],
                    "execution_epoch": epoch,
                    "original_execution_epoch": epoch,
                    "request_digest": digest(call["request"]),
                    "parent_run_id": parent.run_id,
                    "parent_execution_epoch": parent.epoch,
                },
            )
            cls = (
                TemporalParentState
                if call["request"]["definition"]["kind"] == "team"
                else TemporalRunState
            )
            extra = {"depth": call["depth"]} if cls is TemporalParentState else {}
            child = cls(
                call["run_id"],
                parent.scope,
                call["command_id"],
                call["request"],
                parent.manifest,
                epoch,
                **extra,
            )
            initialize(
                child,
                call["deployment_admission"],
                {
                    "namespace": intent["namespace"]["name"],
                    "workflow_id": parent.run_id,
                    "run_id": parent.epoch,
                },
            )
            admit(child)
            composition.initialize(child, namespace=intent["namespace"]["name"])
            composition.validate_child_link(
                child,
                namespace=intent["namespace"]["name"],
                parent_namespace=intent["namespace"]["name"],
                parent_run_id=parent.run_id,
                parent_epoch=parent.epoch,
                original_epoch=epoch,
            )
            states[child.run_id] = child
            if isinstance(child, TemporalParentState):
                member = next(iter(child.definition["members"]))
                child.accept_selection(
                    {
                        "calls": [
                            {"id": "nested", "member": member, "input": child.request["input"]}
                        ],
                        "done": False,
                        "result": None,
                    }
                )
                child.next_calls()
                composition.adopt_admission(
                    child,
                    {"namespace": intent["namespace"], "execution_epoch": epoch, "admitted": True},
                )
                close_tree(child)
            child.state = "succeeded"
            if not isinstance(child, TemporalParentState):
                closure.initialize(child)
                assert closure.closure(child) == (True, [])
                closure.seal(child, {"scope": child.scope, "children": []})
            composition.adopt_child_stop(
                parent, child.run_id, composition.physical_stop_view(child)
            )
            states[child.run_id] = child
        parent.state = "succeeded"
        for reservation in parent.reservations.values():
            reservation["status"] = "settled"
        closure.initialize(parent)
        return closure.seal(
            parent,
            {
                "scope": parent.scope,
                "children": [
                    release._child_entry(call, states[call["run_id"]].deployment_seal)
                    for call in parent.children
                ],
            },
        )

    certificate = close_tree(parent)
    wire = {
        "version": 1,
        "mode": "observe",
        "intent": intent,
        **{
            key: intent[key]
            for key in ("scope", "namespace", "coordinator_id", "coordinator_execution_epoch")
        },
    }
    client = Client(wire)
    runtime = Runtime(copy.deepcopy(parent.manifest))
    from tests.test_temporal_deployment_session_registry import POLICY

    runtime._deployment_admission_policy = runtime._deployment_admission_policy_pin = POLICY
    runtime._deployment_admission_identity = POLICY.identity
    record = {
        "reservation": {"root_admission": copy.deepcopy(parent.deployment_admission["root"])},
        "submission": copy.deepcopy(intent["submission"]),
        "run_receipt": None,
        "execution_epoch": parent.epoch,
        "intent": copy.deepcopy(intent),
        "session_origin": origin(intent),
    }
    client.reads, client.writes, client.hook = Counter(), [], None
    client.states, client.record = states, record
    registry_id = parent.deployment_admission["root"]["registry_id"]

    class TreeHandle(BusinessHandle):
        def __init__(self, identity, epoch):
            super().__init__(client, epoch)
            self.identity = identity

        async def describe(self):
            state = states[self.identity]
            client.member = self.identity
            client.reads[(self.identity, "describe")] += 1
            metadata = state.deployment_admission
            parent_id, parent_epoch = (
                (
                    metadata["lineage"][-1]["parent_run_id"],
                    metadata["lineage"][-1]["parent_execution_epoch"],
                )
                if metadata["lineage"]
                else (intent["coordinator_id"], intent["coordinator_execution_epoch"])
            )
            return SimpleNamespace(
                id=state.run_id,
                run_id=state.epoch,
                namespace=client.namespace,
                task_queue=intent["submission"]["task_queue"],
                workflow_type=PARENT_WORKFLOW_NAME
                if isinstance(state, TemporalParentState)
                else WORKFLOW_NAME,
                parent_id=parent_id,
                parent_run_id=parent_epoch,
                raw_info=SimpleNamespace(first_run_id=state.epoch),
            )

        async def query(self, name, value):
            kind = value["kind"]
            client.reads[(self.identity, kind)] += 1
            if self.identity == registry_id:
                assert kind == "deployment_session_root"
                result = copy.deepcopy(record)
            else:
                state = states[self.identity]
                if kind == "deployment_admission":
                    result = admission.view(state)
                elif kind == "deployment_closure":
                    result = closure.view(state)
                elif kind == "deployment_start":
                    result = {
                        "scope": state.scope,
                        "run_id": state.run_id,
                        "execution_epoch": state.epoch,
                        "activity_timeout": intent["submission"]["activity_timeout"],
                        "task_queue": intent["submission"]["task_queue"],
                        "request_digest": digest(state.request),
                        "manifest_digest": digest(state.manifest),
                    }
                else:
                    raise AssertionError(kind)
            if client.hook:
                client.hook(self.identity, kind, result)
            if getattr(client, "block", None):
                await client.block(self.identity, kind)
            return result

        async def execute_update(self, name, value, **kwargs):
            client.writes.append(name)
            raise AssertionError("Closed-tree reading attempted an SDK write")

    def handle(identity, *, run_id=None):
        if identity == intent["coordinator_id"]:
            return Handle(client, run_id)
        assert identity == registry_id or identity in states
        return TreeHandle(identity, run_id)

    client.get_workflow_handle = handle
    info = SimpleNamespace(
        workflow_id=intent["coordinator_id"],
        workflow_run_id=intent["coordinator_execution_epoch"],
        workflow_namespace=client.namespace,
        activity_id="observe",
        activity_type=SESSION_ACTIVITY,
        attempt=1,
        task_queue=intent["binding"]["task_queue"],
    )
    validation = (validation_class or verification.SessionControlValidation)(
        runtime,
        client,
        wire,
        info,
        deployment_id=parent.manifest["deployment_admission_protocol"]["policy"]["deployment_id"],
    )
    return validation, client, parent, certificate


async def ready(monkeypatch, **kwargs):
    validation, client, parent, certificate = tree_environment(monkeypatch, **kwargs)
    policy = execution._policy(validation.runtime)
    readonly = _CheckedClient(validation, _aggregate=True)
    proof = await execution._proof(
        validation.runtime,
        readonly,
        policy,
        parent.scope,
        parent.run_id,
        parent.epoch,
        required=True,
    )
    client.events.clear()
    client.reads.clear()
    return validation, client, parent, certificate, readonly, policy, proof


def test_closed_tree_keeps_run_registry_start_reads_and_one_final_raw_session_group(monkeypatch):
    async def run():
        validation, client, parent, certificate = tree_environment(monkeypatch)
        policy = execution._policy(validation.runtime)
        readonly = _CheckedClient(validation, _aggregate=True)
        proof = await execution._proof(
            validation.runtime,
            readonly,
            policy,
            parent.scope,
            parent.run_id,
            parent.epoch,
            required=True,
        )
        client.events.clear()
        client.reads.clear()
        baseline = await release._tree(validation.runtime, readonly, policy, proof, seal=False)
        baseline_reads = client.reads.copy()
        assert baseline == certificate and client.events.count("history") == 13
        client.events.clear()
        client.reads.clear()
        reader = getattr(verification, "_read_session_tree", None)
        result = (
            await reader(validation, readonly, policy, proof)
            if reader is not None
            else await release._tree(validation.runtime, readonly, policy, proof, seal=False)
        )
        assert result == certificate
        assert client.reads == baseline_reads
        assert client.events.count("history") == 1
        assert client.events.count("deployment_session_intent") == 1
        assert client.events.count("deployment_session_command") == 1
        assert client.events.count("describe") == 2
        assert Counter(client.events[-7:]) == Counter(
            {
                "namespace": 2,
                "describe": 2,
                "history": 1,
                "deployment_session_intent": 1,
                "deployment_session_command": 1,
            }
        )
        assert client.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("member", [0, 1, 2])
@pytest.mark.parametrize("field", ["intent", "session_origin"])
def test_each_member_registry_must_keep_original_session_identity(monkeypatch, member, field):
    async def run():
        validation, client, parent, _, readonly, policy, proof = await ready(monkeypatch)
        target = parent.children[member]["run_id"]

        def changed(identity, kind, result):
            if kind == "deployment_session_root" and client.member == target:
                result[field]["intent_digest"] = "f" * 64

        client.hook = changed
        with pytest.raises(DefinitionMismatch):
            await verification._read_session_tree(validation, readonly, policy, proof)
        assert client.reads[(target, "deployment_admission")] >= 1
        assert client.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["start", "epoch"])
def test_final_raw_session_facts_refuse_change_after_last_tree_read(monkeypatch, fault):
    async def run():
        validation, client, parent, _, readonly, policy, proof = await ready(monkeypatch)

        def changed(identity, kind, result):
            if (
                identity == parent.run_id
                and kind == "deployment_closure"
                and client.reads[(identity, kind)] == 2
            ):
                if fault == "start":
                    client.accepted["scope"] = {**client.accepted["scope"], "principal": "foreign"}
                else:
                    client.epoch = "reset-original-session"

        client.hook = changed
        with pytest.raises(DefinitionMismatch):
            await verification._read_session_tree(validation, readonly, policy, proof)
        assert ("history" if fault == "start" else "describe") in client.events
        assert client.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["seal", "pin"])
def test_incomplete_tree_refuses_without_sealing_or_pinning_write(monkeypatch, fault):
    async def run():
        validation, client, parent, _, readonly, policy, proof = await ready(monkeypatch)
        call = parent.children[0]
        if fault == "seal":
            client.states[call["run_id"]].deployment_seal = None
        else:
            call["deployment_execution_epoch"] = None
        with pytest.raises(DefinitionMismatch):
            await verification._read_session_tree(validation, readonly, policy, proof)
        assert not hasattr(readonly.get_workflow_handle(parent.run_id), "execute_update")
        assert client.writes == []

    asyncio.run(run())


@pytest.mark.parametrize(
    "port",
    ["_read_admission", "_start_record", "_start_record_binding", "reader-class", "reader-method"],
)
def test_source_ports_cannot_change_during_member_read(monkeypatch, port):
    async def run():
        validation, client, _, _, readonly, policy, proof = await ready(monkeypatch)

        def changed(identity, kind, result):
            if kind != "deployment_start":
                return
            if port == "reader-class":

                class Replacement(verification._SessionTreeReading):
                    pass

                monkeypatch.setattr(verification, "_SessionTreeReading", Replacement)
            elif port == "reader-method":
                monkeypatch.setattr(verification._SessionTreeReading, "_node", lambda *args: None)
            else:
                monkeypatch.setattr(execution, port, lambda *args: None)

        client.hook = changed
        with pytest.raises(DefinitionMismatch):
            await verification._read_session_tree(validation, readonly, policy, proof)
        assert client.writes == []

    asyncio.run(run())


def test_fake_outer_validation_does_not_replace_final_raw_seven_facts(monkeypatch):
    class OuterValidation(verification.SessionControlValidation):
        async def validate(self):
            raise AssertionError("Outer validation must not supply the final SDK evidence")

    async def run():
        validation, client, _, certificate, readonly, policy, proof = await ready(
            monkeypatch, validation_class=OuterValidation
        )
        assert (
            await verification._read_session_tree(validation, readonly, policy, proof)
            == certificate
        )
        assert client.events.count("history") == 1
        assert client.events.count("deployment_session_intent") == 1
        assert client.events.count("deployment_session_command") == 1
        assert client.events.count("describe") == 2

    asyncio.run(run())


def test_cancelled_tree_read_settles_original_read_without_returning_certificate(monkeypatch):
    async def run():
        validation, client, _, _, readonly, policy, proof = await ready(monkeypatch)
        entered, stopped = asyncio.Event(), asyncio.Event()

        async def block(identity, kind):
            if kind == "deployment_start":
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

        client.block = block
        task = asyncio.create_task(
            verification._read_session_tree(validation, readonly, policy, proof)
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set() and client.writes == []

    asyncio.run(run())


def test_default_ordinary_proof_keeps_original_full_session_checks():
    from tests.test_temporal_session_deployment_control import positive_observation

    async def run():
        validation, client = positive_observation()
        intent = validation.intent
        policy = execution._policy(validation.runtime)
        client.events.clear()
        proof = await execution._proof(
            validation.runtime,
            client,
            policy,
            intent["scope"],
            intent["run_id"],
            client.business_epoch,
            required=True,
        )
        assert proof == client.business_closure["deployment"]
        assert client.events.count("history") == 2
        assert client.events.count("deployment_session_intent") == 2
        assert client.events.count("deployment_session_command") == 2
        with pytest.raises(DefinitionMismatch):
            await verification._read_session_tree(
                validation, _CheckedClient(validation), policy, proof
            )

    asyncio.run(run())
