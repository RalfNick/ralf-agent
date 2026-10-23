"""Registry owns verifier dispatch and commits controls only after rechecking."""

import asyncio
import copy
from datetime import timedelta

import pytest

pytest.importorskip("temporalio")
from temporalio.exceptions import ApplicationError

from relf_agent.temporal_workflow import TemporalCommandRegistryWorkflow, workflow
from tests.test_temporal_deployment_descendant_control_state import original, query, retire
from tests.test_temporal_deployment_registry_epoch import sdk_info


@pytest.mark.parametrize("race", ["none", "retire", "reset"])
def test_registry_verifies_on_first_queue_then_atomically_rechecks(race, monkeypatch):
    async def run():
        state, root_request, root, request, verification = original()
        info = sdk_info()
        monkeypatch.setattr(workflow, "info", lambda: info)
        authority = TemporalCommandRegistryWorkflow(
            {
                "deployment_admission": {
                    "version": 2,
                    "policy": state.deployment.policy,
                    "namespace": state.deployment.namespace,
                }
            }
        )
        authority.commands = state
        envelope = root_request["root_admission"]["submission"]
        calls = []

        async def verify(name, payload, **options):
            calls.append((name, copy.deepcopy(payload), options))
            assert name == "ralf.temporal.deployment-release.v2"
            assert payload == {
                "mode": "control",
                "scope": request["scope"],
                "root": root,
                "target": request["target"],
                "target_execution_epoch": verification["target_execution_epoch"],
                "manifest": envelope["manifest"],
                "registry_execution_epoch": "first-sdk-epoch",
            }
            assert options["task_queue"] == envelope["task_queue"]
            assert options["start_to_close_timeout"] == timedelta(
                seconds=envelope["activity_timeout"]
            )
            assert options["schedule_to_close_timeout"] == timedelta(
                seconds=envelope["activity_timeout"] * 2 + 5
            )
            assert options["retry_policy"].maximum_attempts == 1
            if race == "retire":
                retire(state, root)
            elif race == "reset":
                info.run_id = "reset-sdk-epoch"
            return {"ok": True, "result": verification}

        monkeypatch.setattr(workflow, "execute_activity", verify)
        if race != "none":
            with pytest.raises(ApplicationError):
                await authority.reserve(request)
            assert len(calls) == 1
            assert state.deployment.control_bindings == {}
            assert len(state.deployment.commands) == 1
        else:
            result = await authority.reserve(request)
            assert result["control_binding"] == verification and len(calls) == 1
            assert authority.view(query(request)) == result
            retire(state, root)
            assert await authority.reserve(request) == result
            assert len(calls) == 1 and len(state.deployment.commands) == 2

    asyncio.run(run())
