"""Finite native runner fixtures; no model, authentication, or quality certification."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from relf_agent.codex_runner import CodexCodingRunner
from relf_agent.errors import AuthorizationDenied, ValidationError
from relf_agent.executors import DispatchEnvelope
from relf_agent.runner_journal import RunnerJournal
from relf_agent.types import InvocationContext, Scope

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX Coding resource required")


@pytest.fixture
def runner_parts(tmp_path):
    root = tmp_path / "coding"
    root.mkdir(mode=0o700)
    journal = RunnerJournal(str(tmp_path / "native.sqlite"), identity={"dependency": "fixed"})
    try:
        yield root, journal
    finally:
        journal.close()


def runner(runner_parts, **kwargs):
    root, journal = runner_parts
    return CodexCodingRunner(
        root,
        journal=journal,
        docker_executable=sys.executable,
        docker_host="unix:///fixture/docker.sock",
        **kwargs,
    )


def envelope():
    return DispatchEnvelope(
        InvocationContext(Scope("coding", "owner"), "run", "action", "attempt", "effect", "epoch"),
        {"name": "coding", "effect": "queryable_write"},
        {"task": "Write a bounded solution"},
        "digest",
    )


def test_constructor_identity_is_detached_and_has_no_native_business_io(runner_parts):
    resource = runner(runner_parts)
    assert list(runner_parts[0].iterdir()) == []
    identity = resource.identity
    assert identity["kind"] == "codex-coding-runner"
    assert identity["version"] == "1"
    assert identity["journal"] == runner_parts[1].identity
    assert identity["recovery_modes"] == ["none"]
    assert identity["resource_lifecycle_version"] == "2"
    identity["journal"]["dependencies"]["dependency"] = "forged"
    assert resource.identity["journal"]["dependencies"] == {"dependency": "fixed"}


@pytest.mark.parametrize("timeout", [True, 0, 61, float("inf"), float("nan")])
def test_constructor_rejects_nonfinite_or_unbounded_deadline_before_native_io(
    runner_parts, timeout
):
    with pytest.raises(ValidationError):
        runner(runner_parts, request_timeout=timeout)
    assert list(runner_parts[0].iterdir()) == []


def test_envelope_or_ordinary_callable_cannot_supply_engine_authority(runner_parts):
    resource = runner(runner_parts)

    async def scenario():
        for authority in (None, lambda *args: True, envelope(), object()):
            with pytest.raises(AuthorizationDenied):
                await resource.execute(envelope(), authority)
        await resource.aclose()

    asyncio.run(scenario())
    assert list(runner_parts[0].iterdir()) == []


def test_workspace_artifacts_use_fenced_owned_namespace_and_exclude_hidden_metadata(tmp_path):
    from relf_agent.codex_environment import DockerCodingEnvironment
    from tests.test_codex_environment import FAKE_DOCKER

    root = tmp_path / "artifact-resource"
    root.mkdir(mode=0o700)
    cli = tmp_path / "docker"
    cli.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
    cli.chmod(0o700)
    env = DockerCodingEnvironment(
        root,
        "artifact-fixture",
        docker_executable=str(cli),
        docker_host="unix:///fixture/docker.sock",
        retire_on_stop=True,
        expected_generation="a" * 32,
    )

    async def scenario():
        await env.prepare()
        (root / "workspace" / "answer.txt").write_text("hello\n")
        (root / "workspace" / ".codex" / "hidden.json").write_text("private metadata")
        stopped = await env.stop()
        assert stopped["fenced"] is True
        artifacts = CodexCodingRunner._artifacts(env)
        assert artifacts == [
            {
                "path": "answer.txt",
                "size": 6,
                "sha256": "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03",
            }
        ]
        await env.aclose()

    asyncio.run(scenario())


def native_fixture(tmp_path, mode="completed", *, startup_delay=0):
    from tests.coding_cli_fixture import ready_cli
    from tests.test_codex_environment import FAKE_DOCKER

    control = json.loads(Path(__file__).with_name("codex_control_fixture.json").read_text())
    native = {
        "id": "thread-original",
        "cliVersion": "0.144.4",
        "createdAt": 1,
        "updatedAt": 1,
        "cwd": "/workspace",
        "ephemeral": False,
        "sessionId": "session-original",
        "modelProvider": "fixture",
        "preview": "fixture",
        "source": "appServer",
        "status": {"type": "idle"},
        "turns": [],
    }
    response = {
        "thread": native,
        "approvalPolicy": "never",
        "approvalsReviewer": "user",
        "cwd": "/workspace",
        "model": "fixture",
        "modelProvider": "fixture",
        "sandbox": {
            "type": "workspaceWrite",
            "writableRoots": ["/workspace"],
            "networkAccess": False,
        },
    }
    turn = {
        "id": "turn-original",
        "status": "completed",
        "items": [
            {
                "id": "message-original",
                "type": "agentMessage",
                "text": "fixture solution",
                "phase": "final_answer",
            }
        ],
    }
    if mode == "empty":
        turn["items"][0]["text"] = ""
    cli = tmp_path / "codex_rpc_docker_fixture"
    startup = f" time.sleep({startup_delay!r})\n" if startup_delay else ""
    business = f"""
 control={control!r};thread_response={response!r};turn={turn!r};mode={mode!r}
{startup} counts=root/'native-submissions.jsonl'
 workspace=pathlib.Path(next(m['Source'] for m in s['containers'][cid]['Mounts'] if m['Destination']=='/workspace'))
 def send(value):print(json.dumps(value),flush=True)
 for line in sys.stdin:
  message=json.loads(line);method=message['method']
  if method=='initialized':continue
  if method in control:result=control[method]
  elif method in ['thread/start','turn/start']:
   with counts.open('a') as out:out.write(json.dumps(message)+'\\n')
   if method=='thread/start':result=thread_response
   else:
    if mode!='empty':(workspace/'answer.txt').write_text('fixture artifact\\n')
    if mode=='lost_turn':time.sleep(10)
    result={{'turn':{{'id':'turn-original','items':[],'status':'inProgress'}}}}
    send({{'id':message['id'],'result':result}})
    if mode in ['approval','auth_request']:
     send({{'id':'pending-native','method':'item/commandExecution/requestApproval' if mode=='approval' else 'account/auth/request','params':{{'secret':'must never enter journal'}}}})
    elif mode!='hang_turn':
     terminal=dict(turn)
     if mode=='failed_terminal':terminal['status']='failed'
     send({{'method':'turn/completed','params':{{'threadId':'thread-original','turn':terminal}}}})
     if mode=='late_auth':send({{'id':'late-auth','method':'account/auth/request','params':{{'secret':'must never enter journal'}}}})
    continue
  elif method=='thread/read':
   assert message['params']=={{'threadId':'thread-original','includeTurns':True}}
   original=dict(thread_response['thread']);original['turns']=[turn]
   if mode=='wrong_final':original['id']='different-thread'
   result={{'thread':original}}
   if mode=='late_auth_read_before':send({{'id':'late-auth','method':'account/auth/request','params':{{'secret':'must never enter journal'}}}})
  else:raise RuntimeError('unexpected native method')
  send({{'id':message['id'],'result':result}})
  if method=='thread/read' and mode=='late_auth_read_after':send({{'id':'late-auth','method':'account/auth/request','params':{{'secret':'must never enter journal'}}}})
  if method=='thread/read' and mode=='late_auth_close':
   deadline=time.monotonic()+1
   while not (root/'kill.started').exists() and time.monotonic()<deadline:time.sleep(.001)
   assert (root/'kill.started').exists()
   send({{'id':'late-auth','method':'account/auth/request','params':{{'secret':'must never enter journal'}}}})
"""
    # Keep the existing actual CLI boundary/configuration fixture and extend only
    # its contained stdio start branch with a fixed structural native peer.
    source = FAKE_DOCKER.replace("else: sys.exit(4)", business + "\nelse: sys.exit(4)")
    if mode == "late_auth_close":
        source = source.replace(
            "elif a[0]=='kill':",
            "elif a[0]=='kill':\n (root/'kill.started').touch();time.sleep(.1)",
        )
    cli.write_text(f"#!{sys.executable}\n" + source)
    cli.chmod(0o700)
    ready_cli(cli)
    return cli


def original_engine(tmp_path, *, mode="completed", timeout=3, startup_delay=0):
    from relf_agent import AgentSpec, LocalEngine, ModelResponse, ToolCall, ToolRegistry
    from relf_agent.delegated_coding import register_coding_tool
    from relf_agent.storage import SQLiteStore
    from tests.helpers import ScriptedProvider

    root = tmp_path / "coding"
    root.mkdir(mode=0o700)
    cli = native_fixture(tmp_path, mode, startup_delay=startup_delay)
    journal = RunnerJournal(str(tmp_path / "runner.sqlite"), identity={"dependency": "fixture"})
    resource = CodexCodingRunner(
        root,
        journal=journal,
        docker_executable=str(cli),
        docker_host="unix:///fixture/docker.sock",
        request_timeout=timeout,
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
                    ModelResponse(output="outer fixture finished"),
                ]
            )
        },
    )
    handle = engine.submit(
        AgentSpec("fixture", "fixture", tools=("coding",)), {}, command_id="submit"
    )
    return engine, handle.run_id, resource, journal


def test_real_native_fixture_runs_only_original_approved_action_and_fences_before_adoption(
    tmp_path,
):
    engine, run_id, resource, journal = original_engine(tmp_path)

    async def scenario():
        waiting = await engine.drive(run_id)
        assert waiting.state == "waiting_approval"
        assert not (tmp_path / "docker.json").exists()
        pending = waiting.pending[0]
        engine.approve(run_id, pending["action_id"], pending["digest"], command_id="approve")
        finished = await engine.drive(run_id)
        assert finished.state == "succeeded"
        action = next(a for a in engine.store.run(run_id)["actions"] if a["kind"] == "tool")
        candidate = action["delegated_execution"]["result_candidate"]
        assert candidate["text"] == "fixture solution"
        assert candidate["usage"] == {"status": "unknown"}
        assert candidate["native"] == {
            "thread_id": "thread-original",
            "turn_id": "turn-original",
            "status": "completed",
        }
        assert candidate["stop"]["fenced"] is True
        assert candidate["artifacts"][0]["path"] == "answer.txt"
        assert action["delegated_execution"]["pending_stop"] is False
        assert action["delegated_execution"]["fenced"] is True
        assert len(action["attempts"]) == 1
        assert json.loads((tmp_path / "docker.json").read_text())["containers"] == {}
        calls = [
            json.loads(line)["method"]
            for line in (tmp_path / "native-submissions.jsonl").read_text().splitlines()
        ]
        assert calls == ["thread/start", "turn/start"]
        assert resource.active_operations == 0
        await resource.aclose()

    try:
        asyncio.run(scenario())
    finally:
        journal.close()
        engine.close()


@pytest.mark.parametrize(
    "mode",
    [
        "approval",
        "auth_request",
        "wrong_final",
        "failed_terminal",
        "lost_turn",
        "late_auth",
        "late_auth_read_before",
        "late_auth_read_after",
        "late_auth_close",
        "empty",
    ],
)
def test_native_uncertainty_is_fenced_and_cold_reconcile_never_restarts(tmp_path, mode):
    # Allow both supervised gates and thread/start to finish before exercising
    # the lost turn's deadline or the other modes' protocol violations.
    engine, run_id, resource, journal = original_engine(tmp_path, mode=mode, timeout=10)

    async def scenario():
        waiting = await engine.drive(run_id)
        pending = waiting.pending[0]
        engine.approve(run_id, pending["action_id"], pending["digest"], command_id="approve")
        observed = await engine.drive(run_id)
        assert observed.state == "waiting_reconciliation"
        action = next(a for a in engine.store.run(run_id)["actions"] if a["kind"] == "tool")
        delegated = action["delegated_execution"]
        assert delegated["pending_stop"] is False
        assert delegated["fenced"] is True
        assert delegated["native_unknown"] is True
        assert delegated["effect_case"] == "unknown"
        assert "result_candidate" not in delegated
        assert json.loads((tmp_path / "docker.json").read_text())["containers"] == {}
        before = (tmp_path / "native-submissions.jsonl").read_text()
        assert len(before.splitlines()) == 2
        assert (await engine.drive(run_id)).state == "waiting_reconciliation"
        assert (tmp_path / "native-submissions.jsonl").read_text() == before
        records = journal.conn.execute("SELECT record FROM runner_effects").fetchall()
        assert len(records) == 1
        assert "must never enter journal" not in records[0][0]
        record = json.loads(records[0][0])
        # late_auth can invalidate the pending transport response before its
        # locator is durably adopted. Both windows must remain unknown/fenced;
        # the read/close modes below exercise the later confirmed windows.
        expected_stages = (
            {"turn_submitted"}
            if mode == "lost_turn"
            else {"turn_submitted", "turn_confirmed"}
            if mode == "late_auth"
            else {"turn_confirmed"}
        )
        assert record["stage"] in expected_stages
        assert any(item["kind"] == "stop" and item["fenced"] for item in record["observations"])
        assert resource.active_operations == 0
        await resource.aclose()

    try:
        asyncio.run(scenario())
    finally:
        journal.close()
        engine.close()


@pytest.mark.parametrize("startup_delay", [0, 1.6])
def test_caller_cancellation_waits_actual_native_resource_retirement(tmp_path, startup_delay):
    engine, run_id, resource, journal = original_engine(
        tmp_path, mode="hang_turn", startup_delay=startup_delay
    )

    async def scenario():
        waiting = await engine.drive(run_id)
        pending = waiting.pending[0]
        engine.approve(run_id, pending["action_id"], pending["digest"], command_id="approve")
        driving = asyncio.create_task(engine.drive(run_id))
        counter = tmp_path / "native-submissions.jsonl"
        # Observe an original native Thread before timing the next native frame;
        # process startup is bounded by the fixture's unchanged three seconds.
        async with asyncio.timeout(3):
            while not counter.exists():  # noqa: ASYNC110 - bounded real native readiness
                assert not driving.done(), "Driver ended before original native submission"
                await asyncio.sleep(0.005)
        for _ in range(300):
            if counter.exists() and len(counter.read_text().splitlines()) == 2:
                break
            await asyncio.sleep(0.005)
        assert counter.exists() and len(counter.read_text().splitlines()) == 2
        engine.cancel(run_id, command_id="cancel")
        driving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await driving
        await resource.aclose()
        assert resource.active_operations == 0
        assert json.loads((tmp_path / "docker.json").read_text())["containers"] == {}
        settled = await engine.drive(run_id)
        assert settled.state == "cancelled"
        action = next(a for a in engine.store.run(run_id)["actions"] if a["kind"] == "tool")
        assert action["delegated_execution"]["fenced"] is True
        assert "result_candidate" not in action["delegated_execution"]

    try:
        asyncio.run(scenario())
    finally:
        journal.close()
        engine.close()


def test_queued_native_peer_survives_close_with_unscheduled_event_consumer(tmp_path, monkeypatch):
    engine, run_id, resource, journal = original_engine(tmp_path, mode="late_auth_read_after")

    async def paused_after_terminal(owner):
        while True:
            event = await owner["transport"].next_event()
            owner["events"].put_nowait(event)
            if event["method"] == "turn/completed":
                # A deterministic consumer scheduling gap: final read still
                # receives the peer frame, but this pump cannot consume it.
                await asyncio.Event().wait()

    monkeypatch.setattr(resource, "_pump", paused_after_terminal)

    async def scenario():
        pending = (await engine.drive(run_id)).pending[0]
        engine.approve(run_id, pending["action_id"], pending["digest"], command_id="approve")
        assert (await engine.drive(run_id)).state == "waiting_reconciliation"
        action = next(a for a in engine.store.run(run_id)["actions"] if a["kind"] == "tool")
        assert "result_candidate" not in action["delegated_execution"]
        assert action["delegated_execution"]["fenced"] is True
        assert resource.active_operations == 0
        assert json.loads((tmp_path / "docker.json").read_text())["containers"] == {}
        await resource.aclose()

    try:
        asyncio.run(scenario())
    finally:
        journal.close()
        engine.close()


@pytest.mark.parametrize("missing", ["metadata", "root", "locator"])
def test_known_original_cold_namespace_loss_retains_owner_without_fake_fence(tmp_path, missing):
    from relf_agent.errors import CloseIncomplete
    from relf_agent.local_delegated_coding import LocalCodingAuthority, _envelope

    engine, run_id, resource, journal = original_engine(tmp_path)
    removed = None
    original_bytes = None
    namespace = None

    async def scenario():
        nonlocal removed, original_bytes, namespace
        pending = (await engine.drive(run_id)).pending[0]
        engine.approve(run_id, pending["action_id"], pending["digest"], command_id="approve")
        assert (await engine.drive(run_id)).state == "succeeded"
        action = next(a for a in engine.store.run(run_id)["actions"] if a["kind"] == "tool")
        delegated = action["delegated_execution"]
        original = _envelope(delegated)
        authority = LocalCodingAuthority(engine, run_id, action["id"])
        namespace = Path(delegated["prepared"]["identity"]["root"]["path"])
        if missing in ("metadata", "locator"):
            removed = namespace / "environment.json"
            original_bytes = removed.read_bytes()
            if missing == "metadata":
                removed.unlink()
            else:
                changed = json.loads(original_bytes)
                changed["container_id"] = "b" * 64
                changed["retirement"]["stopped"]["container_id"] = "b" * 64
                removed.write_text(json.dumps(changed))
        else:
            removed = namespace.with_name(namespace.name + "-saved")
            namespace.rename(removed)
        before = (tmp_path / "native-submissions.jsonl").read_text()
        before_daemon = (tmp_path / "docker.json").read_bytes()
        with pytest.raises(CloseIncomplete):
            await resource.stop_existing(original, authority)
        assert resource.active_operations == 1
        assert (tmp_path / "native-submissions.jsonl").read_text() == before
        assert (tmp_path / "docker.json").read_bytes() == before_daemon
        if missing in ("metadata", "locator"):
            if missing == "metadata":
                assert not (namespace / "environment.json").exists()
            removed.write_bytes(original_bytes)
            removed.chmod(0o600)
        else:
            assert not namespace.exists()
            removed.rename(namespace)
        removed = None
        await resource.aclose()
        assert resource.active_operations == 0

    try:
        asyncio.run(scenario())
    finally:
        if removed is not None:
            if missing in ("metadata", "locator"):
                removed.write_bytes(original_bytes)
                removed.chmod(0o600)
            else:
                removed.rename(namespace)
            asyncio.run(resource.aclose())
        journal.close()
        engine.close()
