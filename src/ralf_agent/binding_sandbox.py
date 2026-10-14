"""Borrowed native Sandbox registrations and pure per-Agent grant intersection."""

import inspect
import json
from dataclasses import dataclass

from .binding_workspace import _names
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .ports import is_sync_callable
from .sandbox_tools import SandboxToolSource
from .skills import _plain, _sha, _text
from .tool_sources import _SourceBinding
from .tools import ToolRegistry
from .types import canonical


def _snapshot(names, manifests):
    if (
        type(manifests) is not dict
        or set(manifests) != set(names)
        or any(
            type(record) is not dict or record.get("name") != name
            for name, record in manifests.items()
        )
    ):
        raise ValidationError("Sandbox selection requires all original named tool manifests")
    # Preserve the original canonical JSON contract for unrelated business tools.
    # Native Sandbox registrations still require strict ordinary values before copy.
    return {
        name: _plain(record) if _source(record) is not None else json.loads(canonical(record))
        for name, record in manifests.items()
    }


def _registered(registry, names):
    if not is_sync_callable(getattr(registry, "manifests", None)):
        raise ValidationError("Sandbox registration snapshots must be synchronous")
    result = registry.manifests(names)
    if inspect.iscoroutine(result) or inspect.isgenerator(result):
        result.close()
    manifests = _snapshot(names, result)
    for name, manifest in manifests.items():
        _native(manifest)
        registration = registry.get(name)
        handler = registration.handler
        owner = getattr(handler, "__self__", None)
        if (
            type(owner) is not _SourceBinding
            or getattr(handler, "__func__", None) is not _SourceBinding.call
            or not isinstance(owner.source, SandboxToolSource)
            or getattr(owner.source.call_tool, "__func__", None) is not SandboxToolSource.call_tool
            or registration.reconciler is not None
            or owner.policy.reconciler is not None
        ):
            raise ValidationError(
                "Sandbox resource requires the original native handler without a reconciler"
            )
        expected = {
            "source": json.loads(owner._identity_json),
            "remote_tool": owner.descriptor.to_dict(),
            "effect_key_argument": owner.policy.effect_key_argument,
        }
        if (
            canonical(_plain(owner.source.identity)) != owner._identity_json
            or canonical(manifest["config"]) != canonical(expected)
            or canonical(manifest["input_schema"]) != owner._schema_json
            or manifest["version"] != owner.policy.version
            or manifest["effect"] != owner.policy.effect
            or canonical(manifest["cost"]) != canonical(owner.policy.cost)
            or manifest["requires_approval"] is not owner.policy.requires_approval
        ):
            raise DefinitionMismatch(
                "Sandbox registration differs from its original native binding"
            )
    return manifests


def _source(record):
    config = record.get("config", {})
    value = config.get("source") if type(config) is dict else None
    return (
        value
        if type(value) is dict
        and type(value.get("kind")) is str
        and value["kind"] == "sandbox-tool-source"
        else None
    )


def _native(record):
    source = _source(record)
    config = record.get("config", {})
    descriptor = config.get("remote_tool", {}) if type(config) is dict else {}
    if (
        source is None
        or set(source)
        != {
            "kind",
            "version",
            "behavior_version",
            "provider",
            "max_timeout",
            "max_output_bytes",
            "max_calls",
            "implementation",
        }
        or type(source["version"]) is not str
        or source["version"] != "1"
        or type(source["provider"]) is not dict
        or not source["provider"]
        or type(source["max_timeout"]) not in (int, float)
        or not 0 < source["max_timeout"] <= 300
        or type(source["max_output_bytes"]) is not int
        or not 1 <= source["max_output_bytes"] <= 16777216
        or type(source["max_calls"]) is not int
        or not 1 <= source["max_calls"] <= 16
        or type(source["implementation"]) is not dict
        or set(source["implementation"]) != {"call_tool", "_execute", "_observe_failure", "aclose"}
        or type(descriptor) is not dict
        or descriptor.get("name") != "sandbox_run"
        or record.get("effect") != "read_only"
        or config.get("effect_key_argument") is not None
        or record.get("reconciler") is not None
    ):
        raise ValidationError("Sandbox bindings require original native read-only registrations")
    _text(source["behavior_version"], "Sandbox tool version", 256)
    for value in source["implementation"].values():
        _sha(value)
    isolation = source["provider"].get("isolation")
    if type(isolation) is not dict or any(
        type(isolation.get(k)) is not type(v) or isolation.get(k) != v
        for k, v in {"network": "none", "host_mounts": False, "persistent_files": False}.items()
    ):
        raise ValidationError("Sandbox binding requires its original restricted ephemeral profile")
    return source


def has_sandbox_tools(manifests):
    if type(manifests) is not dict or any(
        type(name) is not str or type(record) is not dict for name, record in manifests.items()
    ):
        raise ValidationError("Sandbox tool metadata requires ordinary tool mappings")
    return any(_source(record) is not None for record in manifests.values())


def validate_sandbox_protocol(manifest):
    if type(manifest) is not dict or type(manifest.get("binding_catalog", {})) is not dict:
        raise ValidationError("Sandbox protocol requires ordinary manifest mappings")
    tools = manifest.get("tools", {})
    records = manifest.get("binding_catalog", {}).get("records", {})
    if type(records) is not dict or any(type(record) is not dict for record in records.values()):
        raise ValidationError("Sandbox binding metadata requires ordinary record mappings")
    enabled = has_sandbox_tools(tools) or any(r.get("role") == "sandbox" for r in records.values())
    if (
        not enabled
        and "sandbox_binding_protocol" not in manifest
        and manifest.get("binding_protocol") != 4
    ):
        return
    if (
        not enabled
        or type(manifest.get("sandbox_binding_protocol")) is not int
        or manifest["sandbox_binding_protocol"] != 1
        or manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"]
        not in (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21)
        or "tool_execution_protocol" not in manifest
    ):
        raise DefinitionMismatch("Unsupported original Sandbox binding protocol")
    for record in tools.values():
        if _source(record) is not None:
            _native(record)
    for record in records.values():
        if record.get("role") == "sandbox":
            _record(record.get("identity"))


def _resource(manifests):
    source = None
    for record in manifests.values():
        current = _native(record)
        if source is not None and canonical(current) != canonical(source):
            raise ValidationError("Sandbox binding cannot mix catalogs, versions or allowances")
        source = current
    return {
        "kind": "sandbox-binding-resource",
        "version": "1",
        "source": source,
        "tools": manifests,
    }


def _record(identity):
    value = _plain(identity)
    if (
        type(value) is not dict
        or set(value) != {"kind", "version", "source", "tools"}
        or value["kind"] != "sandbox-binding-resource"
        or value["version"] != "1"
        or type(value["tools"]) is not dict
    ):
        raise ValidationError("Unsupported Sandbox binding resource")
    names = _names(list(value["tools"]))
    tools = _snapshot(names, value["tools"])
    if canonical(_resource(tools)) != canonical(value):
        raise ValidationError("Sandbox resource differs from its original registrations")
    return value


@dataclass(frozen=True, init=False)
class SandboxBindingResource:
    """Select one original catalog ToolSource; owns and executes no resources."""

    registry: ToolRegistry
    names: tuple[str, ...]
    _identity_json: str

    def __init__(self, registry, *, names):
        selected = _names(names)
        if not isinstance(registry, ToolRegistry):
            raise ValidationError("Sandbox binding borrows an original ToolRegistry")
        identity = _resource(_registered(registry, selected))
        object.__setattr__(self, "registry", registry)
        object.__setattr__(self, "names", selected)
        object.__setattr__(self, "_identity_json", canonical(identity))

    @property
    def identity(self):
        current = _resource(_registered(self.registry, self.names))
        if canonical(current) != self._identity_json:
            raise DefinitionMismatch("Original Sandbox binding registrations changed")
        return json.loads(self._identity_json)


def select_sandbox_tools(names, manifests, resource_identity=None):
    """Restrict original grants; None disables only native Sandbox tools."""
    if type(names) not in (tuple, list) or any(type(n) is not str or not n for n in names):
        raise ValidationError("Sandbox selection requires original ordinary tool grants")
    if len(set(names)) != len(names):
        raise ValidationError("Sandbox selection cannot repeat a tool grant")
    names = tuple(names)
    manifests = _snapshot(names, manifests)
    selected = None if resource_identity is None else _record(resource_identity)
    result, matches = [], 0
    for name in names:
        record = manifests[name]
        if selected is not None and name in selected["tools"]:
            if canonical(record) != canonical(selected["tools"][name]):
                raise DefinitionMismatch("Granted Sandbox tool differs from selected registration")
            matches += 1
            result.append(name)
        elif _source(record) is None:
            result.append(name)
    if selected is not None and not matches:
        raise AuthorizationDenied("Selected Sandbox has no already-granted matching tools")
    return tuple(result)
