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
if sys.argv[1:]==['--fixture-ready']: sys.exit(0)
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
 filters=[a[i+1] for i,v in enumerate(a[:-1]) if v=='--filter']
 ids=[v[3:] for v in filters if v.startswith('id=')]
 if ids:
  if (root/'fail-absence').exists(): sys.exit(1)
  print('\n'.join(k for k in s['containers'] if k in ids)); sys.exit(0)
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
elif a[0]=='rm':
 cid=a[-1]
 intent=json.loads((client.parent/'environment.json').read_text())['retirement']
 assert intent['phase']=='intent' and intent['stopped']['container_id']==cid and intent['stopped']['stopped'] is True and intent['stopped']['pid']==0
 if (root/'fail-rm').exists(): sys.exit(1)
 if cid not in s['containers']:sys.exit(1)
 assert s['containers'][cid]['State']['Running'] is False and s['containers'][cid]['State']['Pid']==0
 assert '--force' not in a and '-f' not in a
 s.setdefault('removed',[]).append(cid); del s['containers'][cid]; save()
 if (root/'rm-delay-after-delete').exists():
  (root/'rm.pid').write_text(str(os.getpid()));time.sleep(30)
 if (root/'rm-reply-lost').exists():sys.exit(1)
 print(cid)
elif a[0]=='start':
 cid=a[-1]
 if cid not in s['containers']: print('No such container',file=sys.stderr);sys.exit(1)
 s['containers'][cid]['State'].update({'Running':True,'Pid':123,'Status':'running','StartedAt':'2026-10-14T00:00:01Z'});save()
else: sys.exit(4)
"""


@pytest.fixture
def resource(tmp_path):
    root = tmp_path / "resource"
    root.mkdir(mode=0o700)
    cli = tmp_path / "docker"
    cli.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
    cli.chmod(0o700)
    # A newly created shebang executable can take longer to enter Python than
    # the intentional 0.25/0.3-second handler deadlines on macOS. Readiness
    # warms only the fake executable, before any product ownership or CLI call.
    before = cli.read_bytes()
    ready = subprocess.run(
        [str(cli), "--fixture-ready"],
        env={"PATH": str(cli.parent) + ":/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        start_new_session=True,
        timeout=5,
        check=True,
    )
    assert ready.stdout == ready.stderr == b""
    assert cli.read_bytes() == before
    assert set(tmp_path.iterdir()) == {root, cli}
    assert not tuple(root.iterdir())
    return root, cli


def test_fixture_readiness_does_not_prepare_or_mutate_docker_state(resource):
    root, cli = resource
    before = cli.read_bytes()
    completed = subprocess.run(
        [str(cli), "--fixture-ready"],
        env={"PATH": str(cli.parent) + ":/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        start_new_session=True,
        timeout=5,
        check=True,
    )
    assert completed.stdout == completed.stderr == b""
    assert cli.read_bytes() == before
    assert set(cli.parent.iterdir()) == {root, cli}
    assert not tuple(root.iterdir())


def test_cold_original_container_locator_must_match_before_any_docker_effect(resource):
    async def scenario():
        original = environment(resource, retire_on_stop=True, expected_generation="a" * 32)
        first = await original.prepare()
        await original.aclose()
        metadata_path = resource[0] / "environment.json"
        original_metadata = metadata_path.read_bytes()
        changed = json.loads(original_metadata)
        changed["container_id"] = "b" * 64
        changed["retirement"]["stopped"]["container_id"] = "b" * 64
        metadata_path.write_text(json.dumps(changed))
        before = load(resource)
        cold = environment(resource, retire_on_stop=True, expected_generation="a" * 32)
        try:
            with pytest.raises(DefinitionMismatch):
                await cold.stop_existing(expected_container_id=first["container_id"])
            assert load(resource) == before
            assert cold._lease is not None
        finally:
            metadata_path.write_bytes(original_metadata)
            await cold.stop_existing(expected_container_id=first["container_id"])
            await cold.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("locator", ["", "a" * 63, "A" * 64, True, 1])
def test_invalid_existing_stop_locator_is_rejected_before_any_io(resource, locator):
    cold = environment(resource)

    async def scenario():
        with pytest.raises(ValidationError):
            await cold.stop_existing(expected_container_id=locator)
        assert not (resource[0] / "lease.lock").exists()
        assert not (resource[1].parent / "docker.json").exists()
        await cold.aclose()

    asyncio.run(scenario())


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


def test_opt_in_fence_removes_only_original_id_and_cold_never_replaces_it(resource):
    async def run():
        kwargs = {"retire_on_stop": True, "expected_generation": "a" * 32}
        env = environment(resource, **kwargs)
        prepared = await env.prepare()
        cid = prepared["container_id"]
        old_argv = env.transport_argv()
        workspace = resource[0] / "workspace"
        (workspace / "solution.txt").write_text("original retained solution")
        assert prepared["generation"] == "a" * 32
        assert prepared["container_present"] and not prepared["retired"] and not prepared["fenced"]
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
        evidence = await env.stop()
        assert evidence["stopped"] and evidence["retired"] and evidence["fenced"]
        assert evidence["container_present"] is False
        assert evidence["pid"] == 0 and evidence["running"] is False
        assert evidence["container_id"] == cid and evidence["generation"] == "a" * 32
        assert evidence["started_at"] == "2026-10-14T00:00:01Z" and evidence["exit_code"] == 137
        stale = await asyncio.to_thread(
            subprocess.run, old_argv, env=env.transport_env, capture_output=True, timeout=3
        )
        assert stale.returncode != 0
        with pytest.raises(ValidationError):
            env.transport_argv()
        await env.aclose()
        cold = environment(resource, **kwargs)
        assert await cold.prepare() == evidence
        with pytest.raises(ValidationError):
            cold.transport_argv()
        assert (workspace / "solution.txt").read_text() == "original retained solution"
        assert (resource[0] / "state" / "config.toml").is_file()
        assert load(resource)["creates"] == 1 and load(resource)["removed"] == [cid]
        meta = json.loads((resource[0] / "environment.json").read_text())
        assert meta["retirement"]["phase"] == "fenced"
        assert meta["retirement"]["stopped"]["container_id"] == cid
        await cold.aclose()

    asyncio.run(run())


def test_legacy_stop_retention_identity_metadata_and_stale_argv_remain_v1(resource):
    async def run():
        env = environment(resource, retire_on_stop=False)
        original = await env.prepare()
        cid = original["container_id"]
        argv = env.transport_argv()
        stopped = await env.stop()
        assert stopped == original
        assert env.identity["version"] == "1"
        assert "retire_on_stop" not in env.identity and "expected_generation" not in env.identity
        assert not {"fenced", "retired", "container_present"}.intersection(stopped)
        meta = json.loads((resource[0] / "environment.json").read_text())
        assert set(meta) == {
            "identity",
            "generation",
            "container_id",
            "files",
            "lease_pin",
            "last_state",
        }
        assert cid in load(resource)["containers"] and "removed" not in load(resource)
        stale = await asyncio.to_thread(
            subprocess.run, argv, env=env.transport_env, capture_output=True, timeout=3
        )
        assert stale.returncode == 0
        await env.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"retire_on_stop": 1},
        {"retire_on_stop": "yes"},
        {"expected_generation": "a" * 32},
        {"retire_on_stop": True, "expected_generation": "A" * 32},
        {"retire_on_stop": True, "expected_generation": "a" * 31},
        {"retire_on_stop": True, "expected_generation": 1},
    ],
)
def test_retirement_constructor_rejects_ambiguous_or_unbounded_generation(resource, kwargs):
    with pytest.raises(ValidationError):
        environment(resource, **kwargs)


@pytest.mark.parametrize("lost_reply", [False, True])
def test_remove_receipt_loss_requires_successful_actual_absence_query(resource, lost_reply):
    async def run():
        env = environment(resource, retire_on_stop=True)
        cid = (await env.prepare())["container_id"]
        parent = resource[1].parent
        (parent / ("rm-reply-lost" if lost_reply else "fail-rm")).touch()
        if lost_reply:
            evidence = await env.stop()
            assert evidence["fenced"] and evidence["container_present"] is False
        else:
            with pytest.raises(ExecutionHostFailed):
                await env.stop()
            meta = json.loads((resource[0] / "environment.json").read_text())
            assert meta["retirement"]["phase"] == "intent"
            assert meta["retirement"]["stopped"]["container_id"] == cid
            with pytest.raises(ExecutionHostFailed):
                await environment(resource, retire_on_stop=True).prepare()
            with pytest.raises(ValidationError):
                env.transport_argv()
            (parent / "fail-rm").unlink()
            assert (await env.stop())["fenced"]
        await env.aclose()
        assert load(resource)["creates"] == 1 and load(resource)["removed"] == [cid]

    asyncio.run(run())


def test_lost_remove_reply_and_failed_query_keep_intent_and_lease_until_retry(resource):
    async def run():
        env = environment(resource, retire_on_stop=True)
        cid = (await env.prepare())["container_id"]
        parent = resource[1].parent
        (parent / "rm-reply-lost").touch()
        (parent / "fail-absence").touch()
        with pytest.raises(ExecutionHostFailed):
            await env.stop()
        assert cid not in load(resource)["containers"]
        meta = json.loads((resource[0] / "environment.json").read_text())
        assert meta["retirement"]["phase"] == "intent"
        with pytest.raises(ExecutionHostFailed):
            await env.aclose()
        with pytest.raises(ExecutionHostFailed):
            await environment(resource, retire_on_stop=True).prepare()
        (parent / "fail-absence").unlink()
        assert (await env.stop())["fenced"]
        await env.aclose()
        cold = environment(resource, retire_on_stop=True)
        assert (await cold.prepare())["container_id"] == cid
        assert load(resource)["creates"] == 1 and load(resource)["removed"] == [cid]
        await cold.aclose()

    asyncio.run(run())


def test_cancelled_remove_waits_actual_cli_and_reconciles_intent_before_lease_release(resource):
    async def run():
        env = environment(resource, retire_on_stop=True, command_timeout=0.3)
        cid = (await env.prepare())["container_id"]
        (resource[1].parent / "rm-delay-after-delete").touch()
        task = asyncio.create_task(env.stop())
        for _ in range(100):
            if (resource[1].parent / "rm.pid").exists():
                break
            await asyncio.sleep(0.01)
        pid = int((resource[1].parent / "rm.pid").read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert env.active_operations == 0
        with pytest.raises(ExecutionHostFailed):
            await environment(resource, retire_on_stop=True).prepare()
        assert (await env.inspect())["fenced"]
        await env.aclose()
        cold = environment(resource, retire_on_stop=True)
        assert (await cold.prepare())["container_id"] == cid
        assert load(resource)["creates"] == 1 and load(resource)["removed"] == [cid]
        await cold.aclose()

    asyncio.run(run())


def test_unprepared_absence_and_same_root_identity_switch_cannot_be_fenced(resource):
    async def run():
        env = environment(resource, retire_on_stop=True, expected_generation="a" * 32)
        with pytest.raises(ValidationError):
            await env.stop()
        await env.prepare()
        await env.aclose()
        prior_db = (resource[1].parent / "docker.json").read_bytes()
        for kwargs in [{}, {"retire_on_stop": True, "expected_generation": "b" * 32}]:
            contender = environment(resource, **kwargs)
            with pytest.raises(DefinitionMismatch):
                await contender.prepare()
            assert (resource[1].parent / "docker.json").read_bytes() == prior_db
            # A declaration mismatch owns no verified native ID. Simulate
            # process exit solely in the test to permit the next contender.
            os.close(contender._lease)
            contender._lease = None

    asyncio.run(run())


def test_cold_retirement_intent_after_process_exit_reconciles_only_original_id(resource):
    script = r"""
import asyncio, pathlib, sys
from ralf_agent.codex_environment import DockerCodingEnvironment
from ralf_agent.errors import ExecutionHostFailed
root=pathlib.Path(sys.argv[1]);cli=pathlib.Path(sys.argv[2]);parent=cli.parent
async def run():
 env=DockerCodingEnvironment(root,'test-retained',docker_executable=str(cli),docker_host='unix:///fixture/docker.sock',retire_on_stop=True,expected_generation='a'*32)
 await env.prepare();(parent/'rm-reply-lost').touch();(parent/'fail-absence').touch()
 try:await env.stop()
 except ExecutionHostFailed:return
 raise AssertionError('ambiguous removal was accepted without an absence query')
asyncio.run(run())
"""
    process = subprocess.run(
        [sys.executable, "-c", script, str(resource[0]), str(resource[1])],
        env={"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stderr
    original = json.loads((resource[0] / "environment.json").read_text())
    assert original["retirement"]["phase"] == "intent"
    (resource[1].parent / "fail-absence").unlink()

    async def run():
        cold = environment(resource, retire_on_stop=True, expected_generation="a" * 32)
        fenced = await cold.prepare()
        assert fenced["container_id"] == original["container_id"] and fenced["fenced"]
        assert fenced["generation"] == "a" * 32
        assert load(resource)["creates"] == 1 and load(resource)["removed"] == [
            original["container_id"]
        ]
        await cold.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "tamper", ["generation", "cid", "identity", "running", "pid", "stopped", "phase"]
)
def test_retirement_snapshot_tamper_rejects_before_docker_queries(resource, tamper):
    async def run():
        kwargs = {"retire_on_stop": True, "expected_generation": "a" * 32}
        env = environment(resource, **kwargs)
        await env.prepare()
        await env.aclose()
        path = resource[0] / "environment.json"
        meta = json.loads(path.read_text())
        if tamper == "generation":
            meta["generation"] = "b" * 32
        elif tamper == "cid":
            meta["retirement"]["stopped"]["container_id"] = "f" * 64
        elif tamper == "identity":
            meta["retirement"]["stopped"]["identity"]["resource_id"] = "foreign"
        elif tamper == "phase":
            meta["retirement"]["phase"] = "removed-probably"
        else:
            meta["retirement"]["stopped"][tamper] = {"running": True, "pid": 123, "stopped": False}[
                tamper
            ]
        path.write_text(json.dumps(meta))
        (resource[1].parent / "delay").touch()
        with pytest.raises(DefinitionMismatch):
            await environment(resource, **kwargs).prepare()
        assert not (resource[1].parent / "child.pid").exists()

    asyncio.run(run())


def test_absent_original_without_retirement_intent_is_not_fence_evidence(resource):
    async def run():
        env = environment(resource, retire_on_stop=True)
        await env.prepare()
        change(resource, lambda db: db["containers"].clear())
        with pytest.raises(ExecutionHostFailed):
            await env.stop()
        meta = json.loads((resource[0] / "environment.json").read_text())
        assert meta["retirement"] is None and load(resource)["creates"] == 1

    asyncio.run(run())


def test_stop_existing_absent_metadata_never_provisions_or_dispatches_docker(resource):
    async def run():
        env = environment(resource, retire_on_stop=True, expected_generation="a" * 32)
        (resource[1].parent / "delay").touch()
        assert await env.stop_existing() is None
        assert not (resource[1].parent / "child.pid").exists()
        assert set(p.name for p in resource[0].iterdir()) == {"lease.lock"}
        await env.aclose()
        assert not (resource[1].parent / "docker.json").exists()

    asyncio.run(run())


def test_stop_existing_retired_original_returns_fence_without_create(resource):
    async def run():
        kwargs = {"retire_on_stop": True, "expected_generation": "a" * 32}
        original = environment(resource, **kwargs)
        cid = (await original.prepare())["container_id"]
        fenced = await original.stop()
        await original.aclose()
        cold = environment(resource, **kwargs)
        assert await cold.stop_existing() == fenced
        await cold.aclose()
        assert load(resource)["creates"] == 1 and load(resource)["removed"] == [cid]

    asyncio.run(run())


def test_stop_existing_with_unresolved_create_intent_cannot_create_during_close(resource):
    async def run():
        kwargs = {"retire_on_stop": True, "expected_generation": "a" * 32}
        original = environment(resource, **kwargs)
        await original.prepare()
        await original.aclose()
        path = resource[0] / "environment.json"
        meta = json.loads(path.read_text())
        meta["container_id"] = None
        meta["last_state"] = None
        meta["retirement"] = None
        path.write_text(json.dumps(meta))
        (resource[1].parent / "delay").touch()
        cold = environment(resource, **kwargs)
        with pytest.raises(ValidationError):
            await cold.stop_existing()
        with pytest.raises(ExecutionHostFailed):
            await cold.aclose()
        with pytest.raises(ValidationError):
            await cold.prepare()
        assert not (resource[1].parent / "child.pid").exists()
        assert load(resource)["creates"] == 1

    asyncio.run(run())


def test_missing_metadata_cannot_forget_a_live_objects_original_locator_and_lease(resource):
    async def run():
        kwargs = {"retire_on_stop": True, "expected_generation": "a" * 32}
        env = environment(resource, **kwargs)
        cid = (await env.prepare())["container_id"]
        path = resource[0] / "environment.json"
        original = path.read_bytes()
        path.unlink()
        with pytest.raises(DefinitionMismatch):
            await env.stop_existing()
        assert cid in load(resource)["containers"]
        with pytest.raises(ExecutionHostFailed):
            await environment(resource, **kwargs).prepare()
        path.write_bytes(original)
        path.chmod(0o600)
        assert (await env.stop_existing())["fenced"]
        await env.aclose()

    asyncio.run(run())
