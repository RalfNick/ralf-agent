"""Optional public controls retain original owners and command receipts."""

import asyncio
from dataclasses import asdict

import pytest

from relf_agent import AgentSpec, LocalEngine, RuntimeBuilder, RuntimeCatalog, RuntimeProfile
from relf_agent.agent_run import RunRef
from relf_agent.agent_runtime import AgentRun
from relf_agent.errors import ValidationError
from relf_agent.runtime_config import COMPONENT_KINDS
from relf_agent.runtime_router import ProfiledEngine
from relf_agent.storage import SQLiteStore
from relf_agent.task_controls import TaskControlBridge
from relf_agent.types import CommandReceipt, RunSnapshot, Scope

from .helpers import ScriptedProvider
from .test_task_controls import Controls


def input_record(run_id="run"):
    request = {
        "schema_version": 1,
        "pending_id": "",
        "target_digest": "",
        "owner": {"run_id": run_id, "release_digest": "a" * 64, "scope": asdict(Scope())},
        "source": {"kind": "tool", "action_id": "ask", "node": 0, "proposal_digest": "b" * 64},
        "ordinal": 1,
        "prompt": "Which environment?",
        "reply_schema": {"type": "string", "minLength": 1},
        "max_reply_bytes": 65536,
        "policy_digest": "c" * 64,
    }
    # Use the shared creation API only once available; this tests projection,
    # not independently generated authority identities.
    from relf_agent.user_input import UserInputPolicy, make_input_record

    return make_input_record(
        run_id=run_id,
        release_digest=request["owner"]["release_digest"],
        scope=Scope(),
        source=request["source"],
        prompt=request["prompt"],
        policy=UserInputPolicy(),
        ordinal=1,
    )


def test_agent_run_input_control_keeps_original_target_and_optional_revision():
    class Host:
        async def _acontrol(self, ref, method, *args, **kwargs):
            assert ref.run_id == "child"
            assert method == "send_input"
            assert args == ("input:" + "b" * 64, "a" * 64, {"environment": "prod"})
            assert kwargs == {"command_id": "reply", "expected_state_revision": 7}
            return CommandReceipt("reply", "child", "send_input", apply_state="rejected")

    run = AgentRun(Host(), RunRef("authority", "default", "local-owner", "child", "b" * 64))
    receipt = asyncio.run(
        run.send_input(
            "input:" + "b" * 64,
            "a" * 64,
            {"environment": "prod"},
            command_id="reply",
            expected_state_revision=7,
        )
    )
    assert receipt.run_id == "child" and receipt.apply_state == "rejected"


def test_optional_controls_do_not_require_input_from_legacy_adapter():
    controls = TaskControlBridge(Controls(), Scope())
    assert asyncio.run(controls.status("run")).state == "queued"
    with pytest.raises(ValidationError, match="input"):
        asyncio.run(
            controls.send_input("run", "input:" + "b" * 64, "a" * 64, "prod", command_id="r")
        )


def test_optional_input_bridge_accepts_waiting_and_stable_rejections():
    class InputControls(Controls):
        def status(self, run_id):
            return RunSnapshot(run_id, "waiting_input", 2, None, None, (), ())

        def send_input(
            self,
            run_id,
            pending_id,
            target_digest,
            value,
            *,
            command_id,
            expected_state_revision=None,
        ):
            return CommandReceipt(
                command_id,
                run_id,
                "send_input",
                apply_state="rejected",
                outcome={"reason": "stale_pending_target"},
            )

    controls = TaskControlBridge(InputControls(), Scope())
    assert asyncio.run(controls.status("run")).state == "waiting_input"
    receipt = asyncio.run(
        controls.send_input("run", "input:" + "b" * 64, "a" * 64, "prod", command_id="reply")
    )
    assert receipt.apply_state == "rejected"
    assert receipt.outcome == {"reason": "stale_pending_target"}


def test_profiled_input_replay_does_not_construct_removed_profile(tmp_path):
    payload = {
        "run_id": "run",
        "pending_id": "input:" + "b" * 64,
        "digest": "a" * 64,
        "value": "prod",
    }
    path = tmp_path / "reply.sqlite"
    with SQLiteStore(path) as store:
        store.insert_run(
            {
                "id": "run",
                "revision": 0,
                "scope": asdict(Scope()),
                "manifest": {},
                "release_digest": "b" * 64,
                "state": "succeeded",
                "result": "prod",
                "error": None,
                "actions": [],
            }
        )
        receipt = store.command(Scope(), "reply", "send_input", payload, "run", lambda: {})
    engine = ProfiledEngine(RuntimeCatalog(), path)
    try:
        assert (
            engine.send_input("run", "input:" + "b" * 64, "a" * 64, "prod", command_id="reply")
            == receipt
        )
        assert engine._active is None
    finally:
        engine.close()


def test_configured_policy_schema_preflight_precedes_provider_io(tmp_path):
    assert "user_input_policies" in COMPONENT_KINDS, "missing configured policy family"
    from relf_agent.runtime_builder import ComponentRegistry

    called = []
    registry = ComponentRegistry()
    registry.register("provider", "must-not-run", lambda config, context: called.append(True))
    profile = RuntimeProfile(
        "input",
        "1",
        {"default": {"adapter": "must-not-run"}},
        {
            "user_input_policies": {
                "adapter": "configured",
                "config": {
                    "policies": {"ask": {"reply_schema": {"$ref": "https://invalid.test/schema"}}},
                    "tools": {"request_input": {"policy": "ask"}},
                },
            },
        },
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder(registry).build(profile, tmp_path / "never.sqlite")
    assert called == [] and not (tmp_path / "never.sqlite").exists()


def test_snapshot_projects_input_and_preserves_legacy_approval_bytes():
    from relf_agent import types

    assert callable(getattr(AgentRun, "send_input", None)), "missing public input control"
    record = input_record()
    approval = {
        "id": "write",
        "digest": "d" * 64,
        "tool": "apply",
        "arguments": {"id": 7},
        "status": "waiting_approval",
    }
    run = {
        "id": "run",
        "revision": 2,
        "scope": asdict(Scope()),
        "release_digest": "a" * 64,
        "state": "waiting_input",
        "result": None,
        "error": None,
        "actions": [approval],
        "input_requests": {record["request"]["pending_id"]: record},
    }
    snapshot = types.RunSnapshot.from_record(run)
    assert snapshot.pending[0] == {
        "action_id": "write",
        "digest": "d" * 64,
        "tool": "apply",
        "arguments": {"id": 7},
    }
    assert snapshot.pending[1] == {"kind": "input", **record["request"]}
    record["request"]["prompt"] = "Changed after observation"
    assert snapshot.pending[1]["prompt"] == "Which environment?"


@pytest.mark.parametrize(
    "record", [None, "deferred", {"request": "wrong"}, {"request": {"ordinal": "wrong"}}]
)
def test_snapshot_rejects_malformed_input_journal_with_typed_error(record):
    run = {
        "id": "run",
        "revision": 2,
        "scope": asdict(Scope()),
        "release_digest": "a" * 64,
        "state": "waiting_input",
        "result": None,
        "error": None,
        "actions": [],
        "input_requests": {"input:" + "b" * 64: record},
    }
    with pytest.raises(ValidationError):
        RunSnapshot.from_record(run)


def test_public_child_question_observation_and_reply_keep_original_owner(tmp_path):
    from relf_agent import ModelResponse, Runtime, TeamSpec, ToolCall, ToolRegistry
    from relf_agent.user_input import register_user_input

    async def run():
        tools = ToolRegistry()
        register_user_input(tools)
        provider = ScriptedProvider(
            [
                ModelResponse(
                    tool_calls=(ToolCall("request_input", {"prompt": "Which environment?"}),)
                ),
                ModelResponse(output="confirmed"),
            ]
        )
        async with Runtime(
            LocalEngine(
                SQLiteStore(tmp_path / "root.sqlite"), tools=tools, providers={"default": provider}
            ),
            owned=True,
        ) as runtime:
            root = await runtime.create_agent(
                TeamSpec(
                    "team",
                    {
                        "worker": AgentSpec("worker", "Ask", ("request_input",)),
                    },
                )
            ).submit("Choose", command_id="start")
            waiting = await root.wait(wait_timeout=1)
            assert waiting.snapshot.state == "waiting_input"
            question = (await root.pending())[0]
            child = await runtime.aattach(RunRef.from_dict(question["ref"]))
            assert child.ref.run_id != root.ref.run_id
            observer = asyncio.create_task(root.wait(terminal_only=True))
            await asyncio.sleep(0)
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            assert (await root.pending())[0] == question
            rejected = await child.send_input(
                question["pending_id"], question["target_digest"], {}, command_id="invalid"
            )
            assert rejected.apply_state == "rejected"
            assert provider.calls == 1
            receipt = await child.send_input(
                question["pending_id"], question["target_digest"], "prod", command_id="answer"
            )
            assert receipt.run_id == child.ref.run_id
            completed = await root.wait(wait_timeout=1, terminal_only=True)
            assert completed.snapshot.state == "succeeded" and provider.calls == 2
            assert await root.pending() == []
            assert (
                await child.send_input(
                    question["pending_id"], question["target_digest"], "prod", command_id="answer"
                )
                == receipt
            )

    asyncio.run(run())
