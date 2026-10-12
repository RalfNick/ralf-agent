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


def protect_history(runtime, history, messages):
    """Pinned pure policy plus unconditional original-chain protection."""
    from .model_history import validate_model_history
    from .temporal_activities import _completed_none
    from .temporal_state import detached

    runtime.validate_release()
    policy = runtime.model_history
    if runtime.manifest.get("model_history_protocol") == 2:
        from .session_model_history import validate_model_history_frame

        _completed_none(
            policy.validate_frame(detached(history), detached(messages)),
            "Model history frame validation",
        )
        validate_model_history_frame(
            history,
            messages,
            allow_tool_result_projection=runtime.manifest["model_history"]["identity"].get(
                "allow_tool_result_projection", False
            ),
        )
        runtime.validate_release()
        return
    _completed_none(
        policy.validate(detached(history), detached(messages)), "Model history validation"
    )
    validate_model_history(
        history,
        messages,
        allow_tool_result_projection=runtime.manifest["model_history"]["identity"].get(
            "allow_tool_result_projection", False
        ),
    )
    runtime.validate_release()


def assemble_history(runtime, history, references, max_chars, *, frame=None):
    """Select references without discarding the accepted native interaction."""
    from .temporal_activities import _close_lazy
    from .temporal_state import detached

    if runtime.model_history is None:
        return assemble_context(runtime.context, history, references, max_chars)
    from .model_history import validate_reference_evidence
    from .session_model_history import validate_native_reference_evidence

    # Validate original structured evidence before any replaceable policy can
    # stringify native continuation into a seemingly ordinary reference excerpt.
    validate_reference_evidence(references)
    validate_native_reference_evidence(references)
    if runtime.manifest.get("model_history_protocol") == 2:
        selected = detached(frame)
        projections = []
        from .data_context import ManagedDataContext

        if isinstance(runtime.context, ManagedDataContext) and runtime.manifest["model_history"][
            "identity"
        ].get("allow_tool_result_projection", False):
            offset = 1
            for turn in selected["turns"]:
                turn["history"], records = runtime.context.project_history(turn["history"])
                projections.extend(
                    {**record, "message_index": offset + record["message_index"] - 1}
                    for record in records
                )
                offset += len(turn["history"]) - 1
            selected["history"], records = runtime.context.project_history(selected["history"])
            projections.extend(
                {**record, "message_index": offset + record["message_index"] - 1}
                for record in records
            )
        value = runtime.model_history.assemble_frame(
            selected, detached(references), max_chars, context=runtime.context
        )
        if type(value) not in {tuple, list} or len(value) != 2:
            _close_lazy(value)
            raise ValidationError(
                "Model history frame must return a completed messages/manifest pair"
            )
        validate_context(value[0], value[1], max_chars)
        protect_history(runtime, frame, value[0])
        identity = detached(value[1])
        if projections:
            identity["artifact_projection"] = detached(projections)
        return detached(value[0]), identity
    source = detached(history)
    projected = source
    projection = []
    from .data_context import ManagedDataContext

    if isinstance(runtime.context, ManagedDataContext) and runtime.manifest["model_history"][
        "identity"
    ].get("allow_tool_result_projection", False):
        projected, projection = runtime.context.project_history(source)
    value = runtime.model_history.assemble(
        detached(projected), detached(references), max_chars, context=runtime.context
    )
    if type(value) not in {tuple, list} or len(value) != 2:
        _close_lazy(value)
        raise ValidationError("Model history must return a completed messages/manifest pair")
    validate_context(value[0], value[1], max_chars)
    protect_history(runtime, source, value[0])
    identity = detached(value[1])
    if projection:
        identity["artifact_projection"] = detached(projection)
    return detached(value[0]), identity
