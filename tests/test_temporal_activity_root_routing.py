"""Original Activity root routing retains fresh ancestry and Registry admission."""

import asyncio
import copy
from collections import Counter

import pytest
from temporalio import activity

from relf_agent import temporal_coding_composition_control as composition
from relf_agent import temporal_deployment_execution as execution
from relf_agent import temporal_deployment_release as release
from relf_agent.errors import DefinitionMismatch
from relf_agent.types import canonical, digest
from tests.test_temporal_session_activity_reads import CONTEXT, MODEL, TOOL, activity_environment


async def ready(monkeypatch, activity_type=MODEL):
    e = activity_environment(monkeypatch, activity_type)
    monkeypatch.setattr(activity, "info", lambda: e.info)
    e.proof = await execution._proof(
        e.runtime,
        e.client,
        e.registry.policy,
        e.request["scope"],
        e.info.workflow_id,
        e.info.workflow_run_id,
        required=True,
    )
    e.counts.clear()
    e.client.events.clear()
    e.trace.clear()
    return e


async def validate(e):
    return await composition.validate_activity(e.client, e.request, workflow_id=e.info.workflow_id)


@pytest.mark.parametrize("wrapped_carrier", [False, True])
@pytest.mark.parametrize("activity_type", [MODEL, CONTEXT])
def test_original_activity_routes_to_exact_admission_without_candidate_scan(
    monkeypatch, activity_type, wrapped_carrier
):
    async def run():
        e = await ready(monkeypatch, activity_type)
        before = canonical([e.request, e.client.record])
        assert await validate(e) is None
        baseline = list(e.trace)
        assert e.counts[("query", "coding_composition_candidates")] == 1
        assert e.counts[("query", "deployment_configuration")] == 2
        assert e.counts[("describe", e.registry.registry_id)] == 2
        namespaces = e.client.events.count("namespace")
        e.counts.clear()
        e.client.events.clear()
        e.trace.clear()
        carrier = (
            {"scope": copy.deepcopy(e.request["scope"]), "_deployment_activity_request": e.request}
            if wrapped_carrier
            else e.request
        )
        with release.activity_context(e.runtime, e.client, e.proof, carrier):
            assert await validate(e) is None
        assert [r for r in e.trace if r[0] != e.registry.registry_id] == [
            r for r in baseline if r[0] != e.registry.registry_id
        ]
        assert canonical([e.request, e.client.record]) == before
        assert e.probe.writes == []
        assert e.counts[("query", "coding_composition_candidates")] == 0
        assert e.counts[("query", "coding_composition_admission")] == 1
        assert e.counts[("query", "deployment_configuration")] == 1
        assert e.counts[("describe", e.registry.registry_id)] == 1
        assert e.client.events.count("namespace") == namespaces - 4
        assert Counter({k[1]: v for k, v in e.counts.items() if k[0] == "query"}) == Counter(
            coding_composition_proof=2,
            coding_composition_children=1,
            coding_composition_admission=1,
            deployment_configuration=1,
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["receipt", "command", "foreign-command", "raw-client", "carrier", "run"]
)
def test_missing_or_unmatched_original_context_falls_back_to_fresh_scan(monkeypatch, fault):
    async def run():
        e = await ready(monkeypatch)
        proof, client, carrier = copy.deepcopy(e.proof), e.client, copy.deepcopy(e.request)
        if fault == "receipt":
            proof["admission_receipt"] = None
        elif fault == "command":
            proof["admission_receipt"]["root"].pop("command_id")
        elif fault == "foreign-command":
            proof["admission_receipt"]["root"]["command_id"] = "foreign-original-command"
        elif fault == "raw-client":
            client = copy.copy(e.client)
        elif fault == "carrier":
            carrier["run_id"] = "foreign-original-run"
        else:
            proof["run_id"] = "foreign-original-run"
        with release.activity_context(e.runtime, client, proof, carrier):
            assert await validate(e) is None
        assert e.counts[("query", "coding_composition_candidates")] == 1
        assert e.counts[("query", "coding_composition_admission")] == 1
        assert e.counts[("query", "deployment_configuration")] == 2
        assert e.probe.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("activity_type", [TOOL, "ralf.temporal.control.v1", "missing-type"])
def test_other_actual_activities_keep_the_original_scan(monkeypatch, activity_type):
    async def run():
        e = await ready(monkeypatch, activity_type)
        if activity_type == "missing-type":
            del e.info.activity_type
        with release.activity_context(e.runtime, e.client, e.proof, e.request):
            assert await validate(e) is None
        assert e.counts[("query", "coding_composition_candidates")] == 1
        assert e.counts[("query", "deployment_configuration")] == 2
        assert e.probe.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("field", ["execution_epoch", "namespace"])
def test_routed_admission_response_still_matches_original_epoch_and_namespace(monkeypatch, field):
    async def run():
        e = await ready(monkeypatch)
        original = e.registry.coding_admission

        def reply(query):
            result = original(query)
            result[field] = (
                "foreign-epoch"
                if field == "execution_epoch"
                else {"name": "foreign", "id": "foreign"}
            )
            return result

        monkeypatch.setattr(e.registry, "coding_admission", reply)
        with release.activity_context(e.runtime, e.client, e.proof, e.request):
            with pytest.raises(DefinitionMismatch):
                await validate(e)
        assert e.counts[("query", "coding_composition_admission")] == 1
        assert e.counts[("query", "coding_composition_candidates")] == 0
        assert e.probe.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["namespace", "parent-epoch"])
def test_original_sdk_namespace_and_fresh_parent_epoch_are_not_routing_hints(monkeypatch, fault):
    async def run():
        e = await ready(monkeypatch)
        changed = []
        record = e.probe.before_query

        def change(identity, kind):
            record(identity, kind)
            if kind == "coding_composition_proof" and identity == e.parent.run_id and not changed:
                changed.append(True)
                if fault == "namespace":
                    e.client.namespace_uuid = "22222222-2222-4222-8222-222222222222"
                else:
                    e.parent.epoch = "foreign-parent-epoch"

        e.probe.before_query = change
        with release.activity_context(e.runtime, e.client, e.proof, e.request):
            with pytest.raises(DefinitionMismatch):
                await validate(e)
        assert changed and e.probe.writes == []
        assert e.counts[("query", "coding_composition_admission")] == 0

    asyncio.run(run())


def test_fresh_closed_root_admission_keeps_original_cancel_path(monkeypatch):
    async def run():
        e = await ready(monkeypatch)
        e.registry.close_coding_submissions(
            {
                "scope": e.parent.scope,
                "admission_policy": e.registry.policy,
                "namespace": e.intent["namespace"],
                "manifest_digest": digest(e.parent.manifest),
            }
        )
        cls = type(e.client.get_workflow_handle(e.call["run_id"]))
        original_query = cls.query

        async def query(self, name, value):
            if value["kind"] == "status":
                assert name == "view"
                state = e.client.states[self.identity]
                state.authorize(value["scope"])
                # This Update-only Worker returns its complete original status.
                return state.snapshot()
            return await original_query(self, name, value)

        async def signal(self, *args, **options):
            raise AssertionError("The original Update-only Worker cannot accept Signals")

        async def update(self, name, value, **options):
            e.probe.writes.append((self.identity, name, value))
            assert name == "command" and value["payload"]["kind"] == "cancel"
            # The original sealed Run rejects a fresh mutation. The route must
            # nevertheless retain the existing cancellation attempt on close.
            return e.client.states[self.identity].command(value["command_id"], value["payload"])

        monkeypatch.setattr(cls, "query", query)
        monkeypatch.setattr(cls, "signal", signal, raising=False)
        monkeypatch.setattr(cls, "execute_update", update)
        with release.activity_context(e.runtime, e.client, e.proof, e.request):
            with pytest.raises(DefinitionMismatch):
                await validate(e)
        assert e.counts[("query", "coding_composition_admission")] == 1
        assert e.counts[("query", "coding_composition_candidates")] == 0
        assert len(e.probe.writes) == 1

    asyncio.run(run())


@pytest.mark.parametrize("release_kind", ["legacy-three", "ordinary-four"])
def test_other_complete_public_releases_provide_no_private_route_hint(monkeypatch, release_kind):
    from relf_agent.temporal_coding_composition_state import physical_stop_view
    from tests.test_temporal_deployment_coding_registry import coding_request
    from tests.test_temporal_deployment_session_registry import deployment_intent

    async def run():
        e = await ready(monkeypatch)
        manifest = (
            coding_request()["root_admission"]["submission"]["manifest"]
            if release_kind == "legacy-three"
            else deployment_intent()["submission"]["manifest"]
        )
        # Full original fixtures, not invented version-only Manifest stubs.
        request = {**e.request, "runtime_manifest": manifest}
        with release.activity_context(e.runtime, e.client, e.proof, request):
            assert (
                composition._activity_root_command(
                    e.client,
                    request,
                    physical_stop_view(e.client.states[e.call["run_id"]]),
                    physical_stop_view(e.parent),
                    manifest,
                    e.intent["namespace"],
                )
                is None
            )
        assert not e.counts and e.probe.writes == []

    asyncio.run(run())


def test_context_original_request_inside_actual_deployment_carrier_routes_exact_root(monkeypatch):
    async def run():
        e = await ready(monkeypatch, CONTEXT)
        carrier = {
            "scope": copy.deepcopy(e.request["scope"]),
            "_deployment_activity_request": {
                **copy.deepcopy(e.request),
                "original_request": copy.deepcopy(e.request),
            },
        }
        before = canonical(carrier)
        with release.activity_context(e.runtime, e.client, e.proof, carrier):
            assert await validate(e) is None
        assert canonical(carrier) == before
        assert e.counts[("query", "coding_composition_candidates")] == 0
        assert e.counts[("query", "coding_composition_admission")] == 1
        assert e.counts[("query", "deployment_configuration")] == 1
        assert e.probe.writes == []

    asyncio.run(run())
