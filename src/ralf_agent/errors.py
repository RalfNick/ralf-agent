"""Typed, public errors. External exception bodies never enter run records."""


class RalfError(Exception):
    code = "ralf_error"


class ValidationError(RalfError):
    code = "validation_error"


class IdempotencyConflict(RalfError):
    code = "idempotency_conflict"


class BudgetExceeded(RalfError):
    code = "budget_exceeded"


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
