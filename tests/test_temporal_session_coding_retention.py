"""Registry4 fixture deletion needs original Session History, not quiet guesses."""

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from relf_agent.temporal_session_state import TemporalSessionState
from relf_agent.types import canonical, digest
from tests.test_temporal_deployment_coding_retention import description, started, update
from tests.test_temporal_deployment_session_registry import (
    NAMESPACE,
    POLICY,
    SCOPE,
    state,
    verified,
)
from tests.test_temporal_session_deployment_coding_registry import coding_intent_request
from tests.test_temporal_session_deployment_dto import call, start
from tests.test_temporal_session_deployment_state import advance

pytest.importorskip("temporalio")
from temporalio.api.history.v1 import HistoryEvent
from temporalio.client import WorkflowHistory
from temporalio.converter import DataConverter


async def scenario(*, fault=None, encoded=False):
    from tests.temporal_deployment_coding_retention import deletion_evidence

    registry = state()
    if encoded:
        from relf_agent.temporal_deployment_protocol import validate_protocol
        from tests import test_temporal_session_deployment_coding_registry as fixture

        original_manifest = fixture.coding_session_manifest

        def large_manifest(**options):
            manifest = original_manifest(**options)
            # A real ToolSpec description grows the accepted release, rather
            # than adding a field the original publication would reject.
            manifest["tools"]["plain"]["description"] = (
                "Original accepted tool description. " * 8192
            )
            validate_protocol(manifest)
            assert len(canonical(manifest).encode()) < 1024 * 1024
            return manifest

        with patch.object(fixture, "coding_session_manifest", large_manifest):
            intent, request = coding_intent_request(registry)
    else:
        intent, request = coding_intent_request(registry)
    binding = intent["binding"]
    initial = {
        "scope": SCOPE,
        "namespace_id": NAMESPACE["id"],
        "session_namespace": None,
        "session_id": "chat",
        "command_id": "open",
        **binding,
    }
    session = TemporalSessionState(
        initial,
        deployment_context={
            "namespace": NAMESPACE,
            "coordinator_execution_epoch": intent["coordinator_execution_epoch"],
        },
    )
    payload = {
        "kind": "submit",
        "scope": SCOPE,
        "command_id": intent["session_command_id"],
        "session_ref": intent["session_ref"],
        "input": intent["submission"]["request"]["input"],
        "budget": intent["submission"]["request"]["budget"],
    }
    receipt = session.command(payload)
    registry.session_commands[digest([SCOPE, intent["session_command_id"]])]["session_receipt"] = (
        copy.deepcopy(receipt)
    )
    assert session.deployment_turn().intent == intent
    reservation = registry.commit_session_root(request, intent, verified(intent, request))
    retirement = advance(SimpleNamespace(intent=intent))["retirement"]
    certificate = retirement["certificate"]
    coordinator = intent["coordinator_id"]
    session_events = [await started(coordinator, intent["coordinator_execution_epoch"], initial)]
    session_events[0].workflow_execution_started_event_attributes.task_queue.name = binding[
        "task_queue"
    ]
    await update(session_events, "command", payload, receipt)

    async def control(mode, phase=None):
        entry = session.deployment_turn()
        identity = call(intent)
        identity.update(
            mode=mode,
            activity_id=str(len(session_events)),
            request_digest=digest(entry.control_request(mode)),
        )
        schedule = HistoryEvent(event_id=len(session_events) + 1)
        attrs = schedule.activity_task_scheduled_event_attributes
        attrs.activity_id, attrs.activity_type.name = (
            identity["activity_id"],
            identity["activity_name"],
        )
        attrs.input.payloads.extend(
            await DataConverter.default.encode([entry.control_request(mode)])
        )
        session_events.append(schedule)
        begun = entry.begin_call(identity)
        await update(session_events, "session_deployment_call_start", {"identity": identity}, begun)
        body = {
            "ok": True,
            "result": {
                "registry_execution_epoch": "registry-original",
                "execution_epoch": "original-business-epoch"
                if mode == "observe" or phase == "started"
                else None,
            },
        }
        if mode == "register":
            body["result"]["start"] = start(intent, phase)
        else:
            body["result"]["advance"] = advance(SimpleNamespace(intent=intent))
        end = {
            "identity": identity,
            "body_result_digest": digest(body),
            "body_stopped": True,
            "body_result": body,
        }
        if encoded:
            from relf_agent.temporal_session_deployment_dto import encode_control_body

            end["body_result"] = encode_control_body(body, binding["manifest"])
            assert "_ralf_session_control_body" in end["body_result"]
        ack = entry.end_call(end)
        if fault == "bad_digest" and mode == "observe":
            end["body_result_digest"] = "0" * 64
        if fault != "missing_end" or mode != "observe":
            await update(session_events, "session_deployment_call_end", end, ack)
        session.recover_deployment_result()
        return body

    await control("register", "held-unbound")
    child = HistoryEvent(event_id=len(session_events) + 1)
    attrs = child.start_child_workflow_execution_initiated_event_attributes
    attrs.workflow_id, attrs.task_queue.name = intent["run_id"], binding["task_queue"]
    attrs.input.payloads.extend(
        await DataConverter.default.encode(
            [
                {
                    "scope": SCOPE,
                    "command_id": intent["run_command_id"],
                    "request": intent["submission"]["request"],
                    "manifest": binding["manifest"],
                    "activity_timeout": binding["activity_timeout"],
                    "deployment_admission": {
                        "version": 2,
                        "root": reservation["root_admission"],
                        "lineage": [],
                        "session_origin": request["root_admission"]["session_origin"],
                    },
                }
            ]
        )
    )
    session_events.append(child)
    assert session.deployment_turn().issue_start()
    await control("register", "started")
    await control("observe")
    assert not session.snapshot()["busy"]
    root_events = [
        await started(
            intent["run_id"],
            "original-business-epoch",
            {
                "scope": SCOPE,
                "command_id": intent["run_command_id"],
                "request": intent["submission"]["request"],
                "manifest": binding["manifest"],
                "activity_timeout": binding["activity_timeout"],
                "deployment_admission": {
                    "version": 2,
                    "root": reservation["root_admission"],
                    "lineage": [],
                    "session_origin": request["root_admission"]["session_origin"],
                },
            },
        )
    ]
    root_start = root_events[0].workflow_execution_started_event_attributes
    root_start.task_queue.name = binding["task_queue"]
    root_start.parent_workflow_namespace = NAMESPACE["name"]
    root_start.parent_workflow_execution.workflow_id = coordinator
    root_start.parent_workflow_execution.run_id = intent["coordinator_execution_epoch"]
    registry_events = [
        await started(
            registry.registry_id,
            "registry-original",
            {
                "deployment_admission": {
                    "version": 4,
                    "policy": POLICY.identity,
                    "namespace": NAMESPACE,
                }
            },
        )
    ]
    await update(
        registry_events, "reserve_session_root", {"request": request, "intent": intent}, reservation
    )
    release = {
        **{
            key: retirement["root"][key]
            for key in (
                "scope",
                "command_id",
                "run_id",
                "request_digest",
                "manifest_digest",
                "proof_digest",
                "execution_epoch",
                "namespace",
            )
        },
        "admission_policy": POLICY.identity,
        "certificate": certificate,
    }
    if fault != "unretired":
        await update(registry_events, "release_deployment_root", release, retirement)
    scoped_close = {
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        "manifest_digest": digest(binding["manifest"]),
    }
    await update(
        registry_events,
        "close_deployment_coding_submissions",
        scoped_close,
        {
            "manifest_digest": scoped_close["manifest_digest"],
            "close_requested": True,
            "candidates": [],
        },
    )
    if fault != "missing_session_close":
        await update(
            registry_events,
            "close_deployment_sessions",
            scoped_close,
            {
                "manifest_digest": scoped_close["manifest_digest"],
                "close_requested": True,
                "candidates": [
                    copy.deepcopy(
                        registry.session_commands[digest([SCOPE, intent["session_command_id"]])]
                    )
                ],
            },
        )
    if fault == "unknown_child":
        extra = copy.deepcopy(child)
        extra.event_id = len(session_events) + 1
        extra.start_child_workflow_execution_initiated_event_attributes.workflow_id = (
            "unproven-child"
        )
        session_events.append(extra)
    if fault == "queue":
        session_events[
            0
        ].workflow_execution_started_event_attributes.task_queue.name = "other-queue"

    class Client:
        namespace = NAMESPACE["name"]
        data_converter = DataConverter.default
        workflow_service = SimpleNamespace()

        async def describe_namespace(self, request):
            return SimpleNamespace(namespace_info=SimpleNamespace(id=NAMESPACE["id"]))

        def get_workflow_handle(self, identity, *, run_id=None):
            require_epoch = (
                intent["coordinator_execution_epoch"]
                if identity == coordinator
                else "original-business-epoch"
            )
            assert identity in {coordinator, intent["run_id"]}
            if run_id is not None:
                assert run_id == require_epoch

            class Handle:
                async def describe(self, **options):
                    value = description(identity, require_epoch)
                    value.workflow_type = (
                        "ralf.temporal.sessions.v1"
                        if identity == coordinator
                        else "ralf.temporal.run.v1"
                    )
                    value.task_queue = binding["task_queue"]
                    value.parent_id = None if identity == coordinator else coordinator
                    value.parent_run_id = (
                        None if identity == coordinator else intent["coordinator_execution_epoch"]
                    )
                    value.namespace = NAMESPACE["name"]
                    if fault == "reset" and identity == coordinator:
                        value.raw_description.workflow_execution_info.first_run_id = (
                            "reset-original"
                        )
                    return value

                async def fetch_history(self, **options):
                    return WorkflowHistory(
                        identity, session_events if identity == coordinator else root_events
                    )

            return Handle()

    connection = Client()
    connection.workflow_service.describe_namespace = connection.describe_namespace
    archive = []
    report = await deletion_evidence(
        connection,
        description(registry.registry_id, "registry-original"),
        WorkflowHistory(registry.registry_id, registry_events),
        policy=POLICY.identity,
        namespace=NAMESPACE,
        scope=SCOPE,
        manifest_digest=digest(binding["manifest"]),
        targets={coordinator, intent["run_id"]},
        effects=[{"effect": "write", "state": "adopted"}],
        archive=lambda identity, history: archive.append(identity),
    )
    return report, intent, archive


def test_session_four_positive_original_history_allows_fixture_deletion():
    report, intent, archived = asyncio.run(scenario())
    assert report["deletion_allowed"], report
    assert len(report["accepted_roots"]) == 1
    assert intent["coordinator_id"] in archived and intent["run_id"] in archived


def test_encoded_session_body_original_history_allows_fixture_deletion():
    report, intent, archived = asyncio.run(scenario(encoded=True))
    assert report["deletion_allowed"], {
        key: report.get(key) for key in ("reasons", "session_evidence_exception_type")
    }
    assert len(report["retired_roots"]) == 1
    assert intent["coordinator_id"] in archived and intent["run_id"] in archived


@pytest.mark.parametrize("fault", ["missing_end", "unretired", "bad_digest"])
def test_encoded_session_body_missing_original_evidence_still_retains(fault):
    report, _, _ = asyncio.run(scenario(encoded=True, fault=fault))
    assert not report["deletion_allowed"]
    assert (
        "root_retirement_unconfirmed" if fault == "unretired" else "session_evidence_invalid"
    ) in report["reasons"]


@pytest.mark.parametrize(
    "fault",
    ["missing_end", "reset", "unretired", "missing_session_close", "unknown_child", "queue"],
)
def test_session_four_missing_original_debt_or_identity_proof_retains(fault):
    report, _, _ = asyncio.run(scenario(fault=fault))
    assert not report["deletion_allowed"]
