"""The mechanical peer must implement the namespace filters used by the real CLI."""

import asyncio
import json
import os

import pytest

from ralf_agent.codex_environment import DockerCodingEnvironment
from tests.test_temporal_parallel_coding_service import parallel_peer


@pytest.mark.skipif(os.name != "posix", reason="POSIX native peer")
def test_parallel_peer_preserves_distinct_namespaces(tmp_path):
    cli = parallel_peer(tmp_path)
    environments = []
    for name in ("first", "second"):
        root = tmp_path / name
        root.mkdir(mode=0o700)
        environments.append(
            DockerCodingEnvironment(
                root,
                name,
                docker_executable=str(cli),
                docker_host="unix:///fixture/docker.sock",
                retire_on_stop=True,
            )
        )

    async def run():
        prepared = [await env.prepare() for env in environments]
        assert len({value["container_id"] for value in prepared}) == 2
        assert json.loads((tmp_path / "docker.json").read_text())["creates"] == 2
        for env in environments:
            assert (await env.stop())["fenced"] is True
            await env.aclose()
        assert json.loads((tmp_path / "docker.json").read_text())["containers"] == {}

    asyncio.run(run())
