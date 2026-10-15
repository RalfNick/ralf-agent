"""Session Coding sends reuse adjacent fresh authority, without skipping it."""

import asyncio
import copy

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_coding_authority import TemporalCodingAuthority
from ralf_agent.types import digest
from tests.test_codex_deployment_business_validation_cost import METHODS, Sent, business, params
from tests.test_codex_deployment_control_validation_cost import fixture
from tests.test_temporal_deployment_session_registry import deployment_intent
from tests.test_temporal_session_deployment_coding_configuration import coding_session_manifest


def session_publication(owner, *, composition=False, ordinary=False):
    manifest = coding_session_manifest(composition=composition)
    if ordinary:
        manifest = deployment_intent()["binding"]["manifest"]
    authority = owner["authority"]
    authority._request["runtime_manifest"] = manifest
    # Effective release digests need not equal the full Runtime manifest digest.
    authority._proof["request_digest"] = digest(authority._request)


@pytest.mark.parametrize("composition", [False, True])
@pytest.mark.parametrize("method", ["configRequirements/read", *METHODS])
def test_session_coding_reuses_only_adjacent_pre_and_post_query_validation(
    monkeypatch, composition, method
):
    control = method == "configRequirements/read"
    runner, owner, calls, _ = fixture(monkeypatch) if control else business(monkeypatch)
    session_publication(owner, composition=composition)
    if control:
        assert asyncio.run(runner._request(owner, method, None, control=True)) == {
            "requirements": None
        }
        assert calls == ["schema", "validate", "query", "validate", "native"]
    else:
        with pytest.raises(Sent):
            asyncio.run(runner._request(owner, method, params(method)))
        assert calls == ["business-schema", "validate", "query", "validate", "business-send"]


def test_ordinary_session_publication_cannot_select_coding_adjacency(monkeypatch):
    runner, owner, calls, _ = fixture(monkeypatch)
    session_publication(owner, ordinary=True)
    asyncio.run(runner._request(owner, "configRequirements/read", None, control=True))
    assert calls == ["validate", "query", "validate", "schema", "validate", "native"]


@pytest.mark.parametrize("change", ["owner", "proof", "callback"])
def test_session_coding_query_drift_still_refuses_native(monkeypatch, change):
    runner, owner, calls, hook = fixture(monkeypatch)
    session_publication(owner)
    authority = owner["authority"]

    def mutate():
        if change == "owner":
            owner["authority"] = object()
        elif change == "proof":
            authority._proof["execution_epoch"] = "foreign"
        else:
            authority._validate = lambda: None

    hook(mutate)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(runner._request(owner, "configRequirements/read", None, control=True))
    assert "native" not in calls


@pytest.mark.parametrize("during_query", [False, True])
def test_session_coding_adjacent_query_retains_fresh_original_origin_validation(
    monkeypatch, during_query
):
    from ralf_agent.temporal_deployment_coding_validation import CodingValidation
    from tests.test_temporal_session_coding_projection import sdk_session_environment

    runtime, client, request, info = sdk_session_environment(monkeypatch)
    runner, owner, calls, _ = fixture(monkeypatch)
    native = copy.deepcopy(owner["authority"]._request["coding_request"])
    request.update(action_id="original-action", release_digest=digest(request["runtime_manifest"]))
    native["release_digest"] = request["release_digest"]
    native["request_digest"] = digest({k: v for k, v in native.items() if k != "request_digest"})
    request["coding_request"] = native
    validation = CodingValidation(runtime, client, request, info)
    reset_on_query = False

    async def query(name, proof):
        calls.append("query")
        if reset_on_query:
            client.session_reset = True
        return {"request": native, "runner": {}, "state": {}, "cancelled": False}

    async def update(*args):
        raise AssertionError("Preflight cannot grant business work")

    owner["authority"] = TemporalCodingAuthority(
        request=request,
        invocation_id="original",
        query=query,
        update=update,
        validate=validation.validate,
    )

    async def run():
        nonlocal reset_on_query
        await runner._request(owner, "configRequirements/read", None, control=True)
        assert calls == ["schema", "query", "native"]
        assert client.origin_reads >= 4
        reset_on_query = during_query
        client.session_reset = not during_query
        calls.clear()
        with pytest.raises(DefinitionMismatch):
            await runner._request(owner, "configRequirements/read", None, control=True)
        assert "native" not in calls

    asyncio.run(run())
