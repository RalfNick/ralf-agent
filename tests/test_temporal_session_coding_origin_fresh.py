"""Each Coding fresh read set ends with original Session verification."""

import asyncio

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_coding_authority import TemporalCodingAuthority
from ralf_agent.temporal_deployment_coding_validation import CodingValidation
from ralf_agent.types import digest
from tests.test_temporal_session_coding_projection import sdk_session_environment


def test_each_readset_performs_one_terminal_origin_read_without_caching(monkeypatch):
    runtime, client, request, info = sdk_session_environment(monkeypatch)
    validator = CodingValidation(runtime, client, request, info)

    async def run():
        await validator.validate()  # Original full bootstrap remains independent.
        for operation in (validator.validate, validator.permission, validator.validate):
            before = client.origin_reads
            await operation()
            assert client.origin_reads == before + 1
        assert client.session_root_reads == 1

    asyncio.run(run())


@pytest.mark.parametrize("change", ["reset", "namespace", "identity", "source"])
def test_changes_during_original_compact_reads_never_return_permission(monkeypatch, change):
    runtime, client, request, info = sdk_session_environment(monkeypatch)
    validator = CodingValidation(runtime, client, request, info)
    permitted = []

    async def mutate(identity):
        if change == "reset":
            client.session_reset = True
        elif change == "namespace":
            client.namespace_uuid = "22222222-2222-4222-8222-222222222222"
        elif change == "identity":
            client.descriptions["root"].raw_info.first_run_id = "replacement"
        else:
            validator._request["changed_original_request"] = True

    async def run():
        assert await validator.permission() is True
        client.read_hook = mutate
        with pytest.raises(DefinitionMismatch):
            permitted.append(await validator.permission())
        assert not permitted

    asyncio.run(run())


@pytest.mark.parametrize("update", [False, True])
def test_actual_history_query_and_update_keep_fresh_validation_on_both_sides(monkeypatch, update):
    runtime, client, request, info = sdk_session_environment(monkeypatch)
    request.update(action_id="original-action", release_digest=digest(request["runtime_manifest"]))
    native = {"release_digest": request["release_digest"]}
    native["request_digest"] = digest(native)
    request["coding_request"] = native
    validator = CodingValidation(runtime, client, request, info)
    boundaries = []

    async def query(name, proof):
        boundaries.append(client.origin_reads)
        return {"request": native, "runner": {}, "state": {}, "cancelled": False}

    async def write(name, proof):
        boundaries.append(client.origin_reads)
        return {"action_id": request["action_id"], "recorded": True}

    authority = TemporalCodingAuthority(
        request=request,
        invocation_id="original",
        query=query,
        update=write,
        validate=validator.validate,
    )

    async def run():
        await validator.validate()
        before = client.origin_reads
        if update:
            assert await authority.adopt("error", {"code": "original-evidence"}) is None
        else:
            assert await authority.cancelled() is False
        assert boundaries == [before + 1]
        assert client.origin_reads == before + 2

    asyncio.run(run())


def test_publication_three_without_session_keeps_original_compact_reads(monkeypatch):
    from ralf_agent import temporal_session_deployment_verification as verification
    from tests.test_temporal_deployment_coding_validation import environment

    runtime, client, request, info, bootstrap_reads = environment(monkeypatch, depth=1)

    async def no_session(*args):
        raise AssertionError("Publication three must not query a Session")

    monkeypatch.setattr(verification, "validate_session_origin", no_session)
    validator = CodingValidation(runtime, client, request, info)

    async def run():
        await validator.validate()
        before = len(bootstrap_reads)
        client.calls.clear()
        assert await validator.permission() is True
        assert len(bootstrap_reads) == before
        queries = [call for call in client.calls if call[0] == "query"]
        assert len(queries) == 3
        assert all(call[3]["kind"] == "deployment_coding_validation" for call in queries)

    asyncio.run(run())
