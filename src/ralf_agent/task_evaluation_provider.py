"""Borrowed model accounting with fixed configuration and actual entry points."""

import copy

from .errors import DefinitionMismatch, ValidationError
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
        names = ["complete"] + (
            ["validate_request"] if hasattr(provider, "validate_request") else []
        )
        self._bindings = {name: _binding(getattr(provider, name)) for name in names}
        super().__init__(provider, limits)

    def _check(self):
        if (
            self.provider is not self._provider
            or self.provider.identity != self._identity
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
        self._check()
        return result
