"""Passive diagnostic keeps actual SDK error identity and excludes private errors."""

import asyncio
import json
import sys

import pytest

from ralf_agent.temporal_coding_composition_control import _adopt
from tests.test_temporal_deployment_coding_parent_capacity_service import (
    observe_original_parent_rpc,
)

pytest.importorskip("temporalio")
from temporalio.service import RPCError, RPCStatusCode

pytestmark = pytest.mark.skipif(
    not hasattr(sys, "monitoring"), reason="passive RPC proof requires Python 3.12 monitoring"
)


@pytest.mark.parametrize("limit", [False, True])
def test_observer_records_original_parent_rpc_without_replacing_or_swallowing_it(
    tmp_path, monkeypatch, limit
):
    from ralf_agent import temporal_session_activities

    async def namespace_id(client):
        return "11111111-1111-1111-1111-111111111111"

    monkeypatch.setattr(temporal_session_activities, "namespace_id", namespace_id)
    original_code = _adopt.__code__
    tools = [sys.monitoring.get_tool(i) for i in range(6)]
    message = (
        "The limit on the total number of distinct updates in this workflow has been reached (2000)."
        if limit
        else "postgresql://private:user-password sk-fixture-secret"
    )
    error = RPCError(message, RPCStatusCode.FAILED_PRECONDITION, b"")
    parent = {
        "scope": {"workspace": "original", "principal": "owner"},
        "run_id": "parent",
        "execution_epoch": "parent-epoch",
        "request_digest": "a" * 64,
        "release_digest": "b" * 64,
        "namespace": {"name": "original", "id": "11111111-1111-1111-1111-111111111111"},
    }

    class Handle:
        async def execute_update(self, name, payload, **options):
            assert name == "coding_composition_child_stopped"
            assert payload["run_id"] == "parent" and payload["child_run_id"] == "child"
            raise error

    class Client:
        namespace = "original"

        def get_workflow_handle(self, identity, *, run_id):
            assert (identity, run_id) == ("parent", "parent-epoch")
            return Handle()

    async def run():
        with observe_original_parent_rpc(tmp_path):
            with pytest.raises(RPCError) as caught:
                await _adopt(Client(), parent, {"run_id": "child"})
            assert caught.value is error

    asyncio.run(run())
    assert _adopt.__code__ is original_code
    assert [sys.monitoring.get_tool(i) for i in range(6)] == tools
    output = (tmp_path / "parent-recovery-rpc-errors.jsonl").read_text()
    assert "sk-fixture-secret" not in output and "user-password" not in output
    (record,) = [json.loads(line) for line in output.splitlines()]
    assert record["run_id"] == "parent" and record["execution_epoch"] == "parent-epoch"
    assert record["operation"] == "coding_composition_child_stopped"
    assert record["status"] == "FAILED_PRECONDITION"
    assert record["message_category"] == ("distinct_update_limit" if limit else "other_rpc_error")
    assert record["message"] == (message if limit else None)
