"""A real local CLI fixture exercises retained resource safety without a daemon."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ralf_agent.errors import DefinitionMismatch, ExecutionHostFailed, ValidationError

# Removing physical pins, exact inspect checks or retained ID recovery must fail these tests.
FAKE_DOCKER = r"""
import json, os, pathlib, sys, time
a=sys.argv[1:]; assert a[0]=='--config'; client=pathlib.Path(a[1]); assert json.loads((client/'config.json').read_text())=={}; a=a[2:]
assert a[:2]==['--host','unix:///fixture/docker.sock']; a=a[2:]
root=pathlib.Path(__file__).parent; db=root/'docker.json'
s=json.loads(db.read_text()) if db.exists() else {'containers':{},'creates':0}
if (root/'delay').exists():
 (root/'child.pid').write_text(str(os.getpid())); time.sleep(30)
if (root/'flood').exists():
 print('x'*3000000); sys.exit(0)
def save(): db.write_text(json.dumps(s))
if a[0]=='ps':
 print('\n'.join(s['containers'])); sys.exit(0)
if a[0]=='create':
 if '--pull=never' not in a: (root/'registry-pull-attempt').touch(); sys.exit(1)
 s['creates']+=1; cid=('%064x'%s['creates']); cfg={}; host={}; mounts=[]; labels={}
 i=1
 while i<len(a):
  v=a[i]
  if v.startswith('sha256:'): image=v; cmd=a[i+1:]; break
  key,sep,value=v.partition('=')
  if not sep and key in ['--name','--label','--env','--mount','--tmpfs','--entrypoint','--workdir','--user','--security-opt','--network','--pids-limit','--memory','--cpus']:
   i+=1; value=a[i]
  if key=='--name': name=value
  elif key=='--label': k,val=value.split('=',1); labels[k]=val
  elif key=='--env': env=value
  elif key=='--mount':
   m=dict(p.split('=',1) for p in value.split(',') if '=' in p)
   mounts.append({'Type':m['type'],'Source':m['source'],'Destination':m['target'],'RW':'readonly' not in value,'Propagation':'rprivate'})
  elif key=='--tmpfs': target,opt=value.split(':',1); host['Tmpfs']={target:opt}
  elif key=='--security-opt': host.setdefault('SecurityOpt',[]).append(value)
  i+=1
 sec=host['SecurityOpt']; host['SecurityOpt']=[('seccomp='+json.dumps(json.loads(pathlib.Path(v[8:]).read_text()),separators=(',',':'))) if v.startswith('seccomp=') else v for v in sec]
 host.update({'ReadonlyRootfs':True,'Privileged':False,'CapDrop':['ALL'],'CapAdd':None,'NetworkMode':'bridge','PidsLimit':64,'Memory':536870912,'NanoCpus':1000000000,'AutoRemove':False,'RestartPolicy':{'Name':'no','MaximumRetryCount':0},'PidMode':'','IpcMode':'private','CgroupnsMode':'private','UTSMode':'','UsernsMode':'','Binds':None,'VolumesFrom':None,'PortBindings':{},'Devices':[],'DeviceRequests':None,'PublishAllPorts':False,'ExtraHosts':None,'Links':None})
 cfg={'User':'10001:10001','WorkingDir':'/workspace','Entrypoint':['/opt/codex/bin/codex'],'Cmd':cmd,'Image':image,'Env':[env,'PATH=/opt/codex/bin:/opt/codex/codex-path:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','HOME=/home/ralf'],'Labels':labels,'OpenStdin':True,'Tty':False,'Volumes':None}
 s['containers'][cid]={'Id':cid,'Name':'/'+name,'Image':image,'Config':cfg,'HostConfig':host,'Mounts':mounts,'State':{'Status':'created','Running':False,'Pid':0,'StartedAt':'0001-01-01T00:00:00Z','FinishedAt':'0001-01-01T00:00:00Z','ExitCode':0,'Paused':False,'Restarting':False,'Dead':False},'RestartCount':0}; save(); print(cid)
elif a[0]=='inspect':
 target=a[-1]; found=[v for k,v in s['containers'].items() if k==target or v['Name']=='/'+target]
 if not found: print('missing',file=sys.stderr); sys.exit(1)
 print(json.dumps(found))
elif a[0]=='kill':
 if (root/'fail-kill').exists(): sys.exit(1)
 if (root/'delay-kill').exists():
  (root/'kill.pid').write_text(str(os.getpid())); time.sleep(30)
 c=s['containers'][a[-1]]; c['State'].update({'Running':False,'Pid':0,'Status':'exited','ExitCode':137,'FinishedAt':'2026-10-14T00:00:02Z'}); save(); print(a[-1])
else: sys.exit(4)
"""


@pytest.fixture
def resource(tmp_path):
    root = tmp_path / "resource"
    root.mkdir(mode=0o700)
    cli = tmp_path / "docker"
    cli.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
    cli.chmod(0o700)
    return root, cli


def environment(resource, **kwargs):
    from ralf_agent.codex_environment import DockerCodingEnvironment

    root, cli = resource
    return DockerCodingEnvironment(
        root,
        "test-retained",
        docker_executable=str(cli),
        docker_host="unix:///fixture/docker.sock",
        **kwargs,
    )


def load(resource):
    return json.loads((resource[1].parent / "docker.json").read_text())


def change(resource, fn):
    value = load(resource)
    fn(value)
    (resource[1].parent / "docker.json").write_text(json.dumps(value))


def test_prepare_and_cold_reattach_retains_exact_id_and_workspace(resource):
    async def run():
        env = environment(resource)
        with pytest.raises(ValidationError):
            env.transport_argv()
        first = await env.prepare()
        cid = first["container_id"]
        assert first["running"] is False and first["pid"] == 0
        assert first["execution_admitted"] is False
        assert env.transport_argv() == (
            str(resource[1]),
            "--config",
            str(resource[0] / "docker-client"),
            "--host",
            "unix:///fixture/docker.sock",
            "start",
            "--attach",
            "--interactive",
            cid,
        )
        (resource[0] / "workspace" / "solution.txt").write_text("retained")
        await env.aclose()
        cold = environment(resource)
        assert (await cold.prepare())["container_id"] == cid
        assert (resource[0] / "workspace" / "solution.txt").read_text() == "retained"
        assert load(resource)["creates"] == 1
        assert (resource[0] / "state" / "config.toml").is_file()
        assert all(
            (resource[0] / "workspace" / p).is_dir() for p in [".git", ".agents", ".codex", ".tmp"]
        )
        assert env.identity["execution_admitted"] is False
        assert json.loads((resource[0] / "docker-client" / "config.json").read_text()) == {}
        assert not (resource[1].parent / "registry-pull-attempt").exists()
        altered = env.identity
        altered["resource_id"] = "tampered"
        assert env.identity["resource_id"] == "test-retained"

    asyncio.run(run())


@pytest.mark.parametrize(
    "drift",
    [
        "image",
        "cmd",
        "user",
        "cap",
        "readonly",
        "network",
        "memory",
        "seccomp",
        "mount",
        "extra_mount",
        "home",
        "label",
        "privileged",
        "pid_mode",
    ],
)
def test_existing_container_drift_rejects_without_replacement(resource, drift):
    async def run():
        env = environment(resource)
        await env.prepare()
        await env.aclose()

        def mutate(db):
            c = next(iter(db["containers"].values()))
            if drift == "image":
                c["Image"] = "sha256:" + "f" * 64
            elif drift == "cmd":
                c["Config"]["Cmd"] = ["app-server", "--dangerously-bypass-approvals-and-sandbox"]
            elif drift == "user":
                c["Config"]["User"] = "0"
            elif drift == "cap":
                c["HostConfig"]["CapAdd"] = ["SYS_ADMIN"]
            elif drift == "readonly":
                c["HostConfig"]["ReadonlyRootfs"] = False
            elif drift == "network":
                c["HostConfig"]["NetworkMode"] = "host"
            elif drift == "memory":
                c["HostConfig"]["Memory"] = 0
            elif drift == "seccomp":
                c["HostConfig"]["SecurityOpt"] = ["seccomp=unconfined"]
            elif drift == "mount":
                c["Mounts"][0]["Source"] = "/host/repo"
            elif drift == "extra_mount":
                c["Mounts"].append(
                    {
                        "Type": "bind",
                        "Source": "/var/run/docker.sock",
                        "Destination": "/docker.sock",
                        "RW": True,
                        "Propagation": "rprivate",
                    }
                )
            elif drift == "home":
                c["Config"]["Env"].append("CODEX_HOME=/host")
            elif drift == "label":
                c["Config"]["Labels"]["ralf.coding.resource"] = "another"
            elif drift == "privileged":
                c["HostConfig"]["Privileged"] = True
            elif drift == "pid_mode":
                c["HostConfig"]["PidMode"] = "host"

        change(resource, mutate)
        with pytest.raises(DefinitionMismatch):
            await environment(resource).prepare()
        assert load(resource)["creates"] == 1

    asyncio.run(run())


def test_deleted_retained_container_is_not_silently_replaced(resource):
    async def run():
        env = environment(resource)
        await env.prepare()
        await env.aclose()
        change(resource, lambda db: db["containers"].clear())
        with pytest.raises((DefinitionMismatch, ExecutionHostFailed)):
            await environment(resource).prepare()
        assert load(resource)["creates"] == 1

    asyncio.run(run())


def test_stop_confirms_actual_whole_container_and_retains_epoch(resource):
    async def run():
        env = environment(resource)
        cid = (await env.prepare())["container_id"]
        change(
            resource,
            lambda db: db["containers"][cid]["State"].update(
                {
                    "Running": True,
                    "Pid": 123,
                    "Status": "running",
                    "StartedAt": "2026-10-14T00:00:01Z",
                }
            ),
        )
        assert (await env.inspect())["running"] is True
        stopped = await env.stop()
        assert stopped["container_id"] == cid and stopped["pid"] == 0
        assert stopped["running"] is False and stopped["exit_code"] == 137
        assert stopped["started_at"] == "2026-10-14T00:00:01Z"
        assert cid in load(resource)["containers"]

    asyncio.run(run())


def test_physical_workspace_alias_or_config_drift_fails_closed(resource):
    async def run():
        env = environment(resource)
        await env.prepare()
        workspace = resource[0] / "workspace"
        workspace.rename(resource[0] / "old-workspace")
        workspace.symlink_to(resource[0] / "old-workspace")
        with pytest.raises(DefinitionMismatch):
            await env.inspect()
        with pytest.raises(ExecutionHostFailed):
            await environment(resource).prepare()
        workspace.unlink()
        (resource[0] / "old-workspace").rename(workspace)
        await env.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("resource_id", "../escape"),
        ("resource_id", "x" * 49),
        ("docker_host", "tcp://daemon:2375"),
        ("docker_executable", "docker"),
    ],
)
def test_constructor_rejects_ambient_or_unbounded_inputs(resource, field, value):
    from ralf_agent.codex_environment import DockerCodingEnvironment

    args = {
        "resource_id": "test-retained",
        "docker_executable": str(resource[1]),
        "docker_host": "unix:///fixture/docker.sock",
    }
    args[field] = value
    with pytest.raises(ValidationError):
        DockerCodingEnvironment(resource[0], **args)


def test_private_root_and_identity_are_pinned_before_side_effects(resource):
    resource[0].chmod(0o755)
    with pytest.raises(ValidationError):
        environment(resource)


def test_bounded_output_and_cancelled_cli_reap_real_process(resource):
    async def run():
        env = environment(resource, command_timeout=0.25)
        (resource[1].parent / "flood").touch()
        with pytest.raises(ExecutionHostFailed):
            await env.prepare()
        (resource[1].parent / "flood").unlink()
        (resource[1].parent / "delay").touch()
        task = asyncio.create_task(env.prepare())
        for _ in range(50):
            if (resource[1].parent / "child.pid").exists():
                break
            await asyncio.sleep(0.01)
        pid = int((resource[1].parent / "child.pid").read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)

    asyncio.run(run())


def test_live_resource_lease_excludes_other_instance_until_stopped_close(resource):
    async def run():
        owner = environment(resource)
        cid = (await owner.prepare())["container_id"]
        other = environment(resource)
        with pytest.raises(ExecutionHostFailed):
            await other.prepare()
        await owner.aclose()
        assert (await other.prepare())["container_id"] == cid
        await other.aclose()

    asyncio.run(run())


def test_remembered_running_state_and_closed_environment_cannot_start(resource):
    async def run():
        env = environment(resource)
        cid = (await env.prepare())["container_id"]
        change(
            resource,
            lambda db: db["containers"][cid]["State"].update(
                {
                    "Running": True,
                    "Pid": 123,
                    "Status": "running",
                    "StartedAt": "2026-10-14T00:00:01Z",
                }
            ),
        )
        await env.inspect()
        with pytest.raises(ValidationError):
            env.transport_argv()
        stopped = await env.stop()
        assert stopped["stopped"] is True
        assert stopped["resource_id"] == "test-retained"
        assert stopped["generation"] and stopped["identity"] == env.identity
        await env.aclose()
        with pytest.raises(ValidationError):
            env.transport_argv()

    asyncio.run(run())


def test_failed_close_keeps_lease_until_confirmed_same_id_stop(resource):
    async def run():
        env = environment(resource)
        cid = (await env.prepare())["container_id"]
        change(
            resource,
            lambda db: db["containers"][cid]["State"].update(
                {
                    "Running": True,
                    "Pid": 123,
                    "Status": "running",
                    "StartedAt": "2026-10-14T00:00:01Z",
                }
            ),
        )
        (resource[1].parent / "fail-kill").touch()
        with pytest.raises(ExecutionHostFailed):
            await env.aclose()
        with pytest.raises(ExecutionHostFailed):
            await environment(resource).prepare()
        with pytest.raises(ValidationError):
            env.transport_argv()
        (resource[1].parent / "fail-kill").unlink()
        await env.aclose()
        other = environment(resource)
        assert (await other.prepare())["container_id"] == cid
        await other.aclose()

    asyncio.run(run())


def test_config_and_lease_file_drift_reject_cold_recovery(resource):
    async def run():
        env = environment(resource)
        await env.prepare()
        await env.aclose()
        config = resource[0] / "state" / "config.toml"
        config.chmod(0o600)
        config.write_text("approval_policy = 'on-request'\n")
        with pytest.raises(DefinitionMismatch):
            await environment(resource).prepare()
        assert load(resource)["creates"] == 1

    asyncio.run(run())


@pytest.mark.parametrize("started", [False, True])
def test_create_crash_intent_recovers_only_never_started_original_container(resource, started):
    async def run():
        env = environment(resource)
        cid = (await env.prepare())["container_id"]
        await env.aclose()
        path = resource[0] / "environment.json"
        meta = json.loads(path.read_text())
        meta["container_id"] = None
        meta["last_state"] = None
        path.write_text(json.dumps(meta))
        if started:
            change(
                resource,
                lambda db: db["containers"][cid]["State"].update(
                    {"Status": "exited", "StartedAt": "2026-10-14T00:00:01Z"}
                ),
            )
        cold = environment(resource)
        if started:
            with pytest.raises(DefinitionMismatch):
                await cold.prepare()
            with pytest.raises(DefinitionMismatch):
                await cold.prepare()
        else:
            assert (await cold.prepare())["container_id"] == cid
            await cold.aclose()
        assert load(resource)["creates"] == 1

    asyncio.run(run())


def test_cancelled_stop_reaps_cli_and_keeps_resource_owned_for_retry(resource):
    async def run():
        env = environment(resource, command_timeout=0.25)
        cid = (await env.prepare())["container_id"]
        change(
            resource,
            lambda db: db["containers"][cid]["State"].update(
                {
                    "Running": True,
                    "Pid": 123,
                    "Status": "running",
                    "StartedAt": "2026-10-14T00:00:01Z",
                }
            ),
        )
        (resource[1].parent / "delay-kill").touch()
        task = asyncio.create_task(env.stop())
        for _ in range(100):
            if (resource[1].parent / "kill.pid").exists():
                break
            await asyncio.sleep(0.01)
        pid = int((resource[1].parent / "kill.pid").read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        with pytest.raises(ExecutionHostFailed):
            await environment(resource).prepare()
        (resource[1].parent / "delay-kill").unlink()
        assert (await env.stop())["stopped"] is True
        await env.aclose()

    asyncio.run(run())


def test_host_docker_client_config_drift_is_rejected_before_any_cli(resource):
    async def run():
        env = environment(resource)
        await env.prepare()
        config = resource[0] / "docker-client" / "config.json"
        config.write_text('{"credsStore":"external-host-helper"}')
        with pytest.raises(DefinitionMismatch):
            await env.inspect()
        with pytest.raises(DefinitionMismatch):
            env.transport_argv()
        config.write_text("{}\n")
        await env.aclose()

    asyncio.run(run())


def test_cancel_all_loop_tasks_cannot_release_lease_while_real_cli_is_alive(resource):
    """Cancelling the to_thread Task must not make its running thread disappear."""
    script = r"""
import asyncio, os, pathlib, sys
from ralf_agent.codex_environment import DockerCodingEnvironment
root=pathlib.Path(sys.argv[1]);cli=pathlib.Path(sys.argv[2]);parent=cli.parent
def resource(): return DockerCodingEnvironment(root,'test-retained',docker_executable=str(cli),docker_host='unix:///fixture/docker.sock',command_timeout=0.8)
loop=asyncio.new_event_loop();asyncio.set_event_loop(loop);owner=resource()
try:
 (parent/'delay').touch();original=loop.create_task(owner.prepare())
 async def started():
  for _ in range(100):
   if (parent/'child.pid').exists():return
   await asyncio.sleep(.01)
  raise AssertionError('real CLI did not begin')
 loop.run_until_complete(started());pid=int((parent/'child.pid').read_text())
 pending=list(asyncio.all_tasks(loop))
 for task in pending:task.cancel()
 loop.run_until_complete(asyncio.gather(*pending,return_exceptions=True))
 (parent/'delay').unlink()
 loop.run_until_complete(owner.aclose())
 replacement=resource();loop.run_until_complete(replacement.prepare())
 try:os.kill(pid,0)
 except ProcessLookupError:pass
 else:raise AssertionError('new lease accepted while original real CLI remained alive')
 loop.run_until_complete(replacement.aclose())
 print('actual CLI reaped before lease transfer')
finally:
 loop.run_until_complete(loop.shutdown_asyncgens())
 loop.run_until_complete(loop.shutdown_default_executor())
 loop.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(resource[0]), str(resource[1])],
        env={"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "actual CLI reaped before lease transfer" in result.stdout
