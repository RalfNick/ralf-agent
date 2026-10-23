"""Finite combined transport against local peers, with no native/model execution."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from relf_agent.codex_rpc import CodexRPCClosed, CodexRPCProtocolError, CodexRPCTransport

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")


def peer(tmp_path, body, **limits):
    script = tmp_path / "peer.py"
    script.write_text("import json,sys,time,os\n" + body)
    return CodexRPCTransport(
        (sys.executable, "-u", str(script)), env={}, coding_mode=True, **limits
    )


def test_coding_transport_runs_control_and_business_on_same_connection_without_replying(tmp_path):
    traffic = tmp_path / "traffic.jsonl"
    fixture = Path(__file__).with_name("codex_control_fixture.json")
    rpc = peer(
        tmp_path,
        f"data=json.load(open({str(fixture)!r}))\n"
        "for line in sys.stdin:\n"
        f" with open({str(traffic)!r},'a') as log: log.write(line)\n"
        " request=json.loads(line)\n"
        " if 'id' not in request: continue\n"
        " if request['method']=='thread/start':\n"
        "  print(json.dumps({'method':'turn/started','params':{'turnId':'t'}}),flush=True)\n"
        "  print(json.dumps({'id':'ask','method':'item/commandExecution/requestApproval','params':{}}),flush=True)\n"
        " result=data.get(request['method'],{'peerPid':os.getpid()})\n"
        " print(json.dumps({'id':request['id'],'result':result}),flush=True)\n",
    )
    controls = [
        "initialize",
        "config/read",
        "configRequirements/read",
        "experimentalFeature/list",
        "permissionProfile/list",
        "mcpServerStatus/list",
        "skills/list",
        "plugin/list",
        "plugin/installed",
    ]

    async def scenario():
        assert rpc.pid is None
        await rpc.start()
        try:
            for method in controls:
                result = await rpc.request(
                    method, None if method == "configRequirements/read" else {}
                )
                assert type(result) is dict
                if method == "initialize":
                    await rpc.notify("initialized")
            for method in ("config/write", "process/spawn", "account/login/start", "unknown"):
                with pytest.raises(ValueError):
                    await rpc.request(method, {})
            assert await rpc.request("thread/start", {}) == {"peerPid": rpc.pid}
            assert await rpc.next_event() == {"method": "turn/started", "params": {"turnId": "t"}}
            assert await rpc.next_event() == {
                "id": "ask",
                "method": "item/commandExecution/requestApproval",
                "params": {},
            }
            assert await rpc.request("turn/interrupt", {}) == {"peerPid": rpc.pid}
        finally:
            await rpc.aclose()

    asyncio.run(scenario())
    assert [json.loads(line)["method"] for line in traffic.read_text().splitlines()] == [
        "initialize",
        "initialized",
        *controls[1:],
        "thread/start",
        "turn/interrupt",
    ]


def test_coding_preflight_accepts_reviewed_status_without_business_inbox_entries(tmp_path):
    rpc = peer(
        tmp_path,
        "request=json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'method':'remoteControl/status/changed','params':{"
        "'status':'disabled','serverName':'synthetic','installationId':'synthetic','environmentId':None}}),flush=True)\n"
        "print(json.dumps({'id':request['id'],'result':{}}),flush=True)\n"
        "request=json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'method':'turn/started','params':{}}),flush=True)\n"
        "print(json.dumps({'id':request['id'],'result':{}}),flush=True)\n"
        "time.sleep(5)\n",
    )

    async def scenario():
        await rpc.start()
        try:
            assert await rpc.request("config/read", {}) == {}
            assert await rpc.request("thread/start", {}) == {}
            assert await rpc.next_event() == {"method": "turn/started", "params": {}}
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "message",
    [
        {"id": "ask", "method": "item/commandExecution/requestApproval", "params": {}},
        {"method": "turn/started", "params": {}},
        {"method": "configWarning", "params": {"summary": "unknown", "details": None}},
        {
            "method": "remoteControl/status/changed",
            "params": {
                "status": "connected",
                "serverName": "x",
                "installationId": "i",
                "environmentId": None,
            },
        },
    ],
)
def test_coding_preflight_rejects_unreviewed_traffic_even_after_last_response(tmp_path, message):
    rpc = peer(
        tmp_path,
        "request=json.loads(sys.stdin.readline())\n"
        "wire=json.dumps({'id':request['id'],'result':{}})+'\\n'\n"
        f"wire+=json.dumps({message!r})+'\\n'\n"
        "sys.stdout.write(wire);sys.stdout.flush()\n"
        "time.sleep(5)\n",
    )

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(CodexRPCProtocolError):
                await rpc.request("plugin/installed", {})
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_coding_business_inbox_is_bounded_and_peer_requests_are_never_authorized(tmp_path):
    rpc = peer(
        tmp_path,
        "json.loads(sys.stdin.readline())\n"
        "for method in ['item/commandExecution/requestApproval','item/tool/requestUserInput']:\n"
        " print(json.dumps({'id':method,'method':method,'params':{}}),flush=True)\n"
        "time.sleep(5)\n",
        max_events=1,
    )

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(CodexRPCProtocolError):
                await rpc.request("thread/start", {})
        finally:
            await rpc.aclose()
        with pytest.raises(ProcessLookupError):
            os.kill(rpc.pid, 0)

    asyncio.run(scenario())


def test_cancelled_coding_start_retains_ownership_and_cannot_restart(tmp_path):
    rpc = peer(tmp_path, "time.sleep(5)\n")

    async def scenario():
        starting = asyncio.create_task(rpc.start())
        await asyncio.sleep(0)
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        await rpc.aclose(wait_timeout=2)
        if rpc.pid is not None:
            with pytest.raises(ProcessLookupError):
                os.kill(rpc.pid, 0)
        with pytest.raises(CodexRPCClosed):
            await rpc.start()

    asyncio.run(scenario())
