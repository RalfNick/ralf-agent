"""Registry Activity verifies original SDK ancestry and reads pure Action evidence."""

import asyncio
from types import SimpleNamespace

import pytest

from ralf_agent.errors import RalfError
from ralf_agent.types import digest
from tests.test_temporal_deployment_control_release import environment


@pytest.mark.parametrize("root_target", [False, True])
@pytest.mark.parametrize("fault", [None, "action", "epoch-after-query", "proof", "scope"])
def test_registry_manual_verification_pins_root_or_descendant_without_updates(
    monkeypatch, root_target, fault
):
    from ralf_agent import temporal_deployment_release as release

    async def run():
        runtime, client, value, info, binding = environment(monkeypatch, nested=True)
        if root_target:
            value["target"] = value["root"]["run_id"]
            value["target_execution_epoch"] = value["root"]["execution_epoch"]
            binding.update(
                version=2,
                target=value["target"],
                target_execution_epoch=value["target_execution_epoch"],
            )
        payload = {
            "kind": "reconcile",
            "scope": value["scope"],
            "action_id": "original-tool",
            "query": False,
            "result": {"committed": True},
        }
        value.update(mode="manual_control", payload=payload)
        body = {
            "version": 1,
            "scope": value["scope"],
            "run_id": value["target"],
            "execution_epoch": value["target_execution_epoch"],
            "manifest_digest": digest(value["manifest"]),
            "action_id": payload["action_id"],
            "action_digest": "a" * 64,
            "tool_request_digest": "b" * 64,
            "call_digest": "c" * 64,
        }
        if fault == "action":
            body["action_id"] = "foreign-action"
        if fault == "scope":
            body["scope"] = {**body["scope"], "principal": "foreign"}
        action = {**body, "proof_digest": digest(body)}
        if fault == "proof":
            action["proof_digest"] = "d" * 64
        original_get = client.get_workflow_handle
        queries = []

        def handle(identity, **kwargs):
            original = original_get(identity, **kwargs)

            async def query(name, request):
                if request["kind"] == "deployment_manual_recovery":
                    assert (
                        identity == value["target"]
                        and kwargs["run_id"] == value["target_execution_epoch"]
                    )
                    assert request["payload"] == payload
                    queries.append(request)
                    if fault == "epoch-after-query":
                        client.descriptions[identity].raw_info.first_run_id = "pre-reset"
                    return action
                return await original.query(name, request)

            return SimpleNamespace(query=query, describe=original.describe)

        client.get_workflow_handle = handle
        if fault:
            with pytest.raises(RalfError):
                await release.execute(runtime, client, value, info)
        else:
            assert await release.execute(runtime, client, value, info) == {
                "binding": binding,
                "action": action,
            }
        assert len(queries) == 1
        assert not client.updates and not client.retirements

    asyncio.run(run())
