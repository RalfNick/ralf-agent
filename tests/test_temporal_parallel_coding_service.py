"""Concurrent original Agent business, join barriers and independent leaf closure."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from relf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Scope, ValueRef
from relf_agent.errors import CloseIncomplete
from relf_agent.temporal import TemporalEngine, replay_temporal_history
from tests import temporal_parallel_coding_worker_fixture as fixture
from tests.test_codex_runner import native_fixture
from tests.test_temporal_coding_service import wait_until

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="Requires actual Temporal and PostgreSQL",
)


def parallel_peer(tmp_path):
    """Serialize fixture Docker state only; never hold that lock during a native Turn."""
    cli = native_fixture(tmp_path)
    source = cli.read_text()
    source = source.replace(
        "s=json.loads(db.read_text())",
        "import fcntl\nlease=(root/'peer-state.lock').open('a')\n"
        "fcntl.flock(lease,fcntl.LOCK_EX)\ns=json.loads(db.read_text())",
        1,
    )
    source = source.replace(
        "def save(): db.write_text(json.dumps(s))",
        "def save():\n db.write_text(json.dumps(s))\n "
        "event={'pid':os.getpid(),'method':a[0],'creates':s['creates'],'ids':list(s['containers'])}\n "
        "with (root/'peer-writes.jsonl').open('a') as out:out.write(json.dumps(event)+'\\n')",
        1,
    )
    source = source.replace(
        " print('\\n'.join(s['containers'])); sys.exit(0)",
        " selected=[]\n for cid,c in s['containers'].items():\n"
        "  matches=True\n  for item in filters:\n"
        "   if item.startswith('name='):\n"
        "    import re\n    matches=matches and re.search(item[5:],c['Name']) is not None\n"
        "   elif item.startswith('label='):\n"
        "    key,sep,value=item[6:].partition('=')\n"
        "    matches=matches and key in c['Config']['Labels'] and (not sep or c['Config']['Labels'][key]==value)\n"
        "   else:raise RuntimeError('unsupported test namespace filter')\n"
        "  if matches:selected.append(cid)\n print('\\n'.join(selected)); sys.exit(0)",
        1,
    )
    source = source.replace(" control=", " fcntl.flock(lease,fcntl.LOCK_UN)\n control=", 1)
    source = source.replace(
        "if (root/'fail-kill').exists(): sys.exit(1)",
        "if (root/'fail-kill').exists() or ((root/'fail-kill-cid').exists() and "
        "(root/'fail-kill-cid').read_text()==a[-1]): sys.exit(1)",
        1,
    )
    source = source.replace(
        "elif mode!='hang_turn':\n     terminal=dict(turn)",
        "elif mode!='hang_turn':\n"
        "     (root/('turn-ready-'+cid)).touch()\n"
        "     deadline=time.monotonic()+25\n"
        "     while not (root/'release-turns').exists():\n"
        "      if time.monotonic()>deadline:raise RuntimeError('test gate never released')\n"
        "      time.sleep(.01)\n"
        "     terminal=dict(turn)",
        1,
    )
    assert source != cli.read_text()
    cli.write_text(source)
    return cli


@pytest.mark.parametrize(
    "mode",
    ["join", "separate_runners", "shared_runner", "approval_restart", "cancel", "close_one_failed"],
)
def test_actual_parallel_original_children_and_independent_stopping(tmp_path, monkeypatch, mode):
    async def run():
        import psycopg
        from psycopg import sql
        from temporalio.client import Client

        schema = "coding_parallel_108_" + uuid.uuid4().hex
        conn = await psycopg.AsyncConnection.connect(
            os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True
        )
        await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        for root in (tmp_path / "native", tmp_path / "native-second"):
            root.mkdir(mode=0o700)
        cli = parallel_peer(tmp_path)
        sock = socket.socket(socket.AF_UNIX)
        sock_path = Path("/private/tmp") / ("ralf-parallel-" + uuid.uuid4().hex[:12] + ".sock")
        sock.bind(str(sock_path))
        cli.write_text(
            cli.read_text().replace("unix:///fixture/docker.sock", "unix://" + str(sock_path))
        )
        queue = "coding_parallel_108_" + uuid.uuid4().hex
        for key, value in {
            "RALF_CODING_ROOT": str(tmp_path / "native"),
            "RALF_CODING_DOCKER": str(cli),
            "RALF_CODING_HOST": "unix://" + str(sock_path),
            "RALF_CODING_SCHEMA": schema,
            "RALF_CODING_QUEUE": queue,
            "RALF_CODING_TWO_RUNNERS": "0" if mode == "shared_runner" else "1",
        }.items():
            monkeypatch.setenv(key, value)
        built, runners, journal = await fixture.runtime()
        processes = []

        async def start():
            log = tmp_path / f"worker-{len(processes)}.log"
            env = {k: v for k, v in os.environ.items() if k.startswith("RALF_") or k == "PATH"}
            with log.open("w") as output:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [sys.executable, "-u", "-m", "tests.temporal_parallel_coding_worker_fixture"],
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            await wait_until(
                lambda: asyncio.to_thread(log.read_text),
                lambda value: "PARALLEL_CODING_WORKER_READY" in value or process.poll() is not None,
            )
            assert process.poll() is None, log.read_text()
            return process

        try:
            worker = await start()
            client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
            scope = Scope("coding-service", queue)
            engine = TemporalEngine(
                client,
                task_queue=queue,
                release=built.orchestration_release,
                scope=scope,
                activity_timeout=40,
                drive_timeout=40,
            )
            graph = GraphWorkflowSpec(
                "parallel-coding",
                (
                    GraphNode("first", agent=AgentSpec("a", "Perform Coding", tools=("coding",))),
                    GraphNode(
                        "second",
                        agent=AgentSpec(
                            "b",
                            "Perform Coding",
                            tools=("coding" if mode == "shared_runner" else "coding_second",),
                        ),
                    ),
                    GraphNode(
                        "join",
                        agent=AgentSpec("join", "Join both results", tools=("coding",)),
                        depends_on=("first", "second"),
                        input=ValueRef("first"),
                    ),
                ),
                max_concurrency=2,
            )
            if mode == "separate_runners":
                from relf_agent import AgentBindingDescriptor, BindingSelection, BoundDefinition

                graph = BoundDefinition(
                    graph,
                    {
                        "graph/nodes/first": AgentBindingDescriptor(
                            runner=BindingSelection.ref("original", "1")
                        ),
                        "graph/nodes/second": AgentBindingDescriptor(
                            runner=BindingSelection.ref("second", "1")
                        ),
                        "graph/nodes/join": AgentBindingDescriptor(
                            runner=BindingSelection.ref("original", "1")
                        ),
                    },
                )
            handle = await engine.submit(graph, "fixed task", command_id="submit", budget=40)
            root_sdk = client.get_workflow_handle(handle.run_id)
            waiting = await wait_until(
                lambda: engine.status(handle.run_id),
                lambda value: len(value.pending) == (1 if mode == "shared_runner" else 2),
            )
            originals = {
                item["run_id"]: (await client.get_workflow_handle(item["run_id"]).describe()).run_id
                for item in waiting.pending
            }
            if mode == "approval_restart":
                worker.kill()
                await asyncio.to_thread(worker.wait, timeout=5)
                await start()
                assert (
                    await engine.submit(graph, "fixed task", command_id="submit", budget=40)
                    == handle
                )
            for index, pending in enumerate(waiting.pending):
                await engine.approve(
                    pending["run_id"],
                    action_id=pending["action_id"],
                    target_digest=pending["digest"],
                    approved=True,
                    command_id=f"approve-{index}",
                )
            await wait_until(
                lambda: asyncio.to_thread(lambda: list(tmp_path.glob("turn-ready-*"))),
                lambda value: len(value) == (1 if mode == "shared_runner" else 2),
            )
            state = json.loads((tmp_path / "docker.json").read_text())
            assert len(state["containers"]) == (1 if mode == "shared_runner" else 2)
            assert all(row["State"]["Running"] for row in state["containers"].values())
            counter = tmp_path / "native-submissions.jsonl"
            assert len(counter.read_text().splitlines()) == (2 if mode == "shared_runner" else 4)
            diagnostics = await root_sdk.query(
                "view", {"scope": asdict(scope), "kind": "diagnostics"}
            )
            assert len(diagnostics["workflow"]["children"]) == (1 if mode == "shared_runner" else 2)
            assert diagnostics["budget"]["reserved"] == (8 if mode == "shared_runner" else 16)
            if mode in {"cancel", "close_one_failed"}:
                if mode == "close_one_failed":
                    from relf_agent.temporal_coding_composition_control import close

                    children = await root_sdk.query(
                        "view", {"scope": asdict(scope), "kind": "coding_composition_children"}
                    )
                    records = await journal.composition_resources(scope)
                    first = next(
                        row
                        for row in records
                        if row["request"]["dispatch"]["run_id"] == children[0]["run_id"]
                    )
                    failure = tmp_path / "fail-kill-cid"
                    failure.write_text(first["prepared"]["container_id"])
                    with pytest.raises(CloseIncomplete):
                        await close(built, client=client, scope=scope)
                    remaining = await journal.pending_resources(scope)
                    assert len(remaining) == 1
                    assert remaining[0]["request"]["dispatch"]["run_id"] == children[0]["run_id"]
                    failure.unlink()

                    async def retry_close():
                        try:
                            await close(built, client=client, scope=scope)
                            return True
                        except CloseIncomplete as error:
                            (tmp_path / "close-retry-report.json").write_text(
                                json.dumps(error.report, indent=2)
                            )
                            return False

                    await wait_until(retry_close, lambda value: value is True, wait_seconds=60)
                else:
                    await engine.cancel(handle.run_id, command_id="cancel")
                final = await wait_until(
                    lambda: engine.status(handle.run_id),
                    lambda value: value.state == "cancelled",
                    wait_seconds=60,
                )
                diagnostics = await root_sdk.query(
                    "view", {"scope": asdict(scope), "kind": "diagnostics"}
                )
                assert diagnostics["budget"]["unknown"] == 16
                assert len(counter.read_text().splitlines()) == 4
                assert len(diagnostics["workflow"]["children"]) == 2
            else:
                (tmp_path / "release-turns").touch()
                if mode == "shared_runner":
                    second = await wait_until(
                        lambda: engine.status(handle.run_id),
                        lambda value: any(
                            item["run_id"] not in originals for item in value.pending
                        ),
                    )
                    item = next(item for item in second.pending if item["run_id"] not in originals)
                    originals[item["run_id"]] = (
                        await client.get_workflow_handle(item["run_id"]).describe()
                    ).run_id
                    await engine.approve(
                        item["run_id"],
                        action_id=item["action_id"],
                        target_digest=item["digest"],
                        approved=True,
                        command_id="approve-shared-second",
                    )
                joined = await wait_until(
                    lambda: engine.status(handle.run_id),
                    lambda value: any(item["run_id"] not in originals for item in value.pending),
                    wait_seconds=60,
                )
                item = next(item for item in joined.pending if item["run_id"] not in originals)
                await engine.approve(
                    item["run_id"],
                    action_id=item["action_id"],
                    target_digest=item["digest"],
                    approved=True,
                    command_id="approve-join",
                )
                final = await wait_until(
                    lambda: engine.status(handle.run_id), lambda value: value.state == "succeeded"
                )
                assert final.result == {
                    "first": "finished",
                    "second": "finished",
                    "join": "finished",
                }
                assert len(counter.read_text().splitlines()) == 6
            proof = await wait_until(
                lambda: root_sdk.query(
                    "view", {"scope": asdict(scope), "kind": "coding_composition_proof"}
                ),
                lambda value: value["physical_stopped"] is True,
            )
            children = await root_sdk.query(
                "view", {"scope": asdict(scope), "kind": "coding_composition_children"}
            )
            assert proof["execution_epoch"] == proof["original_execution_epoch"]
            for child in children:
                if child["run_id"] in originals:
                    assert child["child_execution"]["execution_epoch"] == originals[child["run_id"]]
            for run_id in [handle.run_id, *(child["run_id"] for child in children)]:
                history = await client.get_workflow_handle(run_id).fetch_history()
                await replay_temporal_history(history, namespace=client.namespace)
                (tmp_path / (run_id + ".history.json")).write_text(history.to_json())
            assert await journal.pending_resources(scope) == ()
            assert json.loads((tmp_path / "docker.json").read_text())["containers"] == {}
            assert final.state in {"succeeded", "cancelled"}
        except Exception as error:
            (tmp_path / "primary-failure.json").write_text(
                json.dumps(
                    {
                        "type": type(error).__name__,
                        "code": getattr(error, "code", None),
                        "report": getattr(error, "report", None),
                    },
                    indent=2,
                )
            )
            raise
        finally:
            failed = sys.exc_info()[0] is not None
            if "root_sdk" in locals():
                try:
                    observations = {
                        "root": await root_sdk.query(
                            "view", {"scope": asdict(scope), "kind": "diagnostics"}
                        )
                    }
                    for child in observations["root"]["workflow"]["children"]:
                        observations[child["run_id"]] = await client.get_workflow_handle(
                            child["run_id"]
                        ).query("view", {"scope": asdict(scope), "kind": "diagnostics"})
                    (tmp_path / "original-diagnostics.json").write_text(
                        json.dumps(observations, indent=2)
                    )
                except Exception:
                    pass
            (tmp_path / "release-turns").touch()
            cleanup_errors = []
            (tmp_path / "fail-kill-cid").unlink(missing_ok=True)
            for native in runners:
                try:
                    await native.aclose()
                except Exception as error:
                    cleanup_errors.append(
                        {"type": type(error).__name__, "code": getattr(error, "code", None)}
                    )
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            (tmp_path / "cleanup-errors.json").write_text(json.dumps(cleanup_errors))
            await journal.aclose()
            await built.journal.aclose()
            sock.close()
            sock_path.unlink(missing_ok=True)
            await conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            await conn.close()
            if not failed:
                assert not cleanup_errors, cleanup_errors

    asyncio.run(run())
