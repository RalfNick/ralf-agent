import asyncio

import pytest

from ralf_agent import (
    AgentSpec,
    ArtifactReference,
    BudgetedContextAssembler,
    InMemoryArtifactStore,
    LocalEngine,
    ModelResponse,
    SQLiteArtifactStore,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.errors import BudgetExceeded
from ralf_agent.types import Scope, canonical


def test_pure_request_validator_cannot_mutate_dispatched_snapshot(tmp_path):
    actual = []

    class Provider:
        identity = {"kind": "validator-mutation", "version": "1"}

        async def complete(self, messages, tools):
            actual.append(messages)
            return ModelResponse(output="done")

    class Mutating(BudgetedContextAssembler):
        def validate_request(self, messages, max_chars):
            measure = super().validate_request(messages, max_chars)
            messages[1]["content"] += "x" * 5000
            return measure

    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": Provider()},
        tools=ToolRegistry(),
        context_assembler=Mutating(max_units=1000),
    ) as engine:
        handle = engine.submit(
            AgentSpec("answer", "Complete", max_context_chars=1000), "hello", command_id="one"
        )
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert snapshot.state == "succeeded" and len(actual) == 1
        assert len(canonical(actual[0])) <= 1000
        assert snapshot.actions[0]["context_manifest"]["measurement"]["units"] == len(
            canonical(actual[0])
        )
        assert "x" * 5000 not in actual[0][1]["content"]


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_returned_artifact_reference_cannot_corrupt_retained_metadata_or_capacity(tmp_path, kind):
    store = (
        InMemoryArtifactStore(capacity=1)
        if kind == "memory"
        else SQLiteArtifactStore(tmp_path / "artifacts.sqlite", capacity=1)
    )
    with store:
        returned = store.put(Scope(), "a", {"n": 1})
        original = ArtifactReference.from_dict(returned.to_dict())
        object.__setattr__(returned, "namespace", "b")
        assert store.get(Scope(), original) == {"n": 1}
        with pytest.raises(BudgetExceeded):
            store.put(Scope(), "a", {"n": 2})
        assert store.put(Scope(), "a", {"n": 1}) == original
