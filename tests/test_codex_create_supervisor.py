"""Real CREATE gates retain original handles and never infer end from EOF."""

import importlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ralf_agent.errors import DefinitionMismatch, ExecutionHostFailed, ValidationError
from tests.coding_cli_fixture import ready_cli


def supervisor():
    name = "ralf_agent.codex_create_supervisor"
    assert importlib.util.find_spec(name) is not None, "Original CREATE supervisor is missing"
    return importlib.import_module(name).CreateSupervisor


@pytest.fixture
def operation(tmp_path):
    import fcntl

    root = tmp_path / "resource"
    root.mkdir(mode=0o700)
    root = root.resolve()
    cli = tmp_path / "docker"
    cli.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """import json,os,pathlib,sys,time
if sys.argv[1:]==['--fixture-ready']:sys.exit(0)
p=pathlib.Path(sys.argv[2]).parent;mode=sys.argv[6]
if mode=='entry-hold':
 while not (p/'finish').exists():time.sleep(.01)
with (p/'invocations').open('a') as f:f.write(str(os.getpid())+'\\n')
(p/'cli-env.json').write_text(json.dumps(dict(os.environ)))
if mode=='hold':
 while not (p/'finish').exists():time.sleep(.01)
elif mode=='eof-live':
 os.close(1);os.close(2)
 while not (p/'finish').exists():time.sleep(.01)
elif mode=='overflow':sys.stderr.write('synthetic-output'*10000);sys.stderr.flush()
elif mode=='descendant':
 pid=os.fork()
 if pid==0:
  while True:time.sleep(1)
print('d'*64,flush=True)
"""
    )
    cli.chmod(0o700)
    ready_cli(cli)
    assert not tuple(root.iterdir())
    assert set(tmp_path.iterdir()) == {root, cli}
    lease = os.open(root / "lease.lock", os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    binding = {
        "environment": {"kind": "synthetic-original", "root": str(root)},
        "generation": "a" * 32,
        "operation_digest": "b" * 64,
    }
    try:
        yield root, lease, cli.resolve(), binding
    finally:
        (root / "finish").touch()
        declaration_path = root / ".create-operation" / "declaration.json"
        if declaration_path.exists():
            from ralf_agent.codex_create_journal import lock_released

            declaration = json.loads(declaration_path.read_text())
            eventually(lambda: lock_released(declaration["operation_lock"]), timeout=8)
            shutil.rmtree(declaration["control_directory"]["path"])
        os.close(lease)


def create(operation, mode="success", **changes):
    root, lease, cli, binding = operation
    options = dict(
        binding=binding,
        argv=[
            str(cli),
            "--config",
            str(root / "docker-client"),
            "--host",
            "unix:///synthetic.sock",
            "create",
            mode,
        ],
        namespace_lease_fd=lease,
        cli_env={"PATH": "/usr/bin:/bin"},
        timeout=3.0,
        output_limit=65536,
    )
    options.update(changes)
    return supervisor().create(root, **options)


def eventually(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "Original process barrier did not complete"
        time.sleep(0.01)


def test_cli_fixture_readiness_has_no_business_or_operation_effect(operation):
    root, _, cli, _ = operation
    original = cli.read_bytes()
    files = set(root.iterdir())
    ready = subprocess.run(
        [str(cli), "--fixture-ready"],
        env={"PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        start_new_session=True,
        timeout=5,
    )
    assert ready.returncode == 0
    assert ready.stdout == ready.stderr == b""
    assert cli.read_bytes() == original
    assert set(root.iterdir()) == files == {root / "lease.lock"}


def test_ready_cli_still_obeys_original_deadline_before_business_entry(operation):
    handle = create(operation, "entry-hold")
    try:
        handle.launch()
        handle.start_once()
        value = handle.drain()
        assert value["complete"] and value["helpers_ended"] and value["control_drained"]
        receipt = value["receipt"]
        assert receipt["reason"] == "timeout"
        assert receipt["cli_gate_accepted"] is True and receipt["cli_exec_started"] is True
        assert receipt["child_ended"] is True and receipt["exit_code"] != 0
        assert receipt["cid"] is None
        assert not (operation[0] / "invocations").exists()
        with pytest.raises(DefinitionMismatch):
            handle.start_once()
    finally:
        handle.close()


def test_construction_has_no_cli_and_outer_never_gate_produces_actual_drained_receipt(operation):
    handle = create(operation)
    root = operation[0]
    try:
        assert not (root / "invocations").exists()
        declaration = handle.declaration
        handle.launch()
        assert not (root / "invocations").exists()
        value = handle.abort()
        assert value["complete"] and value["helpers_ended"] and value["control_drained"]
        receipt = value["receipt"]
        assert receipt["gate_sealed"] is True
        assert receipt["cli_gate_accepted"] is False
        assert receipt["cli_exec_started"] is False
        assert receipt["cid"] is None
        cold = supervisor().open(root, declaration)
        try:
            assert cold.query()["receipt_digest"] == value["receipt_digest"]
            with pytest.raises(DefinitionMismatch):
                cold.start_once()
        finally:
            cold.close()
        with pytest.raises(DefinitionMismatch):
            handle.start_once()
        with pytest.raises(DefinitionMismatch):
            create(operation)
    finally:
        handle.close()


def test_success_is_one_exact_same_pid_exec_and_no_host_environment_leak(operation, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-must-not-inherit")
    handle = create(operation)
    try:
        handle.launch()
        handle.start_once()
        value = handle.drain()
        assert value["complete"]
        assert not (Path(handle.declaration["control_directory"]["path"]) / "control.sock").exists()
        receipt = value["receipt"]
        assert receipt["cli_gate_accepted"] is True and receipt["cli_exec_started"] is True
        assert receipt["cid"] == "d" * 64
        invocations = (operation[0] / "invocations").read_text().splitlines()
        assert invocations == [str(receipt["child"]["pid"])]
        assert "OPENAI_API_KEY" not in json.loads((operation[0] / "cli-env.json").read_text())
        with pytest.raises(DefinitionMismatch):
            handle.start_once()
    finally:
        handle.close()


@pytest.mark.parametrize("mode", ["hold", "eof-live", "overflow", "descendant"])
def test_timeout_output_and_eof_require_actual_original_child_end(operation, mode):
    handle = create(operation, mode)
    try:
        handle.launch()
        handle.start_once()
        eventually(lambda: (operation[0] / "invocations").exists())
        if mode in {"hold", "eof-live"}:
            assert handle.query()["complete"] is False
        value = handle.drain()
        assert value["helpers_ended"] and value["control_drained"]
        assert value["receipt"]["child_ended"] is True
        assert value["receipt"]["cli_exec_started"] is True
        assert value["receipt"]["cli_gate_accepted"] is True
        if mode != "descendant":
            assert value["receipt"]["cid"] is None
    finally:
        handle.close()


def test_cold_control_drains_live_original_broker_without_go(operation):
    handle = create(operation, "hold")
    handle.launch()
    handle.start_once()
    eventually(lambda: (operation[0] / "invocations").exists())
    cold = supervisor().open(operation[0], handle.declaration)
    try:
        result = cold.abort()
        assert result["helpers_ended"] and result["control_drained"]
        assert result["receipt"]["cli_exec_started"] is True
        handle.drain()
        with pytest.raises(DefinitionMismatch):
            cold.launch()
    finally:
        cold.close()
        handle.close()


def test_broker_death_cannot_raw_signal_original_live_cli_or_relaunch(operation):
    handle = create(operation, "hold")
    handle.launch()
    handle.start_once()
    eventually(lambda: (operation[0] / "invocations").exists())
    os.kill(handle._process.pid, signal.SIGKILL)
    cold = supervisor().open(operation[0], handle.declaration)
    try:
        eventually(lambda: handle._monitor.exited())
        assert cold.query()["complete"] is False
        with pytest.raises(ExecutionHostFailed):
            cold.abort(timeout=0.2)
        assert len((operation[0] / "invocations").read_text().splitlines()) == 1
        assert not (operation[0] / "finish").exists()
        (operation[0] / "finish").touch()
    finally:
        handle.close()
        cold.close()


@pytest.mark.parametrize("frame", [b"{", b"{}\n{}\n", b"{}\n"])
def test_partial_or_duplicate_outer_frames_cannot_create(operation, frame):
    handle = create(operation)
    try:
        handle.launch()
        os.write(handle._go_write, frame)
        os.close(handle._go_write)
        handle._go_write = None
        value = handle.drain()
        assert value["receipt"]["cli_gate_accepted"] is False
        assert not (operation[0] / "invocations").exists()
    finally:
        handle.close()


def test_unregistered_inner_gate_failure_has_no_fabricated_negative_receipt(operation):
    handle = create(operation)
    try:
        handle.launch()
        (operation[0] / ".create-operation" / "gate-register.json").symlink_to("/missing")
        handle.start_once()
        with pytest.raises(DefinitionMismatch):
            handle.drain()
        eventually(lambda: handle._monitor.exited())
        assert not (operation[0] / "invocations").exists()
    finally:
        handle.close()


def test_failed_outer_registration_cannot_send_late_go(operation):
    handle = create(operation)
    try:
        (operation[0] / ".create-operation" / "broker-register.json").symlink_to("/missing")
        with pytest.raises((DefinitionMismatch, ExecutionHostFailed)):
            handle.launch()
        with pytest.raises(DefinitionMismatch):
            handle.start_once()
        assert not (operation[0] / ".create-operation" / "worker-go.json").exists()
        assert not (operation[0] / "invocations").exists()
    finally:
        handle.close()


@pytest.mark.parametrize(
    "options",
    [
        {"cli_env": {"PATH": "/usr/bin:/bin", "OPENAI_API_KEY": "synthetic"}},
        {"timeout": True},
        {"output_limit": True},
        {"namespace_lease_fd": True},
    ],
)
def test_invalid_configuration_rejected_before_any_operation_files(operation, options):
    with pytest.raises((ValidationError, DefinitionMismatch)):
        create(operation, **options)
    assert not (operation[0] / ".create-operation").exists()


def test_unknown_control_token_does_not_stop_or_unseal_original_cli(operation):
    import socket

    handle = create(operation, "hold")
    try:
        handle.launch()
        handle.start_once()
        eventually(lambda: (operation[0] / "invocations").exists())
        path = Path(handle.declaration["control_directory"]["path"]) / "control.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(str(path))
            client.sendall(
                json.dumps(
                    {"token": "0" * 32, "declaration_digest": "0" * 64, "command": "abort"}
                ).encode()
            )
            client.shutdown(socket.SHUT_WR)
            try:
                client.recv(1024)
            except OSError:
                pass
        assert not handle._monitor.exited()
        (operation[0] / "finish").touch()
        value = handle.drain()
        assert value["receipt"]["cid"] == "d" * 64
    finally:
        handle.close()


@pytest.mark.parametrize("send_go", [False, True])
def test_real_worker_exit_keeps_broker_control_and_cold_drain(operation, send_go):
    root, lease, cli, binding = operation
    argv = [
        str(cli),
        "--config",
        str(root / "docker-client"),
        "--host",
        "unix:///synthetic.sock",
        "create",
        "hold",
    ]
    code = """import json,pathlib,sys,time
from ralf_agent.codex_create_supervisor import CreateSupervisor
root=pathlib.Path(sys.argv[1]);binding=json.loads(sys.argv[3]);argv=json.loads(sys.argv[4])
handle=CreateSupervisor.create(root,binding=binding,argv=argv,namespace_lease_fd=int(sys.argv[2]),cli_env={'PATH':'/usr/bin:/bin'},timeout=3,output_limit=65536)
handle.launch()
if sys.argv[5]=='yes':handle.start_once()
(root/'worker-ready').touch()
while True:time.sleep(.05)
"""
    worker = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            str(root),
            str(lease),
            json.dumps(binding),
            json.dumps(argv),
            "yes" if send_go else "no",
        ],
        pass_fds=(lease,),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    cold = None
    try:
        eventually(lambda: (root / "worker-ready").exists())
        if send_go:
            eventually(lambda: (root / "invocations").exists())
        os.kill(worker.pid, signal.SIGKILL)
        worker.wait(timeout=3)
        declaration = json.loads((root / ".create-operation" / "declaration.json").read_text())
        cold = supervisor().open(root, declaration)
        value = cold.abort()
        assert value["helpers_ended"] and value["control_drained"]
        assert value["receipt"]["cli_gate_accepted"] is send_go
        assert value["receipt"]["cli_exec_started"] is send_go
        if not send_go:
            assert not (root / "invocations").exists()
        with pytest.raises(DefinitionMismatch):
            cold.start_once()
    finally:
        if worker.returncode is None:
            worker.kill()
            worker.wait(timeout=3)
        if cold is not None:
            cold.close()


def test_worker_go_fsync_failure_never_sends_execution_grant(operation, monkeypatch):
    handle = create(operation)
    try:
        handle.launch()
        with monkeypatch.context() as patch:

            def failed_fsync(fd):
                raise OSError("synthetic-fsync-failure")

            patch.setattr(os, "fsync", failed_fsync)
            with pytest.raises(OSError, match="synthetic-fsync-failure"):
                handle.start_once()
        value = handle.abort()
        assert value["receipt"]["cli_gate_accepted"] is False
        assert not (operation[0] / "invocations").exists()
        assert not (operation[0] / ".create-operation" / "worker-go.json").exists()
    finally:
        handle.close()


def test_accepted_inner_gate_with_failed_exec_record_stays_maybe_dispatched(operation):
    handle = create(operation)
    try:
        handle.launch()
        path = operation[0] / ".create-operation" / "gate-exec.json"
        path.write_text("{}")
        path.chmod(0o600)
        handle.start_once()
        value = handle.drain()
        assert value["receipt"]["cli_gate_accepted"] is True
        assert value["receipt"]["cli_exec_started"] is True
        assert value["receipt"]["cid"] is None
        assert not (operation[0] / "invocations").exists()
    finally:
        handle.close()


def test_fixed_bootstrap_checks_all_bytes_before_import_and_skips_package_init(tmp_path):
    import hashlib

    from ralf_agent import coding_create_inventory
    from ralf_agent.codex_create_supervisor import _BOOTSTRAP

    directory = tmp_path / "installed-package"
    directory.mkdir()
    marker = tmp_path / "untrusted-import"
    required = coding_create_inventory.source_inventory()
    for name, source in coding_create_inventory.source_paths().items():
        (directory / (name + ".py")).write_bytes(Path(source).read_bytes())
    dangerous = "from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n"
    (directory / "__init__.py").write_text(dangerous)
    required["__init__"] = hashlib.sha256(dangerous.encode()).hexdigest()
    command = [
        sys.executable,
        "-I",
        "-c",
        _BOOTSTRAP,
        str(directory),
        json.dumps(required),
        "codex_create_gate",
    ]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, timeout=5)
    assert result.returncode == 2
    assert not marker.exists()
    with (directory / "codex_create_gate.py").open("a") as stream:
        stream.write(dangerous)
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, timeout=5)
    assert result.returncode == 2
    assert not marker.exists()


def test_source_hash_drift_blocks_outer_launch_before_subprocess(operation):
    handle = create(operation)
    try:
        handle._journal.declaration["required_sources"]["codex_create_gate"] = "0" * 64
        with pytest.raises(DefinitionMismatch):
            handle.launch()
        assert handle._process is None
        assert not (operation[0] / "invocations").exists()
    finally:
        handle.close()


def test_completion_cannot_relabel_original_accepted_gate_as_negative(operation):
    handle = create(operation)
    try:
        handle.launch()
        handle.start_once()
        value = handle.drain()
        receipt = value["receipt"]
        receipt["cli_gate_accepted"] = False
        receipt["cli_exec_started"] = False
        receipt["cid"] = None
        path = operation[0] / ".create-operation" / "broker-result.json"
        path.unlink()
        path.write_text(json.dumps(receipt))
        path.chmod(0o600)
        with pytest.raises(DefinitionMismatch):
            handle.query()
    finally:
        handle.close()


def test_cold_end_observation_handles_exit_between_birth_and_status(monkeypatch):
    from types import SimpleNamespace

    from ralf_agent import codex_create_journal

    observed = iter(["original-birth", None])
    monkeypatch.setattr(codex_create_journal, "birth", lambda pid: next(observed))
    monkeypatch.setattr(
        codex_create_journal.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=b""),
    )
    assert codex_create_journal.process_ended({"pid": 321, "birth": "original-birth"}) is True


def test_atomic_record_reader_waits_for_writer_temporary_link_retirement(operation, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    handle = create(operation)
    original_link = os.link
    value = {"declaration_digest": "synthetic"}
    reader = None
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:

            def paused_link(source, target, **options):
                nonlocal reader
                original_link(source, target, **options)
                reader = pool.submit(handle._journal.read, "launch.json")
                time.sleep(0.03)

            monkeypatch.setattr(os, "link", paused_link)
            handle._journal.write("launch.json", value)
            assert reader.result(timeout=1) == value
    finally:
        handle.close()
