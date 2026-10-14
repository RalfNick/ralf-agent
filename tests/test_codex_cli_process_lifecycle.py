"""Original CLI end is observed without permitting PID/group reuse before signalling."""

import os
import signal
import sys
import time
from types import SimpleNamespace

import pytest

from ralf_agent import codex_environment as module
from ralf_agent.errors import ExecutionHostFailed


def bare_owner(tmp_path, program, *, timeout=2):
    executable = tmp_path / "fixed-cli"
    executable.write_text(f"#!{sys.executable}\n" + program)
    executable.chmod(0o700)
    owner = object.__new__(module.DockerCodingEnvironment)
    owner._check_root = owner._check_files = lambda: None
    owner._docker = str(executable)
    owner._root = tmp_path
    owner._host = "unix:///fixture/docker.sock"
    owner._timeout = timeout
    return owner


@pytest.mark.parametrize("operation", ["cli", "namespace_query"])
def test_successful_cli_never_signals_group_after_original_leader_reap(
    monkeypatch, tmp_path, operation
):
    # Replace OS ports to force an otherwise rare, legal PID-reuse schedule.
    events = []
    state = {"reaped": False}

    class Process:
        pid = 123456
        returncode = None
        stdout = SimpleNamespace(close=lambda: None)
        stderr = SimpleNamespace(close=lambda: None)

        def wait(self, **kwargs):
            events.append("wait")
            state["reaped"] = True
            self.returncode = 0
            return 0

    class Selector:
        def register(self, *args):
            pass

        def get_map(self):
            return {}

        def close(self):
            pass

    class Monitor:
        _closed = False

        def register(self, process):
            assert process.returncode is None
            self._process = process

        def exited(self, timeout=0):
            return True

        def close(self):
            pass

    def signal_group(pid, signum):
        events.append(("killpg", state["reaped"]))

    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: Process())
    monkeypatch.setattr(module.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(module, "ChildExitMonitor", Monitor, raising=False)
    monkeypatch.setattr(module.os, "killpg", signal_group)
    owner = bare_owner(tmp_path, "pass\n")
    if operation == "cli":
        assert owner._cli(["create"]) == (b"", b"")
    else:
        assert owner._namespace_query(tmp_path / "docker-client", ["ps", "-a"]) == b""
    assert not any(isinstance(item, tuple) and item[1] for item in events), events


def test_stdout_eof_does_not_kill_cli_before_its_successful_actual_exit(tmp_path):
    done = tmp_path / "completed"
    owner = bare_owner(
        tmp_path,
        "import os,time,pathlib\nos.close(1);os.close(2)\ntime.sleep(.15)\n"
        + f"pathlib.Path({str(done)!r}).write_text('completed')\n",
    )
    assert owner._cli(["create"]) == (b"", b"")
    assert done.read_text() == "completed"


def test_success_exit_kills_original_descendant_holding_pipe_without_waiting_deadline(tmp_path):
    marker = tmp_path / "descendant-completed"
    owner = bare_owner(
        tmp_path,
        "import os,time,pathlib\nchild=os.fork()\nif child==0:\n time.sleep(5)\n"
        + f" pathlib.Path({str(marker)!r}).write_text('escaped')\n os._exit(0)\n"
        + "print('original',flush=True)\nos._exit(0)\n",
        timeout=2,
    )
    started = time.monotonic()
    assert owner._cli(["create"])[0] == b"original\n"
    assert time.monotonic() - started < 2
    assert not marker.exists()


@pytest.mark.parametrize("failure", ["deadline", "output"])
def test_error_cleanup_signals_only_unreaped_child_and_reaps_actual_process(
    tmp_path, monkeypatch, failure
):
    pids = []
    spawn = module.subprocess.Popen

    def owned_spawn(*args, **kwargs):
        process = spawn(*args, **kwargs)
        pids.append(process.pid)
        return process

    monkeypatch.setattr(module.subprocess, "Popen", owned_spawn)
    code = "import time\n"
    code += (
        "time.sleep(5)\n"
        if failure == "deadline"
        else "print('x'*100000,flush=True)\ntime.sleep(5)\n"
    )
    owner = bare_owner(tmp_path, code, timeout=0.15)
    if failure == "output":
        monkeypatch.setattr(module, "_CAP", 100)
    with pytest.raises(ExecutionHostFailed):
        owner._cli(["create"])
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)


def test_custom_sigchld_refuses_before_cli_spawn(tmp_path):
    marker = tmp_path / "spawned"
    owner = bare_owner(tmp_path, f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    previous = signal.signal(signal.SIGCHLD, lambda *_: None)
    try:
        with pytest.raises(ExecutionHostFailed):
            owner._cli(["create"])
        assert not marker.exists()
    finally:
        signal.signal(signal.SIGCHLD, previous)


def test_missing_monitor_support_refuses_before_cli_spawn(tmp_path, monkeypatch):
    from ralf_agent import coding_process_wait

    marker = tmp_path / "spawned"
    owner = bare_owner(tmp_path, f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    monkeypatch.setattr(coding_process_wait.sys, "platform", "unsupported-posix")
    with pytest.raises(ExecutionHostFailed):
        owner._cli(["create"])
    assert not marker.exists()
