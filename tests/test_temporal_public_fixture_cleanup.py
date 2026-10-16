"""Do not hide the primary HTTP failure when no original Registry ever started."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from tests import test_temporal_deployment_public_service as fixtures


@pytest.mark.parametrize("cleanup_fault", [False, True])
def test_public_fixture_preserves_primary_and_handles_definitive_registry_absence(
    tmp_path, monkeypatch, cleanup_fault
):
    from temporalio.service import RPCError, RPCStatusCode

    class OriginalFailure(Exception):
        pass

    class CleanupFailure(Exception):
        pass

    class Handle:
        async def fetch_history(self):
            raise RPCError("owned Registry never started", RPCStatusCode.NOT_FOUND, b"")

    async def clients():
        client = SimpleNamespace(namespace="default", get_workflow_handle=lambda *a, **k: Handle())
        return [client], {"name": "default", "id": "11111111-1111-1111-1111-111111111111"}

    monkeypatch.setattr(fixtures, "_clients", clients)
    if cleanup_fault:

        async def failed(self):
            raise CleanupFailure("cleanup also failed")

        monkeypatch.setattr(fixtures.PublicSystem, "cleanup", failed)
    captured = []

    async def run():
        async with fixtures.public_system(tmp_path) as system:
            captured.append(system)
            raise OriginalFailure("HTTP startup failed first")

    if cleanup_fault:
        with pytest.raises(BaseExceptionGroup) as result:
            asyncio.run(run())
        assert [type(exc) for exc in result.value.exceptions] == [OriginalFailure, CleanupFailure]
    else:
        with pytest.raises(OriginalFailure):
            asyncio.run(run())
        assert all(engine._closed for engine in captured[0].engines)
        result = json.loads((tmp_path / "cleanup.json").read_text())
        assert result["registry_absent"] is True and result["registry_terminated"] is False
