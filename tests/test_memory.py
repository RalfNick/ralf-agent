import time

import pytest

from ralf_agent.errors import ValidationError
from ralf_agent.memory import InMemoryMemory, SQLiteMemory
from ralf_agent.types import Scope


@pytest.fixture(params=["memory", "sqlite"])
def memory(request, tmp_path):
    backend = (
        InMemoryMemory() if request.param == "memory" else SQLiteMemory(tmp_path / "memory.db")
    )
    yield backend
    backend.close()


def test_session_append_uses_cas_and_stable_message_id(memory):
    scope = Scope("w", "alice")
    message = {"role": "user", "content": "hello"}
    assert memory.append(scope, "s", message, expected_revision=0, message_id="m1") == 1
    assert memory.append(scope, "s", message, expected_revision=0, message_id="m1") == 1
    with pytest.raises(ValidationError):
        memory.append(
            scope, "s", {"role": "user", "content": "stale"}, expected_revision=0, message_id="m2"
        )
    revision, messages = memory.read(scope, "s")
    assert revision == 1
    assert messages == [message]
    assert memory.read(Scope("other", "alice"), "s") == (0, [])


def test_facts_have_versions_expiration_and_namespace_isolation(memory):
    scope = Scope("w", "alice")
    assert memory.put_fact(scope, "agent-a", "service", "checkout", expected_version=0) == 1
    with pytest.raises(ValidationError):
        memory.put_fact(scope, "agent-a", "service", "payment", expected_version=0)
    assert memory.put_fact(scope, "agent-a", "service", "payment", expected_version=1) == 2
    facts = memory.facts(scope, "agent-a")
    assert [(f["key"], f["value"], f["version"]) for f in facts] == [("service", "payment", 2)]
    assert memory.facts(scope, "agent-b") == []
    assert memory.facts(Scope("w", "bob"), "agent-a") == []
    memory.put_fact(
        scope, "agent-a", "expired", "old", expected_version=0, expires_at=time.time() - 1
    )
    assert [f["key"] for f in memory.facts(scope, "agent-a")] == ["service"]


def test_memory_reads_cannot_mutate_stored_values(memory):
    scope = Scope()
    memory.put_fact(scope, "a", "preferences", {"language": "zh"}, expected_version=0)
    memory.facts(scope, "a")[0]["value"]["language"] = "changed"
    assert memory.facts(scope, "a")[0]["value"] == {"language": "zh"}
