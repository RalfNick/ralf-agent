"""An original stop may precede the original business Tool claim."""

import asyncio
import copy

import pytest

from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch
from tests.test_temporal_coding_recovery_transport import api, fixture
from tests.test_temporal_coding_recovery_transport_client import Client
from tests.test_temporal_coding_state import bind, ready


@pytest.mark.parametrize("claimed", [False, True])
def test_complete_original_stop_observation_preserves_absent_or_original_claim(
    monkeypatch, claimed
):
    async def scenario():
        node, info, envelope = fixture(monkeypatch, "admit_coding_stop")
        if not claimed:
            node.state = ready()[0]
        before = copy.deepcopy(node.state.tool_executions)
        action = node.state.actions[-1]
        grants = copy.deepcopy(action["delegated_execution"]["grants"])
        client = Client(node, info)
        receipts = []
        for _ in range(2):
            receipts.append(
                await api().execute(
                    client,
                    info.workflow_id,
                    "admit_coding_stop",
                    envelope["proof"],
                    execution_epoch=info.run_id,
                )
            )
        assert receipts[0] == receipts[1]
        assert receipts[0]["original_invocation_id"] == before[action["id"]].get("invocation_id")
        assert node.state.tool_executions == before
        assert action["delegated_execution"]["grants"] == grants
        assert action["delegated_execution"]["stop_invocations"] == [
            envelope["proof"]["invocation_id"]
        ]
        assert not node.state.tool_executions[action["id"]]["execution_stopped"]
        assert len(client.signals) == 2 and not client.updates
        with pytest.raises(AuthorizationDenied):
            node.state.admit_coding_phase(
                envelope["proof"]
                | {
                    "method": "prepare",
                    "params": {},
                    "binding": bind(action["delegated_execution"]["tool_request"]),
                }
            )
        assert node.state.tool_executions == before
        assert action["delegated_execution"]["grants"] == grants

    asyncio.run(scenario())


class Text(str):
    pass


@pytest.mark.parametrize("invalid", ["", 0, False, [], {}, Text("invocation")])
def test_nullable_stop_claim_still_rejects_other_types_and_empty_text(monkeypatch, invalid):
    node, _, envelope = fixture(monkeypatch, "admit_coding_stop")
    receipt = node.state.admit_coding_stop(envelope["proof"])
    receipt["original_invocation_id"] = invalid
    with pytest.raises(DefinitionMismatch):
        api()._receipt("admit_coding_stop", envelope["proof"], receipt)


@pytest.mark.parametrize("fault", ["missing", "extra"])
def test_nullable_stop_claim_retains_exact_receipt_fields(monkeypatch, fault):
    node, _, envelope = fixture(monkeypatch, "admit_coding_stop")
    receipt = node.state.admit_coding_stop(envelope["proof"])
    if fault == "missing":
        del receipt["original_invocation_id"]
    else:
        receipt["foreign"] = True
    with pytest.raises(DefinitionMismatch):
        api()._receipt("admit_coding_stop", envelope["proof"], receipt)
