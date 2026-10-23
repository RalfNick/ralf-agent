"""Local data scopes across original managed routing, releases and recovery."""

import asyncio
import json
from contextlib import closing

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingSelection,
    BoundDefinition,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    InMemoryMemory,
    LocalEngine,
    Scope,
    SQLiteStore,
    TeamSpec,
    ToolRegistry,
    WorkflowSpec,
)
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.recall import MemoryRecallPolicy
from relf_agent.retrieval import (
    Document,
    InMemoryKnowledgeStore,
    KnowledgeContext,
    LexicalRetriever,
)
from relf_agent.types import canonical

from .test_binding_execution import RecordingProvider, bound_catalog, engine
from .test_data_binding_resources import resources


def data_catalog():
    api = resources()
    catalog = bound_catalog()
    facts = InMemoryMemory(backend_id="shared-facts")
    docs = InMemoryKnowledgeStore(backend_id="shared-docs")
    for namespace in ("red", "blue"):
        facts.put_fact(Scope(), namespace, "setting", namespace + "fact-secret", expected_version=0)
        docs.put(
            Scope(),
            namespace,
            Document("guide", "pool " + namespace + "doc-secret"),
            expected_version=0,
        )
    catalog.register(
        "facts",
        "facts",
        "1",
        api.FactsBindingResource(facts, namespaces=("red", "blue"), default_namespace="red"),
    )
    catalog.register(
        "knowledge",
        "docs",
        "1",
        api.KnowledgeBindingResource(
            KnowledgeContext(LexicalRetriever(docs)),
            namespaces=("red", "blue"),
            default_namespace="red",
        ),
    )
    return catalog


def descriptor(namespace):
    return AgentBindingDescriptor(
        facts=BindingSelection.ref("facts", "1", selector={"namespace": namespace}),
        knowledge=BindingSelection.ref("docs", "1", selector={"namespace": namespace}),
    )


def definitions(kind):
    worker = AgentSpec("worker", "Use the references")
    if kind == "native":
        return AgentDefinition(worker, descriptor("red"))
    if kind == "sequence":
        return BoundDefinition(
            WorkflowSpec("flow", [worker, worker]),
            {f"sequence/steps/{i}": descriptor(ns) for i, ns in enumerate(("red", "blue"))},
        )
    if kind == "graph":
        return BoundDefinition(
            GraphWorkflowSpec(
                "flow", [GraphNode(ns, agent=worker) for ns in ("red", "blue")], max_concurrency=2
            ),
            {f"graph/nodes/{ns}": descriptor(ns) for ns in ("red", "blue")},
        )
    if kind == "nested":
        return BoundDefinition(
            TeamSpec(
                "outer",
                {
                    "inner": GraphWorkflowSpec(
                        "inner",
                        [GraphNode(ns, agent=worker) for ns in ("red", "blue")],
                        max_concurrency=2,
                    )
                },
                child_budget=32,
            ),
            {f"team/members/inner/graph/nodes/{ns}": descriptor(ns) for ns in ("red", "blue")},
        )
    spec = (
        TeamSpec("flow", {ns: worker for ns in ("red", "blue")})
        if kind == "team"
        else DynamicWorkflowSpec("flow", {ns: worker for ns in ("red", "blue")}, plan_mode="dag")
    )
    return BoundDefinition(spec, {f"{kind}/members/{ns}": descriptor(ns) for ns in ("red", "blue")})


@pytest.mark.parametrize("kind", ["native", "sequence", "graph", "team", "dynamic", "nested"])
@pytest.mark.parametrize("paged", [False, True])
def test_shared_clients_are_scoped_through_all_local_compositions(tmp_path, kind, paged):
    catalog = data_catalog()
    with engine(
        tmp_path / "runs.sqlite", catalog, recall_policy=MemoryRecallPolicy() if paged else None
    ) as runtime:
        handle = runtime.submit(definitions(kind), "pool", command_id="s", budget=80)
        assert runtime.diagnostics(handle.run_id).manifest["kernel"] == "local-bindings-4"
        result = asyncio.run(runtime.drive(handle.run_id))
        assert result.state == "succeeded", result
        evidence = []
        for row in runtime.store.conn.execute("SELECT data FROM runs"):
            run = json.loads(row[0])
            for action in run["actions"]:
                if action["kind"] == "model":
                    evidence.extend(
                        message["content"]
                        for message in action["snapshot"]
                        if isinstance(message.get("content"), str)
                        and message["content"].startswith("Reference memory;")
                    )
        assert len(evidence) == (1 if kind == "native" else 2)
        assert any("redfact-secret" in item and "reddoc-secret" in item for item in evidence)
        if kind != "native":
            assert any("bluefact-secret" in item and "bluedoc-secret" in item for item in evidence)
        scoped = [
            canonical(
                [
                    reference
                    for reference in json.loads(item.split("\n", 1)[1])
                    if "_facts_binding" in reference or "_knowledge" in reference
                ]
            )
            for item in evidence
        ]
        assert all(not ("redfact-secret" in item and "bluefact-secret" in item) for item in scoped)


def test_scoped_data_alone_does_not_require_session_admission_and_capabilities_stay_true(tmp_path):
    with engine(tmp_path / "runs.sqlite", data_catalog()) as runtime:
        runtime.store.session_resource_owner = None
        capabilities = runtime.binding_capabilities
        assert capabilities["resource_selectors"] is True
        assert capabilities["resource_selector_roles"] == {
            "facts": ["namespace"],
            "knowledge": ["namespace"],
            "artifacts": ["namespace"],
        }
        handle = runtime.submit(definitions("native"), "pool", command_id="s")
        assert "session_resources" not in runtime.store.run(handle.run_id)
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"


def test_mixed_session_ref_keeps_canonical_admission_under_new_data_kernel(tmp_path):
    catalog = data_catalog()
    catalog.register("session", "session", "1", InMemoryMemory(backend_id="session"))
    roles = descriptor("red").to_dict()
    roles.pop("schema_version")
    roles["session"] = BindingSelection.ref("session", "1")
    agent = AgentDefinition(AgentSpec("worker", "Answer"), AgentBindingDescriptor(**roles))
    with engine(tmp_path / "runs.sqlite", catalog) as runtime:
        first = runtime.submit(agent, "pool", session_id="shared", command_id="s")
        run = runtime.store.run(first.run_id)
        assert run["manifest"]["kernel"] == "local-bindings-4"
        assert run["session_resources"] == [{"backend_id": "session", "session_id": "shared"}]
        with pytest.raises(ValidationError):
            runtime.submit(agent, "pool", session_id="shared", command_id="busy")
        runtime.store.session_resource_owner = None
        with pytest.raises(ValidationError):
            runtime.submit(agent, "pool", session_id="another", command_id="unsupported")


def test_original_scoped_receipt_replays_before_catalog_lookup_and_recovers_with_same_release(
    tmp_path,
):
    path = tmp_path / "runs.sqlite"
    catalog = data_catalog()
    agent = definitions("native")
    with engine(path, catalog) as runtime:
        handle = runtime.submit(agent, "pool", command_id="s")
        manifest = runtime.diagnostics(handle.run_id).manifest
    with engine(path, catalog) as runtime:
        catalog.unregister("facts", "facts", "1")
        assert runtime.submit(agent, "pool", command_id="s") == handle
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(handle.run_id))
    with engine(path, data_catalog()) as runtime:
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"
        assert runtime.diagnostics(handle.run_id).manifest == manifest


@pytest.mark.parametrize("role", ["facts", "knowledge"])
def test_selected_data_views_are_refused_as_host_defaults_before_acceptance(tmp_path, role):
    catalog = data_catalog()
    view, _ = catalog.resolve(role, getattr(descriptor("red"), role), Scope())
    with closing(SQLiteStore(tmp_path / "runs.sqlite")) as store:
        with pytest.raises(ValidationError):
            LocalEngine(
                store,
                providers={"default": RecordingProvider("host")},
                tools=ToolRegistry(),
                **{"memory_store" if role == "facts" else "knowledge": view},
            )
        assert store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_model_response_is_preserved_before_scoped_release_drift_refusal(tmp_path):
    catalog = data_catalog()
    original, _ = catalog._entries[("facts", "facts", "1")]

    class Provider(RecordingProvider):
        async def complete(self, messages, tools):
            result = await super().complete(messages, tools)
            original.backend.backend_id = "changed"
            return result

    with engine(tmp_path / "runs.sqlite", catalog) as runtime:
        runtime.providers["default"] = Provider("drift")
        handle = runtime.submit(definitions("native"), "pool", command_id="s")
        result = asyncio.run(runtime.drive(handle.run_id))
        assert result.state == "failed" and result.error["code"] == "definition_mismatch"
        model = runtime.store.run(handle.run_id)["actions"][0]
        assert model["status"] == "response_received" and model["received_response"]["output"]
