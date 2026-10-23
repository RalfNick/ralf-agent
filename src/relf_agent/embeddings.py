"""An explicit offline feature-hash baseline, not a semantic embedding model."""

from .errors import ValidationError
from .recall import _integer
from .retrieval import _tokens
from .types import digest
from .vector import _unit


class HashEmbeddingProvider:
    def __init__(self, *, dimensions=128):
        _integer(dimensions, "Hash embedding dimensions", 1, 65536)
        self._dimensions = dimensions

    @property
    def dimensions(self):
        return self._dimensions

    @property
    def identity(self):
        return {"kind": "token-hash-embedding", "version": "1", "dimensions": self.dimensions}

    async def embed(self, texts):
        if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
            raise ValidationError("Embedding input must be a list of text strings")
        result = []
        for text in texts:
            values = [0.0] * self.dimensions
            for token in sorted(_tokens(text) or {"<empty>"}):
                identity = digest(token)
                values[int(identity[:16], 16) % self.dimensions] += 1.0
            result.append(list(_unit(values, self.dimensions)))
        return result
