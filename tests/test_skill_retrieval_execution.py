"""Six original compositions discover permitted metadata before native skill_get."""

import asyncio
import json

import pytest

import relf_agent as r
from relf_agent.binding_definitions import decode_definition
from relf_agent.retrieval import KnowledgeContext

from .test_skill_binding_execution import definition as original_definition
from .test_workspace_binding_execution import finish


def definition(kind):
    def change(value):
        if isinstance(value, list):
            return [change(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: change(item) for key, item in value.items()}
        if "skills" in result and result["skills"].get("mode") == "ref":
            result["knowledge"] = dict(result["skills"])
        return result

    return decode_definition(change(original_definition(kind).to_dict()))


class DiscoveryReader:
    identity = {"kind": "skill-directory-first-reader", "version": "1"}

    def __init__(self):
        self.discovered = []

    async def complete(self, messages, tools):
        evidence = [
            json.loads(message["content"]) for message in messages if message["role"] == "tool"
        ]
        if evidence:
            return r.ModelResponse(output=evidence[-1])
        tool = next(
            item["function"]["name"]
            for item in tools
            if item["function"]["name"].endswith("skill_get")
        )
        expected = tool.split("_", 1)[0]
        metadata = []
        for message in messages:
            text = message.get("content", "")
            if not isinstance(text, str) or "skill-directory" not in text:
                continue
            value = json.loads(text.split("\n", 1)[1])
            metadata.extend(
                item["value"]["metadata"]
                for item in value
                if item.get("value", {}).get("metadata", {}).get("reference_kind")
                == "skill-directory"
            )
        assert len(metadata) == 1 and metadata[0]["description"] == expected + " help reference"
        assert metadata[0]["permissions"] == "none" and "instructions" not in metadata[0]
        self.discovered.append(expected)
        return r.ModelResponse(tool_calls=[r.ToolCall(tool, {"name": "help"}, "get")])


@pytest.fixture
def host():
    registry, bindings, catalogs, sources = (
        r.ToolRegistry(),
        r.BindingCatalog(scope=r.Scope()),
        [],
        [],
    )
    observed = []

    class Catalog(r.InMemorySkillCatalog):
        def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            self.observed.append(value["skill"]["instructions"])
            return value

    async def build():
        for name in ("alpha", "beta"):
            catalog = Catalog([r.SkillSpec("help", name + " help reference", name)], version="1")
            catalog.observed = observed
            catalogs.append(catalog)
            source = r.SkillToolSource(catalog, version="1")
            sources.append(source)
            await r.register_tool_source(
                registry,
                source,
                prefix=name + "_",
                policies={
                    "skill_get": r.ToolPolicy("1", effect="read_only", requires_approval=True)
                },
            )
            bindings.register(
                "skills", name, "1", r.SkillBindingResource(registry, names=[name + "_skill_get"])
            )
            context = KnowledgeContext(
                r.SkillDirectoryRetriever(catalog, version="1"), namespace="skills"
            )
            bindings.register(
                "knowledge",
                name,
                "1",
                r.KnowledgeBindingResource(
                    context, namespaces=["skills"], default_namespace="skills"
                ),
            )

    asyncio.run(build())
    registry.register(
        r.ToolSpec("business", "Business", {"type": "object"}), lambda args, context: "business"
    )
    yield registry, bindings, observed
    for source in sources:
        asyncio.run(source.aclose())
    for catalog in catalogs:
        catalog.close()


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_local_discovery_then_approval_restart_and_original_selected_body(tmp_path, host, kind):
    tools, bindings, observed = host
    reader = DiscoveryReader()
    path = tmp_path / "runs.sqlite"
    with r.LocalEngine(
        r.SQLiteStore(path), providers={"default": reader}, tools=tools, binding_catalog=bindings
    ) as engine:
        handle = engine.submit(definition(kind), "help", command_id="same", budget=64)
        waiting = asyncio.run(engine.drive(handle.run_id))
        assert waiting.state == "waiting_approval" and reader.discovered and observed == []
    with r.LocalEngine(
        r.SQLiteStore(path), providers={"default": reader}, tools=tools, binding_catalog=bindings
    ) as engine:
        assert engine.submit(definition(kind), "help", command_id="same", budget=64) == handle
        done = asyncio.run(finish(engine, handle.run_id))
        assert done.state == "succeeded"
        assert asyncio.run(engine.drive(handle.run_id)).result == done.result
    expected = ["alpha"] if kind == "agent" else ["alpha", "beta"]
    assert sorted(reader.discovered) == expected and sorted(observed) == expected


def test_directory_discovery_never_grants_skill_get_or_business_tools(tmp_path):
    catalog = r.InMemorySkillCatalog(
        [r.SkillSpec("help", "help reference", "private body")], version="1"
    )

    class Names:
        identity = {"kind": "passive-discovery-only", "version": "1"}

        async def complete(self, messages, tools):
            assert tools == []
            assert "skill-directory" in str(messages) and "private body" not in str(messages)
            return r.ModelResponse(output="directory only")

    try:
        with r.LocalEngine(
            r.SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": Names()},
            tools=r.ToolRegistry(),
            knowledge=KnowledgeContext(
                r.SkillDirectoryRetriever(catalog, version="1"), namespace="skills"
            ),
        ) as engine:
            handle = engine.submit(r.AgentSpec("reader", "read"), "help", command_id="same")
            assert asyncio.run(engine.drive(handle.run_id)).result == "directory only"
    finally:
        catalog.close()


def test_file_directory_change_after_snapshot_refuses_before_model(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    (root / "help.md").write_text("private body")
    (root / "skills.json").write_text(
        json.dumps(
            {
                "version": "1",
                "skills": [
                    {
                        "name": "help",
                        "description": "help reference",
                        "version": "1",
                        "path": "help.md",
                    }
                ],
            }
        )
    )

    class Changed(r.FileSystemSkillCatalog):
        def list(self, *args, **kwargs):
            value = super().list(*args, **kwargs)
            self.body_path.write_text("changed body")
            return value

    class Never:
        identity = {"kind": "source-invalid-never-model", "version": "1"}

        def __init__(self):
            self.calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            raise AssertionError("invalid directory evidence must not reach model")

    catalog = Changed(root, version="1")
    catalog.body_path = root / "help.md"
    provider = Never()
    try:
        with r.LocalEngine(
            r.SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": provider},
            tools=r.ToolRegistry(),
            knowledge=KnowledgeContext(
                r.SkillDirectoryRetriever(catalog, version="1"), namespace="skills"
            ),
        ) as engine:
            handle = engine.submit(r.AgentSpec("reader", "read"), "help", command_id="same")
            done = asyncio.run(engine.drive(handle.run_id))
            assert done.state == "failed", done
            assert provider.calls == 0
    finally:
        catalog.close()
