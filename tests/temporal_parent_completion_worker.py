"""Real Worker fixture; Responses native items are supplied by an offline transport."""

import asyncio
import copy
import json
import os
import signal
from pathlib import Path

import httpx

from ralf_agent import (
    AgentSpec,
    CompleteModelHistory,
    DynamicWorkflowSpec,
    ModelPlanner,
    SQLiteMemory,
    TeamSpec,
    ToolRegistry,
)
from ralf_agent.parent_completion import ParentCompletionPolicy
from ralf_agent.parent_completion_rules import ReceiptParentCompletionGate
from ralf_agent.parent_verification_stage import ModelParentVerificationStage
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from tests.test_responses_reasoning_runtime import native_output, provider, wire_response

SESSION_WINDOWS = frozenset({"final-session", "lost-session-ack"})


def audit(root, row):
    with (root / "parent-audit.jsonl").open("a") as output:
        output.write(json.dumps(row) + "\n")


class AuditedSession(SQLiteMemory):
    def __init__(self, root):
        super().__init__(root / "session.sqlite")
        self.root = root

    def append(self, scope, address, message, *, expected_revision, message_id):
        fields = {
            "address": address,
            "message_id": message_id,
            "expected_revision": expected_revision,
            "message": copy.deepcopy(message),
        }
        audit(self.root, {"kind": "session-append-attempt", **fields})
        revision = super().append(
            scope, address, message, expected_revision=expected_revision, message_id=message_id
        )
        audit(self.root, {"kind": "session-append-committed", "revision": revision, **fields})
        return revision


def runtime(root, kind="team", *, window="proposal", mode="host"):
    root = Path(root)
    clients = []

    def model(name):
        def reply(request):
            body = json.loads(request.content)
            assert body["reasoning"] == {"effort": "high", "context": "all_turns"}
            assert body["store"] is False and body["include"] == ["reasoning.encrypted_content"]
            result = any(i.get("type") == "function_call_output" for i in body["input"])
            phase = "initial" if name == "business" and not result else "final"
            output = native_output("parent-" + name, "tool-1" if phase == "initial" else phase)
            if phase == "final":
                value = (
                    {"steps": [{"id": "calculation", "member": "worker", "input": {"quantity": 3}}]}
                    if name == "planner"
                    else {"amount": 6}
                    if name == "business"
                    else {
                        "status": "reject" if kind == "team-reject" else "accept",
                        "feedback": "fixture rejection" if kind == "team-reject" else None,
                        "evidence_ids": [],
                    }
                )
                output[-1]["content"][0]["text"] = json.dumps(value)
            audit(
                root,
                {
                    "kind": "model",
                    "provider": name,
                    "phase": phase,
                    "body": copy.deepcopy(body),
                    "output": output,
                },
            )
            return wire_response(output)

        client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        clients.append(client)
        return provider("parent-" + name, client)

    tools = ToolRegistry()

    def calculate(quantity: int, price: int = 2):
        audit(root, {"kind": "tool", "quantity": quantity, "price": price})
        return {"amount": quantity * price}

    session = window in SESSION_WINDOWS
    tools.register_function(calculate, effect="read_only", requires_approval=not session, cost=1)
    parent_kind = "dynamic" if kind in {"plan", "dag"} else "team"
    gate = ReceiptParentCompletionGate(
        [
            {
                "id": "calculation",
                "member_path": ["worker"],
                "tool": "calculate",
                "argument_bindings": {"quantity": {"source": "task", "pointer": "/quantity"}},
                "output_bindings": {"/amount": {"source": "candidate", "pointer": "/amount"}},
            }
        ],
        required_members=[["worker"]],
        candidate_schema={
            "type": "object",
            "properties": {"amount": {"type": "integer"}},
            "required": ["amount"],
            "additionalProperties": False,
        },
    )
    policy = ParentCompletionPolicy(
        gate,
        model_stage=None
        if kind == "team-pure"
        else ModelParentVerificationStage(provider="verifier"),
    )
    agent = AgentSpec(
        "business",
        "Calculate quantity units",
        ("calculate",),
        max_decisions=3,
        max_context_chars=32768,
        output_schema={
            "type": "object",
            "properties": {"amount": {"type": "integer"}},
            "required": ["amount"],
            "additionalProperties": False,
        },
    )
    if parent_kind == "dynamic":
        definition = DynamicWorkflowSpec(
            "checked-plan",
            {"worker": agent},
            planner="dag-rule" if kind == "dag" else "fixture-model",
            plan_mode="dag" if kind == "dag" else "flat",
            child_budget=6,
            max_steps=8,
            completion_policy="checked",
        )
    else:
        definition = TeamSpec(
            "checked-team", {"worker": agent}, child_budget=6, completion_policy="checked"
        )

    class GatedRuntime(TemporalRuntime):
        async def adopt_model(self, request):
            if (
                mode == "original"
                and window in {"receipt", "cancel-receipt"}
                and request["original_request"]["step"]["provider"] == "verifier"
            ):
                (root / "checkpoint").write_text(request["original_request"]["run_id"])
                await asyncio.Event().wait()
            return await super().adopt_model(request)

        async def verify_parent_completion(self, request):
            if mode == "original" and window == "proposal" and request["mode"] == "interpret":
                (root / "checkpoint").write_text(request["run_id"])
                await asyncio.Event().wait()
            return await super().verify_parent_completion(request)

        async def manage_session(self, request, **kwargs):
            is_root = request["run_id"] == request.get("session_lineage", {}).get("root_run_id")
            if (
                mode == "original"
                and window == "lost-session-ack"
                and is_root
                and request["phase"] == "session-write"
            ):
                from temporalio.exceptions import ApplicationError

                ended = asyncio.Event()
                original_end = kwargs.get("on_end")
                assert callable(original_end), (
                    "Lost ACK requires the actual original History end Update"
                )

                async def committed_end(proof):
                    await original_end(proof)
                    (root / "session-lost-ack-end-proof.json").write_text(
                        json.dumps(proof, indent=2) + "\n"
                    )
                    audit(root, {"kind": "session-end-confirmed", "proof": copy.deepcopy(proof)})
                    ended.set()

                kwargs["on_end"] = committed_end
                # Append and its independent original History Update both happen
                # before discarding the Activity result. No receipt/stop is forged.
                response = await super().manage_session(request, **kwargs)
                assert response["ok"] and response["execution_stopped"] is True
                await asyncio.wait_for(ended.wait(), timeout=8)
                (root / "session-lost-ack-write-request.json").write_text(
                    json.dumps(request, indent=2) + "\n"
                )
                (root / "session-lost-ack-write-result.json").write_text(
                    json.dumps(response, indent=2) + "\n"
                )
                (root / "session-ack-lost").write_text(request["run_id"])
                raise ApplicationError(
                    "Fixture lost original Session write ACK after committed receipt and real end Update",
                    type="fixture_session_write_ack_lost",
                    non_retryable=True,
                )
            if (
                mode == "original"
                and window in SESSION_WINDOWS
                and is_root
                and request["phase"] == "adopt"
            ):
                (root / "session-checkpoint-request.json").write_text(
                    json.dumps(request, indent=2) + "\n"
                )
                (root / "checkpoint").write_text(request["run_id"])
                await asyncio.Event().wait()
            return await super().manage_session(request, **kwargs)

    backend = (
        AuditedSession(root)
        if window == "lost-session-ack"
        else SQLiteMemory(root / "session.sqlite")
        if session
        else None
    )
    from ralf_agent.temporal_session_topology import CompositeSessionTopology

    execution = GatedRuntime(
        providers={
            "default": model("business"),
            "verifier": model("verifier"),
            "planner": model("planner"),
        },
        tools=tools,
        planners={"fixture-model": ModelPlanner(provider="planner")},
        parent_completion_policies={"checked": policy},
        model_continuation=True,
        model_history=CompleteModelHistory(scope="session" if session else "run"),
        **(
            {
                "enable_sessions": True,
                "session_store": backend,
                "session_writes": True,
                "session_topology": CompositeSessionTopology(),
                "context_reads": True,
            }
            if session
            else {}
        ),
    )
    return execution, definition, clients, backend


async def run():
    from temporalio.client import Client

    root = Path(os.environ["RALF_PARENT_COMPLETION_ROOT"])
    mode, window = (
        os.environ["RALF_PARENT_COMPLETION_MODE"],
        os.environ["RALF_PARENT_COMPLETION_WINDOW"],
    )
    execution, _, clients, backend = runtime(
        root, os.environ["RALF_PARENT_COMPLETION_KIND"], window=window, mode=mode
    )
    (root / ("worker-manifest-" + mode + ".json")).write_text(
        json.dumps(execution.orchestration_release, indent=2) + "\n"
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    stopped = asyncio.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(signum, stopped.set)
    try:
        async with build_temporal_worker(
            client, task_queue=os.environ["RALF_TEST_TEMPORAL_QUEUE"], runtime=execution
        ):
            print("TEMPORAL_PARENT_COMPLETION_READY " + str(os.getpid()), flush=True)
            await stopped.wait()
    finally:
        await execution.close_context_execution(wait_timeout=5)
        await execution.close_session_execution(wait_timeout=5)
        for client in clients:
            await client.aclose()
        if backend is not None:
            backend.store.close()
        (root / ("worker-closed-" + mode)).write_text("closed")
