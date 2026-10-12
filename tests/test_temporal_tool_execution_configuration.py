"""Explicit Temporal Tool owner configuration is preflighted and owned once."""

import asyncio

import pytest

import ralf_agent as r
from ralf_agent.errors import RalfError


def profile(config):
    return r.TemporalProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "tool_execution": {"adapter": "tracked", "config": config},
        },
    )


def test_default_declaration_and_original_owned_lifecycle(tmp_path):
    async def run():
        assembly = await r.TemporalRuntimeBuilder().abuild(
            profile({"version": "1"}), data_path=tmp_path / "data"
        )
        owner = assembly._runtime.tool_execution
        assert owner.identity["max_calls"] == 8
        assert assembly.release["tool_execution_protocol"]["version"] == 1
        await assembly.aclose()
        with pytest.raises(RalfError):
            await owner.execute(lambda: None, proof={})

    asyncio.run(run())


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"version": ""},
        {"version": True},
        {"version": "1", "max_calls": 0},
        {"version": "1", "max_calls": True},
        {"version": "1", "unknown": True},
    ],
)
def test_invalid_preflight_has_no_data_allocation(tmp_path, config):
    async def run():
        with pytest.raises(RalfError):
            await r.TemporalRuntimeBuilder().abuild(profile(config), data_path=tmp_path / "data")

    asyncio.run(run())
    assert list(tmp_path.iterdir()) == []


def test_local_profile_refuses_temporal_only_owner():
    with pytest.raises(RalfError):
        r.RuntimeProfile(
            "app",
            "1",
            {"default": {"adapter": "offline-echo"}},
            {
                "tool_execution": {"adapter": "tracked", "config": {"version": "1"}},
            },
        )


def test_borrowed_direct_owner_is_waited_but_not_closed():
    from ralf_agent.temporal_activities import TemporalRuntime

    async def run():
        from .test_temporal_engine import Provider

        owner = r.ToolExecutionOwner(version="1")
        runtime = TemporalRuntime(
            providers={"default": Provider()}, tools=r.ToolRegistry(), tool_execution=owner
        )
        await runtime.close_context_execution()
        assert owner._closing is False
        await owner.aclose()

    asyncio.run(run())
