"""Fixed model cases use original Model, Action, approval and metering records."""

import asyncio
import dataclasses
import importlib
import json

import pytest

from relf_agent.adapter_contract_types import AdapterContractCleanupPending
from relf_agent.errors import ValidationError


def api():
    try:
        return importlib.import_module("relf_agent.model_adapter_contract")
    except ModuleNotFoundError:
        pytest.fail("The actual fixed ModelProvider cases are missing")


def fixture():
    return importlib.import_module(
        "relf_agent.model_adapter_contract_reference"
    ).offline_model_fixture()


@pytest.mark.parametrize("case_id", [f"P{n:02}" for n in range(1, 17)])
def test_model_case_uses_actual_provider_and_original_run(case_id, tmp_path):
    result = asyncio.run(api().run_model_case(case_id, fixture(), tmp_path))
    assert (result.status, result.code) == ("passed", "verified"), result.to_dict()
    assert result.adapter_digest and result.configuration_digest
    assert result.observations["cleanup_complete"]
    if case_id != "P01":
        assert result.execution_authority == "local"
        assert result.observations["consumer_runs"] >= 1
    if case_id == "P10":
        assert result.observations["model_calls"] == 1
        assert result.observations["received_count"] == result.observations["adopted_count"] == 1
    if case_id == "P16":
        assert result.observations["model_calls"] == 1
        assert result.observations["received_count"] == result.observations["adopted_count"] == 0
        assert result.observations["write_count"] == 0


class ChangedFixture:
    def __init__(self, transform):
        self.transform, self.session = transform, None

    def prepare(self, case_id, workspace):
        self.session = self.transform(fixture().prepare(case_id, workspace))
        return self.session


@pytest.mark.parametrize(
    "case_id,missing",
    [
        ("P01", "audit"),
        ("P02", "configure"),
        ("P04", "configure"),
        ("P05", "inject_fault"),
        ("P06", "pause"),
        ("P06", "inject_fault"),
        ("P07", "inject_fault"),
        ("P08", "pause"),
        ("P10", "reopen"),
        ("P11", "configure"),
        ("P16", "inject_fault"),
        ("P16", "reopen"),
    ],
)
def test_missing_fixture_hook_is_not_verified(case_id, missing, tmp_path):
    changed = ChangedFixture(lambda session: dataclasses.replace(session, **{missing: None}))
    result = asyncio.run(api().run_model_case(case_id, changed, tmp_path))
    assert (result.status, result.code) == ("not_verified", "missing_fixture_capability")
    assert result.observations["cleanup_complete"]


def test_invalid_fixture_verdict_cannot_supply_provider(tmp_path):
    class Verdict:
        def prepare(self, case_id, workspace):
            return {"status": "passed"}

    result = asyncio.run(api().run_model_case("P01", Verdict(), tmp_path))
    assert (result.status, result.code) == ("failed", "invalid_fixture_session")


def test_original_generic_port_does_not_require_extensions(tmp_path):
    changed = ChangedFixture(lambda session: session)
    result = asyncio.run(api().run_model_case("P01", changed, tmp_path))
    assert result.status == "passed"
    assert not hasattr(changed.session.provider, "stream")
    assert not hasattr(changed.session.provider, "continuation")


def test_audit_must_be_detached_fixed_primitives(tmp_path):
    changed = ChangedFixture(lambda s: dataclasses.replace(s, audit=lambda: {"output": "private"}))
    result = asyncio.run(api().run_model_case("P01", changed, tmp_path))
    assert result.status == "failed"
    assert "private" not in str(result.to_dict())


def test_historical_borrowed_closes_do_not_become_current_close(tmp_path):
    counters = {"model_calls": 0, "request_count": 0, "response_count": 0, "close_calls": 9}

    def transform(s):
        original = s.audit

        def audit():
            counters.update(original())
            counters["close_calls"] += 9
            return counters

        return dataclasses.replace(s, resources=(), audit=audit)

    changed = ChangedFixture(transform)
    result = asyncio.run(api().run_model_case("P08", changed, tmp_path))
    try:
        assert result.status == "passed", result.to_dict()
        assert result.observations["close_calls"] == 0
        assert result.observations["borrowed_closed"] is False
    finally:
        asyncio.run(changed.session.provider.source.aclose())


def test_invalid_case_selection_does_no_preparation(tmp_path):
    class NoIO:
        def prepare(self, *args):
            raise AssertionError("fixture touched")

    with pytest.raises(ValidationError):
        asyncio.run(api().run_model_case("P99", NoIO(), tmp_path))


@pytest.mark.parametrize("boundary", ["before-dispatch", "during-complete"])
def test_original_local_acceptance_rejects_replaced_complete_binding(tmp_path, boundary):
    from relf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolRegistry

    async def run():
        entered, released = asyncio.Event(), asyncio.Event()

        class Provider:
            identity = {"kind": "actual-method-boundary", "version": "1"}
            calls = 0

            async def complete(self, messages, tools):
                self.calls += 1
                entered.set()
                if boundary == "during-complete":
                    await released.wait()
                return ModelResponse(output={"original": True})

        provider = Provider()
        with LocalEngine(
            SQLiteStore(tmp_path / "methods.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="submit", budget=4)
            original = provider.complete

            async def replacement(messages, tools):
                return await original(messages, tools)

            if boundary == "during-complete":
                task = asyncio.create_task(engine.drive(handle.run_id))
                await entered.wait()
                provider.complete = replacement
                released.set()
                result = await task
                assert result.state == "failed" and result.error == {"code": "definition_mismatch"}
                action = engine.store.run(handle.run_id)["actions"][0]
                assert action["status"] == "response_received"
                assert action["received_response"]["output"] == {"original": True}
                assert action["attempts"][0]["status"] == "completed"
                assert engine.store.budget(handle.run_id) == {"limit": 4, "held": 0, "spent": 1}
                assert provider.calls == 1
            else:
                provider.complete = replacement
                try:
                    result = await engine.drive(handle.run_id)
                except Exception as exc:
                    assert getattr(exc, "code", None) == "definition_mismatch"
                else:
                    assert result.state == "failed" and result.error == {
                        "code": "definition_mismatch"
                    }
                assert engine.store.run(handle.run_id)["actions"] == []
                assert engine.store.budget(handle.run_id) == {"limit": 4, "held": 0, "spent": 0}
                assert provider.calls == 0
            provider.complete = original

    asyncio.run(run())


def test_first_acceptance_supports_unhashable_nonweakref_provider_and_preaccept_replace(tmp_path):
    from relf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolRegistry

    class Provider:
        __slots__ = ("number",)
        __hash__ = None

        def __init__(self, number):
            self.number = number

        @property
        def identity(self):
            return {"kind": "plain-model-port", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output={"number": self.number})

    async def run():
        with LocalEngine(
            SQLiteStore(tmp_path / "plain.sqlite"),
            providers={"default": Provider(1)},
            tools=ToolRegistry(),
        ) as engine:
            engine.providers["default"] = Provider(2)
            handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="submit")
            result = await engine.drive(handle.run_id)
            assert result.result == {"number": 2}

    asyncio.run(run())


def test_current_provider_churn_releases_historical_objects(tmp_path):
    import gc
    import weakref

    from relf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolRegistry

    class Provider:
        identity = {"kind": "current-provider-churn", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output={"completed": True})

    async def run():
        previous = []
        with LocalEngine(
            SQLiteStore(tmp_path / "churn.sqlite"),
            providers={"default": Provider()},
            tools=ToolRegistry(),
        ) as engine:
            for number in range(24):
                previous.append(weakref.ref(engine.providers["default"]))
                engine.providers["default"] = Provider()
                handle = engine.submit(
                    AgentSpec("a", "Answer"), "task", command_id=f"submit-{number}"
                )
                assert (await engine.drive(handle.run_id)).state == "succeeded"
            gc.collect()
            assert all(ref() is None for ref in previous)

    asyncio.run(run())


def test_fixture_signal_without_actual_complete_suspension_cannot_pass(tmp_path):
    async def immediate():
        return None

    changed = ChangedFixture(
        lambda session: dataclasses.replace(
            session, pause=lambda name: api().ModelContractPause(immediate, immediate)
        )
    )
    result = asyncio.run(api().run_model_case("P08", changed, tmp_path))
    assert result.status == "failed"
    assert result.observations["cleanup_complete"]


def test_ignored_fault_and_supplier_counter_cannot_create_original_rejection(tmp_path):
    changed = ChangedFixture(
        lambda session: dataclasses.replace(session, inject_fault=lambda kind: None)
    )
    result = asyncio.run(api().run_model_case("P05", changed, tmp_path))
    assert result.status == "failed"
    assert result.observations["received_count"] == 1


def test_close_failure_keeps_original_resource_owner_for_retry(tmp_path):
    attempts = []

    class Owner:
        def __init__(self, source):
            self.source = source

        async def aclose(self):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("private temporary resource close failure")
            await self.source.aclose()

    def transform(session):
        owner = Owner(session.provider.source)
        return dataclasses.replace(
            session, resources=(api().ModelContractResource(owner, asynchronous=True),)
        )

    changed = ChangedFixture(transform)

    async def run():
        with pytest.raises(AdapterContractCleanupPending) as captured:
            await api().run_model_case("P09", changed, tmp_path)
        pending = captured.value
        assert pending.result.code == "cleanup_failed"
        assert not pending.result.observations["cleanup_complete"]
        assert changed.session.provider.source._closed is False
        await pending.cleanup()
        assert changed.session.provider.source._closed is True
        assert len(attempts) == 2

    asyncio.run(run())


def test_observation_cancellation_drains_actual_provider_before_owned_close(tmp_path):
    started = None

    async def run():
        nonlocal started
        started = asyncio.Event()

        def transform(session):
            original_pause = session.pause

            def pause(name):
                actual = original_pause(name)

                async def entered():
                    await actual.wait_entered()
                    started.set()

                return api().ModelContractPause(entered, actual.release)

            return dataclasses.replace(session, pause=pause)

        changed = ChangedFixture(transform)
        operation = asyncio.create_task(api().run_model_case("P08", changed, tmp_path))
        await started.wait()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        source = changed.session.provider.source
        assert source._closed and source._file_descriptor is None
        audit = source.audit()
        assert audit["model_calls"] == audit["response_count"] == audit["close_calls"] == 1
        from relf_agent import SQLiteStore

        with SQLiteStore(tmp_path / "consumer-0.sqlite", readonly=True) as store:
            record = json.loads(store.conn.execute("SELECT data FROM runs").fetchone()[0])
            action = record["actions"][0]
            assert record["state"] == "cancelled"
            assert action["received_response"] is not None
            assert store.budget(record["id"])["held"] == 0
        assert not [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]

    asyncio.run(run())


def test_cancelled_preparation_retains_then_closes_original_allocated_owner(tmp_path):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class Preparing:
            session = None

            async def prepare(self, case_id, workspace):
                self.session = fixture().prepare(case_id, workspace)
                entered.set()
                await release.wait()
                return self.session

        preparing = Preparing()
        operation = asyncio.create_task(api().run_model_case("P01", preparing, tmp_path))
        await entered.wait()
        operation.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        source = preparing.session.provider.source
        assert source._closed and source._file_descriptor is None
        assert source.audit()["close_calls"] == 1
        assert source.audit()["model_calls"] == 0

    asyncio.run(run())


@pytest.mark.parametrize("mutate_original_method", [False, True])
def test_completed_executing_provider_cannot_be_replaced_by_equal_current_provider(
    tmp_path, mutate_original_method
):
    from relf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolRegistry

    async def run():
        entered, released = asyncio.Event(), asyncio.Event()

        class Provider:
            identity = {"kind": "executing-owner-replacement", "version": "1"}

            def __eq__(self, other):
                return isinstance(other, Provider)

            async def complete(self, messages, tools):
                entered.set()
                await released.wait()
                return ModelResponse(output={"original": True})

        original = Provider()
        with LocalEngine(
            SQLiteStore(tmp_path / "owner.sqlite"),
            providers={"default": original},
            tools=ToolRegistry(),
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="submit", budget=4)
            task = asyncio.create_task(engine.drive(handle.run_id))
            await entered.wait()
            if mutate_original_method:
                original_complete = original.complete

                async def changed(messages, tools):
                    return await original_complete(messages, tools)

                original.complete = changed
            engine.providers["default"] = Provider()
            released.set()
            result = await task
            assert result.state == "failed" and result.error == {"code": "definition_mismatch"}
            action = engine.store.run(handle.run_id)["actions"][0]
            assert action["status"] == "response_received"
            assert action["received_response"]["output"] == {"original": True}
            assert action["attempts"][0]["status"] == "completed"
            assert engine.store.budget(handle.run_id) == {"limit": 4, "held": 0, "spent": 1}
            assert len(engine.store.run(handle.run_id)["actions"]) == 1

    asyncio.run(run())


def test_original_request_and_received_evidence_survive_supplier_alias_mutation(tmp_path):
    captured = []

    def transform(session):
        actual = session.provider

        class CapturedProvider:
            @property
            def identity(self):
                return actual.identity

            async def complete(self, messages, tools):
                response = await actual.complete(messages, tools)
                captured.append((messages, tools, response))
                return response

        return dataclasses.replace(session, provider=CapturedProvider())

    result = asyncio.run(api().run_model_case("P03", ChangedFixture(transform), tmp_path))
    assert result.status == "passed"
    assert len(captured) == 1
    from relf_agent import SQLiteStore

    with SQLiteStore(tmp_path / "consumer-0.sqlite", readonly=True) as store:
        before = json.loads(store.conn.execute("SELECT data FROM runs").fetchone()[0])
        messages, _, response = captured[0]
        messages[0]["content"] = "private supplier mutation"
        response.output["items"].append("private supplier mutation")
        after = store.run(before["id"])
        assert after == before
        assert "private supplier mutation" not in str(after)


def test_original_per_agent_provider_override_has_independent_live_method_pin(tmp_path):
    from relf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, SQLiteStore, ToolRegistry
    from relf_agent.binding_catalog import BindingCatalog
    from relf_agent.binding_definitions import AgentDefinition
    from relf_agent.binding_types import AgentBindingDescriptor, BindingSelection

    class Provider:
        def __init__(self, name):
            self.name = name

        @property
        def identity(self):
            return {"kind": "per-agent-provider", "name": self.name, "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output={"name": self.name})

    async def run():
        scope = Scope()
        host, selected = Provider("host"), Provider("selected")
        catalog = BindingCatalog(scope=scope)
        catalog.register("provider", "selected", "1", selected)
        definition = AgentDefinition(
            AgentSpec("a", "Answer"),
            AgentBindingDescriptor(provider=BindingSelection.ref("selected", "1")),
        )
        with LocalEngine(
            SQLiteStore(tmp_path / "bound.sqlite"),
            providers={"default": host},
            tools=ToolRegistry(),
            binding_catalog=catalog,
            scope=scope,
        ) as engine:
            handle = engine.submit(definition, "task", command_id="bound")
            assert (await engine.drive(handle.run_id)).result == {"name": "selected"}
            handle = engine.submit(definition, "task", command_id="bound-drift")
            original = selected.complete

            async def changed(messages, tools):
                return await original(messages, tools)

            selected.complete = changed
            try:
                await engine.drive(handle.run_id)
            except Exception as exc:
                assert getattr(exc, "code", None) == "definition_mismatch"
            else:
                raise AssertionError("Original per-Agent method mutation was accepted")
            assert engine.store.run(handle.run_id)["actions"] == []
            selected.complete = original
            host_handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="host")
            assert (await engine.drive(host_handle.run_id)).result == {"name": "host"}

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["before-dispatch", "during-complete"])
def test_equal_bound_supplier_receiver_cannot_replace_original_complete(tmp_path, boundary):
    from relf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolRegistry

    async def run():
        entered, released = asyncio.Event(), asyncio.Event()
        comparisons = []

        class Provider:
            identity = {"kind": "actual-equal-receiver", "version": "1"}

            def __init__(self, name):
                self.name, self.calls = name, 0

            def __eq__(self, other):
                comparisons.append(1)
                return isinstance(other, Provider)

            async def complete(self, messages, tools):
                self.calls += 1
                entered.set()
                if boundary == "during-complete":
                    await released.wait()
                return ModelResponse(output={"receiver": self.name})

        original, substitute = Provider("original"), Provider("substitute")
        with LocalEngine(
            SQLiteStore(tmp_path / "equal-method.sqlite"),
            providers={"default": original},
            tools=ToolRegistry(),
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="submit", budget=4)
            task = None
            if boundary == "during-complete":
                task = asyncio.create_task(engine.drive(handle.run_id))
                await entered.wait()
            original.complete = substitute.complete
            released.set()
            try:
                result = await task if task is not None else await engine.drive(handle.run_id)
            except Exception as exc:
                assert getattr(exc, "code", None) == "definition_mismatch"
            else:
                assert result.state == "failed" and result.error == {"code": "definition_mismatch"}
            record = engine.store.run(handle.run_id)
            if boundary == "during-complete":
                action = record["actions"][0]
                assert action["status"] == "response_received"
                assert action["received_response"]["output"] == {"receiver": "original"}
                assert action["attempts"][0]["status"] == "completed"
                assert engine.store.budget(handle.run_id) == {"limit": 4, "held": 0, "spent": 1}
                assert original.calls == 1 and substitute.calls == 0
            else:
                assert record["actions"] == []
                assert engine.store.budget(handle.run_id) == {"limit": 4, "held": 0, "spent": 0}
                assert original.calls == substitute.calls == 0
            assert comparisons == []
            await engine.wait_for_threads()

    asyncio.run(run())


def test_p01_invalid_returned_lazy_output_is_disposed_without_fixture_verdict(tmp_path):
    import inspect

    from relf_agent import ModelResponse

    async def lazy():
        return None

    coroutine = lazy()

    def transform(session):
        original = session.provider.complete

        async def complete(messages, tools):
            await original(messages, tools)
            return ModelResponse(output={"lazy": coroutine})

        session.provider.complete = complete
        return session

    changed = ChangedFixture(transform)
    try:
        result = asyncio.run(api().run_model_case("P01", changed, tmp_path))
        assert result.status == "failed"
        assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
        assert changed.session.provider.source._closed
        assert changed.session.provider.source.audit()["close_calls"] == 1
    finally:
        coroutine.close()


@pytest.mark.parametrize("kind", ["coroutine", "generator"])
def test_p01_disposes_whole_lazy_return_before_rejecting_unsupported_type(tmp_path, kind):
    import inspect

    async def lazy_coroutine():
        return None

    def lazy_generator():
        yield None

    lazy = lazy_coroutine() if kind == "coroutine" else lazy_generator()

    def transform(session):
        original = session.provider.complete

        async def complete(messages, tools):
            await original(messages, tools)
            return lazy

        session.provider.complete = complete
        return session

    changed = ChangedFixture(transform)
    try:
        result = asyncio.run(api().run_model_case("P01", changed, tmp_path))
        assert result.status == "failed" and result.observations["cleanup_complete"]
        assert changed.session.provider.source._closed
        if kind == "coroutine":
            assert inspect.getcoroutinestate(lazy) == inspect.CORO_CLOSED
        else:
            assert inspect.getgeneratorstate(lazy) == inspect.GEN_CLOSED
    finally:
        lazy.close()
