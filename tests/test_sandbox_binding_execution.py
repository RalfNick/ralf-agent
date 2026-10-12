"""Six original Local compositions select catalog roles and recover managed reads."""

import asyncio
import json

import pytest

import ralf_agent as r
from ralf_agent.binding_definitions import decode_definition

from .test_workspace_binding_execution import definition as original_definition
from .test_workspace_binding_execution import finish


class Reader:
    identity = {"kind": "sandbox-reference-reader", "version": "1"}

    async def complete(self, messages, tools):
        evidence = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if evidence:
            return r.ModelResponse(output=evidence[-1])
        names = [t["function"]["name"] for t in tools]
        name = next(n for n in names if n.endswith("sandbox_run"))
        return r.ModelResponse(
            tool_calls=[r.ToolCall(name, {"argv": ["/bin/echo", name.split("_")[0]]}, "get")]
        )


def definition(kind):
    def transform(value):
        if isinstance(value, dict):
            return {
                "sandbox" if key == "workspace" else key: "Run the permitted ephemeral command"
                if key == "instructions"
                else transform(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [transform(item) for item in value]
        return (
            value.replace("workspace_read_text", "sandbox_run") if isinstance(value, str) else value
        )

    return decode_definition(transform(original_definition(kind).to_dict()))


@pytest.fixture
def host():
    observed, registry, sources, catalogs = [], r.ToolRegistry(), [], []

    from .test_sandbox_tools import Provider

    class Tracked(Provider):
        async def run(self, scope, request, *, invocation_id):
            value = await super().run(scope, request, invocation_id=invocation_id)
            observed.append(request.argv[-1])
            return value

    async def build():
        for root in ("alpha", "beta"):
            port = Tracked()
            port.identity = {**port.identity, "host": root}
            catalogs.append(port)
            source = r.SandboxToolSource(port, version="1")
            sources.append(source)
            await r.register_tool_source(
                registry,
                source,
                prefix=root + "_",
                policies={
                    "sandbox_run": r.ToolPolicy("1", effect="read_only", requires_approval=True)
                },
            )

    asyncio.run(build())
    registry.register(
        r.ToolSpec("business", "Business", {"type": "object"}), lambda a, c: "business"
    )
    bindings = r.BindingCatalog(scope=r.Scope())
    for root in ("alpha", "beta"):
        bindings.register(
            "sandbox", root, "1", r.SandboxBindingResource(registry, names=[root + "_sandbox_run"])
        )
    yield registry, bindings, observed
    for source in sources:
        asyncio.run(source.aclose())
    for catalog in catalogs:
        assert not catalog.closed


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_original_members_recover_approval_and_use_their_selected_ports(tmp_path, host, kind):
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
        assert engine.diagnostics(handle.run_id).manifest["kernel"] == "local-bindings-14"
        assert asyncio.run(engine.drive(handle.run_id)).result == saved
    assert sorted(observed) == (["alpha"] if kind == "agent" else ["alpha", "beta"])


def test_disabled_sandbox_and_tool_set_intersection_preserves_business(tmp_path, host):
    registry, bindings, observed = host
    bindings.register("tool_set", "subset", "1", ["alpha_sandbox_run", "business"])

    class Names:
        identity = {"kind": "sandbox-disabled-reader", "version": "1"}

        async def complete(self, messages, tools):
            return r.ModelResponse(output=[t["function"]["name"] for t in tools])

    spec = r.AgentDefinition(
        r.AgentSpec("reader", "Names", tools=("alpha_sandbox_run", "beta_sandbox_run", "business")),
        r.AgentBindingDescriptor(
            sandbox=r.BindingSelection.disabled(), tool_set=r.BindingSelection.ref("subset", "1")
        ),
    )
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": Names()},
        tools=registry,
        binding_catalog=bindings,
    ) as engine:
        handle = engine.submit(spec, "q", command_id="same")
        assert asyncio.run(engine.drive(handle.run_id)).result == ["business"]
    assert observed == []


@pytest.mark.parametrize(
    "selector,grants", [({"name": "help"}, ("alpha_sandbox_run",)), ({}, ("beta_sandbox_run",))]
)
def test_unsupported_selector_and_no_original_match_reject_before_model(
    tmp_path, host, selector, grants
):
    registry, bindings, observed = host
    from ralf_agent.errors import RalfError

    calls = []

    class Provider:
        identity = {"kind": "must-not-run", "version": "1"}

        async def complete(self, messages, tools):
            calls.append(True)
            return r.ModelResponse(output="bad")

    spec = r.AgentDefinition(
        r.AgentSpec("reader", "Names", tools=grants),
        r.AgentBindingDescriptor(sandbox=r.BindingSelection.ref("alpha", "1", selector=selector)),
    )
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": Provider()},
        tools=registry,
        binding_catalog=bindings,
    ) as engine:
        with pytest.raises(RalfError):
            engine.submit(spec, "q", command_id="same")
    assert calls == [] and observed == []


def test_sandbox_workspace_tool_set_intersect_independently(tmp_path, host):
    registry, bindings, observed = host
    workspace = r.InMemoryWorkspace({"note": "Original"}, version="1")
    source = r.WorkspaceToolSource(workspace, version="1")

    async def build():
        await r.register_tool_source(
            registry,
            source,
            policies={"workspace_read_text": r.ToolPolicy("1", effect="read_only")},
        )

    asyncio.run(build())
    bindings.register(
        "workspace",
        "files",
        "1",
        r.WorkspaceBindingResource(registry, names=["workspace_read_text"]),
    )
    bindings.register(
        "tool_set",
        "both",
        "1",
        ["alpha_sandbox_run", "beta_sandbox_run", "workspace_read_text", "business"],
    )

    class Names:
        identity = {"kind": "combined-sandbox-reader", "version": "1"}

        async def complete(self, messages, tools):
            return r.ModelResponse(output=[t["function"]["name"] for t in tools])

    selections = r.AgentBindingDescriptor(
        sandbox=r.BindingSelection.ref("alpha", "1"),
        workspace=r.BindingSelection.ref("files", "1"),
        tool_set=r.BindingSelection.ref("both", "1"),
    )
    spec = r.AgentDefinition(
        r.AgentSpec(
            "reader",
            "Names",
            tools=("alpha_sandbox_run", "beta_sandbox_run", "workspace_read_text", "business"),
        ),
        selections,
    )
    try:
        with r.LocalEngine(
            r.SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": Names()},
            tools=registry,
            binding_catalog=bindings,
        ) as engine:
            handle = engine.submit(spec, "q", command_id="same")
            assert asyncio.run(engine.drive(handle.run_id)).result == [
                "alpha_sandbox_run",
                "workspace_read_text",
                "business",
            ]
        assert observed == []
    finally:
        asyncio.run(source.aclose())
        workspace.close()


def test_skill_catalog_scope_cannot_be_selected_by_foreign_host(tmp_path, host):
    from contextlib import closing

    from ralf_agent.errors import ValidationError

    registry, bindings, observed = host
    with closing(r.SQLiteStore(tmp_path / "runs.sqlite")) as store:
        with pytest.raises(ValidationError, match="trusted Engine Scope"):
            r.LocalEngine(
                store,
                providers={"default": Reader()},
                tools=registry,
                binding_catalog=bindings,
                scope=r.Scope("foreign", "principal"),
            )
    assert observed == []
