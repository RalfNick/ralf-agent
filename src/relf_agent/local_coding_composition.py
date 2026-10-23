"""Selected Local Coding composition gates; no scheduling or native authority."""

from .binding_manifests import all_step_manifests, merge_coding_manifests
from .errors import DefinitionMismatch


def mark_composition(engine, manifest, definition, parent_call=None):
    """Aggregate only recorded selected releases and preserve legacy root bytes."""
    views, pending, seen = [], [manifest], set()
    explicit = False
    while pending:
        current = pending.pop()
        if id(current) in seen:
            raise DefinitionMismatch("Selected Coding releases are cyclic")
        seen.add(id(current))
        if len(seen) > 10000:
            raise DefinitionMismatch("Selected Coding releases are unbounded")
        views.extend(all_step_manifests(current))
        entries = current.get("agent_bindings", {}).get("steps", {})
        explicit = explicit or any("runner" in entry["descriptor"] for entry in entries.values())
        pending.extend(current.get("orchestration", {}).get("members", {}).values())
    merge_coding_manifests(manifest, views)
    coding = bool(manifest.get("delegated_coding_tools"))
    if (coding or explicit) and (
        definition["kind"] in {"graph", "team", "dynamic"} or parent_call is not None
    ):
        manifest.update(
            kernel="local-bindings-19" if "agent_bindings" in manifest else "local-11",
            delegated_composition_protocol=1,
        )
    return manifest
