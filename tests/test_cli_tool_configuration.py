"""Explicit async declarations reuse owned resources and original ToolPolicy."""

import asyncio
import copy
import sys
from pathlib import Path

import pytest

from ralf_agent import (
    ComponentRegistry,
    GraphNode,
    GraphWorkflowSpec,
    RuntimeBuilder,
    RuntimeProfile,
    TemporalProfile,
    TemporalRuntimeBuilder,
    ValueRef,
)
from ralf_agent.errors import ValidationError

from .test_cli_tools import descriptor


def config(root):
    return {
        "tools": [
            {
                "descriptor": descriptor().to_dict(),
                "command": [
                    sys.executable,
                    str(Path(__file__).with_name("cli_tool_fixture.py")),
                    "normal",
                    str(root),
                ],
                "version": "fixture-v1",
                "cwd": str(root),
                "policy": {"version": "1", "effect": "read_only", "requires_approval": False},
                "prefix": "cli_",
            }
        ]
    }


def profile(root, *, temporal=False):
    cls = TemporalProfile if temporal else RuntimeProfile
    return cls(
        "cli",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "cli-json", "config": config(root)}},
    )


def test_async_local_declaration_executes_and_owns_original_sources(tmp_path):
    async def run():
        runtime = await RuntimeBuilder(base_dir=tmp_path).abuild(
            profile(tmp_path), tmp_path / "runs.sqlite"
        )
        try:
            assert not (tmp_path / "pid").exists()
            flow = GraphWorkflowSpec(
                "read", [GraphNode("read", tool="cli_read")], output=ValueRef("read")
            )
            handle = runtime.submit(flow, {"value": 7}, command_id="same")
            done = await runtime.drive(handle.run_id)
            assert done.state == "succeeded" and done.result == {"value": 7}
        finally:
            await runtime.aclose()

    asyncio.run(run())


def test_sync_assembly_refuses_before_creating_store(tmp_path):
    with pytest.raises(ValidationError, match="abuild"):
        RuntimeBuilder(base_dir=tmp_path).build(profile(tmp_path), tmp_path / "runs.sqlite")
    assert not (tmp_path / "runs.sqlite").exists() and not (tmp_path / "pid").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        {"unknown": 1},
        {"command": ["python"]},
        {"timeout": True},
        {"env": {"BAD=KEY": "value"}},
        {"policy": {"version": "1", "effect": "queryable_write"}},
        {"descriptor": {"name": "missing"}},
        {"prefix": 42},
        {"version": ""},
        {"max_output_bytes": 0},
    ],
)
def test_pure_declaration_refusal_has_no_store_or_subprocess(tmp_path, mutation):
    declared = config(tmp_path)
    declared["tools"][0].update(copy.deepcopy(mutation))
    registry = ComponentRegistry()
    with pytest.raises(ValidationError):
        registry.prepare("tools", {"adapter": "cli-json", "config": declared})
    assert not (tmp_path / "pid").exists()


def test_duplicate_local_names_are_refused_during_prepare(tmp_path):
    declared = config(tmp_path)
    declared["tools"].append(copy.deepcopy(declared["tools"][0]))
    with pytest.raises(ValidationError):
        ComponentRegistry().prepare("tools", {"adapter": "cli-json", "config": declared})
    assert not (tmp_path / "pid").exists()


def test_temporal_declares_cli_tools_without_creating_local_authority_or_process(tmp_path):
    async def run():
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(
            profile(tmp_path, temporal=True)
        )
        try:
            assert assembly.release["tools"]["cli_read"]["effect"] == "read_only"
            assert not (tmp_path / "pid").exists() and not (tmp_path / "runs.sqlite").exists()
        finally:
            await assembly.aclose()

    asyncio.run(run())


def test_partial_factory_failure_closes_every_already_owned_source(tmp_path, monkeypatch):
    from ralf_agent import RuntimeBuildError, ToolSourceError, cli_tool_factories

    discovered = []
    original = cli_tool_factories.register_tool_source

    async def fail_second(registry, source, **kwargs):
        discovered.append(source)
        if len(discovered) == 2:
            raise RuntimeError("fixture-registration-failure")
        return await original(registry, source, **kwargs)

    monkeypatch.setattr(cli_tool_factories, "register_tool_source", fail_second)
    declared = config(tmp_path)
    other = copy.deepcopy(declared["tools"][0])
    other["prefix"] = "other_"
    declared["tools"].append(other)
    selected = RuntimeProfile(
        "partial-cli",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "cli-json", "config": declared}},
    )

    async def run():
        with pytest.raises(RuntimeBuildError):
            await RuntimeBuilder(base_dir=tmp_path).abuild(selected, tmp_path / "runs.sqlite")
        assert len(discovered) == 2
        for source in discovered:
            with pytest.raises(ToolSourceError):
                await source.list_tools()
        assert not (tmp_path / "pid").exists()

    asyncio.run(run())


@pytest.mark.parametrize("effect", ["idempotent_write", "unqueryable_write"])
def test_unknown_cli_response_restarts_with_original_effect_key_and_one_write(tmp_path, effect):
    import hashlib
    import sqlite3

    from ralf_agent.cli_starter import CLI_FILES

    program = tmp_path / "business_tool.py"
    program.write_text(
        CLI_FILES["business_tool.py"]
        .replace(
            "arguments = json.load(sys.stdin)",
            'arguments = json.load(sys.stdin)\narguments.setdefault("effect_key", "opaque-effect")',
        )
        .replace(
            "print(json.dumps(result), flush=True)",
            'marker = path.parent / "lost-response"\n'
            "if not marker.exists():\n"
            "    marker.touch()\n"
            '    print("response-lost", flush=True)\n'
            "else:\n"
            "    print(json.dumps(result), flush=True)\n",
        )
    )
    schema = {
        "type": "object",
        "properties": {"value": {"type": "integer"}, "effect_key": {"type": "string"}},
        "required": ["value", "effect_key"],
        "additionalProperties": False,
    }
    if effect == "unqueryable_write":
        schema["properties"].pop("effect_key")
        schema["required"].remove("effect_key")
    declared = {
        "tools": [
            {
                "descriptor": {
                    "name": "write",
                    "description": "Write once",
                    "input_schema": schema,
                    "output_schema": {"type": "object"},
                },
                "command": [sys.executable, str(program), str(tmp_path / "business.sqlite")],
                "version": hashlib.sha256(program.read_bytes()).hexdigest(),
                "policy": {
                    "version": "1",
                    "effect": effect,
                    "requires_approval": True,
                    "effect_key_argument": "effect_key",
                },
            }
        ]
    }
    if effect == "unqueryable_write":
        declared["tools"][0]["policy"].pop("effect_key_argument")
    selected = RuntimeProfile(
        "lost-cli",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "cli-json", "config": declared}},
    )
    flow = GraphWorkflowSpec("write", [GraphNode("apply", tool="write")], output=ValueRef("apply"))

    async def run():
        async with await RuntimeBuilder(base_dir=tmp_path).abuild(
            selected, tmp_path / "runs.sqlite"
        ) as runtime:
            handle = runtime.submit(flow, {"value": 9}, command_id="same")
            pending = (await runtime.drive(handle.run_id)).pending[0]
            runtime.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            unknown = await runtime.drive(handle.run_id)
            assert unknown.state == "waiting_reconciliation"
        async with await RuntimeBuilder(base_dir=tmp_path).abuild(
            selected, tmp_path / "runs.sqlite"
        ) as runtime:
            done = await runtime.drive(handle.run_id)
            if effect == "idempotent_write":
                assert done.state == "succeeded" and done.result["value"] == 9
            else:
                assert done.state == "waiting_reconciliation"
            assert runtime.submit(flow, {"value": 9}, command_id="same") == handle
        with sqlite3.connect(tmp_path / "business.sqlite") as connection:
            rows = connection.execute("SELECT effect_key FROM effects").fetchall()
        assert len(rows) == 1
        if effect == "idempotent_write":
            assert rows[0][0] == done.result["effect_key"]
        assert (tmp_path / "call-audit").read_text().splitlines() == (
            ["call", "call"] if effect == "idempotent_write" else ["call"]
        )

    asyncio.run(run())
