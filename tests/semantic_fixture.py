"""Hand-derived vectors for contract tests, not a semantic model benchmark."""

from ralf_agent import InMemoryMemory, Scope


class Embedding:
    dimensions = 2
    identity = {"kind": "semantic-fixture", "model": "fixture", "dimensions": 2}

    async def embed(self, texts):
        return [
            [1, 0] if any(t in text for t in ("vehicle", "car", "automobile")) else [0, 1]
            for text in texts
        ]


def facts():
    backend = InMemoryMemory(backend_id="fixture-facts")
    for key, value in (
        ("a", "maritime transport"),
        ("b", "automobile servicing"),
        ("c", "car policy"),
    ):
        backend.put_fact(Scope(), "assistant", key, value, expected_version=0)
    return backend
