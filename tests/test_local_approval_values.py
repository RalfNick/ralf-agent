"""Approval decisions are booleans at the authority, including through the facade."""

import asyncio

import pytest

from relf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    Runtime,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.errors import ValidationError

from .helpers import ScriptedProvider, tool_response


@pytest.mark.parametrize("facade", [False, True], ids=["engine", "facade"])
@pytest.mark.parametrize("decision", ["false", "true", 0, 1, None, [], {}])
def test_invalid_approval_never_records_a_decision_or_permits_a_write(tmp_path, facade, decision):
    async def run():
        writes = []
        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "change",
                "Change",
                {"type": "object"},
                effect="unqueryable_write",
                requires_approval=True,
            ),
            lambda arguments, context: writes.append(context.effect_key),
        )
        engine = LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={
                "default": ScriptedProvider(
                    [tool_response(arguments={}), ModelResponse(output="done")]
                )
            },
            tools=tools,
        )
        async with Runtime(engine, owned=True) as runtime:
            handle = await runtime.create_agent(AgentSpec("writer", "Change", ("change",))).submit(
                "q", command_id="submit"
            )
            waiting = await handle.wait(wait_timeout=1)
            target = waiting.snapshot.pending[0]
            with pytest.raises(ValidationError, match="bool"):
                if facade:
                    await handle.approve(
                        target["action_id"],
                        target["digest"],
                        command_id="decision",
                        approved=decision,
                    )
                else:
                    engine.approve(
                        handle.ref.run_id,
                        target["action_id"],
                        target["digest"],
                        command_id="decision",
                        approved=decision,
                    )
            assert (await handle.status()).state == "waiting_approval"
            assert writes == []
            # Reuse the same identity: the invalid attempt must not leave a
            # durable command that conflicts with the actual boolean decision.
            receipt = await handle.approve(
                target["action_id"],
                target["digest"],
                command_id="decision",
                approved=True,
            )
            assert receipt.apply_state == "applied"
            assert (await handle.wait(wait_timeout=1)).snapshot.state == "succeeded"
            assert len(writes) == 1

    asyncio.run(run())


@pytest.mark.parametrize("approved", [False, True])
def test_boolean_approval_retains_original_receipt_and_exact_write_count(tmp_path, approved):
    async def run():
        writes = []
        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "change",
                "Change",
                {"type": "object"},
                effect="unqueryable_write",
                requires_approval=True,
            ),
            lambda arguments, context: writes.append(context.effect_key),
        )
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={
                "default": ScriptedProvider(
                    [tool_response(arguments={}), ModelResponse(output="done")]
                )
            },
            tools=tools,
        ) as engine:
            handle = engine.submit(AgentSpec("writer", "Change", ("change",)), "q", command_id="s")
            waiting = await engine.drive(handle.run_id)
            target = waiting.pending[0]
            first = engine.approve(
                handle.run_id,
                target["action_id"],
                target["digest"],
                command_id="a",
                approved=approved,
            )
            assert (
                engine.approve(
                    handle.run_id,
                    target["action_id"],
                    target["digest"],
                    command_id="a",
                    approved=approved,
                )
                == first
            )
            result = await engine.drive(handle.run_id)
            assert result.state == ("succeeded" if approved else "failed")
            assert len(writes) == int(approved)

    asyncio.run(run())
