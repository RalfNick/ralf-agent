"""Typed, public errors. External exception bodies never enter run records."""


class RalfError(Exception):
    code = "ralf_error"


class ValidationError(RalfError, ValueError):
    code = "validation_error"


class IdempotencyConflict(RalfError):
    code = "idempotency_conflict"


class BudgetExceeded(RalfError):
    code = "budget_exceeded"


class CapacityExceeded(RalfError):
    code = "capacity_exceeded"


class CompletionRejected(RalfError):
    code = "completion_rejected"


class AgentLimitExceeded(RalfError):
    code = "agent_limit_exceeded"


class AuthorizationDenied(RalfError):
    code = "authorization_denied"


class DefinitionMismatch(RalfError):
    code = "definition_mismatch"


class CoordinatorBusy(RalfError):
    code = "coordinator_busy"


class NotFound(RalfError):
    code = "not_found"


class ProviderError(RalfError):
    code = "provider_error"


class MemoryBackendError(RalfError):
    code = "memory_backend_error"


class RuntimeClosed(RalfError):
    code = "runtime_closed"


class ExecutionHostFailed(RalfError):
    code = "execution_host_failed"


class CloseIncomplete(RalfError):
    code = "close_incomplete"

    def __init__(self, report):
        super().__init__("Runtime closing is incomplete; retain resources and retry")
        self.report = report


class SessionBusy(RalfError):
    code = "session_busy"

    def __init__(self, receipt, run_ref):
        super().__init__("Session belongs to an unfinished original Turn")
        self.receipt, self.run_ref = receipt, run_ref


class SessionBindingMismatch(RalfError):
    code = "session_binding_mismatch"

    def __init__(self, receipt):
        super().__init__("Session binding differs; use original revision or explicit idle rebind")
        self.receipt = receipt
