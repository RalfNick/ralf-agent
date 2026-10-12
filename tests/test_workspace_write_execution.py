"""Source2 selections retain original Local and pure History authority."""

import asyncio
import copy
from dataclasses import asdict

import pytest

import ralf_agent as r
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import normalize_request
from ralf_agent.temporal_state import TemporalRunState, validate_manifest
from ralf_agent.types import submission_request
from ralf_agent.workspace import WorkspaceError

from .test_temporal_engine import JournalContractFixture
from .test_workspace_binding_execution import definition as read_definition
from .test_workspace_binding_execution import finish
from .test_workspace_write_configuration import Writer


def definition(kind):
    value = read_definition(kind).to_dict()

    def names(item):
        if isinstance(item, dict):
            return {
                k: "Write the permitted note" if k == "instructions" else names(v)
                for k, v in item.items()
            }
        if isinstance(item, list):
            return [names(v) for v in item]
        return (
            item.replace("workspace_read_text", "workspace_write_text")
            if isinstance(item, str)
            else item
        )

    from ralf_agent.binding_definitions import decode_definition

    return decode_definition(names(value))


@pytest.fixture
def host():
    ports, sources, registry = {}, [], r.ToolRegistry()

    async def build():
        for name in ("alpha", "beta"):
            port = ports[name] = r.InMemoryWritableWorkspace(version="1")
            source = r.WritableWorkspaceToolSource(port, version="1")
            sources.append(source)
            await r.register_tool_source(
                registry,
                source,
                prefix=name + "_",
                policies={
                    "workspace_write_text": r.ToolPolicy(
                        "1",
                        effect="idempotent_write",
                        effect_key_argument="effect_key",
                        reconciler=source.reconcile,
                    )
                },
            )

    asyncio.run(build())
    registry.register(
        r.ToolSpec("business", "Business", {"type": "object"}), lambda a, c: "business"
    )
    yield ports, registry
    for source in sources:
        asyncio.run(source.aclose())
    for port in ports.values():
        port.close()


def catalog(registry):
    result = r.BindingCatalog(scope=r.Scope())
    for name in ("alpha", "beta"):
        result.register(
            "workspace",
            name,
            "1",
            r.WorkspaceBindingResource(registry, names=[name + "_workspace_write_text"]),
        )
    return result


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_original_local_six_compositions_write_only_bound_member_roots(tmp_path, host, kind):
    ports, registry = host
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": Writer()},
        tools=registry,
        binding_catalog=catalog(registry),
    ) as engine:
        handle = engine.submit(definition(kind), "q", command_id="submit")
        done = asyncio.run(finish(engine, handle.run_id))
        assert done.state == "succeeded"
        assert ports["alpha"].read_text(r.Scope(), "note")["text"] == "A"
        if kind != "agent":
            assert ports["beta"].read_text(r.Scope(), "note")["text"] == "A"
        else:
            assert ports["beta"].list(r.Scope())["entries"] == []
        assert engine.diagnostics(handle.run_id).manifest["kernel"] == "local-bindings-12"


def test_disabled_source2_binding_keeps_business_and_cannot_write(host, tmp_path):
    ports, registry = host
    value = r.AgentDefinition(
        r.AgentSpec("disabled", "No files", tools=("alpha_workspace_write_text", "business")),
        r.AgentBindingDescriptor(workspace=r.BindingSelection.disabled()),
    )
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "disabled.sqlite"),
        providers={"default": Writer()},
        tools=registry,
        binding_catalog=catalog(registry),
    ) as engine:
        run = engine.submit(value, "q", command_id="submit")
        done = asyncio.run(finish(engine, run.run_id))
        assert done.state == "succeeded" and done.result == {"available": ["business"]}
    assert ports["alpha"].list(r.Scope())["entries"] == []


def test_temporal_native_protocol2_and_copied_history_keep_fixed_write_grants(host):
    _, registry = host
    execution = TemporalRuntime(
        providers={"default": Writer()},
        tools=registry,
        binding_catalog=catalog(registry),
        journal=JournalContractFixture(),
    )
    request = normalize_request(submission_request(definition("agent"), "q"))
    state = TemporalRunState("run", asdict(r.Scope()), "submit", request, execution.manifest)
    assert execution.manifest["workspace_binding_protocol"] == 2
    assert state.step["tools"] == ["alpha_workspace_write_text", "business"]
    assert copy.deepcopy(state).step == state.step
    stale = {**execution.manifest, "workspace_binding_protocol": 1}
    with pytest.raises((DefinitionMismatch, ValidationError)):
        validate_manifest(stale)


def test_excluded_write_proposal_cannot_reach_either_root(host, tmp_path):
    ports, registry = host

    class Wrong(Writer):
        identity = {"kind": "excluded-workspace-write-proposal", "version": "1"}

        async def complete(self, messages, tools):
            assert [t["function"]["name"] for t in tools] == [
                "alpha_workspace_write_text",
                "business",
            ]
            return r.ModelResponse(
                tool_calls=[
                    r.ToolCall(
                        "beta_workspace_write_text",
                        {"path": "note", "text": "A", "expected_version": None},
                        "wrong",
                    )
                ]
            )

    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "excluded.sqlite"),
        providers={"default": Wrong()},
        tools=registry,
        binding_catalog=catalog(registry),
    ) as engine:
        run = engine.submit(definition("agent"), "q", command_id="submit")
        assert asyncio.run(engine.drive(run.run_id)).state == "failed"
    assert all(port.list(r.Scope())["entries"] == [] for port in ports.values())


def test_tool_set_cannot_expand_source2_write_grants(host, tmp_path):
    _, registry = host
    bindings = catalog(registry)
    bindings.register(
        "tool_set", "expanded", "1", ["alpha_workspace_write_text", "beta_workspace_write_text"]
    )
    declared = r.AgentDefinition(
        r.AgentSpec("narrow", "Write", tools=("alpha_workspace_write_text",)),
        r.AgentBindingDescriptor(
            workspace=r.BindingSelection.ref("alpha", "1"),
            tool_set=r.BindingSelection.ref("expanded", "1"),
        ),
    )
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "expanded.sqlite"),
        providers={"default": Writer()},
        tools=registry,
        binding_catalog=bindings,
    ) as engine:
        with pytest.raises(ValidationError):
            engine.submit(declared, "q", command_id="submit")


@pytest.mark.parametrize("bad", [[], "bad", {"wrong": []}])
def test_malformed_temporal_tool_metadata_is_a_typed_preflight_error(host, bad):
    _, registry = host
    execution = TemporalRuntime(
        providers={"default": Writer()},
        tools=registry,
        binding_catalog=catalog(registry),
        journal=JournalContractFixture(),
    )
    manifest = {**execution.manifest, "tools": bad}
    with pytest.raises((ValidationError, DefinitionMismatch)):
        validate_manifest(manifest)


def test_actual_file_lost_response_restarts_original_run_and_queries_receipt_without_rewrite(
    tmp_path,
):
    root = tmp_path / "files"
    root.mkdir()
    calls = []

    class Lost(r.FileSystemWritableWorkspace):
        def write_text(self, scope, path, text, *, expected_version, effect_key):
            receipt = super().write_text(
                scope, path, text, expected_version=expected_version, effect_key=effect_key
            )
            calls.append(receipt["effect_key"])
            raise WorkspaceError("injected lost response after confirmed file effect")

    def build():
        port = Lost(root, version="1")
        source = r.WritableWorkspaceToolSource(port, version="1")
        registry = r.ToolRegistry()
        asyncio.run(
            r.register_tool_source(
                registry,
                source,
                policies={
                    "workspace_write_text": r.ToolPolicy(
                        "1",
                        effect="idempotent_write",
                        effect_key_argument="effect_key",
                        reconciler=source.reconcile,
                    )
                },
            )
        )
        bindings = r.BindingCatalog(scope=r.Scope())
        bindings.register(
            "workspace",
            "files",
            "1",
            r.WorkspaceBindingResource(registry, names=["workspace_write_text"]),
        )
        engine = r.LocalEngine(
            r.SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": Writer()},
            tools=registry,
            binding_catalog=bindings,
        )
        return port, source, engine

    from .test_workspace_write_configuration import bound

    port, source, engine = build()
    try:
        handle = engine.submit(bound(), "q", command_id="same")
        waiting = asyncio.run(engine.drive(handle.run_id))
        pending = waiting.pending[0]
        approval = engine.approve(
            handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
        )
        assert (
            engine.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            == approval
        )
        unknown = asyncio.run(engine.drive(handle.run_id))
        assert unknown.state == "waiting_reconciliation" and (root / "note").read_text() == "A"
        inode = (root / "note").stat().st_ino
    finally:
        engine.close()
        asyncio.run(source.aclose())
        port.close()
    port, source, engine = build()
    try:
        assert engine.submit(bound(), "q", command_id="same") == handle
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        assert len(calls) == 1 and (root / "note").stat().st_ino == inode
        assert done.result["effect_key"] == calls[0]
        (root / "note").write_text("later")
        assert asyncio.run(engine.drive(handle.run_id)).result == done.result
        assert (root / "note").read_text() == "later"
    finally:
        engine.close()
        asyncio.run(source.aclose())
        port.close()
