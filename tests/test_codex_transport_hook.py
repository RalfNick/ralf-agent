"""A protected transport hook composes the original authorized business loop."""

import asyncio

from ralf_agent import AgentSpec, LocalEngine, ModelResponse, ToolCall, ToolRegistry
from ralf_agent.codex_runner import CodexCodingRunner
from ralf_agent.delegated_coding import register_coding_tool
from ralf_agent.runner_journal import RunnerJournal
from ralf_agent.storage import SQLiteStore
from tests.helpers import ScriptedProvider
from tests.test_codex_runner import native_fixture


def test_original_approved_action_uses_subclass_transport_hook_without_duplicate_turn(tmp_path):
    calls = []

    class HookRunner(CodexCodingRunner):
        def _make_transport(self, owner, environment):
            calls.append((owner["envelope"].context.action_id, environment.identity))
            return super()._make_transport(owner, environment)

    root = tmp_path / "coding"
    root.mkdir(mode=0o700)
    journal = RunnerJournal(str(tmp_path / "native.sqlite"), identity={"fixture": "hook"})
    resource = HookRunner(
        root,
        journal=journal,
        docker_executable=str(native_fixture(tmp_path)),
        docker_host="unix:///fixture/docker.sock",
        request_timeout=3,
    )
    tools = ToolRegistry()
    register_coding_tool(tools, resource)
    engine = LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        tools=tools,
        providers={
            "default": ScriptedProvider(
                [
                    ModelResponse(tool_calls=(ToolCall("coding", {"task": "fixture task"}),)),
                    ModelResponse(output="finished"),
                ]
            )
        },
    )

    async def scenario():
        handle = engine.submit(
            AgentSpec("hook", "hook", tools=("coding",)), {}, command_id="submit"
        )
        waiting = await engine.drive(handle.run_id)
        assert waiting.state == "waiting_approval" and calls == []
        action = waiting.pending[0]
        engine.approve(handle.run_id, action["action_id"], action["digest"], command_id="approve")
        finished = await engine.drive(handle.run_id)
        assert finished.state == "succeeded"
        assert len(calls) == 1, "original business loop must select the protected transport hook"
        assert calls[0][0] == action["action_id"]
        assert (tmp_path / "native-submissions.jsonl").read_text().count(
            '"method": "thread/start"'
        ) == 1
        assert (tmp_path / "native-submissions.jsonl").read_text().count(
            '"method": "turn/start"'
        ) == 1
        assert resource.active_operations == 0
        await resource.aclose()

    try:
        asyncio.run(scenario())
    finally:
        journal.close()
        engine.close()
