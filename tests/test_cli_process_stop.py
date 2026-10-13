"""Original process-group signalling never treats persistent denial as stop."""

import errno
import os
import select
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ralf_agent import cli_process


def stopped_process():
    events = []
    process = SimpleNamespace(
        pid=12345,
        poll=lambda: None,
        wait=lambda **options: events.append(("wait", options)),
        stdin=SimpleNamespace(close=lambda: events.append(("stdin", "close"))),
        stdout=SimpleNamespace(close=lambda: events.append(("stdout", "close"))),
    )
    return process, events


@pytest.mark.parametrize("phase", [signal.SIGTERM, signal.SIGKILL])
@pytest.mark.parametrize("absent", [False, True])
def test_original_group_permission_race_requires_later_signal_or_absence(
    monkeypatch, phase, absent
):
    process, events = stopped_process()
    calls = []
    clock = [0.0]

    def killpg(pgid, signum):
        calls.append((pgid, signum))
        if signum == phase:
            if calls.count((pgid, signum)) == 1:
                raise PermissionError(errno.EPERM, "group exit race")
            if absent:
                raise ProcessLookupError(errno.ESRCH, "original group absent")

    monkeypatch.setattr(cli_process.os, "killpg", killpg)
    monkeypatch.setattr(cli_process.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        cli_process.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay)
    )
    cli_process.stop_process(process)
    assert all(pgid == process.pid for pgid, _ in calls)
    assert calls.count((process.pid, phase)) == 2
    assert ("stdin", "close") in events and ("stdout", "close") in events


@pytest.mark.parametrize("phase", [signal.SIGTERM, signal.SIGKILL])
def test_persistent_original_group_permission_denial_remains_failure(monkeypatch, phase):
    process, events = stopped_process()
    calls = []
    clock = [0.0]

    def killpg(pgid, signum):
        calls.append((pgid, signum))
        if signum == phase:
            raise PermissionError(errno.EPERM, "actual persistent denial")

    monkeypatch.setattr(cli_process.os, "killpg", killpg)
    monkeypatch.setattr(cli_process.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        cli_process.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay)
    )
    with pytest.raises(PermissionError, match="actual persistent denial"):
        cli_process.stop_process(process)
    assert all(pgid == process.pid for pgid, _ in calls)
    assert 1 < calls.count((process.pid, phase)) <= 25
    assert 0.1 <= clock[0] <= 0.11
    assert ("stdin", "close") not in events


def test_other_signal_permission_error_is_not_retried(monkeypatch):
    process, _ = stopped_process()
    calls = []

    def killpg(pgid, signum):
        calls.append((pgid, signum))
        raise PermissionError(errno.EACCES, "unrelated error")

    monkeypatch.setattr(cli_process.os, "killpg", killpg)
    with pytest.raises(PermissionError, match="unrelated error"):
        cli_process.stop_process(process)
    assert calls == [(process.pid, signal.SIGTERM)]


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin zombie-group EPERM required")
def test_owned_zombie_leader_is_reaped_before_original_group_retry():
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys;sys.stdin.read()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        watcher = select.kqueue()
        try:
            watcher.control(
                [
                    select.kevent(
                        process.pid,
                        filter=select.KQ_FILTER_PROC,
                        flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                        fflags=select.KQ_NOTE_EXIT,
                    )
                ],
                0,
                0,
            )
            process.stdin.close()
            exited = watcher.control([], 1, 3)
            assert len(exited) == 1 and exited[0].ident == process.pid
            assert exited[0].fflags & select.KQ_NOTE_EXIT
        finally:
            watcher.close()
        # The kernel exit event proves exit without wait/poll reaping our child.
        assert process.returncode is None
        cli_process.stop_process(process)
        assert process.returncode == 0
        assert process.stdout.closed
        with pytest.raises(ProcessLookupError):
            os.killpg(process.pid, 0)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        process.stdin.close()
        process.stdout.close()
