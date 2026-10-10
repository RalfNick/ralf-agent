"""Pure source-order selection after semantic recall; recent Session stays first."""

from .context_budget import _positive
from .errors import ValidationError


class OrderedReferenceSelector:
    def __init__(self, *, max_references=32):
        self._limit = _positive(max_references, "Ordered reference limit", 256)

    @property
    def identity(self):
        return {
            "kind": "ordered-reference-selector",
            "version": "1",
            "max_references": self._limit,
            "source_policy": "recent-session-then-source-order-v1",
        }

    def select(self, task, references):
        if (
            not isinstance(task, str)
            or not isinstance(references, list)
            or any(not isinstance(ref, dict) for ref in references)
        ):
            raise ValidationError(
                "Ordered reference selection requires serialized task and records"
            )
        sessions = [i for i, ref in enumerate(references) if "session" in ref]
        evidence = [i for i, ref in enumerate(references) if "session" not in ref]
        return (sessions + evidence)[: self._limit]
