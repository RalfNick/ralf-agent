"""Separately gated actual Docker CREATE recovery; no native START or model call."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from relf_agent.codex_coding_profile import CodexCodingProfile
from relf_agent.codex_create_journal import lock_released, private_directory, process_ended
from relf_agent.codex_environment import DockerCodingEnvironment
from relf_agent.coding_process_wait import ChildExitMonitor, signal_unreaped_group

pytestmark = pytest.mark.skipif(
    os.environ.get("RALF_CODEX_SUPERVISED_CREATE_RECOVERY_INTEGRATION") != "1",
    reason="Explicitly enable the isolated supervised CREATE recovery Docker tests",
)

CHILD = r"""
import asyncio,json,os,sys
from pathlib import Path
from relf_agent.codex_create_supervisor import CreateSupervisor
from relf_agent.codex_environment import DockerCodingEnvironment
from relf_agent.errors import ExecutionHostFailed
case=Path(sys.argv[1]);mode=sys.argv[2]
config=json.loads((case/'configuration.json').read_text())
environment=DockerCodingEnvironment(**config)
original_drain=CreateSupervisor.drain
original_write=environment._write_metadata
original_cli=environment._cli
lost=False
failed=False
def save(name,value):
 path=case/name;path.write_text(json.dumps(value,sort_keys=True));path.chmod(0o600)
def drain(self,**options):
 global lost
 result=original_drain(self,**options)
 if not lost:
  lost=True
  assert result['complete'] and result['receipt']['cid']
  save('broker-completion.json',result)
  save('native-create.json',{'container_id':result['receipt']['cid'],'successful_docker_create':True})
  with (case/'calls.jsonl').open('a') as out:
   out.write(json.dumps({'role':'original-broker','operation':'create','locator':result['receipt']['cid']})+'\n')
  if mode=='reply_lost':raise ExecutionHostFailed('Controlled completed broker reply loss')
 return result
def write():
 global failed
 if mode=='cid_fsync_failed' and not failed and environment._metadata.get('create_operation',{}).get('phase')=='located':
  failed=True
  original_fsync=os.fsync
  def fsync(fd):raise OSError('Controlled full CID metadata fsync failure')
  os.fsync=fsync
  try:return original_write()
  finally:os.fsync=original_fsync
 return original_write()
def cli(args):
 assert args[0] not in {'create','start','kill','rm'}
 return original_cli(args)
CreateSupervisor.drain=drain
environment._write_metadata=write
environment._cli=cli
async def run():
 try:await environment.prepare()
 except (ExecutionHostFailed,OSError) as exc:
  save('original-exit.json',{'pid':os.getpid(),'controlled_failure':type(exc).__name__,'source':__import__('relf_agent').__file__,'metadata':json.loads((Path(config['root'])/'environment.json').read_text())})
 else:raise AssertionError('Original completed CREATE failure was not injected')
asyncio.run(run())
os._exit(0)
"""


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


def docker(config, *args):
    result = subprocess.run(
        [
            config["docker_executable"],
            "--config",
            str(Path(config["root"]) / "docker-client"),
            "--host",
            config["docker_host"],
            *args,
        ],
        env={"PATH": str(Path(config["docker_executable"]).parent) + ":/usr/bin:/bin"},
        capture_output=True,
        timeout=30,
        check=True,
    )
    return result.stdout


def cleanup(case, config, cold):
    root = Path(config["root"])
    native = case / "native-create.json"
    cid = json.loads(native.read_text())["container_id"] if native.exists() else None
    declaration = None
    metadata_path = root / "environment.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        declaration = metadata.get("create_operation", {}).get("declaration")
    if cold is not None and cold._lease is not None:
        os.close(cold._lease)
        cold._lease = None
    if cid is None and declaration is not None:
        write_json(case / "cleanup.json", {"cleanup_pending": "Original CREATE locator unknown"})
        raise AssertionError("Unknown original CREATE keeps its private ledger for control")
    if cid is not None:
        present = docker(
            config, "ps", "-a", "--no-trunc", "--filter", "id=" + cid, "--format", "{{.ID}}"
        )
        if present.strip():
            assert present.decode().split() == [cid]
            actual = json.loads(docker(config, "inspect", cid))[0]
            assert actual["Id"] == cid and actual["State"]["Pid"] == 0
            assert actual["State"]["Running"] is False
            assert actual["Config"]["Labels"]["ralf.coding.resource"] == config["resource_id"]
            assert (
                actual["Config"]["Labels"]["ralf.coding.generation"]
                == config["expected_generation"]
            )
            docker(config, "rm", cid)
        assert not docker(
            config, "ps", "-a", "--no-trunc", "--filter", "id=" + cid, "--format", "{{.ID}}"
        ).strip()
    control_absent = True
    if declaration is not None:
        registration = json.loads((root / ".create-operation" / "broker-register.json").read_text())
        assert process_ended(registration) and lock_released(declaration["operation_lock"])
        control = Path(declaration["control_directory"]["path"])
        private_directory(control, declaration["control_directory"])
        assert not (control / "control.sock").exists()
        shutil.rmtree(control)
        control_absent = not control.exists()
    shutil.rmtree(root)
    write_json(
        case / "cleanup.json",
        {
            "container_id": cid,
            "container_absent": True,
            "resource_directory_absent": not root.exists(),
            "control_directory_absent": control_absent,
            "control_socket_absent": True,
        },
    )


@pytest.mark.parametrize("mode", ["reply_lost", "cid_fsync_failed"])
def test_actual_supervised_create_cold_recovers_same_cid_without_start(mode):
    settings = {
        name: os.environ.get(name)
        for name in (
            "RALF_CODEX_CREATE_RECOVERY_DOCKER",
            "RALF_CODEX_CREATE_RECOVERY_HOST",
            "RALF_CODEX_SUPERVISED_CREATE_RECOVERY_PROOF_DIR",
        )
    }
    if not all(settings.values()):
        pytest.skip("Supply explicit Docker executable, Unix endpoint and private proof directory")
    base = Path(settings["RALF_CODEX_SUPERVISED_CREATE_RECOVERY_PROOF_DIR"])
    assert base.is_absolute() and not base.is_symlink() and base.is_dir()
    assert base.stat().st_uid == os.getuid() and base.stat().st_mode & 0o777 == 0o700
    case = base / (mode + "-" + uuid.uuid4().hex)
    case.mkdir(mode=0o700)
    root = case / "resource"
    root.mkdir(mode=0o700)
    generation = uuid.uuid4().hex
    config = {
        "root": str(root),
        "resource_id": "supervised-" + generation,
        "docker_executable": settings["RALF_CODEX_CREATE_RECOVERY_DOCKER"],
        "docker_host": settings["RALF_CODEX_CREATE_RECOVERY_HOST"],
        "command_timeout": 30,
        "retire_on_stop": True,
        "expected_generation": generation,
        "configuration_readonly": True,
        "create_recovery": True,
        "create_supervision": True,
    }
    write_json(case / "configuration.json", config)
    child_env = {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        "PYTHONUNBUFFERED": "1",
    }
    if "PYTHONPATH" in os.environ:
        child_env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    monitor, child, cold = ChildExitMonitor(), None, None
    try:
        with (
            (case / "original.stdout").open("wb") as stdout,
            (case / "original.stderr").open("wb") as stderr,
        ):
            child = subprocess.Popen(
                [sys.executable, "-c", CHILD, str(case), mode],
                env=child_env,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            monitor.register(child)
            assert monitor.exited(timeout=50)
            signal_unreaped_group(child, monitor)
            assert child.wait(timeout=5) == 0
        exited = json.loads((case / "original-exit.json").read_text())
        assert exited["pid"] == child.pid
        metadata = exited["metadata"]
        assert metadata["container_id"] is None
        assert metadata["create_operation"]["version"] == 2
        assert metadata["create_operation"]["phase"] == "submitted"
        assert metadata["identity"]["create_supervision_version"] == 1
        complete = json.loads((case / "broker-completion.json").read_text())
        assert complete["helpers_ended"] and complete["control_drained"]
        receipt = complete["receipt"]
        cid = receipt["cid"]
        assert receipt["cli_gate_accepted"] and receipt["cli_exec_started"]
        before = json.loads(docker(config, "inspect", cid))[0]
        assert before["Id"] == cid and before["Image"] == CodexCodingProfile().identity["image_id"]
        assert before["State"]["Status"] == "created" and before["State"]["Pid"] == 0
        assert before["State"]["Running"] is False
        assert before["State"]["StartedAt"] == "0001-01-01T00:00:00Z"
        cold = DockerCodingEnvironment(**config)
        original_cli = cold._cli

        def control_only(args):
            with (case / "calls.jsonl").open("a") as out:
                out.write(
                    json.dumps(
                        {
                            "role": "cold",
                            "operation": args[0],
                            "locator": args[-1] if args[0] in {"inspect", "kill", "rm"} else None,
                        }
                    )
                    + "\n"
                )
            assert args[0] not in {"create", "start"}
            if args[0] in {"inspect", "kill", "rm"}:
                assert args[-1] == cid
            return original_cli(args)

        cold._cli = control_only

        async def recover():
            stopped = await cold.stop_existing()
            assert stopped["container_id"] == cid and stopped["generation"] == generation
            assert stopped["fenced"] and stopped["retired"] and not stopped["container_present"]
            assert stopped["pid"] == 0 and not stopped["running"]
            await cold.aclose()
            return stopped

        stopped = asyncio.run(recover())
        calls = [json.loads(line) for line in (case / "calls.jsonl").read_text().splitlines()]
        assert sum(call["operation"] == "create" for call in calls) == 1
        assert sum(call["operation"] == "start" for call in calls) == 0
        assert sum(call["operation"] == "rm" for call in calls) == 1
        recovered = json.loads((root / "environment.json").read_text())
        assert (
            recovered["container_id"] == cid and recovered["create_operation"]["phase"] == "located"
        )
        assert not docker(
            config, "ps", "-a", "--no-trunc", "--filter", "id=" + cid, "--format", "{{.ID}}"
        ).strip()
        write_json(
            case / "proof.json",
            {
                "mode": mode,
                "original_worker_exited": child.returncode == 0,
                "worker_pid": child.pid,
                "worker_source": exited["source"],
                "parent_source": __import__("relf_agent").__file__,
                "original_container_id": cid,
                "original_create_count": 1,
                "native_start_count": 0,
                "broker_completion": complete,
                "actual_created_never_started": before["State"],
                "retired_original": stopped,
                "metadata": recovered,
                "calls": calls,
            },
        )
    finally:
        if child is not None and child.returncode is None:
            signal_unreaped_group(child, monitor)
            child.wait(timeout=10)
        monitor.close()
        cleanup(case, config, cold)
