import asyncio

import pytest

from ralf_agent import temporal_deployment_protocol as deployment
from ralf_agent import temporal_tool_execution as tools
from ralf_agent.types import canonical
from tests.test_temporal_deployment_publication_cost import construct, count, profile_call


@pytest.mark.parametrize("context_reads", [False, True])
@pytest.mark.parametrize("composition", [False, True])
def test_owned_joint_release_keeps_one_complete_deployment_gate(
    tmp_path, monkeypatch, context_reads, composition
):
    async def run():
        runtime, context = await construct(
            tmp_path, monkeypatch, composition=composition, context_reads=context_reads
        )
        try:
            expected = runtime.manifest
            value, profile = profile_call(runtime._current_manifest)
            assert canonical(value) == canonical(expected)
            assert count(profile, deployment.validate_protocol) == 1
            assert count(profile, tools.publish) == 0
        finally:
            await context.cleanup_async()

    asyncio.run(run())
