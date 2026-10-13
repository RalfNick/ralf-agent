"""Immutable, non-secret component declarations; no plugin imports or construction."""

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import DefinitionMismatch, ValidationError
from .types import canonical, digest, runtime_profile_identity

COMPONENT_KINDS = frozenset(
    {
        "tools",
        "session_store",
        "conversation_resource",
        "memory_store",
        "coordinator",
        "context_assembler",
        "harness",
        "tool_executor",
        "recall_policy",
        "recall_planner",
        "knowledge",
        "workflow_compiler",
        "workflow_interpreter",
        "workflow_scheduler",
        "workflow_transforms",
        "team_strategies",
        "planners",
        "plan_verifiers",
        "parent_completion_policies",
        "verifier",
        "limits",
        "stage_policy",
        "model_continuation",
        "model_history",
    }
)


def _name(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a non-empty string")
    return value


def component_declaration(value):
    if not isinstance(value, dict) or set(value) - {"adapter", "config"} or "adapter" not in value:
        raise ValidationError("A component requires adapter and optional config")
    _name(value["adapter"], "Adapter name")
    config = value.get("config", {})
    if not isinstance(config, dict):
        raise ValidationError("Component config must be a JSON object")
    return json.loads(canonical({"adapter": value["adapter"], "config": config}))


def binding_component_declaration(value):
    from .binding_catalog import SELECTABLE_ROLES

    if not isinstance(value, dict) or set(value) != {
        "role",
        "component_id",
        "version",
        "component",
    }:
        raise ValidationError(
            "Binding component requires role, component_id, version and component"
        )
    if not isinstance(value["role"], str) or value["role"] not in SELECTABLE_ROLES:
        raise ValidationError("Unsupported binding component role")
    _name(value["component_id"], "Binding component ID")
    _name(value["version"], "Binding component version")
    return {
        "role": value["role"],
        "component_id": value["component_id"],
        "version": value["version"],
        "component": component_declaration(value["component"]),
    }


@dataclass(frozen=True, init=False)
class RuntimeProfile:
    name: str
    version: str
    _data_json: str

    def __init__(self, name, version, providers, components=None, binding_components=None):
        _name(name, "Profile name")
        _name(version, "Profile version")
        if not isinstance(providers, dict) or not providers:
            raise ValidationError("A runtime profile requires at least one provider")
        normalized = {}
        for alias, declaration in providers.items():
            _name(alias, "Provider alias")
            normalized[alias] = component_declaration(declaration)
        components = {} if components is None else components
        if not isinstance(components, dict) or set(components) - COMPONENT_KINDS:
            raise ValidationError("Unknown runtime component kind")
        if "recall_policy" in components and "recall_planner" in components:
            raise ValidationError("Configure a recall policy or planner, not both")
        payload = {
            "name": name,
            "version": version,
            "providers": normalized,
            "components": {key: component_declaration(value) for key, value in components.items()},
        }
        if binding_components is not None:
            if not isinstance(binding_components, list):
                raise ValidationError("Binding components require a declaration list")
            bindings = [binding_component_declaration(value) for value in binding_components]
            keys = [(v["role"], v["component_id"], v["version"]) for v in bindings]
            if len(set(keys)) != len(keys):
                raise ValidationError("Binding component role/ID/version must be unique")
            payload.update(schema_version=2, binding_components=bindings)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "_data_json", canonical(payload))

    @property
    def providers(self):
        return json.loads(self._data_json)["providers"]

    @property
    def components(self):
        return json.loads(self._data_json)["components"]

    @property
    def schema_version(self):
        return json.loads(self._data_json).get("schema_version", 1)

    @property
    def binding_components(self):
        return json.loads(self._data_json).get("binding_components")

    @property
    def identity(self):
        return {
            "kind": "runtime-profile",
            "name": self.name,
            "version": self.version,
            "digest": digest(json.loads(self._data_json)),
        }


class RuntimeCatalog:
    def __init__(self, *, base_dir=None):
        self.base_dir = Path.cwd().resolve() if base_dir is None else Path(base_dir).resolve()
        self._profiles = {}
        self._default = None

    def register(self, profile, *, default=False):
        if not isinstance(profile, RuntimeProfile):
            raise ValidationError("Register a RuntimeProfile")
        key = (profile.name, profile.version)
        existing = self._profiles.get(key)
        if existing is not None and existing.identity != profile.identity:
            raise DefinitionMismatch("A profile version cannot be replaced with different content")
        self._profiles[key] = profile
        if default:
            self.set_default(*key)

    def set_default(self, name, version):
        if (name, version) not in self._profiles:
            raise DefinitionMismatch("The selected runtime profile is unavailable")
        self._default = (name, version)

    @property
    def default(self):
        if self._default is None:
            raise DefinitionMismatch("No default runtime profile is selected")
        return self._profiles[self._default]

    def resolve(self, identity):
        identity = runtime_profile_identity(identity)
        profile = self._profiles.get((identity["name"], identity["version"]))
        if profile is None or profile.identity != identity:
            raise DefinitionMismatch("The original runtime profile is unavailable or has changed")
        return profile


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("Duplicate JSON configuration key")
        result[key] = value
    return result


def read_declaration(path):
    path = Path(path).resolve()
    try:
        if path.stat().st_size > 1_000_000:
            raise ValidationError("Configuration files must not exceed 1 MB")
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".toml":
            value = tomllib.loads(text)
        elif path.suffix.lower() == ".json":
            value = json.loads(text, object_pairs_hook=_json_object)
        else:
            raise ValidationError("Use a JSON or TOML configuration file")
        canonical(value)
        return value
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("Cannot read a valid configuration file") from exc


def load_catalog(path):
    payload = read_declaration(path)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "default", "profiles"}
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] not in {1, 2}
        or not isinstance(payload["profiles"], list)
        or not isinstance(payload["default"], dict)
        or set(payload["default"]) != {"name", "version"}
    ):
        raise ValidationError(
            "Runtime catalog requires schema_version=1 or 2, default and profiles"
        )
    catalog = RuntimeCatalog(base_dir=Path(path).resolve().parent)
    for value in payload["profiles"]:
        allowed = {"name", "version", "providers", "components"}
        if payload["schema_version"] == 2:
            allowed.add("binding_components")
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValidationError("Unknown runtime profile fields")
        try:
            catalog.register(RuntimeProfile(**value))
        except TypeError as exc:
            raise ValidationError("A runtime profile requires name, version and providers") from exc
    _name(payload["default"]["name"], "Default profile name")
    _name(payload["default"]["version"], "Default profile version")
    catalog.set_default(**payload["default"])
    return catalog


def load_spec(path):
    from .types import AgentSpec, WorkflowSpec

    value = read_declaration(path)
    if not isinstance(value, dict):
        raise ValidationError("An Agent/Workflow spec must be an object")
    value = dict(value)
    if value.get("kind") in {"bound_agent", "bound_definition"}:
        from .binding_definitions import decode_definition

        return decode_definition(value)
    kind = value.pop("kind", "agent")
    try:
        if kind == "agent":
            return AgentSpec(**value)
        if kind == "sequence":
            steps = value.pop("steps")
            if not isinstance(steps, list):
                raise ValidationError("Workflow steps must be Agent declarations")
            return WorkflowSpec(steps=[AgentSpec(**step) for step in steps], **value)
        if kind == "graph":
            from .workflow import GraphWorkflowSpec

            return GraphWorkflowSpec.from_dict(value)
        if kind in {"team", "dynamic"}:
            from .orchestration_types import DynamicWorkflowSpec, TeamSpec

            return (TeamSpec if kind == "team" else DynamicWorkflowSpec).from_dict(value)
    except (KeyError, TypeError) as exc:
        raise ValidationError("Invalid Agent/Workflow declaration fields") from exc
    raise ValidationError("Spec kind must be agent, sequence, graph, team or dynamic")
