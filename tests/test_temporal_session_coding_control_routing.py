"""Session publication4 retains the existing Coding parent control path."""

import asyncio

import pytest

from tests.test_temporal_deployment_coding_registry import coding_request
from tests.test_temporal_deployment_session_registry import deployment_intent
from tests.test_temporal_session_deployment_coding_configuration import coding_session_manifest


@pytest.mark.parametrize(
    "selection,expected",
    [
        ("native4", "coding"),
        ("composition4", "coding"),
        ("ordinary4", "ordinary"),
        ("coding3", "coding"),
    ],
)
def test_original_parent_control_route_preserves_selected_coding_and_ordinary(
    monkeypatch, selection, expected
):
    from ralf_agent import temporal_control_activities as activities
    from ralf_agent import temporal_deployment_coding_bridge as coding
    from ralf_agent import temporal_deployment_execution as ordinary

    if selection in {"native4", "composition4"}:
        manifest = coding_session_manifest(composition=selection == "composition4")
    elif selection == "coding3":
        manifest = coding_request()["root_admission"]["submission"]["manifest"]
    else:
        manifest = deployment_intent()["binding"]["manifest"]
    runtime, client, info = object(), object(), object()
    request = {"runtime_manifest": manifest, "mode": "observe"}
    calls = []

    def callback(route):
        async def invoke(actual_runtime, actual_client, actual_request, actual_info):
            assert (actual_runtime, actual_client, actual_request, actual_info) == (
                runtime,
                client,
                request,
                info,
            )
            calls.append(route)
            return {"original_route": route}

        return invoke

    monkeypatch.setattr(coding, "control", callback("coding"))
    monkeypatch.setattr(ordinary, "control", callback("ordinary"))
    result = asyncio.run(activities.control(runtime, client, request, info))
    assert result == {"original_route": expected}
    assert calls == [expected]
