"""Fixed HTTP declarations, original approval/effects and async ownership."""

import asyncio
import copy
import json
import sqlite3

import pytest

from ralf_agent import (
    ComponentRegistry,
    GraphNode,
    GraphWorkflowSpec,
    RuntimeBuilder,
    RuntimeProfile,
    ValueRef,
)
from ralf_agent.errors import ValidationError

from .http_tool_fixture import endpoint
from .test_cli_tools import descriptor


def config(url):
    return {
        "tools": [
            {
                "descriptor": descriptor().to_dict(),
                "url": url,
                "version": "fixture-v1",
                "prefix": "http_",
                "policy": {"version": "1", "effect": "read_only", "requires_approval": False},
            }
        ]
    }


def profile(url):
    return RuntimeProfile(
        "http",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "http-json", "config": config(url)}},
    )


def test_async_http_declaration_executes_original_managed_action(tmp_path):
    with endpoint() as (url, calls, _, _):

        async def run():
            async with await RuntimeBuilder().abuild(
                profile(url + "/normal"), tmp_path / "runs.sqlite"
            ) as runtime:
                assert not calls
                flow = GraphWorkflowSpec(
                    "http-read", [GraphNode("read", tool="http_read")], output=ValueRef("read")
                )
                handle = runtime.submit(flow, {"value": 7}, command_id="same")
                done = await runtime.drive(handle.run_id)
                assert done.state == "succeeded" and done.result == {"value": 7}
                assert runtime.submit(flow, {"value": 7}, command_id="same") == handle
                assert (await runtime.drive(handle.run_id)).result == {"value": 7}

        asyncio.run(run())
        assert len(calls) == 1


def test_sync_http_declaration_refuses_before_allocation(tmp_path):
    with pytest.raises(ValidationError, match="abuild"):
        RuntimeBuilder().build(profile("http://127.0.0.1/fixed"), tmp_path / "runs.sqlite")
    assert not (tmp_path / "runs.sqlite").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        {"unknown": 1},
        {"url": "file:///tmp/x"},
        {"headers": {"Host": "different"}},
        {"policy": {"version": "1", "effect": "queryable_write"}},
        {"timeout": True},
        {"max_output_bytes": 0},
        {"descriptor": {"name": "missing"}},
        {"prefix": 42},
        {"version": ""},
    ],
)
def test_http_bad_declarations_refuse_before_allocation(tmp_path, mutation):
    declared = config("http://127.0.0.1/fixed")
    declared["tools"][0].update(copy.deepcopy(mutation))
    with pytest.raises(ValidationError):
        ComponentRegistry().prepare("tools", {"adapter": "http-json", "config": declared})
    assert not (tmp_path / "runs.sqlite").exists()


def test_duplicate_http_tool_names_refuse_purely():
    declared = config("http://127.0.0.1/fixed")
    declared["tools"].append(copy.deepcopy(declared["tools"][0]))
    with pytest.raises(ValidationError):
        ComponentRegistry().prepare("tools", {"adapter": "http-json", "config": declared})


def write_config(url, *, effect="idempotent_write"):
    declared = config(url)
    tool = declared["tools"][0]
    tool["descriptor"] = {
        "name": "write",
        "description": "Write once",
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": "integer"}, "effect_key": {"type": "string"}},
            "required": ["value", "effect_key"],
            "additionalProperties": False,
        },
        "output_schema": {"type": "object"},
    }
    tool["policy"] = {
        "version": "1",
        "effect": effect,
        "requires_approval": True,
        "effect_key_argument": "effect_key",
    }
    return declared


@pytest.mark.parametrize("effect", ["idempotent_write", "unqueryable_write"])
def test_committed_write_with_lost_response_retains_original_effect_protocol(tmp_path, effect):
    with endpoint(tmp_path) as (url, calls, _, _):
        selected = RuntimeProfile(
            "http-write",
            "1",
            {"default": {"adapter": "offline-echo"}},
            {
                "tools": {
                    "adapter": "http-json",
                    "config": write_config(url + "/write-lost", effect=effect),
                }
            },
        )
        flow = GraphWorkflowSpec(
            "write", [GraphNode("write", tool="http_write")], output=ValueRef("write")
        )

        async def run():
            async with await RuntimeBuilder().abuild(selected, tmp_path / "runs.sqlite") as runtime:
                handle = runtime.submit(flow, {"value": 7}, command_id="same")
                status = await runtime.drive(handle.run_id)
                assert status.state == "waiting_approval" and not calls
                pending = status.pending[0]
                receipt = runtime.approve(
                    handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
                )
                assert (
                    runtime.approve(
                        handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
                    )
                    == receipt
                )
                assert (await runtime.drive(handle.run_id)).state == "waiting_reconciliation"
            assert len(calls) == 1
            async with await RuntimeBuilder().abuild(selected, tmp_path / "runs.sqlite") as runtime:
                assert runtime.submit(flow, {"value": 7}, command_id="same") == handle
                status = await runtime.drive(handle.run_id)
                if effect == "idempotent_write":
                    assert status.state == "succeeded" and status.result["value"] == 7
                    assert len(calls) == 2
                    assert (
                        json.loads(calls[0]["body"])["effect_key"]
                        == json.loads(calls[1]["body"])["effect_key"]
                    )
                else:
                    assert status.state == "waiting_reconciliation" and len(calls) == 1

        asyncio.run(run())
        with sqlite3.connect(tmp_path / "business.sqlite") as connection:
            assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == 1


def test_partial_http_factory_failure_drains_every_owned_source(tmp_path, monkeypatch):
    from ralf_agent import RuntimeBuildError, ToolSourceError, http_tool_factories

    sources = []
    original = http_tool_factories.register_tool_source

    async def fail_second(registry, source, **options):
        sources.append(source)
        if len(sources) == 2:
            raise RuntimeError("fixture-registration-failure")
        return await original(registry, source, **options)

    monkeypatch.setattr(http_tool_factories, "register_tool_source", fail_second)
    declared = config("http://127.0.0.1/fixed")
    declared["tools"].append({**copy.deepcopy(declared["tools"][0]), "prefix": "other_"})
    selected = RuntimeProfile(
        "partial-http",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "http-json", "config": declared}},
    )

    async def run():
        with pytest.raises(RuntimeBuildError):
            await RuntimeBuilder().abuild(selected, tmp_path / "runs.sqlite")
        assert len(sources) == 2
        for source in sources:
            with pytest.raises(ToolSourceError):
                await source.list_tools()

    asyncio.run(run())


@pytest.mark.parametrize("url", ["http://[v1.private-endpoint]/", "http://☃.com/"])
def test_httpx_rejected_url_refuses_before_runtime_store_allocation(tmp_path, url):
    selected = profile(url)
    with pytest.raises(ValidationError):
        ComponentRegistry().prepare("tools", {"adapter": "http-json", "config": config(url)})

    async def run():
        with pytest.raises(ValidationError):
            await RuntimeBuilder().abuild(selected, tmp_path / "runs.sqlite")

    asyncio.run(run())
    assert not (tmp_path / "runs.sqlite").exists()
