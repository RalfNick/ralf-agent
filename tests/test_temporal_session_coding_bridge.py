"""Original Registry4 routing for existing native6/composition7 Coding."""

import asyncio
import copy

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_deployment_coding_bridge import _ReadOnlyClient, registry
from ralf_agent.types import digest
from tests.test_temporal_deployment_coding_bridge import MANIFEST, POLICY, SCOPE, Client


def manifest(version=4):
    value = copy.deepcopy(MANIFEST)
    value["deployment_admission_protocol"]["version"] = version
    if version == 4:
        value.update(session_protocol=1, session_deployment_protocol=1)
    return value


@pytest.mark.parametrize(("publication", "configuration"), [(4, 4), (3, 4)])
def test_original_coding_registry_accepts_actual_configuration4(publication, configuration):
    async def run():
        client = Client()
        client.version = configuration
        selected = manifest(publication)
        handle = registry(client, SCOPE, selected)
        result = await handle.query(
            "view",
            {
                "scope": SCOPE,
                "kind": "coding_composition_candidates",
                "manifest_digest": digest(selected),
            },
        )
        assert result == [client.candidate]
        assert handle.configuration_version == 4
        assert all(call[4]["admission_policy"] == POLICY for call in client.calls)
        assert client.starts == []

    asyncio.run(run())


def test_session_coding_cannot_adopt_registry3_or_ordinary4():
    async def run():
        client = Client()
        handle = registry(client, SCOPE, manifest())
        with pytest.raises(DefinitionMismatch):
            await handle.query(
                "view",
                {
                    "scope": SCOPE,
                    "kind": "coding_composition_candidates",
                    "manifest_digest": digest(manifest()),
                },
            )
        ordinary = manifest()
        ordinary.pop("coding_execution_protocol")
        with pytest.raises(DefinitionMismatch):
            registry(client, SCOPE, ordinary)
        assert not any(call[0] == "update" for call in client.calls)

    asyncio.run(run())


def test_session_coding_unused_close_starts_only_registry4_on_original_queue():
    async def run():
        client = Client()
        client.missing_registry = True
        handle = registry(client, SCOPE, manifest())
        await handle._initialize_owned_close("original-queue")
        assert len(client.starts) == 1
        _, request, options = client.starts[0]
        assert request["deployment_admission"]["version"] == 4
        assert options["task_queue"] == "original-queue"
        assert handle.configuration_version == 4

    asyncio.run(run())


def test_read_only_session_origin_validation_can_read_original_history_but_never_update():
    class Handle:
        def fetch_history_events(self, *, page_size):
            assert page_size == 1
            return iter(["original-start"])

        async def execute_update(self, *args, **kwargs):
            raise AssertionError("Read-only verification must not update History")

    class Client:
        data_converter, workflow_service = object(), object()

        def get_workflow_handle(self, identity, *, run_id):
            assert (identity, run_id) == ("coordinator", "original-epoch")
            return Handle()

    async def run():
        original = Client()
        readonly = _ReadOnlyClient(original)
        handle = readonly.get_workflow_handle("coordinator", run_id="original-epoch")
        assert list(handle.fetch_history_events(page_size=1)) == ["original-start"]
        assert readonly.data_converter is original.data_converter
        assert readonly.workflow_service is original.workflow_service
        with pytest.raises(DefinitionMismatch):
            await handle.execute_update("replace", {})

    asyncio.run(run())
