"""The original Runner waits before native admission and releases exact proof."""

import asyncio

import pytest

from ralf_agent.codex_runner import CodexCodingRunner
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.executors import DispatchEnvelope
from ralf_agent.types import InvocationContext, Scope
from tests import test_codex_runner as fixture

runner_parts = fixture.runner_parts
runner = fixture.runner
envelope = fixture.envelope


def owner(resource, value=None):
    return {"envelope": value or envelope(), "capacity": None, "stop_evidence": None}


def test_different_runner_objects_same_physical_root_wait_before_native_admission(
    runner_parts, monkeypatch
):
    first, second = runner(runner_parts), runner(runner_parts)
    a = owner(first)
    b = owner(
        second,
        DispatchEnvelope(
            InvocationContext(
                Scope("foreign", "other"), "run-b", "action-b", "attempt-b", "effect-b", "epoch-b"
            ),
            envelope().tool_manifest,
            {"task": "a different parent task"},
            "different-operation",
        ),
    )

    async def checked(resource, entry):
        assert entry in (a, b)

    monkeypatch.setattr(CodexCodingRunner, "_cancelled_owned", checked)

    async def run():
        await first._acquire_capacity(a)
        waiting = asyncio.create_task(second._acquire_capacity(b))
        try:
            await asyncio.sleep(0.1)
            assert not waiting.done()
            await first._release_capacity(a)
            await asyncio.wait_for(waiting, 1)
            assert b["capacity"].claim is not None
        finally:
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
            await first._release_capacity(a)
            await second._release_capacity(b)

    asyncio.run(run())


def test_waiter_cancellation_leaves_original_root_obligation(runner_parts, monkeypatch):
    first, second = runner(runner_parts), runner(runner_parts)
    a = owner(first)
    b = owner(
        second,
        DispatchEnvelope(
            envelope().context,
            envelope().tool_manifest,
            envelope().arguments,
            "another-original-request",
        ),
    )

    async def checked(*args):
        return None

    monkeypatch.setattr(CodexCodingRunner, "_cancelled_owned", checked)

    async def run():
        await first._acquire_capacity(a)
        original = a["capacity"].claim
        waiting = asyncio.create_task(second._acquire_capacity(b))
        try:
            await asyncio.sleep(0.05)
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
            await second._release_capacity(b)
            assert a["capacity"].claim == original
        finally:
            await first._release_capacity(a)

    asyncio.run(run())


def test_native_intent_cannot_release_on_task_completion_without_physical_proof(
    runner_parts, monkeypatch
):
    resource = runner(runner_parts)
    entry = owner(resource)

    async def checked(*args):
        return None

    monkeypatch.setattr(CodexCodingRunner, "_cancelled_owned", checked)

    async def run():
        await resource._acquire_capacity(entry)
        gate = entry["capacity"]
        claim = gate.claim
        gate.mark_native_intent(claim["token"])
        try:
            with pytest.raises(DefinitionMismatch):
                await resource._release_capacity(entry)
            assert gate.claim is not None
            entry["stop_evidence"] = {
                "container_id": "a" * 64,
                "generation": claim["generation"],
                "stopped": True,
                "fenced": True,
                "retired": True,
                "container_present": False,
                "pid": 0,
            }
            await resource._release_capacity(entry)
            assert gate.claim is None
        finally:
            gate.close()

    asyncio.run(run())


@pytest.mark.parametrize("name", ["_LOCK", "_RECORD", "_LIMIT", "_hex"])
def test_base_local_runner_pins_transitive_capacity_helpers(runner_parts, monkeypatch, name):
    from ralf_agent import codex_runner_capacity as capacity

    resource = runner(runner_parts)
    original = getattr(capacity, name)
    changed = (
        (lambda *args: True)
        if callable(original)
        else original + 1
        if isinstance(original, int)
        else original + ".other"
    )
    monkeypatch.setattr(capacity, name, changed)
    with pytest.raises(DefinitionMismatch):
        resource._check_root()


def test_instance_capacity_port_cannot_skip_original_release(runner_parts, monkeypatch):
    resource = runner(runner_parts)
    entry = owner(resource)

    async def checked(*args):
        return None

    monkeypatch.setattr(CodexCodingRunner, "_cancelled_owned", checked)

    async def run():
        await resource._acquire_capacity(entry)
        gate = entry["capacity"]
        original = gate.release
        gate.release = lambda *args, **kwargs: None
        try:
            with pytest.raises(DefinitionMismatch):
                await resource._release_capacity(entry)
        finally:
            gate.release = original
            await resource._release_capacity(entry)

    asyncio.run(run())


@pytest.mark.parametrize("name", ["_submit_create", "_recover_create", "_cli", "_read_metadata"])
def test_base_local_runner_pins_original_create_and_cold_control(runner_parts, monkeypatch, name):
    from ralf_agent.codex_environment import DockerCodingEnvironment

    resource = runner(runner_parts)
    monkeypatch.setattr(DockerCodingEnvironment, name, lambda *args, **kwargs: None)
    with pytest.raises(DefinitionMismatch):
        resource._check_root()
