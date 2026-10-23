"""Only native grants check admission; cleanup remains available on the same Run."""

import asyncio
from types import SimpleNamespace

import pytest

from relf_agent import temporal_coding_runtime as native
from relf_agent import temporal_deployment_coding_bridge as bridge
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_coding_state import CODING_GRANT, CODING_STOP
from tests.test_temporal_coding_authority import setup


class Validator:
    instances = []

    def __init__(self, runtime, client, request, info):
        self.instances.append(self)
        self._runtime, self._client, self._request, self._info = runtime, client, request, info

    async def validate(self):
        return None

    async def permission(self):
        return False


def test_closed_deployment_grant_cancels_original_run_but_still_allows_stop(monkeypatch):
    from relf_agent import temporal_coding_recovery_transport, temporal_deployment_coding_validation

    monkeypatch.setattr(temporal_deployment_coding_validation, "CodingValidation", Validator)
    _, request = setup()
    request["runtime_manifest"] = {"deployment_admission_protocol": {"version": 3}}
    captured = []

    async def recover(client, run_id, name, payload, *, execution_epoch):
        assert run_id == "r" and execution_epoch == "epoch"
        captured.append((name, payload))
        return {"admitted": True}

    monkeypatch.setattr(temporal_coding_recovery_transport, "execute", recover)

    class Handle:
        async def execute_update(self, name, payload, **options):
            captured.append((name, payload))
            return {"admitted": True}

    client = SimpleNamespace(
        namespace="original", get_workflow_handle=lambda *args, **kwargs: Handle()
    )
    info = SimpleNamespace(workflow_id="r", workflow_run_id="epoch", workflow_namespace="original")
    runtime = SimpleNamespace(validate_release=lambda value: None)

    async def closed(*args):
        return False

    monkeypatch.setattr(bridge, "grant_allowed", closed)

    async def run():
        authority = await native.callbacks(client, request, info, runtime)(
            "claim", None, recovery=True
        )
        with pytest.raises(DefinitionMismatch):
            await authority._update(CODING_GRANT, {"scope": request["scope"]})
        assert captured[0][0] == "command"
        assert captured[0][1]["payload"] == {"kind": "cancel", "scope": request["scope"]}
        assert (await authority._update(CODING_STOP, {"scope": request["scope"]}))[
            "admitted"
        ] is True
        assert captured[-1][0] == CODING_STOP
        assert all(name != CODING_GRANT for name, _ in captured)

    asyncio.run(run())


def test_each_original_invocation_has_separate_validation_and_pinned_methods(monkeypatch):
    from relf_agent import temporal_deployment_coding_validation

    created = []

    class FixedValidator(Validator):
        def __init__(self, *args):
            super().__init__(*args)
            created.append(self)

        async def permission(self):
            self.validate = lambda: None
            return True

    monkeypatch.setattr(temporal_deployment_coding_validation, "CodingValidation", FixedValidator)
    _, request = setup()
    request["runtime_manifest"] = {"deployment_admission_protocol": {"version": 3}}
    calls = []

    class Handle:
        async def execute_update(self, *args, **kwargs):
            calls.append(args)

    client = SimpleNamespace(namespace="original", get_workflow_handle=lambda *a, **k: Handle())
    info = SimpleNamespace(workflow_id="r", workflow_run_id="epoch", workflow_namespace="original")
    runtime = SimpleNamespace(validate_release=lambda value: None)

    async def run():
        factory = native.callbacks(client, request, info, runtime)
        first = await factory("first", None, recovery=True)
        second = await factory("second", None, recovery=True)
        assert len(created) == 2 and created[0] is not created[1]
        await first.validate_registration()
        await second.validate_registration()
        with pytest.raises(DefinitionMismatch, match="callbacks changed"):
            await first._update(CODING_GRANT, {})
        assert calls == []
        await second.validate_registration()

    asyncio.run(run())


@pytest.mark.parametrize("foreign", ["runtime", "client", "info", "request", None])
def test_permission_validator_is_bound_to_this_original_grant(monkeypatch, foreign):
    import copy

    from relf_agent import temporal_deployment_coding_validation

    calls = []

    class GrantValidator(Validator):
        async def permission(self):
            calls.append("fresh")
            return True

    monkeypatch.setattr(temporal_deployment_coding_validation, "CodingValidation", GrantValidator)
    _, request = setup()
    runtime, client, info = SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
    value = GrantValidator(runtime, client, copy.deepcopy(request), info)
    if foreign in {"runtime", "client", "info"}:
        setattr(value, "_" + foreign, SimpleNamespace())
    elif foreign == "request":
        value._request["action_id"] = "foreign-action"

    async def run():
        if foreign is not None:
            with pytest.raises(DefinitionMismatch):
                await bridge.grant_allowed(runtime, client, request, info, value)
            assert calls == []
        else:
            assert await bridge.grant_allowed(runtime, client, request, info, value)
            assert await bridge.grant_allowed(runtime, client, request, info, value)
            assert calls == ["fresh", "fresh"]

    asyncio.run(run())


def test_closed_grant_cancel_is_not_retried_and_rechecks_namespace_after_await(monkeypatch):
    from relf_agent import temporal_deployment_coding_validation

    monkeypatch.setattr(temporal_deployment_coding_validation, "CodingValidation", Validator)
    _, request = setup()
    request["runtime_manifest"] = {"deployment_admission_protocol": {"version": 3}}
    calls = []

    class Handle:
        async def execute_update(self, name, payload, **options):
            calls.append(name)
            client.namespace = "replaced"
            return {"recorded": True}

    client = SimpleNamespace(namespace="original", get_workflow_handle=lambda *a, **k: Handle())
    info = SimpleNamespace(workflow_id="r", workflow_run_id="epoch", workflow_namespace="original")
    runtime = SimpleNamespace(validate_release=lambda value: None)

    async def run():
        authority = await native.callbacks(client, request, info, runtime)(
            "claim", None, recovery=True
        )
        with pytest.raises(DefinitionMismatch, match="namespace changed"):
            await authority._update(CODING_GRANT, {})
        assert calls == ["command"]

    asyncio.run(run())
