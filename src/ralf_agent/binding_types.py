"""Immutable, caller-owned capability choices; no clients, factories or secrets."""

import json
from dataclasses import dataclass

from .errors import ValidationError
from .types import canonical

BINDING_ROLES = (
    "provider",
    "decision_policy",
    "context",
    "session",
    "facts",
    "knowledge",
    "artifacts",
    "tool_set",
    "workspace",
    "sandbox",
    "skills",
    "verifier",
    "stage_policy",
    "limits",
)
MODEL_HISTORY_ROLE = "model_history"
RUNNER_ROLE = "runner"
REQUIRED_ROLES = frozenset({"provider", "decision_policy", "context"})


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True, init=False)
class BindingSelection:
    mode: str
    component_id: str | None
    version: str | None
    _selector_json: str

    def __init__(self, mode="inherit", *, component_id=None, version=None, selector=None):
        if not isinstance(mode, str) or mode not in {"inherit", "ref", "disabled"}:
            raise ValidationError("Binding mode must be inherit, ref or disabled")
        if mode == "ref":
            text(component_id, "Binding component ID")
            text(version, "Binding version")
        elif component_id is not None or version is not None or selector is not None:
            raise ValidationError("Only reference bindings accept component identities/selectors")
        selector = {} if selector is None else selector
        if not isinstance(selector, dict):
            raise ValidationError("Binding selector must be a finite JSON object")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "component_id", component_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "_selector_json", canonical(selector))

    @classmethod
    def inherit(cls):
        return cls()

    @classmethod
    def disabled(cls):
        return cls("disabled")

    @classmethod
    def ref(cls, component_id, version, *, selector=None):
        return cls("ref", component_id=component_id, version=version, selector=selector)

    @property
    def selector(self):
        return json.loads(self._selector_json)

    def to_dict(self):
        if self.mode != "ref":
            return {"mode": self.mode}
        value = {"mode": "ref", "component_id": self.component_id, "version": self.version}
        if self.selector:
            value["selector"] = self.selector
        return value

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or "mode" not in value:
            raise ValidationError("Binding choice must be an explicit object")
        allowed = (
            {"mode", "component_id", "version", "selector"} if value["mode"] == "ref" else {"mode"}
        )
        if set(value) - allowed or (
            "selector" in value and not isinstance(value["selector"], dict)
        ):
            raise ValidationError("Unknown or invalid binding fields")
        try:
            return cls(**value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Invalid binding selection") from exc


@dataclass(frozen=True, init=False)
class AgentBindingDescriptor:
    _json: str

    def __init__(self, **selections):
        roles = (
            *BINDING_ROLES,
            *(role for role in (MODEL_HISTORY_ROLE, RUNNER_ROLE) if role in selections),
        )
        if set(selections) - set(roles):
            raise ValidationError("Unknown Agent binding role")
        normalized = {}
        for role in roles:
            selection = selections.get(role, BindingSelection.inherit())
            if isinstance(selection, dict):
                if role == RUNNER_ROLE and "selector" in selection:
                    raise ValidationError("Runner bindings do not accept resource selectors")
                selection = BindingSelection.from_dict(selection)
            if not isinstance(selection, BindingSelection):
                raise ValidationError("Binding choices cannot be null or runtime objects")
            if role in REQUIRED_ROLES and selection.mode == "disabled":
                raise ValidationError(f"Required binding cannot be disabled: {role}")
            if role == RUNNER_ROLE and selection.selector:
                raise ValidationError("Runner bindings do not accept resource selectors")
            normalized[role] = selection.to_dict()
        version = 3 if RUNNER_ROLE in selections else 2 if MODEL_HISTORY_ROLE in selections else 1
        object.__setattr__(self, "_json", canonical({"schema_version": version, **normalized}))

    def __getattr__(self, name):
        if name in (MODEL_HISTORY_ROLE, RUNNER_ROLE):
            return BindingSelection.from_dict(json.loads(self._json).get(name, {"mode": "inherit"}))
        if name in BINDING_ROLES:
            return BindingSelection.from_dict(json.loads(self._json)[name])
        raise AttributeError(name)

    def to_dict(self):
        return json.loads(self._json)

    @classmethod
    def from_dict(cls, value):
        if (
            not isinstance(value, dict)
            or type(value.get("schema_version")) is not int
            or value["schema_version"] not in {1, 2, 3}
        ):
            raise ValidationError("Binding descriptor requires schema_version=1, 2 or 3")
        version = value["schema_version"]
        roles = (
            (*BINDING_ROLES, MODEL_HISTORY_ROLE, RUNNER_ROLE)
            if version == 3
            else (*BINDING_ROLES, MODEL_HISTORY_ROLE)
            if version == 2
            else BINDING_ROLES
        )
        if (
            set(value) - {"schema_version", *roles}
            or (version == 2 and MODEL_HISTORY_ROLE not in value)
            or (version == 3 and RUNNER_ROLE not in value)
        ):
            raise ValidationError("Binding descriptor fields differ from its schema version")
        return cls(**{k: v for k, v in value.items() if k != "schema_version"})
