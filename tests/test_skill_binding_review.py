"""Whole-batch review regressions preserve legacy grants and native provenance."""

import asyncio
from dataclasses import replace

import pytest

import relf_agent as r
from relf_agent.errors import RalfError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_bindings import effective_step, normalize_request
from relf_agent.types import submission_request

from .test_skill_bindings import registered as registered


@pytest.mark.parametrize("backend", ["local", "temporal"])
@pytest.mark.parametrize("mode", ["ref", "disabled"])
@pytest.mark.parametrize("combined", [False, True])
def test_unrelated_tuple_config_remains_legal_under_skill_selection(
    tmp_path, registered, backend, mode, combined
):
    registry, _ = registered
    registry.register(
        r.ToolSpec(
            "tuple_business", "Business", {"type": "object"}, config={"formats": ("json", "text")}
        ),
        lambda a, c: "ok",
    )
    catalog = r.BindingCatalog(scope=r.Scope())
    catalog.register("skills", "a", "1", r.SkillBindingResource(registry, names=["a_skill_get"]))
    names = ["tuple_business", "a_skill_get"]
    options = {
        "skills": r.BindingSelection.ref("a", "1")
        if mode == "ref"
        else r.BindingSelection.disabled()
    }
    workspace = None
    source = None
    if combined:
        workspace = r.InMemoryWorkspace({"note": "Original"}, version="1")
        source = r.WorkspaceToolSource(workspace, version="1")

        async def register():
            await r.register_tool_source(
                registry,
                source,
                policies={"workspace_read_text": r.ToolPolicy("1", effect="read_only")},
            )

        asyncio.run(register())
        names.append("workspace_read_text")
        catalog.register(
            "workspace",
            "files",
            "1",
            r.WorkspaceBindingResource(registry, names=["workspace_read_text"]),
        )
        catalog.register("tool_set", "both", "1", names)
        options.update(
            workspace=r.BindingSelection.ref("files", "1"),
            tool_set=r.BindingSelection.ref("both", "1"),
        )
    descriptor = r.AgentBindingDescriptor(**options)
    spec = r.AgentSpec("reader", "Names", tools=names)
    expected = [name for name in names if mode != "disabled" or name != "a_skill_get"]

    class Provider:
        identity = {"kind": "legacy-tuple-business", "version": "1"}

        async def complete(self, messages, tools):
            return r.ModelResponse(output=[t["function"]["name"] for t in tools])

    try:
        if backend == "local":
            with r.LocalEngine(
                r.SQLiteStore(tmp_path / "runs.sqlite"),
                providers={"default": Provider()},
                tools=registry,
                binding_catalog=catalog,
            ) as engine:
                handle = engine.submit(r.AgentDefinition(spec, descriptor), "q", command_id="same")
                assert asyncio.run(engine.drive(handle.run_id)).result == expected
        else:
            runtime = TemporalRuntime(
                providers={"default": Provider()}, tools=registry, binding_catalog=catalog
            )
            request = normalize_request(
                submission_request(r.AgentDefinition(spec, descriptor), "q")
            )
            assert (
                effective_step(
                    request["definition"]["steps"][0],
                    runtime.manifest,
                    request["agent_bindings"]["agent"],
                )["tools"]
                == expected
            )
    finally:
        if source is not None:
            asyncio.run(source.aclose())
            workspace.close()


@pytest.mark.parametrize("change", ["genuine_alias", "handler", "reconciler"])
def test_native_registration_provenance_and_actual_reconciler(registered, change):
    registry, _ = registered
    native = registry.get("a_skill_get")

    def business(arguments, context):
        raise AssertionError("provenance validation cannot execute handlers")

    def reconcile(arguments, context):
        raise AssertionError("provenance validation cannot execute reconcilers")

    registry.register(
        replace(native.spec, name="alias"),
        business if change == "handler" else native.handler,
        reconciler=reconcile if change == "reconciler" else None,
    )
    if change == "genuine_alias":
        resource = r.SkillBindingResource(registry, names=["alias"])
        assert resource.identity["tools"]["alias"]["name"] == "alias"
    else:
        with pytest.raises(RalfError):
            r.SkillBindingResource(registry, names=["alias"])
