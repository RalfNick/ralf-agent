import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ralf_agent.errors import ValidationError
from ralf_agent.types import Scope


def api():
    return importlib.import_module("ralf_agent.artifacts")


def package_env():
    import ralf_agent

    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(ralf_agent.__file__).resolve().parent.parent),
    }


@pytest.mark.parametrize("phase", ["before", "after"])
def test_real_process_loss_artifact_commit_is_all_or_nothing(tmp_path, phase):
    path = tmp_path / "artifacts.sqlite"
    code = """
import os,sys
from ralf_agent import Scope
from ralf_agent.artifacts import SQLiteArtifactStore
s=SQLiteArtifactStore(sys.argv[1])
conn=s.conn
class Crash:
 def __getattr__(self,name):return getattr(conn,name)
 def execute(self,sql,*args):
  if sql == 'COMMIT' and sys.argv[2]=='before':os._exit(79)
  result=conn.execute(sql,*args)
  if sql == 'COMMIT' and sys.argv[2]=='after':os._exit(79)
  return result
s.conn=Crash()
s.put(Scope(),'results',{'evidence':'confirmed'})
"""
    crashed = subprocess.run(
        [sys.executable, "-c", code, str(path), phase],
        env=package_env(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert crashed.returncode == 79, crashed.stderr
    with api().SQLiteArtifactStore(path) as reopened:
        count = reopened.conn.execute("SELECT COUNT(*) FROM ralf_artifacts").fetchone()[0]
        assert count == (0 if phase == "before" else 1)
        first = reopened.put(Scope(), "results", {"evidence": "confirmed"})
        assert reopened.put(Scope(), "results", {"evidence": "confirmed"}) == first
        assert reopened.get(Scope(), first) == {"evidence": "confirmed"}
        assert reopened.conn.execute("SELECT COUNT(*) FROM ralf_artifacts").fetchone()[0] == 1


def test_concurrent_processes_use_atomic_capacity_and_duplicate_commit(tmp_path):
    path = tmp_path / "artifacts.sqlite"
    with api().SQLiteArtifactStore(path, capacity=1):
        pass
    code = """
import json,sys
from ralf_agent import Scope
from ralf_agent.artifacts import SQLiteArtifactStore
from ralf_agent.errors import BudgetExceeded
with SQLiteArtifactStore(sys.argv[1],capacity=1) as s:
 try:
  ref=s.put(Scope(),'results',{'value':sys.argv[2]})
  print(json.dumps({'id':ref.artifact_id,'value':s.get(Scope(),ref)}))
 except BudgetExceeded: print(json.dumps({'full':True}))
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(path), value],
            env=package_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for value in ["same", "same", "different"]
    ]
    outputs = []
    for process in processes:
        out, err = process.communicate(timeout=20)
        assert process.returncode == 0, err
        outputs.append(json.loads(out))
    successes = [x for x in outputs if "id" in x]
    assert successes and len({x["id"] for x in successes}) == 1
    with api().SQLiteArtifactStore(path, capacity=1) as store:
        assert store.conn.execute("SELECT COUNT(*) FROM ralf_artifacts").fetchone()[0] == 1


def test_artifact_canonical_snapshot_is_not_reread_from_mutable_caller():
    class ChangesOnEncode(dict):
        calls = 0

        def items(self):
            self.calls += 1
            return {"n": self.calls}.items()

    value = ChangesOnEncode(n=0)
    with api().InMemoryArtifactStore() as store:
        ref = store.put(Scope(), "results", value)
        assert store.get(Scope(), ref) == {"n": 1}
        assert value.calls == 1


def test_tampered_sqlite_payload_read_is_bounded_before_decoding(tmp_path):
    with api().SQLiteArtifactStore(tmp_path / "artifacts.sqlite", max_bytes=32) as store:
        ref = store.put(Scope(), "results", {"n": 1})
        store.conn.execute("UPDATE ralf_artifacts SET payload=?", ('"' + "x" * 2000000 + '"',))
        queries = []
        store.conn.set_trace_callback(queries.append)
        with pytest.raises(ValidationError):
            store.get(Scope(), ref)
        assert any("substr" in query.lower() for query in queries)
