"""Assert durable effects across the real context crash fixture's two agents."""

import json
import sqlite3
from contextlib import closing


def assert_context_crash_effects(directory, *, file_artifacts=False):
    with closing(sqlite3.connect(directory / "business.sqlite")) as database:
        counts = dict(database.execute("SELECT kind,COUNT(*) FROM calls GROUP BY kind"))
        effects = database.execute("SELECT key FROM effects").fetchall()
        calls = database.execute("SELECT run_id,node_id,artifact_id FROM artifact_calls").fetchall()
    assert counts["tool"] == 8 and counts["summary"] == 4
    assert len(effects) == len(set(effects)) == 8

    with closing(sqlite3.connect(directory / "runs.sqlite")) as database:
        dispatches = [
            (run_id, json.loads(data))
            for run_id, data in database.execute(
                "SELECT run_id,data FROM events WHERE kind='context_artifact_dispatched'"
            )
        ]
    identities = [
        (run_id, data.get("workflow_node"), data["artifact_id"]) for run_id, data in dispatches
    ]
    # A crash can leave a durable dispatch before the backend method enters.
    # Count actual calls separately so content dedup cannot hide a repeated put.
    assert 1 <= len(identities) <= 2
    assert len(identities) == len(set(identities))
    assert 1 <= len(calls) == len(set(calls)) == counts["artifact"]
    assert set(calls) <= set(identities)
    artifact_ids = {artifact_id for _, _, artifact_id in identities}
    assert len(artifact_ids) == 1

    if file_artifacts:
        files = list((directory / "file-artifacts").glob("*.json"))
        assert len(files) == 1 and files[0].stem in artifact_ids
        payload = files[0].read_text()
        index = directory / "file-artifacts" / ".index.sqlite"
        with closing(sqlite3.connect(index)) as database:
            assert database.execute("SELECT COUNT(*) FROM ralf_artifacts").fetchone()[0] == 1
    else:
        with closing(sqlite3.connect(directory / "artifacts.sqlite")) as database:
            artifacts = database.execute(
                "SELECT artifact_id,payload FROM ralf_artifacts"
            ).fetchall()
        assert len(artifacts) == 1 and artifacts[0][0] in artifact_ids
        payload = artifacts[0][1]
    # The artifact contains the canonical tool-message text, not a preview.
    assert json.loads(json.loads(payload)) == "BIG" * 4000
    return counts
