"""History validates pure permissions; Worker validates physical implementation."""

import pytest

from ralf_agent import temporal_coding_protocol as protocol
from ralf_agent.errors import DefinitionMismatch
from tests.test_temporal_coding_configuration import manifest


def test_history_validation_does_not_load_worker_io_implementations(monkeypatch):
    value = manifest()

    def blocked():
        raise AssertionError("History attempted Worker implementation discovery")

    monkeypatch.setattr(protocol, "implementation", blocked)
    protocol.validate_protocol(value)


def test_original_permission_helper_drift_is_refused(monkeypatch):
    from ralf_agent import temporal_coding_state as state

    value = manifest()

    def changed(*args, **kwargs):
        return None

    monkeypatch.setattr(state, "_record", changed)
    with pytest.raises(DefinitionMismatch, match="pure"):
        protocol.validate_protocol(value)
