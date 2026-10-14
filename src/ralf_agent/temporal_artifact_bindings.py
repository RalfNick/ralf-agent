"""Fixed pure Context templates; original History alone selects and adopts them."""

import copy
from types import SimpleNamespace

from .artifact_binding_context import binding_supported, validate_prediction
from .errors import DefinitionMismatch, ValidationError
from .types import canonical, digest


def origin_key(role, component_id=None, version=None):
    return digest([role, component_id, version])


def selection_key(resource, namespace):
    return digest([resource, namespace])


def registration(runtime, catalog):
    from .binding_types import BindingSelection
    from .runtime_builder import _completed
    from .temporal_bindings import key
    from .temporal_context import context_registration
    from .temporal_managed_context import registration as managed_registration

    resources = (
        [
            (key("artifacts", BindingSelection.ref(cid, version)), component)
            for (role, cid, version), (component, _) in runtime.binding_catalog._entries.items()
            if role == "artifacts"
        ]
        if runtime.binding_catalog is not None
        else []
    )
    if not resources and not runtime.artifact_bindings:
        return None
    origins = [(origin_key("inherit"), runtime.context)] + [
        (origin_key("ref", cid, version), component)
        for (role, cid, version), (component, _) in runtime.binding_catalog._entries.items()
        if role == "context"
    ]
    entries = {}
    for identifier, origin in origins:
        if not binding_supported(origin):
            continue
        targets = [(selection_key(None, None), None)]
        for resource_id, resource in resources:
            targets.extend(
                (
                    selection_key(resource_id, name),
                    resource.select({"namespace": name}, runtime.binding_catalog.scope),
                )
                for name in resource.identity["namespaces"]
            )
        choices = {}
        for choice, target in targets:
            metadata = None if target is None else target.identity
            expected = _completed(
                origin.artifact_binding_identity(copy.deepcopy(metadata)), "Artifact prediction"
            )
            if type(expected) is not dict:
                raise ValidationError("Artifact prediction requires ordinary Context identity")
            validate_prediction(origin.identity, metadata, expected)
            selected = _completed(origin.bind_artifacts(target), "Artifact Context")
            from .managed_context import ManagedContextPipeline

            if not isinstance(selected, ManagedContextPipeline) or selected.identity != expected:
                raise DefinitionMismatch("Artifact Context differs from published prediction")
            managed = managed_registration(
                SimpleNamespace(context=selected, providers=runtime.providers)
            )
            choices[choice] = {
                "resource": metadata,
                "configuration": {
                    "context_builder": expected,
                    "context_registration": context_registration(selected),
                    "managed_context": managed,
                },
            }
        entries[identifier] = {"origin": origin.identity, "choices": choices}
    value = {"version": 1, "contexts": entries}
    if len(canonical(value).encode("utf-8")) > 1048576:
        raise ValidationError("Artifact Context registration exceeds one MiB")
    return value


def validate_protocol(manifest):
    records = manifest.get("binding_catalog", {}).get("records", {})
    enabled = any(record.get("role") == "artifacts" for record in records.values())
    if (
        not enabled
        and "artifacts_binding_protocol" not in manifest
        and manifest.get("binding_protocol") != 5
    ):
        if "artifact_contexts" in manifest:
            raise DefinitionMismatch("Artifact Context templates require original protocol")
        return
    value = manifest.get("artifact_contexts")
    if (
        manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"] not in (5, 6, 7, 8, 9, 10, 11, 12, 13)
        or type(manifest.get("artifacts_binding_protocol")) is not int
        or manifest["artifacts_binding_protocol"] != 1
        or type(value) is not dict
        or set(value) != {"version", "contexts"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or type(value["contexts"]) is not dict
    ):
        raise DefinitionMismatch("Unsupported original Artifact binding protocol")
    if len(canonical(value).encode("utf-8")) > 1048576:
        raise DefinitionMismatch("Artifact Context registration exceeds its bound")
    origins = {
        origin_key("inherit"): (manifest["context_builder"], manifest.get("managed_context"))
    }
    for record in records.values():
        if record.get("role") == "context":
            config = record["configuration"]
            origins[origin_key("ref", record["component_id"], record["version"])] = (
                config["context_builder"],
                config.get("managed_context"),
            )
    targets = {selection_key(None, None): None}
    for identifier, record in records.items():
        if record.get("role") == "artifacts":
            resource = record.get("identity")
            if (
                type(resource) is not dict
                or resource.get("kind") != "artifact-binding-resource"
                or resource.get("version") != "1"
                or type(resource.get("backend")) is not dict
                or type(resource.get("namespaces")) is not list
                or resource.get("default_namespace") not in resource["namespaces"]
            ):
                raise DefinitionMismatch("Artifact registration lost original resource")
            for namespace in resource["namespaces"]:
                targets[selection_key(identifier, namespace)] = {
                    "kind": "artifact-binding-view",
                    "version": "1",
                    "backend_id": resource["backend"].get("backend_id"),
                    "target": resource,
                    "scope": record["scope"],
                    "namespace": namespace,
                }
    for identifier, context in value["contexts"].items():
        if (
            type(context) is not dict
            or set(context) != {"origin", "choices"}
            or type(context["origin"]) is not dict
            or type(context["choices"]) is not dict
        ):
            raise DefinitionMismatch("Invalid original Artifact Context metadata")
        original = origins.get(identifier)
        if (
            original is None
            or context["origin"] != original[0]
            or original[1] is None
            or set(context["choices"]) != set(targets)
        ):
            raise DefinitionMismatch("Artifact templates differ from original Context registration")
        for choice_key, choice in context["choices"].items():
            if type(choice) is not dict or set(choice) != {"resource", "configuration"}:
                raise DefinitionMismatch("Invalid Artifact prediction")
            if choice["resource"] != targets[choice_key]:
                raise DefinitionMismatch(
                    "Artifact template differs from original selected resource"
                )
            config = choice["configuration"]
            if (
                type(config) is not dict
                or set(config) != {"context_builder", "context_registration", "managed_context"}
                or type(config["context_builder"]) is not dict
                or type(config["managed_context"]) is not dict
                or config["managed_context"].get("policy") != config["context_builder"]
                or type(config["context_registration"]) is not dict
                or config["context_registration"].get("identity") != config["context_builder"]
            ):
                raise DefinitionMismatch("Artifact Context prediction lost its original policy")
            binding = config["context_builder"].get("artifact_binding", {})
            if (
                binding
                != {
                    "version": 1,
                    "mode": "disabled" if choice["resource"] is None else "ref",
                    "origin": original[0],
                    "resource": choice["resource"],
                }
                or config["managed_context"].get("provider") != original[1].get("provider")
                or config["managed_context"].get("version") != 1
                or config["managed_context"].get("summary_credits") != 1
                or config["managed_context"].get("dispatch_admission") != "history-1"
            ):
                raise DefinitionMismatch("Artifact Context lost its original policy and provider")
            policy = validate_prediction(original[0], choice["resource"], config["context_builder"])
            implementation = policy.get("implementation")
            if (
                type(implementation) is not dict
                or "validate_request" not in implementation
                or set(config["context_registration"])
                != {"identity", "implementation_digest", "request_validator"}
                or config["context_registration"]["implementation_digest"] != digest(implementation)
                or config["context_registration"]["request_validator"]
                != implementation["validate_request"]
            ):
                raise DefinitionMismatch("Artifact Context implementation registration differs")


def effective(manifest, choices, origin):
    if choices.artifacts.mode == "inherit":
        return None
    if choices.artifacts.mode == "disabled" and manifest.get("parent_completion_protocol") == 1:
        identifier = origin_key(
            choices.context.mode, choices.context.component_id, choices.context.version
        )
        if identifier not in manifest.get("artifact_contexts", {}).get("contexts", {}):
            return None
    validate_protocol(manifest)
    selection = choices.context
    identifier = origin_key(selection.mode, selection.component_id, selection.version)
    context = manifest["artifact_contexts"]["contexts"].get(identifier)
    if context is None or context["origin"] != origin:
        raise DefinitionMismatch("Selected Context has no original Artifact prediction port")
    target = choices.artifacts
    resource, namespace = None, None
    if target.mode == "ref":
        from .temporal_bindings import key

        resource = key("artifacts", target)
        identity = manifest["binding_catalog"]["records"][resource]["identity"]
        namespace = target.selector.get("namespace", identity["default_namespace"])
    value = context["choices"].get(selection_key(resource, namespace))
    if value is None:
        raise DefinitionMismatch("Original Artifact Context selection unavailable")
    return value["configuration"]
