"""New original CREATE supervision cannot reinterpret dev111 resource records."""

import pytest

from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_coding_protocol import validate_protocol
from tests.test_temporal_coding_configuration import manifest


def test_current_native_supervision_requires22_version6():
    value = manifest()
    value["binding_protocol"] = 22
    value["coding_execution_protocol"]["version"] = 6
    validate_protocol(value)


@pytest.mark.parametrize("binding", [18, 19])
def test_original_dev111_selection_requires_matching_immutable_worker(binding):
    value = manifest()
    value["binding_protocol"] = binding
    value["coding_execution_protocol"]["version"] = 4
    with pytest.raises(DefinitionMismatch):
        validate_protocol(value)
