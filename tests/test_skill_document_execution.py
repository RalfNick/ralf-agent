"""Six original Local compositions select catalog roles and recover managed reads."""

import asyncio
import json

import pytest

import relf_agent as r
from relf_agent.binding_definitions import decode_definition

from .test_workspace_binding_execution import definition as original_definition
from .test_workspace_binding_execution import finish


class Reader:
    identity = {"kind": "skill-reference-reader", "version": "1"}

    async def complete(self, messages, tools):
        evidence = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if evidence:
            return r.ModelResponse(output=evidence[-1])
        names = [t["function"]["name"] for t in tools]
        name = next(n for n in names if n.endswith("skill_get"))
        return r.ModelResponse(tool_calls=[r.ToolCall(name, {"name": "help"}, "get")])


def definition(kind):
    def transform(value):
        if isinstance(value, dict):
            return {
                "skills" if key == "workspace" else key: "Load the permitted reference skill"
                if key == "instructions"
                else transform(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [transform(item) for item in value]
        return (
            value.replace("workspace_read_text", "skill_get") if isinstance(value, str) else value
        )

    return decode_definition(transform(original_definition(kind).to_dict()))


@pytest.fixture
def host(tmp_path):
    observed, registry, sources, catalogs = [], r.ToolRegistry(), [], []

    class Tracked(r.FileSkillDocumentCatalog):
        def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            observed.append(value["skill"]["instructions"])
            return value

    async def build():
        for root in ("alpha", "beta"):
            directory = tmp_path / root
            (directory / "help").mkdir(parents=True)
            (directory / "help/SKILL.md").write_text(
                f"---\nname: help\ndescription: Reference\nallowed-tools: forbidden_danger\n---\n{root}"
            )
            catalog = Tracked(directory, version="1", paths=["help/SKILL.md"])
            catalogs.append(catalog)
            source = r.SkillToolSource(catalog, version="1")
            sources.append(source)
            await r.register_tool_source(
                registry,
                source,
                prefix=root + "_",
                policies={
                    "skill_get": r.ToolPolicy("1", effect="read_only", requires_approval=True)
                },
            )

    asyncio.run(build())
    registry.register(
        r.ToolSpec("business", "Business", {"type": "object"}), lambda a, c: "business"
    )
    bindings = r.BindingCatalog(scope=r.Scope())
    for root in ("alpha", "beta"):
        bindings.register(
            "skills", root, "1", r.SkillBindingResource(registry, names=[root + "_skill_get"])
        )
    yield registry, bindings, observed
    for source in sources:
        asyncio.run(source.aclose())
    for catalog in catalogs:
        catalog.close()


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_original_members_recover_approval_and_read_only_their_selected_catalogs(
    tmp_path, host, kind
):
    registry, bindings, observed = host
    path = tmp_path / "runs.sqlite"
    with r.LocalEngine(
        r.SQLiteStore(path),
        providers={"default": Reader()},
        tools=registry,
        binding_catalog=bindings,
    ) as engine:
        handle = engine.submit(definition(kind), "load", command_id="same")
        waiting = asyncio.run(engine.drive(handle.run_id))
        assert waiting.state == "waiting_approval" and observed == []
    with r.LocalEngine(
        r.SQLiteStore(path),
        providers={"default": Reader()},
        tools=registry,
        binding_catalog=bindings,
    ) as engine:
        assert engine.submit(definition(kind), "load", command_id="same") == handle
        done = asyncio.run(finish(engine, handle.run_id))
        assert done.state == "succeeded"
        saved = done.result
        assert engine.diagnostics(handle.run_id).manifest["kernel"] == "local-bindings-13"
        assert asyncio.run(engine.drive(handle.run_id)).result == saved
    assert sorted(observed) == (["alpha"] if kind == "agent" else ["alpha", "beta"])
