import json
import sqlite3
import subprocess
import sys

import pytest

from .test_cli import subprocess_env


@pytest.mark.parametrize("kind", ["agent", "team"])
@pytest.mark.parametrize("window", ["before", "after"])
def test_default_external_sqlite_recovers_original_turn_after_process_death(tmp_path, kind, window):
    def worker(phase):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.default_session_receipt_worker",
                str(tmp_path),
                phase,
                kind,
                window,
            ],
            env=subprocess_env(),
            capture_output=True,
            text=True,
            timeout=25,
        )

    prepared = worker("prepare")
    assert prepared.returncode == 0, prepared.stderr
    crashed = worker("crash")
    assert crashed.returncode == 77, crashed.stderr
    with sqlite3.connect(tmp_path / "effects.sqlite") as connection:
        assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM calls WHERE kind='model'").fetchone()[0] == 2
        )
    finished = worker("recover")
    assert finished.returncode == 0, finished.stderr
    assert json.loads(finished.stdout) == {"state": "succeeded", "revision": 1}
    with sqlite3.connect(tmp_path / "effects.sqlite") as connection:
        assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM calls WHERE kind='model'").fetchone()[0] == 2
        )
        assert connection.execute("SELECT count(*) FROM calls WHERE kind='append'").fetchone()[
            0
        ] == (1 if window == "after" else 2)
