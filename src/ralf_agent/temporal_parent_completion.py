"""Registered pure parent policy operations; model I/O belongs to a child Run."""

import json

from .errors import DefinitionMismatch, ValidationError
from .types import canonical, digest, submission_request


def stage_request(policy, input=None):
    from .temporal_bindings import normalize_request

    return normalize_request(
        submission_request(policy.model_stage.agent, input, budget=policy.verifier_budget)
    )


def registration(policy, manifest, runtime):
    from .binding_types import AgentBindingDescriptor
    from .parent_completion_protocol import policy_registration, validate_policy
    from .temporal_bindings import effective_manifest, effective_step, step_descriptor
    from .temporal_state import detached

    validate_policy(policy)
    result = policy_registration(policy)
    result["effective_agent_release"] = None
    if policy.model_stage is None:
        return json.loads(canonical(result))
    request = stage_request(policy)
    if request["definition"]["kind"] != "agent":
        raise ValidationError("Parent verifier requires one actual native Agent")
    descriptor = step_descriptor(request, 0)
    selected = effective_manifest(manifest, descriptor)
    choices = AgentBindingDescriptor.from_dict(descriptor)
    step = effective_step(request["definition"]["steps"][0], manifest, descriptor)
    if step["provider"] not in manifest["providers"]:
        raise DefinitionMismatch("Parent verifier provider unavailable")
    if step["tools"] or step["max_decisions"] != 1:
        raise ValidationError("Parent verifier must be tool-free with one decision")
    # An ordinary inherited ContextAssembler is pure. Managed summaries or data
    # references would create undisclosed reads/models beside the declared child.
    if any(
        name in selected
        for name in (
            "managed_context",
            "managed_memory",
            "facts_context",
            "knowledge_context",
            "completion_verifier",
        )
    ):
        raise ValidationError("Parent verifier selected auxiliary execution capabilities")
    if "session_data" in selected:
        if (
            choices.session.mode != "ref"
            or manifest.get("session_tree_protocol", {}).get("version") != 1
            or "session_save_protocol" not in manifest
        ):
            raise ValidationError(
                "Verifier Session requires an explicit original managed member source"
            )
        if (
            policy.verifier_budget
            < step["model_credits"] + selected["session_save_protocol"]["write_credits"]
        ):
            raise ValidationError("Verifier budget cannot cover original Session save")
    from .binding_runtime import artifact_free_context

    context_owner = runtime.context
    if choices.context.mode == "ref":
        context_owner, _ = runtime.binding_catalog.resolve(
            "context", choices.context, runtime.binding_catalog.scope
        )
    elif choices.context.mode != "inherit":
        raise ValidationError("Parent verifier requires an actual pure Context")
    if not artifact_free_context(context_owner):
        raise ValidationError("Parent verifier Context must be an original built-in pure assembly")
    context = selected.get("context_builder", {})
    result["effective_agent_release"] = detached(
        {
            "definition": request["definition"],
            "agent_bindings": request.get("agent_bindings", {}),
            "step": step,
            "provider_registration": manifest["providers"][step["provider"]],
            "context_registration": selected.get("context_registration"),
            "context_builder": context,
            "model_history": selected.get("model_history"),
        }
    )
    return json.loads(canonical(result))


def registrations(policies, manifest, runtime):
    if type(policies) is not dict or any(type(n) is not str or not n.strip() for n in policies):
        raise ValidationError("Parent completion policies require a named registry")
    return {
        name: registration(policy, manifest, runtime) for name, policy in sorted(policies.items())
    }


async def evaluate(runtime, value):
    from .parent_completion import ParentCompletionRequest
    from .parent_completion_protocol import (
        gate_verdict,
        interpret_stage_output,
        prepare_stage_input,
        validate_request_bounds,
    )
    from .temporal_state import detached

    try:
        runtime.validate_release(value["runtime_manifest"])
        if value.get("version") != 1 or runtime.manifest.get("parent_completion_protocol") != 1:
            raise DefinitionMismatch("Parent completion requires its original protocol")
        name = value["policy"]
        policy = runtime.parent_completion_policies[name]
        expected = value["runtime_manifest"]["parent_completion_policies"][name]
        if (
            value["registration"] != expected
            or registration(policy, runtime.manifest, runtime) != expected
        ):
            raise DefinitionMismatch("Parent policy differs from frozen History registration")
        source = detached(value["source"])
        if digest(source) != value["source_digest"] or source["scope"] != value["scope"]:
            raise DefinitionMismatch("Parent source differs from original intent")
        request = ParentCompletionRequest.from_dict(source)
        validate_request_bounds(policy, request)
        if value["mode"] == "prepare":
            verdict = gate_verdict(policy, request)
            prepared = (
                prepare_stage_input(policy, request)
                if (verdict.status == "accept" and policy.model_stage is not None)
                else None
            )
            proposal = {"gate_verdict": verdict.to_dict(), "prepared_input": prepared}
        elif value["mode"] == "interpret":
            proposal = {
                "verdict": interpret_stage_output(
                    policy, request, detached(value["output"])
                ).to_dict()
            }
        else:
            raise ValidationError("Unknown parent policy operation")
        runtime.validate_release(value["runtime_manifest"])
        if registration(policy, runtime.manifest, runtime) != expected:
            raise DefinitionMismatch("Parent completion policy changed during execution")
        return {"ok": True, "request_digest": digest(value), **detached(proposal)}
    except Exception as exc:
        from .temporal_activities import _code

        return {"ok": False, "code": _code(exc, "validation_error"), "dispatched": False}
