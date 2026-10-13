"""Actual process boundaries retain the accepted input command and original Run."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path


def test_process_exit_before_reply_and_after_reply_commit_keeps_one_answer(tmp_path):
    fixture = Path(__file__).resolve()
    for mode, status in [("pause", 0), ("answer-crash", 77), ("resume", 0), ("resume", 0)]:
        process = subprocess.run(
            [sys.executable, str(fixture), str(tmp_path), mode],
            capture_output=True,
            text=True,
            timeout=15,
            env={"PATH": os.defpath, "PYTHONPATH": str(fixture.parent.parent / "src")},
        )
        assert process.returncode == status, process.stderr
    proof = json.loads((tmp_path / "proof.json").read_text())
    original = json.loads((tmp_path / "pending.json").read_text())
    assert proof["run_id"] == original["run_id"]
    assert proof["input"] == "original-task" and proof["state"] == "succeeded"
    assert proof["budget"] == {"limit": 4, "spent": 2, "held": 0}
    assert proof["answer_messages"] == 1 and proof["answered_events"] == 1
    assert (tmp_path / "model-calls.txt").read_text().splitlines() == ["question", "final"]


def worker(directory, mode):
    import ralf_agent as r

    class Provider:
        identity = {"kind": "process-input-provider", "version": "1"}

        async def complete(self, messages, descriptions):
            final = messages[-1]["role"] == "tool"
            with (directory / "model-calls.txt").open("a") as calls:
                calls.write("final\n" if final else "question\n")
            return (
                r.ModelResponse(output="completed")
                if final
                else r.ModelResponse(
                    tool_calls=(
                        r.ToolCall(
                            "request_input", {"prompt": "Which target?"}, "stable-native-id"
                        ),
                    )
                )
            )

    tools = r.ToolRegistry()
    r.register_user_input(tools)
    spec = r.AgentSpec("a", "Answer", ("request_input",))
    with r.LocalEngine(
        r.SQLiteStore(directory / "runs.sqlite"), providers={"default": Provider()}, tools=tools
    ) as engine:
        if mode == "pause":
            handle = engine.submit(spec, "original-task", command_id="submission", budget=4)
            assert asyncio.run(engine.drive(handle.run_id)).state == "waiting_input"
            pending = next(iter(engine.store.run(handle.run_id)["input_requests"].values()))[
                "request"
            ]
            (directory / "pending.json").write_text(
                json.dumps({"run_id": handle.run_id, "request": pending})
            )
            return
        original = json.loads((directory / "pending.json").read_text())
        pending, run_id = original["request"], original["run_id"]
        receipt = engine.send_input(
            run_id, pending["pending_id"], pending["target_digest"], "wire", command_id="answer"
        )
        assert receipt.apply_state == "applied"
        if mode == "answer-crash":
            os._exit(77)
        assert asyncio.run(engine.drive(run_id)).state == "succeeded"
        owner = engine.store.run(run_id)
        assert (
            engine.submit(spec, "original-task", command_id="submission", budget=4).run_id == run_id
        )
        proof = {
            "run_id": run_id,
            "input": owner["input"],
            "state": owner["state"],
            "budget": engine.store.budget(run_id),
            "answer_messages": sum(
                m.get("role") == "tool" and m.get("content") == '"wire"' for m in owner["messages"]
            ),
            "answered_events": sum(e.kind == "input_answered" for e in engine.events(run_id)),
        }
        (directory / "proof.json").write_text(json.dumps(proof))


if __name__ == "__main__":
    worker(Path(sys.argv[1]), sys.argv[2])
