"""Real process exits prove receipt/adoption/verification recovery, not exception unwinding."""

import asyncio
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

import ralf_agent
from ralf_agent import AgentSpec, CompleteModelHistory, LocalEngine, SQLiteStore, ToolRegistry
from ralf_agent.completion import CompletionVerdict
from ralf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
from ralf_agent.types import digest

FIRST_RAW = ' { "answer" : "first" } '
SECOND_RAW = ' { "answer" : "second" } '


class ProcessProvider:
    identity = {"kind": "complete-history-process-fixture", "version": "1"}
    continuation_identity = {"protocol": "process-history-v1", "owner_digest": "b" * 64}

    def __init__(self, audit):
        self.audit = audit

    async def complete(self, messages, tools):
        # The audit is separate from execution storage and fsynced before return.
        # An actual repeated model dispatch after process exit produces another line.
        record = json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False) + "\n"
        with self.audit.open("a", encoding="utf-8") as stream:
            stream.write(record)
            stream.flush()
            os.fsync(stream.fileno())
        retried = any(
            isinstance(message.get("content"), str)
            and message["content"].startswith("Completion verification:")
            for message in messages
        )
        output = SECOND_RAW if retried else FIRST_RAW
        return ContinuedModelResponse(
            output=output,
            continuation=ModelContinuation(
                "process-history-v1",
                "b" * 64,
                digest({"output": output, "tool_calls": []}),
                {"signature": "第二个原始签名" if retried else "第一个原始签名"},
            ),
        )


class ProcessVerifier:
    identity = {"kind": "complete-history-process-verifier", "version": "1"}

    def verify(self, request):
        return (
            CompletionVerdict("retry", "Need the second answer")
            if request.output["answer"] == "first"
            else CompletionVerdict("accept")
        )


def spec():
    return AgentSpec(
        "answer",
        "Answer in JSON",
        output_schema={
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
            "additionalProperties": False,
        },
    )


def process_worker(root, window, mode):
    class CrashStore(SQLiteStore):
        depth, trigger = 0, False

        @contextmanager
        def transaction(self):
            self.depth += 1
            try:
                with super().transaction():
                    yield
            finally:
                self.depth -= 1
            if not self.depth and self.trigger:
                # This executes only after the outermost SQLite transaction commits;
                # os._exit bypasses finally, Engine.close and asyncio cancellation.
                os._exit(77)

        def emit(self, run_id, event, data=None):
            super().emit(run_id, event, data)
            if mode == "crash" and event == window:
                self.trigger = True

    with LocalEngine(
        CrashStore(root / "runs.sqlite"),
        providers={"default": ProcessProvider(root / "model-calls.jsonl")},
        tools=ToolRegistry(),
        verifier=ProcessVerifier(),
        model_continuation=True,
        model_history=CompleteModelHistory(),
    ) as engine:
        handle = engine.submit(spec(), "question", command_id="original-command", budget=10)
        run_id_file = root / "run-id.txt"
        if mode == "crash":
            run_id_file.write_text(handle.run_id)
        else:
            assert handle.run_id == run_id_file.read_text()
        result = asyncio.run(engine.drive(handle.run_id))
        if mode == "crash":
            raise AssertionError("Expected committed crash window was not reached")
        original = engine.store.run(handle.run_id)
        budget = engine.store.budget(handle.run_id)
        assert engine.submit(spec(), "question", command_id="original-command", budget=10) == handle
        assert asyncio.run(engine.drive(handle.run_id)) == result
        assert engine.store.run(handle.run_id) == original
        assert engine.store.budget(handle.run_id) == budget
        print(
            json.dumps(
                {
                    "run_id": handle.run_id,
                    "state": result.state,
                    "result": result.result,
                    "messages": original["messages"],
                    "actions": original["actions"],
                    "budget": budget,
                    "reservation_states": [
                        row[0]
                        for row in engine.store.conn.execute(
                            "SELECT state FROM reservations WHERE run_id=?", (handle.run_id,)
                        ).fetchall()
                    ],
                },
                ensure_ascii=False,
            )
        )


@pytest.mark.parametrize(
    "window", ["model_response_recorded", "decision_adopted", "completion_verified"]
)
def test_committed_process_exit_preserves_complete_original_final_and_verifier_retry(
    tmp_path, window
):
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join(
            (str(Path(ralf_agent.__file__).parent.parent), str(Path(__file__).parent.parent))
        ),
    }
    for mode, expected in (("crash", 77), ("resume", 0)):
        process = subprocess.run(
            [sys.executable, str(Path(__file__)), str(tmp_path), window, mode],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert process.returncode == expected, process.stderr or process.stdout
        if mode == "crash":
            audit = [
                json.loads(line)
                for line in (tmp_path / "model-calls.jsonl").read_text().splitlines()
            ]
            assert len(audit) == 1
            with SQLiteStore(tmp_path / "runs.sqlite") as store:
                partial = store.run((tmp_path / "run-id.txt").read_text())
                first = next(action for action in partial["actions"] if action["kind"] == "model")
                assert first["received_response"]["output"] == FIRST_RAW
                assert first["received_response"]["continuation"]["data"] == {
                    "signature": "第一个原始签名"
                }
                assistants = [
                    message for message in partial["messages"] if message["role"] == "assistant"
                ]
                assert len(assistants) == (0 if window == "model_response_recorded" else 1)
                if window == "completion_verified":
                    assert partial["messages"][-1]["role"] == "user"
                    assert first["completion_verification"]["verdict"]["status"] == "retry"
            continue
        result = json.loads(process.stdout)
        assert result["state"] == "succeeded" and result["result"] == {"answer": "second"}
        assert result["budget"]["spent"] == 2
        assert result["budget"]["held"] == 0
        assert result["reservation_states"] == ["settled", "settled"]
        assistants = [message for message in result["messages"] if message["role"] == "assistant"]
        assert [message["content"] for message in assistants] == [FIRST_RAW, SECOND_RAW]
        assert [message["model_continuation"]["data"] for message in assistants] == [
            {"signature": "第一个原始签名"},
            {"signature": "第二个原始签名"},
        ]
        assert [message["role"] for message in result["messages"]] == [
            "system",
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        audit = [
            json.loads(line) for line in (tmp_path / "model-calls.jsonl").read_text().splitlines()
        ]
        assert len(audit) == 2
        assert audit[0]["messages"] == result["messages"][:2]
        assert audit[1]["messages"] == result["messages"][:-1]
        assert audit[0]["tools"] == audit[1]["tools"] == []
        models = [action for action in result["actions"] if action["kind"] == "model"]
        assert len(models) == 2
        assert [model["received_response"]["output"] for model in models] == [FIRST_RAW, SECOND_RAW]
        assert [model["status"] for model in models] == ["completed", "completed"]


if __name__ == "__main__":
    process_worker(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
