"""Mechanical edge recovery reuses business identity, not SDK Update identity."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

pytest.importorskip("temporalio")

from ralf_agent import AgentSpec, TemporalRuntime, ToolRegistry
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.temporal_workflow import TemporalRunWorkflow
from ralf_agent.types import submission_request


class Provider:
    identity = {"kind": "delegated-recovery-test", "version": "1"}

    async def complete(self, messages, tools):
        raise AssertionError("Mechanical recovery must not dispatch a model")


def node(run_id, scope, epoch):
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
    value = object.__new__(TemporalRunWorkflow)
    value.state = TemporalRunState(
        run_id,
        scope,
        "original-submit",
        submission_request(AgentSpec("a", "Answer"), "original", budget=8),
        runtime.manifest,
        epoch,
    )
    value.wake_revision = 0
    return value


def sdk_commands(client, original_node):
    """Model only SDK Update dedup; the original command handler stays real."""
    original = client.get_workflow_handle
    cache = {}

    class Handle:
        def __init__(self, handle, run_id, epoch):
            self.handle, self.run_id, self.epoch = handle, run_id, epoch

        def __getattr__(self, name):
            return getattr(self.handle, name)

        async def signal(self, name, envelope):
            from ralf_agent.temporal_command_transport import accept

            assert name == "control_command"
            await accept(original_node, envelope, self.info())

        def info(self):
            return SimpleNamespace(
                workflow_id=original_node.state.run_id,
                run_id=original_node.state.epoch,
                first_execution_run_id=original_node.state.epoch,
                original_execution_run_id=original_node.state.epoch,
                namespace=client.namespace,
            )

        async def query(self, name, request):
            if name == "view" and "command_observation" in request:
                from ralf_agent.temporal_command_transport import observe

                return {
                    "command_observation": observe(
                        original_node, request["command_observation"], self.info()
                    )
                }
            return await self.handle.query(name, request)

        async def describe(self):
            return await self.handle.describe()

        async def execute_update(self, name, request, **options):
            if name != "command":
                return await self.handle.execute_update(name, request, **options)
            assert self.run_id == original_node.state.run_id
            assert self.epoch == original_node.state.epoch
            key = (self.run_id, self.epoch, options.get("id"))
            if options.get("id") is not None and key in cache:
                return copy.deepcopy(cache[key])
            result = await original_node.command(request)
            if options.get("id") is not None:
                cache[key] = copy.deepcopy(result)
            return result

    client.get_workflow_handle = lambda workflow_id, **options: Handle(
        original(workflow_id, **options), workflow_id, options.get("run_id")
    )


def test_public_original_edge_recovers_twice_with_one_business_command(monkeypatch):
    from ralf_agent import temporal_deployment_execution as execution
    from tests.test_temporal_deployment_control_release import environment

    async def run():
        runtime, client, _, _, binding = environment(monkeypatch)
        parent = client.proofs[binding["root_run_id"]]
        call = parent["children"][0]
        child = node(call["run_id"], parent["scope"], binding["target_execution_epoch"])
        sdk_commands(client, child)
        info = SimpleNamespace(
            workflow_id=parent["run_id"],
            workflow_run_id=parent["execution_epoch"],
            workflow_namespace=client.namespace,
        )
        request = {
            "mode": "recover",
            "scope": parent["scope"],
            "parent_id": parent["run_id"],
            "child": call,
            "runtime_manifest": runtime.manifest,
        }
        before = copy.deepcopy(client.registry.commands)
        for _ in range(3):
            await execution.control(runtime, client, request, info)
        assert child.wake_revision == 3
        assert sum(e["kind"] == "command_recorded" for e in child.state.event_log) == 1
        assert client.registry.commands == before
        assert not child.state.actions

    asyncio.run(run())


@pytest.mark.parametrize("publication", [3, 4])
@pytest.mark.parametrize("changing_revision", [False, True])
def test_public_coding_edge_keeps_one_identity_across_child_revisions(
    publication, changing_revision
):
    from ralf_agent import temporal_coding_composition_control as composition
    from tests.test_temporal_coding_composition_control import proof
    from tests.test_temporal_deployment_execution import Client

    async def run():
        client, original = Client(), proof()
        original["manifest"] = {
            **original["manifest"],
            "deployment_admission_protocol": {"version": publication},
        }
        child = node(original["run_id"], original["scope"], original["execution_epoch"])
        sdk_commands(client, child)
        for _ in range(3):
            if changing_revision:
                original["revision"] = child.state.revision
            await composition._command(client, original, "drive", owner_id="root")
        assert child.wake_revision == 3
        assert sum(e["kind"] == "command_recorded" for e in child.state.event_log) == 1
        await composition._command(client, original, "cancel", owner_id="root")
        assert child.state.state == "cancelled"
        await composition._command(client, original, "drive", owner_id="root")
        assert child.state.state == "cancelled" and child.wake_revision == 5
        assert sum(e["kind"] == "command_recorded" for e in child.state.event_log) == 2
        assert not child.state.actions

    asyncio.run(run())
