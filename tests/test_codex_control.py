"""Control-only checks never submit a native Thread or Turn."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from ralf_agent.codex_protocol import CodexProtocol
from ralf_agent.codex_rpc import CodexRPCProtocolError, CodexRPCTransport
from ralf_agent.errors import ValidationError


def test_control_protocol_supports_only_frozen_reads_and_null_requirements():
    from ralf_agent.codex_protocol import CodexControlProtocol

    protocol = CodexControlProtocol()
    assert protocol.validate_request("configRequirements/read", None) is None
    assert protocol.validate_request("config/read", {"cwd": "/workspace", "includeLayers": True})
    for method in ("thread/start", "turn/start", "thread/resume", "config/write"):
        with pytest.raises(ValidationError):
            protocol.validate_request(method, {})
    for method, params in (("config/read", None), ("configRequirements/read", {})):
        with pytest.raises(ValidationError):
            protocol.validate_request(method, params)
    assert protocol.identity["execution_admitted"] is False
    with pytest.raises(ValidationError):
        CodexProtocol().validate_request("configRequirements/read", None)


def test_control_protocol_accepts_real_bounded_result_shapes():
    from ralf_agent.codex_protocol import CodexControlProtocol

    results = json.loads(Path(__file__).with_name("codex_control_fixture.json").read_text())
    protocol = CodexControlProtocol()
    for method, result in results.items():
        assert protocol.validate_response(method, result) == result
    with pytest.raises(ValidationError):
        protocol.validate_response("config/read", {"config": {}})
    with pytest.raises(ValidationError):
        protocol.validate_request("skills/list", {"cwds": ["/workspace"], "secret": "hidden"})


def test_default_transport_has_no_control_methods_and_control_mode_is_strict(tmp_path):
    rpc = CodexRPCTransport((sys.executable, "-u", "-c", "import time; time.sleep(5)"), env={})

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(ValueError):
                await rpc.request("configRequirements/read", None)
        finally:
            await rpc.aclose()

    asyncio.run(scenario())
    with pytest.raises(ValueError):
        CodexRPCTransport((sys.executable,), env={}, control_only=1)


@pytest.mark.parametrize(
    "peer_message",
    [
        {"id": "ask", "method": "item/commandExecution/requestApproval", "params": {}},
        {"method": "turn/started", "params": {}},
        {"method": "configWarning", "params": {"summary": "unknown warning", "details": None}},
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
def test_control_transport_rejects_native_requests_and_unreviewed_events(tmp_path, peer_message):
    script = tmp_path / "peer.py"
    script.write_text(
        "import json,sys,time\njson.loads(sys.stdin.readline())\n"
        + f"print({json.dumps(json.dumps(peer_message))},flush=True)\n"
        + "time.sleep(5)\n"
    )
    rpc = CodexRPCTransport((sys.executable, "-u", str(script)), env={}, control_only=True)

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(ValueError):
                await rpc.request("turn/start", {})
            with pytest.raises(CodexRPCProtocolError):
                await rpc.request("initialize", {})
        finally:
            await rpc.aclose()
        with pytest.raises(ProcessLookupError):
            os.kill(rpc.pid, 0)

    asyncio.run(scenario())


def test_probe_queries_nine_reads_and_closes_without_business_submission(tmp_path):
    from ralf_agent.codex_control import CodexControlProbe

    traffic = tmp_path / "traffic.jsonl"
    fixture = Path(__file__).with_name("codex_control_fixture.json")
    script = tmp_path / "peer.py"
    script.write_text(
        "import json,sys,time\n"
        + f"data=json.load(open({str(fixture)!r}))\n"
        + "for line in sys.stdin:\n"
        + " message=json.loads(line)\n"
        + f" with open({str(traffic)!r}, 'a') as log: log.write(line)\n"
        + " if 'id' in message:\n"
        + "  print(json.dumps({'id':message['id'],'result':data[message['method']]}),flush=True)\n"
    )
    probe = CodexControlProbe((sys.executable, "-u", str(script)), env={})

    async def scenario():
        snapshot = await probe.verify()
        assert snapshot["control_verified"] is True
        assert snapshot["execution_admitted"] is False
        with pytest.raises(ValidationError):
            await probe.verify()
        await probe.aclose()

    asyncio.run(scenario())
    messages = [json.loads(line) for line in traffic.read_text().splitlines()]
    assert [item["method"] for item in messages] == [
        "initialize",
        "initialized",
        "config/read",
        "configRequirements/read",
        "experimentalFeature/list",
        "permissionProfile/list",
        "mcpServerStatus/list",
        "skills/list",
        "plugin/list",
        "plugin/installed",
    ]
    assert messages[3]["params"] is None


def test_control_transport_accepts_exact_untrusted_workspace_warning(tmp_path):
    summary = (
        "Project-local config, hooks, and exec policies are disabled in the following folders "
        "until the project is trusted, but skills still load.\n"
        "    1. /workspace/.codex\n"
        "       To load project-local config, hooks, and exec policies, add /workspace as a "
        "trusted project in /home/ralf/.codex/config.toml.\n"
    )
    message = {"method": "configWarning", "params": {"summary": summary, "details": None}}
    script = tmp_path / "peer.py"
    script.write_text(
        "import json,sys,time\nrequest=json.loads(sys.stdin.readline())\n"
        + f"print({json.dumps(json.dumps(message))},flush=True)\n"
        + "print(json.dumps({'id':request['id'],'result':{}}),flush=True)\n"
        + "time.sleep(5)\n"
    )
    rpc = CodexRPCTransport((sys.executable, "-u", str(script)), env={}, control_only=True)

    async def scenario():
        await rpc.start()
        try:
            assert await rpc.request("initialize", {}) == {}
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_probe_does_not_accept_final_receipt_after_protocol_failure(tmp_path):
    from ralf_agent.codex_control import CodexControlProbe

    fixture = Path(__file__).with_name("codex_control_fixture.json")
    script = tmp_path / "peer.py"
    script.write_text(
        "import json,sys,time\n"
        + f"data=json.load(open({str(fixture)!r}))\n"
        + "for line in sys.stdin:\n"
        + " request=json.loads(line)\n"
        + " if 'id' not in request: continue\n"
        + " response=json.dumps({'id':request['id'],'result':data[request['method']]})+'\\n'\n"
        + " if request['method']=='plugin/installed':\n"
        + "  response+=json.dumps({'id':'ask','method':'item/commandExecution/requestApproval','params':{}})+'\\n'\n"
        + " sys.stdout.write(response);sys.stdout.flush()\n"
    )
    probe = CodexControlProbe((sys.executable, "-u", str(script)), env={})
    with pytest.raises(CodexRPCProtocolError):
        asyncio.run(probe.verify())


def test_cancelled_control_probe_reaps_its_actual_peer(tmp_path):
    from ralf_agent.codex_control import CodexControlProbe

    identity = tmp_path / "pid.txt"
    script = tmp_path / "peer.py"
    script.write_text(
        "import os,time\n"
        + f"open({str(identity)!r},'w').write(str(os.getpid()))\n"
        + "time.sleep(10)\n"
    )
    probe = CodexControlProbe((sys.executable, "-u", str(script)), env={})

    async def scenario():
        task = asyncio.create_task(probe.verify())
        async with asyncio.timeout(3):
            for _ in range(600):
                if identity.exists():
                    break
                await asyncio.sleep(0.005)
            else:
                pytest.fail("native peer did not start")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(int(identity.read_text()), 0)
        await probe.aclose()

    asyncio.run(scenario())


def test_reviewed_control_status_is_still_bounded(tmp_path):
    message = {
        "method": "remoteControl/status/changed",
        "params": {
            "status": "disabled",
            "serverName": "synthetic",
            "installationId": "synthetic",
            "environmentId": None,
        },
    }
    script = tmp_path / "peer.py"
    script.write_text(
        "import json,sys,time\njson.loads(sys.stdin.readline())\n"
        + f"print({json.dumps(json.dumps(message))},flush=True)\n" * 2
        + "time.sleep(5)\n"
    )
    rpc = CodexRPCTransport(
        (sys.executable, "-u", str(script)), env={}, control_only=True, max_events=1
    )

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(CodexRPCProtocolError):
                await rpc.request("initialize", {})
        finally:
            await rpc.aclose()

    asyncio.run(scenario())
