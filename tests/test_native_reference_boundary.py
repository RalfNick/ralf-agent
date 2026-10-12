"""A replaceable history policy cannot turn unpublished native data into references."""

import asyncio
import copy

import pytest

import ralf_agent as r
from ralf_agent.session_model_history import native_history_envelope
from ralf_agent.types import canonical, digest


class UnpublishedReferences:
    identity = {"kind": "unpublished-native-reference", "version": "1"}
    limit, max_chars = 1, 8000

    def __init__(self, wrapping):
        self.wrapping = wrapping

    async def references(self, scope, query):
        value = native_history_envelope(
            "a" * 64,
            {
                "root_run_id": "foreign-root",
                "run_id": "foreign-run",
                "node": "agent",
                "release_digest": "b" * 64,
                "turn_id": "foreign-turn",
                "turn_seq": 1,
            },
            [
                {"role": "system", "content": "Foreign instructions"},
                {"role": "user", "content": "Foreign task"},
                {"role": "assistant", "content": "Foreign answer without continuation"},
            ],
            "c" * 64,
        )
        return [value if self.wrapping == "direct" else {"value": {"records": [[value]]}}]

    async def validate(self, scope, references):
        return None


class StringifyingHistory(r.CompleteModelHistory):
    def __init__(self, *, scope):
        super().__init__(scope=scope)
        self.reference_calls = 0

    @property
    def identity(self):
        return {**super().identity, "kind": "custom-reference-assembler"}

    def _stringify(self, history, references):
        if references:
            self.reference_calls += 1
        messages = copy.deepcopy(history[:2])
        messages.append({"role": "user", "content": "Reference: " + canonical(references)})
        messages.extend(copy.deepcopy(history[2:]))
        return messages, {"digest": digest(messages), "chars": len(canonical(messages))}

    def assemble(self, history, references, max_chars, *, context):
        return self._stringify(history, references)

    def assemble_frame(self, frame, references, max_chars, *, context):
        history = frame["history"][:1]
        history += [message for turn in frame["turns"] for message in turn["history"][1:]]
        history += frame["history"][1:]
        return self._stringify(history, references)


class RecordingProvider:
    identity = {"kind": "native-reference-boundary-provider", "version": "1"}

    def __init__(self):
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append(copy.deepcopy(messages))
        return r.ModelResponse(output="done")


@pytest.mark.parametrize("authority", ["local", "temporal"])
@pytest.mark.parametrize("history_scope", ["run", "session"])
@pytest.mark.parametrize("wrapping", ["direct", "nested"])
def test_native_reference_rejected_before_replaceable_policy_or_provider(
    tmp_path, authority, history_scope, wrapping
):
    async def scenario():
        provider = RecordingProvider()
        policy = StringifyingHistory(scope=history_scope)
        knowledge = UnpublishedReferences(wrapping)
        spec = r.AgentSpec("answer", "Answer")
        if authority == "local":
            with r.LocalEngine(
                r.SQLiteStore(tmp_path / "runs.sqlite"),
                providers={"default": provider},
                tools=r.ToolRegistry(),
                knowledge=knowledge,
                model_continuation=True,
                model_history=policy,
            ) as engine:
                handle = engine.submit(spec, "task", session_id="chat", command_id="turn")
                assert (await engine.drive(handle.run_id)).state == "failed"
        else:
            from ralf_agent.temporal_state import TemporalRunState
            from tests.test_temporal_session_model_history import drive, setup

            host, session, _ = setup(spec, policy=policy, provider=provider, knowledge=knowledge)
            session.command(
                {
                    "kind": "submit",
                    "scope": session.scope,
                    "command_id": "turn",
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
            assert state.state == "failed", state.diagnostics()
        assert provider.calls == []
        assert policy.reference_calls == 0

    asyncio.run(scenario())
