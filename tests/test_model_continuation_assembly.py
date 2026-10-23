"""Public assembly enables continuation explicitly without changing old defaults."""

import asyncio
import importlib
import json

import pytest

from relf_agent import AgentSpec, RuntimeBuilder, RuntimeProfile
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.planning_evaluation import EvaluationLimits
from relf_agent.runtime_builder import EchoProvider
from relf_agent.task_evaluation_provider import PinnedEvaluationProvider


def test_public_provider_and_continuation_exports():
    api = importlib.import_module("relf_agent")
    for name, module in [
        ("GeminiFunctionProvider", "gemini_functions"),
        ("ModelContinuation", "model_continuation"),
        ("ContinuedModelResponse", "model_continuation"),
    ]:
        assert getattr(api, name, None) is getattr(
            importlib.import_module("relf_agent." + module), name
        )


@pytest.mark.parametrize("asynchronous", [False, True])
def test_explicit_profile_enables_gemini_functions_without_exposing_credentials(
    tmp_path, monkeypatch, asynchronous
):
    monkeypatch.setenv("GEMINI_API_KEY", "FIXTURE_PRIVATE_KEY")
    profile = RuntimeProfile(
        "signed",
        "1",
        {"default": {"adapter": "gemini-functions", "config": {"model": "fixture", "seed": 9}}},
        {"model_continuation": {"adapter": "native"}},
    )
    builder = RuntimeBuilder()

    async def run():
        instance = await builder.abuild(profile, tmp_path / "runs.sqlite")
        try:
            h = instance.submit(AgentSpec("a", "Answer"), "q", command_id="s")
            manifest = instance.diagnostics(h.run_id).manifest
            assert manifest["kernel"] == "local-5"
            assert manifest["provider_continuations"]["default"]["protocol"] == "gemini-content-v1"
            assert "FIXTURE_PRIVATE_KEY" not in json.dumps(manifest)
        finally:
            await instance.aclose()

    if asynchronous:
        asyncio.run(run())
    else:
        with builder.build(profile, tmp_path / "runs.sqlite") as instance:
            h = instance.submit(AgentSpec("a", "Answer"), "q", command_id="s")
            assert instance.diagnostics(h.run_id).manifest["model_continuation_protocol"] == 1


def test_gemini_profile_without_opt_in_refuses_before_database_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "FIXTURE")
    path = tmp_path / "not-created.sqlite"
    profile = RuntimeProfile(
        "a", "1", {"default": {"adapter": "gemini-functions", "config": {"model": "fixture"}}}
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile, path)
    assert not path.exists()


def test_continuation_adapter_configuration_is_strict_before_construction(tmp_path):
    profile = RuntimeProfile(
        "a",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"model_continuation": {"adapter": "native", "config": {"ignored": True}}},
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile, tmp_path / "not-created.sqlite")
    assert not (tmp_path / "not-created.sqlite").exists()


def test_audit_wrapper_pins_and_delegates_original_continuation_owner():
    class Signed(EchoProvider):
        continuation_identity = {"protocol": "fixture-1", "owner_digest": "a" * 64}

    provider = Signed("fixture")
    wrapped = PinnedEvaluationProvider(provider, EvaluationLimits())
    assert getattr(wrapped, "continuation_identity", None) == provider.continuation_identity
    provider.continuation_identity = {"protocol": "fixture-1", "owner_digest": "b" * 64}
    with pytest.raises(DefinitionMismatch):
        wrapped.validate_request([], [])


@pytest.mark.parametrize("change", ["owner", "identity", "method"])
def test_completed_signed_response_is_recorded_before_audit_drift_rejection(tmp_path, change):
    from relf_agent import LocalEngine, SQLiteStore
    from tests.test_local_model_continuation import Provider, registry, spec

    class Changing(Provider):
        async def complete(self, messages, tools):
            result = await super().complete(messages, tools)
            if change == "owner":
                self.continuation_identity = {
                    **self.continuation_identity,
                    "owner_digest": "b" * 64,
                }
            elif change == "identity":
                self.identity = {**self.identity, "version": "changed"}
            else:

                async def replacement(messages, tools):
                    return result

                self.complete = replacement
            return result

    effects, raw = [], Changing()
    wrapped = PinnedEvaluationProvider(raw, EvaluationLimits())
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": wrapped},
        tools=registry(effects),
        model_continuation=True,
    ) as engine:
        handle = engine.submit(spec(), "task", command_id="submit")
        try:
            asyncio.run(engine.drive(handle.run_id))
        except DefinitionMismatch:
            pass
        record = engine.store.run(handle.run_id)
        model = record["actions"][0]
        assert model.get("received_response", {}).get("continuation"), record
        assert model["attempts"][0]["status"] == "completed"
        assert model["status"] != "outcome_unknown"
        assert engine.store.budget(handle.run_id)["spent"] == 1
        assert engine.store.budget(handle.run_id)["held"] == 0
        assert raw.calls == 1 and effects == []


def test_temporal_profile_forwards_explicit_execution_option(tmp_path):
    from relf_agent.temporal_builder import TemporalRuntimeBuilder
    from relf_agent.temporal_profile import TemporalProfile

    selected = TemporalProfile(
        "a", "1", {"default": {"adapter": "offline-echo"}}, execution={"model_continuation": True}
    )

    async def run():
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(selected)
        try:
            assert assembly.release["model_continuation_protocol"] == 1
            assert assembly.release["binding_protocol"] == 6
            assert assembly.release["provider_continuations"] == {"default": None}
        finally:
            await assembly.aclose()

    asyncio.run(run())


def test_middleware_provider_delegates_signed_protocol_and_preserves_tool_loop(tmp_path):
    from relf_agent import LocalEngine, MiddlewareProvider, SQLiteStore
    from tests.test_local_model_continuation import Provider, registry, spec

    effects, raw = [], Provider()
    wrapped = MiddlewareProvider(raw)
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": wrapped},
        tools=registry(effects),
        model_continuation=True,
    ) as engine:
        h = engine.submit(spec(), "task", command_id="s")
        outcome = asyncio.run(engine.drive(h.run_id))
        assert outcome.state == "succeeded", outcome
        assert raw.calls == 2 and effects == [{"value": 7, "flag": True}]


@pytest.mark.parametrize("kind", ["rag", "orchestration"])
def test_task_cli_explicit_gemini_functions_enables_runtime_mode(kind, monkeypatch):
    module = importlib.import_module(f"relf_agent.{kind}_evaluation_cli")
    seen = []
    monkeypatch.setattr(
        module, "_http_provider", lambda args, limits: (EchoProvider("fixture"), None)
    )
    if kind == "rag":
        monkeypatch.setattr(module, "_embedding_provider", lambda args, limits: (None, None))

    async def evaluate(provider, **kwargs):
        seen.append(kwargs)
        return {"status": "not_run"}

    monkeypatch.setattr(module, "evaluate_" + kind, evaluate)
    args = module.arguments(["--provider", "gemini-functions", "--model", "fixture"])
    asyncio.run(module.run(args))
    assert seen[0]["model_continuation"] is True
