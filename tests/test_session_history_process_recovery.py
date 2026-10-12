"""Actual Local process loss preserves native snapshot/freeze/publication windows."""

import asyncio
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

import ralf_agent as r
from tests.test_model_history_process_recovery import (
    FIRST_RAW,
    SECOND_RAW,
    ProcessProvider,
    ProcessVerifier,
    spec,
)


def worker(root, window, mode):
    class CrashStore(r.SQLiteStore):
        depth, trigger = 0, False

        @contextmanager
        def transaction(self):
            self.depth += 1
            try:
                with super().transaction():
                    yield
            finally:
                self.depth -= 1
            if self.depth == 0 and self.trigger:
                os._exit(77)

        def emit(self, run_id, kind, data=None):
            super().emit(run_id, kind, data)
            if mode == "crash" and kind == window:
                self.trigger = True

        def publish_native_history(self, scope, stream, message_id, evidence):
            super().publish_native_history(scope, stream, message_id, evidence)
            if mode == "crash" and window == "native_before_success_commit":
                os._exit(77)

    async def scenario():
        with r.LocalEngine(
            CrashStore(root / "runs.sqlite"),
            providers={"default": ProcessProvider(root / "model-calls.jsonl")},
            tools=r.ToolRegistry(),
            verifier=ProcessVerifier(),
            model_continuation=True,
            model_history=r.CompleteModelHistory(scope="session"),
        ) as engine:
            first = engine.submit(
                spec(), "first-task", session_id="same", command_id="first", budget=10
            )
            if mode == "crash":
                (root / "run-id").write_text(first.run_id)
            else:
                assert first.run_id == (root / "run-id").read_text()
            assert (await engine.drive(first.run_id)).state == "succeeded"
            if mode == "crash":
                raise AssertionError("Crash window was not reached")
            original = engine.store.run(first.run_id)
            assert (
                engine.submit(
                    spec(), "first-task", session_id="same", command_id="first", budget=10
                )
                == first
            )
            assert (await engine.drive(first.run_id)).state == "succeeded"
            assert engine.store.run(first.run_id) == original
            second = engine.submit(
                spec(), "second-task", session_id="same", command_id="second", budget=10
            )
            assert (await engine.drive(second.run_id)).state == "succeeded"
            print(
                json.dumps(
                    {
                        "first": original,
                        "second": engine.store.run(second.run_id),
                        "publications": engine.store.conn.execute(
                            "SELECT count(*) FROM native_history_publications"
                        ).fetchone()[0],
                    }
                )
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "window",
    [
        "native_history_snapshot_adopted",
        "native_history_episode_frozen",
        "native_before_success_commit",
        "run_succeeded",
    ],
)
def test_actual_process_exit_keeps_snapshot_and_original_success_publication(tmp_path, window):
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join(
            (str(Path(r.__file__).parent.parent), str(Path(__file__).parent.parent))
        ),
    }
    results = []
    for mode, code in (("crash", 77), ("resume", 0)):
        process = subprocess.run(
            [sys.executable, str(Path(__file__)), str(tmp_path), window, mode],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert process.returncode == code, process.stderr or process.stdout
        if mode == "crash":
            with r.SQLiteStore(tmp_path / "runs.sqlite", readonly=True) as store:
                root = store.run((tmp_path / "run-id").read_text())
                assert root["state"] == ("succeeded" if window == "run_succeeded" else "running")
                assert store.conn.execute(
                    "SELECT count(*) FROM native_history_publications"
                ).fetchone()[0] == (1 if window == "run_succeeded" else 0)
                if window == "native_before_success_commit":
                    stream = root["native_model_history"]["stages"]["agent"]["stream"]
                    assert (
                        store.conn.execute(
                            "SELECT data FROM memory_sessions WHERE workspace=? AND principal=? AND session=?",
                            (
                                r.Scope().workspace,
                                r.Scope().principal,
                                r.native_history_address(stream),
                            ),
                        ).fetchone()
                        is None
                    )
        else:
            results.append(json.loads(process.stdout))
    result = results[0]
    assert result["publications"] == 2
    calls = [json.loads(line) for line in (tmp_path / "model-calls.jsonl").read_text().splitlines()]
    assert len(calls) == 3
    assert [m["role"] for m in calls[2]["messages"][:6]] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert calls[2]["messages"][2]["content"] == FIRST_RAW
    assert calls[2]["messages"][4]["content"] == SECOND_RAW
    assert calls[2]["messages"][5]["content"] == "second-task"
    assert result["second"]["messages"][1]["content"] == "second-task"


if __name__ == "__main__":
    worker(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
