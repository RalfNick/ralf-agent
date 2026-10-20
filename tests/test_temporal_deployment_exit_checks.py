"""One full release reconstruction at the final synchronous Activity boundary."""

import asyncio
import copy
from functools import partial

import pytest

from tests import test_temporal_deployment_execution as fixture


@pytest.mark.parametrize("operation", ["admit", "control", "wrapper", "release"])
def test_final_sdk_exit_checks_expected_release_without_duplicate_reconstruction(
    monkeypatch, operation
):
    from temporalio import activity

    from ralf_agent import temporal_deployment_execution as execution
    from ralf_agent import temporal_deployment_release as release
    from tests.test_temporal_deployment_release import environment

    events = []
    original = fixture.Runtime.validate_release

    def validate(runtime, expected=None):
        result = original(runtime, expected)
        events.append(("release", copy.deepcopy(expected)))
        return result

    monkeypatch.setattr(fixture.Runtime, "validate_release", validate)

    async def run():
        if operation == "release":
            runtime, client, state, _, info = environment(monkeypatch)
            value = {
                "mode": "release",
                "scope": state.scope,
                "run_id": state.run_id,
                "execution_epoch": state.epoch,
            }
            call = partial(release.execute, runtime, client, value, info)
        elif operation == "admit":
            runtime, client, value, info = fixture.setup()
            call = partial(execution.admit, runtime, client, value, info)
        else:
            runtime, client, value, info = await fixture.admitted_setup()
            if operation == "control":
                child, child_info, edge = fixture.child_setup(runtime, client, value)
                receipt = await execution.admit(runtime, client, child, child_info)
                client.proofs[child["run_id"]] = fixture.sealed(
                    {**client.proofs[child["run_id"]], "admission_receipt": receipt}
                )
                value = {
                    "mode": "register",
                    "scope": fixture.SCOPE,
                    "parent_id": value["run_id"],
                    "child": edge,
                    "runtime_manifest": runtime.manifest,
                }
                call = partial(execution.control, runtime, client, value, info)
            else:
                monkeypatch.setattr(activity, "info", lambda: info)

                @activity.defn(name="test.original-exit")
                async def body(request: dict) -> dict:
                    return {"done": True}

                wrapped = execution.wrap_activities(runtime, client, [body])[0]
                call = partial(wrapped, {"scope": fixture.SCOPE})
        namespace = client.workflow_service.describe_namespace

        async def observed(request):
            result = await namespace(request)
            events.append(("sdk", None))
            return result

        client.workflow_service.describe_namespace = observed
        events.clear()
        result = await call()
        assert result
        last_sdk = max(i for i, event in enumerate(events) if event[0] == "sdk")
        # Reconstructing the complete release twice here has no intervening I/O;
        # the final check must still compare the original expected Manifest.
        assert events[last_sdk + 1 :] == [("release", runtime.manifest)]

    asyncio.run(run())
