"""Per-definition component views. No ambient current Agent and no execution state."""

import copy
from dataclasses import dataclass

from .binding_catalog import SELECTABLE_ROLES
from .binding_paths import agent_paths
from .binding_types import AgentBindingDescriptor
from .errors import DefinitionMismatch, ValidationError
from .types import runtime_profile_identity
from .workflow_runtime import agent_step


@dataclass(frozen=True)
class StepComponents:
    provider: object
    harness: object
    context: object
    sessions: object | None
    memory: object | None
    knowledge: object | None
    tools: tuple[str, ...]
    verifier: object | None
    limits: object | None
    stage_policy: object | None = None


def step_path(definition, index, plan=None):
    if definition["kind"] == "graph":
        nodes = definition["nodes"] if plan is None else plan["nodes"]
        return f"graph/nodes/{nodes[index]['id']}"
    return "agent" if definition["kind"] == "agent" else f"sequence/steps/{index}"


def descriptor_for(definition, index, plan=None):
    wrapper = definition["binding_definition"]
    if wrapper["kind"] == "bound_agent":
        return AgentBindingDescriptor.from_dict(wrapper["bindings"])
    value = wrapper["agent_bindings"].get(step_path(definition, index, plan))
    return AgentBindingDescriptor() if value is None else AgentBindingDescriptor.from_dict(value)


class AgentBindingResolver:
    def __init__(self, engine):
        self.engine = engine

    def resolve(self, step, descriptor):
        e = self.engine
        selections = descriptor.to_dict()
        for role, value in selections.items():
            if role == "schema_version":
                continue
            mode = value["mode"]
            if (
                role not in SELECTABLE_ROLES
                and not (role == "session" and mode == "disabled")
                and mode != "inherit"
            ):
                raise ValidationError(f"Binding role is not supported in Local H1a: {role}")
        values = {
            "provider": e.providers.get(step["provider"]),
            "decision_policy": e.harness,
            "context": e.context,
            "session": e.sessions,
            "facts": e.memory,
            "knowledge": e.knowledge,
            "tool_set": tuple(step["tools"]),
        }
        # Inherited legacy bindings retain their exact resolved release records.
        if descriptor.verifier.mode != "inherit" or e.verifier is not None:
            values["verifier"] = e.verifier
        if descriptor.limits.mode != "inherit" or e.limits is not None:
            values["limits"] = e.limits
        if descriptor.stage_policy.mode != "inherit" or e.stage_policy is not None:
            values["stage_policy"] = e.stage_policy
        records = {}
        for role in values:
            selection = getattr(descriptor, role)
            if selection.mode == "ref":
                if e.binding_catalog is None:
                    raise DefinitionMismatch("Binding components require a host BindingCatalog")
                values[role], records[role] = e.binding_catalog.resolve(role, selection, e.scope)
            elif selection.mode == "disabled":
                values[role] = () if role == "tool_set" else None
                records[role] = {"mode": "disabled"}
            else:
                records[role] = {"mode": "inherit"}
        tools = tuple(values["tool_set"])
        if not set(tools).issubset(step["tools"]):
            raise ValidationError("A bound tool set cannot expand AgentSpec tools")
        if values["provider"] is None:
            raise DefinitionMismatch("The selected model provider is unavailable")
        return StepComponents(
            values["provider"],
            values["decision_policy"],
            values["context"],
            values["session"],
            values["facts"],
            values["knowledge"],
            tools,
            values.get("verifier"),
            values.get("limits"),
            values.get("stage_policy"),
        ), records

    def components(self, run, index=None):
        index = run["node"] if index is None else index
        step = agent_step(run, index)
        if "binding_definition" in run["definition"]:
            return self.resolve(step, descriptor_for(run["definition"], index, run.get("plan")))[0]
        e = self.engine
        return StepComponents(
            e.providers[step["provider"]],
            e.harness,
            e.context,
            e.sessions,
            e.memory,
            e.knowledge,
            tuple(step["tools"]),
            e.verifier,
            None,
            e.stage_policy,
        )

    def base_step(self, run, index=None):
        original = agent_step(run, index)
        if "binding_definition" not in run["definition"]:
            return original
        return {**copy.deepcopy(original), "tools": list(self.components(run, index).tools)}

    def effective_step(self, run, index=None):
        from .agent_limits import apply_pinned_limits

        return apply_pinned_limits(
            self.base_step(run, index), self.engine._step_manifest(run, index)
        )

    def tool_action_limit(self, run, index=None):
        from .agent_limits import tool_action_limit

        return tool_action_limit(self.base_step(run, index), self.engine._step_manifest(run, index))

    def manifest(self, definition, *, plan=None):
        entries = {}
        wrapper = definition["binding_definition"]
        source = wrapper["spec"] if wrapper["kind"] == "bound_agent" else wrapper["definition"]
        paths = agent_paths(source)
        for path, step in paths.items():
            descriptor = AgentBindingDescriptor.from_dict(
                wrapper["bindings"]
                if wrapper["kind"] == "bound_agent"
                else wrapper["agent_bindings"].get(path, AgentBindingDescriptor().to_dict())
            )
            components, records = self.resolve(step, descriptor)
            effective = {**copy.deepcopy(step), "tools": list(components.tools)}
            entries[path] = {
                "descriptor": descriptor.to_dict(),
                "resolved": records,
                "manifest": self.engine._manifest([effective], components=components),
            }
        manifest = {
            "kernel": "local-bindings-1",
            "agent_bindings": {"schema_version": 1, "steps": entries},
        }
        if definition["kind"] == "graph":
            plan = self.engine._workflow.compile(definition) if plan is None else plan
            compiled = {
                f"graph/nodes/{node['id']}": node["agent"]
                for node in plan["nodes"]
                if node["agent"] is not None
            }
            if compiled != paths:
                raise DefinitionMismatch("A bound graph compiler changed declared Agent identities")
            base = self.engine._workflow.manifest(
                plan, agent_manifests=[entry["manifest"] for entry in entries.values()]
            )
            manifest = {**base, **manifest, "kernel": "local-bindings-2"}
            manifest["agent_bindings"]["node_paths"] = {
                str(index): f"graph/nodes/{node['id']}" if node["agent"] is not None else None
                for index, node in enumerate(plan["nodes"])
            }
        elif definition["kind"] in {"team", "dynamic"}:
            from .binding_paths import member_spec

            releases = {
                name: self.manifest(unwrap_definition(member_spec(definition, name).to_dict()))
                for name in definition["members"]
            }
            base = self.engine._orchestration.manifest(definition, member_manifests=releases)
            manifest = {**base, **manifest, "kernel": "local-bindings-2"}
        if any(entry["descriptor"]["session"]["mode"] == "ref" for entry in entries.values()):
            manifest["kernel"] = "local-bindings-3"
        if any(
            "resource" in entry["resolved"][role]
            for entry in entries.values()
            for role in ("facts", "knowledge")
        ):
            manifest["kernel"] = "local-bindings-4"
        if any(entry["descriptor"]["verifier"]["mode"] != "inherit" for entry in entries.values()):
            manifest["kernel"] = "local-bindings-5"
        if any(entry["descriptor"]["limits"]["mode"] != "inherit" for entry in entries.values()):
            manifest["kernel"] = "local-bindings-6"
        if any("managed_memory" in entry["manifest"] for entry in entries.values()):
            manifest["kernel"] = "local-bindings-7"
        if any("managed_context" in entry["manifest"] for entry in entries.values()):
            manifest["kernel"] = "local-bindings-8"
        if self.engine.runtime_profile is not None:
            manifest["runtime_profile"] = runtime_profile_identity(self.engine.runtime_profile)
        if any(
            "selection" in entry["manifest"].get("managed_memory", {}) for entry in entries.values()
        ):
            manifest["kernel"] = "local-bindings-9"
        return manifest


def unwrap_definition(wrapper):
    from .binding_definitions import AgentDefinition, decode_definition
    from .types import submission_request

    restored = decode_definition(wrapper)
    spec = restored.spec if isinstance(restored, AgentDefinition) else restored.definition
    definition = submission_request(spec, None)["definition"]
    return {**definition, "binding_definition": restored.to_dict()}


def binding_capabilities():
    return {
        "schema_version": 1,
        "supported_definition_kinds": [
            "bound_agent",
            "bound_definition:sequence",
            "bound_definition:graph",
            "bound_definition:team",
            "bound_definition:dynamic",
        ],
        "supported_binding_roles": sorted(SELECTABLE_ROLES),
        "session_modes": ["inherit", "ref", "disabled"],
        "resource_selectors": True,
        "resource_selector_roles": {
            "session": ["namespace"],
            "facts": ["namespace"],
            "knowledge": ["namespace"],
        },
        "session_resource_admission": True,
        "required_stage_kinds": ["model", "tool"],
        "session_admission": False,
    }
