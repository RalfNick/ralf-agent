"""Additive pure ContextBuilder registration; native v1 releases stay stable."""

from dataclasses import asdict

from .component_fingerprint import executable_digest
from .context_budget import ContextMeasure
from .errors import ValidationError
from .ports import is_sync_callable
from .types import canonical


def context_registration(builder):
    from .managed_context import ManagedContextPipeline
    from .temporal_activities import component_identity
    from .types import digest

    if isinstance(builder, ManagedContextPipeline):
        policy = builder.identity
        return {
            "identity": component_identity(builder, ("assemble",), synchronous=True),
            "implementation_digest": digest(policy["implementation"]),
            "request_validator": policy["implementation"]["validate_request"],
        }

    result = {
        "identity": component_identity(builder, ("assemble",), synchronous=True),
        "implementation_digest": executable_digest(builder.assemble),
    }
    validator = getattr(builder, "validate_request", None)
    if validator is not None:
        if not is_sync_callable(validator):
            raise ValidationError("Context request validator must be synchronous")
        result["request_validator"] = executable_digest(validator)
    return result


def validate_context(messages, identity, max_chars):
    if (
        type(messages) is not list
        or not messages
        or any(type(m) is not dict for m in messages)
        or type(identity) is not dict
        or len(canonical(messages)) > max_chars
    ):
        raise ValidationError("Invalid or unbounded Temporal model context")


def assemble_context(builder, history, references, max_chars):
    from .temporal_activities import _close_lazy

    value = builder.assemble(history, references, max_chars)
    if type(value) not in {tuple, list} or len(value) != 2:
        _close_lazy(value)
        raise ValidationError("ContextBuilder must return a completed messages/manifest pair")
    try:
        validate_context(value[0], value[1], max_chars)
    except ValidationError:
        _close_lazy(value)
        raise
    return value[0], value[1]


def validate_prepared(builder, messages, max_chars):
    """Validate a detached actual Harness request. Never disclose validator edits."""
    from .temporal_activities import _close_lazy
    from .temporal_state import detached

    validate_context(messages, {}, max_chars)
    validator = getattr(builder, "validate_request", None)
    if validator is None:
        return None
    value = validator(detached(messages), max_chars)
    if not isinstance(value, ContextMeasure):
        _close_lazy(value)
        raise ValidationError("Context validator must return a completed ContextMeasure")
    measurement = asdict(ContextMeasure(value.units, value.unit, value.estimated))
    validate_context(messages, {}, max_chars)
    return measurement
