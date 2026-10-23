"""A normal owner subclass may capture self in its end callback and use super."""

import pytest

from relf_agent import ContextExecutionOwner
from relf_agent.component_fingerprint import executable_digest
from relf_agent.errors import ValidationError
from relf_agent.temporal_context_read_protocol import ContextExecutionRegistration


class ForwardOwner(ContextExecutionOwner):
    async def execute(self, operation, *, proof, on_end=None):
        async def ended(value):
            assert self.active_count >= 0  # Captured self becomes a compiler cell.
            if on_end is not None:
                await on_end(value)

        return await super().execute(operation, proof=proof, on_end=ended)


def test_owner_subclass_compiler_super_with_cell_self_has_fixed_fingerprint():
    registered = ContextExecutionRegistration(ForwardOwner())
    assert len(registered.identity["implementation"]["execute"]) == 64
    assert registered.identity == ContextExecutionRegistration(ForwardOwner()).identity


def test_opaque_class_capture_remains_refused():
    class Opaque:
        def execute(self):
            return __class__

    with pytest.raises(ValidationError):
        executable_digest(Opaque.execute)
