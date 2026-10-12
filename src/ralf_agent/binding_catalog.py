"""Trusted, scoped borrowed components. This registry grants no host permissions."""

import copy
from dataclasses import asdict

from .binding_types import BindingSelection, text
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .ports import is_sync_callable
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
    }
)


def component_identity(role, component):
    from .engine import LocalEngine

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
        if not is_sync_callable(getattr(component, "assemble", None)):
            raise ValidationError("Context assemble must be synchronous")
        return LocalEngine._component_identity(component, ("assemble",), True, "Context")
    if role == "knowledge":
        from .binding_data import KnowledgeBindingResource, KnowledgeView
        from .recall import _integer

        if isinstance(component, KnowledgeBindingResource):
            return component.identity
        if isinstance(component, KnowledgeView):
            raise ValidationError("Register the original Knowledge context or resource, not a view")
        _integer(getattr(component, "limit", None), "Knowledge reference limit", 1)
        _integer(getattr(component, "max_chars", None), "Knowledge character limit", 2)
        return LocalEngine._component_identity(
            component, ("references", "validate"), False, "Knowledge"
        )
    if role == "decision_policy":
        return LocalEngine._component_identity(
            component, ("prepare", "propose"), True, "Decision policy"
        )
    if role == "provider":
        return LocalEngine._component_identity(component, ("complete",), False, "Provider")
    if role == "verifier":
        return LocalEngine._component_identity(component, ("verify",), True, "Completion verifier")
    if role == "limits":
        return LocalEngine._component_identity(component, ("propose",), True, "Agent limits")
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
            if original is not component or digest(record["identity"]) != digest(identity):
                raise DefinitionMismatch("Registered binding version cannot be replaced")
            return
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

    def resolve(self, role, selection, scope):
        if not isinstance(role, str) or role not in SELECTABLE_ROLES:
            raise ValidationError("Unsupported binding component role")
        if scope != self.scope:
            raise AuthorizationDenied("Binding catalog belongs to a different trusted Scope")
        if not isinstance(selection, BindingSelection) or selection.mode != "ref":
            raise ValidationError("Catalog resolution requires a reference binding")
        if selection.selector and role not in {"session", "facts", "knowledge"}:
            raise ValidationError("Resource selectors are not supported in Local H1a")
        entry = self._entries.get((role, selection.component_id, selection.version))
        if entry is None:
            raise DefinitionMismatch("Original binding component is unavailable")
        component, record = entry
        if digest(component_identity(role, component)) != digest(record["identity"]):
            raise DefinitionMismatch("Registered binding component identity changed")
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
