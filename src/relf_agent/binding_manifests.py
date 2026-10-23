"""Read fixed binding manifests without resolving clients or current configuration."""

import copy

from .errors import DefinitionMismatch, ValidationError


def merge_coding_manifests(manifest, selected_manifests):
    """Union only actual selected release grants, retaining exact tool identities."""
    coding = copy.deepcopy(manifest.get("delegated_coding_tools", {}))
    for selected in selected_manifests:
        for name, record in selected.get("delegated_coding_tools", {}).items():
            if name in coding and coding[name] != record:
                raise DefinitionMismatch("A selected Coding tool changed between releases")
            coding[name] = copy.deepcopy(record)
    if coding:
        manifest.update(delegated_execution_protocol=1, delegated_coding_tools=coding)
    return manifest


def all_step_manifests(manifest):
    if "agent_bindings" not in manifest:
        return [manifest]
    try:
        entries = manifest["agent_bindings"]["steps"]
        if not isinstance(entries, dict) or (
            not entries
            and not (
                manifest.get("kernel")
                in {
                    "local-bindings-2",
                    "local-bindings-3",
                    "local-bindings-16",
                    "local-bindings-17",
                }
                or (
                    manifest.get("kernel") == "local-bindings-19"
                    and manifest.get("delegated_composition_protocol") == 1
                )
            )
        ):
            raise ValidationError("Binding manifest requires recorded steps")
        return ([manifest] if "providers" in manifest else []) + [
            entry["manifest"] for entry in entries.values()
        ]
    except (KeyError, TypeError) as exc:
        raise ValidationError("Invalid recorded binding manifest") from exc


def step_manifest(manifest, index):
    if "agent_bindings" not in manifest:
        return manifest
    if type(index) is not int or index < 0:
        raise ValidationError("Binding action requires a non-negative step index")
    try:
        entries = manifest["agent_bindings"]["steps"]
        if "node_paths" in manifest["agent_bindings"]:
            path = manifest["agent_bindings"]["node_paths"][str(index)]
            return manifest if path is None else entries[path]["manifest"]
        path = "agent" if "agent" in entries and index == 0 else f"sequence/steps/{index}"
        return entries[path]["manifest"]
    except (KeyError, TypeError) as exc:
        raise ValidationError("Action does not belong to a recorded binding step") from exc
