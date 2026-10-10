"""Versioned scoped selections; no clients or alternate authority in History."""

import copy
from dataclasses import asdict
from types import SimpleNamespace

from .binding_types import BINDING_ROLES, AgentBindingDescriptor, BindingSelection
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .temporal_state import detached
from .types import Scope, digest, submission_request

ROLES = frozenset({"provider", "context", "knowledge", "tool_set", "stage_policy"})


def key(role, selection):
    return digest([role, selection.component_id, selection.version])


def provider_alias(selection):
    return "binding:" + key("provider", selection)


def normalize_request(request):
    from .binding_definitions import AgentDefinition, BoundDefinition, decode_definition

    value = request["definition"]
    if value["kind"] not in {"bound_agent", "bound_definition"}:
        return detached(request)
    wrapper = decode_definition(value)
    if isinstance(wrapper, AgentDefinition):
        spec, selections = wrapper.spec, {"agent": wrapper.bindings.to_dict()}
    elif isinstance(wrapper, BoundDefinition):
        spec, selections = (
            wrapper.definition,
            {k: v.to_dict() for k, v in wrapper.agent_bindings.items()},
        )
    result = submission_request(
        spec, request["input"], budget=request["budget"], session_id=request["session_id"]
    )
    result["agent_bindings"] = selections
    return result


def step_descriptor(request, node):
    path = "agent" if request["definition"]["kind"] == "agent" else f"sequence/steps/{node}"
    return detached(request.get("agent_bindings", {}).get(path, AgentBindingDescriptor().to_dict()))


def validate_descriptor(manifest, descriptor, scope=None):
    descriptor = AgentBindingDescriptor.from_dict(descriptor)
    records = manifest.get("binding_catalog", {}).get("records", {})
    for role in BINDING_ROLES:
        choice = getattr(descriptor, role)
        if choice.mode == "inherit":
            continue
        if role not in ROLES or choice.selector:
            raise ValidationError("Unsupported Temporal binding role or resource selector")
        if choice.mode == "ref":
            record = records.get(key(role, choice))
            if record is None or record["role"] != role:
                raise DefinitionMismatch("Original Temporal binding version unavailable")
            configuration = record["configuration"]
            memory = configuration.get("managed_memory", {}).get("policy", {})
            context = configuration.get("managed_context", {}).get("policy", {})
            if scope is not None and (
                (memory and memory["scope"] != scope)
                or (context.get("kind") == "managed-data-context" and context["scope"] != scope)
            ):
                raise AuthorizationDenied("Selected Temporal component belongs to another Scope")
            if scope is not None and record["scope"] != scope:
                raise AuthorizationDenied("Temporal binding belongs to another Scope")
    return descriptor


def validate_bindings(request, manifest, scope=None):
    from .binding_paths import agent_paths

    selections = request.get("agent_bindings", {})
    if not isinstance(selections, dict) or set(selections) - set(
        agent_paths(request["definition"])
    ):
        raise ValidationError("Temporal binding path does not name an actual declared Agent")
    if selections and manifest["kernel"] != "temporal-3":
        raise DefinitionMismatch("Per-Agent bindings require temporal-3")
    for descriptor in selections.values():
        validate_descriptor(manifest, descriptor, scope)
    memory = manifest.get("managed_memory")
    if memory is not None and scope is not None and memory["policy"]["scope"] != scope:
        raise AuthorizationDenied("Temporal memory belongs to another Scope")


def memory_registration(policy, providers):
    if policy is None:
        return None
    from .managed_memory import stage_identity
    from .temporal_activities import component_identity

    identity = stage_identity(policy, policy.scope)
    if identity["inspection"] != "exact-v1":
        raise ValidationError("Temporal memory requires exact fact inspection v1")
    if "selection" in identity:
        provider = providers.get(policy.provider)
        if provider is None:
            raise DefinitionMismatch("Memory selector provider unavailable")
        identity["selector_provider"] = component_identity(provider, ("complete",))
    from .component_fingerprint import executable_digest

    hooks = {
        "propose": executable_digest(policy.propose),
        "admit": executable_digest(policy.admission.validate),
    }
    if "selection" in identity:
        hooks.update(
            request=executable_digest(policy.request), select=executable_digest(policy.select)
        )
    return {
        "version": 1,
        "policy": identity,
        "implementation": hooks,
        "dispatch_admission": "history-1",
    }


def catalog_registration(runtime):
    catalog = runtime.binding_catalog
    if catalog is None:
        return None
    records = {}
    from .temporal_context import context_registration
    from .temporal_managed_context import registration

    for (role, component_id, version), (component, record) in sorted(catalog._entries.items()):
        if role not in ROLES:
            continue
        choice = BindingSelection.ref(component_id, version)
        component, record = catalog.resolve(role, choice, catalog.scope)
        extra = {}
        if role == "context":
            extra = {
                "context_builder": detached(component.identity),
                "context_registration": context_registration(component),
            }
            managed = registration(SimpleNamespace(context=component, providers=runtime.providers))
            if managed is not None:
                extra["managed_context"] = managed
        elif role == "knowledge":
            from .temporal_activities import component_identity

            extra["knowledge_context"] = component_identity(component, ("references", "validate"))
        elif role == "stage_policy":
            extra["managed_memory"] = memory_registration(component, runtime.providers)
        records[key(role, choice)] = {**record, "configuration": extra}
    return {"version": 1, "scope": asdict(catalog.scope), "records": records}


def effective_manifest(manifest, descriptor):
    choices = validate_descriptor(manifest, descriptor)
    result = detached(manifest)
    for role in ("context", "knowledge", "stage_policy"):
        selection = getattr(choices, role)
        if selection.mode == "inherit":
            continue
        fields = {
            "context": ("context_builder", "context_registration", "managed_context"),
            "knowledge": ("knowledge_context",),
            "stage_policy": ("managed_memory",),
        }[role]
        for field in fields:
            result.pop(field, None)
        if selection.mode == "ref":
            result.update(
                result["binding_catalog"]["records"][key(role, selection)]["configuration"]
            )
    return result


def effective_step(step, manifest, descriptor):
    result = detached(step)
    choices = validate_descriptor(manifest, descriptor)
    if choices.provider.mode == "ref":
        result["provider"] = provider_alias(choices.provider)
    if choices.tool_set.mode == "ref":
        names = manifest["binding_catalog"]["records"][key("tool_set", choices.tool_set)][
            "identity"
        ]["names"]
        if not set(names) <= set(step["tools"]):
            raise AuthorizationDenied("Binding tool set exceeds declared Agent tool grants")
        result["tools"] = names
    elif choices.tool_set.mode == "disabled":
        result["tools"] = []
    return result


def selected_runtime(runtime, request):
    if getattr(runtime, "_selected_host", None) is not None:
        return runtime
    descriptor = request.get("step_bindings", AgentBindingDescriptor().to_dict())
    choices = validate_descriptor(runtime.manifest, descriptor, request.get("scope"))
    view = copy.copy(runtime)
    view._selected_host = runtime
    view._manifest = effective_manifest(runtime.manifest, descriptor)
    for role, attr in (
        ("context", "context"),
        ("knowledge", "knowledge"),
        ("stage_policy", "stage_policy"),
    ):
        selection = getattr(choices, role)
        if selection.mode == "ref":
            component, _ = runtime.binding_catalog.resolve(
                role, selection, Scope(**request["scope"])
            )
            setattr(view, attr, component)
        elif selection.mode == "disabled":
            setattr(view, attr, None)
    return view


def project_child(parent_request, member, request):
    if "agent_bindings" not in parent_request or member == "@planner":
        return request
    prefix = f"{parent_request['definition']['kind']}/" + (
        f"nodes/{member}"
        if parent_request["definition"]["kind"] == "graph"
        else f"members/{member}"
    )
    selections = parent_request["agent_bindings"]
    if request["definition"]["kind"] == "agent":
        values = {"agent": selections[prefix]} if prefix in selections else {}
    else:
        values = {
            p[len(prefix) + 1 :]: v for p, v in selections.items() if p.startswith(prefix + "/")
        }
    return {**request, "agent_bindings": detached(values)}


def request_release_digest(request, manifest):
    value = {"definition": request["definition"], "manifest": manifest}
    if "agent_bindings" in request:
        value["agent_bindings"] = request["agent_bindings"]
    return digest(value)


def capabilities(manifest):
    configurations = [manifest] + [
        r["configuration"] for r in manifest.get("binding_catalog", {}).get("records", {}).values()
    ]
    return {
        "per_agent_bindings": manifest["kernel"] == "temporal-3",
        "automatic_memory": any("managed_memory" in c for c in configurations),
        "automatic_context_compression": any("managed_context" in c for c in configurations),
        "large_tool_result_offload": any(
            c.get("managed_context", {}).get("policy", {}).get("kind") == "managed-data-context"
            for c in configurations
        ),
        "rag": any("knowledge_context" in c for c in configurations),
    }
