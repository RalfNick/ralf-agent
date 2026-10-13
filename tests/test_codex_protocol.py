import copy

import pytest

from ralf_agent.codex_protocol import CodexProtocol
from ralf_agent.errors import DefinitionMismatch, ValidationError


def test_protocol_pins_installed_version_and_schema():
    protocol = CodexProtocol()
    identity = protocol.identity
    assert identity["external_version"] == "0.144.4"
    assert len(identity["schema_digest"]) == 64
    identity["methods"].append("process/spawn")
    assert "process/spawn" not in protocol.identity["methods"]
    with pytest.raises(DefinitionMismatch):
        CodexProtocol(external_version="0.144.5")


def test_schema_resource_tamper_is_rejected_before_native_io(tmp_path, monkeypatch):
    import ralf_agent.codex_protocol as module

    (tmp_path / "_codex_protocol_schema.json").write_text("{}")
    monkeypatch.setattr(module, "files", lambda package: tmp_path)
    with pytest.raises(DefinitionMismatch, match="integrity"):
        CodexProtocol()


def test_stable_handshake_rejects_experimental_and_unknown_fields():
    protocol = CodexProtocol()
    params = {
        "clientInfo": {"name": "ralf-agent", "version": "preview"},
        "capabilities": {"experimentalApi": False},
    }
    assert protocol.validate_request("initialize", params) == params
    for edit in (
        {"experimentalApi": True},
        {"mcpServerOpenaiFormElicitation": True},
        {"requestAttestation": True},
        {"unexpected": False},
    ):
        with pytest.raises(ValidationError):
            protocol.validate_request("initialize", {**params, "capabilities": edit})
    with pytest.raises(ValidationError):
        protocol.validate_request("initialize", {**params, "secret": "never print me"})


@pytest.mark.parametrize("method", ["process/spawn", "thread/shellCommand", "config/write"])
def test_management_paths_are_not_in_protocol_subset(method):
    with pytest.raises(ValidationError):
        CodexProtocol().validate_request(method, {})


def test_known_locator_query_and_interrupt_are_strict_and_detached():
    protocol = CodexProtocol()
    params = {"threadId": "native-thread", "includeTurns": True}
    value = protocol.validate_request("thread/read", params)
    value["threadId"] = "other"
    assert params["threadId"] == "native-thread"
    assert protocol.validate_response("turn/interrupt", {}) == {}
    for invalid in ({"threadId": "t"}, {"threadId": "t", "turnId": 1}):
        with pytest.raises(ValidationError):
            protocol.validate_request("turn/interrupt", invalid)
    with pytest.raises(ValidationError):
        protocol.validate_response("turn/start", {})


def test_protocol_validity_is_not_environment_or_governance_proof():
    protocol = CodexProtocol()
    native = {"sandbox": "workspace-write", "approvalPolicy": "never", "cwd": "/tmp"}
    assert protocol.validate_request("thread/start", native) == native
    assert protocol.identity["environment_verified"] is False
    assert protocol.identity["governance_verified"] is False


def test_nonfinite_or_unknown_nested_fields_never_enter_protocol():
    protocol = CodexProtocol()
    params = {"threadId": "t", "input": [{"type": "text", "text": "task"}]}
    assert protocol.validate_request("turn/start", params) == params
    invalid = copy.deepcopy(params)
    invalid["input"][0]["secret"] = "never print me"
    with pytest.raises(ValidationError, match="Codex request does not match") as exc:
        protocol.validate_request("turn/start", invalid)
    assert "never print me" not in str(exc.value)
    with pytest.raises(ValidationError):
        protocol.validate_request("thread/start", {"config": {"value": float("nan")}})


def test_response_preserves_native_fields_but_validates_original_required_fields():
    protocol = CodexProtocol()
    native = {
        "userAgent": "test",
        "codexHome": "/private/native",
        "platformFamily": "unix",
        "platformOs": "macos",
        "extra": 1,
    }
    assert protocol.validate_response("initialize", native) == native
    with pytest.raises(ValidationError):
        protocol.validate_response("initialize", {"userAgent": 42})


@pytest.mark.parametrize("mode", ["depth", "cycle", "surrogate", "huge"])
def test_unbounded_protocol_values_fail_with_sanitized_typed_error(mode):
    value = {"x": "\ud800" if mode == "surrogate" else "a"}
    if mode == "depth":
        for _ in range(2000):
            value = {"x": value}
    elif mode == "cycle":
        value["x"] = value
    elif mode == "huge":
        value["x"] = "a" * (1048576 + 1)
    with pytest.raises(ValidationError):
        CodexProtocol().validate_request("thread/start", {"config": value})
