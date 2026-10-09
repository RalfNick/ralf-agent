"""Pure verification, durable retries and approved effect correspondence."""

import asyncio
import importlib
from contextlib import contextmanager

import pytest

from ralf_agent import AgentSpec, InMemoryMemory, LocalEngine, ModelResponse, Scope, SQLiteStore
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.tools import ToolRegistry, ToolSpec
from ralf_agent.types import ToolCall

from .helpers import ScriptedProvider


def api():
    return importlib.import_module("ralf_agent.completion")


OUTPUT = {"status": "resolved", "ticket": "INC-1"}


def gate(**kwargs):
    return api().ToolReceiptVerifier(
        "repair",
        when={
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"const": "resolved"}},
        },
        result_schema={
            "type": "object",
            "required": ["applied"],
            "properties": {"applied": {"const": True}},
        },
        argument_bindings={"ticket": "/ticket"},
        **kwargs,
    )


def setup(path, provider, verifier, **kwargs):
    return LocalEngine(
        SQLiteStore(path),
        providers={"default": provider},
        tools=kwargs.pop("tools", ToolRegistry()),
        verifier=verifier,
        **kwargs,
    )


def test_values_are_detached_and_immutable():
    c = api()
    request = c.CompletionRequest({"task": [1]}, OUTPUT, [])
    request.task["task"].append(2)
    request.output["ticket"] = "changed"
    assert request.task == {"task": [1]} and request.output == OUTPUT
    with pytest.raises((AttributeError, TypeError)):
        request.output = "changed"
    assert c.SchemaCompletionVerifier().verify(request).status == "accept"


@pytest.mark.parametrize(
    "status,feedback",
    [
        ("succeeded", None),
        ("retry", None),
        ("retry", " "),
        ("retry", "x" * 4097),
        ("accept", "unused"),
    ],
)
def test_invalid_verdicts_fail_closed(status, feedback):
    with pytest.raises(ValidationError):
        api().CompletionVerdict(status, feedback)


@pytest.mark.parametrize(
    "config",
    [
        {"argument_bindings": {"ticket": "ticket"}},
        {"argument_bindings": {"ticket": "/bad~2escape"}},
        {"result_schema": {"type": "invalid"}},
        {"on_missing": "accept"},
    ],
)
def test_invalid_rule_configuration(config):
    with pytest.raises(ValidationError):
        api().ToolReceiptVerifier("repair", **config)


@pytest.mark.parametrize("field", ["when", "result_schema"])
@pytest.mark.parametrize(
    "reference", ["https://remote.invalid/schema.json", "file:///tmp/untrusted.json"]
)
def test_rule_external_schema_refs_never_retrieve_or_change_verdict(monkeypatch, field, reference):
    import io
    import urllib.request

    fetched = []

    def remote(*args, **kwargs):
        fetched.append(args)
        return io.BytesIO(b"false")

    monkeypatch.setattr(urllib.request, "urlopen", remote)
    c = api()
    receipt = {
        "id": "a",
        "tool": "repair",
        "arguments": {},
        "result": {},
        "receipt": {"source": "handler"},
        "effect_key": "e",
    }
    with pytest.raises(ValidationError):
        rule = c.ToolReceiptVerifier("repair", **{field: {"$ref": reference}})
        rule.verify(c.CompletionRequest("q", OUTPUT, [receipt]))
    assert fetched == []


def test_local_schema_refs_remain_usable():
    c = api()
    rule = c.ToolReceiptVerifier(
        "repair", when={"$defs": {"answer": {"type": "object"}}, "$ref": "#/$defs/answer"}
    )
    assert rule.verify(c.CompletionRequest("q", OUTPUT, [])).status == "retry"


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph"])
@pytest.mark.parametrize("task", [{"ticket": "INC-1"}, '{"ticket":"INC-1"}', [1, True], None])
def test_current_task_preserves_json_type_across_execution_forms(tmp_path, kind, task):
    from ralf_agent import GraphNode, GraphWorkflowSpec, WorkflowSpec

    c = api()

    class TypedTaskVerifier:
        identity = {"kind": "typed-task", "version": "1"}

        def verify(self, request):
            return c.CompletionVerdict(
                "accept" if request.task == task and type(request.task) is type(task) else "reject"
            )

    agent = AgentSpec("a", "a")
    spec = (
        agent
        if kind == "agent"
        else WorkflowSpec("s", [agent])
        if kind == "sequence"
        else GraphWorkflowSpec("g", [GraphNode("a", agent=agent)])
    )
    with setup(
        tmp_path / "typed.sqlite",
        ScriptedProvider([ModelResponse(output="ok")]),
        TypedTaskVerifier(),
    ) as engine:
        handle = engine.submit(spec, task, command_id="s")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        record = next(
            a["completion_verification"] for a in done.actions if "completion_verification" in a
        )
        assert record["request"]["task"] == task


def test_sequence_successor_task_is_normalized_predecessor_output(tmp_path):
    from ralf_agent import WorkflowSpec

    c = api()

    class StepVerifier:
        identity = {"kind": "typed-sequence", "version": "1"}

        def verify(self, request):
            wanted = "initial" if request.output == {"ticket": "INC-1"} else {"ticket": "INC-1"}
            return c.CompletionVerdict("accept" if request.task == wanted else "reject")

    spec = WorkflowSpec(
        "s", [AgentSpec("first", "a", output_schema={"type": "object"}), AgentSpec("second", "a")]
    )
    provider = ScriptedProvider(
        [ModelResponse(output='{"ticket":"INC-1"}'), ModelResponse(output="done")]
    )
    with setup(tmp_path / "successor.sqlite", provider, StepVerifier()) as engine:
        handle = engine.submit(spec, "initial", command_id="s")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        records = [
            a["completion_verification"] for a in done.actions if "completion_verification" in a
        ]
        assert records[-1]["request"]["task"] == {"ticket": "INC-1"}


def test_rule_requires_result_and_argument_correspondence():
    c = api()
    receipt = {
        "id": "action",
        "tool": "repair",
        "arguments": {"ticket": "INC-1"},
        "result": {"applied": True},
        "receipt": {"source": "handler"},
        "effect_key": "effect",
    }
    assert gate().verify(c.CompletionRequest("q", OUTPUT, [receipt])).status == "accept"
    receipt["arguments"]["ticket"] = "INC-2"
    assert gate().verify(c.CompletionRequest("q", OUTPUT, [receipt])).status == "retry"
    assert gate().verify(c.CompletionRequest("q", {"status": "needs_input"}, [])).status == "accept"
    assert gate().verify(c.CompletionRequest("q", OUTPUT, [])).status == "retry"


def test_false_resolved_retries_then_requires_approval_and_exactly_one_write(tmp_path):
    writes = []
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "repair",
            "repair",
            {"type": "object", "required": ["ticket"]},
            effect="idempotent_write",
            requires_approval=True,
        ),
        lambda args, ctx: writes.append(args) or {"applied": True},
    )
    provider = ScriptedProvider(
        [
            ModelResponse(output=OUTPUT),
            ModelResponse(tool_calls=[ToolCall("repair", {"ticket": "INC-1"})]),
            ModelResponse(output=OUTPUT),
        ]
    )
    path = tmp_path / "run.sqlite"
    spec = AgentSpec("repairer", "Repair", ("repair",), max_decisions=3)
    with setup(path, provider, gate(), tools=tools) as engine:
        handle = engine.submit(spec, "q", command_id="s")
        waiting = asyncio.run(engine.drive(handle.run_id))
        assert waiting.state == "waiting_approval" and writes == []
        assert "Completion verification" in str(provider.messages[1])
        action = waiting.pending[0]
        approval = engine.approve(
            handle.run_id, action["action_id"], action["digest"], command_id="a"
        )
    with setup(path, provider, gate(), tools=tools) as engine:
        assert (
            engine.approve(handle.run_id, action["action_id"], action["digest"], command_id="a")
            == approval
        )
        done = asyncio.run(engine.drive(handle.run_id))
        assert (
            done.state == "succeeded" and done.result == OUTPUT and writes == [{"ticket": "INC-1"}]
        )
        records = [
            a["completion_verification"] for a in done.actions if "completion_verification" in a
        ]
        assert [r["verdict"]["status"] for r in records] == ["retry", "accept"]
        assert len(records[-1]["request"]["receipts"]) == 1
        assert asyncio.run(engine.drive(handle.run_id)) == done and provider.calls == 3


def test_rejection_does_not_save_final_session(tmp_path):
    memory = InMemoryMemory()
    with setup(
        tmp_path / "reject.sqlite",
        ScriptedProvider([ModelResponse(output=OUTPUT)]),
        gate(on_missing="reject"),
        session_store=memory,
    ) as engine:
        handle = engine.submit(AgentSpec("a", "a"), "q", command_id="s", session_id="session")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "completion_rejected"
        assert memory.read(Scope(), "session") == (0, [])
        assert done.actions[-1]["completion_verification"]["verdict"]["status"] == "reject"


def test_retry_is_bounded_by_existing_decision_limit(tmp_path):
    provider = ScriptedProvider([ModelResponse(output=OUTPUT)] * 3)
    with setup(tmp_path / "limit.sqlite", provider, gate()) as engine:
        handle = engine.submit(AgentSpec("a", "a", max_decisions=2), "q", command_id="s")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "failed" and provider.calls == 2
        assert len([a for a in done.actions if "completion_verification" in a]) == 2


def test_retry_is_bounded_by_existing_credit_reservation(tmp_path):
    provider = ScriptedProvider([ModelResponse(output=OUTPUT)] * 3)
    with setup(tmp_path / "credits.sqlite", provider, gate()) as engine:
        handle = engine.submit(AgentSpec("a", "a", max_decisions=3), "q", command_id="s", budget=1)
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "budget_exceeded"
        assert provider.calls == 1 and engine.diagnostics(handle.run_id).budget["spent"] == 1


def test_cancel_during_verification_does_not_save_or_confirm_result(tmp_path):
    c = api()

    class CancelVerifier:
        identity = {"kind": "cancel-test", "version": "1"}

        def verify(self, request):
            engine.cancel(handle.run_id, command_id="cancel")
            return c.CompletionVerdict("accept")

    memory = InMemoryMemory()
    with setup(
        tmp_path / "cancel.sqlite",
        ScriptedProvider([ModelResponse(output="ok")]),
        CancelVerifier(),
        session_store=memory,
    ) as engine:
        handle = engine.submit(AgentSpec("a", "a"), "q", command_id="s", session_id="session")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "cancelled" and done.result is None
        assert memory.read(Scope(), "session") == (0, [])
        assert "completion_verification" not in done.actions[-1]


def test_original_verifier_identity_is_pinned_on_restart(tmp_path):
    path = tmp_path / "identity.sqlite"
    with setup(path, ScriptedProvider([]), gate()) as engine:
        handle = engine.submit(AgentSpec("a", "a"), "q", command_id="s")
    provider = ScriptedProvider([ModelResponse(output=OUTPUT)])
    with setup(path, provider, gate(on_missing="reject")) as engine:
        with pytest.raises(DefinitionMismatch):
            asyncio.run(engine.drive(handle.run_id))
        assert provider.calls == 0


@pytest.mark.parametrize("kind", ["contextmanager", "dict", "async"])
def test_invalid_verifier_call_or_return_never_confirms_success(tmp_path, kind):
    class Invalid:
        identity = {"kind": "invalid", "version": "1"}

        def verify(self, request):
            if kind == "dict":
                return {"status": "accept"}

            @contextmanager
            def lazy():
                raise RuntimeError("denied")
                yield

            return lazy()

    if kind == "async":

        async def verify(self, request):
            return api().CompletionVerdict("accept")

        Invalid.verify = verify
        with pytest.raises(ValidationError):
            setup(tmp_path / "invalid.sqlite", ScriptedProvider([]), Invalid())
        return
    with setup(
        tmp_path / "invalid.sqlite", ScriptedProvider([ModelResponse(output="ok")]), Invalid()
    ) as engine:
        handle = engine.submit(AgentSpec("a", "a"), "q", command_id="s")
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"


def test_actual_invoked_verifier_cannot_be_replaced_during_call(tmp_path):
    c = api()

    class Verifier:
        identity = {"kind": "mutable", "version": "1"}

        def verify(self, request):
            self.identity = {"kind": "mutable", "version": "2"}
            engine.verifier = replacement
            return c.CompletionVerdict("accept")

    replacement = Verifier()
    with setup(
        tmp_path / "drift.sqlite", ScriptedProvider([ModelResponse(output="ok")]), Verifier()
    ) as engine:
        handle = engine.submit(AgentSpec("a", "a"), "q", command_id="s")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "definition_mismatch"


@pytest.mark.parametrize("status", ["accept", "retry"])
def test_restart_reuses_committed_verification_and_feedback(tmp_path, status):
    c = api()

    class Verifier:
        identity = {"kind": "counted", "version": "1"}
        calls = 0

        def verify(self, request):
            self.calls += 1
            return c.CompletionVerdict(status, "try again" if status == "retry" else None)

    class StopAfterVerification(LocalEngine):
        async def _finish_node(self, run_id, result):
            from ralf_agent.completion_runtime import verify_completion

            verify_completion(self, run_id, result)
            raise RuntimeError("simulated process boundary")

    provider = ScriptedProvider([ModelResponse(output="ok"), ModelResponse(output="ok")])
    path = tmp_path / "restart.sqlite"
    verifier = Verifier()
    with StopAfterVerification(
        SQLiteStore(path), providers={"default": provider}, tools=ToolRegistry(), verifier=verifier
    ) as engine:
        handle = engine.submit(AgentSpec("a", "a", max_decisions=2), "q", command_id="s")
        with pytest.raises(RuntimeError, match="simulated"):
            asyncio.run(engine.drive(handle.run_id))
        original_messages = engine.store.run(handle.run_id)["messages"]
    with setup(path, provider, verifier) as engine:
        done = asyncio.run(engine.drive(handle.run_id))
        assert verifier.calls == (1 if status == "accept" else 2)
        assert provider.calls == (1 if status == "accept" else 2)
        assert done.state == ("succeeded" if status == "accept" else "failed")
        if status == "retry":
            assert provider.messages[-1] == original_messages
