"""Selected resource safety requires a new explicit Worker publication."""

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_coding_protocol import validate_protocol
from tests.test_temporal_coding_configuration import manifest


def test_current_resource_safety_accepts_native18_version4():
    value = manifest()
    value["binding_protocol"] = 18
    value["coding_execution_protocol"]["version"] = 4
    validate_protocol(value)


@pytest.mark.parametrize("binding", [16, 17])
def test_dev110_selected_workers_require_their_immutable_implementation(binding):
    value = manifest()
    value["binding_protocol"] = binding
    value["coding_execution_protocol"]["version"] = 3
    with pytest.raises(DefinitionMismatch):
        validate_protocol(value)
