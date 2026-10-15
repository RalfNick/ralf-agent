"""MODEL/CONTEXT keep original node reads and one independent Session read set."""

import asyncio
import copy
from collections import Counter

import pytest

from ralf_agent import temporal_deployment_execution as execution
from ralf_agent.types import canonical
from tests.test_temporal_coding_observe_validation import environment

MODEL = "ralf.temporal.model.v1"
CONTEXT = "ralf.temporal.context.v1"
TOOL = "ralf.temporal.tool.v1"
SESSION_QUERIES = {"deployment_session_intent", "deployment_session_command"}


def activity_environment(monkeypatch, activity_type=MODEL):
    e = environment(monkeypatch)
    e.info.workflow_id = e.call["run_id"]
    e.info.workflow_run_id = e.call["deployment_execution_epoch"]
    e.info.activity_type = activity_type
    e.info.activity_id = "original-model-or-context"
    e.request = {
        "scope": copy.deepcopy(e.parent.scope),
        "run_id": e.info.workflow_id,
        "execution_epoch": e.info.workflow_run_id,
        "runtime_manifest": copy.deepcopy(e.parent.manifest),
    }
    e.trace = []

    def record(identity, kind):
        if identity != e.intent["coordinator_id"]:
            e.trace.append((identity, kind))

    e.probe.before_query = record
    handle_type = type(e.client.get_workflow_handle(e.parent.run_id))
    original_describe = handle_type.describe

    async def describe(self):
        if self.identity != e.intent["coordinator_id"]:
            e.trace.append((self.identity, "describe"))
        return await original_describe(self)

    monkeypatch.setattr(handle_type, "describe", describe)
    return e


async def candidate(e):
    return await execution.validate_activity(e.runtime, e.client, e.request, e.info)


def non_session_counts(e):
    return Counter(
        {
            key: count
            for key, count in e.counts.items()
            if not (key[0] == "query" and key[1] in SESSION_QUERIES)
            and key != ("describe", e.intent["coordinator_id"])
        }
    )


@pytest.mark.parametrize("activity_type", [MODEL, CONTEXT])
def test_actual_activity_keeps_proof_and_non_session_reads_with_one_session_group(
    monkeypatch, activity_type
):
    async def run():
        e = activity_environment(monkeypatch, TOOL)
        before = canonical([e.request, e.client.record])
        baseline = await execution.validate_activity(e.runtime, e.client, e.request, e.info)
        counts, trace = non_session_counts(e), list(e.trace)
        namespaces = e.client.events.count("namespace")
        assert e.client.events.count("history") == 3
        assert e.probe.writes == []
        e.info.activity_type = activity_type
        e.counts.clear()
        e.client.events.clear()
        e.trace.clear()
        result = await candidate(e)
        assert result == baseline
        assert non_session_counts(e) == counts
        assert e.trace == trace
        assert canonical([e.request, e.client.record]) == before
        assert e.probe.writes == []
        assert e.client.events.count("history") == 1
        assert e.client.events.count("describe") == 2
        assert e.client.events.count("namespace") == namespaces - 4
        assert e.counts[("query", "deployment_session_intent")] == 1
        assert e.counts[("query", "deployment_session_command")] == 1

    asyncio.run(run())


def helper():
    from ralf_agent.temporal_session_activity_reads import read_activity

    return read_activity


@pytest.mark.parametrize("activity_type", [TOOL, "ralf.temporal.control.v1", None, "missing-type"])
def test_other_actual_activity_types_keep_the_original_full_path(monkeypatch, activity_type):
    async def run():
        e = activity_environment(monkeypatch, activity_type)
        if activity_type == "missing-type":
            del e.info.activity_type
        assert await helper()(e.runtime, e.client, e.registry.policy, e.request, e.info) is None
        proof = await execution.validate_activity(e.runtime, e.client, e.request, e.info)
        assert proof["run_id"] == e.call["run_id"]
        assert e.client.events.count("history") == 3
        assert e.probe.writes == []

    asyncio.run(run())


def test_missing_original_parent_epoch_pin_returns_no_proposal_and_never_writes(monkeypatch):
    async def run():
        e = activity_environment(monkeypatch)
        e.call["deployment_execution_epoch"] = None
        result = await helper()(e.runtime, e.client, e.registry.policy, e.request, e.info)
        assert result is None
        assert e.probe.writes == []
        assert e.client.events.count("history") == 0

    asyncio.run(run())


@pytest.mark.parametrize("replacement", ["replaced-original-child", None])
def test_second_parent_refresh_cannot_replace_the_original_child_epoch(monkeypatch, replacement):
    from ralf_agent.errors import DefinitionMismatch
    from ralf_agent.types import digest

    async def run():
        e = activity_environment(monkeypatch)
        changed = []

        def change(identity, kind, result):
            if (
                identity == e.parent.run_id
                and kind == "deployment_admission"
                and e.client.reads[(identity, kind)] == 2
            ):
                changed.append(True)
                next(c for c in result["children"] if c["run_id"] == e.call["run_id"])[
                    "deployment_execution_epoch"
                ] = replacement
                result["proof_digest"] = digest(
                    {k: v for k, v in result.items() if k != "proof_digest"}
                )

        e.client.hook = change
        with pytest.raises(DefinitionMismatch):
            await candidate(e)
        assert changed and e.probe.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("field", ["epoch", "namespace_uuid", "runtime"])
def test_original_session_or_runtime_drift_during_group_cannot_return_proof(monkeypatch, field):
    from ralf_agent.errors import DefinitionMismatch

    async def run():
        e = activity_environment(monkeypatch)
        changed = []

        def change(identity, kind):
            if kind == "deployment_admission" and e.counts[("query", kind)] == 3:
                changed.append(True)
                if field == "runtime":
                    e.runtime.manifest["providers"]["default"]["version"] = "foreign"
                else:
                    setattr(e.client, field, "22222222-2222-4222-8222-222222222222")

        e.probe.before_query = change
        with pytest.raises(DefinitionMismatch):
            await candidate(e)
        assert changed and e.probe.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("source", ["node", "session-check"])
def test_original_reader_methods_cannot_change_after_sdk_await(monkeypatch, source):
    from ralf_agent import temporal_session_deployment_verification as verification
    from ralf_agent.errors import DefinitionMismatch

    async def run():
        e = activity_environment(monkeypatch)
        changed = []

        def foreign(*args, **kwargs):
            raise AssertionError("A changed reader must not supply authority")

        def change(identity, kind):
            if kind == "deployment_start" and not changed:
                changed.append(True)
                if source == "node":
                    monkeypatch.setattr(verification, "_read_session_node", foreign)
                else:
                    monkeypatch.setattr(verification.SessionControlValidation, "_check", foreign)

        e.probe.before_query = change
        with pytest.raises(DefinitionMismatch):
            await candidate(e)
        assert changed and e.probe.writes == []

    asyncio.run(run())


def test_cancelled_original_reads_return_no_proof_and_retry_fresh(monkeypatch):
    async def run():
        e = activity_environment(monkeypatch)
        cancelled = []

        def cancel(identity, kind):
            if kind == "deployment_admission" and e.counts[("query", kind)] == 3:
                cancelled.append(True)
                asyncio.current_task().cancel()

        e.probe.before_query = cancel
        with pytest.raises(asyncio.CancelledError):
            await candidate(e)
        assert cancelled and e.probe.writes == []
        e.probe.before_query = None
        e.counts.clear()
        e.client.events.clear()
        result = await candidate(e)
        assert result["run_id"] == e.call["run_id"]
        assert e.client.events.count("history") == 1
        assert e.probe.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("foreign_scope", [False, True])
def test_original_activity_carrier_keeps_scope_admission_before_reading(monkeypatch, foreign_scope):
    from ralf_agent.errors import DefinitionMismatch

    async def run():
        e = activity_environment(monkeypatch, CONTEXT)
        body = e.request
        e.request = {
            "scope": {**e.parent.scope, "workspace": "foreign"}
            if foreign_scope
            else copy.deepcopy(e.parent.scope),
            "_deployment_activity_request": body,
        }
        if foreign_scope:
            with pytest.raises(DefinitionMismatch):
                await candidate(e)
            assert e.counts == Counter() and e.probe.writes == []
        else:
            proof = await candidate(e)
            assert proof["run_id"] == e.call["run_id"]
            assert e.client.events.count("history") == 1 and e.probe.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("source", ["session-class", "session-validate", "intent-validator"])
def test_final_independent_verifier_cannot_accept_a_changed_baseline(monkeypatch, source):
    from ralf_agent import temporal_session_deployment_verification as verification
    from ralf_agent.errors import DefinitionMismatch

    async def run():
        e = activity_environment(monkeypatch)
        changed = []
        original_class = verification.SessionControlValidation

        def foreign(*args, **kwargs):
            raise AssertionError("Changed verifier must not become a fresh baseline")

        def change(identity, kind):
            if kind == "deployment_admission" and e.counts[("query", kind)] == 2:
                changed.append(True)
                if source == "session-class":

                    class ForeignSession(original_class):
                        pass

                    monkeypatch.setattr(verification, "SessionControlValidation", ForeignSession)
                elif source == "session-validate":
                    monkeypatch.setattr(original_class, "validate", foreign)
                else:
                    monkeypatch.setattr(verification, "validate_intent", foreign)

        e.probe.before_query = change
        with pytest.raises(DefinitionMismatch):
            await candidate(e)
        assert changed and e.client.events.count("history") == 0
        assert e.probe.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("port", ["service", "converter", "handle", "activity"])
def test_original_sdk_ports_and_actual_activity_claim_remain_pinned(monkeypatch, port):
    from temporalio import activity

    from ralf_agent.errors import DefinitionMismatch

    async def run():
        e = activity_environment(monkeypatch)
        live = [e.info]
        monkeypatch.setattr(activity, "info", lambda: live[0])
        changed = []

        async def foreign(*args, **kwargs):
            raise AssertionError("Changed SDK port must not supply evidence")

        def change(identity, kind):
            if kind == "deployment_start" and not changed:
                changed.append(True)
                if port == "service":
                    e.client.workflow_service = copy.copy(e.client.workflow_service)
                elif port == "converter":
                    e.client.data_converter = copy.copy(e.client.data_converter)
                elif port == "handle":
                    cls = type(e.client.get_workflow_handle(e.parent.run_id))
                    monkeypatch.setattr(cls, "query", foreign)
                else:
                    live[0] = copy.copy(e.info)
                    live[0].attempt += 1

        e.probe.before_query = change
        with pytest.raises(DefinitionMismatch):
            await candidate(e)
        assert changed and e.probe.writes == []

    asyncio.run(run())


def test_separate_successful_activity_reads_repeat_the_original_raw_fact_set(monkeypatch):
    async def run():
        e = activity_environment(monkeypatch)
        first = await candidate(e)
        first_counts = non_session_counts(e)
        first_trace = list(e.trace)
        e.counts.clear()
        e.trace.clear()
        e.client.events.clear()
        second = await candidate(e)
        assert second == first and second is not first
        assert non_session_counts(e) == first_counts and e.trace == first_trace
        assert e.client.events.count("history") == 1
        assert e.counts[("query", "deployment_session_intent")] == 1
        assert e.counts[("query", "deployment_session_command")] == 1
        assert e.client.events.count("describe") == 2
        assert e.probe.writes == []
        second["request"]["input"] = "detached mutation"
        assert second != first

    asyncio.run(run())


@pytest.mark.parametrize("release_kind", ["ordinary-four", "coding-three"])
def test_other_original_public_releases_do_not_select_the_private_reader(monkeypatch, release_kind):
    from ralf_agent.errors import DefinitionMismatch
    from tests.test_temporal_deployment_coding_registry import coding_request
    from tests.test_temporal_deployment_session_registry import deployment_intent

    async def run():
        e = activity_environment(monkeypatch)
        manifest = (
            deployment_intent()["submission"]["manifest"]
            if release_kind == "ordinary-four"
            else coding_request()["root_admission"]["submission"]["manifest"]
        )
        e.request["runtime_manifest"] = manifest
        assert await helper()(e.runtime, e.client, e.registry.policy, e.request, e.info) is None
        # The public entry keeps its original Worker release check. An
        # ineligible request cannot substitute this genuinely different release.
        with pytest.raises(DefinitionMismatch):
            await candidate(e)
        assert not e.counts and e.probe.writes == []

    asyncio.run(run())


def test_original_default_public_entry_keeps_its_complete_proof():
    from tests.test_temporal_deployment_execution import admitted_setup

    async def run():
        runtime, client, request, info = await admitted_setup()
        info.activity_type = MODEL
        policy = execution._policy(runtime)
        assert await helper()(runtime, client, policy, request, info) is None
        result = await execution.validate_activity(runtime, client, request, info)
        assert result == client.proofs[request["run_id"]]

    asyncio.run(run())


@pytest.mark.parametrize("port", ["handle", "namespace", "service"])
def test_readonly_instance_ports_cannot_be_replaced_after_original_sdk_read(monkeypatch, port):
    from ralf_agent import temporal_session_activity_reads as reading
    from ralf_agent.errors import DefinitionMismatch

    async def run():
        e = activity_environment(monkeypatch)
        instances, changed = [], []
        original_init = reading._ActivityReading.__init__

        def capture(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            instances.append(self)

        # Install before the entry captures its fixed implementation inventory.
        monkeypatch.setattr(reading._ActivityReading, "__init__", capture)

        def change(identity, kind):
            if kind == "deployment_admission" and not changed:
                changed.append(True)
                readonly = instances[0].readonly
                if port == "handle":
                    readonly.get_workflow_handle = lambda *a, **kw: e.client.get_workflow_handle(
                        *a, **kw
                    )
                elif port == "namespace":
                    readonly._service.describe_namespace = (
                        e.client.workflow_service.describe_namespace
                    )
                else:
                    readonly._service = copy.copy(readonly._service)

        e.probe.before_query = change
        with pytest.raises(DefinitionMismatch):
            await candidate(e)
        assert len(instances) == 1 and changed
        assert e.probe.writes == []

    asyncio.run(run())
