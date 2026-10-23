"""Registry-owned SDK verification followed by an original atomic commit."""

from datetime import timedelta

from .errors import DefinitionMismatch
from .temporal_deployment_admission import _exact

REGISTRY_ACTIVITY = "ralf.temporal.session-deployment-verify.v1"


def state(owner):
    owner._check_deployment_registry_epoch()
    if owner.commands.admission_protocol != 4 or owner.commands.deployment is None:
        raise DefinitionMismatch("Session admission requires its original Registry4")
    return owner.commands.deployment


async def execute(owner, operation, request):
    from temporalio import workflow
    from temporalio.common import RetryPolicy

    current = state(owner)
    if operation == "session_root":
        _exact(request, {"request", "intent"})
        prepared = current.prepare_session_root(request["request"], request["intent"])
        if "receipt" in prepared:
            return prepared["receipt"]
        binding = prepared["intent"]["binding"]
    elif operation == "session_never_claimed":
        prepared = current.prepare_session_never_claimed(request)
        if "certificate" in prepared:
            return prepared["certificate"]
        binding = prepared["intent"]["binding"]
    elif operation == "session_receipt":
        prepared = current.prepare_session_receipt(request)
        binding = prepared["session_submission"]["binding"]
    else:
        raise DefinitionMismatch("Unsupported original Session verification")
    response = await workflow.execute_activity(
        REGISTRY_ACTIVITY,
        {
            "mode": operation,
            "scope": request["request"]["scope"]
            if operation == "session_root"
            else request["scope"],
            "manifest": binding["manifest"],
            "registry_execution_epoch": workflow.info().run_id,
            "prepared": prepared,
        },
        task_queue=binding["task_queue"],
        start_to_close_timeout=timedelta(seconds=binding["activity_timeout"]),
        schedule_to_close_timeout=timedelta(seconds=binding["activity_timeout"] * 2 + 5),
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    if state(owner) is not current:
        raise DefinitionMismatch("Original Session Registry changed during verification")
    _exact(response, {"ok", "result"} if response.get("ok") is True else {"ok", "code"})
    if response["ok"] is not True:
        from temporalio.exceptions import ApplicationError

        allowed = {
            "validation_error",
            "definition_mismatch",
            "authorization_denied",
            "idempotency_conflict",
        }
        raise ApplicationError(
            "Original Session SDK proof unavailable",
            type=response["code"] if response["code"] in allowed else "definition_mismatch",
            non_retryable=True,
        )
    if operation == "session_root":
        return current.commit_session_root(
            request["request"], request["intent"], response["result"]
        )
    if operation == "session_never_claimed":
        return current.commit_session_never_claimed(request, response["result"])
    return current.commit_session_receipt(request, response["result"])
