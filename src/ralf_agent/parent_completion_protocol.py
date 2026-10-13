"""Shared pure registration, bounds and concrete proposal validation."""

import inspect
import json
from dataclasses import asdict

from .binding_artifacts import _method_binding, _method_matches
from .binding_definitions import AgentDefinition
from .completion import _matches
from .component_fingerprint import executable_digest
from .errors import DefinitionMismatch, RalfError, ValidationError
from .parent_completion import (
    ParentCompletionPolicy,
    ParentCompletionRequest,
    ParentCompletionVerdict,
    _json,
)
from .ports import is_sync_callable
from .types import AgentSpec, canonical, digest


def _completed(value):
    if (
        inspect.isawaitable(value)
        or inspect.isgenerator(value)
        or inspect.isasyncgen(value)
        or hasattr(value, "__enter__")
        or hasattr(value, "__aenter__")
    ):
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise ValidationError("Parent completion methods require completed concrete values")
    return value


def _component_registration(component, methods):
    identity = _json(getattr(component, "identity", None))
    if (
        type(identity) is not dict
        or type(identity.get("version")) is not str
        or not identity["version"].strip()
    ):
        raise ValidationError("Parent components require explicit versioned JSON identity")
    if len(canonical(identity).encode("utf-8")) > 1_048_576 or any(
        not is_sync_callable(getattr(component, name, None)) for name in methods
    ):
        raise ValidationError(
            "Parent completion component methods must be synchronous pure operations"
        )
    return {
        "identity": identity,
        "implementation_digest": digest(
            {name: executable_digest(getattr(component, name)) for name in methods}
        ),
    }


def _stage_agent(stage):
    agent = getattr(stage, "agent", None)
    if type(agent) is AgentDefinition:
        spec, encoded = agent.spec, agent.to_dict()
    elif type(agent) is AgentSpec:
        spec, encoded = agent, {"kind": "agent", **asdict(agent)}
    else:
        raise ValidationError(
            "Parent verification stage requires an original AgentSpec or AgentDefinition"
        )
    if spec.tools or spec.max_decisions != 1 or spec.output_schema is None:
        raise ValidationError(
            "Parent verifier must declare one tool-free decision and Verdict Schema"
        )
    schema = spec.output_schema
    properties = schema.get("properties") if type(schema) is dict else None
    if (
        type(properties) is not dict
        or set(properties) != {"status", "feedback", "evidence_ids"}
        or set(schema.get("required", [])) != set(properties)
        or schema.get("additionalProperties") is not False
    ):
        raise ValidationError("Parent verifier requires an exact bounded Verdict Schema")
    status, feedback, ids = properties["status"], properties["feedback"], properties["evidence_ids"]
    if (
        type(status) is not dict
        or type(status.get("enum")) is not list
        or not status["enum"]
        or any(
            type(item) is not str or item not in {"accept", "reject", "replan"}
            for item in status["enum"]
        )
        or type(feedback) is not dict
        or type(feedback.get("maxLength")) is not int
        or not 1 <= feedback["maxLength"] <= 4096
        or type(ids) is not dict
        or ids.get("type") != "array"
        or type(ids.get("maxItems")) is not int
        or not 0 <= ids["maxItems"] <= 256
        or ids.get("uniqueItems") is not True
    ):
        raise ValidationError("Parent verifier output feedback and IDs must be bounded")
    item = ids.get("items")
    if (
        type(item) is not dict
        or item.get("type") != "string"
        or not (
            item.get("pattern") == "^(child|tool):[0-9a-f]{64}$"
            or type(item.get("maxLength")) is int
            and 1 <= item["maxLength"] <= 128
        )
    ):
        raise ValidationError("Parent verifier evidence IDs require bounded string items")
    return spec, _json(encoded)


def _current_registration(policy):
    gate = _component_registration(policy.gate, ("verify",))
    stage = None
    if policy.model_stage is not None:
        stage = _component_registration(policy.model_stage, ("prepare", "interpret"))
        spec, encoded = _stage_agent(policy.model_stage)
        if policy.verifier_budget < spec.model_credits:
            raise ValidationError("Verifier budget cannot cover declared model credits")
        stage["agent"] = encoded
    identity = {
        "kind": "parent-completion-policy",
        "version": "1",
        "gate": gate["identity"],
        "model_stage": None if stage is None else stage["identity"],
        "verifier_budget": policy.verifier_budget,
        "max_source_bytes": policy.max_source_bytes,
        "max_receipts": policy.max_receipts,
        "max_evidence_children": policy.max_evidence_children,
    }
    return {
        "identity": identity,
        "implementation_digest": digest(
            [
                gate["implementation_digest"],
                None if stage is None else stage["implementation_digest"],
            ]
        ),
        "gate_registration": gate,
        "stage_registration": stage,
    }


def _initialize_policy(policy):
    registration = _current_registration(policy)
    policy._registration_json = canonical(registration)
    policy._identity_json = canonical(registration["identity"])
    policy._original_components = (policy.gate, policy.model_stage)
    policy._method_pins = [(policy.gate, "verify", _method_binding(policy.gate.verify))]
    if policy.model_stage is not None:
        policy._method_pins.extend(
            (policy.model_stage, name, _method_binding(getattr(policy.model_stage, name)))
            for name in ("prepare", "interpret")
        )


def policy_registration(policy):
    """Detached pure registration; original authorities add effective Agent release."""
    return validate_policy(policy)


def validate_policy(policy, parent_kind=None):
    if type(policy) is not ParentCompletionPolicy:
        raise ValidationError("Register an original ParentCompletionPolicy")
    if parent_kind is not None and parent_kind not in {"dynamic", "team"}:
        raise ValidationError("Parent completion supports dynamic or team")
    if (
        policy.gate is not policy._original_components[0]
        or policy.model_stage is not policy._original_components[1]
        or any(
            not _method_matches(getattr(component, name, None), pin)
            for component, name, pin in policy._method_pins
        )
    ):
        raise DefinitionMismatch("The original parent completion implementation changed")
    try:
        current = _current_registration(policy)
    except ValidationError as exc:
        raise DefinitionMismatch("The registered parent completion component changed") from exc
    if (
        canonical(current) != policy._registration_json
        or canonical(policy.identity) != policy._identity_json
    ):
        raise DefinitionMismatch("The registered parent completion identity changed")
    if (
        parent_kind == "team"
        and current["gate_registration"]["identity"].get("on_missing") == "replan"
    ):
        raise ValidationError("Team completion cannot select a replan receipt policy")
    return json.loads(policy._registration_json)


def validate_request_bounds(policy, request):
    if type(request) is not ParentCompletionRequest:
        raise ValidationError("Parent completion requires a concrete frozen request")
    validate_policy(policy, parent_kind=request.parent_kind)
    checked = ParentCompletionRequest.from_dict(request.to_dict())
    if (
        len(canonical(checked.to_dict()).encode("utf-8")) > policy.max_source_bytes
        or len(checked.children) > policy.max_evidence_children
        or len(checked.receipts) > policy.max_receipts
    ):
        raise ValidationError("Parent completion source exceeds declared evidence bounds")


def validate_verdict(request, verdict):
    if (
        type(request) is not ParentCompletionRequest
        or type(_completed(verdict)) is not ParentCompletionVerdict
    ):
        raise ValidationError(
            "Parent completion requires a concrete verdict over its frozen request"
        )
    verdict = ParentCompletionVerdict.from_dict(verdict.to_dict())
    ids = {item["id"] for item in [*request.children, *request.receipts]}
    if any(item not in ids for item in verdict.evidence_ids):
        raise ValidationError("Parent verdict refers to foreign evidence")
    if verdict.status == "replan" and request.parent_kind == "team":
        raise ValidationError("Team completion cannot replan")
    return verdict


def _invoke(policy, request, operation, *args):
    validate_request_bounds(policy, request)
    try:
        proposed = _completed(operation(request, *args))
    except RalfError:
        raise
    except Exception as exc:
        raise ValidationError(
            "Parent completion operation failed to produce a pure proposal"
        ) from exc
    validate_policy(policy, parent_kind=request.parent_kind)
    return proposed


def gate_verdict(policy, request):
    validate_request_bounds(policy, request)
    return validate_verdict(request, _invoke(policy, request, policy.gate.verify))


def prepare_stage_input(policy, request):
    validate_request_bounds(policy, request)
    if policy.model_stage is None:
        raise ValidationError("Parent policy has no managed verification stage")
    result = _json(_invoke(policy, request, policy.model_stage.prepare))
    if len(canonical(result).encode("utf-8")) > policy.max_source_bytes:
        raise ValidationError("Prepared verification source exceeds declared byte bounds")
    spec, _ = _stage_agent(policy.model_stage)
    if len(canonical(result)) > spec.max_context_chars:
        raise ValidationError("Prepared verification source exceeds Agent context bounds")
    return result


def interpret_stage_output(policy, request, output):
    validate_request_bounds(policy, request)
    if policy.model_stage is None:
        raise ValidationError("Parent policy has no managed verification stage")
    output = _json(_completed(output))
    spec, _ = _stage_agent(policy.model_stage)
    if not _matches(spec.output_schema, output):
        raise ValidationError("Managed verification output violates its original Verdict Schema")
    return validate_verdict(request, _invoke(policy, request, policy.model_stage.interpret, output))
