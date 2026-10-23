"""Coding requires complete explicit original runtime assembly."""

import pytest

from relf_agent.errors import ValidationError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.tools import ToolRegistry


def test_opt_in_requires_registered_postgres_native_resource():
    from .test_temporal_engine import Provider

    with pytest.raises(ValidationError, match="registered|PostgreSQL"):
        TemporalRuntime(
            providers={"default": Provider()}, tools=ToolRegistry(), coding_execution=True
        )


def test_opt_in_boolean_is_strict():
    from .test_temporal_engine import Provider

    with pytest.raises(ValidationError, match="boolean"):
        TemporalRuntime(
            providers={"default": Provider()}, tools=ToolRegistry(), coding_execution="true"
        )


def test_omitted_and_false_opt_in_keep_same_release():
    from .test_temporal_engine import Provider

    default = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
    disabled = TemporalRuntime(
        providers={"default": Provider()}, tools=ToolRegistry(), coding_execution=False
    )
    assert default.manifest == disabled.manifest
    assert "coding_execution_protocol" not in default.manifest


def test_unknown_effect_does_not_skip_original_owner_stop_evidence(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from relf_agent import delegated_coding, temporal_coding_protocol
    from relf_agent import temporal_coding_runtime as module
    from relf_agent.codex_runner import RunnerOutcomeUnknown

    async def run():
        updates = []
        request = {"runtime_manifest": {}, "coding_request": {"original": "intent"}}
        runner = SimpleNamespace()

        async def reconcile(envelope, authority):
            raise RunnerOutcomeUnknown("Original result remains unknown")

        runner.reconcile_history = reconcile
        handler = SimpleNamespace(
            identity={"runner": "original"}, runner=runner, check=lambda: None
        )
        monkeypatch.setattr(delegated_coding, "registered_coding_tool", lambda tool: handler)
        monkeypatch.setattr(temporal_coding_protocol, "check", lambda runtime, manifest: None)

        async def absent(runner, owner):
            return True

        monkeypatch.setattr(module, "original_owner_stopped", absent)

        async def call(name, proof, **kwargs):
            updates.append(name)
            return {
                "admitted": True,
                "request": request["coding_request"],
                "runner": handler.identity,
            }

        async def state():
            return {
                "state": {"fenced": True, "pending_stop": False, "owner": {"original": "process"}}
            }

        authority = SimpleNamespace(_proof={}, _call=call, _state=state)

        async def factory(*args, **kwargs):
            return authority

        runtime = SimpleNamespace(_envelope=lambda request: (object(), object()))
        result = await module.stop(runtime, request, factory)
        assert result["ok"] is True and "result" not in result
        assert "coding_owner_stopped" in updates

    asyncio.run(run())


def test_native_error_preserves_possible_dispatch_and_unknown_reservation(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from relf_agent import temporal_coding_protocol, temporal_coding_runtime
    from relf_agent.codex_runner import RunnerOutcomeUnknown

    async def fail(*args):
        raise RunnerOutcomeUnknown("Original native response lost")

    monkeypatch.setattr(temporal_coding_protocol, "owns", lambda manifest, name: True)
    monkeypatch.setattr(temporal_coding_runtime, "execute", fail)
    runtime = SimpleNamespace(_envelope=lambda request: (object(), object()))
    response = asyncio.run(
        TemporalRuntime._execute_tool(
            runtime, {"runtime_manifest": {}, "tool": "coding"}, coding_authority=object()
        )
    )
    assert response["ok"] is False and response["dispatched"] is True
