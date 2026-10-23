"""Real Local Actions share one physical root across approved native invocations."""

import asyncio
import json
import os

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, ToolCall, ToolRegistry
from relf_agent.codex_runner import CodexCodingRunner
from relf_agent.delegated_coding import register_coding_tool
from relf_agent.runner_journal import RunnerJournal
from relf_agent.storage import SQLiteStore
from tests.helpers import ScriptedProvider
from tests.test_codex_runner import native_fixture

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX native resource fixture required")

FIRST_TASK = "first physical task"


def native_barrier(tmp_path):
    cli = native_fixture(tmp_path)
    source = cli.read_text()
    original = "   else:\n    if mode!='empty':"
    assert source.count(original) == 1
    replacement = """   else:
    if message['params']['input'][0]['text']=='first physical task':
     (root/'first-turn-entered').write_text(str(os.getpid()))
     deadline=time.monotonic()+8
     while not (root/'first-turn-release').exists() and time.monotonic()<deadline:time.sleep(.005)
     assert (root/'first-turn-release').exists(), 'Original Turn barrier exceeded its bound'
    if mode!='empty':"""
    source = source.replace(original, replacement)
    # The second actual CREATE must observe the first original object retired
    # and its real attached native peer reaped before new physical admission.
    create = "if a[0]=='create':"
    assert source.count(create) == 1
    source = source.replace(
        create,
        """if a[0]=='create':
 if s['creates']:
  assert s['containers']=={} and len(s['removed'])==1
  previous=int((root/'first-turn-entered').read_text())
  try:os.kill(previous,0)
  except ProcessLookupError:pass
  else:raise AssertionError('First actual native peer still owns execution')
""",
    )
    cli.write_text(source)
    return cli


def local_engine(tmp_path, runner, *, label, task):
    alias = "coding_" + label
    tools = ToolRegistry()
    register_coding_tool(tools, runner, name=alias)
    engine = LocalEngine(
        SQLiteStore(tmp_path / (label + ".sqlite")),
        tools=tools,
        scope=Scope("workspace-" + label, "principal-" + label),
        providers={
            "default": ScriptedProvider(
                [
                    ModelResponse(tool_calls=(ToolCall(alias, {"task": task}),)),
                    ModelResponse(output=label + " completed"),
                ]
            )
        },
    )
    handle = engine.submit(
        AgentSpec(label, "Original task", tools=(alias,)), label, command_id="submit-" + label
    )
    return engine, handle.run_id


def tool_action(engine, run_id):
    actions = [action for action in engine.store.run(run_id)["actions"] if action["kind"] == "tool"]
    assert len(actions) == 1
    return actions[0]


def native_calls(tmp_path):
    path = tmp_path / "native-submissions.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def root_capacity(root):
    return json.loads((root / ".coding-capacity.json").read_text())


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():  # noqa: ASYNC110 -- observe the actual peer process's file barrier
            await asyncio.sleep(0.005)


async def approve(engine, run_id, label):
    waiting = await engine.drive(run_id)
    assert waiting.state == "waiting_approval"
    pending = waiting.pending[0]
    engine.approve(run_id, pending["action_id"], pending["digest"], command_id="approve-" + label)


@pytest.mark.parametrize(
    "shared_object,cancel_waiter", [(True, False), (False, False), (False, True)]
)
def test_original_approved_actions_wait_for_physical_root_without_resubmission(
    tmp_path, shared_object, cancel_waiter
):
    root = tmp_path / "coding-root"
    root.mkdir(mode=0o700)
    cli = native_barrier(tmp_path)
    journals = [RunnerJournal(str(tmp_path / "first-runner.sqlite"), identity={"owner": "first"})]
    first_runner = CodexCodingRunner(
        root,
        journal=journals[0],
        docker_executable=str(cli),
        docker_host="unix:///fixture/docker.sock",
        request_timeout=10,
    )
    second_runner = first_runner
    if not shared_object:
        journals.append(
            RunnerJournal(str(tmp_path / "second-runner.sqlite"), identity={"owner": "second"})
        )
        second_runner = CodexCodingRunner(
            root,
            journal=journals[1],
            docker_executable=str(cli),
            docker_host="unix:///fixture/docker.sock",
            request_timeout=10,
        )
        assert second_runner.identity != first_runner.identity
    first, first_run = local_engine(tmp_path, first_runner, label="first", task=FIRST_TASK)
    second, second_run = local_engine(
        tmp_path, second_runner, label="second", task="different second task"
    )
    assert first.scope != second.scope and first.store is not second.store
    tasks = []

    async def scenario():
        try:
            await approve(first, first_run, "first")
            first_task = asyncio.create_task(first.drive(first_run))
            tasks.append(first_task)
            await until(lambda: (tmp_path / "first-turn-entered").exists())
            peer_pid = int((tmp_path / "first-turn-entered").read_text())
            original_capacity = root_capacity(root)
            original_action = tool_action(first, first_run)
            original_first_action_id = original_action["id"]
            assert len(original_action["attempts"]) == 1
            assert set(original_action["delegated_execution"]["grants"]) == {
                "prepare",
                "thread/start",
                "turn/start",
            }
            assert [call["method"] for call in native_calls(tmp_path)] == [
                "thread/start",
                "turn/start",
            ]
            await approve(second, second_run, "second")
            second_task = asyncio.create_task(second.drive(second_run))
            tasks.append(second_task)
            await until(lambda: bool(tool_action(second, second_run)["attempts"]))
            original_second_attempt = tool_action(second, second_run)["attempts"][0]["id"]
            original_second_action_id = tool_action(second, second_run)["id"]
            await asyncio.sleep(0.1)
            assert not second_task.done()
            assert len(tool_action(second, second_run)["attempts"]) == 1
            assert tool_action(second, second_run)["delegated_execution"]["grants"] == {}
            assert root_capacity(root) == original_capacity
            assert len(native_calls(tmp_path)) == 2
            assert json.loads((tmp_path / "docker.json").read_text())["creates"] == 1
            if cancel_waiter:
                second.cancel(second_run, command_id="cancel-waiter")
                second_task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(second_task, 10)
                assert not first_task.done()
                assert root_capacity(root) == original_capacity
                assert len(native_calls(tmp_path)) == 2
                assert json.loads((tmp_path / "docker.json").read_text())["creates"] == 1
            (tmp_path / "first-turn-release").touch()
            assert (await asyncio.wait_for(first_task, 10)).state == "succeeded"
            if cancel_waiter:
                assert (await asyncio.wait_for(second.drive(second_run), 10)).state == "cancelled"
            else:
                assert (await asyncio.wait_for(second_task, 10)).state == "succeeded"
            first_action, second_action = (
                tool_action(first, first_run),
                tool_action(second, second_run),
            )
            assert first_action["id"] == original_first_action_id
            assert second_action["id"] == original_second_action_id
            assert len(first_action["attempts"]) == len(second_action["attempts"]) == 1
            assert second_action["attempts"][0]["id"] == original_second_attempt
            assert (
                first_action["delegated_execution"]["fenced"]
                and not first_action["delegated_execution"]["pending_stop"]
            )
            assert root_capacity(root)["obligation"] is None
            assert first_runner.active_operations == second_runner.active_operations == 0
            expected = 1 if cancel_waiter else 2
            assert [call["method"] for call in native_calls(tmp_path)] == [
                "thread/start",
                "turn/start",
            ] * expected
            database = json.loads((tmp_path / "docker.json").read_text())
            assert database["creates"] == len(database["removed"]) == expected
            assert database["containers"] == {}
            with pytest.raises(ProcessLookupError):
                os.kill(peer_pid, 0)
        finally:
            (tmp_path / "first-turn-release").touch()
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 10)
            for engine, run_id in ((first, first_run), (second, second_run)):
                if engine.store.run(run_id)["state"] not in {"succeeded", "failed", "cancelled"}:
                    engine.cancel(run_id, command_id="fixture-finally-cancel")
                    await asyncio.wait_for(engine.drive(run_id), 10)
            for resource in {first_runner, second_runner}:
                await resource.aclose(wait_timeout=10)

    try:
        asyncio.run(scenario())
    finally:
        for journal in journals:
            journal.close()
        first.close()
        second.close()
