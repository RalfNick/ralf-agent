"""Real, local stdio peers exercise transport boundaries without Codex/model runs."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import textwrap
import tracemalloc
from pathlib import Path

import pytest

from ralf_agent.codex_rpc import (
    CodexRPCClosed,
    CodexRPCCloseIncomplete,
    CodexRPCError,
    CodexRPCProtocolError,
    CodexRPCRemoteError,
    CodexRPCTransport,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")


def peer(tmp_path, body, **limits):
    script = tmp_path / "codex_rpc_peer.py"
    script.write_text(
        "import sys, json, time, os, signal\n"
        "def send(value):\n"
        "    print(json.dumps(value), flush=True)\n" + textwrap.dedent(body)
    )
    return CodexRPCTransport((sys.executable, "-u", str(script)), env={}, **limits)


def test_handshake_out_of_order_and_raw_peer_requests(tmp_path):
    rpc = peer(
        tmp_path,
        """
        first = json.loads(sys.stdin.readline())
        assert first['method'] == 'initialize'
        send({'id': first['id'], 'result': {'server': 'fake'}})
        ready = json.loads(sys.stdin.readline())
        assert ready == {'method': 'initialized'}
        a = json.loads(sys.stdin.readline())
        b = json.loads(sys.stdin.readline())
        send({'method': 'turn/started', 'params': {'turnId': 'turn-a'}})
        send({'id': 'approval-1', 'method': 'item/commandExecution/requestApproval',
              'params': {'command': 'test'}})
        send({'id': b['id'], 'result': {'thread': 'b'}})
        send({'id': a['id'], 'result': {'thread': 'a'}})
        # No approval response must be invented by the transport.
        last = json.loads(sys.stdin.readline())
        assert last['method'] == 'thread/read'
        send({'id': last['id'], 'result': {'noAutomaticApproval': True}})
        time.sleep(10)
    """,
    )

    async def scenario():
        await rpc.start()
        try:
            assert await rpc.request("initialize", {}) == {"server": "fake"}
            await rpc.notify("initialized")
            a = asyncio.create_task(rpc.request("thread/start", {}))
            b = asyncio.create_task(rpc.request("thread/read", {}))
            assert await a == {"thread": "a"}
            assert await b == {"thread": "b"}
            assert await rpc.next_event() == {
                "method": "turn/started",
                "params": {"turnId": "turn-a"},
            }
            event = await rpc.next_event()
            assert event["id"] == "approval-1"
            assert event["method"] == "item/commandExecution/requestApproval"
            assert await rpc.request("thread/read", {}) == {"noAutomaticApproval": True}
        finally:
            await rpc.aclose()
        with pytest.raises(CodexRPCClosed):
            await rpc.request("thread/start", {})

    asyncio.run(scenario())


@pytest.mark.parametrize("coding_mode", [False, True])
def test_only_coding_mode_retains_bounded_queued_peer_after_close(tmp_path, coding_mode):
    rpc = peer(
        tmp_path,
        """
        message=json.loads(sys.stdin.readline())
        send({'id':'queued-peer','method':'account/auth/request','params':{}})
        send({'id':message['id'],'result':{}})
        time.sleep(10)
    """,
        coding_mode=coding_mode,
        max_events=2,
    )

    async def scenario():
        await rpc.start()
        await rpc.request("thread/start", {})
        # No event consumer was scheduled before the queue-owning close.
        assert len(rpc._events) == 1
        await rpc.aclose()
        if coding_mode:
            assert await rpc.next_event() == {
                "id": "queued-peer",
                "method": "account/auth/request",
                "params": {},
            }
        with pytest.raises(CodexRPCClosed):
            await rpc.next_event()

    asyncio.run(scenario())


@pytest.mark.parametrize("startup_delay", [0, 0.2])
def test_timeout_and_cancel_do_not_retry_or_misroute_late_response(tmp_path, startup_delay):
    rpc = peer(
        tmp_path,
        """
        time.sleep(STARTUP_DELAY)
        send({'method': 'ready'})
        a = json.loads(sys.stdin.readline())
        # First request must expire before the caller sends the second.
        b = json.loads(sys.stdin.readline())
        send({'id': a['id'], 'result': {'late': True}})
        send({'method': 'secondSeen'})
        # Third request is sent only after cancellation of the second caller.
        c = json.loads(sys.stdin.readline())
        send({'id': b['id'], 'result': {'cancelledCaller': True}})
        send({'id': c['id'], 'result': {'third': True}})
        time.sleep(10)
    """.replace("STARTUP_DELAY", str(startup_delay)),
        request_timeout=0.04,
    )

    async def scenario():
        await rpc.start()
        try:
            assert await asyncio.wait_for(rpc.next_event(), 2) == {"method": "ready"}
            with pytest.raises(TimeoutError):
                await rpc.request("turn/start", {})
            cancelled = asyncio.create_task(rpc.request("thread/read", {}))
            assert await asyncio.wait_for(rpc.next_event(), 2) == {"method": "secondSeen"}
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            assert await rpc.request("thread/read", {}) == {"third": True}
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "wire",
    [
        '{"id":1,"result":{},"result":{}}\n',
        '{"id":true,"result":{}}\n',
        '{"id":1.0,"result":{}}\n',
        '{"id":null,"result":{}}\n',
        '{"id":999,"result":{}}\n',
        '{"id":1,"result":{"n":NaN}}\n',
        '{"id":1,"result":{"n":1e999}}\n',
        '{"id":1,"result":{},"error":{"code":1,"message":"bad"}}\n',
        '{"id":1,"result":[]}\n',
        '{"method":"event","params":[]}\n',
        "[]\n",
        '{"jsonrpc":"1.0","method":"event"}\n',
        "{}\n",
        "not json\n",
        '{"method":"event"}',
        "x" * 300 + "\n",
    ],
)
def test_invalid_frames_fail_closed(tmp_path, wire):
    rpc = peer(
        tmp_path,
        f"""
        sys.stdin.readline()
        sys.stdout.write({wire!r})
        sys.stdout.flush()
    """,
        max_message_bytes=256,
    )

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(CodexRPCProtocolError):
                await rpc.request("initialize", {})
            with pytest.raises(CodexRPCError):
                await rpc.notify("initialized")
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_event_and_pending_bounds(tmp_path):
    rpc = peer(
        tmp_path,
        """
        sys.stdin.readline()
        for i in range(4):
            send({'method': 'event', 'params': {'i': i}})
        time.sleep(10)
    """,
        max_events=2,
    )

    async def scenario():
        await rpc.start()
        try:
            first = asyncio.create_task(rpc.request("initialize", {}))
            second = asyncio.create_task(rpc.request("thread/read", {}))
            await asyncio.sleep(0)
            with pytest.raises(CodexRPCError):
                await rpc.request("thread/read", {})
            for request in (first, second):
                with pytest.raises(CodexRPCProtocolError):
                    await request
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_remote_error_is_not_success(tmp_path):
    rpc = peer(
        tmp_path,
        """
        req = json.loads(sys.stdin.readline())
        send({'id': req['id'], 'error': {'code': -1, 'message': 'rejected'}})
        time.sleep(10)
    """,
    )

    async def scenario():
        await rpc.start()
        try:
            with pytest.raises(CodexRPCRemoteError) as caught:
                await rpc.request("turn/start", {})
            assert caught.value.error == {"code": -1, "message": "rejected"}
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_cancelled_close_preserves_owner_and_reaps_process_group(tmp_path):
    heartbeat = tmp_path / "child-heartbeat"
    rpc = peer(
        tmp_path,
        f"""
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        child = os.fork()
        if child == 0:
            count = 0
            while True:
                count += 1
                with open({str(heartbeat)!r}, 'w') as heartbeat:
                    heartbeat.write(str(count))
                time.sleep(.01)
        while not os.path.exists({str(heartbeat)!r}):
            time.sleep(.001)
        send({{'method': 'identity', 'params': {{'pid': os.getpid(), 'child': child}}}})
        while True:
            time.sleep(1)
    """,
    )

    async def scenario():
        await rpc.start()
        ids = (await rpc.next_event())["params"]
        closing = asyncio.create_task(rpc.aclose())
        await asyncio.sleep(0.01)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        closing_again = asyncio.create_task(rpc.aclose())
        await asyncio.sleep(0.01)
        closing_again.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing_again
        await rpc.aclose(wait_timeout=2)
        with pytest.raises(ProcessLookupError):
            os.kill(ids["pid"], 0)
        # A descendant zombie is init's reap responsibility. Its actual heartbeat
        # must stop, independently of the leader's successful reap.
        stopped_heartbeat = heartbeat.read_text()
        await asyncio.sleep(0.05)
        assert heartbeat.read_text() == stopped_heartbeat
        with pytest.raises(CodexRPCClosed):
            await rpc.next_event()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"argv": []},
        {"argv": ()},
        {"argv": ("",)},
        {"argv": ("x\0",)},
        {"env": {"BAD=KEY": "x"}},
        {"env": {"X": "x\0"}},
        {"env": {"X": 1}},
        {"max_events": True},
        {"max_events": 0},
        {"max_message_bytes": 0},
        {"request_timeout": True},
        {"request_timeout": 0},
        {"request_timeout": float("inf")},
        {"request_timeout": float("nan")},
        {"coding_mode": 1},
        {"coding_mode": True, "control_only": True},
    ],
)
def test_invalid_configuration_never_spawns(tmp_path, kwargs):
    marker = tmp_path / "spawned"
    defaults = {"argv": (sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"), "env": {}}
    defaults.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        CodexRPCTransport(**defaults)
    assert not marker.exists()


def test_outgoing_methods_and_payloads_fail_before_peer_effect(tmp_path):
    rpc = peer(
        tmp_path,
        """
        req = json.loads(sys.stdin.readline())
        send({'id': req['id'], 'result': {'onlyAllowedRequest': req['method']}})
        time.sleep(10)
    """,
        max_message_bytes=256,
    )

    async def scenario():
        with pytest.raises(CodexRPCClosed):
            await rpc.request("initialize", {})
        await rpc.start()
        try:
            for method in ("process/spawn", "thread/shellCommand", "experimental/start"):
                with pytest.raises((TypeError, ValueError)):
                    await rpc.request(method, {})
            with pytest.raises((TypeError, ValueError)):
                await rpc.notify("turn/start", {})
            for params in ([], {"x": float("nan")}, {"x": "a" * 500}, {1: "not string"}):
                with pytest.raises((TypeError, ValueError)):
                    await rpc.request("turn/start", params)
            assert await rpc.request("thread/read", {}) == {"onlyAllowedRequest": "thread/read"}
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_huge_outgoing_string_is_rejected_before_encoding_allocation(tmp_path):
    rpc = peer(tmp_path, "time.sleep(10)", max_message_bytes=256)
    huge = {"text": '"' * 1024 * 1024}

    async def scenario():
        await rpc.start()
        try:
            tracemalloc.start()
            try:
                with pytest.raises(ValueError):
                    await rpc.request("turn/start", huge)
                assert tracemalloc.get_traced_memory()[1] < 256 * 1024
            finally:
                tracemalloc.stop()
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_close_timeout_keeps_cleanup_for_same_loop_retry(tmp_path):
    rpc = peer(
        tmp_path,
        """
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        send({'method': 'ready'})
        time.sleep(10)
    """,
    )

    async def scenario():
        await rpc.start()
        await rpc.next_event()
        process_id = rpc.pid
        with pytest.raises(CodexRPCCloseIncomplete):
            await rpc.aclose(wait_timeout=0.001)
        await rpc.aclose(wait_timeout=2)
        with pytest.raises(ProcessLookupError):
            os.kill(process_id, 0)

    asyncio.run(scenario())


def test_cancelled_start_is_owned_until_same_loop_close(tmp_path):
    rpc = peer(tmp_path, "time.sleep(10)")

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

    asyncio.run(scenario())


def test_event_loop_shutdown_during_cancelled_close_still_reaps(tmp_path):
    rpc = peer(
        tmp_path,
        """
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        send({'method': 'ready'})
        time.sleep(10)
    """,
    )

    async def scenario():
        await rpc.start()
        await rpc.next_event()
        closing = asyncio.create_task(rpc.aclose())
        await asyncio.sleep(0.01)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        return rpc.pid

    process_id = asyncio.run(scenario())
    try:
        with pytest.raises(ProcessLookupError):
            os.kill(process_id, 0)
    finally:
        # The intentionally RED lifecycle check must never leave its fake peer running.
        try:
            os.killpg(process_id, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_concurrent_notifications_have_bounded_outgoing_ownership(tmp_path):
    rpc = peer(
        tmp_path,
        """
        time.sleep(.1)
        first = json.loads(sys.stdin.readline())
        assert first['method'] == 'initialized'
        second = json.loads(sys.stdin.readline())
        assert second['method'] == 'thread/read'
        send({'id': second['id'], 'result': {'onlyOneNotification': True}})
        time.sleep(10)
    """,
        max_events=1,
        max_message_bytes=2 * 1024 * 1024,
    )

    async def scenario():
        await rpc.start()
        try:
            first = asyncio.create_task(rpc.notify("initialized", {"data": "a" * 1024 * 1024}))
            second = asyncio.create_task(rpc.notify("initialized"))
            await first
            with pytest.raises(CodexRPCError):
                await second
            assert await rpc.request("thread/read", {}) == {"onlyOneNotification": True}
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_repeated_write_timeouts_do_not_accumulate_unbounded_pipe_buffer(tmp_path):
    rpc = peer(
        tmp_path,
        "time.sleep(10)",
        max_events=1,
        max_message_bytes=2 * 1024 * 1024,
        request_timeout=0.005,
    )
    params = {"data": "a" * 1024 * 1024}

    async def scenario():
        await rpc.start()
        try:
            tracemalloc.start()
            try:
                for _ in range(12):
                    with pytest.raises(TimeoutError):
                        await rpc.request("turn/start", params)
                assert tracemalloc.get_traced_memory()[1] < 8 * 1024 * 1024
            finally:
                tracemalloc.stop()
        finally:
            await rpc.aclose()

    asyncio.run(scenario())


def test_cancelled_start_during_real_pipe_setup_and_shutdown_retains_pid(tmp_path):
    """Delay actual pipe attachment, with an independent watchdog for RED safety."""
    identity = tmp_path / "codex_rpc_launch_ids.json"
    heartbeat = tmp_path / "codex_rpc_launch_heartbeat"
    script = tmp_path / "codex_rpc_launch_peer.py"
    script.write_text(
        textwrap.dedent(f"""
        import os, json, time
        child = os.fork()
        if child == 0:
            while True:
                with open({str(heartbeat)!r}, 'w') as heartbeat:
                    heartbeat.write(str(time.monotonic()))
                time.sleep(.01)
        with open({str(identity)!r}, 'w') as identity:
            json.dump([os.getpid(), child], identity)
        time.sleep(10)
    """)
    )
    harness = tmp_path / "codex_rpc_launch_harness.py"
    harness.write_text(
        textwrap.dedent(f"""
        import asyncio, json, os, pathlib, signal, sys, threading, time
        from ralf_agent.codex_rpc import CodexRPCTransport
        identity = pathlib.Path({str(identity)!r})
        heartbeat = pathlib.Path({str(heartbeat)!r})
        done = threading.Event()
        def watchdog():
            if done.wait(2):
                return
            if identity.exists():
                try:
                    os.killpg(json.loads(identity.read_text())[0], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            os._exit(9)
        threading.Thread(target=watchdog, daemon=True).start()
        rpc = CodexRPCTransport((sys.executable, '-u', {str(script)!r}), env={{}})
        async def scenario():
            loop = asyncio.get_running_loop()
            original = loop.connect_read_pipe
            async def delayed(*args, **kwargs):
                await asyncio.sleep(.5)
                return await original(*args, **kwargs)
            loop.connect_read_pipe = delayed
            starting = asyncio.create_task(rpc.start())
            for _ in range(200):
                if identity.exists() and heartbeat.exists():
                    break
                await asyncio.sleep(.005)
            assert identity.exists() and heartbeat.exists()
            ids = json.loads(identity.read_text())
            owned_before_ack = rpc.pid == ids[0]
            starting.cancel()
            try:
                await starting
            except asyncio.CancelledError:
                pass
            return ids, owned_before_ack
        ids, owned_before_ack = asyncio.run(scenario())
        try:
            os.kill(ids[0], 0)
            leader_reaped = False
        except ProcessLookupError:
            leader_reaped = True
        old = heartbeat.read_text()
        time.sleep(.05)
        print(json.dumps({{'owned_before_ack': owned_before_ack,
            'leader_reaped': leader_reaped, 'child_stopped': heartbeat.read_text() == old}}))
        done.set()
    """)
    )
    try:
        result = subprocess.run(
            [sys.executable, "-u", str(harness)],
            capture_output=True,
            text=True,
            timeout=4,
            env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        )
        assert result.returncode == 0, result.stderr or "startup cleanup watchdog fired"
        assert json.loads(result.stdout) == {
            "owned_before_ack": True,
            "leader_reaped": True,
            "child_stopped": True,
        }
    finally:
        if identity.exists():
            try:
                os.killpg(json.loads(identity.read_text())[0], signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_signal_permission_failure_is_incomplete_and_keeps_pid_for_retry(tmp_path, monkeypatch):
    rpc = peer(
        tmp_path,
        """
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        send({'method': 'ready'})
        time.sleep(10)
    """,
    )

    def denied(*args):
        raise PermissionError("injected signal denial")

    async def scenario():
        await rpc.start()
        await rpc.next_event()
        pid = rpc.pid
        try:
            with monkeypatch.context() as patch:
                patch.setattr("ralf_agent.codex_rpc.os.killpg", denied)
                with pytest.raises(CodexRPCCloseIncomplete):
                    await rpc.aclose()
            assert rpc.pid == pid
            os.kill(pid, 0)
        finally:
            await rpc.aclose(wait_timeout=2)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)

    asyncio.run(scenario())
