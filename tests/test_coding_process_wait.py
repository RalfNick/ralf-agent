"""Nonreaping direct-child exit observation preserves a later authoritative wait."""

import ctypes
import errno
import importlib.util
import signal
import subprocess
import sys
import time

import pytest


def monitor_type():
    assert importlib.util.find_spec("relf_agent.coding_process_wait") is not None
    from relf_agent.coding_process_wait import ChildExitMonitor

    return ChildExitMonitor


@pytest.mark.parametrize("register_after_exit", [False, True])
def test_exit_observation_leaves_original_child_unreaped(register_after_exit):
    monitor = monitor_type()()
    process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
    try:
        if register_after_exit:
            time.sleep(0.1)
        monitor.register(process)
        assert monitor.exited(timeout=2)
        assert monitor.exited(timeout=0)
        assert process.returncode is None
        assert process.wait(timeout=2) == 7
    finally:
        process.wait(timeout=2)
        monitor.close()


def test_live_child_is_not_reported_ended_or_reaped():
    monitor = monitor_type()()
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys;sys.stdin.read()"], stdin=subprocess.PIPE
    )
    try:
        monitor.register(process)
        assert not monitor.exited(timeout=0.02)
        assert process.returncode is None
        process.stdin.close()
        assert monitor.exited(timeout=2)
        assert process.wait(timeout=2) == 0
    finally:
        process.stdin.close()
        process.wait(timeout=2)
        monitor.close()


@pytest.mark.parametrize("handler", [signal.SIG_IGN, lambda *_: None])
def test_sigchld_reaper_policy_refused_before_any_child(handler):
    monitor = monitor_type()
    previous = signal.signal(signal.SIGCHLD, handler)
    try:
        with pytest.raises(RuntimeError):
            monitor()
    finally:
        signal.signal(signal.SIGCHLD, previous)


def test_numeric_cold_pid_is_not_a_registered_direct_child():
    monitor = monitor_type()()
    try:
        with pytest.raises((TypeError, RuntimeError)):
            monitor.register(12345)
    finally:
        monitor.close()


def test_unsupported_platform_has_no_reaping_fallback(monkeypatch):
    from relf_agent import coding_process_wait as module

    monkeypatch.setattr(module.sys, "platform", "unsupported-posix")
    with pytest.raises(RuntimeError):
        module.ChildExitMonitor()


def test_failed_zero_byte_darwin_group_query_is_not_absence(monkeypatch):
    from relf_agent import coding_process_wait as module

    def failed_query(*args):
        ctypes.set_errno(errno.EACCES)
        return 0

    class Library:
        proc_listpids = staticmethod(failed_query)

    monkeypatch.setattr(module.ctypes, "CDLL", lambda *a, **k: Library())
    with pytest.raises(RuntimeError):
        module._darwin_group_members(12345)


@pytest.mark.parametrize("members", [{12345}, set(), {12345, 12346}])
def test_darwin_zombie_permission_exception_requires_only_original_leader(monkeypatch, members):
    from types import SimpleNamespace

    from relf_agent import coding_process_wait as module

    process = SimpleNamespace(pid=12345, returncode=None)
    monitor = SimpleNamespace(_process=process, _closed=False, exited=lambda: True)

    def denied(*args):
        raise PermissionError(errno.EPERM, "group denied")

    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.os, "killpg", denied)
    monkeypatch.setattr(module, "_darwin_group_members", lambda pid: members)
    if members <= {12345}:
        module.signal_unreaped_group(process, monitor)
    else:
        with pytest.raises(PermissionError):
            module.signal_unreaped_group(process, monitor)


def test_reaped_child_cannot_signal_any_numeric_group(monkeypatch):
    from types import SimpleNamespace

    from relf_agent import coding_process_wait as module

    process = SimpleNamespace(pid=12345, returncode=0)
    monitor = SimpleNamespace(_process=process, _closed=False)
    monkeypatch.setattr(module.os, "killpg", lambda *a: pytest.fail("foreign signal"))
    with pytest.raises(RuntimeError):
        module.signal_unreaped_group(process, monitor)
