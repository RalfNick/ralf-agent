"""Pure, host-grounded selection policy; the original authority owns model I/O."""

import copy
from dataclasses import asdict

from .context_budget import _positive
from .decisions import final_output
from .errors import DefinitionMismatch, ValidationError
from .harness import ModelRequest
from .managed_memory import ManagedMemoryPolicy
from .memory_extraction import FactProposal, ModelMemoryExtractor, source_value
from .model_evidence import validate_received_response
from .ports import is_sync_callable
from .task_controls import _binding
from .tools import _callable_identity
from .types import canonical, digest


class ManagedModelMemoryPolicy(ManagedMemoryPolicy):
    """Models choose allowlisted keys; they never invent persistent fact values."""

    def __init__(self, memory, *, provider="default", max_context_chars=32768, **kwargs):
        super().__init__(memory, **kwargs)
        if not isinstance(provider, str) or not provider.strip():
            raise ValidationError("Memory selection requires a host provider alias")
        _positive(max_context_chars, "Memory selector request allowance", 65536)
        self.provider, self.max_context_chars = provider, max_context_chars
        self._selector = ModelMemoryExtractor(
            self.admission, provider=provider, max_context_chars=max_context_chars
        )
        self._hooks = {n: _binding(getattr(self, n)) for n in ("request", "select")}
        if any(not is_sync_callable(getattr(self, n)) for n in self._hooks):
            raise ValidationError("Model memory hooks must finish synchronously")
        self._identity = {
            **self._identity,
            "kind": "managed-model-memory",
            "selection": {
                "provider": provider,
                "max_context_chars": max_context_chars,
                "agent": asdict(self._selector.agent),
                "credits": 1,
                "implementation": {
                    n: digest(_callable_identity(getattr(self, n))) for n in self._hooks
                },
            },
        }
        canonical(self._identity)

    def check(self, scope):
        super().check(scope)
        selected = self._identity["selection"]
        if (
            self.provider != selected["provider"]
            or self.max_context_chars != selected["max_context_chars"]
            or asdict(self._selector.agent) != selected["agent"]
            or any(_binding(getattr(self, n)) != b for n, b in self._hooks.items())
        ):
            raise DefinitionMismatch("Memory selection configuration or implementation changed")

    def propose(self, evidence):
        raise ValidationError("Model field selection requires original-authority execution")

    def request(self, source):
        self.check(self.scope)
        request = ModelRequest(
            [
                {"role": "system", "content": self._selector.agent.instructions},
                {
                    "role": "user",
                    "content": canonical(
                        {"evidence": source, "fields": self.admission.identity["fields"]}
                    ),
                },
            ],
            [],
        )
        if len(canonical(request.messages)) > self.max_context_chars:
            raise ValidationError("Memory selector source exceeds its request allowance")
        return request

    def select(self, source, response):
        self.check(self.scope)
        validate_received_response(response)
        if response["tool_calls"]:
            raise ValidationError("Memory selection cannot propose tools")
        result = final_output(response["output"], self._selector.agent.output_schema)
        fields = self.admission.identity["fields"]
        return [
            FactProposal(k, source_value(copy.deepcopy(source), fields[k]), fields[k])
            for k in result["keys"]
        ]
