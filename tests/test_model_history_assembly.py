"""Public configuration selects complete history without changing old defaults."""

import asyncio

import pytest

from ralf_agent import AgentSpec, CompleteModelHistory, RuntimeBuilder, RuntimeProfile
from ralf_agent.errors import ValidationError
from ralf_agent.runtime_builder import ComponentRegistry
from ralf_agent.temporal_builder import TemporalRuntimeBuilder
from ralf_agent.temporal_profile import TemporalProfile


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("projection", [False, True])
def test_public_local_profile_runs_complete_history(tmp_path, asynchronous, projection):
    profile = RuntimeProfile(
        "history",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "model_continuation": {"adapter": "native"},
            "model_history": {
                "adapter": "complete",
                "config": {"allow_tool_result_projection": projection},
            },
        },
    )

    async def run():
        instance = await RuntimeBuilder().abuild(profile, tmp_path / "runs.sqlite")
        try:
            h = instance.submit(AgentSpec("a", "Answer"), "question", command_id="s")
            assert (await instance.drive(h.run_id)).state == "succeeded"
            manifest = instance.diagnostics(h.run_id).manifest
            assert manifest["kernel"] == "local-6"
            assert (
                manifest["model_history"]["identity"]["allow_tool_result_projection"] is projection
            )
            assert len(instance.store.run(h.run_id)["messages"]) == 3
        finally:
            await instance.aclose()

    if asynchronous:
        asyncio.run(run())
    else:
        with RuntimeBuilder().build(profile, tmp_path / "runs.sqlite") as instance:
            h = instance.submit(AgentSpec("a", "Answer"), "question", command_id="s")
            assert asyncio.run(instance.drive(h.run_id)).state == "succeeded"
            assert instance.diagnostics(h.run_id).manifest["model_history_protocol"] == 1


@pytest.mark.parametrize(
    "components",
    [
        {"model_history": {"adapter": "complete"}},
        {
            "model_continuation": {"adapter": "native"},
            "model_history": {"adapter": "complete", "config": {"unknown": True}},
        },
        {
            "model_continuation": {"adapter": "native"},
            "model_history": {"adapter": "complete", "config": {"allow_tool_result_projection": 1}},
        },
    ],
)
def test_invalid_history_configuration_refuses_before_store_creation(tmp_path, components):
    profile = RuntimeProfile("p", "1", {"default": {"adapter": "offline-echo"}}, components)
    path = tmp_path / "not-created.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile, path)
    assert not path.exists()


def test_registry_can_replace_history_policy_and_pins_its_identity(tmp_path):
    class BusinessHistory(CompleteModelHistory):
        @property
        def identity(self):
            return {**super().identity, "kind": "business-history", "business_version": "4"}

    registry = ComponentRegistry()
    registry.register("model_history", "business", lambda c, ctx: BusinessHistory())
    profile = RuntimeProfile(
        "p",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"model_continuation": {"adapter": "native"}, "model_history": {"adapter": "business"}},
    )
    with RuntimeBuilder(registry).build(profile, tmp_path / "runs.sqlite") as instance:
        h = instance.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(instance.drive(h.run_id)).state == "succeeded"
        assert (
            instance.diagnostics(h.run_id).manifest["model_history"]["identity"]["business_version"]
            == "4"
        )


def test_temporal_profile_requires_continuation_and_builds_joint_seven(tmp_path):
    components = {"model_history": {"adapter": "complete"}}
    with pytest.raises(ValidationError):
        TemporalProfile("p", "1", {"default": {"adapter": "offline-echo"}}, components)

    async def run():
        profile = TemporalProfile(
            "p",
            "1",
            {"default": {"adapter": "offline-echo"}},
            components,
            execution={"model_continuation": True},
        )
        assembly = await TemporalRuntimeBuilder().abuild(profile, data_path=tmp_path / "data")
        try:
            assert assembly.release["binding_protocol"] == 7
            assert assembly.release["model_history_protocol"] == 1
            assert (
                assembly.release["model_history"]["identity"]["allow_tool_result_projection"]
                is False
            )
        finally:
            await assembly.aclose()

    asyncio.run(run())
