"""Tool-free managed verification; model I/O remains in the original child Run."""

from .binding_definitions import AgentDefinition
from .binding_types import AgentBindingDescriptor, BindingSelection
from .errors import ValidationError
from .parent_completion import (
    PARENT_COMPLETION_VERDICT_SCHEMA,
    ParentCompletionRequest,
    ParentCompletionVerdict,
    _json,
)
from .types import AgentSpec, canonical

_DISABLED = (
    "facts",
    "knowledge",
    "stage_policy",
    "session",
    "model_history",
    "verifier",
    "artifacts",
    "workspace",
    "skills",
    "sandbox",
    "tool_set",
)


class ModelParentVerificationStage:
    def __init__(
        self,
        *,
        provider="default",
        instructions=None,
        bindings=None,
        version="1",
        model_credits=1,
        max_context_chars=32768,
    ):
        if bindings is not None and type(bindings) is not AgentBindingDescriptor:
            raise ValidationError("Model verification bindings require AgentBindingDescriptor")
        supplied = AgentBindingDescriptor() if bindings is None else bindings
        selections = {
            key: value for key, value in supplied.to_dict().items() if key != "schema_version"
        }
        for role in _DISABLED:
            if getattr(supplied, role).mode == "ref":
                raise ValidationError(
                    "Default model verification disables auxiliary capability references"
                )
            selections[role] = BindingSelection.disabled()
        self.agent = AgentDefinition(
            AgentSpec(
                "verifier",
                instructions
                if instructions is not None
                else (
                    "Review the frozen parent completion source and its declared evidence. "
                    "Return only JSON {status,feedback,evidence_ids}: accept, reject, or replan. "
                    "Accept preserves the supplied candidate exactly and requires feedback=null. "
                    "Replan requires concrete feedback. Use only supplied child/tool evidence IDs. "
                    "Do not execute tools or invent evidence, and do not replace the candidate."
                ),
                provider=provider,
                version=version,
                max_decisions=1,
                model_credits=model_credits,
                max_context_chars=max_context_chars,
                output_schema=_json(PARENT_COMPLETION_VERDICT_SCHEMA),
            ),
            AgentBindingDescriptor(**selections),
        )

    @property
    def identity(self):
        return {
            "kind": "model-parent-verification-stage",
            "version": "1",
            "agent": self.agent.to_dict(),
        }

    def prepare(self, request):
        if type(request) is not ParentCompletionRequest:
            raise ValidationError("Model parent verification requires a frozen request")
        prepared = request.to_dict()
        if len(canonical(prepared)) > self.agent.spec.max_context_chars:
            raise ValidationError("Parent verification source exceeds model context limit")
        return prepared

    def interpret(self, request, output):
        from .parent_completion_protocol import validate_verdict

        return validate_verdict(request, ParentCompletionVerdict.from_dict(_json(output)))
