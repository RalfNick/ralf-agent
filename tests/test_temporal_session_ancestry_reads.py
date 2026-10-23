"""Nested admission keeps all original edge facts without repeating Session origin reads."""

import asyncio
import copy
from collections import Counter

import pytest

from relf_agent import temporal_deployment_execution as execution
from relf_agent.errors import DefinitionMismatch
from relf_agent.types import canonical, digest
from tests.test_temporal_coding_observe_validation import environment

ACTIVITIES = [
    execution.ACTIVITY,
    "ralf.temporal.control.v1",
    "ralf.temporal.selection.v1",
    "ralf.temporal.tool.v1",
]
SESSION = {"deployment_session_intent", "deployment_session_command"}


def nested_environment(monkeypatch):
    e = environment(monkeypatch, nested_depth=3)
    leaf = next(s for s in e.client.states.values() if not getattr(s, "children", None))
    e.call = next(
        c
        for s in e.client.states.values()
        for c in getattr(s, "children", [])
        if c["run_id"] == leaf.run_id
    )
    e.info.workflow_id, e.info.workflow_run_id = leaf.run_id, leaf.epoch
    e.info.activity_type = "ralf.temporal.tool.v1"
    e.request = {
        "scope": copy.deepcopy(e.parent.scope),
        "run_id": leaf.run_id,
        "execution_epoch": leaf.epoch,
        "runtime_manifest": copy.deepcopy(e.parent.manifest),
    }
    return e


@pytest.mark.parametrize("activity_type", ACTIVITIES)
def test_nested_activity_keeps_all_original_node_reads_and_two_independent_origins(
    monkeypatch, activity_type
):
    async def run():
        e = nested_environment(monkeypatch)
        before = canonical([e.request, e.client.record, e.call])
        e.info.activity_type = "unrecognized-legacy-path"
        baseline = await execution.validate_activity(e.runtime, e.client, e.request, e.info)
        counts = Counter(
            {k: n for k, n in e.counts.items() if k[0] == "query" and k[1] not in SESSION}
        )
        assert e.client.events.count("history") == 7
        e.info.activity_type = activity_type
        e.counts.clear()
        e.client.events.clear()
        result = await execution.validate_activity(e.runtime, e.client, e.request, e.info)
        assert result == baseline
        assert (
            Counter({k: n for k, n in e.counts.items() if k[0] == "query" and k[1] not in SESSION})
            == counts
        )
        assert e.client.events.count("history") == 2
        assert e.counts[("query", "deployment_session_intent")] == 2
        assert e.counts[("query", "deployment_session_command")] == 2
        assert canonical([e.request, e.client.record, e.call]) == before
        assert not e.probe.writes and not e.client.writes

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["parent-pin", "session-command", "namespace", "runtime"])
@pytest.mark.parametrize("entrypoint", ["activity", "bootstrap"])
def test_nested_activity_rejects_drift_across_original_sdk_reads(monkeypatch, fault, entrypoint):
    async def run():
        e = nested_environment(monkeypatch)
        changed = []
        parent_id = next(
            s.run_id for s in e.client.states.values() if e.call in getattr(s, "children", [])
        )

        def change(identity, kind, result):
            if (
                identity != parent_id
                or kind != "deployment_admission"
                or e.client.reads[(identity, kind)] != 2
            ):
                return
            changed.append(True)
            if fault == "parent-pin":
                result["children"][0]["deployment_execution_epoch"] = "replaced-epoch"
                result["proof_digest"] = digest(
                    {k: v for k, v in result.items() if k != "proof_digest"}
                )
            elif fault == "session-command":
                e.client.intent["session_command_id"] = "foreign-command"
            elif fault == "namespace":
                e.client.namespace_uuid = "22222222-2222-4222-8222-222222222222"
            else:
                e.runtime.manifest["providers"]["default"]["version"] = "foreign"

        e.client.hook = change
        with pytest.raises(DefinitionMismatch):
            if entrypoint == "activity":
                await execution.validate_activity(e.runtime, e.client, e.request, e.info)
            else:
                from relf_agent.temporal_deployment_coding_bridge import _ReadOnlyClient
                from relf_agent.temporal_deployment_coding_validation import CodingValidation

                validator = CodingValidation(e.runtime, e.client, e.request, e.info)
                await validator._bootstrap_nodes(_ReadOnlyClient(e.client))
        assert changed and not e.probe.writes and not e.client.writes

    asyncio.run(run())


def test_missing_nested_pin_returns_no_proposal_without_writing(monkeypatch):
    async def run():
        from relf_agent.temporal_session_activity_reads import read_ancestry

        e = nested_environment(monkeypatch)
        original = await e.client.get_workflow_handle(
            e.info.workflow_id, run_id=e.info.workflow_run_id
        ).query("view", {"scope": e.parent.scope, "kind": "deployment_admission"})
        e.call["deployment_execution_epoch"] = None
        result = await read_ancestry(e.runtime, e.client, e.registry.policy, original, e.info)
        assert result is None and not e.probe.writes and not e.client.writes

    asyncio.run(run())


def test_nested_coding_bootstrap_keeps_node_facts_without_repeating_session_origins(monkeypatch):
    from relf_agent.temporal_deployment_coding_bridge import _ReadOnlyClient
    from relf_agent.temporal_deployment_coding_validation import CodingValidation

    async def run():
        e = nested_environment(monkeypatch)
        e.info.activity_type = "unrecognized-legacy-path"
        validator = CodingValidation(e.runtime, e.client, e.request, e.info)
        baseline = await validator._bootstrap_nodes(_ReadOnlyClient(e.client))
        counts = Counter(
            {k: n for k, n in e.counts.items() if k[0] == "query" and k[1] not in SESSION}
        )
        assert e.client.events.count("history") == 10
        e.info.activity_type = "ralf.temporal.tool.v1"
        validator = CodingValidation(e.runtime, e.client, e.request, e.info)
        e.counts.clear()
        e.client.events.clear()
        result = await validator._bootstrap_nodes(_ReadOnlyClient(e.client))
        assert result == baseline
        assert (
            Counter({k: n for k, n in e.counts.items() if k[0] == "query" and k[1] not in SESSION})
            == counts
        )
        # Leaf and three follow-up proofs retain their own independent verifier;
        # the existing deep ancestry reader adds one for the complete ancestor set.
        assert e.client.events.count("history") == 5
        assert e.counts[("query", "deployment_session_intent")] == 5
        assert e.counts[("query", "deployment_session_command")] == 5
        assert not e.probe.writes and not e.client.writes

    asyncio.run(run())


def test_nested_reading_refuses_component_change_during_final_independent_session_read(monkeypatch):
    from relf_agent.temporal_session_activity_reads import read_ancestry

    async def run():
        e = nested_environment(monkeypatch)
        original = await e.client.get_workflow_handle(
            e.info.workflow_id, run_id=e.info.workflow_run_id
        ).query("view", {"scope": e.parent.scope, "kind": "deployment_admission"})
        changed = []

        def change(identity, kind):
            if kind == "deployment_session_intent" and not changed:
                changed.append(True)
                e.runtime.manifest["providers"]["default"]["version"] = "foreign"

        e.probe.before_query = change
        accepted = []
        with pytest.raises(DefinitionMismatch):
            accepted.append(
                await read_ancestry(e.runtime, e.client, e.registry.policy, original, e.info)
            )
        assert changed and not accepted
        assert not e.probe.writes and not e.client.writes

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["cancel", "release-drift"])
def test_failed_reading_retry_reads_original_session_facts_again(monkeypatch, failure):
    from relf_agent.temporal_session_activity_reads import read_ancestry

    async def run():
        e = nested_environment(monkeypatch)
        original = await e.client.get_workflow_handle(
            e.info.workflow_id, run_id=e.info.workflow_run_id
        ).query("view", {"scope": e.parent.scope, "kind": "deployment_admission"})
        provider = copy.deepcopy(e.runtime.manifest["providers"]["default"])
        interrupted = []

        def stop(identity, kind):
            if kind == "deployment_session_intent" and not interrupted:
                interrupted.append(True)
                if failure == "cancel":
                    raise asyncio.CancelledError
                e.runtime.manifest["providers"]["default"]["version"] = "foreign"

        e.probe.before_query = stop
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else DefinitionMismatch):
            await read_ancestry(e.runtime, e.client, e.registry.policy, original, e.info)
        assert interrupted and not e.probe.writes and not e.client.writes
        before = e.counts[("query", "deployment_session_intent")]
        e.probe.before_query = None
        e.runtime.manifest["providers"]["default"] = provider
        result = await read_ancestry(e.runtime, e.client, e.registry.policy, original, e.info)
        assert result["run_id"] == e.parent.run_id
        assert e.counts[("query", "deployment_session_intent")] == before + 1
        assert e.counts[("query", "deployment_session_command")] >= 1
        assert e.client.events.count("history") >= 1
        assert not e.probe.writes and not e.client.writes

    asyncio.run(run())


@pytest.mark.parametrize("port", ["entry", "method", "sources", "ancestry"])
@pytest.mark.parametrize("entrypoint", ["activity", "admit", "bootstrap"])
def test_first_sdk_read_cannot_replace_later_ancestry_implementation(monkeypatch, port, entrypoint):
    from relf_agent import temporal_deployment_execution_state as admission
    from relf_agent import temporal_session_activity_reads as readings

    async def run():
        e = nested_environment(monkeypatch)
        changed, foreign_calls = [], []
        original_sources = readings.source_bindings()

        async def foreign(*args, **kwargs):
            foreign_calls.append(True)
            return admission.view(e.parent)

        def sources():
            foreign_calls.append(True)
            return original_sources

        def change(identity, kind):
            if kind != "deployment_session_intent" or changed:
                return
            changed.append(True)
            e.call["deployment_execution_epoch"] = "foreign-parent-pin"
            if port == "entry":
                monkeypatch.setattr(readings, "read_ancestry", foreign)
            elif port == "method":
                monkeypatch.setattr(readings._ActivityReading, "read_ancestry", foreign)
            elif port == "sources":
                monkeypatch.setattr(readings, "source_bindings", sources)
            else:
                monkeypatch.setattr(execution, "_ancestry", foreign)

        e.probe.before_query = change
        with pytest.raises(DefinitionMismatch):
            if entrypoint == "activity":
                await execution.validate_activity(e.runtime, e.client, e.request, e.info)
            elif entrypoint == "bootstrap":
                from relf_agent.temporal_deployment_coding_bridge import _ReadOnlyClient
                from relf_agent.temporal_deployment_coding_validation import CodingValidation

                validator = CodingValidation(e.runtime, e.client, e.request, e.info)
                await validator._bootstrap_nodes(_ReadOnlyClient(e.client))
            else:
                state = e.client.states[e.info.workflow_id]
                await execution.admit(
                    e.runtime,
                    e.client,
                    {
                        "scope": state.scope,
                        "run_id": state.run_id,
                        "execution_epoch": state.epoch,
                        "command_id": e.call["command_id"],
                        "request": state.request,
                        "runtime_manifest": state.manifest,
                        "deployment_admission": state.deployment_admission,
                    },
                    e.info,
                )
        assert changed and not foreign_calls
        assert not e.probe.writes and not e.client.writes

    asyncio.run(run())
