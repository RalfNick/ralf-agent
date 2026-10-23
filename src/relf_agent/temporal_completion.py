"""Pure worker completion proposals over detached original execution evidence."""

from .completion import CompletionRequest, CompletionVerdict
from .component_fingerprint import executable_digest
from .errors import DefinitionMismatch, ValidationError
from .task_controls import _binding
from .types import digest


def registration(verifier):
    if verifier is None:
        return None
    from .temporal_activities import component_identity

    return {
        "identity": component_identity(verifier, ("verify",), synchronous=True),
        "implementation_digest": executable_digest(verifier.verify),
    }


def pin(verifier):
    return verifier, _binding(verifier.verify), registration(verifier)


def check_pin(original):
    verifier, method, identity = original
    if _binding(verifier.verify) != method or registration(verifier) != identity:
        raise DefinitionMismatch("Temporal completion verifier registration changed")


async def evaluate(runtime, request):
    from .temporal_activities import _close_lazy, _code
    from .temporal_bindings import selected_runtime
    from .temporal_state import detached

    try:
        runtime.validate_release(request["runtime_manifest"])
        if (
            type(request.get("version")) is not int
            or request["version"] != 1
            or runtime.manifest.get("completion_protocol") != 1
        ):
            raise DefinitionMismatch("Completion requires its original protocol")
        selected = selected_runtime(runtime, request)
        verifier = selected.verifier
        expected = selected.manifest.get("completion_verifier")
        if (
            verifier is None
            or expected != request["registration"]
            or registration(verifier) != expected
        ):
            raise DefinitionMismatch("Completion verifier differs from original intent")
        frozen = CompletionRequest(**detached(request["completion"]))
        value = verifier.verify(frozen)
        if type(value) is not CompletionVerdict:
            _close_lazy(value)
            raise ValidationError("CompletionVerifier.verify requires completed CompletionVerdict")
        verdict = CompletionVerdict(**value.to_dict()).to_dict()
        runtime.validate_release(request["runtime_manifest"])
        if registration(verifier) != expected:
            raise DefinitionMismatch("Completion verifier changed during execution")
        return {"ok": True, "request_digest": digest(request), "verdict": verdict}
    except Exception as exc:
        return {"ok": False, "code": _code(exc, "validation_error"), "dispatched": False}
