"""Real local peer integration; no Codex/model/environment certification."""

import asyncio
import os
import sys

import pytest

from ralf_agent.codex_protocol import CodexProtocol
from ralf_agent.codex_rpc import CodexRPCTransport
from ralf_agent.runner_journal import RunnerJournal
from ralf_agent.types import Scope

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX native ownership required")


def native_thread():
    return {
        "id": "thread-original",
        "cliVersion": "0.144.4",
        "createdAt": 1,
        "updatedAt": 1,
        "cwd": "/private/test",
        "ephemeral": False,
        "sessionId": "session-original",
        "modelProvider": "fake",
        "preview": "test",
        "source": "appServer",
        "status": {"type": "idle"},
        "turns": [],
    }


def make_peer(tmp_path, *, lose_turn_receipt):
    # A native counter is separate from RALF journal commits: lost response
    # really does leave one accepted native Turn, rather than a mock side effect.
    counter = tmp_path / "turn-counter"
    thread_response = {
        "thread": native_thread(),
        "approvalPolicy": "never",
        "approvalsReviewer": "user",
        "cwd": "/private/test",
        "model": "fake",
        "modelProvider": "fake",
        "sandbox": {
            "type": "workspaceWrite",
            "writableRoots": ["/private/test"],
            "networkAccess": False,
        },
    }
    script = tmp_path / "native-peer.py"
    script.write_text(
        "import json,sys,time,pathlib\n"
        f"thread_response={thread_response!r}\n"
        f"counter=pathlib.Path({str(counter)!r})\n"
        "def send(value): print(json.dumps(value),flush=True)\n"
        "for line in sys.stdin:\n"
        " m=json.loads(line); method=m['method']\n"
        " if method=='initialized': continue\n"
        " if method=='initialize': result={'userAgent':'codex_cli_rs/0.144.4','codexHome':'/private/test-native','platformFamily':'unix','platformOs':'macos'}\n"
        " elif method=='thread/start': result=thread_response\n"
        " elif method=='turn/start':\n"
        "  counter.write_text(str(int(counter.read_text())+1) if counter.exists() else '1')\n"
        + ("  time.sleep(10)\n" if lose_turn_receipt else "")
        + "  result={'turn':{'id':'turn-original','items':[],'status':'inProgress'}}\n"
        " elif method=='turn/interrupt': result={}\n"
        " else: raise RuntimeError('unexpected request')\n"
        " send({'id':m['id'],'result':result})\n"
    )
    return CodexRPCTransport(
        (sys.executable, "-u", str(script)), env={}, request_timeout=0.5
    ), counter


@pytest.mark.parametrize("lose_turn_receipt", [False, True])
def test_committed_start_and_lost_native_receipt_never_grant_second_turn(
    tmp_path, lose_turn_receipt
):
    path = str((tmp_path / "native-evidence.sqlite").resolve())
    scope, key = Scope("workspace", "human"), "original-effect"
    protocol = CodexProtocol()
    dependencies = {"protocol": protocol.identity, "environment": "unverified-fake-peer"}
    binding = {
        "run_id": "original-run",
        "action_id": "original-action",
        "release_digest": "release",
        "operation_digest": "task",
    }
    journal = RunnerJournal(path, identity=dependencies)
    rpc, counter = make_peer(tmp_path, lose_turn_receipt=lose_turn_receipt)

    async def request(method, params):
        accepted = protocol.validate_request(method, params)
        return protocol.validate_response(method, await rpc.request(method, accepted))

    async def scenario():
        await rpc.start()
        try:
            await request(
                "initialize",
                {
                    "clientInfo": {"name": "ralf-test", "version": "1"},
                    "capabilities": {"experimentalApi": False},
                },
            )
            await rpc.notify("initialized")
            journal.begin(scope, key, binding)
            assert journal.mark_thread_submitted(scope, key, binding=binding)["execute"] is True
            response = await request("thread/start", {})
            journal.record_thread(
                scope,
                key,
                binding=binding,
                thread_id=response["thread"]["id"],
                process_epoch="peer-1",
            )
            assert journal.mark_turn_submitted(scope, key, binding=binding)["execute"] is True
            params = {
                "threadId": "thread-original",
                "input": [{"type": "text", "text": "bounded task"}],
            }
            if lose_turn_receipt:
                with pytest.raises(TimeoutError):
                    await request("turn/start", params)
            else:
                response = await request("turn/start", params)
                journal.record_turn(scope, key, binding=binding, turn_id=response["turn"]["id"])
                journal.request_cancel(scope, key, binding=binding)
                ack = await request(
                    "turn/interrupt", {"threadId": "thread-original", "turnId": "turn-original"}
                )
                assert ack == {}
                journal.record_observation(
                    scope,
                    key,
                    binding=binding,
                    observation={
                        "kind": "cancel_ack",
                        "thread_id": "thread-original",
                        "turn_id": "turn-original",
                    },
                )
                # Empty ack does not become a success result or native-stop proof.
                original = journal.lookup(scope, key, binding=binding)
                assert original["stage"] == "turn_confirmed"
                assert original["observations"] == [
                    {
                        "kind": "cancel_ack",
                        "thread_id": "thread-original",
                        "turn_id": "turn-original",
                    }
                ]
        finally:
            await rpc.aclose()
            journal.close()

    asyncio.run(scenario())
    assert counter.read_text() == "1"
    reopened = RunnerJournal(path, identity=dependencies)
    try:
        record = reopened.lookup(scope, key, binding=binding)
        assert record["stage"] == ("turn_submitted" if lose_turn_receipt else "turn_confirmed")
        assert record["turn_id"] == (None if lose_turn_receipt else "turn-original")
        assert reopened.begin(scope, key, binding)["execute"] is False
        assert reopened.mark_turn_submitted(scope, key, binding=binding)["execute"] is False
    finally:
        reopened.close()
    assert counter.read_text() == "1"
