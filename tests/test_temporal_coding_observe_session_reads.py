"""One closed CONTROL group retains the original non-Session reads and two raw exits."""

import asyncio
from collections import Counter

import pytest

from ralf_agent import temporal_coding_composition_state as composition
from ralf_agent import temporal_deployment_coding_validation as validation
from ralf_agent import temporal_deployment_control_transport as transport
from ralf_agent import temporal_deployment_execution as execution
from ralf_agent import temporal_session_deployment_verification as verification
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_coding_runtime import callbacks
from ralf_agent.temporal_deployment_coding_bridge import _ReadOnlyClient
from ralf_agent.types import digest
from tests.test_temporal_coding_observe_validation import environment

SESSION_QUERIES = {"deployment_session_intent", "deployment_session_command"}
NON_SESSION_QUERIES = Counter(
    deployment_admission=4,
    deployment_session_root=4,
    deployment_start=4,
    coding_composition_proof=3,
    deployment_configuration=1,
    deployment_coding_validation=4,
    coding_composition_children=1,
    diagnostics=1,
)


def test_closed_control_preserves_real_result_and_reads_with_two_raw_session_groups(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        result = await transport.execute(
            e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
        )
        child = e.client.states[e.call["run_id"]]
        original = {
            **child.diagnostics(),
            "scope": e.parent.scope,
            "coding_composition_proof": composition.physical_stop_view(child),
        }
        assert result == transport.pack_response(e.parent, e.call, original)
        assert (
            Counter(
                {
                    key[1]: value
                    for key, value in e.counts.items()
                    if key[0] == "query" and key[1] not in SESSION_QUERIES
                }
            )
            == NON_SESSION_QUERIES
        )
        assert e.probe.writes == []
        # The entry and the independent raw exit retain all original facts;
        # intermediate readonly queries correlate the fixed original identity.
        assert e.client.events.count("history") == 2
        assert e.counts[("query", "deployment_session_intent")] == 2
        assert e.counts[("query", "deployment_session_command")] == 2

    asyncio.run(run())


def watch_packing(monkeypatch):
    packed = []
    original = transport.pack_response

    def pack(*args):
        packed.append(True)
        return original(*args)

    monkeypatch.setattr(transport, "pack_response", pack)
    return packed


@pytest.mark.parametrize("field", ["intent", "session_origin"])
@pytest.mark.parametrize("read", [2, 4])
def test_every_middle_registry_identity_still_matches_original_session(monkeypatch, field, read):
    async def run():
        e = environment(monkeypatch)
        packed = watch_packing(monkeypatch)
        original = e.registry.deployment_session_root

        def reply(query):
            # First run the actual Registry selector/record validator. Alter
            # only its detached SDK response, not the original Registry state.
            result = original(query)
            if e.counts[("query", "deployment_session_root")] == read:
                result[field]["intent_digest"] = "f" * 64
            return result

        monkeypatch.setattr(e.registry, "deployment_session_root", reply)
        with pytest.raises(DefinitionMismatch):
            await transport.execute(
                e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
            )
        assert e.counts[("query", "deployment_session_root")] == read
        assert packed == e.probe.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("field", ["epoch", "first_epoch", "original_epoch", "namespace_uuid"])
def test_final_original_session_facts_refuse_drift_after_body(monkeypatch, field):
    async def run():
        e = environment(monkeypatch)
        packed = watch_packing(monkeypatch)
        changed = []

        def change(identity, kind):
            if kind == "deployment_coding_validation" and e.counts[("query", kind)] == 4:
                changed.append(True)
                setattr(e.client, field, "22222222-2222-4222-8222-222222222222")

        e.probe.before_query = change
        with pytest.raises(DefinitionMismatch):
            await transport.execute(
                e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
            )
        assert changed and e.counts[("query", "diagnostics")] == 1
        assert packed == e.probe.writes == []

    asyncio.run(run())


@pytest.mark.parametrize(
    "port", ["_start_record", "validate_session_origin", "session-class", "session-validate"]
)
def test_group_helper_source_cannot_change_during_original_reads(monkeypatch, port):
    async def run():
        e = environment(monkeypatch)
        packed = watch_packing(monkeypatch)
        changed = []

        async def foreign(*args, **kwargs):
            raise AssertionError("Changed verification must not supply evidence")

        def change(identity, kind):
            if kind == "deployment_coding_validation" and not changed:
                changed.append(True)
                if port == "session-class":

                    class ForeignSession(verification.SessionControlValidation):
                        pass

                    monkeypatch.setattr(verification, "SessionControlValidation", ForeignSession)
                elif port == "session-validate":
                    monkeypatch.setattr(verification.SessionControlValidation, "validate", foreign)
                else:
                    monkeypatch.setattr(
                        verification if port == "validate_session_origin" else execution,
                        port,
                        foreign,
                    )

        e.probe.before_query = change
        with pytest.raises(DefinitionMismatch):
            await transport.execute(
                e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
            )
        assert changed and packed == e.probe.writes == []

    asyncio.run(run())


def test_fake_outer_validate_cannot_replace_final_original_session_sdk_check(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        packed = watch_packing(monkeypatch)
        outer_calls, changed = [], []

        async def outer(self):
            # Deliberately remove the outer validator in this negative test.
            # It supplies no proof and is never used as positive evidence.
            outer_calls.append(True)

        monkeypatch.setattr(validation._ObservationValidation, "validate", outer)

        def change(identity, kind):
            if kind == "diagnostics":
                changed.append(True)
                e.client.epoch = "reset-original-session"

        e.probe.before_query = change
        with pytest.raises(DefinitionMismatch):
            await transport.execute(
                e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
            )
        assert outer_calls and changed and e.counts[("query", "diagnostics")] == 1
        # The entry and independent exit have both queried the actual original
        # coordinator, despite every outer validate() completing with None.
        assert e.counts[("query", "deployment_session_intent")] == 2
        assert e.counts[("query", "deployment_session_command")] == 2
        assert packed == e.probe.writes == []

    asyncio.run(run())


def test_cancelled_group_clears_snapshot_and_never_packs(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        packed = watch_packing(monkeypatch)
        instances, cancelled = [], []
        original = validation._ObservationValidation._open_reading

        def opened(self, proof):
            result = original(self, proof)
            instances.append(self)
            return result

        monkeypatch.setattr(validation._ObservationValidation, "_open_reading", opened)

        def cancel(identity, kind):
            if kind == "diagnostics" and not cancelled:
                cancelled.append(True)
                asyncio.current_task().cancel()

        e.probe.before_query = cancel
        with pytest.raises(asyncio.CancelledError):
            await transport.execute(
                e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
            )
        assert cancelled and len(instances) == 1
        assert instances[0]._snapshot is None and instances[0]._snapshot_digest is None
        assert packed == e.probe.writes == []

    asyncio.run(run())


def test_real_business_ancestor_requires_original_pin_and_cannot_write_it(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        readonly = _ReadOnlyClient(e.client)
        child = await execution._proof(
            e.runtime,
            readonly,
            e.registry.policy,
            e.parent.scope,
            e.call["run_id"],
            e.call["deployment_execution_epoch"],
            required=True,
        )
        # This fixture's CONTROL addresses the Session root itself. Exercise
        # the genuine child's business-ancestor reader, without adding a new
        # nested topology or substituting any proof/ancestry result.
        e.call["deployment_execution_epoch"] = None
        with pytest.raises(DefinitionMismatch):
            await execution._ancestry(e.runtime, readonly, e.registry.policy, child, read_only=True)
        assert e.probe.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("activity_type", [None, "ralf.temporal.tool.v1"])
def test_non_control_original_observation_retains_six_session_groups(monkeypatch, activity_type):
    async def run():
        e = environment(monkeypatch)
        if activity_type is None:
            del e.info.activity_type
        else:
            e.info.activity_type = activity_type
        result = await transport.execute(
            e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
        )
        assert result["version"] == 1
        assert e.client.events.count("history") == 6
        assert e.counts[("query", "deployment_session_intent")] == 6
        assert e.counts[("query", "deployment_session_command")] == 6
        assert e.probe.writes == []

    asyncio.run(run())


def test_native_callback_keeps_independent_original_session_checks(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        request = {
            "scope": e.parent.scope,
            "run_id": e.parent.run_id,
            "execution_epoch": e.parent.epoch,
            "runtime_manifest": e.parent.manifest,
            "action_id": "original-native-action",
            "release_digest": digest(e.parent.manifest),
        }
        native = {"release_digest": request["release_digest"]}
        native["request_digest"] = digest(native)
        request["coding_request"] = native
        authority = await callbacks(e.client, request, e.info, e.runtime)(
            "original", None, recovery=True
        )
        await authority.validate_registration()
        e.client.events.clear()
        e.full.clear()
        await authority.validate_registration()
        assert e.client.events.count("history") == 1
        assert e.client.events.count("deployment_session_intent") == 1
        assert e.client.events.count("deployment_session_command") == 1
        assert e.full["runtime"] == 2 and e.probe.writes == []

    asyncio.run(run())
