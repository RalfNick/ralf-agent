"""Session4 retirement recovery keeps original SDK ancestry and one seal wake."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from relf_agent import Scope
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_deployment_submissions import recover_retirement
from relf_agent.types import digest
from tests.test_temporal_session_deployment_control import positive_observation


class Client:
    def __init__(self, original):
        self.original, self.wakes = original, []

    def __getattr__(self, name):
        return getattr(self.original, name)

    def get_workflow_handle(self, *args, **kwargs):
        return Handle(self, self.original.get_workflow_handle(*args, **kwargs))


class Handle:
    def __init__(self, client, original):
        self.client, self.original = client, original

    def __getattr__(self, name):
        return getattr(self.original, name)

    async def execute_update(self, name, value, **options):
        assert name == "deployment_seal", "Recovery may only wake the original seal"
        self.client.wakes.append((copy.deepcopy(value), options["id"]))
        return copy.deepcopy(self.client.business_closure["seal"])


def fixture():
    validation, original = positive_observation()
    original.business_retirement = None
    i = validation.intent
    record = original.registry_state.submissions[digest([i["scope"], i["run_command_id"]])]
    original.original_submission_receipt = copy.deepcopy(record["run_receipt"])
    client = Client(original)
    engine = SimpleNamespace(
        client=client,
        scope=Scope(**i["scope"]),
        namespace=i["namespace"]["name"],
        release=copy.deepcopy(i["submission"]["manifest"]),
        _closed=False,
        task_queue=i["submission"]["task_queue"],
        activity_timeout=i["submission"]["activity_timeout"],
    )
    return engine, original, copy.deepcopy(original.business_closure)


def test_session4_sealed_retirement_recovery_wakes_original_child_only():
    engine, original, closure = fixture()
    result = asyncio.run(recover_retirement(engine, original.intent["run_id"], closure))
    assert result == closure["seal"]
    assert len(engine.client.wakes) == 1
    assert engine.client.wakes[0][0] == {"scope": original.intent["scope"], "children": []}
    assert "deployment_session_command" in original.events
    assert "reserve_session_root" not in original.events


@pytest.mark.parametrize("changed", ["parent", "intent"])
def test_session4_recovery_rejects_changed_original_identity_before_seal(changed):
    engine, original, closure = fixture()
    if changed == "parent":
        original.business_parent_epoch = "replaced-coordinator"
    else:
        original.intent["submission"]["request"]["input"] = "forged-original"
        original.intent["intent_digest"] = digest(
            {k: v for k, v in original.intent.items() if k != "intent_digest"}
        )
    with pytest.raises(DefinitionMismatch):
        asyncio.run(recover_retirement(engine, closure["deployment"]["run_id"], closure))
    assert engine.client.wakes == []
