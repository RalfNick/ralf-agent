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
    close_observed = False
    try:
        started, epoch = original_started(
            description, history, registry_id(policy["deployment_id"])
        )
        require(description.workflow_type == "ralf.temporal.commands.v1")
        require(client.namespace == namespace["name"])
        initialization = await decoded(client, started.input.payloads)
        require(
            initialization
            == {"deployment_admission": {"version": 3, "policy": policy, "namespace": namespace}}
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
                "release_deployment_root",
                "close_deployment_coding_submissions",
            }:
                continue
            value = await decoded(client, request.input.args.payloads)
            if name == "reserve" and value.get("kind") != "submit":
                continue
            require(value.get("admission_policy") == policy and value.get("namespace") == namespace)
            done = completions.get(event_id)
            if done is None:
                report["reasons"].append("pending_registry_update")
                continue
            require(done.meta.update_id == request.meta.update_id)
            if done.outcome.WhichOneof("value") != "success":
                if name == "reserve":
                    rejected.add(value["target"])
                continue
            result = await decoded(client, done.outcome.success.payloads)
            if name == "reserve":
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
                    close_observed = True
    except Exception as error:
        report["reasons"].append("registry_evidence_invalid")
        report["evidence_exception_type"] = type(error).__name__
    if not close_observed:
        report["reasons"].append("scoped_close_unconfirmed")
    if targets - set(accepted) - rejected:
        report["reasons"].append("target_acceptance_unresolved")
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
