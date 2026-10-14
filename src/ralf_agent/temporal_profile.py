"""Pure Temporal declarations, separate from factory I/O and execution authority."""

import json
from dataclasses import dataclass
from pathlib import Path

from .errors import DefinitionMismatch, ValidationError
from .runtime_config import RuntimeProfile, component_declaration, read_declaration
from .types import canonical, digest, runtime_profile_identity

LOCAL_COMPONENTS = frozenset(
    {
        "coordinator",
        "model_continuation",
        "conversation_resource",
        "workflow_compiler",
        "workflow_interpreter",
        "workflow_scheduler",
        "workflow_transforms",
    }
)
EXECUTION_FLAGS = frozenset(
    {
        "enable_sessions",
        "session_writes",
        "composite_sessions",
        "context_reads",
        "artifact_bindings",
        "model_continuation",
        "coding_execution",
        "coding_composition",
    }
)
MAX_DECLARATION_BYTES = 1_000_000


def _bounded(value):
    text = canonical(value)
    try:
        if len(text.encode("utf-8")) > MAX_DECLARATION_BYTES:
            raise ValidationError("Temporal declarations must not exceed 1 MB")
    except UnicodeError:
        raise ValidationError("Temporal declarations require valid UTF-8 text") from None
    return text


@dataclass(frozen=True, init=False)
class TemporalProfile:
    name: str
    version: str
    _data_json: str

    def __init__(
        self,
        name,
        version,
        providers,
        components=None,
        binding_components=None,
        execution=None,
    ):
        temporal_components = {}
        if type(components) is dict:
            temporal_components = {
                key: component_declaration(value)
                for key, value in components.items()
                if key in {"effect_journal", "tool_execution"}
            }
            components = {
                key: value for key, value in components.items() if key not in temporal_components
            }
        original = RuntimeProfile(name, version, providers, components, binding_components)
        if set(original.components) & LOCAL_COMPONENTS:
            raise ValidationError("Local execution components cannot configure Temporal authority")
        execution = {} if execution is None else execution
        if (
            type(execution) is not dict
            or set(execution) - EXECUTION_FLAGS
            or any(type(value) is not bool for value in execution.values())
        ):
            raise ValidationError("Temporal execution options require declared boolean flags")
        flags = {
            name: execution.get(name, False)
            for name in sorted(EXECUTION_FLAGS)
            if name
            not in {
                "artifact_bindings",
                "model_continuation",
                "coding_execution",
                "coding_composition",
            }
            or execution.get(name, False)
        }
        if flags.get("coding_composition") and not flags.get("coding_execution"):
            raise ValidationError("Coding composition requires explicit Coding execution")
        from .runtime_builder import (
            model_history_declarations,
            validate_session_history_declarations,
        )

        if model_history_declarations(original) and not flags.get("model_continuation", False):
            raise ValidationError("Temporal model history requires explicit model continuation")
        validate_session_history_declarations(original, source_available=flags["enable_sessions"])
        session_declared = "session_store" in original.components or any(
            item["role"] == "session" for item in original.binding_components or []
        )
        if flags["session_writes"] and not session_declared:
            raise ValidationError("Temporal Session writes require declared Session data")
        if flags["composite_sessions"] and (
            not flags["enable_sessions"]
            or not flags["session_writes"]
            or "session_store" not in original.components
        ):
            raise ValidationError(
                "Composite Session data requires host Session data and write admission"
            )
        payload = {
            "name": name,
            "version": version,
            "providers": original.providers,
            "components": original.components,
            "execution": flags,
        }
        payload["components"].update(temporal_components)
        if original.binding_components is not None:
            payload["binding_components"] = original.binding_components
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "_data_json", _bounded(payload))

    def to_dict(self):
        return json.loads(self._data_json)

    @property
    def providers(self):
        return self.to_dict()["providers"]

    @property
    def components(self):
        return self.to_dict()["components"]

    @property
    def binding_components(self):
        return self.to_dict().get("binding_components")

    @property
    def execution(self):
        return self.to_dict()["execution"]

    @property
    def identity(self):
        return {
            "kind": "runtime-profile",
            "name": self.name,
            "version": self.version,
            "digest": digest(self.to_dict()),
        }


class TemporalProfileCatalog:
    def __init__(self, *, base_dir=None):
        self.base_dir = Path.cwd().resolve() if base_dir is None else Path(base_dir).resolve()
        self._profiles, self._default = {}, None

    def register(self, profile, *, default=False):
        if not isinstance(profile, TemporalProfile) or type(default) is not bool:
            raise ValidationError("Register a TemporalProfile with a boolean default flag")
        key = (profile.name, profile.version)
        original = self._profiles.get(key)
        if original is not None and original.identity != profile.identity:
            raise DefinitionMismatch("A Temporal profile version cannot change content")
        self._profiles[key] = profile
        if default:
            self._default = key

    def set_default(self, name, version):
        if any(type(value) is not str or not value.strip() for value in (name, version)):
            raise ValidationError("Temporal default selection requires nonempty name and version")
        if (name, version) not in self._profiles:
            raise DefinitionMismatch("The selected Temporal profile is unavailable")
        self._default = (name, version)

    @property
    def default_profile(self):
        if self._default is None:
            raise DefinitionMismatch("No default Temporal profile is selected")
        return self._profiles[self._default]

    @property
    def profiles(self):
        return tuple(TemporalProfile(**item.to_dict()) for item in self._profiles.values())

    def resolve(self, identity):
        identity = runtime_profile_identity(identity)
        original = self._profiles.get((identity["name"], identity["version"]))
        if original is None or original.identity != identity:
            raise DefinitionMismatch("The original Temporal profile is unavailable or changed")
        return original

    def to_dict(self):
        profile = self.default_profile
        return {
            "kind": "temporal-profiles",
            "schema_version": 1,
            "default": {"name": profile.name, "version": profile.version},
            "profiles": [item.to_dict() for item in self._profiles.values()],
        }

    @classmethod
    def from_file(cls, path):
        payload = read_declaration(path)
        if (
            type(payload) is not dict
            or set(payload) != {"kind", "schema_version", "default", "profiles"}
            or payload["kind"] != "temporal-profiles"
            or type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1
            or type(payload["profiles"]) is not list
            or type(payload["default"]) is not dict
            or set(payload["default"]) != {"name", "version"}
            or any(type(v) is not str or not v.strip() for v in payload["default"].values())
        ):
            raise ValidationError(
                "Temporal catalog requires its explicit kind, version and default"
            )
        catalog = cls(base_dir=Path(path).resolve().parent)
        allowed = {"name", "version", "providers", "components", "binding_components", "execution"}
        for item in payload["profiles"]:
            if (
                type(item) is not dict
                or set(item) - allowed
                or any(
                    type(item[name]) is not dict
                    for name in ("components", "execution")
                    if name in item
                )
                or ("binding_components" in item and type(item["binding_components"]) is not list)
            ):
                raise ValidationError("Unknown or incomplete Temporal profile fields")
            try:
                catalog.register(TemporalProfile(**item))
            except TypeError:
                raise ValidationError(
                    "Temporal profiles require name, version and providers"
                ) from None
        catalog.set_default(**payload["default"])
        return catalog
