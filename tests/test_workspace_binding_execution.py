"""Actual Local members keep their root-selected original read Actions and receipts."""

import asyncio
import json

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    InMemoryWorkspace,
    LocalEngine,
    ModelResponse,
    Scope,
    SQLiteStore,
    TeamSpec,
    ToolCall,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
    WorkspaceBindingResource,
    WorkspaceToolSource,
    register_tool_source,
)
from ralf_agent.errors import DefinitionMismatch


class Reader:
    identity = {"kind": "bound-workspace-reader", "version": "1"}

    async def complete(self, messages, tools):
        evidence = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if evidence:
            return ModelResponse(output=evidence[-1])
        names = [t["function"]["name"] for t in tools]
        name = next((n for n in names if n.endswith("workspace_read_text")), None)
        if name is None:
            return ModelResponse(output={"available": names})
        return ModelResponse(tool_calls=[ToolCall(name, {"path": "note"}, call_id="read")])


@pytest.fixture
def workspace_host():
    observed, registry, sources = [], ToolRegistry(), []

    class Tracked(InMemoryWorkspace):
        def read_text(self, scope, path, *, max_bytes=1048576):
            result = super().read_text(scope, path, max_bytes=max_bytes)
            observed.append(result["text"])
            return result

    async def build():
        for root in ("alpha", "beta"):
            source = WorkspaceToolSource(Tracked({"note": root}, version=root), version="1")
            sources.append(source)
            await register_tool_source(
                registry,
                source,
                prefix=root + "_",
                policies={
                    "workspace_read_text": ToolPolicy(
                        "1", effect="read_only", requires_approval=True
                    )
                },
            )

    asyncio.run(build())
    registry.register(ToolSpec("business", "Business", {"type": "object"}), lambda a, c: "business")
    catalog = BindingCatalog(scope=Scope())
    for root in ("alpha", "beta"):
        catalog.register(
            "workspace",
            root,
            "1",
            WorkspaceBindingResource(registry, names=[root + "_workspace_read_text"]),
        )
    yield registry, catalog, observed
    for source in sources:
        asyncio.run(source.aclose())


def descriptor(root):
    return AgentBindingDescriptor(
        workspace=BindingSelection.ref(root, "1"), session=BindingSelection.disabled()
    )


def agent(name="worker"):
    return AgentSpec(
        name,
        "Read the selected note",
        tools=("alpha_workspace_read_text", "beta_workspace_read_text", "business"),
    )


def definition(kind):
    if kind == "agent":
        return AgentDefinition(agent(), descriptor("alpha"))
    if kind == "sequence":
        return BoundDefinition(
            WorkflowSpec("sequence", [agent("alpha"), agent("beta")]),
            {"sequence/steps/0": descriptor("alpha"), "sequence/steps/1": descriptor("beta")},
        )
    if kind == "graph":
        return BoundDefinition(
            GraphWorkflowSpec(
                "graph",
                [GraphNode(root, agent=agent(root)) for root in ("alpha", "beta")],
                max_concurrency=2,
            ),
            {f"graph/nodes/{root}": descriptor(root) for root in ("alpha", "beta")},
        )
    if kind == "nested":
        return BoundDefinition(
            TeamSpec("nested", {"group": WorkflowSpec("group", [agent("alpha"), agent("beta")])}),
            {
                "team/members/group/sequence/steps/0": descriptor("alpha"),
                "team/members/group/sequence/steps/1": descriptor("beta"),
            },
        )
    flow = (
        TeamSpec("team", {r: agent(r) for r in ("alpha", "beta")})
        if kind == "team"
        else DynamicWorkflowSpec(
            "dynamic", {r: agent(r) for r in ("alpha", "beta")}, plan_mode="dag"
        )
    )
    return BoundDefinition(flow, {f"{kind}/members/{r}": descriptor(r) for r in ("alpha", "beta")})


def engine(path, registry, catalog, provider=None):
    return LocalEngine(
        SQLiteStore(path),
        providers={"default": provider or Reader()},
        tools=registry,
        binding_catalog=catalog,
    )


async def finish(runtime, run_id):
    def approve_pending(current):
        for pending in runtime.status(current).pending:
            runtime.approve(
                current,
                pending["action_id"],
                pending["digest"],
                command_id="approve-" + pending["action_id"],
            )
        for child in (runtime.diagnostics(current).workflow or {}).get("children", []):
            approve_pending(child["run_id"])

    for _ in range(8):
        result = await runtime.drive(run_id)
        if result.state != "waiting_approval":
            return result
        approve_pending(run_id)
    raise AssertionError("member approvals did not finish")


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_actual_members_read_only_their_selected_roots(tmp_path, workspace_host, kind):
    registry, catalog, observed = workspace_host
    with engine(tmp_path / (kind + ".sqlite"), registry, catalog) as runtime:
        handle = runtime.submit(definition(kind), "read note", command_id="submit")
        done = asyncio.run(finish(runtime, handle.run_id))
        assert done.state == "succeeded", done.error
        assert sorted(observed) == (["alpha"] if kind == "agent" else ["alpha", "beta"])
        if kind == "agent":
            assert done.result["text"] == "alpha"
        elif kind == "graph":
            assert done.result["alpha"]["text"] == "alpha" and done.result["beta"]["text"] == "beta"
        else:
            assert done.result["text"] == "beta"
        assert runtime.diagnostics(handle.run_id).manifest["kernel"] == "local-bindings-11"


def test_disabled_workspace_keeps_actual_business_grant(tmp_path, workspace_host):
    registry, catalog, observed = workspace_host
    wrapped = AgentDefinition(
        agent(), AgentBindingDescriptor(workspace=BindingSelection.disabled())
    )
    with engine(tmp_path / "disabled.sqlite", registry, catalog) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="submit")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded" and done.result == {"available": ["business"]}
        assert observed == []


def test_excluded_root_proposal_is_refused_without_read(tmp_path, workspace_host):
    registry, catalog, observed = workspace_host

    class WrongRoot(Reader):
        identity = {"kind": "excluded-root-reader", "version": "1"}

        async def complete(self, messages, tools):
            assert [t["function"]["name"] for t in tools] == [
                "alpha_workspace_read_text",
                "business",
            ]
            return ModelResponse(
                tool_calls=[ToolCall("beta_workspace_read_text", {"path": "note"})]
            )

    with engine(tmp_path / "excluded.sqlite", registry, catalog, WrongRoot()) as runtime:
        handle = runtime.submit(definition("agent"), "q", command_id="submit")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "failed" and observed == []


def test_tool_set_intersection_cannot_be_expanded_by_workspace(tmp_path, workspace_host):
    registry, catalog, observed = workspace_host
    catalog.register("tool_set", "beta-only", "1", ["beta_workspace_read_text", "business"])
    wrapped = AgentDefinition(
        agent(),
        AgentBindingDescriptor(
            workspace=BindingSelection.ref("alpha", "1"),
            tool_set=BindingSelection.ref("beta-only", "1"),
        ),
    )
    with engine(tmp_path / "intersection.sqlite", registry, catalog) as runtime:
        from ralf_agent.errors import AuthorizationDenied

        with pytest.raises(AuthorizationDenied):
            runtime.submit(wrapped, "q", command_id="submit")
        assert observed == []


def test_approval_restart_keeps_original_binding_and_read_receipt(tmp_path, workspace_host):
    registry, catalog, observed = workspace_host
    path = tmp_path / "restart.sqlite"
    wrapped = definition("agent")
    with engine(path, registry, catalog) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="submit")
        waiting = asyncio.run(runtime.drive(handle.run_id))
        assert waiting.state == "waiting_approval" and not observed
        pending = waiting.pending[0]
        original = runtime.diagnostics(handle.run_id).manifest
    with engine(path, registry, catalog) as runtime:
        assert runtime.submit(wrapped, "q", command_id="submit") == handle
        receipt = runtime.approve(
            handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
        )
        assert (
            runtime.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            == receipt
        )
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded" and done.result["text"] == "alpha"
        assert runtime.diagnostics(handle.run_id).manifest == original
    with engine(path, registry, catalog) as runtime:
        assert asyncio.run(runtime.drive(handle.run_id)) == done
    assert observed == ["alpha"]


def test_restarting_with_another_root_under_same_binding_name_fails(tmp_path, workspace_host):
    registry, catalog, observed = workspace_host
    path = tmp_path / "drift.sqlite"
    with engine(path, registry, catalog) as runtime:
        handle = runtime.submit(definition("agent"), "q", command_id="submit")
        assert asyncio.run(runtime.drive(handle.run_id)).state == "waiting_approval"
    replacement = BindingCatalog(scope=Scope())
    replacement.register(
        "workspace",
        "alpha",
        "1",
        WorkspaceBindingResource(registry, names=["beta_workspace_read_text"]),
    )
    with engine(path, registry, replacement) as runtime:
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(handle.run_id))
        assert runtime.status(handle.run_id).state == "waiting_approval"
        assert observed == []
