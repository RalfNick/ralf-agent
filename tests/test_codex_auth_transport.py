"""Finite real-process authentication peers; no native/model/container execution."""

import asyncio
import importlib
import importlib.util
import json
import os
import sys
import textwrap

import pytest

from ralf_agent.codex_rpc import CodexRPCClosed, CodexRPCError, CodexRPCTransport

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
CANARY = "synthetic-auth-canary-109"


def transport_type():
    name = "ralf_agent.codex_auth_transport"
    assert importlib.util.find_spec(name) is not None, (
        "dedicated authenticated transport is missing"
    )
    return importlib.import_module(name).CodexAuthenticatedTransport


def peer(
    tmp_path, *, initial=None, login=None, notifications=None, barrier=None, extra="", **limits
):
    script = tmp_path / "auth_peer.py"
    traffic = tmp_path / "traffic.jsonl"
    # The peer validates secret wire input in memory; its log records methods only.
    script.write_text(
        "import json,sys,os,time\n"
        "def send(value): print(json.dumps(value),flush=True)\n"
        "def read():\n"
        " value=json.loads(sys.stdin.readline())\n"
        f" with open({str(traffic)!r},'a') as log: log.write(json.dumps({{'method':value['method'],'pid':os.getpid()}})+'\\n')\n"
        " return value\n"
        "while True:\n"
        " request=read()\n"
        " if request['method']=='account/read': break\n"
        " if 'id' in request: send({'id':request['id'],'result':{'peerPid':os.getpid()}})\n"
        "assert request['params']=={'refreshToken':False}\n"
        + (
            initial
            or "send({'id':request['id'],'result':{'account':None,'requiresOpenaiAuth':True}})\n"
        )
        + "request=read()\nassert request['method']=='account/login/start'\n"
        + f"assert request['params']=={{'type':'apiKey','apiKey':{CANARY!r}}}\n"
        + (login or "send({'id':request['id'],'result':{'type':'apiKey'}})\n")
        + (
            notifications
            if notifications is not None
            else "send({'method':'account/login/completed','params':{'loginId':None,'success':True,'error':None}})\n"
            "send({'method':'account/updated','params':{'authMode':'apikey','planType':None}})\n"
        )
        + "request=read()\nassert request['method']=='account/read'\nassert request['params']=={'refreshToken':False}\n"
        + (
            barrier
            or "send({'id':request['id'],'result':{'account':{'type':'apiKey'},'requiresOpenaiAuth':True}})\n"
        )
        + "barrier_id=request['id']\n"
        + textwrap.dedent(extra)
        + "while True:\n"
        " request=read()\n"
        " if 'id' in request: send({'id':request['id'],'result':{'peerPid':os.getpid()}})\n"
    )
    rpc = transport_type()((sys.executable, "-u", str(script)), env={}, coding_mode=True, **limits)
    return rpc, traffic


def assert_secret_absent(rpc, error=None):
    visible = [rpc._pending, rpc._events, rpc._failure]
    if error is not None:
        visible += [str(error), repr(error), vars(error), error.__cause__, error.__context__]
    assert CANARY not in repr(visible)
    assert not any(event.get("method", "").startswith("account/") for event in rpc._events)


def test_authentication_uses_one_connection_and_exact_barrier_then_business(tmp_path):
    rpc, traffic = peer(tmp_path)

    async def scenario():
        assert isinstance(rpc, CodexRPCTransport)
        await rpc.start()
        try:
            assert await rpc.request("initialize", {}) == {"peerPid": rpc.pid}
            await rpc.notify("initialized")
            assert await rpc.request("config/read", {}) == {"peerPid": rpc.pid}
            with pytest.raises(CodexRPCError):
                await rpc.request("thread/start", {})
            assert await rpc.authenticate_api_key(CANARY) == {
                "mode": "apiKey",
                "ephemeral": True,
                "barrier_verified": True,
            }
            assert await rpc.request("thread/start", {}) == {"peerPid": rpc.pid}
            with pytest.raises(CodexRPCError):
                await rpc.authenticate_api_key(CANARY)
            for method in ("account/read", "account/login/start", "account/logout"):
                with pytest.raises(ValueError):
                    await rpc.request(method, {})
            assert_secret_absent(rpc)
        finally:
            await rpc.aclose()

    asyncio.run(scenario())
    rows = [json.loads(line) for line in traffic.read_text().splitlines()]
    assert [row["method"] for row in rows] == [
        "initialize",
        "initialized",
        "config/read",
        "account/read",
        "account/login/start",
        "account/read",
        "thread/start",
    ]
    assert {row["pid"] for row in rows} == {rpc.pid}
    assert CANARY not in traffic.read_text()


@pytest.mark.parametrize(
    "stage,wire",
    [
        (
            "initial",
            "{'id':request['id'],'result':{'account':{'type':'apiKey'},'requiresOpenaiAuth':True}}",
        ),
        ("initial", "{'id':request['id'],'result':{'account':None,'requiresOpenaiAuth':False}}"),
        ("initial", "{'id':request['id'],'result':{'account':None,'requiresOpenaiAuth':1}}"),
        (
            "initial",
            f"{{'id':request['id'],'result':{{'account':None,'requiresOpenaiAuth':True,'apiKey':{CANARY!r}}}}}",
        ),
        ("login", f"{{'id':request['id'],'result':{{'type':'apiKey','apiKey':{CANARY!r}}}}}"),
        ("login", "{'id':True,'result':{'type':'apiKey'}}"),
        ("login", f"{{'id':request['id'],'result':{{'type':'apiKey'}},'echo':{CANARY!r}}}"),
        ("login", "{'jsonrpc':'2.0','id':request['id'],'result':{'type':'apiKey'}}"),
        ("login", "{'id':request['id'],'result':{'type':'chatgpt'}}"),
        (
            "login",
            f"{{'id':request['id'],'error':{{'code':-32000,'message':{CANARY!r},'data':{{'apiKey':{CANARY!r}}}}}}}",
        ),
        (
            "notifications",
            "{'method':'account/login/completed','params':{'loginId':None,'success':1,'error':None}}",
        ),
        (
            "notifications",
            f"{{'method':'account/login/completed','params':{{'loginId':None,'success':False,'error':{CANARY!r}}}}}",
        ),
        (
            "notifications",
            f"{{'id':'auth','method':'account/chatgptAuthTokens/refresh','params':{{'apiKey':{CANARY!r}}}}}",
        ),
        (
            "notifications",
            "{'method':'account/updated','params':{'authMode':'apikey','planType':None}}",
        ),
        (
            "notifications",
            f"{{'method':'account/login/completed','params':{{'loginId':None,'success':True,'error':None,'echo':{CANARY!r}}}}}",
        ),
        ("notifications", f"{{'method':'unknown','params':{{'echo':{CANARY!r}}}}}"),
        (
            "barrier",
            f"{{'id':request['id'],'result':{{'account':{{'type':'apiKey','apiKey':{CANARY!r}}},'requiresOpenaiAuth':True}}}}",
        ),
        ("barrier", "{'id':request['id'],'result':{'account':None,'requiresOpenaiAuth':True}}"),
        ("barrier", "{'id':request['id']-1,'result':{'type':'apiKey'}}"),
    ],
)
def test_auth_rejects_malformed_echoed_unknown_and_raw_error_before_storage(tmp_path, stage, wire):
    rpc, traffic = peer(tmp_path, **{stage: f"send({wire})\n"})

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(CodexRPCError) as caught:
                await rpc.authenticate_api_key(CANARY)
            assert_secret_absent(rpc, caught.value)
            assert rpc._state == "closed"
            with pytest.raises(CodexRPCError):
                await rpc.request("thread/start", {})
        finally:
            await rpc.aclose()
        with pytest.raises(ProcessLookupError):
            os.kill(rpc.pid, 0)

    asyncio.run(scenario())
    methods = [json.loads(line)["method"] for line in traffic.read_text().splitlines()]
    assert methods.count("account/login/start") <= 1
    assert "thread/start" not in methods


@pytest.mark.parametrize(
    "notifications",
    [
        "",
        "send({'method':'account/login/completed','params':{'loginId':None,'success':True,'error':None}})\n",
        "send({'method':'account/login/completed','params':{'loginId':None,'success':True,'error':None}})\n"
        * 2,
        "send({'method':'account/login/completed','params':{'loginId':None,'success':True,'error':None}})\n"
        "send({'method':'account/updated','params':{'authMode':'apikey','planType':None}})\n"
        "send({'method':'account/updated','params':{'authMode':'apikey','planType':None}})\n",
    ],
)
def test_barrier_requires_exactly_two_ordered_notifications(tmp_path, notifications):
    rpc, _ = peer(tmp_path, notifications=notifications)

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(CodexRPCError):
                await rpc.authenticate_api_key(CANARY)
            assert_secret_absent(rpc)
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "late",
    [
        "{'method':'account/login/completed','params':{'loginId':None,'success':True,'error':None}}",
        f"{{'id':'auth','method':'account/chatgptAuthTokens/refresh','params':{{'echo':{CANARY!r}}}}}",
        "{'id':barrier_id,'result':{'account':{'type':'apiKey'},'requiresOpenaiAuth':True}}",
    ],
)
def test_late_authentication_traffic_never_enters_business_inbox(tmp_path, late):
    rpc, _ = peer(
        tmp_path, extra=f"request=read()\nassert request['method']=='thread/start'\nsend({late})\n"
    )

    async def scenario():
        await rpc.start()
        try:
            await rpc.authenticate_api_key(CANARY)
            with pytest.raises(CodexRPCError):
                await rpc.request("thread/start", {})
            assert_secret_absent(rpc)
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


async def wait_for_file(path):
    async with asyncio.timeout(3):
        while not path.exists():  # noqa: ASYNC110 - bounded real-process file handshake
            await asyncio.sleep(0.005)


@pytest.mark.parametrize("stage", ["initial", "login", "barrier"])
@pytest.mark.parametrize("termination", ["timeout", "cancel", "disconnect"])
def test_auth_failure_stops_original_process_without_retry(tmp_path, stage, termination):
    marker = tmp_path / "entered"
    block = f"open({str(marker)!r},'w').write('ready')\n"
    block += "sys.exit(0)\n" if termination == "disconnect" else "time.sleep(30)\n"
    rpc, traffic = peer(
        tmp_path, **{stage: block}, request_timeout=0.12 if termination == "timeout" else 3
    )

    async def scenario():
        await rpc.start()
        try:
            authentication = asyncio.create_task(rpc.authenticate_api_key(CANARY))
            await wait_for_file(marker)
            if termination == "cancel":
                authentication.cancel()
                async with asyncio.timeout(3):
                    while rpc._state != "closing":  # noqa: ASYNC110 - original owner lifecycle
                        await asyncio.sleep(0)
                authentication.cancel()  # Cleanup remains owned under repeated cancellation.
                with pytest.raises(asyncio.CancelledError):
                    await authentication
            else:
                with pytest.raises(CodexRPCError) as caught:
                    await authentication
                assert_secret_absent(rpc, caught.value)
            assert_secret_absent(rpc)
            assert rpc._state == "closed"
            with pytest.raises(CodexRPCClosed):
                await rpc.start()
            with pytest.raises(CodexRPCError):
                await rpc.authenticate_api_key(CANARY)
        finally:
            await rpc.aclose()
        with pytest.raises(ProcessLookupError):
            os.kill(rpc.pid, 0)

    asyncio.run(scenario())
    methods = [json.loads(line)["method"] for line in traffic.read_text().splitlines()]
    assert (
        methods
        == {
            "initial": ["account/read"],
            "login": ["account/read", "account/login/start"],
            "barrier": ["account/read", "account/login/start", "account/read"],
        }[stage]
    )


def test_exclusive_authentication_rejects_concurrent_calls_without_extra_wire(tmp_path):
    marker, release = tmp_path / "entered", tmp_path / "release"
    initial = (
        f"open({str(marker)!r},'w').write('ready')\n"
        f"while not os.path.exists({str(release)!r}): time.sleep(.005)\n"
        "send({'id':request['id'],'result':{'account':None,'requiresOpenaiAuth':True}})\n"
    )
    rpc, traffic = peer(tmp_path, initial=initial)

    async def scenario():
        await rpc.start()
        try:
            authentication = asyncio.create_task(rpc.authenticate_api_key(CANARY))
            await wait_for_file(marker)
            for operation in (
                rpc.request("config/read", {}),
                rpc.request("thread/start", {}),
                rpc.notify("initialized"),
                rpc.authenticate_api_key(CANARY),
            ):
                with pytest.raises(CodexRPCError):
                    await operation
            release.write_text("go")
            assert await authentication == {
                "mode": "apiKey",
                "ephemeral": True,
                "barrier_verified": True,
            }
        finally:
            await rpc.aclose()

    asyncio.run(scenario())
    assert [json.loads(line)["method"] for line in traffic.read_text().splitlines()] == [
        "account/read",
        "account/login/start",
        "account/read",
    ]


def test_authentication_waits_for_exclusive_admission_and_can_be_tried_after_busy_request(tmp_path):
    marker, release = tmp_path / "entered", tmp_path / "release"
    script = tmp_path / "busy_peer.py"
    script.write_text(
        "import sys,json,time,os\nrequest=json.loads(sys.stdin.readline())\n"
        f"open({str(marker)!r},'w').write('ready')\n"
        f"while not os.path.exists({str(release)!r}): time.sleep(.005)\n"
        "print(json.dumps({'id':request['id'],'result':{}}),flush=True)\n"
        "request=json.loads(sys.stdin.readline())\n"
        "assert request['method']=='account/read'\n"
        "print(json.dumps({'id':request['id'],'result':{'account':None,'requiresOpenaiAuth':True}}),flush=True)\n"
        "request=json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'id':request['id'],'result':{'type':'apiKey'}}),flush=True)\n"
        "print(json.dumps({'method':'account/login/completed','params':{'loginId':None,'success':True,'error':None}}),flush=True)\n"
        "print(json.dumps({'method':'account/updated','params':{'authMode':'apikey','planType':None}}),flush=True)\n"
        "request=json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'id':request['id'],'result':{'account':{'type':'apiKey'},'requiresOpenaiAuth':True}}),flush=True)\n"
        "time.sleep(30)\n"
    )
    rpc = transport_type()((sys.executable, "-u", str(script)), env={}, coding_mode=True)

    async def scenario():
        await rpc.start()
        try:
            reading = asyncio.create_task(rpc.request("config/read", {}))
            await wait_for_file(marker)
            with pytest.raises(CodexRPCError):
                await rpc.authenticate_api_key(CANARY)
            release.write_text("go")
            assert await reading == {}
            assert await rpc.authenticate_api_key(CANARY) == {
                "mode": "apiKey",
                "ephemeral": True,
                "barrier_verified": True,
            }
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_pre_reply_notification_is_refused(tmp_path):
    rpc, _ = peer(
        tmp_path,
        login=(
            "send({'method':'account/login/completed','params':{'loginId':None,'success':True,'error':None}})\n"
            "send({'id':request['id'],'result':{'type':'apiKey'}})\n"
        ),
    )

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(CodexRPCError):
                await rpc.authenticate_api_key(CANARY)
            assert_secret_absent(rpc)
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_late_same_batch_auth_after_barrier_cannot_publish_success(tmp_path):
    rpc, _ = peer(
        tmp_path,
        barrier=(
            "sys.stdout.write(json.dumps({'id':request['id'],'result':{'account':{'type':'apiKey'},'requiresOpenaiAuth':True}})+'\\n'"
            "+json.dumps({'method':'account/updated','params':{'authMode':'apikey','planType':None}})+'\\n');sys.stdout.flush()\n"
        ),
    )

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(CodexRPCError):
                await rpc.authenticate_api_key(CANARY)
            assert_secret_absent(rpc)
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_post_auth_remote_error_is_sanitized_before_correlated_future(tmp_path):
    rpc, _ = peer(
        tmp_path,
        extra=(
            "request=read()\nassert request['method']=='thread/start'\n"
            f"send({{'id':request['id'],'error':{{'code':-32000,'message':{CANARY!r},'data':{{'echo':{CANARY!r}}}}}}})\n"
        ),
    )

    async def scenario():
        await rpc.start()
        try:
            await rpc.authenticate_api_key(CANARY)
            with pytest.raises(CodexRPCError) as caught:
                await rpc.request("thread/start", {})
            assert_secret_absent(rpc, caught.value)
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_auth_traffic_after_business_reply_in_same_batch_fails_that_call(tmp_path):
    rpc, _ = peer(
        tmp_path,
        extra=(
            "request=read()\nassert request['method']=='thread/start'\n"
            "sys.stdout.write(json.dumps({'id':request['id'],'result':{'peerPid':os.getpid()}})+'\\n'"
            "+json.dumps({'method':'account/updated','params':{'authMode':'apikey','planType':None}})+'\\n');sys.stdout.flush()\n"
        ),
    )

    async def scenario():
        await rpc.start()
        try:
            await rpc.authenticate_api_key(CANARY)
            with pytest.raises(CodexRPCError):
                await rpc.request("thread/start", {})
            assert_secret_absent(rpc)
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("termination", ["cancel", "timeout"])
def test_incomplete_cleanup_retains_original_owner_and_cancellation_identity(
    tmp_path, monkeypatch, termination
):
    import signal

    from ralf_agent.codex_rpc import CodexRPCCloseIncomplete

    marker = tmp_path / "entered"
    rpc, _ = peer(
        tmp_path,
        initial=f"open({str(marker)!r},'w').write('ready')\ntime.sleep(30)\n",
        request_timeout=0.12 if termination == "timeout" else 3,
    )
    original_killpg = os.killpg
    denied = False

    def deny_one_final_signal(pid, number):
        nonlocal denied
        if pid == rpc.pid and number == signal.SIGKILL and not denied:
            denied = True
            raise PermissionError("synthetic final signal denial")
        return original_killpg(pid, number)

    monkeypatch.setattr(os, "killpg", deny_one_final_signal)

    async def scenario():
        await rpc.start()
        original_pid = rpc.pid
        authentication = asyncio.create_task(rpc.authenticate_api_key(CANARY))
        await wait_for_file(marker)
        if termination == "cancel":
            authentication.cancel()
            with pytest.raises(asyncio.CancelledError):
                await authentication
        else:
            with pytest.raises(CodexRPCCloseIncomplete):
                await authentication
        assert rpc.pid == original_pid
        assert rpc._state == "closing"
        assert rpc._close_task.done()
        assert isinstance(rpc._close_task.exception(), CodexRPCCloseIncomplete)
        assert_secret_absent(rpc)
        await rpc.aclose(wait_timeout=2)
        assert rpc._state == "closed"
        assert rpc.pid == original_pid
        with pytest.raises(ProcessLookupError):
            os.kill(original_pid, 0)

    asyncio.run(scenario())
    assert denied


@pytest.mark.parametrize("credential", [None, 1, True, "", "bad\0key", "bad\nkey", "bad\rkey"])
def test_invalid_credential_cannot_write_any_authentication_frame(tmp_path, credential):
    rpc, traffic = peer(tmp_path)

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(ValueError) as caught:
                await rpc.authenticate_api_key(credential)
            assert "bad" not in str(caught.value)
            assert not traffic.exists()
            assert await rpc.authenticate_api_key(CANARY) == {
                "mode": "apiKey",
                "ephemeral": True,
                "barrier_verified": True,
            }
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "login",
    [
        'sys.stdout.write(\'{"id":\'+str(request[\'id\'])+\',"result":{"type":"apiKey","type":"apiKey"}}\\n\');sys.stdout.flush()\n',
        "sys.stdout.write('x'*200+'\\n');sys.stdout.flush()\n",
        "sys.stdout.write('{\"id\":1');sys.stdout.flush();sys.exit(0)\n",
    ],
)
def test_auth_reuses_original_duplicate_frame_and_byte_bounds(tmp_path, login):
    rpc, _ = peer(tmp_path, login=login, max_message_bytes=150)

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(CodexRPCError) as caught:
                await rpc.authenticate_api_key(CANARY)
            assert_secret_absent(rpc, caught.value)
            assert rpc._state == "closed"
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_outgoing_credential_is_bounded_without_partial_login_or_retry(tmp_path):
    rpc, traffic = peer(tmp_path, max_message_bytes=150)

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(CodexRPCError) as caught:
                await rpc.authenticate_api_key(CANARY * 20)
            assert_secret_absent(rpc, caught.value)
            assert rpc._state == "closed"
        finally:
            await rpc.aclose()

    asyncio.run(scenario())
    assert [json.loads(line)["method"] for line in traffic.read_text().splitlines()] == [
        "account/read"
    ]


@pytest.mark.parametrize(
    "method",
    [
        "__init__",
        "request",
        "notify",
        "authenticate_api_key",
        "_auth_request",
        "_route",
        "_route_auth",
        "_sanitized_error",
    ],
)
def test_every_owned_auth_transport_method_can_publish_executable_fingerprint(method):
    from ralf_agent.component_fingerprint import executable_digest

    fingerprint = executable_digest(getattr(transport_type(), method))
    assert type(fingerprint) is str
    assert len(fingerprint) == 64
    assert all(character in "0123456789abcdef" for character in fingerprint)


@pytest.mark.parametrize(
    "method",
    [
        "account/login/start",
        "account/read",
        "account/logout",
        "account/future/auth/method",
        "loginApiKey",
        "loginChatGpt",
        "cancelLoginChatGpt",
        "logoutChatGpt",
        "getAuthStatus",
        "authStatusChange",
        "loginChatGptComplete",
    ],
)
@pytest.mark.parametrize("borrowed_allowlist", ["_METHODS", "_CONTROL_METHODS"])
def test_generic_auth_methods_remain_refused_when_borrowed_base_allowlist_drifts(
    tmp_path, monkeypatch, method, borrowed_allowlist
):
    from ralf_agent import codex_rpc

    monkeypatch.setattr(
        codex_rpc, borrowed_allowlist, getattr(codex_rpc, borrowed_allowlist) | {method}
    )
    rpc, traffic = peer(tmp_path)

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(ValueError):
                await rpc.request(method, {"type": "apiKey", "apiKey": CANARY})
            assert rpc._auth_used is False
            assert not traffic.exists()
            # The private, one-shot phase still owns all actual authentication.
            assert await rpc.authenticate_api_key(CANARY) == {
                "mode": "apiKey",
                "ephemeral": True,
                "barrier_verified": True,
            }
            with pytest.raises(ValueError):
                await rpc.request(method, {"type": "apiKey", "apiKey": CANARY})
            assert_secret_absent(rpc)
        finally:
            await rpc.aclose()

    asyncio.run(scenario())
    assert [json.loads(line)["method"] for line in traffic.read_text().splitlines()] == [
        "account/read",
        "account/login/start",
        "account/read",
    ]


@pytest.mark.parametrize("method", [None, 1, [], {}])
def test_generic_non_string_methods_keep_stable_value_error_without_wire(tmp_path, method):
    rpc, traffic = peer(tmp_path)

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(ValueError):
                await rpc.request(method, {})
            assert not traffic.exists()
        finally:
            await rpc.aclose()

    asyncio.run(scenario())
