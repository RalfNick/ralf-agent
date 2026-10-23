"""Explicit close retries preserve an original in-flight cleanup wave.

Only the retirement dependency is controlled; the Runner's actual close,
supervision and cleanup-task ownership methods execute unchanged.
"""

import asyncio

from relf_agent.codex_runner import CodexCodingRunner
from relf_agent.errors import CloseIncomplete


def test_fault_removal_preserves_inflight_failure_until_next_explicit_close():
    async def scenario():
        captured, drained = asyncio.Event(), asyncio.Event()
        original_failure = CloseIncomplete({"coding_resource": "retirement_unconfirmed"})
        original_stop = {"fenced": True}
        fault, attempts = True, []

        class ControlledRetirement(CodexCodingRunner):
            async def _retire(self, owner):
                # A real retirement may already have observed a failed stop
                # while it still owns subsequent transport/handler drain.
                failed = fault
                attempts.append(owner)
                captured.set()
                await drained.wait()
                if failed:
                    raise original_failure
                owner["stop"] = original_stop

        runner = ControlledRetirement.__new__(ControlledRetirement)
        owner = {"task": None, "cleanup": None, "stop": None, "supervision": None}
        runner._active, runner._closing = owner, False
        first = asyncio.create_task(runner._close_owner(owner))
        recovery = None
        try:
            await asyncio.wait_for(captured.wait(), timeout=1)
            original_cleanup = owner["cleanup"]
            assert original_cleanup is not None and not original_cleanup.done()

            fault = False
            recovery = asyncio.create_task(runner.aclose(wait_timeout=1))
            # Run aclose and its separately owned supervision to their first await.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert owner["cleanup"] is original_cleanup
            assert attempts == [owner] and not recovery.done()
            assert runner._active is owner and owner["stop"] is None
        finally:
            # A failed regression assertion must also release the controlled
            # retirement dependency and retrieve every owned task's outcome.
            drained.set()
            tasks = [first] + ([] if recovery is None else [recovery])
            outcomes = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=1
            )
        assert outcomes == [original_failure, original_failure]
        assert all(outcome is original_failure for outcome in outcomes)
        assert original_cleanup.done() and original_cleanup.exception() is original_failure
        assert owner["supervision"].done()
        assert owner["supervision"].exception() is original_failure
        assert runner._active is owner and owner["stop"] is None
        assert attempts == [owner]  # Neither caller silently retries retirement.

        await runner.aclose(wait_timeout=1)
        assert attempts == [owner, owner]
        assert owner["cleanup"] is not original_cleanup
        assert owner["cleanup"].done() and owner["cleanup"].exception() is None
        assert owner["stop"] is original_stop and runner._active is None

        await runner.aclose(wait_timeout=1)
        assert attempts == [owner, owner]

    asyncio.run(scenario())
