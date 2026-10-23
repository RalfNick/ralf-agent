"""MCP HTTP declarations and original managed effect recovery."""

import asyncio
import copy
import sqlite3

import pytest

from relf_agent import (
    ComponentRegistry,
    GraphNode,
    GraphWorkflowSpec,
    RuntimeBuilder,
    RuntimeProfile,
    ValueRef,
)
from relf_agent.errors import ValidationError

from .mcp_http_fixture import peer
from .test_mcp_http import business_calls


def config(url, *, write=False, effect="idempotent_write"):
    policy = {
        "version": "1",
        "effect": effect if write else "read_only",
        "requires_approval": write,
    }
    if write:
        policy["effect_key_argument"] = "effect_key"
    return {
        "servers": [
            {
                "url": url,
                "version": "peer-v1",
                "prefix": "mcp_",
                "policies": {"write" if write else "read": policy},
            }
        ]
    }


def profile(url, *, write=False, effect="idempotent_write"):
    return RuntimeProfile(
        "mcp-http",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "mcp-http", "config": config(url, write=write, effect=effect)}},
    )


def test_declared_mcp_http_executes_original_graph_tool_action(tmp_path):
    with peer("sse") as (url, calls, _, _):

        async def run():
            async with await RuntimeBuilder().abuild(
                profile(url), tmp_path / "runs.sqlite"
            ) as runtime:
                assert not business_calls(calls)
                flow = GraphWorkflowSpec(
                    "read", [GraphNode("read", tool="mcp_read")], output=ValueRef("read")
                )
                handle = runtime.submit(flow, {"value": 7}, command_id="same")
                done = await runtime.drive(handle.run_id)
                assert done.state == "succeeded" and done.result["structuredContent"] == {
                    "value": 7
                }, done.error
                assert runtime.submit(flow, {"value": 7}, command_id="same") == handle
                assert (await runtime.drive(handle.run_id)).result == done.result

        asyncio.run(run())
        assert len(business_calls(calls)) == 1


def test_valid_mcp_declaration_sync_build_refuses_before_store(tmp_path):
    ComponentRegistry().prepare(
        "tools", {"adapter": "mcp-http", "config": config("http://127.0.0.1:1/mcp")}
    )
    with pytest.raises(ValidationError, match="abuild"):
        RuntimeBuilder().build(profile("http://127.0.0.1:1/mcp"), tmp_path / "runs.sqlite")
    assert not (tmp_path / "runs.sqlite").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        {"unknown": True},
        {"url": "http://[v1.private]/"},
        {"headers": {"MCP-Session-Id": "override"}},
        {"policies": {}},
        {"policies": {"read": {"version": "1", "effect": "queryable_write"}}},
        {"prefix": 1},
        {"max_operation_bytes": True},
        {"timeout": 0},
    ],
)
def test_bad_declared_mcp_refuses_purely_before_allocation(tmp_path, mutation):
    declared = config("http://127.0.0.1:1/mcp")
    declared["servers"][0].update(copy.deepcopy(mutation))
    with pytest.raises(ValidationError):
        ComponentRegistry().prepare("tools", {"adapter": "mcp-http", "config": declared})
    assert not (tmp_path / "runs.sqlite").exists()


def test_duplicate_declared_mcp_names_refuse_before_discovery():
    declared = config("http://127.0.0.1:1/mcp")
    declared["servers"].append(copy.deepcopy(declared["servers"][0]))
    with pytest.raises(ValidationError):
        ComponentRegistry().prepare("tools", {"adapter": "mcp-http", "config": declared})


@pytest.mark.parametrize("effect", ["idempotent_write", "unqueryable_write"])
def test_committed_mcp_write_lost_response_keeps_original_effect_key_and_recovery(tmp_path, effect):
    with peer("write-lost", root=tmp_path, write=True) as (url, calls, _, _):
        declared = profile(url, write=True, effect=effect)
        flow = GraphWorkflowSpec(
            "write", [GraphNode("write", tool="mcp_write")], output=ValueRef("write")
        )

        async def run():
            async with await RuntimeBuilder().abuild(declared, tmp_path / "runs.sqlite") as runtime:
                h = runtime.submit(flow, {"value": 7}, command_id="same")
                status = await runtime.drive(h.run_id)
                assert status.state == "waiting_approval" and not business_calls(calls)
                pending = status.pending[0]
                receipt = runtime.approve(
                    h.run_id, pending["action_id"], pending["digest"], command_id="approve"
                )
                assert (
                    runtime.approve(
                        h.run_id, pending["action_id"], pending["digest"], command_id="approve"
                    )
                    == receipt
                )
                assert (await runtime.drive(h.run_id)).state == "waiting_reconciliation"
            assert len(business_calls(calls)) == 1
            async with await RuntimeBuilder().abuild(declared, tmp_path / "runs.sqlite") as runtime:
                assert runtime.submit(flow, {"value": 7}, command_id="same") == h
                done = await runtime.drive(h.run_id)
                if effect == "idempotent_write":
                    assert (
                        done.state == "succeeded" and done.result["structuredContent"]["value"] == 7
                    )
                    requests = business_calls(calls)
                    assert len(requests) == 2
                    assert (
                        requests[0]["message"]["params"]["arguments"]["effect_key"]
                        == requests[1]["message"]["params"]["arguments"]["effect_key"]
                    )
                else:
                    assert (
                        done.state == "waiting_reconciliation" and len(business_calls(calls)) == 1
                    )

        asyncio.run(run())
        with sqlite3.connect(tmp_path / "business.sqlite") as connection:
            assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == 1


def test_partial_mcp_discovery_failure_closes_every_owned_transport(tmp_path, monkeypatch):
    import relf_agent.mcp_http_factories as factories
    from relf_agent import ToolSourceError

    wires = []
    original = factories.MCPHTTPTransport

    def capture(*args, **options):
        wire = original(*args, **options)
        wires.append(wire)
        return wire

    with peer() as (url, _, _, _), peer("no-tools") as (invalid, _, _, _):
        selected = config(url)
        selected["servers"].append(
            {
                "url": invalid,
                "version": "peer-v1",
                "prefix": "other_",
                "policies": {
                    "read": {"version": "1", "effect": "read_only", "requires_approval": False}
                },
            }
        )
        declared = RuntimeProfile(
            "partial",
            "1",
            {"default": {"adapter": "offline-echo"}},
            {"tools": {"adapter": "mcp-http", "config": selected}},
        )
        monkeypatch.setattr(factories, "MCPHTTPTransport", capture)

        async def run():
            with pytest.raises(ToolSourceError):
                await RuntimeBuilder().abuild(declared, tmp_path / "runs.sqlite")
            # Pure preflight constructor instances are not owned/called. Actual
            # construction instances can be identified by their closed state.
            closed = [wire for wire in wires if wire._closing]
            assert len(closed) == 2
            for wire in closed:
                with pytest.raises(ToolSourceError):
                    await wire.request("tools/list", {})

        asyncio.run(run())
