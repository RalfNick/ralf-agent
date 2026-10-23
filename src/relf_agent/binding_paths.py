"""Stable declaration paths; no registry lookups or execution authority."""

import copy

from .spec_codec import validate_definition_tree


def agent_paths(definition):
    """Detach leaves while preserving legacy native acceptance limits."""
    result = {}

    def visit(value, prefix=""):
        kind = value.get("kind", "agent")
        if kind == "agent":
            result[prefix or "agent"] = value.get("steps", [value])[0]
        elif kind == "sequence":
            for index, step in enumerate(value["steps"]):
                result[f"{prefix}sequence/steps/{index}"] = step
        elif kind == "graph":
            for node in value["nodes"]:
                if node["agent"] is not None:
                    result[f"{prefix}graph/nodes/{node['id']}"] = node["agent"]
        else:
            for name, member in value["members"].items():
                path = f"{prefix}{kind}/members/{name}"
                visit(member, path + "/" if member.get("kind", "agent") != "agent" else path)

    # Native H1a did not impose composite tree limits on valid AgentSpec fields.
    # Sequence/composite declarations retain their existing codec limits.
    source = (
        copy.deepcopy(definition)
        if definition.get("kind", "agent") == "agent"
        else validate_definition_tree(definition)
    )
    visit(source)
    return result


def member_spec(definition, name):
    """Project only a registered member's binding subtree into its child declaration."""
    from .binding_definitions import AgentDefinition, BoundDefinition
    from .binding_types import AgentBindingDescriptor
    from .spec_codec import decode_spec

    member = definition["members"][name]
    spec = decode_spec(member)
    wrapper = definition.get("binding_definition")
    if wrapper is None:
        return spec
    prefix = f"{definition['kind']}/members/{name}"
    bindings = wrapper["agent_bindings"]
    if member.get("kind", "agent") == "agent":
        descriptor = AgentBindingDescriptor.from_dict(
            bindings.get(prefix, AgentBindingDescriptor().to_dict())
        )
        return AgentDefinition(spec, descriptor)
    return BoundDefinition(
        spec,
        {
            path[len(prefix) + 1 :]: AgentBindingDescriptor.from_dict(value)
            for path, value in bindings.items()
            if path.startswith(prefix + "/")
        },
    )


def has_disabled_session(spec):
    from .binding_definitions import AgentDefinition, BoundDefinition

    if isinstance(spec, AgentDefinition):
        return spec.bindings.session.mode == "disabled"
    return isinstance(spec, BoundDefinition) and any(
        value.session.mode == "disabled" for value in spec.agent_bindings.values()
    )
