"""Small, read-only summaries and shell-quoted local-owner command hints."""

import json
import shlex

from .engine import TERMINAL
from .types import RunDiagnostics, RunSnapshot, digest
from .workflow_runtime import workflow_details


def command_hint(db, factory, command, *arguments, config=None):
    parts = ["ralf", "--db", str(db)]
    if factory:
        parts.extend(("--factory", factory))
    elif config:
        parts.extend(("--config", str(config)))
    return shlex.join([*parts, command, *arguments])


def inspection(run, budget, db, factory=None, *, config=None):
    return diagnostics_inspection(
        RunDiagnostics(
            RunSnapshot.from_record(run),
            run["manifest"],
            run["release_digest"],
            budget,
            workflow_details(run),
        ),
        db,
        factory,
        config=config,
    )


def diagnostics_inspection(details, db, factory=None, *, config=None):
    snapshot = details.snapshot
    manifest = details.manifest
    providers = manifest["providers"]
    is_demo = bool(providers) and all(
        value.get("kind") == "offline-scripted-oncall" for value in providers.values()
    )
    needs_factory = factory is None and config is None and not is_demo
    configured_factory = factory or ("YOUR_MODULE:create_engine" if needs_factory else None)
    pending = []
    for action in snapshot.pending:
        item = dict(action)
        item["effect"] = manifest["tools"][item["tool"]]["effect"]
        for decision in ("approve", "reject"):
            arguments = [
                snapshot.run_id,
                item["action_id"],
                "--digest",
                item["digest"],
                "--command-id",
                f"{decision}:{item['action_id']}:{item['digest']}",
            ]
            if decision == "reject":
                arguments.append("--reject")
            item[f"{decision}_command"] = command_hint(
                db, configured_factory, "approve", *arguments, config=config
            )
        pending.append(item)
    unresolved = [
        {
            "action_id": action["id"],
            "tool": action["tool"],
            "arguments": action["arguments"],
            "effect": manifest["tools"][action["tool"]]["effect"],
            "effect_key": action["effect_key"],
            "digest": action["digest"],
        }
        for action in snapshot.actions
        if action["kind"] == "tool"
        and action["status"] in {"executing", "outcome_unknown"}
        and manifest["tools"][action["tool"]]["effect"] != "read_only"
    ]
    recorded = [
        {
            "action_id": action["id"],
            "kind": action["kind"],
            "status": action["status"],
            "evidence_digest": digest(
                action["received_response"]
                if action["kind"] == "model"
                else action["effect_observation"]
            ),
        }
        for action in snapshot.actions
        if action["status"] in {"response_received", "receipt_received"}
    ]
    report = {
        "run_id": snapshot.run_id,
        "state": snapshot.state,
        "state_revision": snapshot.state_revision,
        "result": snapshot.result,
        "error": snapshot.error,
        "release": {"kernel": manifest["kernel"], "digest": details.release_digest},
        "budget": {"unit": "execution_credits", **details.budget},
        "needs_factory": needs_factory,
        "pending": pending,
        "unresolved_effects": unresolved,
        "recorded_evidence": recorded,
        "resume_command": (
            command_hint(db, configured_factory, "resume", snapshot.run_id, config=config)
            if snapshot.state not in TERMINAL or recorded
            else None
        ),
        "events_command": command_hint(db, None, "events", snapshot.run_id, "--after", "0"),
    }
    if details.workflow is not None:
        report["workflow"] = details.workflow
    return report


def render_inspection(report):
    lines = [
        f"Run: {report['run_id']}",
        f"State: {report['state']} (revision {report['state_revision']})",
        f"Release: {report['release']['kernel']} / {report['release']['digest']}",
    ]
    budget = report["budget"]
    lines.append(
        f"Execution credits: spent {budget['spent']}, held {budget['held']}, limit {budget['limit']}"
    )
    if report["needs_factory"]:
        lines.append("Set YOUR_MODULE:create_engine to the original trusted runtime factory.")
    if report["error"]:
        lines.append("Error: " + json.dumps(report["error"], ensure_ascii=False))
    if report.get("workflow") is not None:
        for node_id, node in report["workflow"]["nodes"].items():
            lines.append(f"Node: {node_id} ({node['state']})")
    for item in report["pending"]:
        lines.extend(
            [
                f"Approval: {item['action_id']} / {item['tool']} ({item['effect']})",
                "Arguments: " + json.dumps(item["arguments"], ensure_ascii=False),
                f"Digest: {item['digest']}",
                "Review the arguments, then explicitly approve or reject:",
                "  " + item["approve_command"],
                "  " + item["reject_command"],
            ]
        )
    for item in report["unresolved_effects"]:
        lines.extend(
            [
                f"Unconfirmed write: {item['action_id']} / {item['tool']} ({item['effect']})",
                "Arguments: " + json.dumps(item["arguments"], ensure_ascii=False),
                f"Effect key: {item['effect_key']}",
                "Check the business receipt; use the original reconciler or SDK reconcile() with verified evidence.",
                "A running handler may still own this operation. Do not submit a replacement Run.",
            ]
        )
    for item in report["recorded_evidence"]:
        lines.extend(
            [
                f"Saved evidence awaiting adoption: {item['action_id']} / {item['kind']} ({item['status']})",
                f"Evidence digest: {item['evidence_digest']}",
                "No external request is needed to adopt this saved evidence; later live steps may make new requests.",
            ]
        )
    if report["resume_command"]:
        lines.extend(["Continue with the original runtime:", "  " + report["resume_command"]])
    lines.extend(["Read events:", "  " + report["events_command"]])
    if report["result"] is not None:
        lines.append("Result: " + json.dumps(report["result"], ensure_ascii=False))
    return "\n".join(lines)


def render_result(result):
    """Human-readable control receipts and event pages; JSON remains the default."""
    if isinstance(result, dict) and "directory" in result and "factory" in result:
        template = result.get("template", "oncall")
        entry_arguments = (
            ["--input", "hello"]
            if template in {"config", "model", "graph"}
            else (
                ["--query", "缓存连接失败怎么恢复"]
                if template == "rag"
                else ["--ticket", "INC-001"]
            )
        )
        return "\n".join(
            [
                f"Created offline Agent starter: {result['directory']}",
                f"Runtime factory: {result['factory']}",
                "Start the test task, then inspect its approval:",
                "  " + shlex.join(["cd", result["directory"]]),
                "  " + shlex.join(["python", "-m", result["module"], *entry_arguments]),
                "  "
                + command_hint(
                    ".ralf/runs.sqlite", result["factory"], "--format", "text", "inspect", "RUN_ID"
                ),
            ]
        )
    if isinstance(result, list):
        return (
            "\n".join(
                f"{event['seq']} {event['kind']}: " + json.dumps(event["data"], ensure_ascii=False)
                for event in result
            )
            or "No events in this page."
        )
    return "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in result.items()
    )
