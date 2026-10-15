"""Selected deployment control reads reuse only the adjacent fresh validation."""

import asyncio
import copy

import pytest

from ralf_agent.codex_protocol import CodexCodingProtocol, CodexControlProtocol
from ralf_agent.codex_runner import CodexCodingRunner, RunnerOutcomeUnknown
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal_coding_authority import TemporalCodingAuthority
from ralf_agent.types import digest
from tests.test_temporal_coding_authority import setup


def fixture(monkeypatch, *, version=3, cancelled=False, release_digest=None):
    _, request = setup()
    request["runtime_manifest"] = {"deployment_admission_protocol": {"version": version}}
    request["release_digest"] = release_digest or digest(request["runtime_manifest"])
    native = request["coding_request"]
    native["release_digest"] = request["release_digest"]
    native["request_digest"] = digest({k: v for k, v in native.items() if k != "request_digest"})
    calls = []
    query_hook = None

    async def validate():
        calls.append("validate")

    async def query(name, proof):
        calls.append("query")
        if query_hook is not None:
            query_hook()
        await asyncio.sleep(0)
        return {"request": copy.deepcopy(native), "runner": {}, "state": {}, "cancelled": cancelled}

    async def update(*args):
        raise AssertionError("Control preflight cannot grant or update business")

    authority = TemporalCodingAuthority(
        request=request, invocation_id="original", query=query, update=update, validate=validate
    )

    class Transport:
        async def request(self, method, params):
            calls.append("native")
            assert method == "configRequirements/read" and params is None
            return {"requirements": None}

    runner = CodexCodingRunner.__new__(CodexCodingRunner)
    monkeypatch.setattr(CodexCodingRunner, "_check_root", lambda self: None)
    runner._protocol = CodexCodingProtocol()
    owner = {
        "history": True,
        "authority": authority,
        "control": CodexControlProtocol(),
        "transport": Transport(),
    }
    original = CodexControlProtocol.validate_request

    def schema(self, method, params):
        calls.append("schema")
        return original(self, method, params)

    monkeypatch.setattr(CodexControlProtocol, "validate_request", schema)

    def hook(value):
        nonlocal query_hook
        query_hook = value

    return runner, owner, calls, hook


def test_selected_control_has_only_fresh_pre_query_post_before_native(monkeypatch):
    runner, owner, calls, _ = fixture(monkeypatch)
    assert asyncio.run(runner._request(owner, "configRequirements/read", None, control=True)) == {
        "requirements": None
    }
    assert calls == ["schema", "validate", "query", "validate", "native"]


def test_selected_control_preserves_original_effective_release_digest(monkeypatch):
    runner, owner, calls, _ = fixture(monkeypatch, release_digest="original-effective-release")
    assert owner["authority"]._request["release_digest"] != digest(
        owner["authority"]._request["runtime_manifest"]
    )
    asyncio.run(runner._request(owner, "configRequirements/read", None, control=True))
    assert calls == ["schema", "validate", "query", "validate", "native"]


@pytest.mark.parametrize("version", [1, 2, None, True, "3"])
def test_legacy_control_keeps_original_order_and_three_validations(monkeypatch, version):
    runner, owner, calls, _ = fixture(monkeypatch, version=version)
    owner["deployment_control"] = True  # An owner flag cannot opt into the fast path.
    asyncio.run(runner._request(owner, "configRequirements/read", None, control=True))
    assert calls == ["validate", "query", "validate", "schema", "validate", "native"]


def test_selected_control_schema_refuses_before_any_rpc(monkeypatch):
    runner, owner, calls, _ = fixture(monkeypatch)
    with pytest.raises(ValidationError):
        asyncio.run(runner._request(owner, "configRequirements/read", {"private": 1}, control=True))
    assert calls == ["schema"]


def test_selected_control_cancellation_refuses_before_native(monkeypatch):
    runner, owner, calls, _ = fixture(monkeypatch, cancelled=True)
    with pytest.raises(RunnerOutcomeUnknown):
        asyncio.run(runner._request(owner, "configRequirements/read", None, control=True))
    assert calls == ["schema", "validate", "query", "validate"]


@pytest.mark.parametrize("change", ["request", "proof", "native"])
def test_selected_control_requires_original_request_proof_digest(monkeypatch, change):
    runner, owner, calls, _ = fixture(monkeypatch)
    authority = owner["authority"]
    if change == "request":
        authority._request["foreign"] = True
    elif change == "proof":
        authority._proof["execution_epoch"] = "foreign"
    else:
        authority._request["coding_request"]["release_digest"] = "foreign"
        authority._proof["request_digest"] = digest(authority._request)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(runner._request(owner, "configRequirements/read", None, control=True))
    assert "native" not in calls


@pytest.mark.parametrize("name", ["_state", "_call", "_check_pins"])
@pytest.mark.parametrize("replace_class", [False, True])
def test_selected_control_nested_source_replacement_cannot_skip_fresh_validation(
    monkeypatch, name, replace_class
):
    runner, owner, calls, _ = fixture(monkeypatch)

    async def replaced(*args):
        return {"cancelled": False}

    replacement = (lambda *args: None) if name == "_check_pins" else replaced
    monkeypatch.setattr(
        TemporalCodingAuthority if replace_class else owner["authority"], name, replacement
    )
    with pytest.raises(DefinitionMismatch):
        asyncio.run(runner._request(owner, "configRequirements/read", None, control=True))
    assert "native" not in calls


@pytest.mark.parametrize("change", ["owner", "request", "method", "callback"])
def test_selected_control_rechecks_identity_after_state_query(monkeypatch, change):
    runner, owner, calls, hook = fixture(monkeypatch)
    authority = owner["authority"]

    def replace():
        if change == "owner":
            owner["authority"] = object()
        elif change == "request":
            authority._request = {**authority._request, "foreign": True}
        elif change == "method":
            authority.cancelled = lambda: False
        else:

            async def replaced():
                pass

            authority._validate = replaced

    hook(replace)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(runner._request(owner, "configRequirements/read", None, control=True))
    assert "native" not in calls


@pytest.mark.parametrize("name", ["cancelled", "_state", "_call", "_check_pins"])
@pytest.mark.parametrize("during_query", [False, True])
def test_selected_control_rejects_in_place_helper_code_changes_before_native(
    monkeypatch, name, during_query
):
    runner, owner, calls, hook = fixture(monkeypatch)

    async def replaced(self, *args, **kwargs):
        return {"cancelled": False}

    def replaced_pins(self):
        return None

    def change():
        function = getattr(TemporalCodingAuthority, name)
        monkeypatch.setattr(
            function, "__code__", (replaced_pins if name == "_check_pins" else replaced).__code__
        )

    if during_query:
        hook(change)
    else:
        change()
    with pytest.raises(DefinitionMismatch):
        asyncio.run(runner._request(owner, "configRequirements/read", None, control=True))
    assert "native" not in calls


@pytest.mark.parametrize(
    "attribute,value", [("__defaults__", (None,)), ("__kwdefaults__", {"update": True})]
)
def test_selected_control_rejects_changed_helper_defaults(monkeypatch, attribute, value):
    runner, owner, calls, _ = fixture(monkeypatch)
    monkeypatch.setattr(TemporalCodingAuthority._call, attribute, value)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(runner._request(owner, "configRequirements/read", None, control=True))
    assert "native" not in calls


def test_local_control_keeps_original_path(monkeypatch):
    runner, owner, calls, _ = fixture(monkeypatch)

    class Local:
        def cancelled(self):
            calls.append("local-cancelled")
            return False

    owner.update(history=False, authority=Local())
    asyncio.run(runner._request(owner, "configRequirements/read", None, control=True))
    assert calls == ["local-cancelled", "schema", "native"]


def test_selected_business_reuses_adjacent_fresh_registration_walk(monkeypatch):
    runner, owner, calls, _ = fixture(monkeypatch)

    class Sent(Exception):
        pass

    async def request(method, params):
        calls.append("native-business")
        raise Sent

    owner["transport"].request = request
    with pytest.raises(Sent):
        asyncio.run(
            runner._request(owner, "thread/read", {"threadId": "original", "includeTurns": True})
        )
    assert calls == ["validate", "query", "validate", "native-business"]
