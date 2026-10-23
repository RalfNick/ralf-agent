"""Execute the documented two-database backup, then replace lost execution data.

All applications run in independent processes against the installed/current SDK.
Original directories and incomplete backups are retained as recovery evidence.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from relf_agent.starter import create_starter

PRELUDE = """
import asyncio, json
from dataclasses import asdict
from agent_app.runtime import create_engine, agent_spec, ChangeService
db = '.ralf/runs.sqlite'
"""


def app(project, source, *, expected=0):
    result = subprocess.run(
        [sys.executable, "-c", PRELUDE + source],
        cwd=project,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == expected, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def documented_backup(project, *, expected=0):
    guide = Path(__file__).parents[1] / "docs/recovery-guide.md"
    section = guide.read_text().split("## 默认本地项目的手工备份演练", 1)[1]
    source = section.split("```python\n", 1)[1].split("```", 1)[0]
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=project,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == expected, result.stderr
    if expected == 0:
        assert "Both databases backed up:" in result.stdout
        backup = project / "private-backup-001"
        assert backup.stat().st_mode & 0o777 == 0o700
        for name in ("runs.sqlite", "runs.sqlite.business.sqlite"):
            assert (backup / name).stat().st_mode & 0o777 == 0o600
    return result


def dump(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        return list(connection.iterdump())


def project_at(tmp_path):
    project = tmp_path / "oncall"
    create_starter(project)
    (project / ".ralf").mkdir()
    return project


def restore(project, *, keep_current_business=False):
    # Every application process has exited and its actual handler has ended.
    # Preserve the complete original directory, including original WAL/locks.
    original = project / "original-ralf-retained"
    (project / ".ralf").rename(original)
    (project / ".ralf").mkdir(mode=0o700)
    backup = project / "private-backup-001"
    for name in ("runs.sqlite", "runs.sqlite.business.sqlite"):
        source = (
            original / name
            if keep_current_business and name.endswith("business.sqlite")
            else backup / name
        )
        target = project / ".ralf" / name
        shutil.copyfile(source, target)
        target.chmod(0o600)
        assert source.stat().st_ino != target.stat().st_ino
        assert dump(target) == dump(source)
    return original


def test_documented_backup_restores_approval_and_wrong_version_can_roll_back(tmp_path):
    project = project_at(tmp_path)
    initial = app(
        project,
        """
with create_engine(db) as engine:
    handle = engine.submit(agent_spec(), {'ticket':'RESTORE'}, command_id='original')
    waiting = asyncio.run(engine.drive(handle.run_id))
    print(json.dumps(asdict(waiting)))
""",
    )
    assert initial["state"] == "waiting_approval"
    before = dump(project / ".ralf/runs.sqlite")
    documented_backup(project)
    assert dump(project / "private-backup-001/runs.sqlite") == before
    original = restore(project)
    # The running database was actually replaced from the offline snapshot.
    assert dump(original / "runs.sqlite") == before
    run_id = initial["run_id"]
    failed = app(
        project,
        f"""
from relf_agent.errors import DefinitionMismatch
from agent_app.runtime import OfflineProvider
class WrongVersion(OfflineProvider):
    identity = {{'kind':'starter-offline','version':'incompatible-upgrade'}}
with create_engine(db) as engine:
    engine.providers['default'] = WrongVersion()
    try:
        asyncio.run(engine.drive({run_id!r}))
    except DefinitionMismatch as error:
        print(json.dumps({{'code':error.code}}))
    else:
        raise AssertionError('Incompatible original Run was executed')
""",
    )
    assert failed == {"code": "definition_mismatch"}
    assert dump(project / ".ralf/runs.sqlite") == before
    final = app(
        project,
        f"""
with create_engine(db) as engine:
    handle = engine.submit(agent_spec(), {{'ticket':'RESTORE'}}, command_id='original')
    assert handle.run_id == {run_id!r}
    waiting = engine.status(handle.run_id)
    assert waiting.state == 'waiting_approval'
    pending = waiting.pending[0]
    receipt = engine.approve(handle.run_id, pending['action_id'], pending['digest'], command_id='approved')
    assert receipt == engine.approve(handle.run_id, pending['action_id'], pending['digest'], command_id='approved')
    done = asyncio.run(engine.drive(handle.run_id))
    assert done.state == 'succeeded' and done.result['verified'] is True
    assert engine.status(handle.run_id).pending == ()
    print(json.dumps({{'state':done.state,'run_id':handle.run_id,'receipt':asdict(receipt)}}))
""",
    )
    assert final["run_id"] == run_id
    with sqlite3.connect(project / ".ralf/runs.sqlite.business.sqlite") as business:
        assert business.execute("SELECT COUNT(*) FROM effects").fetchone() == (1,)
    (tmp_path / "local-approval-restore.json").write_text(json.dumps(final))


def test_unknown_restore_keeps_post_backup_external_effects_and_original_receipts(tmp_path):
    project = project_at(tmp_path)
    initial = app(
        project,
        """
import os
original_apply = ChangeService.apply
def crash_after_actual_commit(self, arguments, effect_key):
    original_apply(self, arguments, effect_key)
    os._exit(77)
ChangeService.apply = crash_after_actual_commit
with create_engine(db) as engine:
    handle = engine.submit(agent_spec(), {'ticket':'UNKNOWN'}, command_id='original')
    waiting = asyncio.run(engine.drive(handle.run_id))
    pending = waiting.pending[0]
    receipt = engine.approve(handle.run_id, pending['action_id'], pending['digest'], command_id='approved')
    print(json.dumps({'run_id':handle.run_id,'pending':pending,'receipt':asdict(receipt)}),flush=True)
    asyncio.run(engine.drive(handle.run_id))
""",
        expected=77,
    )
    with sqlite3.connect(project / ".ralf/runs.sqlite.business.sqlite") as business:
        original_effect_key = business.execute(
            "SELECT effect_key FROM effects WHERE ticket='UNKNOWN'"
        ).fetchone()[0]
    documented_backup(project)
    # External reality can move after a framework backup. Never replace this
    # actual business database with the older business snapshot on recovery.
    app(
        project,
        """
ChangeService(db + '.business.sqlite').apply({'ticket':'AFTER-BACKUP'}, 'external-new')
""",
    )
    restore(project, keep_current_business=True)
    restored = app(
        project,
        f"""
with create_engine(db) as engine:
    handle = engine.submit(agent_spec(), {{'ticket':'UNKNOWN'}}, command_id='original')
    assert handle.run_id == {initial["run_id"]!r}
    prior = engine.status(handle.run_id)
    action = next(a for a in prior.actions if a.get('tool') == 'apply_change')
    # Cold status retains the original executing attempt; drive, not backup,
    # owns abandoned-attempt normalization and original effect lookup.
    assert action['status'] == 'executing'
    assert action['effect_key'] == {original_effect_key!r}
    pending = {initial["pending"]!r}
    receipt = engine.approve(handle.run_id, pending['action_id'], pending['digest'], command_id='approved')
    assert asdict(receipt) == {initial["receipt"]!r}
    done = asyncio.run(engine.drive(handle.run_id))
    assert done.state == 'succeeded' and done.result['verified'] is True
    dispatched = [e for e in engine.events(handle.run_id) if e.kind=='tool_dispatch_intent' and e.data['action_id']==action['id']]
    assert len(dispatched) == 1
    print(json.dumps({{'state':done.state,'run_id':handle.run_id,'effect_key':action['effect_key'],'original_dispatch_intents':len(dispatched)}}))
""",
    )
    with sqlite3.connect(project / ".ralf/runs.sqlite.business.sqlite") as business:
        assert business.execute("SELECT COUNT(*) FROM effects").fetchone() == (2,)
        assert business.execute(
            "SELECT effect_key FROM effects WHERE ticket='UNKNOWN'"
        ).fetchone() == (restored["effect_key"],)
        assert business.execute(
            "SELECT effect_key FROM effects WHERE ticket='AFTER-BACKUP'"
        ).fetchone() == ("external-new",)
    (tmp_path / "local-unknown-restore.json").write_text(json.dumps(restored))


def test_documented_backup_refuses_another_live_coordinator(tmp_path):
    project = project_at(tmp_path)
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            PRELUDE + "with create_engine(db) as engine:\n print('OWNED',flush=True)\n input()\n",
        ],
        cwd=project,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdout.readline().strip() == "OWNED"
        before = dump(project / ".ralf/runs.sqlite")
        rejected = documented_backup(project, expected=1)
        assert "CoordinatorBusy" in rejected.stderr
        assert dump(project / ".ralf/runs.sqlite") == before
        assert list((project / "private-backup-001").iterdir()) == []
    finally:
        _, error = process.communicate("\n", timeout=10)
        assert process.returncode == 0, error
