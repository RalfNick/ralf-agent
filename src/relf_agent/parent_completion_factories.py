"""Pure parent-policy declarations; owned model I/O stays with the authority."""

from .binding_types import AgentBindingDescriptor
from .errors import ValidationError
from .runtime_config import component_declaration
from .types import _require_text


def _fields(value, allowed, required=()):
    if type(value) is not dict or set(value) - set(allowed) or set(required) - set(value):
        raise ValidationError("Invalid parent completion declaration fields")


def _gate(declaration):
    from .parent_completion_rules import InventoryParentCompletionGate, ReceiptParentCompletionGate

    value = component_declaration(declaration)
    config = value["config"]
    if value["adapter"] == "receipt-rules":
        _fields(config, {"rules", "required_members", "candidate_schema", "on_missing"}, {"rules"})
        return ReceiptParentCompletionGate(**config)
    if value["adapter"] == "inventory":
        _fields(
            config,
            {"dataset", "request_pointer", "researcher_path", "writer_path", "on_missing"},
            {"dataset"},
        )
        return InventoryParentCompletionGate(**config)
    raise ValidationError("Unknown parent completion gate adapter")


def _stage(declaration):
    from .parent_verification_stage import ModelParentVerificationStage

    value = component_declaration(declaration)
    if value["adapter"] != "model":
        raise ValidationError("Unknown parent verification stage adapter")
    config = value["config"]
    _fields(
        config,
        {"provider", "instructions", "bindings", "version", "model_credits", "max_context_chars"},
    )
    if "bindings" in config:
        config["bindings"] = AgentBindingDescriptor.from_dict(config["bindings"])
    return ModelParentVerificationStage(**config)


def configured_parent_completion(config, context=None):
    from .parent_completion import ParentCompletionPolicy
    from .parent_completion_protocol import validate_policy

    _fields(config, {"policies"}, {"policies"})
    if type(config["policies"]) is not dict or not config["policies"]:
        raise ValidationError("Parent completion policies require named registrations")
    result = {}
    for name, value in config["policies"].items():
        _require_text(name, "Parent completion policy registration")
        _fields(
            value,
            {
                "gate",
                "model_stage",
                "verifier_budget",
                "max_source_bytes",
                "max_receipts",
                "max_evidence_children",
            },
            {"gate"},
        )
        options = {k: v for k, v in value.items() if k not in {"gate", "model_stage"}}
        options["model_stage"] = (
            None if value.get("model_stage") is None else _stage(value["model_stage"])
        )
        try:
            policy = ParentCompletionPolicy(_gate(value["gate"]), **options)
            validate_policy(policy)
        except (TypeError, KeyError, AttributeError) as exc:
            raise ValidationError("Invalid parent completion policy configuration") from exc
        result[name] = policy
    return result


def parent_completion_config(config):
    configured_parent_completion(config)


def preflight_parent_completion_providers(profile):
    """Resolve declared model aliases/refs before constructing owned resources."""
    declaration = profile.components.get("parent_completion_policies")
    if declaration is None or declaration["adapter"] != "configured":
        return
    config = declaration["config"]
    _fields(config, {"policies"}, {"policies"})
    if type(config["policies"]) is not dict:
        raise ValidationError("Parent completion policies require named registrations")
    bindings = {
        (item["role"], item["component_id"], item["version"]): item["component"]
        for item in profile.binding_components or []
    }
    for value in config["policies"].values():
        if type(value) is not dict:
            raise ValidationError("Invalid parent completion policy configuration")
        declaration = value.get("model_stage")
        if declaration is None:
            continue
        stage = component_declaration(declaration)
        if stage["adapter"] != "model":
            raise ValidationError("Unknown parent verification stage adapter")
        options = stage["config"]
        descriptor = (
            AgentBindingDescriptor.from_dict(options["bindings"])
            if "bindings" in options
            else AgentBindingDescriptor()
        )
        selected = descriptor.provider
        if selected.mode == "ref":
            if ("provider", selected.component_id, selected.version) not in bindings:
                raise ValidationError("Parent verification provider reference is unavailable")
        else:
            provider = options.get("provider", "default")
            if not isinstance(provider, str) or provider not in profile.providers:
                raise ValidationError("Parent verification provider alias is unavailable")
        context = descriptor.context
        if context.mode == "ref":
            selected_context = bindings.get(("context", context.component_id, context.version))
            if selected_context is None:
                raise ValidationError("Parent verification context reference is unavailable")
        else:
            selected_context = profile.components.get("context_assembler", {"adapter": "default"})
        if selected_context["adapter"] not in {"default", "budgeted"}:
            raise ValidationError(
                "Parent verification requires an explicit pure context declaration"
            )
