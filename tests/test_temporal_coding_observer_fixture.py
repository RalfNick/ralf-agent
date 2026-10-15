import asyncio
from types import SimpleNamespace

import pytest

from tests.test_temporal_deployment_coding_service import CodingSystem


@pytest.mark.parametrize("closing,closed", [(True, False), (False, True), (False, False)])
def test_count_borrows_independent_observer_during_close_without_starting_worker(closing, closed):
    class Observer:
        def __init__(self):
            self.calls = 0

        async def deployment_diagnostics(self):
            self.calls += 1
            return {"counts": {"held_root_runs": 1}}

    system = object.__new__(CodingSystem)
    system.assembly = SimpleNamespace(_closing=closing, _closed=closed)
    system.engine, independent = Observer(), Observer()
    system.facade = lambda: independent

    def forbidden_worker():
        pytest.fail("Observing close must not start a Worker")

    system.worker = forbidden_worker
    assert asyncio.run(system.count(1)) == {"counts": {"held_root_runs": 1}}
    assert independent.calls == int(closing or closed)
    assert system.engine.calls == int(not (closing or closed))
