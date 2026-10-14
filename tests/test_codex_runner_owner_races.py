"""Original Runner lifecycle methods preserve the actual owner across awaits."""

import asyncio
from types import SimpleNamespace

import pytest

from ralf_agent.errors import CoordinatorBusy
from ralf_agent.executors import DispatchEnvelope
from ralf_agent.types import InvocationContext, Scope
from tests import test_codex_runner as fixture

runner_parts = fixture.runner_parts
runner = fixture.runner


def envelope(name):
    return DispatchEnvelope(
        InvocationContext(Scope("coding", "owner"), name, "action", "attempt", name, "epoch"),
        {"name": "coding", "effect": "queryable_write"},
        {"task": "bounded " + name},
        "digest-" + name,
    )


def ports(resource):
    """Fix external authority/PG/native ports; leave lifecycle methods real."""

    async def history(original, authority):
        return {"original": original.context.run_id}

    async def state(owner, method, *args):
        assert method == "resource_state"
        return dict.fromkeys(("prepare_grant", "prepared", "binding", "thread", "turn"))

    async def journal(owner, method, *args, **kwargs):
        assert method == "resource_state"
        return None

    async def cleanup(owner):
        owner["stop"] = {"fenced": True}
        owner["stop_evidence"] = {"original": owner["envelope"].context.run_id}

    resource._journal._ready = lambda: None
    resource._history_authority = history
    resource._authority_method = state
    resource._journal_method = journal
    resource._authority = lambda original, authority: {"original": original.context.run_id}
    resource._environment = lambda original, create: SimpleNamespace()
    resource._cleanup = cleanup
    return cleanup


@pytest.mark.parametrize("same_original", [False, True])
def test_cold_history_stop_cannot_replace_an_owner_installed_during_original_reads(
    runner_parts, same_original
):
    async def scenario():
        resource = runner(runner_parts)
        cleanup = ports(resource)
        waiting, resume, live, finish = [asyncio.Event() for _ in range(4)]
        first_read = True

        async def state(owner, method, *args):
            nonlocal first_read
            assert method == "resource_state"
            if first_read:
                first_read = False
                waiting.set()
                await resume.wait()
                return {
                    "prepare_grant": {},
                    "prepared": None,
                    "binding": None,
                    "thread": None,
                    "turn": None,
                }
            return dict.fromkeys(("prepare_grant", "prepared", "binding", "thread", "turn"))

        async def native(owner):
            live.set()
            try:
                await finish.wait()
            finally:
                await cleanup(owner)

        resource._authority_method, resource._execute = state, native
        original = envelope("a")
        stopping = asyncio.create_task(resource.stop_history(original, object()))
        await waiting.wait()
        executing = asyncio.create_task(
            resource.execute_history(original if same_original else envelope("b"), object())
        )
        await live.wait()
        actual_owner = resource._active
        resume.set()
        try:
            if same_original:
                assert await stopping == {"original": "a"}
                assert actual_owner["task"].done()
                assert resource._active is None
            else:
                with pytest.raises(CoordinatorBusy):
                    await stopping
                assert resource._active is actual_owner
                assert resource.active_operations == 1 and not actual_owner["task"].done()
        finally:
            finish.set()
            await asyncio.gather(executing, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["execute", "execute_history"])
def test_original_execution_finally_cannot_clear_a_later_owner(runner_parts, method):
    async def scenario():
        resource = runner(runner_parts)
        ports(resource)
        later = {"original": "later"}

        async def native(owner):
            owner["stop"] = {"fenced": True}
            resource._active = later

        resource._execute = native
        authority = SimpleNamespace(resource_state=lambda *args: {})
        await getattr(resource, method)(envelope("a"), authority)
        assert resource._active is later and resource.active_operations == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["stop_existing", "stop_history"])
def test_original_cold_stop_finally_cannot_clear_a_later_owner(runner_parts, method):
    async def scenario():
        resource = runner(runner_parts)
        ports(resource)
        later = {"original": "later"}

        async def cleanup(owner):
            owner["stop"] = {"fenced": True}
            resource._active = later

        resource._cleanup = cleanup
        authority = SimpleNamespace(resource_state=lambda *args: {"prepare_grant": {}})
        await getattr(resource, method)(envelope("a"), authority)
        assert resource._active is later and resource.active_operations == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["stopped", "task", "cleanup"])
def test_retained_close_cannot_clear_a_later_owner(runner_parts, phase):
    async def scenario():
        resource = runner(runner_parts)
        ports(resource)
        later = {"original": "later"}
        original = {"task": None, "stop": None, "cleanup": None}
        resource._active = original
        if phase == "stopped":
            original["stop"] = {"fenced": True}
            resource._active = later
        elif phase == "task":
            original["task"] = SimpleNamespace(done=lambda: False, cancel=lambda: None)

            async def settle(task):
                original["stop"] = {"fenced": True}
                resource._active = later

            resource._settle = settle
        else:

            async def cleanup(owner):
                owner["stop"] = {"fenced": True}
                resource._active = later

            resource._cleanup = cleanup
        await resource._close_owner(original)
        assert resource._active is later and resource.active_operations == 1

    asyncio.run(scenario())
