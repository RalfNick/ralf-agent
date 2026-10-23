"""Explicit thinking configuration reaches the original Local and Temporal assembly."""

import asyncio
import importlib
import json

import httpx
import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingSelection,
    ComponentRegistry,
    RuntimeBuilder,
    RuntimeProfile,
    TemporalProfile,
    TemporalRuntimeBuilder,
)
from relf_agent.errors import ValidationError
from relf_agent.runtime_builder import EchoProvider
from relf_agent.temporal_bindings import provider_alias


def declaration(**config):
    return {
        "adapter": "deepseek-thinking",
        "config": {"model": "explicit-fixture-model", **config},
    }


def bindings(component=None):
    return [
        {
            "role": "provider",
            "component_id": "reasoner",
            "version": "2",
            "component": declaration(reasoning_effort="low") if component is None else component,
        }
    ]


def bound_agent():
    return AgentDefinition(
        AgentSpec("a", "Answer"),
        AgentBindingDescriptor(provider=BindingSelection.ref("reasoner", "2")),
    )


def test_sdk_exports_independent_thinking_provider():
    api = importlib.import_module("relf_agent")
    assert getattr(api, "DeepSeekThinkingProvider", None) is not None
    assert (
        api.DeepSeekThinkingProvider
        is importlib.import_module("relf_agent.deepseek_thinking").DeepSeekThinkingProvider
    )
    assert api.DeepSeekThinkingProvider is not api.DeepSeekChatProvider


@pytest.mark.parametrize("asynchronous", [False, True])
def test_local_profile_pins_explicit_effort_and_per_agent_owner(
    tmp_path, monkeypatch, asynchronous
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ASSEMBLY_PRIVATE_FIXTURE")
    selected = RuntimeProfile(
        "thinking",
        "1",
        {"default": declaration(reasoning_effort="max")},
        {"model_continuation": {"adapter": "native"}},
        binding_components=bindings(),
    )

    def check(instance):
        h = instance.submit(bound_agent(), "question", command_id="submit")
        manifest = instance.diagnostics(h.run_id).manifest
        effective = next(iter(manifest["agent_bindings"]["steps"].values()))["manifest"]
        assert manifest["model_continuation_protocol"] == 1
        assert effective["providers"]["default"]["model"] == "explicit-fixture-model"
        assert effective["providers"]["default"]["reasoning_effort"] == "low"
        assert effective["provider_continuations"]["default"]["protocol"] == "deepseek-thinking-v1"
        assert instance.providers["default"].identity["reasoning_effort"] == "max"
        assert "ASSEMBLY_PRIVATE_FIXTURE" not in json.dumps(manifest)

    async def run():
        instance = await RuntimeBuilder().abuild(selected, tmp_path / "runs.sqlite")
        try:
            check(instance)
        finally:
            await instance.aclose()

    if asynchronous:
        asyncio.run(run())
    else:
        with RuntimeBuilder().build(selected, tmp_path / "runs.sqlite") as instance:
            check(instance)


def test_actual_offline_temporal_profile_pins_both_owners_without_local_database(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "TEMPORAL_PRIVATE_FIXTURE")
    selected = TemporalProfile(
        "thinking",
        "1",
        {"default": declaration()},
        binding_components=bindings(),
        execution={"model_continuation": True},
    )

    async def run():
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(
            selected, data_path=tmp_path / "data"
        )
        try:
            release = assembly.release
            alias = provider_alias(BindingSelection.ref("reasoner", "2"))
            assert release["binding_protocol"] == 6
            assert release["runtime_profile"] == selected.identity
            assert release["model_continuation_protocol"] == 1
            assert release["providers"]["default"]["reasoning_effort"] == "high"
            assert release["providers"][alias]["reasoning_effort"] == "low"
            assert release["provider_continuations"][alias]["protocol"] == "deepseek-thinking-v1"
            assert (
                release["provider_continuations"][alias]
                != release["provider_continuations"]["default"]
            )
            assert "TEMPORAL_PRIVATE_FIXTURE" not in json.dumps(release)
            assert list(tmp_path.iterdir()) == []
        finally:
            await assembly.aclose()
        assert list(tmp_path.iterdir()) == []

    asyncio.run(run())


@pytest.mark.parametrize("temporal", [False, True])
@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("adapter", ["gemini-functions", "deepseek-thinking"])
def test_missing_continuation_opt_in_rejects_before_owned_resources(
    tmp_path, monkeypatch, temporal, bound, adapter
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "FIXTURE")
    monkeypatch.setenv("GEMINI_API_KEY", "FIXTURE")
    events = []

    class Resource:
        def close(self):
            events.append("close")

    def factory(config, context):
        events.append("construct")
        context.own(Resource())
        return EchoProvider("owned")

    registry = ComponentRegistry()
    registry.register("provider", "owned-before-thinking", factory)
    model = {"adapter": adapter, "config": {"model": "explicit-fixture-model"}}
    providers = {"default": {"adapter": "owned-before-thinking"}}
    if not bound:
        providers["thinking"] = model
    options = {"binding_components": bindings(model)} if bound else {}
    profile_type = TemporalProfile if temporal else RuntimeProfile
    selected = profile_type("p", "1", providers, **options)
    path = tmp_path / "must-not-exist.sqlite"

    async def run():
        with pytest.raises(ValidationError, match="continuation"):
            if temporal:
                await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                    selected, data_path=path
                )
            else:
                await RuntimeBuilder(registry).abuild(selected, path)

    asyncio.run(run())
    assert events == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("temporal", [False, True])
@pytest.mark.parametrize(
    "invalid",
    [
        {"model": ""},
        {"reasoning_effort": "medium"},
        {"reasoning_effort": True},
        {"temperature": 0.5},
        {"seed": 42},
        {"top_p": 0.94},
        {"top_p": 1.01},
        {"json_mode": True, "stream": True},
        {"api_key": "inline-secret"},
        {"ignored": True},
    ],
)
def test_invalid_thinking_binding_preflight_creates_no_authority_or_resource(
    tmp_path, temporal, invalid
):
    events = []

    def factory(config, context):
        events.append("constructed")
        return EchoProvider("owned")

    registry = ComponentRegistry()
    registry.register("provider", "before-invalid", factory)
    providers = {"default": {"adapter": "before-invalid"}}
    profile_type = TemporalProfile if temporal else RuntimeProfile
    options = (
        {"execution": {"model_continuation": True}}
        if temporal
        else {"components": {"model_continuation": {"adapter": "native"}}}
    )
    selected = profile_type(
        "p", "1", providers, binding_components=bindings(declaration(**invalid)), **options
    )
    path = tmp_path / "must-not-exist.sqlite"

    async def run():
        with pytest.raises(ValidationError):
            if temporal:
                await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                    selected, data_path=path
                )
            else:
                await RuntimeBuilder(registry).abuild(selected, path)

    asyncio.run(run())
    assert events == [] and list(tmp_path.iterdir()) == []


def test_replacement_provider_and_old_defaults_use_existing_registry_and_profile(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "REPLACEMENT_PRIVATE_FIXTURE")
    registry = ComponentRegistry()
    registry.register("provider", "replacement", lambda c, ctx: EchoProvider("replacement"))
    selected = RuntimeProfile(
        "p",
        "1",
        {"default": declaration()},
        {"model_continuation": {"adapter": "native"}},
    )
    replacement = RuntimeProfile(
        "p",
        "2",
        {"default": {"adapter": "replacement"}},
        {"model_continuation": {"adapter": "native"}},
    )
    assert selected.identity != replacement.identity
    with RuntimeBuilder(registry).build(selected, tmp_path / "original.sqlite") as instance:
        h = instance.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        original_manifest = instance.diagnostics(h.run_id).manifest
        assert original_manifest["providers"]["default"]["kind"] == "deepseek-thinking-completions"
        assert (
            original_manifest["provider_continuations"]["default"]["protocol"]
            == "deepseek-thinking-v1"
        )
    with RuntimeBuilder(registry).build(replacement, tmp_path / "replacement.sqlite") as instance:
        h = instance.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(instance.drive(h.run_id)).result == {"echo": "q", "label": "replacement"}
        assert instance.diagnostics(h.run_id).manifest["provider_continuations"] == {
            "default": None
        }
    assert original_manifest["runtime_profile"] == selected.identity
    assert original_manifest["providers"]["default"]["kind"] == "deepseek-thinking-completions"
    old = RuntimeProfile("p", "1", {"default": {"adapter": "offline-echo"}})
    with RuntimeBuilder().build(old, tmp_path / "old.sqlite") as instance:
        h = instance.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(instance.drive(h.run_id)).result == {"echo": "q", "label": "offline"}
        assert "model_continuation_protocol" not in instance.diagnostics(h.run_id).manifest
    assert json.loads(old._data_json) == {
        "name": "p",
        "version": "1",
        "providers": {"default": {"adapter": "offline-echo", "config": {}}},
        "components": {},
    }


def test_temporal_replacement_reuses_registry_without_changing_old_profile(tmp_path):
    registry = ComponentRegistry()
    registry.register("provider", "replacement", lambda c, ctx: EchoProvider("replacement"))
    old = TemporalProfile("p", "1", {"default": {"adapter": "offline-echo"}})
    explicit_false = TemporalProfile(
        "p",
        "1",
        {"default": {"adapter": "offline-echo"}},
        execution={"model_continuation": False},
    )
    replacement = TemporalProfile("p", "2", {"default": {"adapter": "replacement"}})
    assert old.to_dict() == explicit_false.to_dict()
    assert old.identity == explicit_false.identity

    async def run():
        builder = TemporalRuntimeBuilder(registry, base_dir=tmp_path)
        for selected, label in [(old, "offline"), (replacement, "replacement")]:
            assembly = await builder.abuild(selected)
            try:
                assert assembly.release["runtime_profile"] == selected.identity
                assert assembly.release["providers"]["default"]["label"] == label
                assert "model_continuation_protocol" not in assembly.release
                assert list(tmp_path.iterdir()) == []
            finally:
                await assembly.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "adapter",
    [
        "chat-completions",
        "deepseek-chat",
        "anthropic-messages",
        "gemini-content",
        "gemini-functions",
    ],
)
def test_unrelated_model_configuration_rejects_effort_before_database(tmp_path, adapter):
    selected = RuntimeProfile(
        "p",
        "1",
        {
            "default": {
                "adapter": adapter,
                "config": {
                    "model": "explicit-fixture-model",
                    "reasoning_effort": "high",
                },
            }
        },
        {"model_continuation": {"adapter": "native"}},
    )
    with pytest.raises(ValidationError, match="configuration"):
        RuntimeBuilder().build(selected, tmp_path / "must-not-exist.sqlite")
    assert list(tmp_path.iterdir()) == []


def cli(name):
    return importlib.import_module("relf_agent." + name)


@pytest.mark.parametrize(
    "name",
    [
        "model_check_cli",
        "planning_evaluation_cli",
        "rag_evaluation_cli",
        "orchestration_evaluation_cli",
    ],
)
@pytest.mark.parametrize("source", [[], ["--offline"]])
def test_effort_without_thinking_selection_is_rejected_before_clients(
    name, source, monkeypatch, capsys
):
    if name == "planning_evaluation_cli" and source:
        source = ["--provider", "openai"]

    def forbidden(*args, **kwargs):
        raise AssertionError("Unrelated effort configuration must fail before HTTP clients")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    assert cli(name).main([*source, "--reasoning-effort", "max"]) == 2
    encoded = capsys.readouterr().out
    assert json.loads(encoded).get("calls", 0) == 0


@pytest.mark.parametrize(
    "name",
    [
        "model_check_cli",
        "planning_evaluation_cli",
        "rag_evaluation_cli",
        "orchestration_evaluation_cli",
    ],
)
def test_cli_defaults_still_do_not_infer_deepseek_model_or_credentials(name, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "UNREQUESTED_PRIVATE_FIXTURE")
    assert cli(name).main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_run" and report["calls"] == 0
    assert "UNREQUESTED_PRIVATE_FIXTURE" not in json.dumps(report)


@pytest.mark.parametrize(
    "name",
    [
        "model_check_cli",
        "planning_evaluation_cli",
        "rag_evaluation_cli",
        "orchestration_evaluation_cli",
    ],
)
def test_thinking_cli_runs_actual_managed_evaluation_with_explicit_effort(
    name, tmp_path, monkeypatch, capsys
):
    from relf_agent.embeddings import HashEmbeddingProvider
    from relf_agent.orchestration_evaluation import OfflineOrchestrationProvider
    from relf_agent.rag_evaluation import OfflineRAGProvider
    from tests.test_planning_evaluation import proposal

    native_client = httpx.AsyncClient
    requests, clients = [], []

    async def handle(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            vectors = await HashEmbeddingProvider(dimensions=16).embed(body["input"])
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "explicit-embedding",
                    "data": [
                        {"object": "embedding", "index": i, "embedding": v}
                        for i, v in enumerate(vectors)
                    ],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
            )
        requests.append(body)
        assert body["model"] == "explicit-fixture-model"
        assert body["reasoning_effort"] == "max"
        assert body["thinking"] == {"type": "enabled"}
        assert "temperature" not in body and "seed" not in body
        if name == "planning_evaluation_cli":
            output, calls = proposal(), ()
        elif name == "rag_evaluation_cli":
            response = await OfflineRAGProvider().complete(body["messages"], [])
            output, calls = response.output, response.tool_calls
        elif name == "orchestration_evaluation_cli":
            response = await OfflineOrchestrationProvider().complete(
                body["messages"], body["tools"]
            )
            output, calls = response.output, response.tool_calls
        elif not any(m["role"] == "tool" for m in body["messages"]):
            from relf_agent import ToolCall

            output, calls = (
                None,
                (ToolCall("ralf_model_echo", {"value": "RALF_TOOL_CHECK"}, "native-echo"),),
            )
        else:
            output, calls = {"ok": True}, ()
        message = {
            "role": "assistant",
            "content": json.dumps(output) if output is not None else None,
            "reasoning_content": "PRIVATE_REASONING_FIXTURE",
        }
        if calls:
            message["tool_calls"] = [
                {
                    "id": call.call_id or f"fixture-native-{i}",
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for i, call in enumerate(calls)
            ]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if calls else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            },
        )

    class RecordedClient(native_client):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **{**kwargs, "transport": httpx.MockTransport(handle)})
            clients.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", RecordedClient)
    monkeypatch.setenv("THINKING_ASSEMBLY_KEY", "PRIVATE_THINKING_CREDENTIAL")
    monkeypatch.setenv("THINKING_EMBEDDING_KEY", "PRIVATE_EMBEDDING_CREDENTIAL")
    options = [
        "--model",
        "explicit-fixture-model",
        "--reasoning-effort",
        "max",
        "--evidence-dir",
        str(tmp_path / "evidence"),
    ]
    if name == "model_check_cli":
        options += [
            "--adapter",
            "deepseek-thinking",
            "--api-key-env",
            "THINKING_ASSEMBLY_KEY",
            "--cases",
            "tool",
        ]
    else:
        options += [
            "--provider",
            "deepseek-thinking",
            "--key-env",
            "THINKING_ASSEMBLY_KEY",
            "--max-cases",
            "1",
        ]
    if name == "rag_evaluation_cli":
        options += [
            "--embedding-model",
            "explicit-embedding",
            "--embedding-dimensions",
            "16",
            "--embedding-key-env",
            "THINKING_EMBEDDING_KEY",
        ]
    assert cli(name).main(options) == 0
    encoded = capsys.readouterr().out
    report = json.loads(encoded)
    assert report["passed"] == report["total"] == 1
    assert requests
    assert all(client.is_closed for client in clients)
    assert "PRIVATE_THINKING_CREDENTIAL" not in encoded
    assert "PRIVATE_EMBEDDING_CREDENTIAL" not in encoded
    assert "PRIVATE_REASONING_FIXTURE" not in encoded
    if name in {"model_check_cli", "orchestration_evaluation_cli"}:
        assert any(
            m["role"] == "assistant" and m["reasoning_content"] == "PRIVATE_REASONING_FIXTURE"
            for request in requests[1:]
            for m in request["messages"]
        )
