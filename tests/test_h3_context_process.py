"""OS process exit after summary receipt/adoption with saved reference selection."""

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

import ralf_agent
from tests.context_crash_assertions import assert_context_crash_effects


@pytest.mark.parametrize("kind", ["parallel", "team", "dynamic-dag", "nested"])
@pytest.mark.parametrize(
    "window", ["context_preparation_response_received", "context_preparation_adopted"]
)
def test_relevant_context_restores_original_summary_and_effects(tmp_path, kind, window):
    fixture = Path(__file__).with_name("composite_context_crash_fixture.py")
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join(
            [str(Path(ralf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
        ),
    }
    for mode, expected in (("crash", 77), ("resume", 0)):
        result = subprocess.run(
            [sys.executable, str(fixture), str(tmp_path), kind, window, mode, "relevant"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == expected, result.stderr
    assert_context_crash_effects(tmp_path)
    with closing(sqlite3.connect(tmp_path / "runs.sqlite")) as db:
        runs = [json.loads(row[0]) for row in db.execute("SELECT data FROM runs")]

    def snapshots_in(value):
        if isinstance(value, dict):
            for record in value.get("context_preparations", {}).values():
                if record["snapshot"] is not None:
                    yield record["snapshot"]
            for key, item in value.items():
                if key != "context_preparations":
                    yield from snapshots_in(item)
        elif isinstance(value, list):
            for item in value:
                yield from snapshots_in(item)

    snapshots = list(snapshots_in(runs))
    assert snapshots
    selections = [snapshot["manifest"]["reference_selection"] for snapshot in snapshots]
    assert all(selection["selected_count"] >= 1 for selection in selections)
    assert all(
        selection["source_digest"] and selection["selector"]["identity"]["version"] == "1"
        for selection in selections
    )
