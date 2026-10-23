import asyncio
import copy
import importlib

import pytest

from relf_agent import (
    AgentSpec,
    InMemoryMemory,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolRegistry,
)
from relf_agent.errors import ValidationError


def read_value(value):
    try:
        module = importlib.import_module("relf_agent.facts_store_values")
    except ModuleNotFoundError:
        pytest.fail("The completed Facts adoption boundary is missing")
    return module.facts_read_value(value)


def fact(**changes):
    return {
        "key": "中文🙂",
        "value": {"nested": [None, True, 2]},
        "version": 1,
        "expires_at": None,
        "provenance": {"source": ["original"]},
        **changes,
    }


def test_completed_read_detaches_nested_values_and_retains_finite_provenance():
    source = [fact()]
    result = read_value(source)
    source[0]["value"]["nested"].append("input changed")
    result[0]["provenance"]["source"].append("result changed")
    assert result[0]["value"] == {"nested": [None, True, 2]}
    assert source[0]["provenance"] == {"source": ["original"]}
    assert read_value([]) == []
    assert read_value([fact(value=None, expires_at=1.5)])[0]["value"] is None


@pytest.mark.parametrize(
    "value",
    [
        (),
        {},
        [None],
        [dict(key="one", value=1, version=1)],
        [fact(key="")],
        [fact(key=" ")],
        [fact(version=True)],
        [fact(version=1.0)],
        [fact(version=0)],
        [fact(expires_at=True)],
        [fact(expires_at=float("inf"))],
        [fact(value=float("nan"))],
        [fact(provenance={"bad": float("inf")})],
        [fact(), fact()],
    ],
)
def test_completed_read_refuses_invalid_records_without_repair(value):
    with pytest.raises(ValidationError):
        read_value(value)


def test_lazy_read_is_disposed_without_executing_its_body():
    async def lazy():
        raise AssertionError("lazy read body must not execute")

    value = lazy()
    with pytest.raises(ValidationError):
        read_value(value)
    assert value.cr_frame is None


@pytest.mark.parametrize("bad", [[fact(version=True)], [fact(value=float("nan"))], {}])
def test_original_local_full_read_rejects_bad_facts_before_model(bad, tmp_path):
    class Memory(InMemoryMemory):
        def facts(self, scope, namespace):
            return copy.deepcopy(bad)

    class Observer:
        identity = {"kind": "facts-boundary-observer", "version": "1"}
        calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            return ModelResponse(output="should not run")

    observer = Observer()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.sqlite"),
        memory_store=Memory(),
        providers={"default": observer},
        tools=ToolRegistry(),
    ) as engine:
        run = engine.submit(AgentSpec("facts", "Observe"), "q", command_id="case")
        result = asyncio.run(engine.drive(run.run_id))
        assert result.state == "failed"
        assert observer.calls == 0
