"""Only network transport is doubled; receipts/governance use real Temporal state."""

import asyncio
from dataclasses import asdict
from types import SimpleNamespace

from ralf_agent import ModelResponse, ToolCall, ToolRegistry, ToolSpec
from ralf_agent.errors import AuthorizationDenied, IdempotencyConflict
from ralf_agent.temporal import TemporalEngine
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_state import (
    COMMAND_REGISTRY_NAME,
    TemporalCommandRegistryState,
    TemporalRunState,
)


class Provider:
    identity = {"kind": "temporal-agent-facade-test", "version": "1"}

    async def complete(self, messages, tools):
        if tools and not any(m["role"] == "tool" for m in messages):
            return ModelResponse(tool_calls=[ToolCall("lookup", {}, "lookup-call")])
        return ModelResponse(output="done")


async def lookup(arguments, context):
    return {"found": True}


def worker_runtime():
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "lookup", "Lookup", {"type": "object"}, requires_approval=True, effect="read_only"
        ),
        lookup,
    )
    return TemporalRuntime(providers={"default": Provider()}, tools=tools)


class AlreadyStarted(Exception):
    pass


class RPCError(Exception):
    status = "NOT_FOUND"


class ApplicationError(Exception):
    pass


class UpdateFailed(Exception):
    pass


def sdk():
    return (
        object,
        UpdateFailed,
        SimpleNamespace(FAIL="fail"),
        SimpleNamespace(REJECT_DUPLICATE="reject"),
        ApplicationError,
        AlreadyStarted,
        RPCError,
        SimpleNamespace(NOT_FOUND="NOT_FOUND"),
    )


class StateClient:
    namespace = "default"

    def __init__(self, address="127.0.0.1:7233"):
        self.service_client = SimpleNamespace(config=SimpleNamespace(target_host=address))
        self.states, self.registries = {}, {}
        self.tool_calls = 0
        self.hold_execution = False
        self.query_gate = None
        self.start_entered, self.start_gate = asyncio.Event(), asyncio.Event()
        self.start_gate.set()
        self.closed = False

    async def start_workflow(self, name, accepted, *, id, **options):
        if id in self.states or id in self.registries:
            raise AlreadyStarted()
        if name == COMMAND_REGISTRY_NAME:
            self.registries[id] = TemporalCommandRegistryState(accepted["scope"])
        else:
            self.states[id] = TemporalRunState(
                id,
                accepted["scope"],
                accepted["command_id"],
                accepted["request"],
                accepted["manifest"],
            )
            self.start_entered.set()
            await self.start_gate.wait()
            await self.advance(id)

    def get_workflow_handle(self, workflow_id, *, run_id=None):
        if run_id is not None and run_id != workflow_id + ":original-epoch":
            raise RPCError()
        return StateHandle(self, workflow_id)

    async def advance(self, run_id):
        if self.hold_execution:
            return
        state = self.states[run_id]
        for _ in range(40):
            operation = state.next_operation()
            if operation is None:
                return
            action, _ = operation
            if action["kind"] == "model":
                response = await Provider().complete(state.messages, list(state.step["tools"]))
                state.accept_model(
                    action["id"],
                    {
                        "ok": True,
                        "output": response.output,
                        "tool_calls": [asdict(call) for call in response.tool_calls],
                        "usage": None,
                    },
                )
            elif action["kind"] == "tool":
                self.tool_calls += 1
                state.accept_tool(action["id"], {"ok": True, "result": {"found": True}})
                # The actual worker acknowledges adopted read-only evidence.
                state.pending_acks.clear()
            else:
                raise AssertionError("Unexpected fixture operation")
        raise AssertionError("Unbounded fixture execution")


class StateHandle:
    def __init__(self, client, run_id):
        self.client, self.run_id = client, run_id

    async def signal(self, name, value):
        raise AssertionError("The Update-only fixture Worker must not receive Signals")

    async def describe(self):
        from ralf_agent.temporal_parent_state import PARENT_WORKFLOW_NAME, TemporalParentState
        from ralf_agent.temporal_state import WORKFLOW_NAME

        if self.run_id not in self.client.states:
            raise RPCError()
        epoch = self.run_id + ":original-epoch"
        return SimpleNamespace(
            id=self.run_id,
            namespace=self.client.namespace,
            run_id=epoch,
            raw_info=SimpleNamespace(first_run_id=epoch),
            workflow_type=PARENT_WORKFLOW_NAME
            if isinstance(self.client.states[self.run_id], TemporalParentState)
            else WORKFLOW_NAME,
        )

    async def query(self, name, value):
        assert name == "view"
        if self.run_id in self.client.registries:
            # This network double represents the original Update-only Worker.
            # Its unknown views return the exact scoped configuration used by
            # the SDK to identify that Worker before sending any Signal.
            registry = self.client.registries[self.run_id]
            if value.get("scope") != registry.scope:
                raise AuthorizationDenied("Command registry belongs to another trusted scope")
            return {
                "scope": dict(registry.scope),
                "capacity": registry.capacity,
                "accepted_commands": len(registry.identities),
            }
        if self.run_id not in self.client.states:
            raise RPCError()
        state = self.client.states[self.run_id]
        state.authorize(value["scope"])
        if self.client.query_gate is not None:
            await self.client.query_gate.wait()
        kind = value["kind"]
        if kind == "submission":
            if value["request"] != state.request:
                raise IdempotencyConflict("Original request differs")
            return state.receipts[value["command_id"]]
        if kind == "diagnostics":
            return state.diagnostics()
        if kind == "status":
            return state.snapshot()
        if kind == "events":
            return [x for x in state.event_log if x["seq"] > value["after"]][: value["limit"]]
        raise AssertionError("Unexpected query")

    async def execute_update(self, name, value):
        if self.run_id in self.client.registries:
            assert name == "reserve"
            return self.client.registries[self.run_id].reserve(value)
        assert name == "command"
        state = self.client.states[self.run_id]
        receipt = state.command(value["command_id"], value["payload"])
        await self.client.advance(self.run_id)
        return receipt


def engine(monkeypatch, *, client=None, release=None):
    monkeypatch.setattr("ralf_agent.temporal._sdk", sdk)
    return TemporalEngine(
        client or StateClient(), task_queue="agents", release=release or worker_runtime().manifest
    )
