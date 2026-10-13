import copy
import hashlib
import json
from importlib.resources import files
from pathlib import Path

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


def test_coding_protocol_combines_frozen_schemas_without_changing_reference_identities():
    from ralf_agent.codex_protocol import CodexCodingProtocol, CodexControlProtocol

    protocol = CodexCodingProtocol()
    assert protocol.identity["business_protocol"] == CodexProtocol().identity
    assert protocol.identity["control_protocol"] == CodexControlProtocol().identity
    assert protocol.identity["methods"] == [
        "config/read",
        "configRequirements/read",
        "experimentalFeature/list",
        "initialize",
        "mcpServerStatus/list",
        "permissionProfile/list",
        "plugin/installed",
        "plugin/list",
        "skills/list",
        "thread/read",
        "thread/resume",
        "thread/start",
        "turn/interrupt",
        "turn/start",
    ]
    assert protocol.identity["execution_admitted"] is False
    assert protocol.validate_request("configRequirements/read", None) is None
    assert protocol.validate_request("thread/read", {"threadId": "t", "includeTurns": True})
    assert protocol.validate_request(
        "turn/start",
        {
            "threadId": "t",
            "input": [{"type": "text", "text": "task"}],
        },
    )
    assert protocol.validate_response("turn/interrupt", {}) == {}
    fixture = Path(__file__).with_name("codex_control_fixture.json")
    for method, result in json.loads(fixture.read_bytes()).items():
        assert protocol.validate_response(method, result) == result
    for method, params in (
        ("process/spawn", {}),
        ("config/write", {}),
        ("unknown", {}),
        ("config/read", None),
        ("configRequirements/read", {}),
        (
            "initialize",
            {
                "clientInfo": {"name": "test", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        ),
    ):
        with pytest.raises(ValidationError):
            protocol.validate_request(method, params)
    with pytest.raises(DefinitionMismatch):
        CodexCodingProtocol(external_version="0.144.5")


@pytest.mark.parametrize("resource", ["_codex_protocol_schema.json", "_codex_control_schema.json"])
def test_coding_protocol_checks_both_reference_resource_integrities(
    tmp_path, monkeypatch, resource
):
    import ralf_agent.codex_protocol as module
    from ralf_agent.codex_protocol import CodexCodingProtocol

    for name in ("_codex_protocol_schema.json", "_codex_control_schema.json"):
        data = files("ralf_agent").joinpath(name).read_bytes()
        (tmp_path / name).write_bytes(b"{}" if name == resource else data)
    monkeypatch.setattr(module, "files", lambda package: tmp_path)
    with pytest.raises(DefinitionMismatch, match="integrity"):
        CodexCodingProtocol()


def test_frozen_native_artifact_bytes_and_business_identity_are_unchanged():
    expected = {
        "_codex_protocol_schema.json": "5d2ba8cdee699144bd0ec23760146c6f45919fa9ac6ec5b61004dc3ea7b2a275",
        "_codex_control_schema.json": "87807599334eb051aee3aedfae349c936108a0122770e73f0d466433d39d55bf",
        "_codex_coding_seccomp.json": "569e7aa0a4d8ed2b0bfada839187309d880c21350c36eaa2b55f15c0c85b41aa",
    }
    for name, digest in expected.items():
        assert hashlib.sha256(files("ralf_agent").joinpath(name).read_bytes()).hexdigest() == digest
    assert CodexProtocol().identity == {
        "kind": "codex-app-server-protocol",
        "version": "1",
        "external_version": "0.144.4",
        "schema_digest": expected["_codex_protocol_schema.json"],
        "methods": [
            "initialize",
            "thread/read",
            "thread/resume",
            "thread/start",
            "turn/interrupt",
            "turn/start",
        ],
        "experimental_api": False,
        "environment_verified": False,
        "governance_verified": False,
    }
