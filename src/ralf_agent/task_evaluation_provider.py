"""Borrowed model accounting with fixed configuration and actual entry points."""

import copy

from .errors import DefinitionMismatch, ValidationError
from .model_continuation import provider_continuation_identity
from .planning_evaluation import _AuditedProvider
from .ports import is_async_callable
from .task_controls import _binding
from .types import canonical


class PinnedEvaluationProvider(_AuditedProvider):
    def __init__(self, provider, limits):
        if not is_async_callable(getattr(provider, "complete", None)):
            raise ValidationError("Evaluation Provider.complete must be async")
        self._provider = provider
        self._identity = copy.deepcopy(provider.identity)
        if not isinstance(self._identity, dict) or not self._identity:
            raise ValidationError("Evaluation Provider requires a finite identity")
        canonical(self._identity)
        self._continuation_identity = provider_continuation_identity(provider)
        names = ["complete"] + (
            ["validate_request"] if hasattr(provider, "validate_request") else []
        )
        self._bindings = {name: _binding(getattr(provider, name)) for name in names}
        super().__init__(provider, limits)

    @property
    def identity(self):
        # Let the original authority record a completed response before
        # registration drift rejects its adoption.
        value = super().identity
        try:
            self._check()
        except (DefinitionMismatch, ValidationError):
            # A finite changed identity permits read-only reconstruction, but
            # cannot match the original release or admit another model call.
            value = {**value, "registration_changed": True}
        return value

    def _check(self):
        if (
            self.provider is not self._provider
            or self.provider.identity != self._identity
            or provider_continuation_identity(self.provider) != self._continuation_identity
            or any(
                _binding(getattr(self.provider, name, None)) != binding
                for name, binding in self._bindings.items()
            )
            or ("validate_request" in self._bindings) != hasattr(self.provider, "validate_request")
        ):
            raise DefinitionMismatch("The borrowed evaluation Provider changed")

    def validate_request(self, messages, tools):
        self._check()
        super().validate_request(messages, tools)
        self._check()

    async def complete(self, messages, tools):
        self._check()
        result = await super().complete(messages, tools)
        return result
