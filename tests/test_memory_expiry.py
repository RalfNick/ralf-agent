from decimal import Decimal

import pytest

from ralf_agent.errors import ValidationError
from ralf_agent.memory import InMemoryMemory, SQLiteMemory
from ralf_agent.types import Scope


@pytest.fixture(params=["memory", "sqlite"])
def memory_backend(request, tmp_path):
    backend = (
        InMemoryMemory() if request.param == "memory" else SQLiteMemory(tmp_path / "memory.db")
    )
    yield backend
    backend.close()


@pytest.mark.parametrize(
    "expires_at",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(True, id="true"),
        pytest.param(False, id="false"),
        pytest.param("4102444800", id="numeric-string"),
        pytest.param([], id="list"),
        pytest.param({}, id="mapping"),
        pytest.param(Decimal("4102444800"), id="decimal"),
        pytest.param(10**400, id="unrepresentable-integer"),
    ],
)
def test_invalid_expiration_cannot_create_or_update_fact(memory_backend, expires_at):
    scope = Scope()
    with pytest.raises(ValidationError, match="expires_at"):
        memory_backend.put_fact(
            scope, "preferences", "new", "invalid", expected_version=0, expires_at=expires_at
        )

    # A rejected create must not consume a version or create a hidden/permanent record.
    assert memory_backend.put_fact(scope, "preferences", "new", "valid", expected_version=0) == 1
    before = memory_backend.facts(scope, "preferences")
    with pytest.raises(ValidationError, match="expires_at"):
        memory_backend.put_fact(
            scope, "preferences", "new", "changed", expected_version=1, expires_at=expires_at
        )
    assert memory_backend.facts(scope, "preferences") == before
    assert memory_backend.put_fact(scope, "preferences", "new", "updated", expected_version=1) == 2


@pytest.mark.parametrize(
    ("expires_at", "visible"),
    [
        pytest.param(None, True, id="no-expiration"),
        pytest.param(-1, False, id="past-integer"),
        pytest.param(0.5, False, id="past-float"),
        pytest.param(4102444800, True, id="future-integer"),
        pytest.param(4102444800.5, True, id="future-float"),
    ],
)
def test_valid_expiration_preserves_visibility_and_versions(memory_backend, expires_at, visible):
    scope = Scope()
    assert (
        memory_backend.put_fact(
            scope, "preferences", "language", "zh", expected_version=0, expires_at=expires_at
        )
        == 1
    )
    facts = memory_backend.facts(scope, "preferences")
    assert bool(facts) is visible
    if visible:
        assert facts == [{"key": "language", "value": "zh", "version": 1, "expires_at": expires_at}]
    # Expiration hides facts without resetting their CAS version.
    assert memory_backend.put_fact(scope, "preferences", "language", "en", expected_version=1) == 2
