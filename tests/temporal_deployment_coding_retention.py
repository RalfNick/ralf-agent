"""Read original SDK History before deleting this test's recovery resources.

This helper cannot grant, stop, query Workflow state, release quota or mutate
journals. Missing or malformed evidence always retains the original fixture.
"""

import copy
from datetime import timedelta

from ralf_agent.temporal_deployment_admission import registry_id, root_run_id
from ralf_agent.temporal_deployment_release_state import CERTIFICATE_FIELDS
from ralf_agent.types import digest


class EvidenceMismatch(ValueError):
    pass


def require(condition):
    if not condition:
        raise EvidenceMismatch("Original fixture deletion evidence is incomplete")


async def decoded(client, payloads):
    values = await client.data_converter.decode(payloads)
    require(len(values) == 1 and type(values[0]) is dict)
    return values[0]


def original_started(description, history, identity):
    require(description.id == identity and history.workflow_id == identity and bool(history.events))
    started = history.events[0].workflow_execution_started_event_attributes
    epoch = description.run_id
    require(type(epoch) is str and bool(epoch))
    require(
        started.workflow_id == identity
        and started.first_execution_run_id == epoch
        and started.original_execution_run_id == epoch
        and description.raw_description.workflow_execution_info.first_run_id == epoch
    )
    return started, epoch


def root_identity(value):
    return {key: copy.deepcopy(value[key]) for key in ("run_id", "scope", "execution_epoch")}


async def deletion_evidence(
    client,
    description,
    history,
    *,
    policy,
    namespace,
    scope,
    manifest_digest,
    targets,
    effects,
    archive,
):
    report = {
        "deletion_allowed": False,
        "accepted_roots": [],
        "retired_roots": [],
        "retained_roots": [],
        "reasons": [],
        "registry_execution_epoch": None,
    }
    accepted, released, rejected = {}, {}, set()
    close_observed, session_close = False, False
    version, sessions = None, {}
    try:
        started, epoch = original_started(
            description, history, registry_id(policy["deployment_id"])
        )
        require(description.workflow_type == "ralf.temporal.commands.v1")
        require(client.namespace == namespace["name"])
        initialization = await decoded(client, started.input.payloads)
        version = initialization["deployment_admission"]["version"]
        require(type(version) is int and version in (3, 4))
        require(
            initialization
            == {
                "deployment_admission": {
                    "version": version,
                    "policy": policy,
                    "namespace": namespace,
                }
            }
        )
        report["registry_execution_epoch"] = epoch
        updates, completions = {}, {}
        for event in history.events:
            if event.HasField("workflow_execution_update_accepted_event_attributes"):
                updates[event.event_id] = (
                    event.workflow_execution_update_accepted_event_attributes.accepted_request
                )
            elif event.HasField("workflow_execution_update_completed_event_attributes"):
                done = event.workflow_execution_update_completed_event_attributes
                require(done.accepted_event_id not in completions)
                completions[done.accepted_event_id] = done
        for event_id, request in updates.items():
            name = request.input.name
            if name not in {
                "reserve",
                "reserve_session_root",
                "release_deployment_root",
                "close_deployment_coding_submissions",
                "close_deployment_sessions",
            }:
                continue
            value = await decoded(client, request.input.args.payloads)
            intent = None
            if name == "reserve_session_root":
                require(version == 4 and set(value) == {"request", "intent"})
                value, intent = value["request"], value["intent"]
            if name == "reserve" and value.get("kind") != "submit":
                continue
            require(value.get("admission_policy") == policy and value.get("namespace") == namespace)
            done = completions.get(event_id)
            if done is None:
                report["reasons"].append("pending_registry_update")
                continue
            require(done.meta.update_id == request.meta.update_id)
            if done.outcome.WhichOneof("value") != "success":
                if name in {"reserve", "reserve_session_root"}:
                    rejected.add(value["target"])
                continue
            result = await decoded(client, done.outcome.success.payloads)
            if name in {"reserve", "reserve_session_root"}:
                root = result["root_admission"]
                require(
                    root["version"] == 1
                    and root["registry_id"] == description.id
                    and root["namespace"] == namespace
                    and root["scope"] == value["scope"]
                    and root["command_id"] == value["command_id"]
                    and root["run_id"]
                    == value["target"]
                    == root_run_id(policy["deployment_id"], value["scope"], value["command_id"])
                    and root["request_digest"] == value["payload_digest"]
                    and root["manifest_digest"] == value["root_admission"]["manifest_digest"]
                )
                proof = {
                    k: v
                    for k, v in root.items()
                    if k not in {"proof_digest", "state", "execution_epoch"}
                }
                require(root["proof_digest"] == digest(proof))
                submission = result["submission"]
                require(
                    submission == value["root_admission"]["submission"]
                    and digest(submission["request"]) == root["request_digest"]
                    and digest(submission["manifest"]) == root["manifest_digest"]
                )
                saved = {"root": copy.deepcopy(root), "submission": copy.deepcopy(submission)}
                if intent is not None:
                    from ralf_agent.temporal_session_deployment_dto import (
                        validate_intent,
                        validate_origin,
                    )

                    validate_intent(
                        intent,
                        deployment_id=policy["deployment_id"],
                        scope=value["scope"],
                        namespace=namespace,
                        coordinator_execution_epoch=intent["coordinator_execution_epoch"],
                    )
                    origin = value["root_admission"]["session_origin"]
                    validate_origin(origin, intent=intent, deployment_id=policy["deployment_id"])
                    require(
                        intent["submission"] == submission
                        and intent["run_id"] == root["run_id"]
                        and intent["run_command_id"] == root["command_id"]
                    )
                    saved.update(intent=copy.deepcopy(intent), session_origin=copy.deepcopy(origin))
                    sessions.setdefault(intent["coordinator_id"], [])
                require(root["run_id"] not in accepted or accepted[root["run_id"]] == saved)
                accepted[root["run_id"]] = saved
            elif name == "release_deployment_root":
                require(
                    set(result) == {"root", "certificate", "released"}
                    and result["released"] is True
                )
                root, certificate = result["root"], result["certificate"]
                require(root["state"] == "held-bound" and root["execution_epoch"])
                require(
                    set(certificate) == CERTIFICATE_FIELDS
                    and certificate["proof_digest"]
                    == digest({k: v for k, v in certificate.items() if k != "proof_digest"})
                    and certificate["terminal_state"] in {"succeeded", "failed", "cancelled"}
                )
                require(value["certificate"] == certificate)
                require(
                    all(
                        value[key] == root[key]
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
                    )
                )
                require(
                    all(
                        certificate[key] == root[key]
                        for key in (
                            "scope",
                            "command_id",
                            "run_id",
                            "request_digest",
                            "manifest_digest",
                            "execution_epoch",
                            "namespace",
                        )
                    )
                )
                require(certificate["original_execution_epoch"] == root["execution_epoch"])
                require(root["run_id"] not in released or released[root["run_id"]] == result)
                released[root["run_id"]] = copy.deepcopy(result)
            else:
                if value["scope"] == scope and value["manifest_digest"] == manifest_digest:
                    require(
                        set(result) == {"manifest_digest", "close_requested", "candidates"}
                        and result["manifest_digest"] == manifest_digest
                        and result["close_requested"] is True
                        and type(result["candidates"]) is list
                    )
                    if name == "close_deployment_coding_submissions":
                        close_observed = True
                    else:
                        require(version == 4)
                        session_close = True
                        from ralf_agent.session_types import SessionKey
                        from ralf_agent.temporal_session_state import workflow_id

                        for candidate in result["candidates"]:
                            saved = candidate["session_submission"]
                            key = SessionKey.from_dict(saved["session_key"])
                            require(
                                saved["payload"]["scope"] == scope
                                and digest(saved["binding"]["manifest"]) == manifest_digest
                            )
                            identity = workflow_id(key)
                            require(candidate["reservation"]["target"] == identity)
                            sessions.setdefault(identity, []).append(candidate)
    except Exception as error:
        report["reasons"].append("registry_evidence_invalid")
        report["evidence_exception_type"] = type(error).__name__
    if not close_observed:
        report["reasons"].append("scoped_close_unconfirmed")
    if targets - set(accepted) - rejected - set(sessions):
        report["reasons"].append("target_acceptance_unresolved")
    if version == 4 and not session_close:
        report["reasons"].append("scoped_session_close_unconfirmed")
    for identity, saved in accepted.items():
        root, submission = saved["root"], saved["submission"]
        record = {
            "run_id": identity,
            "scope": copy.deepcopy(root["scope"]),
            "execution_epoch": None,
        }
        retired = False
        try:
            handle = client.get_workflow_handle(identity)
            info = await handle.describe(rpc_timeout=timedelta(seconds=15))
            pinned = client.get_workflow_handle(identity, run_id=info.run_id)
            root_history = await pinned.fetch_history(rpc_timeout=timedelta(seconds=15))
            archive(identity, root_history)
            started, epoch = original_started(info, root_history, identity)
            record["execution_epoch"] = epoch
            payload = await decoded(client, started.input.payloads)
            require(
                payload["scope"] == root["scope"]
                and payload["command_id"] == root["command_id"]
                and payload["request"] == submission["request"]
                and payload["manifest"] == submission["manifest"]
            )
            if "intent" in saved:
                origin = saved["session_origin"]
                require(
                    payload["activity_timeout"] == submission["activity_timeout"]
                    and info.task_queue == started.task_queue.name == submission["task_queue"]
                )
                require(info.namespace == started.parent_workflow_namespace == namespace["name"])
                require(
                    (info.parent_id, info.parent_run_id)
                    == (origin["coordinator_id"], origin["coordinator_execution_epoch"])
                )
                require(
                    (
                        started.parent_workflow_execution.workflow_id,
                        started.parent_workflow_execution.run_id,
                    )
                    == (origin["coordinator_id"], origin["coordinator_execution_epoch"])
                )
                require(
                    payload["deployment_admission"]
                    == {"version": 2, "root": root, "lineage": [], "session_origin": origin}
                )
            release = released.get(identity)
            if release is not None:
                require(
                    {
                        k: v
                        for k, v in release["root"].items()
                        if k not in {"state", "execution_epoch"}
                    }
                    == {k: v for k, v in root.items() if k not in {"state", "execution_epoch"}}
                )
                require(release["root"]["execution_epoch"] == epoch)
                retired = True
        except Exception as error:
            report["reasons"].append("root_evidence_invalid")
            report["root_evidence_exception_type"] = type(error).__name__
        report["accepted_roots"].append(copy.deepcopy(record))
        report["retired_roots" if retired else "retained_roots"].append(record)
    if version == 4:
        report["coordinators"] = []
        for identity, records in sessions.items():
            try:
                require(records)
                await session_evidence(
                    client,
                    identity,
                    records,
                    accepted,
                    released,
                    namespace,
                    scope,
                    report["registry_execution_epoch"],
                    archive,
                )
                report["coordinators"].append(identity)
            except Exception as error:
                report["reasons"].append("session_evidence_invalid")
                report["session_evidence_exception_type"] = type(error).__name__
    if report["retained_roots"]:
        report["reasons"].append("root_retirement_unconfirmed")
    if set(released) - set(accepted):
        report["reasons"].append("release_acceptance_unmatched")
    if any(
        type(row) is not dict or row.get("effect") != "read_only" and row.get("state") != "adopted"
        for row in effects
    ):
        report["reasons"].append("unadopted_write")
    report["reasons"] = sorted(set(report["reasons"]))
    report["deletion_allowed"] = not report["reasons"]
    return report


async def session_evidence(
    client, identity, records, accepted, released, namespace, scope, registry_epoch, archive
):
    """Read/reduce original History through the existing pure Session state only."""
    from ralf_agent.temporal_session_activities import namespace_id
    from ralf_agent.temporal_session_deployment_dto import decode_control_body
    from ralf_agent.temporal_session_deployment_state import START_SELECTOR_FIELDS
    from ralf_agent.temporal_session_state import (
        SESSION_ACTIVITY,
        SESSION_WORKFLOW,
        TemporalSessionState,
        workflow_id,
    )

    require(await namespace_id(client) == namespace["id"])
    handle = client.get_workflow_handle(identity)
    info = await handle.describe(rpc_timeout=timedelta(seconds=15))
    pinned = client.get_workflow_handle(identity, run_id=info.run_id)
    history = await pinned.fetch_history(rpc_timeout=timedelta(seconds=15))
    archive(identity, history)
    started, epoch = original_started(info, history, identity)
    initial = await decoded(client, started.input.payloads)
    require(info.workflow_type == SESSION_WORKFLOW and info.namespace == namespace["name"])
    require(info.parent_id is None and info.parent_run_id is None)
    require(not started.parent_workflow_execution.workflow_id)
    require(initial["scope"] == scope and initial["namespace_id"] == namespace["id"])
    require(info.task_queue == started.task_queue.name == initial["task_queue"])
    session = TemporalSessionState(
        initial, deployment_context={"namespace": namespace, "coordinator_execution_epoch": epoch}
    )
    require(workflow_id(session.key) == identity)
    for record in records:
        saved = record["session_submission"]
        require(saved["session_key"] == session.key.to_dict())
        binding = saved["binding"]
        require(
            binding["task_queue"] == initial["task_queue"]
            and binding["activity_timeout"] == initial["activity_timeout"]
            and binding["manifest"] == initial["manifest"]
        )

    completions = {}
    for event in history.events:
        if event.HasField("workflow_execution_update_completed_event_attributes"):
            done = event.workflow_execution_update_completed_event_attributes
            require(done.accepted_event_id not in completions)
            completions[done.accepted_event_id] = done
    schedules, children = {}, set()

    def drain():
        while session.recover_deployment_result():
            pass

    for event in history.events:
        if event.HasField("activity_task_scheduled_event_attributes"):
            attrs = event.activity_task_scheduled_event_attributes
            if attrs.activity_type.name == SESSION_ACTIVITY:
                schedules[attrs.activity_id] = await decoded(client, attrs.input.payloads)
        elif event.HasField("start_child_workflow_execution_initiated_event_attributes"):
            drain()
            attrs = event.start_child_workflow_execution_initiated_event_attributes
            entry = session.deployment_turn()
            intent = entry.intent
            require(attrs.workflow_id == intent["run_id"] and attrs.workflow_id not in children)
            require(attrs.task_queue.name == intent["submission"]["task_queue"])
            payload = await decoded(client, attrs.input.payloads)
            saved = accepted[attrs.workflow_id]
            require(
                saved["intent"] == intent
                and payload
                == {
                    "scope": intent["scope"],
                    "command_id": intent["run_command_id"],
                    **{
                        name: intent["submission"][name]
                        for name in ("request", "manifest", "activity_timeout")
                    },
                    "deployment_admission": {
                        "version": 2,
                        "root": saved["root"],
                        "lineage": [],
                        "session_origin": saved["session_origin"],
                    },
                }
            )
            require(entry.issue_start())
            children.add(attrs.workflow_id)
        elif event.HasField("workflow_execution_update_accepted_event_attributes"):
            request = event.workflow_execution_update_accepted_event_attributes.accepted_request
            done = completions.get(event.event_id)
            require(done is not None and done.meta.update_id == request.meta.update_id)
            if done.outcome.WhichOneof("value") != "success":
                continue
            name = request.input.name
            if name not in {
                "command",
                "session_deployment_call_start",
                "session_deployment_call_end",
            }:
                continue
            value = await decoded(client, request.input.args.payloads)
            result = await decoded(client, done.outcome.success.payloads)
            if name == "command":
                drain()
                require(session.command(value) == result)
                continue
            call = value["identity"]
            entry = session.deployment_turn({key: call[key] for key in START_SELECTOR_FIELDS})
            require(
                call["activity_name"] == SESSION_ACTIVITY
                and schedules.get(call["activity_id"]) == entry.control_request(call["mode"])
            )
            if name == "session_deployment_call_start":
                require(set(value) == {"identity"} and entry.begin_call(call) == result)
            else:
                require(entry.end_call(value) == result)
                body = decode_control_body(
                    value["body_result"], entry.intent["submission"]["manifest"]
                )
                if (
                    body["ok"]
                    and call["mode"] == "observe"
                    and body["result"]["advance"] is not None
                ):
                    require(
                        body["result"]["advance"]["retirement"] == released[entry.intent["run_id"]]
                    )
                drain()
    drain()
    snapshot = session.snapshot()
    require(snapshot["busy"] is False and snapshot["active_run"] is None)
    require(snapshot["deployment_close"] == {"pending_calls": 0, "unpublished_turns": 0})
    expected = {
        key
        for key, saved in accepted.items()
        if saved.get("intent", {}).get("coordinator_id") == identity
    }
    require(
        children
        == expected
        == {entry.intent["run_id"] for entry in session.deployment_turns.values()}
    )
    require(
        all(
            entry.published
            and entry.registry_execution_epoch == registry_epoch
            and entry.intent == accepted[entry.intent["run_id"]]["intent"]
            and entry.intent["run_id"] in released
            for entry in session.deployment_turns.values()
        )
    )
    for record in records:
        require(
            session.receipts[record["session_submission"]["payload"]["command_id"]]
            == record["session_receipt"]
        )
    current = await handle.describe(rpc_timeout=timedelta(seconds=15))
    require(
        current.run_id == epoch
        and current.raw_description.workflow_execution_info.first_run_id == epoch
    )
    require(await namespace_id(client) == namespace["id"])
