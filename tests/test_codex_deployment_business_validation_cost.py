"""Selected business sends retain grants and reuse only adjacent registration."""

import asyncio
from types import SimpleNamespace

import pytest

from relf_agent.codex_protocol import CodexCodingProtocol, CodexControlProtocol
from relf_agent.codex_runner import RunnerOutcomeUnknown
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.temporal_coding_authority import TemporalCodingAuthority
from tests.test_codex_deployment_control_validation_cost import fixture
from tests.test_temporal_coding_authority import setup

METHODS = ["thread/start", "turn/start", "thread/read"]


def params(method):
    if method == "thread/read":
        return {"threadId": "original", "includeTurns": True}
    value = {"cwd": "/workspace", "approvalPolicy": "never", "approvalsReviewer": "user"}
    if method == "thread/start":
        return {**value, "ephemeral": False}
    return {
        **value,
        "threadId": "original",
        "input": [{"type": "text", "text": "fix", "text_elements": []}],
    }


class Sent(Exception):
    pass


def business(monkeypatch, *, version=3, cancelled=False):
    runner, owner, calls, hook = fixture(monkeypatch, version=version, cancelled=cancelled)
    original = CodexCodingProtocol.validate_request

    def schema(self, method, payload):
        calls.append("business-schema")
        return original(self, method, payload)

    monkeypatch.setattr(CodexCodingProtocol, "validate_request", schema)

    async def send(method, payload):
        calls.append("business-send")
        raise Sent

    owner["transport"].request = send
    return runner, owner, calls, hook


@pytest.mark.parametrize("method", METHODS)
def test_three_business_methods_schema_then_fresh_query_then_send(monkeypatch, method):
    runner, owner, calls, _ = business(monkeypatch)
    with pytest.raises(Sent):
        asyncio.run(runner._request(owner, method, params(method)))
    assert calls == ["business-schema", "validate", "query", "validate", "business-send"]


@pytest.mark.parametrize("version", [1, 2, None, True, "3"])
@pytest.mark.parametrize("method", METHODS)
def test_legacy_business_registration_order_is_unchanged(monkeypatch, version, method):
    runner, owner, calls, _ = business(monkeypatch, version=version)
    with pytest.raises(Sent):
        asyncio.run(runner._request(owner, method, params(method)))
    assert calls == [
        "validate",
        "query",
        "validate",
        "business-schema",
        "validate",
        "business-send",
    ]


@pytest.mark.parametrize("method", METHODS)
def test_local_business_keeps_original_order(monkeypatch, method):
    runner, owner, calls, _ = business(monkeypatch)

    class Local:
        def cancelled(self):
            calls.append("local-cancelled")
            return False

    owner.update(history=False, authority=Local())
    with pytest.raises(Sent):
        asyncio.run(runner._request(owner, method, params(method)))
    assert calls == ["local-cancelled", "business-schema", "business-send"]


def test_non_allowlisted_business_method_keeps_original_order(monkeypatch):
    runner, owner, calls, _ = business(monkeypatch)
    with pytest.raises(Sent):
        asyncio.run(
            runner._request(owner, "turn/interrupt", {"threadId": "original", "turnId": "original"})
        )
    assert calls == [
        "validate",
        "query",
        "validate",
        "business-schema",
        "validate",
        "business-send",
    ]


@pytest.mark.parametrize("method", METHODS)
def test_business_schema_refuses_before_any_rpc_and_control_schema_cannot_carry_it(
    monkeypatch, method
):
    runner, owner, calls, _ = business(monkeypatch)
    with pytest.raises(ValidationError):
        asyncio.run(runner._request(owner, method, {"foreign": True}))
    assert calls == ["business-schema"]
    with pytest.raises(ValidationError):
        CodexControlProtocol().validate_request(method, params(method))


@pytest.mark.parametrize("method", METHODS)
def test_business_cancellation_preserves_query_both_sides_and_prevents_send(monkeypatch, method):
    runner, owner, calls, _ = business(monkeypatch, cancelled=True)
    with pytest.raises(RunnerOutcomeUnknown):
        asyncio.run(runner._request(owner, method, params(method)))
    assert calls == ["business-schema", "validate", "query", "validate"]


@pytest.mark.parametrize("method", METHODS)
def test_business_response_schema_is_still_enforced(monkeypatch, method):
    runner, owner, calls, _ = business(monkeypatch)

    async def send(name, payload):
        calls.append("business-send")
        return {}

    owner["transport"].request = send
    with pytest.raises(ValidationError):
        asyncio.run(runner._request(owner, method, params(method)))
    assert calls[-1] == "business-send"


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize(
    "change",
    ["owner", "request", "proof", "native", "callback", "helper", "helper_code", "helper_defaults"],
)
def test_business_query_drift_refuses_before_native(monkeypatch, method, change):
    runner, owner, calls, hook = business(monkeypatch)
    authority = owner["authority"]

    async def fake(*args, **kwargs):
        return False

    def mutate():
        if change == "owner":
            owner["authority"] = object()
        elif change == "request":
            authority._request["foreign"] = True
        elif change == "proof":
            authority._proof["execution_epoch"] = "foreign"
        elif change == "native":
            authority._request["coding_request"]["release_digest"] = "foreign"
        elif change == "callback":
            authority._validate = fake
        elif change == "helper":
            monkeypatch.setattr(authority, "_state", fake)
        elif change == "helper_code":
            monkeypatch.setattr(TemporalCodingAuthority.cancelled, "__code__", fake.__code__)
        else:
            monkeypatch.setattr(TemporalCodingAuthority._call, "__kwdefaults__", {"update": True})

    hook(mutate)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(runner._request(owner, method, params(method)))
    assert "business-send" not in calls


@pytest.mark.parametrize("method", ["thread/start", "turn/start"])
@pytest.mark.parametrize("barrier", ["grant", "pg_submission"])
def test_original_execute_false_barriers_still_prevent_business(monkeypatch, method, barrier):
    """Run the original execution loop with finite authority/PG/native ports."""
    runner, owner, calls, _ = business(monkeypatch)
    envelope, _ = setup()
    runner._identity, runner._timeout = {"kind": "fixture"}, 1
    environment = SimpleNamespace(identity={"original": "namespace"})
    inspected = {
        "identity": environment.identity,
        "stopped": True,
        "fenced": False,
        "generation": "original",
        "container_id": "a" * 64,
    }

    async def prepare():
        return inspected

    async def inspect():
        return inspected

    environment.prepare, environment.inspect = prepare, inspect
    runner._environment = lambda *args, **kwargs: environment
    owner.update(envelope=envelope, intent={}, journaled=False)

    async def no_op(*args, **kwargs):
        return None

    async def capacity(value):
        value["capacity"] = SimpleNamespace(
            claim={"token": "original"}, mark_native_intent=lambda token: None
        )

    async def authority(value, name, *args):
        if name == "authorize":
            phase, payload, binding = args
            calls.append(("grant", phase))
            return {
                "method": phase,
                "params": payload,
                "binding": binding,
                "execute": not (barrier == "grant" and phase == method),
            }
        return {}

    async def journal(value, name, *args, **kwargs):
        calls.append(("pg", name))
        denied = "mark_thread_submitted" if method == "thread/start" else "mark_turn_submitted"
        return {"execute": not (barrier == "pg_submission" and name == denied), "resource": {}}

    async def send(value, phase, payload):
        calls.append(("native", phase))
        return {"cwd": "/workspace", "thread": {"id": "original", "cwd": "/workspace"}}

    async def cleanup(value):
        value["cleaned"] = True
        if "pump" in value:
            await value["pump"]

    runner._cancelled_owned, runner._acquire_capacity = no_op, capacity
    runner._check_capacity = lambda value: None
    runner._authority_method, runner._authority_owned = authority, no_op
    runner._journal_method, runner._observe_owned = journal, no_op
    runner._preflight, runner._pump, runner._cleanup = no_op, no_op, cleanup
    runner._make_transport = lambda *args: SimpleNamespace(start=no_op)
    runner._request = send
    # Preparation still needs a positive original owner proof before its grant.
    owner["authority"]._owner_proof = {"original": "process"}
    with pytest.raises(RunnerOutcomeUnknown):
        asyncio.run(runner._execute(owner))
    assert ("grant", method) in calls and ("native", method) not in calls
    assert owner["cleaned"] is True
    if method == "turn/start":
        assert calls.count(("native", "thread/start")) == 1
