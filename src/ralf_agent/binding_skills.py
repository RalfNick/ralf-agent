"""Borrowed native Skill registrations and pure per-Agent grant intersection."""

import inspect
import json
from dataclasses import dataclass

from .binding_workspace import _names
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .ports import is_sync_callable
from .skill_tools import SkillToolSource
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
        raise ValidationError("Skills selection requires all original named tool manifests")
    # Preserve the original canonical JSON contract for unrelated business tools.
    # Native Skills registrations still require strict ordinary values before copy.
    return {
        name: _plain(record) if _source(record) is not None else json.loads(canonical(record))
        for name, record in manifests.items()
    }


def _registered(registry, names):
    if not is_sync_callable(getattr(registry, "manifests", None)):
        raise ValidationError("Skills registration snapshots must be synchronous")
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
            or not isinstance(owner.source, SkillToolSource)
            or getattr(owner.source.call_tool, "__func__", None) is not SkillToolSource.call_tool
            or registration.reconciler is not None
            or owner.policy.reconciler is not None
        ):
            raise ValidationError(
                "Skills resource requires the original native handler without a reconciler"
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
            raise DefinitionMismatch("Skills registration differs from its original native binding")
    return manifests


def _source(record):
    config = record.get("config", {})
    value = config.get("source") if type(config) is dict else None
    return (
        value
        if type(value) is dict
        and type(value.get("kind")) is str
        and value["kind"] == "skill-tool-source"
        else None
    )


def _native(record):
    source = _source(record)
    config = record.get("config", {})
    descriptor = config.get("remote_tool", {}) if type(config) is dict else {}
    if (
        source is None
        or set(source)
        != {"kind", "version", "behavior_version", "catalog", "max_entries", "max_bytes"}
        or type(source["version"]) is not str
        or source["version"] != "1"
        or type(source["catalog"]) is not dict
        or not source["catalog"]
        or type(source["max_entries"]) is not int
        or not 1 <= source["max_entries"] <= 1000
        or type(source["max_bytes"]) is not int
        or not 1 <= source["max_bytes"] <= 16777216
        or type(descriptor) is not dict
        or descriptor.get("name") not in {"skill_list", "skill_get"}
        or record.get("effect") != "read_only"
        or config.get("effect_key_argument") is not None
        or record.get("reconciler") is not None
    ):
        raise ValidationError("Skills bindings require original native read-only registrations")
    _text(source["behavior_version"], "Skill tool version", 256)
    _sha(source["catalog"].get("catalog_digest"))
    return source


def _resource(manifests):
    source = None
    for record in manifests.values():
        current = _native(record)
        if source is not None and canonical(current) != canonical(source):
            raise ValidationError("Skills binding cannot mix catalogs, versions or allowances")
        source = current
    return {"kind": "skill-binding-resource", "version": "1", "source": source, "tools": manifests}


def _record(identity):
    value = _plain(identity)
    if (
        type(value) is not dict
        or set(value) != {"kind", "version", "source", "tools"}
        or value["kind"] != "skill-binding-resource"
        or value["version"] != "1"
        or type(value["tools"]) is not dict
    ):
        raise ValidationError("Unsupported Skills binding resource")
    names = _names(list(value["tools"]))
    tools = _snapshot(names, value["tools"])
    if canonical(_resource(tools)) != canonical(value):
        raise ValidationError("Skills resource differs from its original registrations")
    return value


@dataclass(frozen=True, init=False)
class SkillBindingResource:
    """Select one original catalog ToolSource; owns and executes no resources."""

    registry: ToolRegistry
    names: tuple[str, ...]
    _identity_json: str

    def __init__(self, registry, *, names):
        selected = _names(names)
        if not isinstance(registry, ToolRegistry):
            raise ValidationError("Skills binding borrows an original ToolRegistry")
        identity = _resource(_registered(registry, selected))
        object.__setattr__(self, "registry", registry)
        object.__setattr__(self, "names", selected)
        object.__setattr__(self, "_identity_json", canonical(identity))

    @property
    def identity(self):
        current = _resource(_registered(self.registry, self.names))
        if canonical(current) != self._identity_json:
            raise DefinitionMismatch("Original Skills binding registrations changed")
        return json.loads(self._identity_json)


def select_skill_tools(names, manifests, resource_identity=None):
    """Restrict original grants; None disables only native Skills tools."""
    if type(names) not in (tuple, list) or any(type(n) is not str or not n for n in names):
        raise ValidationError("Skills selection requires original ordinary tool grants")
    if len(set(names)) != len(names):
        raise ValidationError("Skills selection cannot repeat a tool grant")
    names = tuple(names)
    manifests = _snapshot(names, manifests)
    selected = None if resource_identity is None else _record(resource_identity)
    result, matches = [], 0
    for name in names:
        record = manifests[name]
        if selected is not None and name in selected["tools"]:
            if canonical(record) != canonical(selected["tools"][name]):
                raise DefinitionMismatch("Granted Skills tool differs from selected registration")
            matches += 1
            result.append(name)
        elif _source(record) is None:
            result.append(name)
    if selected is not None and not matches:
        raise AuthorizationDenied("Selected Skills has no already-granted matching tools")
    return tuple(result)
