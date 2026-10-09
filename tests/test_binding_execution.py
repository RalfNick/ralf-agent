"""Real SQLite acceptance, per-Run routing and approval/recovery boundaries."""

import asyncio
import importlib
import json

import pytest

from ralf_agent import (
    AgentSpec,
    InMemoryMemory,
    LocalEngine,
    ModelResponse,
    Scope,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
)
from ralf_agent.context import ContextAssembler
from ralf_agent.errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from ralf_agent.harness import NativeHarness
from ralf_agent.retrieval import (
    Document,
    InMemoryKnowledgeStore,
    KnowledgeContext,
    LexicalRetriever,
)
from ralf_agent.types import ToolCall, canonical

from .helpers import ScriptedProvider


def api():
    return (
        importlib.import_module("ralf_agent.binding_types"),
        importlib.import_module("ralf_agent.binding_definitions"),
        importlib.import_module("ralf_agent.binding_catalog"),
    )


class RecordingProvider:
    def __init__(self, label):
        self.label = label

    @property
    def identity(self):
        return {"kind": "binding-recording", "version": "1", "label": self.label}

    async def complete(self, messages, tools):
        await asyncio.sleep(0)
        return ModelResponse(output={"provider": self.label, "request": canonical(messages)})


class TaggedContext:
    def __init__(self, tag):
        self.tag = tag

    @property
    def identity(self):
        return {"kind": "tagged-context", "version": "1", "tag": self.tag}

    def assemble(self, history, references, max_chars):
        return ContextAssembler().assemble(
            [*history, {"role": "system", "content": "context:" + self.tag}], references, max_chars
        )


def bound_catalog():
    _, _, c = api()
    return c.BindingCatalog(scope=Scope())


def definition(spec=None, **roles):
    t, d, _ = api()
    return d.AgentDefinition(
        spec or AgentSpec("shared", "Answer"), t.AgentBindingDescriptor(**roles)
    )


def choice(component):
    return api()[0].BindingSelection.ref(component, "1")


def engine(path, catalog, **kwargs):
    return LocalEngine(
        SQLiteStore(path),
        providers={"default": RecordingProvider("host")},
        tools=kwargs.pop("tools", ToolRegistry()),
        binding_catalog=catalog,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("kind", "size"), [("agent", 530_000), ("agent", 1_100_000), ("sequence", 900_000)]
)
def test_large_legacy_binding_preserves_acceptance_and_queued_restart(tmp_path, kind, size):
    t, d, _ = api()
    spec = AgentSpec("large", "Answer", output_schema={"description": "x" * size})
    wrapped = (
        d.AgentDefinition(spec, t.AgentBindingDescriptor())
        if kind == "agent"
        else d.BoundDefinition(WorkflowSpec("large", [spec]), {})
    )
    path = tmp_path / "large.sqlite"
    with engine(path, bound_catalog()) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="s")
        original = runtime.diagnostics(handle.run_id).manifest
    with engine(path, bound_catalog()) as runtime:
        assert runtime.submit(wrapped, "q", command_id="s") == handle
        result = asyncio.run(runtime.drive(handle.run_id))
        assert result.state == "succeeded" and result.result["provider"] == "host"
        assert runtime.diagnostics(handle.run_id).manifest == original


def test_concurrent_agents_use_separate_provider_context_facts_and_knowledge(tmp_path):
    catalog = bound_catalog()
    for label in ("red", "blue"):
        catalog.register("provider", label, "1", RecordingProvider(label))
        catalog.register("context", label, "1", TaggedContext(label))
        facts = InMemoryMemory(backend_id="facts-" + label)
        facts.put_fact(Scope(), "shared", "color", label, expected_version=0)
        catalog.register("facts", label, "1", facts)
        store = InMemoryKnowledgeStore(backend_id="knowledge-" + label)
        store.put(Scope(), "docs", Document("guide", "pool " + label), expected_version=0)
        catalog.register(
            "knowledge", label, "1", KnowledgeContext(LexicalRetriever(store), namespace="docs")
        )
    with engine(tmp_path / "shared.sqlite", catalog) as runtime:
        handles = [
            runtime.submit(
                definition(
                    **{
                        role: choice(label)
                        for role in ("provider", "context", "facts", "knowledge")
                    }
                ),
                "pool",
                command_id=label,
            )
            for label in ("red", "blue")
        ]

        async def run_all():
            return await asyncio.gather(*(runtime.drive(h.run_id) for h in handles))

        results = asyncio.run(run_all())
        for label, other, result in zip(("red", "blue"), ("blue", "red"), results, strict=True):
            assert result.state == "succeeded" and result.result["provider"] == label
            assert "context:" + label in result.result["request"]
            assert "pool " + label in result.result["request"]
            assert "pool " + other not in result.result["request"]
        assert runtime.providers["default"].label == "host"


def test_sequence_routes_same_logical_provider_name_per_step(tmp_path):
    t, d, _ = api()
    catalog = bound_catalog()
    for label in ("one", "two"):
        catalog.register("provider", label, "1", RecordingProvider(label))
    sequence = WorkflowSpec(
        "pipeline", [AgentSpec("first", "Answer"), AgentSpec("second", "Answer")]
    )
    wrapped = d.BoundDefinition(
        sequence,
        {
            f"sequence/steps/{n}": t.AgentBindingDescriptor(provider=choice(label))
            for n, label in enumerate(("one", "two"))
        },
    )
    with engine(tmp_path / "sequence.sqlite", catalog) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="submit")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded" and done.result["provider"] == "two"
        assert json.loads(json.loads(done.result["request"])[1]["content"])["provider"] == "one"
        manifests = runtime.diagnostics(handle.run_id).manifest["agent_bindings"]["steps"]
        assert manifests["sequence/steps/0"]["manifest"]["providers"]["default"]["label"] == "one"
        assert manifests["sequence/steps/1"]["manifest"]["providers"]["default"]["label"] == "two"


def test_policy_and_stateless_disable_do_not_use_host_session_or_facts(tmp_path):
    t, _, _ = api()
    catalog = bound_catalog()

    class Policy(NativeHarness):
        identity = {"kind": "bound-policy", "version": "1"}

        def propose(self, spec, response):
            from ralf_agent.harness import DecisionProposal

            return DecisionProposal("policy-output")

    catalog.register("decision_policy", "custom", "1", Policy())
    wrapped = definition(
        decision_policy=choice("custom"),
        session=t.BindingSelection.disabled(),
        facts=t.BindingSelection.disabled(),
        knowledge=t.BindingSelection.disabled(),
    )
    with engine(tmp_path / "stateless.sqlite", catalog) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).result == "policy-output"
        assert runtime.sessions.read(Scope(), handle.run_id)[1] == []
        with pytest.raises(ValidationError):
            runtime.submit(wrapped, "q", command_id="explicit-session", session_id="shared")


def test_bound_tool_subset_blocks_forbidden_effect(tmp_path):
    catalog = bound_catalog()
    catalog.register("tool_set", "read-only", "1", ["read"])
    executed = []
    tools = ToolRegistry()
    for name in ("read", "write"):
        tools.register(
            ToolSpec(name, name, {"type": "object"}), lambda a, c: executed.append("effect")
        )
    provider = ScriptedProvider([ModelResponse(tool_calls=(ToolCall("write", {}),))])
    catalog.register("provider", "request-write", "1", provider)
    wrapped = definition(
        AgentSpec("a", "Act", tools=("read", "write")),
        provider=choice("request-write"),
        tool_set=choice("read-only"),
    )
    with engine(tmp_path / "denied.sqlite", catalog, tools=tools) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="s")
        result = asyncio.run(runtime.drive(handle.run_id))
        assert result.state == "failed" and result.error["code"] == "authorization_denied"
        assert executed == []


def test_tool_binding_cannot_expand_agent_declared_grant(tmp_path):
    catalog = bound_catalog()
    catalog.register("tool_set", "expanded", "1", ["outside"])
    with engine(tmp_path / "expanded.sqlite", catalog) as runtime:
        with pytest.raises(ValidationError):
            runtime.submit(definition(tool_set=choice("expanded")), "q", command_id="bad")
        assert runtime.store.session_owner(Scope(), "q") is None


def test_approval_and_restart_keep_bound_provider_and_host_policy(tmp_path):
    catalog = bound_catalog()
    selected = ScriptedProvider(
        [ModelResponse(tool_calls=(ToolCall("write", {}),)), ModelResponse(output="done")]
    )
    catalog.register("provider", "model", "1", selected)
    calls = []
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "write", "Write", {"type": "object"}, effect="unqueryable_write", requires_approval=True
        ),
        lambda a, c: calls.append(c.effect_key) or "written",
    )
    wrapped = definition(AgentSpec("a", "Act", tools=("write",)), provider=choice("model"))
    path = tmp_path / "approval.sqlite"
    with engine(path, catalog, tools=tools) as original:
        handle = original.submit(wrapped, "q", command_id="submit")
        assert asyncio.run(original.drive(handle.run_id)).state == "waiting_approval"
        action = original.store.run(handle.run_id)["actions"][-1]
    with engine(path, catalog, tools=tools) as restarted:
        receipt = restarted.approve(
            handle.run_id, action["id"], action["digest"], command_id="approve"
        )
        assert (
            restarted.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
            == receipt
        )
        assert asyncio.run(restarted.drive(handle.run_id)).result == "done"
    assert len(calls) == 1


def test_replay_precedes_catalog_resolution_and_changed_binding_conflicts(tmp_path):
    catalog = bound_catalog()
    catalog.register("provider", "model", "1", RecordingProvider("original"))
    wrapped = definition(provider=choice("model"))
    with engine(tmp_path / "receipts.sqlite", catalog) as runtime:
        original = runtime.submit(wrapped, "q", command_id="submit")
        catalog.unregister("provider", "model", "1")
        assert runtime.submit(wrapped, "q", command_id="submit").run_id == original.run_id
        with pytest.raises(IdempotencyConflict):
            runtime.submit(definition(), "q", command_id="submit")
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(original.run_id))


def test_identity_drift_after_response_preserves_received_evidence(tmp_path):
    catalog = bound_catalog()

    class DriftingProvider(RecordingProvider):
        async def complete(self, messages, tools):
            self.label = "changed"
            return ModelResponse(output="received-original")

    provider = DriftingProvider("original")
    catalog.register("provider", "model", "1", provider)
    with engine(tmp_path / "drift.sqlite", catalog) as runtime:
        handle = runtime.submit(definition(provider=choice("model")), "q", command_id="s")
        result = asyncio.run(runtime.drive(handle.run_id))
        assert result.state == "failed" and result.error["code"] == "definition_mismatch"
        action = runtime.store.run(handle.run_id)["actions"][0]
        assert action["received_response"]["output"] == "received-original"
        assert action["status"] == "response_received"


@pytest.mark.parametrize("role", ["workspace", "sandbox"])
def test_unsupported_reference_fails_before_any_run_or_model(tmp_path, role):
    catalog = bound_catalog()
    with engine(tmp_path / (role + ".sqlite"), catalog) as runtime:
        with pytest.raises(ValidationError):
            runtime.submit(definition(**{role: choice("unsupported")}), "q", command_id="s")
        assert runtime.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_bound_json_declaration_loads_and_executes(tmp_path):
    from ralf_agent.runtime_config import load_spec

    path = tmp_path / "agent.json"
    path.write_text(json.dumps(definition().to_dict()))
    loaded = load_spec(path)
    with engine(tmp_path / "loaded.sqlite", bound_catalog()) as runtime:
        handle = runtime.submit(loaded, "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"


def test_legacy_manifest_remains_unbound(tmp_path):
    with LocalEngine(
        SQLiteStore(tmp_path / "old.sqlite"),
        providers={"default": RecordingProvider("host")},
        tools=ToolRegistry(),
    ) as runtime:
        handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        manifest = runtime.diagnostics(handle.run_id).manifest
        assert manifest["kernel"] == "local-4"
        assert "agent_bindings" not in manifest
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"


def test_host_authorization_still_applies_to_bound_policy_and_provider(tmp_path):
    from ralf_agent.errors import AuthorizationDenied

    catalog = bound_catalog()
    catalog.register(
        "provider",
        "model",
        "1",
        ScriptedProvider([ModelResponse(tool_calls=(ToolCall("write", {}),))]),
    )
    calls = []
    tools = ToolRegistry()
    tools.register(
        ToolSpec("write", "Write", {"type": "object"}), lambda a, c: calls.append("write")
    )

    def deny(scope, spec, arguments):
        raise AuthorizationDenied("host refusal")

    with engine(tmp_path / "host-policy.sqlite", catalog, tools=tools, policy=deny) as runtime:
        handle = runtime.submit(
            definition(AgentSpec("a", "Act", tools=("write",)), provider=choice("model")),
            "q",
            command_id="s",
        )
        result = asyncio.run(runtime.drive(handle.run_id))
        assert result.state == "failed" and result.error["code"] == "authorization_denied"
    assert calls == []


def test_stateless_and_disabled_facts_work_with_host_paged_recall(tmp_path):
    from ralf_agent.recall import MemoryRecallPolicy

    t, _, _ = api()
    with engine(
        tmp_path / "paged.sqlite", bound_catalog(), recall_policy=MemoryRecallPolicy()
    ) as runtime:
        handle = runtime.submit(
            definition(session=t.BindingSelection.disabled(), facts=t.BindingSelection.disabled()),
            "q",
            command_id="s",
        )
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"


def test_catalog_removal_during_model_io_does_not_erase_response(tmp_path):
    catalog = bound_catalog()

    class RemovingProvider(RecordingProvider):
        async def complete(self, messages, tools):
            catalog.unregister("provider", "model", "1")
            return ModelResponse(output="received")

    catalog.register("provider", "model", "1", RemovingProvider("original"))
    with engine(tmp_path / "removed.sqlite", catalog) as runtime:
        handle = runtime.submit(definition(provider=choice("model")), "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).error["code"] == "definition_mismatch"
        assert (
            runtime.store.run(handle.run_id)["actions"][0]["received_response"]["output"]
            == "received"
        )


def test_temporal_rejects_wrappers_before_network_access():
    from ralf_agent import TemporalEngine, TemporalRuntime

    runtime = TemporalRuntime(
        providers={"default": RecordingProvider("fixture")}, tools=ToolRegistry()
    )

    class Client:
        namespace = "default"

        def get_workflow_handle(self, *args, **kwargs):
            pytest.fail("Unsupported binding reached Temporal transport")

    engine = TemporalEngine(Client(), task_queue="queue", release=runtime.manifest)
    assert engine.binding_capabilities["supported_binding_roles"] == []
    with pytest.raises(ValidationError):
        asyncio.run(engine.submit(definition(), "q", command_id="s"))
