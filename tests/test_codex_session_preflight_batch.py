"""Eight selected Session control reads settle before native business admission."""

import asyncio
import copy
from contextlib import suppress
from types import SimpleNamespace

import pytest

from ralf_agent.codex_coding_profile import CodexCodingProfile
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.types import digest
from tests.test_codex_coding_profile import native_results
from tests.test_codex_deployment_control_validation_cost import fixture

METHODS = (
    "config/read",
    "configRequirements/read",
    "experimentalFeature/list",
    "permissionProfile/list",
    "mcpServerStatus/list",
    "skills/list",
    "plugin/list",
    "plugin/installed",
)


def preflight(monkeypatch, *, version=4, coding=True, history=True):
    runner, owner, calls, hook = fixture(monkeypatch, version=version)
    authority = owner["authority"]
    if coding:
        authority._request["runtime_manifest"]["coding_execution_protocol"] = {"version": 6}
        authority._proof["request_digest"] = digest(authority._request)
    if not history:
        owner.pop("history")
    results, events, profiled = native_results(), [], []

    def validate(values):
        events.append("profile")
        profiled.append(copy.deepcopy(values))
        return CodexCodingProfile().validate_control(values)

    runner._profile = SimpleNamespace(validate_control=validate)

    class Transport:
        async def request(self, method, params):
            assert method == "initialize" or events[:2] == ["initialize", "initialized"]
            events.append(method)
            return copy.deepcopy(results[method])

        async def notify(self, method):
            assert method == "initialized" and events == ["initialize"]
            events.append(method)

    owner["transport"] = Transport()
    return runner, owner, calls, hook, events, profiled


def test_selected_eight_reads_overlap_after_handshake_and_each_keep_fresh_checks(monkeypatch):
    async def scenario():
        runner, owner, calls, _, events, profiled = preflight(monkeypatch)
        transport = owner["transport"]
        original = transport.request
        original_notify = transport.notify
        initializing, allow_initialize = asyncio.Event(), asyncio.Event()
        notifying, allow_notify = asyncio.Event(), asyncio.Event()
        all_started, release = asyncio.Event(), asyncio.Event()
        started = []

        async def request(method, params):
            if method == "initialize":
                initializing.set()
                await allow_initialize.wait()
            else:
                started.append(method)
                if len(started) == 8:
                    all_started.set()
                await release.wait()
            return await original(method, params)

        async def notify(method):
            await original_notify(method)
            notifying.set()
            await allow_notify.wait()

        transport.request = request
        transport.notify = notify
        task = asyncio.create_task(runner._preflight(owner))
        try:
            await asyncio.wait_for(initializing.wait(), 1)
            assert not started and not notifying.is_set()
            allow_initialize.set()
            await asyncio.wait_for(notifying.wait(), 1)
            assert not started and not profiled
            allow_notify.set()
            await asyncio.wait_for(all_started.wait(), 1)
            assert not task.done() and not profiled
            assert started == list(METHODS)
        finally:
            allow_initialize.set()
            allow_notify.set()
            release.set()
            await task
        assert list(profiled[0]) == ["initialize", *METHODS]
        assert calls.count("query") == 9 and calls.count("validate") == 18
        assert events[:2] == ["initialize", "initialized"] and events[-1] == "profile"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure", [RuntimeError("original read failed"), asyncio.CancelledError()]
)
def test_failed_reader_waits_for_all_other_reads_before_rejecting(monkeypatch, failure):
    async def scenario():
        runner, owner, _, _, _, profiled = preflight(monkeypatch)
        transport, started, finished = owner["transport"], [], []
        original = transport.request
        all_started, release, failed = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def request(method, params):
            if method == "initialize":
                return await original(method, params)
            started.append(method)
            if len(started) == 8:
                all_started.set()
            try:
                if method == METHODS[0]:
                    await all_started.wait()
                    failed.set()
                    raise failure
                await release.wait()
                return await original(method, params)
            finally:
                finished.append(method)

        transport.request = request
        task = asyncio.create_task(runner._preflight(owner))
        try:
            await asyncio.wait_for(failed.wait(), 1)
            await asyncio.sleep(0)
            assert not task.done() and not profiled
        finally:
            release.set()
            if not all_started.is_set():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(type(failure)):
                    await task
        assert set(finished) == set(METHODS) and not profiled

    asyncio.run(scenario())


def test_caller_cancellation_cancels_and_drains_all_eight_reads(monkeypatch):
    async def scenario():
        runner, owner, _, _, _, profiled = preflight(monkeypatch)
        transport, started, cancelled, finished = owner["transport"], [], [], []
        original = transport.request
        all_started, all_cancelled, drain = asyncio.Event(), asyncio.Event(), asyncio.Event()
        errors = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda loop, context: errors.append(context))

        async def request(method, params):
            if method == "initialize":
                return await original(method, params)
            started.append(method)
            if len(started) == 8:
                all_started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.append(method)
                if len(cancelled) == 8:
                    all_cancelled.set()
                await drain.wait()
                raise
            finally:
                finished.append(method)

        transport.request = request
        task = asyncio.create_task(runner._preflight(owner))
        try:
            await asyncio.wait_for(all_started.wait(), 1)
            task.cancel()
            await asyncio.wait_for(all_cancelled.wait(), 1)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not finished and not profiled
        finally:
            drain.set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert set(finished) == set(METHODS) and not profiled
        await asyncio.sleep(0)
        assert not errors

    asyncio.run(scenario())


@pytest.mark.parametrize("version,coding", [(3, True), (4, False), (None, False), ("local", True)])
def test_unselected_preflight_retains_original_serial_control_order(monkeypatch, version, coding):
    async def scenario():
        runner, owner, _, _, events, profiled = preflight(
            monkeypatch, version=version, coding=coding
        )
        if version == "local":
            owner.pop("history")
            owner["authority"] = SimpleNamespace(cancelled=lambda: False)
        transport, active = owner["transport"], 0
        original = transport.request

        async def request(method, params):
            nonlocal active
            active += 1
            assert active == 1
            await asyncio.sleep(0)
            try:
                return await original(method, params)
            finally:
                active -= 1

        transport.request = request
        await runner._preflight(owner)
        assert events == ["initialize", "initialized", *METHODS, "profile"]
        assert len(profiled) == 1

    asyncio.run(scenario())


def test_selected_preflight_rejects_original_source_callback_drift(monkeypatch):
    async def scenario():
        runner, owner, _, hook, _, profiled = preflight(monkeypatch)
        original = owner["transport"].notify

        async def notify(method):
            await original(method)
            hook(lambda: setattr(owner["authority"], "_query", lambda *args: None))

        owner["transport"].notify = notify
        with pytest.raises(DefinitionMismatch):
            await runner._preflight(owner)
        assert not profiled

    asyncio.run(scenario())
