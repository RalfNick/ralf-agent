"""Real native adapter groups survive original composite execution and approvals.

MockTransport proves HTTP protocol and runtime integration, never model quality.
"""

import asyncio
import copy
import json
from collections import Counter

import httpx
import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    Scope,
    SQLiteStore,
    TeamSpec,
    ToolRegistry,
)
from ralf_agent.artifacts import InMemoryArtifactStore
from ralf_agent.data_context import ManagedDataContext
from ralf_agent.gemini_functions import GeminiFunctionProvider
from ralf_agent.types import digest


def native_content(label):
    return {
        "role": "model",
        "parts": [
            {"text": "private thought", "thought": True, "thoughtSignature": "cHJpdmF0ZQ=="},
            {"text": "Checking " + label},
            {
                "functionCall": {"name": "change", "args": {"value": 7}, "id": "native-" + label},
                "thoughtSignature": "c2lnbmVkLWNhbGw=",
            },
        ],
    }


def candidate(content):
    return {
        "candidates": [{"content": content, "finishReason": "STOP"}],
        "usageMetadata": {
            "promptTokenCount": 3,
            "candidatesTokenCount": 4,
            "thoughtsTokenCount": 2,
        },
    }


def declaration(kind):
    members = {
        name: AgentSpec(
            name, "Apply a change using evidence.", tools=("change",), max_context_chars=4096
        )
        for name in ("first", "second")
    }
    if kind in {"graph", "nested"}:
        graph = GraphWorkflowSpec(
            "graph",
            [
                GraphNode("first", agent=members["first"]),
                GraphNode("second", agent=members["second"], depends_on=["first"]),
            ],
        )
        if kind == "graph":
            definition, prefix = graph, "graph/nodes/"
        else:
            definition, prefix = (
                TeamSpec("outer", {"nested": graph}, child_budget=16),
                "team/members/nested/graph/nodes/",
            )
    elif kind == "team":
        definition, prefix = TeamSpec("team", members), "team/members/"
    else:
        definition, prefix = (
            DynamicWorkflowSpec("plan", members, plan_mode="dag"),
            "dynamic/members/",
        )
    return BoundDefinition(
        definition,
        {
            prefix + name: AgentBindingDescriptor(
                provider=BindingSelection.ref(name, "1"),
                context=BindingSelection.ref("managed", "1"),
            )
            for name in members
        },
    )


def records(engine, run_id):
    record = engine.store.run(run_id)
    return [
        record,
        *[
            child
            for call in record.get("orchestration", {}).get("children", [])
            for child in records(engine, call["run_id"])
        ],
    ]


class HostProvider:
    identity = {"kind": "unselected-host", "version": "1"}

    async def complete(self, messages, tools):
        raise AssertionError("A selected Agent must never fall back to the host model")


@pytest.mark.parametrize("kind", ["graph", "team", "plan", "nested"])
@pytest.mark.parametrize("approval", [False, True])
@pytest.mark.parametrize("complete_history", [False, True])
def test_signed_native_groups_and_ids_survive_composite_approval_and_reconstruction(
    tmp_path, kind, approval, complete_history
):
    async def run():
        requests, effects, approved = [], [], {}

        def respond(request):
            label = request.url.path.split("/models/", 1)[1].split(":", 1)[0]
            body = json.loads(request.content)
            requests.append((label, copy.deepcopy(body)))
            assert (
                body["tools"][0]["functionDeclarations"][0]["parametersJsonSchema"]["properties"][
                    "flag"
                ]["type"]
                == "boolean"
            )
            replies = [
                part["functionResponse"]
                for content in body["contents"]
                for part in content["parts"]
                if "functionResponse" in part
            ]
            if not replies:
                return httpx.Response(200, json=candidate(native_content(label)))
            assert replies == [
                {"name": "change", "id": "native-" + label, "response": {"value": 7, "flag": True}}
            ]
            assert [content for content in body["contents"] if content["role"] == "model"] == [
                native_content(label)
            ]
            return httpx.Response(
                200, json=candidate({"role": "model", "parts": [{"text": "complete-" + label}]})
            )

        def change(value: int, flag: bool = True):
            effects.append({"value": value, "flag": flag})
            return {"value": value, "flag": flag}

        tools = ToolRegistry()
        tools.register_function(change, effect="unqueryable_write", requires_approval=approval)
        spec, path = declaration(kind), tmp_path / "runs.sqlite"
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:

            def open_engine():
                catalog = BindingCatalog(scope=Scope())
                for name in ("first", "second"):
                    catalog.register(
                        "provider",
                        name,
                        "1",
                        GeminiFunctionProvider(name, api_key="fixture", client=client),
                    )
                catalog.register(
                    "context",
                    "managed",
                    "1",
                    ManagedDataContext(
                        InMemoryArtifactStore(backend_id="composition-artifacts:" + kind)
                    ),
                )
                return LocalEngine(
                    SQLiteStore(path),
                    providers={"default": HostProvider()},
                    tools=tools,
                    binding_catalog=catalog,
                    model_continuation=True,
                    **(
                        {"model_history": __import__("ralf_agent").CompleteModelHistory()}
                        if complete_history
                        else {}
                    ),
                )

            with open_engine() as engine:
                handle = engine.submit(spec, "Change with care", command_id="submit", budget=32)
                outcome = await engine.drive(handle.run_id)
                original_manifest = engine.diagnostics(handle.run_id).manifest
                if approval:
                    assert outcome.state == "waiting_approval" and effects == []
                    frozen = next(
                        a["received_response"]
                        for r in records(engine, handle.run_id)
                        for a in r["actions"]
                        if a["kind"] == "model"
                    )
                    assert frozen["continuation"]["data"]["content"] == native_content("first")
                else:
                    assert outcome.state == "succeeded", outcome.error
            with open_engine() as engine:
                assert (
                    engine.submit(spec, "Change with care", command_id="submit", budget=32)
                    == handle
                )
                while engine.status(handle.run_id).state == "waiting_approval":
                    waiting = [
                        (r["id"], a)
                        for r in records(engine, handle.run_id)
                        for a in r["actions"]
                        if a["kind"] == "tool" and a["status"] == "waiting_approval"
                    ]
                    assert waiting
                    for owner, action in waiting:
                        command = "approve:" + action["id"]
                        receipt = engine.approve(
                            owner, action["id"], action["digest"], command_id=command
                        )
                        assert (
                            engine.approve(
                                owner, action["id"], action["digest"], command_id=command
                            )
                            == receipt
                        )
                        approved[command] = (owner, action["id"], action["digest"], receipt)
                    outcome = await engine.drive(handle.run_id)
                assert outcome.state == "succeeded", outcome.error
                all_records = records(engine, handle.run_id)
                models = [a for r in all_records for a in r["actions"] if a["kind"] == "model"]
                tools_evidence = [
                    a for r in all_records for a in r["actions"] if a["kind"] == "tool"
                ]
                assert len(models) == 4 and len(tools_evidence) == 2
                assert all(a["arguments"] == {"value": 7, "flag": True} for a in tools_evidence)
                assert Counter(a["call_id"] for a in tools_evidence) == {
                    "native-first": 1,
                    "native-second": 1,
                }
                signed = [a for a in models if a["received_response"]["tool_calls"]]
                for action in signed:
                    continuation = action["received_response"]["continuation"]
                    label = continuation["data"]["content"]["parts"][-1]["functionCall"][
                        "id"
                    ].removeprefix("native-")
                    assert continuation["data"]["content"] == native_content(label)
                    assert continuation["owner_digest"] == digest(
                        GeminiFunctionProvider(label, api_key="fixture", client=client).identity
                    )
                    assert action["response"]["tool_calls"][0]["arguments"] == {
                        "value": 7,
                        "flag": True,
                    }
                assert engine.diagnostics(handle.run_id).manifest == original_manifest
                assert engine.diagnostics(handle.run_id).budget == {
                    "limit": 32,
                    "held": 0,
                    "spent": 6,
                }
                assert effects == [{"value": 7, "flag": True}] * 2
                before = copy.deepcopy(requests)
                assert await engine.drive(handle.run_id) == outcome
                assert requests == before
                for command, (owner, action_id, target, receipt) in approved.items():
                    assert engine.approve(owner, action_id, target, command_id=command) == receipt
            assert Counter(label for label, _ in requests) == {"first": 2, "second": 2}
            assert not client.is_closed

    asyncio.run(run())
