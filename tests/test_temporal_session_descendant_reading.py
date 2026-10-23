"""Closed descendant collection preserves original SDK facts and independent Session exit."""

import asyncio
import copy
from collections import Counter

import pytest

from relf_agent import temporal_deployment_execution as execution
from relf_agent import temporal_session_deployment_verification as verification
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_session_deployment_control import _CheckedClient
from relf_agent.temporal_state import detached
from tests.test_temporal_session_tree_reading import tree_environment


def descendant_environment(monkeypatch, **options):
    validation, client, parent, certificate = tree_environment(monkeypatch, **options)
    handle_type = type(client.get_workflow_handle(parent.run_id))
    original_query = handle_type.query

    async def query(self, name, value):
        if value["kind"] != "session_proof":
            return await original_query(self, name, value)
        assert name == "view" and value["scope"] == parent.scope
        client.reads[(self.identity, "session_proof")] += 1
        state = client.states[self.identity]
        assert "session_history" in state.request
        result = {"scope": state.scope, "request": state.request, **state.diagnostics()}
        result = copy.deepcopy(result)
        if client.hook:
            client.hook(self.identity, "session_proof", result)
        if getattr(client, "block", None):
            await client.block(self.identity, "session_proof")
        return result

    # The SDK boundary returns the actual Run state's original session_proof view.
    # No proof reader, validator, source pin or lifecycle method is replaced.
    monkeypatch.setattr(handle_type, "query", query)
    return validation, client, parent, certificate


async def ready(monkeypatch, **options):
    validation, client, parent, certificate = descendant_environment(monkeypatch, **options)
    readonly = _CheckedClient(validation, _aggregate=True)
    policy = execution._policy(validation.runtime)
    proof = await execution._proof(
        validation.runtime,
        readonly,
        policy,
        parent.scope,
        parent.run_id,
        parent.epoch,
        required=True,
    )
    client.events.clear()
    client.reads.clear()
    return validation, client, parent, certificate, readonly, policy, proof


async def original_descendant_loop(validation, readonly, policy, proof):
    """Reference: the existing control._observe loop, with its real proof readers."""
    descendants, pending, seen = [], list(proof["children"]), {validation.intent["run_id"]}
    while pending:
        child = pending.pop()
        if child.get("dispatch_started") is not True and child.get("started") is not True:
            continue
        child_id, epoch = child["run_id"], child.get("deployment_execution_epoch")
        if child_id in seen or len(seen) >= 4096 or type(epoch) is not str or not epoch:
            raise DefinitionMismatch("Original descendant identity changed")
        seen.add(child_id)
        physical = await execution._proof(
            validation.runtime,
            readonly,
            policy,
            validation.intent["scope"],
            child_id,
            epoch,
            required=True,
        )
        await validation.validate()
        root = await execution._ancestry(
            validation.runtime, readonly, policy, physical, read_only=True
        )
        await validation.validate()
        if root["run_id"] != proof["run_id"] or root["execution_epoch"] != proof["execution_epoch"]:
            raise DefinitionMismatch("Original descendant root changed")
        descendants.append(
            await readonly.get_workflow_handle(child_id, run_id=epoch).query(
                "view", {"kind": "session_proof", "scope": validation.intent["scope"]}
            )
        )
        pending.extend(physical["children"])
    return detached(descendants)


def reader():
    function = getattr(verification, "_read_session_descendants", None)
    assert callable(function), "Closed Session descendant reader is not implemented"
    return function


def test_original_descendant_result_and_non_session_reads_with_one_final_raw_group(monkeypatch):
    async def run():
        validation, client, parent, _, readonly, policy, proof = await ready(monkeypatch)
        # The original loop ignores unstarted entries before inspecting identity fields.
        proof["children"].append({"started": False, "dispatch_started": False})
        baseline = await original_descendant_loop(validation, readonly, policy, proof)
        baseline_reads, baseline_groups = client.reads.copy(), client.events.count("history")
        assert [v["snapshot"]["run_id"] for v in baseline] == [
            c["run_id"] for c in reversed(parent.children)
        ]
        assert baseline_groups > 1
        client.events.clear()
        client.reads.clear()
        function = getattr(verification, "_read_session_descendants", original_descendant_loop)
        result = await function(validation, readonly, policy, proof)
        assert result == baseline
        assert client.reads == baseline_reads
        assert client.writes == []
        assert client.events.count("history") == 1
        assert Counter(client.events[-7:]) == Counter(
            namespace=2,
            describe=2,
            history=1,
            deployment_session_intent=1,
            deployment_session_command=1,
        )
        result[0]["scope"]["principal"] = "caller-mutated"
        assert client.states[parent.children[-1]["run_id"]].scope == parent.scope

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["epoch", "duplicate", "root", "pin", "second_refresh"])
def test_invalid_member_or_original_ancestry_never_returns_descendants(monkeypatch, fault):
    async def run():
        validation, client, parent, _, readonly, policy, proof = await ready(monkeypatch)
        target = parent.children[-1]["run_id"]
        if fault == "epoch":
            proof["children"][-1]["deployment_execution_epoch"] = ""
        elif fault == "duplicate":
            proof["children"].append(copy.deepcopy(proof["children"][-1]))
        elif fault == "root":
            proof["run_id"] = "foreign-original-root"
        elif fault == "pin":
            parent.children[-1]["deployment_execution_epoch"] = None
        else:

            def changed(identity, kind, value):
                if (
                    identity == parent.run_id
                    and kind == "deployment_admission"
                    and client.reads[(identity, kind)] == 2
                ):
                    original = next(c for c in value["children"] if c["run_id"] == target)
                    original["deployment_execution_epoch"] = "changed-on-second-parent-read"

            client.hook = changed
        with pytest.raises(DefinitionMismatch):
            await reader()(validation, readonly, policy, proof)
        if fault == "second_refresh":
            assert client.reads[(parent.run_id, "deployment_admission")] == 2
        if fault in {"pin", "second_refresh"}:
            assert client.reads[(target, "deployment_admission")] == 1
        assert client.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("field", ["intent", "session_origin"])
def test_each_descendant_registry_keeps_complete_original_session_identity(monkeypatch, field):
    async def run():
        validation, client, parent, _, readonly, policy, proof = await ready(monkeypatch)
        target = parent.children[-1]["run_id"]

        def changed(identity, kind, value):
            if kind == "deployment_session_root" and client.member == target:
                value[field]["intent_digest"] = "f" * 64

        client.hook = changed
        with pytest.raises(DefinitionMismatch):
            await reader()(validation, readonly, policy, proof)
        assert client.reads[(target, "deployment_admission")] == 1
        assert client.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["epoch", "namespace"])
def test_final_raw_session_exit_rejects_reset_even_when_outer_validate_is_fake(monkeypatch, fault):
    class OuterValidation(verification.SessionControlValidation):
        async def validate(self):
            raise AssertionError("Outer validate must not replace independent SDK evidence")

    async def run():
        validation, client, parent, _, readonly, policy, proof = await ready(
            monkeypatch, validation_class=OuterValidation
        )
        last = parent.children[0]["run_id"]

        def changed(identity, kind, value):
            if identity == last and kind == "session_proof":
                if fault == "epoch":
                    client.epoch = "reset-original-session"
                else:
                    client.namespace_uuid = "22222222-2222-4222-8222-222222222222"

        client.hook = changed
        with pytest.raises(DefinitionMismatch):
            await reader()(validation, readonly, policy, proof)
        assert sum(n for (_, kind), n in client.reads.items() if kind == "session_proof") == 3
        assert ("describe" if fault == "epoch" else "namespace") in client.events
        assert client.writes == []

    asyncio.run(run())


def test_descendant_method_source_is_pinned_across_original_sdk_await(monkeypatch):
    async def run():
        validation, client, _, _, readonly, policy, proof = await ready(monkeypatch)
        changed = []

        async def foreign(*args, **options):
            raise AssertionError("Foreign reader must never execute")

        def hook(identity, kind, value):
            if kind == "deployment_start" and not changed:
                changed.append(True)
                monkeypatch.setattr(verification._SessionTreeReading, "read_descendants", foreign)

        client.hook = hook
        with pytest.raises(DefinitionMismatch):
            await reader()(validation, readonly, policy, proof)
        assert changed and client.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["exception", "cancelled"])
def test_failed_or_cancelled_collection_settles_read_and_restarts_with_fresh_facts(
    monkeypatch, outcome
):
    async def run():
        validation, client, _, _, readonly, policy, proof = await ready(monkeypatch)
        entered, stopped = asyncio.Event(), asyncio.Event()
        original_error = ConnectionError("Original SDK session_proof unavailable")

        async def block(identity, kind):
            if kind == "session_proof":
                entered.set()
                try:
                    if outcome == "exception":
                        raise original_error
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

        client.block = block
        task = asyncio.create_task(reader()(validation, readonly, policy, proof))
        await entered.wait()
        if outcome == "cancelled":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(ConnectionError) as caught:
                await task
            assert caught.value is original_error
        assert stopped.is_set() and client.writes == []
        assert client.events.count("history") == 0
        client.block = None
        client.events.clear()
        client.reads.clear()
        result = await reader()(validation, readonly, policy, proof)
        assert len(result) == 3
        assert sum(n for (_, kind), n in client.reads.items() if kind == "session_proof") == 3
        assert client.events.count("history") == 1
        assert client.writes == []

    asyncio.run(run())


def test_ordinary_session_is_not_accepted_by_coding_descendant_reader():
    from tests.test_temporal_session_deployment_control import positive_observation

    async def run():
        validation, client = positive_observation()
        intent = validation.intent
        policy = execution._policy(validation.runtime)
        proof = await execution._proof(
            validation.runtime,
            client,
            policy,
            intent["scope"],
            intent["run_id"],
            client.business_epoch,
            required=True,
        )
        with pytest.raises(DefinitionMismatch):
            await reader()(validation, _CheckedClient(validation), policy, proof)

    asyncio.run(run())
