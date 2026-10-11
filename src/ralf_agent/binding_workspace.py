"""Borrowed Workspace tool registrations and pure per-Agent grant intersection."""

import inspect
import json
from dataclasses import dataclass

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .ports import is_sync_callable
from .tools import ToolRegistry
from .types import canonical


def _names(values, *, empty=False):
    if type(values) not in (tuple, list) or not (0 if empty else 1) <= len(values) <= 256:
        raise ValidationError("Workspace bindings require at most 256 explicit tool names")
    for name in values:
        if (
            type(name) is not str
            or not name.strip()
            or len(name) > 128
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
        ):
            raise ValidationError("Workspace binding requires bounded ordinary tool names")
        try:
            if len(name.encode("utf-8")) > 512:
                raise ValidationError("Workspace tool name exceeds its UTF-8 allowance")
        except UnicodeError:
            raise ValidationError("Workspace tool names require UTF-8") from None
    if len(set(values)) != len(values):
        raise ValidationError("Workspace binding tool names must be unique")
    return tuple(values)


def _snapshot(names, manifests):
    if type(manifests) is not dict or set(manifests) != set(names):
        raise ValidationError("Workspace selection requires all original named tool manifests")
    value = json.loads(canonical(manifests))
    if any(
        type(record) is not dict or record.get("name") != name for name, record in value.items()
    ):
        raise ValidationError("Workspace tool manifest names differ from their registrations")
    return value


def _registered(registry, names):
    if not is_sync_callable(getattr(registry, "manifests", None)):
        raise ValidationError("Workspace registry snapshots must be synchronous")
    result = registry.manifests(names)
    if inspect.iscoroutine(result) or inspect.isgenerator(result):
        result.close()
    return _snapshot(names, result)


def _source(record):
    config = record.get("config", {})
    value = config.get("source") if type(config) is dict else None
    return value if type(value) is dict and value.get("kind") == "workspace-tool-source" else None


def _workspace_source(record):
    source = _source(record)
    config = record.get("config", {})
    descriptor = config.get("remote_tool", {}) if type(config) is dict else {}
    if (
        source is None
        or set(source)
        != {"kind", "version", "behavior_version", "workspace", "max_entries", "max_bytes"}
        or source["version"] != "1"
        or type(source["behavior_version"]) is not str
        or not source["behavior_version"].strip()
        or type(source["workspace"]) is not dict
        or not source["workspace"]
        or type(source["max_entries"]) is not int
        or not 1 <= source["max_entries"] <= 1000
        or type(source["max_bytes"]) is not int
        or not 1 <= source["max_bytes"] <= 16777216
        or record.get("effect") != "read_only"
        or config.get("effect_key_argument") is not None
        or type(descriptor) is not dict
        or descriptor.get("name") not in {"workspace_stat", "workspace_list", "workspace_read_text"}
    ):
        raise ValidationError(
            "Workspace binding requires original read-only Workspace registrations"
        )
    return source


def _resource(manifests):
    source = None
    for record in manifests.values():
        current = _workspace_source(record)
        if source is not None and canonical(current) != canonical(source):
            raise ValidationError(
                "Workspace binding cannot mix source roots, versions or allowances"
            )
        source = current
    return {
        "kind": "workspace-binding-resource",
        "version": "1",
        "source": source,
        "tools": manifests,
    }


def _record(identity):
    if type(identity) is not dict or set(identity) != {"kind", "version", "source", "tools"}:
        raise ValidationError("Workspace selection requires its recorded resource identity")
    value = json.loads(canonical(identity))
    if (
        value["kind"] != "workspace-binding-resource"
        or value["version"] != "1"
        or type(value["tools"]) is not dict
    ):
        raise ValidationError("Unsupported Workspace binding resource")
    names = _names(list(value["tools"]))
    tools = _snapshot(names, value["tools"])
    if canonical(_resource(tools)) != canonical(value):
        raise ValidationError("Workspace resource differs from its original source registrations")
    return value


@dataclass(frozen=True, init=False)
class WorkspaceBindingResource:
    """Select one host-registered Workspace source; owns and executes no resources."""

    registry: ToolRegistry
    names: tuple[str, ...]
    _identity_json: str

    def __init__(self, registry, *, names):
        selected = _names(names)
        if not isinstance(registry, ToolRegistry):
            raise ValidationError("Workspace binding borrows an original ToolRegistry")
        identity = _resource(_registered(registry, selected))
        object.__setattr__(self, "registry", registry)
        object.__setattr__(self, "names", selected)
        object.__setattr__(self, "_identity_json", canonical(identity))

    @property
    def identity(self):
        current = _resource(_registered(self.registry, self.names))
        if canonical(current) != self._identity_json:
            raise DefinitionMismatch("Original Workspace binding registrations changed")
        return json.loads(self._identity_json)


def select_workspace_tools(names, manifests, resource_identity=None):
    """Restrict original grants; None disables Workspace tools, never business tools."""
    if type(names) not in (tuple, list) or any(type(name) is not str or not name for name in names):
        raise ValidationError("Workspace selection requires original ordinary tool grants")
    if len(set(names)) != len(names):
        raise ValidationError("Workspace selection cannot repeat a tool grant")
    names = tuple(names)
    manifests = _snapshot(names, manifests)
    selected = None if resource_identity is None else _record(resource_identity)
    result, matches = [], 0
    for name in names:
        record = manifests[name]
        if selected is not None and name in selected["tools"]:
            if canonical(record) != canonical(selected["tools"][name]):
                raise DefinitionMismatch(
                    "Granted Workspace tool differs from selected registration"
                )
            matches += 1
            result.append(name)
        elif _source(record) is None:
            result.append(name)
    if selected is not None and not matches:
        raise AuthorizationDenied("Selected Workspace has no already-granted matching tools")
    return tuple(result)
