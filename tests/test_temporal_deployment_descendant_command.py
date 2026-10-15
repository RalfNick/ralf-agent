"""A verified public control cannot follow a target reset to another History."""

import asyncio
from dataclasses import asdict

import pytest

from ralf_agent import DeploymentAdmissionPolicy, Scope, TemporalRuntime, ToolRegistry
from tests.test_temporal_engine import Provider


@pytest.fixture(autouse=True, scope="module")
def _optional_sdk():
    pytest.importorskip("temporalio")


def test_verified_descendant_command_uses_original_epoch_after_reset(monkeypatch):
    from ralf_agent import temporal_deployment_submissions as transport
    from ralf_agent.temporal import TemporalEngine

    async def run():
        events = []
        scope = Scope("original", "caller")
        binding = {
            "version": 1,
            "scope": asdict(scope),
            "namespace": {"name": "original", "id": "11111111-1111-1111-1111-111111111111"},
            "target": "child",
            "target_execution_epoch": "original-child-epoch",
            "root_run_id": "original-root",
            "root_execution_epoch": "original-root-epoch",
        }

        class Handle:
            def __init__(self, client, epoch):
                self.client, self.epoch = client, epoch

            async def query(self, name, value):
                events.append(("observe", self.epoch))
                return {"state": "waiting_approval"}

            async def execute_update(self, name, value):
                events.append(("command", self.epoch))
                assert value["payload"] == {"kind": "cancel", "scope": asdict(scope)}
                return {
                    "command_id": value["command_id"],
                    "run_id": "child",
                    "kind": "cancel",
                    "record_state": "durably_recorded",
                    "apply_state": "applied",
                    "outcome": {},
                }

        class Client:
            namespace = "original"
            current_epoch = "original-child-epoch"

        # The SDK API uses the first positional argument as workflow_id.
        def get_handle(client, workflow_id, *, run_id=None):
            assert workflow_id == "child"
            return Handle(client, run_id or client.current_epoch)

        Client.get_workflow_handle = get_handle
        client = Client()
        runtime = TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            admission_policy=DeploymentAdmissionPolicy("controls"),
        )
        engine = TemporalEngine(
            client, task_queue="original-queue", release=runtime.orchestration_release, scope=scope
        )

        async def guard(*args):
            events.append(("verify", "original-child-epoch"))
            client.current_epoch = "reset-child-epoch"
            return binding

        async def recheck(engine, actual_client, actual_scope, namespace, policy):
            assert actual_client is client and actual_scope == asdict(scope)
            assert namespace == binding["namespace"]
            events.append(("recheck", "original-child-epoch"))

        monkeypatch.setattr(transport, "guard", guard)
        monkeypatch.setattr(transport, "_recheck", recheck)
        receipt = await engine._command("child", "cancel", "original-cancel")
        assert receipt.run_id == "child"
        assert ("command", "original-child-epoch") in events
        assert ("command", "reset-child-epoch") not in events
        assert events.index(("verify", "original-child-epoch")) < events.index(
            ("observe", "original-child-epoch")
        )
        assert events.index(("recheck", "original-child-epoch")) < events.index(
            ("command", "original-child-epoch")
        )

    asyncio.run(run())
