"""Original Session and Run Histories publish complete accepted Agent episodes."""

import asyncio
import copy
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, Scope, ToolCall, ToolRegistry, WorkflowSpec
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
from ralf_agent.model_history import CompleteModelHistory
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_session_state import TemporalSessionState
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import digest, submission_request
from tests.test_temporal_memory_bindings import grant


class SessionPolicy(CompleteModelHistory):
    """Explicit frame policy keeps tests runnable before the public factory is added."""

    @property
    def identity(self):
        return {
            "kind": "complete-model-history",
            "version": "2",
            "scope": "session",
            "allow_tool_result_projection": False,
        }

    def assemble_frame(self, frame, references, max_chars, *, context):
        return CompleteModelHistory(scope="session").assemble_frame(
            frame, references, max_chars, context=context
        )

    def validate_frame(self, frame, messages):
        from ralf_agent.session_model_history import validate_model_history_frame

        validate_model_history_frame(frame, messages)


class SignedTools:
    identity = {"kind": "session-native-signed-tools", "version": "1"}

    def __init__(self):
        self.calls = []

    @property
    def continuation_identity(self):
        return {"protocol": "session-signed-v1", "owner_digest": digest(self.identity)}

    async def complete(self, messages, tools):
        self.calls.append(copy.deepcopy(messages))
        last_user = max(i for i, item in enumerate(messages) if item["role"] == "user")
        current = messages[last_user + 1 :]
        calls = (
            []
            if any(m["role"] == "tool" for m in current)
            else [ToolCall("one", {}, "same-call-one"), ToolCall("two", {}, "same-call-two")]
        )
        output = ' { "answer" : 42 } ' if not calls else None
        return ContinuedModelResponse(
            output=output,
            tool_calls=calls,
            continuation=ModelContinuation(
                "session-signed-v1",
                digest(self.identity),
                digest({"output": output, "tool_calls": [asdict(c) for c in calls]}),
                {"signature": "opaque-signature", "serial": len(self.calls)},
            ),
        )


def one():
    return {"exact": "one"}


def two():
    return {"exact": "two"}


def setup(definition=None, *, policy=True, provider=None, **options):
    provider = provider or SignedTools()
    tools = ToolRegistry()
    tools.register_function(one, effect="read_only")
    tools.register_function(two, effect="read_only")
    host = TemporalRuntime(
        providers={"default": provider},
        tools=tools,
        enable_sessions=True,
        model_continuation=True,
        model_history=CompleteModelHistory(scope="session") if policy is True else policy,
        **options,
    )
    definition = definition or AgentSpec("answer", "Answer", tools=("one", "two"))
    from ralf_agent.temporal_bindings import normalize_request

    session = TemporalSessionState(
        {
            "scope": asdict(Scope()),
            "namespace_id": "actual-ns",
            "session_namespace": None,
            "session_id": "chat",
            "command_id": "open",
            "request": normalize_request(submission_request(definition, None)),
            "manifest": host.orchestration_release,
            "task_queue": "q",
            "activity_timeout": 3,
        }
    )
    return host, session, provider


async def drive(host, state):
    async def context_grant(request):
        if "execution_epoch" not in request:
            return await grant(state, request)
        return state.admit_context_dispatch(
            {
                **{
                    k: request[k]
                    for k in (
                        "scope",
                        "run_id",
                        "action_id",
                        "release_digest",
                        "phase",
                        "execution_epoch",
                    )
                },
                "request_digest": digest(request),
            }
        )

    async def context_end(proof):
        state.context_execution_ended(proof)

    async def session_end(proof):
        state.session_execution_ended(proof)

    for _ in range(90):
        while state.pending_acks:
            response = await host.acknowledge_evidence(state.pending_acks.pop(0))
            assert response["ok"]
        operation = state.next_operation()
        if operation is None:
            break
        action, request = operation
        if action["kind"] == "context":
            state.accept_context(
                action["id"],
                await host.prepare_context(
                    request, dispatch_guard=context_grant, on_end=context_end
                ),
            )
        elif action["kind"] == "managed_context":
            state.accept_managed_context(
                action["id"],
                await host.manage_context(
                    request, dispatch_guard=context_grant, on_end=context_end
                ),
            )
        elif action["kind"] == "model":
            state.accept_model(
                action["id"],
                await host.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
            )
        elif action["kind"] == "model_adoption":
            state.accept_model_adoption(action["id"], await host.adopt_model(request))
        elif action["kind"] == "tool":
            state.accept_tool(
                action["id"],
                await host.execute_tool(request, dispatch_guard=lambda r: grant(state, r)),
            )
        elif action["kind"] == "managed_session":
            state.accept_session(
                action["id"],
                await host.manage_session(
                    request, dispatch_guard=lambda r: grant(state, r), on_end=session_end
                ),
            )
        elif action["kind"] == "agent_completion":
            state.accept_completion(action["id"], await host.verify_completion(request))
        else:
            raise AssertionError(action)
    return state


async def execute(host, session, command, task):
    session.command(
        {
            "kind": "submit",
            "scope": session.scope,
            "command_id": command,
            "session_ref": session.ref.to_dict(),
            "input": task,
            "budget": 32,
        }
    )
    accepted = session.active
    state = TemporalRunState(
        accepted["run_id"],
        session.scope,
        accepted["command_id"],
        accepted["request"],
        accepted["manifest"],
    )
    await drive(host, state)
    assert state.state == "succeeded", state.diagnostics()
    assert session.adopt_observation(
        {"scope": session.scope, "request": state.request, **state.diagnostics()}
    )
    return state


def test_native_two_turns_send_exact_signed_tool_episode_and_current_task():
    async def run():
        host, session, provider = setup()
        first = await execute(host, session, "first", "turn-one")
        second = await execute(host, session, "second", "turn-two")
        assert host.manifest["binding_protocol"] == 8
        assert host.manifest["model_history_protocol"] == 2
        assert provider.calls[2] == first.messages + [{"role": "user", "content": "turn-two"}]
        assert second.messages[1] == {"role": "user", "content": "turn-two"}
        assert second.current_task == "turn-two"
        episodes = first.diagnostics()["native_history_episodes"]
        assert len(episodes) == 1 and episodes[0]["history"] == first.messages
        assert episodes[0]["source"]["root_run_id"] == first.run_id
        assert episodes[0]["source"]["turn_seq"] == 1
        assert episodes[0]["source"]["turn_id"] == first.request["session_turn"]["turn_id"]
        assert len(session.native_history[episodes[0]["stream"]]) == 2
        assert not session.history  # Native default never clips into normalized pairs.
        assert not any((m.get("content") or "").startswith("Reference") for m in provider.calls[2])

    asyncio.run(run())


def test_sequence_freezes_each_actual_episode_before_node_reset():
    async def run():
        schema = {"type": "object", "properties": {"answer": {"type": "integer"}}}
        definition = WorkflowSpec(
            "seq",
            [
                AgentSpec("a", "A", tools=("one", "two"), output_schema=schema),
                AgentSpec("b", "B", tools=("one", "two"), output_schema=schema),
            ],
        )
        host, session, provider = setup(definition)
        first = await execute(host, session, "first", "turn-one")
        second = await execute(host, session, "second", "turn-two")
        frozen = first.diagnostics()["native_history_episodes"]
        assert len(frozen) == 2 and frozen[0]["stream"] != frozen[1]["stream"]
        assert frozen[0]["history"][1]["content"] == "turn-one"
        assert frozen[1]["history"][1]["content"] == '{"answer":42}'
        assert provider.calls[4] == frozen[0]["history"] + [{"role": "user", "content": "turn-two"}]
        assert provider.calls[6] == frozen[1]["history"] + [
            {"role": "user", "content": '{"answer":42}'}
        ]
        assert second.current_task == {"answer": 42}

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_native_context_uses_current_task_and_preserves_all_past_messages(managed):
    from ralf_agent.managed_context import ManagedContextPipeline

    class Knowledge:
        identity = {"kind": "current-task-capture", "version": "1"}
        limit, max_chars = 4, 256

        def __init__(self):
            self.queries = []

        async def references(self, scope, query):
            self.queries.append(query)
            return []

        async def validate(self, scope, references):
            return None

    async def run():
        knowledge = Knowledge()
        host, session, provider = setup(
            knowledge=knowledge, context_builder=ManagedContextPipeline() if managed else None
        )
        try:
            first = await execute(host, session, "first", "turn-one")
            second = await execute(host, session, "second", "turn-two")
            assert knowledge.queries == ["turn-one", "turn-one", "turn-two", "turn-two"]
            assert provider.calls[2] == first.messages + [second.messages[1]]
        finally:
            await host.close_context_execution()

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_external_native_history_is_saved_at_isolated_original_session_address(managed):
    from ralf_agent import InMemoryMemory
    from ralf_agent.session_model_history import native_history_address

    async def run():
        backend = InMemoryMemory()
        from ralf_agent.managed_context import ManagedContextPipeline

        host, session, provider = setup(
            session_store=backend,
            session_writes=True,
            context_builder=ManagedContextPipeline() if managed else None,
        )
        try:
            first = await execute(host, session, "first", "turn-one")
            episode = first.diagnostics()["native_history_episodes"][0]
            address = native_history_address(episode["stream"])
            revision, items = backend.read(Scope(), address)
            assert revision == 1 and items == [episode]
            second = await execute(host, session, "second", "turn-two")
            assert provider.calls[2] == first.messages + [second.messages[1]]
            assert backend.read(Scope(), address)[0] == 2
            assert first.context_snapshot["native_history_snapshot"]["revision"] == 0
            assert second.context_snapshot["native_history_snapshot"]["revision"] == 1
        finally:
            await host.close_context_execution()
            await host.close_session_execution()

    asyncio.run(run())


@pytest.mark.parametrize("changed", ["stream", "task", "receipt"])
def test_session_history_refuses_forged_native_source_without_publication(changed):
    async def run():
        host, session, _ = setup()
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "first",
                "session_ref": session.ref.to_dict(),
                "input": "turn-one",
                "budget": 32,
            }
        )
        accepted = session.active
        state = TemporalRunState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        await drive(host, state)
        proof = {"scope": session.scope, "request": state.request, **state.diagnostics()}
        envelope = proof["native_history_episodes"][0]
        if changed == "stream":
            envelope["stream"] = "f" * 64
        elif changed == "task":
            envelope["history"][1]["content"] = "forged original task"
        else:
            envelope["history"][3]["content"] = "forged receipt"
        with pytest.raises((ValidationError, DefinitionMismatch)):
            session.adopt_observation(proof)
        assert not session.native_history and session.snapshot()["busy"]

    asyncio.run(run())


@pytest.mark.parametrize("root_state", ["failed", "cancelled"])
def test_original_root_failure_never_publishes_frozen_partial_episode(root_state):
    async def run():
        definition = WorkflowSpec(
            "partial",
            [
                AgentSpec("first", "Answer", tools=("one", "two")),
                AgentSpec(
                    "second", "Other", tools=("one", "two"), output_schema={"type": "integer"}
                ),
            ],
        )
        host, session, _ = setup(definition)
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "first",
                "session_ref": session.ref.to_dict(),
                "input": "turn-one",
                "budget": 32,
            }
        )
        accepted = session.active
        state = TemporalRunState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        if root_state == "failed":
            await drive(host, state)
            assert (
                state.state == "failed"
            )  # Original second Agent output validation closes the root.
        else:
            while state.node == 0:
                action, request = state.next_operation()
                if action["kind"] == "context":
                    state.accept_context(action["id"], await host.prepare_context(request))
                elif action["kind"] == "model":
                    state.accept_model(
                        action["id"],
                        await host.complete_model(
                            request, dispatch_guard=lambda r: grant(state, r)
                        ),
                    )
                elif action["kind"] == "model_adoption":
                    state.accept_model_adoption(action["id"], await host.adopt_model(request))
                else:
                    state.accept_tool(
                        action["id"],
                        await host.execute_tool(request, dispatch_guard=lambda r: grant(state, r)),
                    )
                while state.pending_acks:
                    assert (await host.acknowledge_evidence(state.pending_acks.pop(0)))["ok"]
            state.command("cancel-root", {"kind": "cancel", "scope": state.scope})
            assert state.state == "cancelled"
        assert len(state.native_history_episodes) == 1
        assert session.adopt_observation(
            {"scope": session.scope, "request": state.request, **state.diagnostics()}
        )
        assert not session.native_history and not session.snapshot()["busy"]

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["graph", "nested"])
def test_composite_actual_agent_paths_continue_independently_over_two_turns(kind):
    from ralf_agent import GraphNode, GraphWorkflowSpec, TeamSpec
    from ralf_agent.temporal_parent_state import TemporalParentState

    async def run():
        members = [
            GraphNode("left", agent=AgentSpec("same", "Left", tools=("one", "two"))),
            GraphNode("right", agent=AgentSpec("same", "Right", tools=("one", "two"))),
        ]
        definition = GraphWorkflowSpec("g", members, max_concurrency=2)
        if kind == "nested":
            definition = TeamSpec("outer", {"inner": definition}, child_budget=24)
        host, session, provider = setup(definition)

        async def parent_drive(state):
            descendants = []
            if state.kind == "team":
                state.accept_selection(
                    {
                        "calls": [
                            {
                                "id": "changing-turn-call",
                                "member": "inner",
                                "input": state.request["input"],
                            }
                        ],
                        "done": False,
                        "result": None,
                    }
                )
            for _ in range(10):
                calls = state.next_calls()
                if not calls:
                    if state.kind == "team" and state.state not in {"succeeded", "failed"}:
                        state.accept_selection({"calls": [], "done": True, "result": "aggregate"})
                    break
                for call in calls:
                    entry = next(c for c in state.children if c["run_id"] == call["run_id"])
                    entry["dispatch_started"] = True
                    state.mark_started(call["run_id"])
                    cls = (
                        TemporalParentState
                        if call["request"]["definition"]["kind"] in {"graph", "team", "dynamic"}
                        else TemporalRunState
                    )
                    child = cls(
                        call["run_id"],
                        state.scope,
                        call["command_id"],
                        call["request"],
                        state.manifest,
                    )
                    if isinstance(child, TemporalParentState):
                        descendants.extend(await parent_drive(child))
                    else:
                        await drive(host, child)
                    proof = {"scope": state.scope, "request": child.request, **child.diagnostics()}
                    state.observe(call["run_id"], proof)
                    descendants.append(proof)
            assert state.state == "succeeded", state.diagnostics()
            return descendants

        first_episodes = {}
        for seq in (1, 2):
            session.command(
                {
                    "kind": "submit",
                    "scope": session.scope,
                    "command_id": f"turn-{seq}",
                    "session_ref": session.ref.to_dict(),
                    "input": f"turn-{seq}",
                    "budget": 64,
                }
            )
            accepted = session.active
            parent = TemporalParentState(
                accepted["run_id"],
                session.scope,
                accepted["command_id"],
                accepted["request"],
                accepted["manifest"],
            )
            descendants = await parent_drive(parent)
            assert session.adopt_observation(
                {
                    "scope": session.scope,
                    "request": parent.request,
                    **parent.diagnostics(),
                    "descendants": descendants,
                }
            )
            current = [e for proof in descendants for e in proof.get("native_history_episodes", [])]
            assert len(current) == 2
            if seq == 1:
                first_episodes = {e["stream"]: e for e in current}
            else:
                assert set(first_episodes) == {e["stream"] for e in current}
                assert all(len(session.native_history[e["stream"]]) == 2 for e in current)
        assert len(provider.calls) == 8
        assert all(
            any(m["role"] == "tool" for m in call)
            for call in (provider.calls[4], provider.calls[6])
        )

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["ack-loss", "cas-conflict"])
def test_native_original_receipt_recovery_never_resends_model_or_tool(mode):
    from ralf_agent import InMemoryMemory

    class Faulted(InMemoryMemory):
        failed = False
        appends = 0

        def append(self, scope, address, message, *, expected_revision, message_id):
            self.appends += 1
            if message.get("kind") == "ralf-native-model-turn" and not self.failed:
                self.failed = True
                if mode == "cas-conflict":
                    foreign = copy.deepcopy(message)
                    foreign["source"]["turn_id"] += "-foreign"
                    super().append(
                        scope,
                        address,
                        foreign,
                        expected_revision=expected_revision,
                        message_id="foreign",
                    )
                else:
                    super().append(
                        scope,
                        address,
                        message,
                        expected_revision=expected_revision,
                        message_id=message_id,
                    )
                    raise TimeoutError("committed ACK lost")
            return super().append(
                scope, address, message, expected_revision=expected_revision, message_id=message_id
            )

    async def run():
        backend = Faulted()
        host, session, provider = setup(session_store=backend, session_writes=True)
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "first",
                "session_ref": session.ref.to_dict(),
                "input": "turn-one",
                "budget": 32,
            }
        )
        accepted = session.active
        state = TemporalRunState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        try:
            await drive(host, state)
            assert state.state == "waiting_reconciliation"
            assert len(provider.calls) == 2 and backend.appends == 1
            saved = copy.deepcopy(state)
            saved.retry_blocked()
            await drive(host, saved)
            assert len(provider.calls) == 2 and backend.appends == 1
            if mode == "ack-loss":
                assert saved.state == "succeeded"
                assert session.adopt_observation(
                    {"scope": session.scope, "request": saved.request, **saved.diagnostics()}
                )
                assert len(session.native_history) == 1
            else:
                assert saved.state == "waiting_reconciliation" and not session.native_history
                assert saved.session_stages["0"]["intent"]["expected_revision"] == 0
        finally:
            await host.close_context_execution()
            await host.close_session_execution()

    asyncio.run(run())


def test_idle_rebind_changes_native_epoch_without_changing_old_turn_receipt():
    async def run():
        host, session, provider = setup()
        first = await execute(host, session, "first", "turn-one")
        old_receipt = copy.deepcopy(session.receipts["first"])
        session.command(
            {
                "kind": "rebind",
                "scope": session.scope,
                "command_id": "new-epoch",
                "session_ref": session.ref.to_dict(),
                "expected_binding_revision": 1,
                "binding": session.binding,
            }
        )
        second = await execute(host, session, "second", "turn-two")
        assert (
            first.native_history_episodes[0]["stream"]
            != second.native_history_episodes[0]["stream"]
        )
        assert provider.calls[2] == second.messages[:2]
        assert session.receipts["first"] == old_receipt

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["ref-without-host", "disabled", "ref-run"])
def test_each_actual_agent_selects_its_original_history_policy(mode):
    from ralf_agent import AgentBindingDescriptor, AgentDefinition, BindingCatalog, BindingSelection

    async def run():
        catalog = BindingCatalog(scope=Scope())
        selected = CompleteModelHistory(scope="session" if mode == "ref-without-host" else "run")
        catalog.register("model_history", "picked", "1", selected)
        choice = (
            BindingSelection.disabled()
            if mode == "disabled"
            else BindingSelection.ref("picked", "1")
        )
        definition = AgentDefinition(
            AgentSpec("a", "Answer", tools=("one", "two")),
            AgentBindingDescriptor(model_history=choice),
        )
        host, session, provider = setup(
            definition, binding_catalog=catalog, policy=None if mode == "ref-without-host" else True
        )
        first = await execute(host, session, "first", "turn-one")
        second = await execute(host, session, "second", "turn-two")
        if mode == "ref-without-host":
            assert provider.calls[2] == first.messages + [second.messages[1]]
            assert len(session.native_history) == 1
        else:
            assert not session.native_history and "model_history_frame" not in next(
                a["dispatch_request"] for a in second.actions if a["kind"] == "model"
            )
            assert "Reference memory" in str(provider.calls[2])

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_joint_eight_recreates_only_an_original_unadmitted_context_timeout(managed):
    from ralf_agent.managed_context import ManagedContextPipeline

    async def run():
        host, session, provider = setup(
            context_reads=True, context_builder=ManagedContextPipeline() if managed else None
        )
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "first",
                "session_ref": session.ref.to_dict(),
                "input": "turn-one",
                "budget": 32,
            }
        )
        accepted = session.active
        state = TemporalRunState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        try:
            action, original = state.next_operation()
            accept = state.accept_managed_context if managed else state.accept_context
            accept(action["id"], {"ok": False, "code": "activity_outcome_unknown"})
            retry = state.next_operation()
            assert retry is not None and state.state != "failed"
            assert retry[1]["model_history_frame"] == original["model_history_frame"]
            assert not provider.calls
            denied = state.admit_context_dispatch(
                {
                    **{
                        k: original[k]
                        for k in (
                            "scope",
                            "run_id",
                            "action_id",
                            "release_digest",
                            "phase",
                            "execution_epoch",
                        )
                    },
                    "request_digest": digest(original),
                }
            )
            assert denied["allowed"] is False
        finally:
            await host.close_context_execution()

    asyncio.run(run())


def test_actual_harness_cannot_discard_a_published_native_turn():
    from ralf_agent import NativeHarness

    class Truncating(NativeHarness):
        identity = {"kind": "session-truncate-fixture", "version": "1"}

        def prepare(self, spec, messages, tools):
            if sum(m["role"] == "user" for m in messages) >= 2:
                messages = [messages[0], messages[-1]]
            return super().prepare(spec, messages, tools)

    async def run():
        host, session, provider = setup(harness=Truncating())
        await execute(host, session, "first", "turn-one")
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "second",
                "session_ref": session.ref.to_dict(),
                "input": "turn-two",
                "budget": 32,
            }
        )
        accepted = session.active
        state = TemporalRunState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        await drive(host, state)
        assert state.state == "failed" and state.error["code"] == "validation_error"
        assert len(provider.calls) == 2 and not state.native_history_episodes

    asyncio.run(run())


def test_native_external_snapshot_is_in_original_frame_and_is_accepted_once():
    from ralf_agent import InMemoryMemory

    class Observed(InMemoryMemory):
        reads = 0

        def read_page(self, scope, address, query):
            if address.startswith("ralf-native-model-history-v1:"):
                self.reads += 1
            return super().read_page(scope, address, query)

    async def run():
        backend = Observed()
        host, session, _ = setup(session_store=backend, session_writes=True)
        try:
            state = await execute(host, session, "first", "turn-one")
            assert backend.reads == 1
            model = next(a for a in state.actions if a["kind"] == "model")
            assert (
                model["dispatch_request"]["model_history_frame"]["snapshot"]["data"]
                == state.native_history_snapshots["0"]
            )
        finally:
            await host.close_context_execution()
            await host.close_session_execution()

    asyncio.run(run())


@pytest.mark.parametrize("snapshot_id", ["[]", '"opaque"', '{"revision":true}'])
def test_original_history_rejects_malformed_native_snapshot_without_workflow_crash(snapshot_id):
    from ralf_agent import InMemoryMemory

    async def run():
        host, session, provider = setup(session_store=InMemoryMemory(), session_writes=True)
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "first",
                "session_ref": session.ref.to_dict(),
                "input": "turn-one",
                "budget": 32,
            }
        )
        accepted = session.active
        state = TemporalRunState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        action, request = state.next_operation()

        async def admission(value):
            return state.admit_context_dispatch(
                {
                    **{
                        k: value[k]
                        for k in (
                            "scope",
                            "run_id",
                            "action_id",
                            "release_digest",
                            "phase",
                            "execution_epoch",
                        )
                    },
                    "request_digest": digest(value),
                }
            )

        async def ended(proof):
            state.context_execution_ended(proof)

        try:
            response = await host.prepare_context(request, dispatch_guard=admission, on_end=ended)
            assert response["ok"]
            response["native_history_snapshot"]["snapshot_id"] = snapshot_id
            state.accept_context(action["id"], response)
            assert state.state == "failed" and state.error["code"] == "validation_error"
            assert not provider.calls and not state.native_history_snapshots
        finally:
            await host.close_context_execution()
            await host.close_session_execution()

    asyncio.run(run())


def test_mixed_session_publication_is_atomic_when_legacy_pair_cannot_be_adopted():
    from ralf_agent import AgentBindingDescriptor, BindingSelection, BoundDefinition, ModelResponse

    class LargeFinal(SignedTools):
        async def complete(self, messages, tools):
            if messages[0]["content"] == "Large":
                self.calls.append(copy.deepcopy(messages))
                return ModelResponse(output="L" * 300000)
            return await super().complete(messages, tools)

    async def run():
        definition = BoundDefinition(
            WorkflowSpec(
                "mixed",
                [
                    AgentSpec("small", "Answer", tools=("one", "two")),
                    AgentSpec("large", "Large", max_context_chars=400000),
                ],
            ),
            {"sequence/steps/1": AgentBindingDescriptor(model_history=BindingSelection.disabled())},
        )
        host, session, _ = setup(definition, provider=LargeFinal())
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "first",
                "session_ref": session.ref.to_dict(),
                "input": "turn-one",
                "budget": 32,
            }
        )
        accepted = session.active
        state = TemporalRunState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        await drive(host, state)
        assert state.state == "succeeded" and len(state.native_history_episodes) == 1
        assert not session.adopt_observation(
            {"scope": session.scope, "request": state.request, **state.diagnostics()}
        )
        assert session.error["code"] == "session_history_capacity"
        assert not session.native_history and not session.history

    asyncio.run(run())


@pytest.mark.parametrize("allow", [False, True])
def test_session_large_tool_projection_is_explicit_and_keeps_stored_original(allow):
    from ralf_agent import InMemoryArtifactStore, ModelResponse, ToolSpec
    from ralf_agent.data_context import ManagedDataContext

    class Provider:
        identity = {"kind": "session-large-native-result", "version": "1"}

        def __init__(self):
            self.calls = []

        async def complete(self, messages, tools):
            self.calls.append(copy.deepcopy(messages))
            last = max(i for i, message in enumerate(messages) if message["role"] == "user")
            if any(message["role"] == "tool" for message in messages[last + 1 :]):
                return ModelResponse(output="final")
            return ModelResponse(tool_calls=[ToolCall("read", {}, "same-call")])

    async def run():
        provider, tools = Provider(), ToolRegistry()
        tools.register(
            ToolSpec("read", "Read", {"type": "object"}, cost=0), lambda args, ctx: "LARGE" * 2000
        )
        context = ManagedDataContext(
            InMemoryArtifactStore(), tool_result_chars=1024, preview_chars=32
        )
        host = TemporalRuntime(
            providers={"default": provider},
            tools=tools,
            context_builder=context,
            enable_sessions=True,
            model_continuation=True,
            model_history=CompleteModelHistory(scope="session", allow_tool_result_projection=allow),
        )
        session = TemporalSessionState(
            {
                "scope": asdict(Scope()),
                "namespace_id": "ns",
                "session_namespace": None,
                "session_id": "large",
                "command_id": "open",
                "request": submission_request(
                    AgentSpec("a", "Read", tools=("read",), max_context_chars=3000), None
                ),
                "manifest": host.orchestration_release,
                "task_queue": "q",
                "activity_timeout": 3,
            }
        )
        try:
            if allow:
                first = await execute(host, session, "first", "turn-one")
                await execute(host, session, "second", "turn-two")
                assert len(provider.calls) == 4
                assert (
                    first.native_history_episodes[0]["history"][3]["content"]
                    == '"' + "LARGE" * 2000 + '"'
                )
                assert all(
                    len(message["content"]) < 3000
                    for message in provider.calls[2]
                    if message["role"] == "tool"
                )
            else:
                session.command(
                    {
                        "kind": "submit",
                        "scope": session.scope,
                        "command_id": "first",
                        "session_ref": session.ref.to_dict(),
                        "input": "turn-one",
                        "budget": 32,
                    }
                )
                accepted = session.active
                state = TemporalRunState(
                    accepted["run_id"],
                    session.scope,
                    accepted["command_id"],
                    accepted["request"],
                    accepted["manifest"],
                )
                await drive(host, state)
                assert state.state == "failed" and len(provider.calls) == 1
        finally:
            await host.close_context_execution()

    asyncio.run(run())


def test_pure_publication_filters_failed_members_under_assumed_successful_root_evidence():
    """Predicate coverage only; current Temporal parent API always fails on a failed child."""
    from ralf_agent import GraphNode, GraphWorkflowSpec
    from ralf_agent.temporal_parent_state import TemporalParentState
    from ralf_agent.temporal_session_model_history import publish

    async def run():
        definition = GraphWorkflowSpec(
            "qualification",
            [
                GraphNode("good", agent=AgentSpec("good", "Answer", tools=("one", "two"))),
                GraphNode(
                    "bad",
                    agent=AgentSpec(
                        "bad", "Other", tools=("one", "two"), output_schema={"type": "integer"}
                    ),
                ),
            ],
            max_concurrency=2,
        )
        host, session, _ = setup(definition)
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "first",
                "session_ref": session.ref.to_dict(),
                "input": "turn-one",
                "budget": 32,
            }
        )
        accepted = session.active
        parent = TemporalParentState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        proofs = []
        for call in parent.next_calls():
            child = TemporalRunState(
                call["run_id"], session.scope, call["command_id"], call["request"], parent.manifest
            )
            await drive(host, child)
            proofs.append({"scope": session.scope, "request": child.request, **child.diagnostics()})
        root_evidence = {"scope": session.scope, "request": parent.request, **parent.diagnostics()}
        root_evidence["snapshot"]["state"] = (
            "succeeded"  # Hypothetical qualification input, not a public execution path.
        )
        candidate = publish(session, [root_evidence, *proofs])
        assert len(candidate) == 1
        assert (
            next(iter(candidate.values()))[0]["source"]["run_id"] == proofs[0]["snapshot"]["run_id"]
        )
        assert (
            proofs[1]["snapshot"]["state"] == "failed" and not proofs[1]["native_history_episodes"]
        )

    asyncio.run(run())


def test_nullable_schema_keeps_accepted_null_final_across_two_native_turns():
    from ralf_agent import ModelResponse

    class Nullable:
        identity = {"kind": "native-session-null", "version": "1"}

        def __init__(self):
            self.calls = []

        async def complete(self, messages, tools):
            self.calls.append(copy.deepcopy(messages))
            return ModelResponse(output=None)

    async def run():
        provider = Nullable()
        host, session, _ = setup(
            AgentSpec("null", "Return null", output_schema={"type": "null"}), provider=provider
        )
        first = await execute(host, session, "first", "turn-one")
        second = await execute(host, session, "second", "turn-two")
        assert first.result is None and second.result is None
        assert first.messages[-1] == {"role": "assistant", "content": None, "tool_calls": []}
        assert provider.calls[1] == first.messages + [second.messages[1]]

    asyncio.run(run())


def test_native_session_publication_enforces_utf8_stream_capacity_atomically(monkeypatch):
    from ralf_agent import ModelResponse
    from ralf_agent import temporal_session_model_history as native
    from ralf_agent.types import canonical

    class UnicodeFinal:
        identity = {"kind": "native-utf8-capacity", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output="原文" * 100)

    async def run():
        host, session, _ = setup(AgentSpec("unicode", "Return text"), provider=UnicodeFinal())
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "first",
                "session_ref": session.ref.to_dict(),
                "input": "task",
                "budget": 8,
            }
        )
        accepted = session.active
        state = TemporalRunState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        await drive(host, state)
        assert state.state == "succeeded"
        encoded = canonical(state.native_history_episodes)
        assert len(encoded.encode("utf-8")) > len(encoded)
        monkeypatch.setattr(native, "MAX_CHARS", len(encoded))
        with pytest.raises(ValidationError):
            session.adopt_observation(
                {"scope": session.scope, "request": state.request, **state.diagnostics()}
            )
        assert not session.native_history

    asyncio.run(run())


@pytest.mark.parametrize("external", [False, True])
def test_full_native_stream_fails_before_model_dispatch_and_releases_session(monkeypatch, external):
    from ralf_agent import InMemoryMemory, ModelResponse
    from ralf_agent import temporal_session_model_history as native

    class SmallFinal:
        identity = {"kind": "bounded-native-final", "version": "1"}

        def __init__(self):
            self.calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            return ModelResponse(output="done")

    async def run():
        monkeypatch.setattr(native, "MAX_TURNS", 2)
        provider = SmallFinal()
        backend = InMemoryMemory() if external else None
        host, session, _ = setup(
            AgentSpec("a", "Answer", max_context_chars=1_000_000),
            provider=provider,
            session_store=backend,
            session_writes=external,
        )
        for seq in (1, 2):
            await execute(host, session, f"turn-{seq}", f"task-{seq}")
        before = copy.deepcopy(session.native_history)
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "full",
                "session_ref": session.ref.to_dict(),
                "input": "too-many",
                "budget": 32,
            }
        )
        accepted = session.active
        state = TemporalRunState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        await drive(host, state)
        assert provider.calls == 2
        assert state.state == "failed" and not state.native_history_episodes
        assert session.adopt_observation(
            {"scope": session.scope, "request": state.request, **state.diagnostics()}
        )
        assert not session.snapshot()["busy"] and session.native_history == before
        await host.close_context_execution()
        await host.close_session_execution()

    asyncio.run(run())


@pytest.mark.parametrize("external", [False, True])
def test_late_native_capacity_failure_is_failed_run_with_no_partial_publication(
    monkeypatch, external
):
    from ralf_agent import InMemoryMemory, ModelResponse
    from ralf_agent import temporal_session_model_history as native
    from ralf_agent.types import canonical

    class GrowingFinal:
        identity = {"kind": "growing-native-final", "version": "1"}

        def __init__(self):
            self.calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            return ModelResponse(output="done" if self.calls == 1 else "原文" * 1000)

    async def run():
        provider = GrowingFinal()
        backend = InMemoryMemory() if external else None
        host, session, _ = setup(
            AgentSpec("a", "Answer", max_context_chars=1_000_000),
            provider=provider,
            session_store=backend,
            session_writes=external,
        )
        await execute(host, session, "first", "task-one")
        before = copy.deepcopy(session.native_history)
        monkeypatch.setattr(native, "MAX_CHARS", len(canonical(next(iter(before.values())))) + 1024)
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "large",
                "session_ref": session.ref.to_dict(),
                "input": "task-two",
                "budget": 32,
            }
        )
        accepted = session.active
        state = TemporalRunState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        await drive(host, state)
        assert provider.calls == 2 and state.state == "failed"
        assert not state.native_history_episodes and not state.session_stages
        assert session.adopt_observation(
            {"scope": session.scope, "request": state.request, **state.diagnostics()}
        )
        assert not session.snapshot()["busy"] and session.native_history == before
        if external:
            from ralf_agent.session_model_history import native_history_address

            assert (
                backend.read(Scope(**session.scope), native_history_address(next(iter(before))))[0]
                == 1
            )
        await host.close_context_execution()
        await host.close_session_execution()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["team", "plan"])
def test_original_parent_rejects_combined_same_stream_episodes_atomically(monkeypatch, kind):
    from ralf_agent import DynamicWorkflowSpec, TeamSpec
    from ralf_agent import temporal_session_model_history as native
    from ralf_agent.orchestration_types import ChildCall, TeamSelection
    from ralf_agent.planning import PlanProposal
    from ralf_agent.temporal_parent_state import TemporalParentState

    async def run():
        monkeypatch.setattr(native, "MAX_TURNS", 1)
        agent = AgentSpec("a", "Answer", tools=("one", "two"))
        definition = (
            TeamSpec("repeat", {"one": agent})
            if kind == "team"
            else DynamicWorkflowSpec("repeat", {"one": agent})
        )
        host, session, _ = setup(definition)
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "first",
                "session_ref": session.ref.to_dict(),
                "input": "task",
                "budget": 32,
            }
        )
        accepted = session.active
        parent = TemporalParentState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        calls = [ChildCall("first", "one", "task-one"), ChildCall("second", "one", "task-two")]
        selection = TeamSelection(calls) if kind == "team" else PlanProposal(calls)
        parent.accept_selection(selection.to_dict())
        proofs = []
        while ready := parent.next_calls():
            for call in ready:
                # Original Workflow records this after registered child control.
                next(c for c in parent.children if c["run_id"] == call["run_id"])[
                    "dispatch_started"
                ] = True
                parent.mark_started(call["run_id"])
                child = TemporalRunState(
                    call["run_id"],
                    session.scope,
                    call["command_id"],
                    call["request"],
                    parent.manifest,
                )
                await drive(host, child)
                assert child.state == "succeeded"
                proof = {"scope": session.scope, "request": child.request, **child.diagnostics()}
                proofs.append(proof)
                parent.observe(child.run_id, proof)
        if kind == "team":
            parent.accept_selection(TeamSelection(done=True, result="done").to_dict())
        else:
            parent.accept_verification({"status": "succeeded", "result": "done"})
        assert len(proofs) == 2 and parent.state == "failed"
        proof = {
            "scope": session.scope,
            "request": parent.request,
            "descendants": proofs,
            **parent.diagnostics(),
        }
        assert session.adopt_observation(proof)
        assert not session.snapshot()["busy"] and not session.native_history

    asyncio.run(run())


def test_failed_root_external_candidates_still_block_physical_stream_capacity(monkeypatch):
    from ralf_agent import InMemoryMemory, ModelResponse
    from ralf_agent import temporal_session_model_history as native
    from ralf_agent.session_model_history import native_history_address

    class Final:
        identity = {"kind": "failed-root-physical-capacity", "version": "1"}

        def __init__(self):
            self.calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            return ModelResponse(output="done")

    async def run():
        monkeypatch.setattr(native, "MAX_TURNS", 2)
        provider, backend = Final(), InMemoryMemory()
        host, session, _ = setup(
            WorkflowSpec(
                "fails",
                [
                    AgentSpec("good", "Answer"),
                    AgentSpec("bad", "Answer", output_schema={"type": "integer"}),
                ],
            ),
            provider=provider,
            session_store=backend,
            session_writes=True,
        )
        current_stream = None
        for seq in (1, 2, 3):
            session.command(
                {
                    "kind": "submit",
                    "scope": session.scope,
                    "command_id": f"turn-{seq}",
                    "session_ref": session.ref.to_dict(),
                    "input": "task",
                    "budget": 32,
                }
            )
            accepted = session.active
            state = TemporalRunState(
                accepted["run_id"],
                session.scope,
                accepted["command_id"],
                accepted["request"],
                accepted["manifest"],
            )
            await drive(host, state)
            assert state.state == "failed"
            if seq < 3:
                current_stream = state.native_history_episodes[0]["stream"]
            else:
                assert not state.native_history_episodes and provider.calls == 4
            assert session.adopt_observation(
                {"scope": session.scope, "request": state.request, **state.diagnostics()}
            )
            assert not session.snapshot()["busy"] and not session.native_history
        assert backend.read(Scope(**session.scope), native_history_address(current_stream))[0] == 2
        await host.close_context_execution()
        await host.close_session_execution()

    asyncio.run(run())
