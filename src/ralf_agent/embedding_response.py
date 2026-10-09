"""Detached embedding results with per-request usage; missing usage stays unknown."""

from .errors import ValidationError
from .orchestration_types import _JsonValue
from .retrieval import _integer
from .types import canonical
from .vector import _vector


def embedding_usage(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"prompt_tokens", "total_tokens"}:
        raise ValidationError("Invalid embedding usage")
    if not value:
        raise ValidationError("Empty embedding usage")
    result = {k: _integer(v, "Embedding usage") for k, v in value.items()}
    if (
        "prompt_tokens" in result
        and "total_tokens" in result
        and result["total_tokens"] < result["prompt_tokens"]
    ):
        raise ValidationError("Inconsistent embedding usage")
    return result


class EmbeddingResponse(_JsonValue):
    def __init__(self, vectors, usage, *, dimensions):
        _integer(dimensions, "Embedding dimensions", minimum=1)
        if (
            not isinstance(vectors, (list, tuple))
            or len(vectors) > 4096
            or len(vectors) * dimensions > 4000000
        ):
            raise ValidationError("Embedding result exceeds limit")
        if not isinstance(usage, (list, tuple)) or len(usage) > 4096:
            raise ValidationError("Embedding usage requires bounded per-request values")
        self._data_json = canonical(
            {
                "vectors": [_vector(v, dimensions) for v in vectors],
                "usage": [embedding_usage(u) for u in usage],
                "batches": len(usage),
            }
        )
