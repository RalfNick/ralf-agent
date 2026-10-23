"""Small, read-only summaries and shell-quoted local-owner command hints."""

import json
import shlex

from .binding_manifests import all_step_manifests, step_manifest
from .engine import TERMINAL
from .types import RunDiagnostics, RunSnapshot, digest
from .workflow_runtime import workflow_details


def command_hint(db, factory, command, *arguments, config=None):
    parts = ["relf", "--db", str(db)]
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
    providers = [
        value for view in all_step_manifests(manifest) for value in view["providers"].values()
    ]
    is_demo = bool(providers) and all(
        value.get("kind") == "offline-scripted-oncall" for value in providers
    )
    actions = {action["id"]: action for action in snapshot.actions}

    def effect(action):
        return step_manifest(manifest, action["node"])["tools"][action["tool"]]["effect"]

    needs_factory = factory is None and config is None and not is_demo
    configured_factory = factory or ("YOUR_MODULE:create_engine" if needs_factory else None)
    pending = []
    for action in snapshot.pending:
        if action.get("kind") == "input":
            item = dict(action)
            item["send_input_command"] = command_hint(
                db,
                configured_factory,
                "send-input",
                item["owner"]["run_id"],
                item["pending_id"],
                "--digest",
                item["target_digest"],
                "--value-json",
                '"YOUR_ANSWER"',
                "--command-id",
                "reply:" + item["pending_id"],
                config=config,
            )
            pending.append(item)
            continue
        item = dict(action)
        item["effect"] = effect(actions[item["action_id"]])
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
            "effect": effect(action),
            "effect_key": action["effect_key"],
            "digest": action["digest"],
        }
        for action in snapshot.actions
        if action["kind"] == "tool"
        and action["status"] in {"executing", "outcome_unknown"}
        and effect(action) != "read_only"
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
    if "agent_bindings" in manifest:
        report["agent_bindings"] = {
            path: {"resolved": entry["resolved"], "providers": entry["manifest"]["providers"]}
            for path, entry in manifest["agent_bindings"]["steps"].items()
        }
    if details.workflow is not None:
        report["workflow"] = details.workflow
        for child in report["workflow"].get("children", []):
            child["inspect_command"] = command_hint(
                db, None, "--format", "text", "inspect", child["run_id"]
            )
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
    for path, entry in report.get("agent_bindings", {}).items():
        lines.append(f"Agent binding: {path}")
        for alias, identity in entry["providers"].items():
            lines.append("  Provider: " + alias + " / " + json.dumps(identity, ensure_ascii=False))
    if report["needs_factory"]:
        lines.append("Set YOUR_MODULE:create_engine to the original trusted runtime factory.")
    if report["error"]:
        lines.append("Error: " + json.dumps(report["error"], ensure_ascii=False))
    if report.get("workflow") is not None:
        for node_id, node in report["workflow"].get("nodes", {}).items():
            lines.append(f"Node: {node_id} ({node['state']})")
        for child in report["workflow"].get("children", []):
            lines.append(
                f"Child: {child['id']} / {child['member']} / {child['run_id']} ({child['state']})"
            )
            lines.append("  " + child["inspect_command"])
        for revision in report["workflow"].get("revisions", []):
            lines.append(f"Plan revision: {revision.get('plan_revision', revision['revision'])}")
        for node_id, node in report["workflow"].get("dag", {}).get("nodes", {}).items():
            lines.append(f"DAG node: {node_id} ({node['state']})")
    for item in report["pending"]:
        if item.get("kind") == "input":
            lines.extend(
                [
                    f"Question: {item['pending_id']}",
                    item["prompt"],
                    "Reply Schema: " + json.dumps(item["reply_schema"], ensure_ascii=False),
                    "Replace YOUR_ANSWER with a Schema-valid JSON value, then send input:",
                    "  " + item["send_input_command"],
                ]
            )
            continue
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
        if template == "sessions":
            return "\n".join(
                [
                    f"Created offline Session starter: {result['directory']}",
                    "  " + shlex.join(["cd", result["directory"]]),
                    "  "
                    + shlex.join(
                        [
                            "python",
                            "-m",
                            result["module"],
                            "run",
                            "--input",
                            "hello",
                            "--command-id",
                            "first",
                        ]
                    ),
                    "Reconnect with the reference path returned by that command:",
                    "  "
                    + shlex.join(
                        [
                            "python",
                            "-m",
                            result["module"],
                            "resume",
                            "--reference",
                            "REFERENCE_PATH",
                        ]
                    ),
                ]
            )
        if template == "temporal":
            return "\n".join(
                [
                    f"Created offline Temporal starter: {result['directory']}",
                    "Install relf-agent[temporal] and set RALF_TEMPORAL_ADDRESS to your Service.",
                    "  " + shlex.join(["cd", result["directory"]]),
                    "  " + shlex.join(["python", "-m", result["module"], "worker"]),
                    "In another terminal from the same directory:",
                    "  " + shlex.join(["python", "-m", result["module"], "run", "--kind", "dag"]),
                ]
            )
        if template == "a2a":
            return "\n".join(
                [
                    f"Created offline A2A service starter: {result['directory']}",
                    "Install relf-agent[server] and set RALF_A2A_TOKEN locally in both terminals.",
                    "  " + shlex.join(["cd", result["directory"]]),
                    "  " + shlex.join(["python", "-m", result["module"], "serve"]),
                    "In another terminal from the same directory:",
                    "  "
                    + shlex.join(["python", "-m", result["module"], "client", "--input", "hello"]),
                ]
            )
        if template == "async":
            return "\n".join(
                [
                    f"Created offline async Agent starter: {result['directory']}",
                    f"Async Python factory: {result['factory']}",
                    "  " + shlex.join(["cd", result["directory"]]),
                    "  " + shlex.join(["python", "-m", result["module"], "--input", "hello"]),
                    "  " + shlex.join(["python", "-m", result["module"], "--resume", "RUN_ID"]),
                    "  "
                    + command_hint(
                        ".ralf/runs.sqlite", None, "--format", "text", "inspect", "RUN_ID"
                    ),
                ]
            )
        if template in {"ingest", "hybrid"}:
            entries = [
                [
                    "ingest",
                    "README.md",
                    "--document-id",
                    "guide",
                    "--command-id",
                    "ingest-guide",
                    "--expected-version",
                    "0",
                ],
            ]
            if template == "hybrid":
                entries.append(["index", "--document-id", "guide"])
            entries.append(["query", "--query", "Agent", "--command-id", "query-guide"])
        elif template in {
            "adapter-contracts",
            "session-contracts",
            "facts-contracts",
            "model-contracts",
        }:
            entries = [["seed"], ["check"], ["run"]]
        elif template == "memory-index":
            entries = [["seed"], ["run", "--command-prefix", "memory-first"]]
        else:
            entries = [
                {
                    "oncall": ["--ticket", "INC-001"],
                    "rag": ["--query", "缓存连接失败怎么恢复"],
                    "cli": ["run"],
                    "user-input": ["run", "--command-id", "first-task"],
                    "config": ["--input", "hello"],
                    "model": ["--input", "hello"],
                    "graph": ["--input", "hello"],
                    "parallel": ["--input", "hello"],
                    "plan": ["--input", "hello"],
                    "team": ["--input", "hello"],
                    "dag": ["--input", "hello"],
                    "nested": ["--input", "hello"],
                }.get(template, [])
            ]
        lines = [f"Created Agent starter: {result['directory']}"]
        if result["factory"] is not None:
            lines.append(f"Runtime factory: {result['factory']}")
        lines.extend(
            ["Run from the generated directory:", "  " + shlex.join(["cd", result["directory"]])]
        )
        lines.extend(
            "  " + shlex.join(["python", "-m", result["module"], *arguments])
            for arguments in entries
        )
        lines.append("See README.md for configuration, approval, observation and recovery steps.")
        return "\n".join(lines)
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
