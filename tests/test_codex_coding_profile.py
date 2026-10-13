import copy
import importlib
import json
import tomllib
from pathlib import Path

import pytest

from ralf_agent.errors import ValidationError


def native_results():
    return json.loads(Path(__file__).with_name("codex_control_fixture.json").read_text())


def profile():
    module = importlib.import_module("ralf_agent.codex_coding_profile")
    return module.CodexCodingProfile()


def test_native_fixture_is_nine_complete_stable_control_result_shapes():
    from ralf_agent.codex_protocol import CodexControlProtocol

    values = json.loads(Path(__file__).with_name("codex_control_fixture.json").read_text())
    protocol = CodexControlProtocol()
    assert len(values) == 9
    for method, result in values.items():
        assert protocol.validate_response(method, result) == result


def test_actual_native_config_is_accepted_as_control_only():
    value = profile().validate_control(native_results())
    assert value["control_verified"] is True
    assert value["execution_admitted"] is False
    assert value["native_version"] == "0.144.4"
    assert value["permission_profile"] == "ralf-coding-v1"
    assert value["config_origin_digest"] == (
        "sha256:d3195ce1484a937eaf84cec38dfd6c86992d41dc4ffbe7640ccfc7f448f9abfa"
    )
    assert value["enabled_coding_features"] == ["shell_tool", "unified_exec"]
    assert "config" not in value and "origins" not in value


def test_config_emits_named_bounded_permissions_and_no_legacy_policy():
    p = profile()
    config = tomllib.loads(p.config_text)
    assert config["default_permissions"] == "ralf-coding-v1"
    assert "sandbox_mode" not in config and "sandbox_workspace_write" not in config
    filesystem = config["permissions"]["ralf-coding-v1"]["filesystem"]
    assert filesystem[":minimal"] == "read"
    assert filesystem["/opt/codex/bin/codex"] == "read"
    for denied in ("/home/ralf", "/forbidden", "/traps", "/tmp"):
        assert filesystem[denied] == "deny"
    assert filesystem[":workspace_roots"] == {
        ".": "write",
        ".codex": "deny",
        ".agents": "deny",
        ".git": "deny",
    }
    assert config["permissions"]["ralf-coding-v1"]["network"]["enabled"] is False
    assert config["shell_environment_policy"]["inherit"] == "none"
    assert config["allow_login_shell"] is False


def test_identity_and_validation_output_do_not_authorize_execution_or_alias_state():
    p = profile()
    identity = p.identity
    assert identity["kind"] == "codex-coding-candidate"
    assert identity["control_verified"] is False
    assert identity["execution_admitted"] is False
    assert identity["normal_account"] == {"uid": 10001, "gid": 10001, "home": "/home/ralf"}
    identity["normal_account"]["uid"] = 0
    assert p.identity["normal_account"]["uid"] == 10001
    results = native_results()
    accepted = p.validate_control(results)
    accepted["enabled_coding_features"].append("hooks")
    assert p.validate_control(results)["enabled_coding_features"] == ["shell_tool", "unified_exec"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("mcp_servers", {"unexpected": {"command": "sensitive-value"}}),
        ("hooks", {"SessionStart": "sensitive-value"}),
        ("notify", ["sensitive-value"]),
        ("model_providers", {"other": {"api_key": "sensitive-value"}}),
        ("sandbox_mode", "danger-full-access"),
        ("allow_login_shell", True),
        ("default_permissions", ":danger-full-access"),
        ("plugins", {"unexpected": {"enabled": True}}),
        ("instructions", "sensitive-value"),
    ],
)
def test_effective_capability_changes_are_rejected_without_leaking_values(field, value):
    native = native_results()
    native["config/read"]["config"][field] = value
    with pytest.raises(ValidationError) as exc:
        profile().validate_control(native)
    assert "sensitive-value" not in str(exc.value)


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "digest",
        "missing_origin",
        "extra_origin",
        "system_config",
        "extra_layer",
        "layer_value",
    ],
)
def test_config_origin_and_exact_parsed_layer_are_mandatory(mutation):
    native = native_results()
    read = native["config/read"]
    if mutation == "source":
        next(iter(read["origins"].values()))["name"]["file"] = "/unexpected/config.toml"
    elif mutation == "digest":
        next(iter(read["origins"].values()))["version"] = "sha256:" + "0" * 64
    elif mutation == "missing_origin":
        read["origins"].pop("default_permissions")
    elif mutation == "extra_origin":
        read["origins"]["unexpected"] = copy.deepcopy(next(iter(read["origins"].values())))
    elif mutation == "system_config":
        read["layers"][2]["config"] = {"hooks": {"x": "sensitive-value"}}
    elif mutation == "extra_layer":
        read["layers"].append(copy.deepcopy(read["layers"][0]))
    else:
        read["layers"][1]["config"]["default_permissions"] = ":danger-full-access"
    with pytest.raises(ValidationError):
        profile().validate_control(native)


@pytest.mark.parametrize(
    "mutation", ["enable", "stage", "extra", "duplicate", "missing", "bool_int"]
)
def test_effective_feature_catalog_is_frozen_including_removed_exceptions(mutation):
    native = native_results()
    data = native["experimentalFeature/list"]["data"]
    feature = next(x for x in data if x["name"] == "hooks")
    if mutation == "enable":
        feature["enabled"] = True
    elif mutation == "stage":
        feature["stage"] = "removed"
    elif mutation == "extra":
        data.append({**feature, "name": "unexpected"})
    elif mutation == "duplicate":
        data.append(copy.deepcopy(feature))
    elif mutation == "missing":
        data.remove(feature)
    else:
        feature["enabled"] = 0
    with pytest.raises(ValidationError):
        profile().validate_control(native)


@pytest.mark.parametrize(
    "method", ["experimentalFeature/list", "mcpServerStatus/list", "permissionProfile/list"]
)
@pytest.mark.parametrize("cursor", ["missing", "more", 0])
def test_inventory_must_be_complete_with_explicit_null_cursor(method, cursor):
    native = native_results()
    if cursor == "missing":
        native[method].pop("nextCursor")
    else:
        native[method]["nextCursor"] = cursor
    with pytest.raises(ValidationError):
        profile().validate_control(native)


@pytest.mark.parametrize(
    "mutation", ["enabled", "path", "scope", "extra", "errors", "missing", "int_false"]
)
def test_every_known_system_skill_must_be_disabled_without_extra_sources(mutation):
    native = native_results()
    entry = native["skills/list"]["data"][0]
    skill = entry["skills"][0]
    if mutation in ("enabled", "int_false"):
        skill["enabled"] = True if mutation == "enabled" else 0
    elif mutation == "path":
        skill["path"] = "/workspace/.agents/skills/unexpected/SKILL.md"
    elif mutation == "scope":
        skill["scope"] = "repo"
    elif mutation == "extra":
        entry["skills"].append({**skill, "name": "unexpected"})
    elif mutation == "errors":
        entry["errors"] = [{"path": "/unknown", "message": "sensitive-value"}]
    else:
        entry["skills"].pop()
    with pytest.raises(ValidationError):
        profile().validate_control(native)


@pytest.mark.parametrize(
    "mutation", ["requirements", "mcp", "plugins", "plugin_errors", "profile", "null"]
)
def test_unexpected_capabilities_and_requirements_fail_closed(mutation):
    native = native_results()
    if mutation == "requirements":
        native["configRequirements/read"]["requirements"] = {"allowedSandboxModes": ["read-only"]}
    elif mutation == "mcp":
        native["mcpServerStatus/list"]["data"] = [{"name": "disabled_but_unexpected"}]
    elif mutation == "plugins":
        native["plugin/list"]["marketplaces"] = [{"name": "unexpected"}]
    elif mutation == "plugin_errors":
        native["plugin/installed"]["marketplaceLoadErrors"] = [{"message": "sensitive-value"}]
    elif mutation == "profile":
        native["permissionProfile/list"]["data"][3]["allowed"] = False
    else:
        native["config/read"]["layers"] = None
    with pytest.raises(ValidationError):
        profile().validate_control(native)


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "nan", "cycle", "surrogate", "huge", "platform"]
)
def test_unbounded_or_wrong_control_shapes_are_sanitized(mutation):
    native = native_results()
    if mutation == "missing":
        native.pop("config/read")
    elif mutation == "extra":
        native["account/login/start"] = {"apiKey": "sensitive-value"}
    elif mutation == "nan":
        native["initialize"]["userAgent"] = float("nan")
    elif mutation == "cycle":
        native["config/read"]["config"]["loop"] = native
    elif mutation == "surrogate":
        native["initialize"]["userAgent"] = "\ud800"
    elif mutation == "huge":
        native["initialize"]["userAgent"] = "sensitive-value" * 100000
    else:
        native["initialize"]["platformOs"] = "macos"
    with pytest.raises(ValidationError) as exc:
        profile().validate_control(native)
    assert "sensitive-value" not in str(exc.value)


def test_removed_feature_exceptions_are_exact_native_values_without_new_exceptions():
    native = native_results()
    flag = next(
        x for x in native["experimentalFeature/list"]["data"] if x["name"] == "tui_app_server"
    )
    flag["enabled"] = False
    with pytest.raises(ValidationError):
        profile().validate_control(native)


def test_skill_dependency_metadata_cannot_introduce_an_unexpected_command():
    native = native_results()
    skill = next(
        x for x in native["skills/list"]["data"][0]["skills"] if x["name"] == "openai-docs"
    )
    skill["dependencies"]["tools"][0]["command"] = "sensitive-value"
    with pytest.raises(ValidationError) as exc:
        profile().validate_control(native)
    assert "sensitive-value" not in str(exc.value)


@pytest.mark.parametrize(
    "mutation",
    ["config", "reason", "missing_reason", "folder", "digest", "missing_layer", "extra_layer"],
)
def test_protected_project_directory_requires_exact_empty_disabled_layer(mutation):
    native = native_results()
    layers = native["config/read"]["layers"]
    project = layers[0]
    if mutation == "config":
        project["config"] = {"hooks": {"SessionStart": "sensitive-value"}}
    elif mutation == "reason":
        project["disabledReason"] = "some other disabled reason"
    elif mutation == "missing_reason":
        project.pop("disabledReason")
    elif mutation == "folder":
        project["name"]["dotCodexFolder"] = "/other/.codex"
    elif mutation == "digest":
        project["version"] = "sha256:" + "0" * 64
    elif mutation == "missing_layer":
        layers.pop(0)
    else:
        layers.insert(0, copy.deepcopy(project))
    with pytest.raises(ValidationError) as exc:
        profile().validate_control(native)
    assert "sensitive-value" not in str(exc.value)
