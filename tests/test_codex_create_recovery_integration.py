"""Gated real Docker create recovery; containers are never started or run models."""

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ralf_agent.codex_coding_profile import CodexCodingProfile
from ralf_agent.codex_environment import DockerCodingEnvironment

pytestmark = pytest.mark.skipif(
    os.environ.get("RALF_CODEX_CREATE_RECOVERY_INTEGRATION") != "1",
    reason="Set RALF_CODEX_CREATE_RECOVERY_INTEGRATION=1 with explicit Docker and proof directory",
)

CHILD = r"""
import asyncio,json,os,sys
from pathlib import Path
from ralf_agent.codex_environment import DockerCodingEnvironment
from ralf_agent.errors import ExecutionHostFailed
case=Path(sys.argv[1]); mode=sys.argv[2]
config=json.loads((case/'configuration.json').read_text())
environment=DockerCodingEnvironment(**config)
original_cli=environment._cli
original_fsync=os.fsync
def save(name,value):
 (case/name).write_text(json.dumps(value,sort_keys=True))
def logged(args):
 with (case/'calls.jsonl').open('a') as out:
  out.write(json.dumps({'pid':os.getpid(),'role':'original','operation':args[0],'locator':args[-1] if args[0] in {'inspect','kill','rm'} else None})+'\n')
 if args[0] in {'start','kill','rm'}:raise AssertionError('Original create fixture cannot start or clean up')
 result=original_cli(args)
 if args[0]=='create':
  cid=result[0].decode().strip()
  save('native-create.json',{'container_id':cid,'successful_docker_create':True})
  if mode=='reply_lost':raise ExecutionHostFailed('Controlled original CREATE reply loss')
 return result
def fsync(fd):
 if mode=='cid_fsync_failed' and environment._metadata is not None and environment._metadata.get('create_operation',{}).get('phase')=='located':
  raise OSError('Controlled CID persistence fsync failure')
 original_fsync(fd)
environment._cli=logged
os.fsync=fsync
async def run():
 try:await environment.prepare()
 except (ExecutionHostFailed,OSError) as exc:
  save('original-exit.json',{'pid':os.getpid(),'mode':mode,'controlled_failure':type(exc).__name__,'source':__import__('ralf_agent').__file__,'metadata':json.loads((Path(config['root'])/'environment.json').read_text())})
 else:raise AssertionError('Required create failure was not injected')
asyncio.run(run())
# Deliberate process crash: release the actual OS lease without product cleanup.
os._exit(0)
"""


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


def docker(config, *args):
    completed = subprocess.run(
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
    return completed.stdout


def exact_cleanup(case, config, cold):
    """Fixture cleanup targets only the CID returned by this original CREATE."""
    observed = case / "native-create.json"
    cid = json.loads(observed.read_text())["container_id"] if observed.exists() else None
    if cold is not None and cold._lease is not None:
        os.close(cold._lease)
        cold._lease = None
    saved = Path(config["root"]) / "environment.json"
    if cid is None and saved.exists():
        operation = json.loads(saved.read_text()).get("create_operation", {})
        if operation.get("phase") == "submitted":
            write_json(
                case / "cleanup.json",
                {
                    "container_id": None,
                    "container_absent": None,
                    "resource_directory_absent": False,
                    "cleanup_pending": "Original create locator remains unknown",
                },
            )
            raise AssertionError("Unknown original create retains its private root for control")
    if cid is not None:
        present = docker(
            config, "ps", "-a", "--no-trunc", "--filter", "id=" + cid, "--format", "{{.ID}}"
        )
        if present.strip():
            assert present.decode().split() == [cid]
            actual = json.loads(docker(config, "inspect", cid))[0]
            assert actual["Id"] == cid
            assert actual["State"]["Running"] is False and actual["State"]["Pid"] == 0
            assert actual["Config"]["Labels"]["ralf.coding.resource"] == config["resource_id"]
            assert (
                actual["Config"]["Labels"]["ralf.coding.generation"]
                == config["expected_generation"]
            )
            assert any(
                mount["Source"] == str(Path(config["root"]) / "workspace")
                for mount in actual["Mounts"]
            )
            docker(config, "rm", cid)
        assert not docker(
            config, "ps", "-a", "--no-trunc", "--filter", "id=" + cid, "--format", "{{.ID}}"
        ).strip()
    shutil.rmtree(config["root"])
    write_json(
        case / "cleanup.json",
        {
            "container_id": cid,
            "container_absent": True,
            "resource_directory_absent": not Path(config["root"]).exists(),
        },
    )


@pytest.mark.parametrize("mode", ["reply_lost", "cid_fsync_failed"])
def test_actual_original_create_survives_worker_exit_and_cold_control_retires_same_cid(mode):
    settings = {
        name: os.environ.get(name)
        for name in (
            "RALF_CODEX_CREATE_RECOVERY_DOCKER",
            "RALF_CODEX_CREATE_RECOVERY_HOST",
            "RALF_CODEX_CREATE_RECOVERY_PROOF_DIR",
        )
    }
    if not all(settings.values()):
        pytest.skip(
            "Real create recovery requires explicit Docker executable, host, and proof directory"
        )
    base = Path(settings["RALF_CODEX_CREATE_RECOVERY_PROOF_DIR"])
    assert base.is_absolute() and base.is_dir() and not base.is_symlink()
    assert base.stat().st_uid == os.getuid() and base.stat().st_mode & 0o777 == 0o700
    case = base / (mode + "-" + uuid.uuid4().hex)
    case.mkdir(mode=0o700)
    root = case / "resource"
    root.mkdir(mode=0o700)
    generation = uuid.uuid4().hex
    config = {
        "root": str(root),
        "resource_id": "create-proof-" + generation,
        "docker_executable": settings["RALF_CODEX_CREATE_RECOVERY_DOCKER"],
        "docker_host": settings["RALF_CODEX_CREATE_RECOVERY_HOST"],
        "command_timeout": 30,
        "retire_on_stop": True,
        "expected_generation": generation,
        "configuration_readonly": True,
        "create_recovery": True,
    }
    write_json(case / "configuration.json", config)
    child_env = {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        "PYTHONUNBUFFERED": "1",
    }
    if "PYTHONPATH" in os.environ:
        child_env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    child, cold = None, None
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
            assert child.wait(timeout=50) == 0
        exited = json.loads((case / "original-exit.json").read_text())
        assert exited["pid"] == child.pid
        assert exited["metadata"]["container_id"] is None
        assert exited["metadata"]["create_operation"]["phase"] == "submitted"
        cid = json.loads((case / "native-create.json").read_text())["container_id"]
        before = json.loads(docker(config, "inspect", cid))[0]
        assert before["Id"] == cid and before["Image"] == CodexCodingProfile().identity["image_id"]
        assert before["State"]["Status"] == "created" and before["State"]["Running"] is False
        assert (
            before["State"]["Pid"] == 0 and before["State"]["StartedAt"] == "0001-01-01T00:00:00Z"
        )
        cold = DockerCodingEnvironment(**config)
        original_cli = cold._cli

        def control_only(args):
            with (case / "calls.jsonl").open("a") as out:
                out.write(
                    json.dumps(
                        {
                            "pid": os.getpid(),
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
            result = await cold.stop_existing()
            assert result["container_id"] == cid and result["generation"] == generation
            assert result["fenced"] and result["retired"] and not result["container_present"]
            assert result["pid"] == 0 and not result["running"]
            await cold.aclose()
            return result

        stopped = asyncio.run(recover())
        calls = [json.loads(line) for line in (case / "calls.jsonl").read_text().splitlines()]
        assert sum(call["operation"] == "create" for call in calls) == 1
        assert sum(call["operation"] == "start" for call in calls) == 0
        assert sum(call["operation"] == "rm" for call in calls) == 1
        assert not docker(
            config, "ps", "-a", "--no-trunc", "--filter", "id=" + cid, "--format", "{{.ID}}"
        ).strip()
        write_json(
            case / "proof.json",
            {
                "mode": mode,
                "actual_original_worker_exited": child.returncode == 0,
                "worker_pid": child.pid,
                "worker_source": exited["source"],
                "parent_source": __import__("ralf_agent").__file__,
                "original_container_id": cid,
                "actual_created_never_started": before["State"],
                "original_create_count": 1,
                "native_start_count": 0,
                "retired_original": stopped,
                "metadata": json.loads((root / "environment.json").read_text()),
                "calls": calls,
            },
        )
    finally:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=10)
        exact_cleanup(case, config, cold)
