import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from ralf_agent import InvocationContext, Scope, SQLiteStore
from ralf_agent.errors import ValidationError
from ralf_agent.executors import DispatchEnvelope

ROOT = Path(__file__).resolve().parents[1]
FACTORY = "examples.execution_components:create_engine"


def test_business_adapter_deduplicates_effect_key_and_rejects_changed_request(tmp_path):
    from examples.execution_components import BusinessExecutor, BusinessService

    service = BusinessService(tmp_path / "business.sqlite")
    executor = BusinessExecutor(service)
    context = InvocationContext(Scope(), "run", "action", "attempt", "same-effect", "owner")
    arguments = {"ticket": "INC-DEDUPE", "plan": "approved plan"}
    envelope = DispatchEnvelope(context, {"name": "apply_change"}, arguments, "approved-digest")

    async def retry():
        first = await executor.execute(envelope)
        again = await executor.execute(envelope)
        assert (
            first.result
            == again.result
            == {
                "ticket": "INC-DEDUPE",
                "plan": "approved plan",
                "change_id": "same-effect",
                "verified": True,
            }
        )
        assert (await executor.reconcile(envelope)).result == first.result
        changed = DispatchEnvelope(
            context, {"name": "apply_change"}, {**arguments, "plan": "changed"}, "changed-digest"
        )
        with pytest.raises(ValidationError):
            await executor.execute(changed)

    asyncio.run(retry())
    with sqlite3.connect(service.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0] == 2


def process(arguments, *, cwd, returncode=0):
    result = subprocess.run(
        [str(value) for value in arguments],
        cwd=cwd,
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT))),
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == returncode, result.stderr
    return result.stdout


@pytest.mark.parametrize("workflow", [False, True])
def test_custom_component_example_stays_approved_and_recovers_via_cli(tmp_path, workflow):
    database = tmp_path / "component.sqlite"
    entry = [sys.executable, "-m", "examples.execution_components", "--db", database]
    if workflow:
        entry.append("--workflow")
    waiting = json.loads(process(entry, cwd=tmp_path))
    assert waiting["state"] == "waiting_approval"
    pending = waiting["pending"][0]
    assert pending["arguments"] == {
        "ticket": "INC-COMPONENTS",
        "plan": "policy/component-change: restart fixture cache",
    }
    business = Path(str(database) + ".business.sqlite")
    with sqlite3.connect(business) as connection:
        assert connection.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 0
    with SQLiteStore(database, readonly=True) as store:
        submitted = store.run(waiting["run_id"])
    model = next(action for action in submitted["actions"] if action["kind"] == "model")
    assert "Example policy for component-change" in model["snapshot"][0]["content"]
    assert model["received_response"]["tool_calls"][0]["arguments"]["plan"] == (
        "restart fixture cache"
    )
    cli = [sys.executable, "-m", "ralf_agent", "--db", database, "--factory", FACTORY]
    approval = json.loads(
        process(
            [
                *cli,
                "approve",
                waiting["run_id"],
                pending["action_id"],
                "--digest",
                pending["digest"],
                "--command-id",
                "approve-components",
            ],
            cwd=tmp_path,
        )
    )
    assert approval["apply_state"] == "applied"
    complete = json.loads(process([*cli, "resume", waiting["run_id"]], cwd=tmp_path))
    assert complete["state"] == "succeeded"
    assert complete["result"]["verified"] is True
    assert complete["result"]["plan"] == pending["arguments"]["plan"]
    assert complete["result"]["policy"] == ("component-summary" if workflow else "component-change")
    if workflow:
        assert complete["result"]["summary"] == "One approved fixture change was verified."
    tool = next(action for action in complete["actions"] if action["kind"] == "tool")
    assert tool["receipt"]["source"] == "example-business-executor"
    with sqlite3.connect(business) as connection:
        rows = connection.execute(
            "SELECT effect_key, action_id, operation_digest, arguments FROM dispatches"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][:3] == (tool["effect_key"], pending["action_id"], pending["digest"])
        assert json.loads(rows[0][3]) == pending["arguments"]
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
    replay = json.loads(process(entry, cwd=tmp_path))
    assert replay["run_id"] == waiting["run_id"]
    assert replay["state"] == "succeeded"
    with sqlite3.connect(business) as connection:
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1


def test_custom_example_queries_an_effect_committed_before_process_crash(tmp_path):
    database = tmp_path / "crash.sqlite"
    waiting = json.loads(
        process(
            [sys.executable, "-m", "examples.execution_components", "--db", database], cwd=tmp_path
        )
    )
    pending = waiting["pending"][0]
    cli = [sys.executable, "-m", "ralf_agent", "--db", database, "--factory", FACTORY]
    process(
        [
            *cli,
            "approve",
            waiting["run_id"],
            pending["action_id"],
            "--digest",
            pending["digest"],
            "--command-id",
            "approve-crash",
        ],
        cwd=tmp_path,
    )
    crash = """
import asyncio
import os
import sys
from examples.execution_components import BusinessService, create_engine

apply_change = BusinessService.apply

def commit_then_exit(self, envelope):
    apply_change(self, envelope)
    os._exit(77)

BusinessService.apply = commit_then_exit
with create_engine(sys.argv[1]) as engine:
    asyncio.run(engine.drive(sys.argv[2]))
"""
    process([sys.executable, "-c", crash, database, waiting["run_id"]], cwd=tmp_path, returncode=77)
    complete = json.loads(process([*cli, "resume", waiting["run_id"]], cwd=tmp_path))
    assert complete["state"] == "succeeded"
    tool = next(action for action in complete["actions"] if action["kind"] == "tool")
    assert tool["receipt"]["source"] == "example-business-reconciler"
    with sqlite3.connect(str(database) + ".business.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0] == 1
