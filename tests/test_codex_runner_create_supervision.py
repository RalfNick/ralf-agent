"""Actual original broker no-submit receipt reaches the original Local Action."""

import asyncio
import json
import shutil

from relf_agent.codex_create_supervisor import CreateSupervisor
from relf_agent.errors import ExecutionHostFailed
from tests.test_codex_runner import original_engine


def test_original_never_go_seals_local_action_without_fake_container_fence(tmp_path, monkeypatch):
    def never_go(self):
        # Registered original broker; seal its outer gate and observe real end.
        # This fault injects no daemon/native response or manufactured receipt.
        self.abort()
        raise ExecutionHostFailed("Injected original Worker failed before outer GO")

    monkeypatch.setattr(CreateSupervisor, "start_once", never_go)
    engine, run_id, runner, journal = original_engine(tmp_path, timeout=10)

    async def scenario():
        waiting = await engine.drive(run_id)
        pending = waiting.pending[0]
        engine.approve(run_id, pending["action_id"], pending["digest"], command_id="approve")
        result = await engine.drive(run_id)
        assert result.state == "waiting_reconciliation"
        action = next(a for a in engine.store.run(run_id)["actions"] if a["kind"] == "tool")
        state = action["delegated_execution"]
        proof = state["create_not_dispatched"]
        assert proof["metadata_present"] is True and proof["container_present"] is False
        assert proof["cli_gate_accepted"] is proof["cli_exec_started"] is False
        assert proof["helpers_ended"] is proof["control_drained"] is True
        assert state["fenced"] is True and state["pending_stop"] is False
        assert state.get("prepared") is state.get("stop") is None
        assert set(state["grants"]) == {"prepare"}
        assert len(action["attempts"]) == 1
        assert not (tmp_path / "docker.json").exists()
        capacity = json.loads((runner._root / ".coding-capacity.json").read_text())
        assert capacity["obligation"] is None
        await runner.aclose()
        assert runner.active_operations == 0

    try:
        asyncio.run(scenario())
    finally:
        # Original mechanical evidence is preserved; remove only test control
        # dirs once all original processes have ended and monitors have closed.
        for path in runner._root.glob("*/environment.json"):
            metadata = json.loads(path.read_text())
            directory = metadata["create_operation"]["declaration"]["control_directory"]["path"]
            shutil.rmtree(directory)
        journal.close()
        engine.close()
