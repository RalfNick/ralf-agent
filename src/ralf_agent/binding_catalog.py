"""Trusted, scoped borrowed components. This registry grants no host permissions."""

import copy
from dataclasses import asdict

from .binding_types import BindingSelection, text
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .ports import validate_component_identity
from .types import Scope, canonical, digest

SELECTABLE_ROLES = frozenset(
    {
        "provider",
        "decision_policy",
        "context",
        "session",
        "facts",
        "knowledge",
        "tool_set",
        "verifier",
        "limits",
        "stage_policy",
        "workspace",
        "skills",
        "sandbox",
        "artifacts",
        "model_history",
        "runner",
    }
)


def component_identity(role, component):
    if role == "model_history":
        from .model_history import model_history_registration

        return model_history_registration(component)

    if role == "runner":
        from .binding_runner import runner_registration

        return runner_registration(component)

    if role == "artifacts":
        from .binding_artifacts import ArtifactBindingResource

        if type(component) is not ArtifactBindingResource:
            raise ValidationError("Artifact bindings require an original scoped store resource")
        return component.identity

    if role == "sandbox":
        from .binding_sandbox import SandboxBindingResource

        if type(component) is not SandboxBindingResource:
            raise ValidationError("Sandbox bindings require an original registered-tool resource")
        return component.identity

    if role == "skills":
        from .binding_skills import SkillBindingResource

        if type(component) is not SkillBindingResource:
            raise ValidationError("Skills bindings require an original registered-tool resource")
        return component.identity
    if role == "workspace":
        from .binding_workspace import WorkspaceBindingResource

        if type(component) is not WorkspaceBindingResource:
            raise ValidationError("Workspace bindings require an original registered-tool resource")
        return component.identity
    if role == "session":
        from .binding_sessions import SessionBindingResource, session_identity

        return (
            component.identity
            if isinstance(component, SessionBindingResource)
            else session_identity(component)
        )
    if role == "tool_set":
        if not isinstance(component, (tuple, list)) or any(
            not isinstance(n, str) or not n.strip() for n in component
        ):
            raise ValidationError("Tool set requires tool names")
        if len(set(component)) != len(component):
            raise ValidationError("Tool set names must be unique")
        return {"kind": "tool-set", "names": list(component)}
    if role == "facts":
        from .binding_data import FactsBindingResource, facts_identity

        return (
            component.identity
            if isinstance(component, FactsBindingResource)
            else facts_identity(component)
        )
    if role == "context":
        return validate_component_identity(
            component, ("assemble",), synchronous=True, label="Context"
        )
    if role == "knowledge":
        from .binding_data import KnowledgeBindingResource, KnowledgeView
        from .recall import _integer

        if isinstance(component, KnowledgeBindingResource):
            return component.identity
        if isinstance(component, KnowledgeView):
            raise ValidationError("Register the original Knowledge context or resource, not a view")
        _integer(getattr(component, "limit", None), "Knowledge reference limit", 1)
        _integer(getattr(component, "max_chars", None), "Knowledge character limit", 2)
        return validate_component_identity(component, ("references", "validate"), label="Knowledge")
    if role == "decision_policy":
        return validate_component_identity(
            component, ("prepare", "propose"), synchronous=True, label="Decision policy"
        )
    if role == "provider":
        return validate_component_identity(component, ("complete",), label="Provider")
    if role == "verifier":
        return validate_component_identity(
            component, ("verify",), synchronous=True, label="Completion verifier"
        )
    if role == "limits":
        return validate_component_identity(
            component, ("propose",), synchronous=True, label="Agent limits"
        )
    if role == "stage_policy":
        from .managed_memory import stage_identity

        return stage_identity(component, component.scope)
    raise ValidationError("Binding role is not selectable in Local H1a")


class BindingCatalog:
    """Components registered here are borrowed, scoped to one trusted host Scope."""

    def __init__(self, *, scope):
        if not isinstance(scope, Scope):
            raise ValidationError("Binding catalog requires trusted Scope")
        self._scope, self._entries = scope, {}
        self._model_history_pins = {}
        self._runner_pins = {}

    @property
    def scope(self):
        return self._scope

    def register(self, role, component_id, version, component):
        if not isinstance(role, str) or role not in SELECTABLE_ROLES:
            raise ValidationError("Unsupported binding component role")
        text(component_id, "Binding component ID")
        text(version, "Binding component version")
        identity = component_identity(role, component)
        if role == "tool_set":
            component = tuple(component)
        key = role, component_id, version
        if key in self._entries:
            original, record = self._entries[key]
            if role == "model_history":
                check_model_history_binding(original, self._model_history_pins[key])
            if role == "runner":
                from .binding_runner import check_runner_binding

                check_runner_binding(original, self._runner_pins[key])
            if original is not component or digest(record["identity"]) != digest(identity):
                raise DefinitionMismatch("Registered binding version cannot be replaced")
            return
        if role == "model_history":
            self._model_history_pins[key] = pin_model_history_binding(component)
        if role == "runner":
            from .binding_runner import pin_runner_binding

            self._runner_pins[key] = pin_runner_binding(component)
        self._entries[key] = (
            component,
            {
                "role": role,
                "component_id": component_id,
                "version": version,
                "interface_version": 1,
                "identity": copy.deepcopy(identity),
                "scope": asdict(self.scope),
            },
        )

    def unregister(self, role, component_id, version):
        self._entries.pop((role, component_id, version), None)
        self._model_history_pins.pop((role, component_id, version), None)
        self._runner_pins.pop((role, component_id, version), None)

    def resolve(self, role, selection, scope):
        if not isinstance(role, str) or role not in SELECTABLE_ROLES:
            raise ValidationError("Unsupported binding component role")
        if scope != self.scope:
            raise AuthorizationDenied("Binding catalog belongs to a different trusted Scope")
        if not isinstance(selection, BindingSelection) or selection.mode != "ref":
            raise ValidationError("Catalog resolution requires a reference binding")
        if selection.selector and role not in {"session", "facts", "knowledge", "artifacts"}:
            raise ValidationError("Resource selectors are not supported in Local H1a")
        entry = self._entries.get((role, selection.component_id, selection.version))
        if entry is None:
            raise DefinitionMismatch("Original binding component is unavailable")
        component, record = entry
        if role == "model_history":
            check_model_history_binding(
                component,
                self._model_history_pins[(role, selection.component_id, selection.version)],
            )
        if role == "runner":
            from .binding_runner import check_runner_binding

            identity = check_runner_binding(
                component, self._runner_pins[(role, selection.component_id, selection.version)]
            )
        else:
            identity = component_identity(role, component)
        if digest(identity) != digest(record["identity"]):
            raise DefinitionMismatch("Registered binding component identity changed")
        if role == "artifacts":
            view = component.select(selection.selector, scope)
            return view, {**copy.deepcopy(record), "resource": view.resource}
        if role in {"facts", "knowledge"}:
            from .binding_data import FactsBindingResource, KnowledgeBindingResource

            if isinstance(component, (FactsBindingResource, KnowledgeBindingResource)):
                view = component.select(selection.selector, scope)
                return view, {**copy.deepcopy(record), "resource": view.resource}
            if selection.selector:
                raise ValidationError("Data namespace selectors require an explicit host resource")
        if role == "session":
            from .binding_sessions import SessionBindingResource

            resource = (
                component
                if isinstance(component, SessionBindingResource)
                else SessionBindingResource(component)
            )
            view = resource.select(selection.selector, scope)
            return view, {**copy.deepcopy(record), "resource": view.resource}
        canonical(record)
        return component, copy.deepcopy(record)


def pin_model_history_binding(policy):
    """Keep the original pure methods as well as their persistent registration."""
    from .binding_artifacts import _method_binding
    from .model_history import model_history_registration

    registration = model_history_registration(policy)
    return (
        policy,
        registration,
        {name: _method_binding(getattr(policy, name)) for name in registration["implementation"]},
    )


def check_model_history_binding(policy, pin):
    from .binding_artifacts import _method_matches
    from .model_history import model_history_registration

    original, registration, methods = pin
    if policy is not original or any(
        not _method_matches(getattr(policy, name, None), binding)
        for name, binding in methods.items()
    ):
        raise DefinitionMismatch("Original model history policy or method changed")
    if model_history_registration(policy) != registration:
        raise DefinitionMismatch("Original model history registration changed")
    return copy.deepcopy(registration)
