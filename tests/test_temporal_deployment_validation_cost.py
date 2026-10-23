"""Bound synchronous release work without caching live SDK permission."""

import asyncio
import copy

import pytest

from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_deployment_admission import registry_id
from relf_agent.temporal_deployment_coding_validation import CodingValidation
from relf_agent.temporal_deployment_execution import _policy
from tests.test_temporal_deployment_coding_validation import (
    POLICY,
    Client,
    Runtime,
    environment,
    seal,
)


@pytest.fixture(autouse=True, scope="module")
def _sdk():
    pytest.importorskip("temporalio")


def test_policy_checks_expected_release_after_capturing_policy_declaration():
    manifest = {"fixed": "original"}
    calls = []

    class ObservedRuntime(Runtime):
        def validate_release(self, expected=None):
            calls.append(copy.deepcopy(expected))
            return super().validate_release(expected)

    runtime = ObservedRuntime(manifest)
    assert _policy(runtime, expected=manifest) == POLICY.identity
    assert calls == [manifest]
    with pytest.raises(DefinitionMismatch):
        _policy(runtime, expected={"fixed": "foreign"})


def test_policy_still_refuses_release_change_during_policy_inspection(monkeypatch):
    from relf_agent.governance import DeploymentAdmissionPolicy

    runtime = Runtime({"fixed": "original"})
    original = DeploymentAdmissionPolicy.identity.fget

    def identity(policy):
        runtime.changed = True
        return original(policy)

    monkeypatch.setattr(DeploymentAdmissionPolicy, "identity", property(identity))
    with pytest.raises(DefinitionMismatch):
        _policy(runtime, expected=runtime.manifest)


@pytest.mark.parametrize("method", ["validate", "permission"])
def test_ready_identity_bootstrap_bounds_release_work_and_refreshes_permissions(
    monkeypatch, method
):
    original = Runtime.validate_release
    counts = []

    def observed(self, expected=None):
        counts.append(copy.deepcopy(expected))
        return original(self, expected)

    monkeypatch.setattr(Runtime, "validate_release", observed)
    runtime, client, request, info, bootstrap_reads = environment(monkeypatch, 1)
    validator = CodingValidation(runtime, client, request, info)

    async def scenario():
        assert await validator.permission()
        before = len(bootstrap_reads)
        counts.clear()
        client.calls.clear()
        client.namespace_reads = 0
        result = await getattr(validator, method)()
        assert result is (None if method == "validate" else True)
        assert len(bootstrap_reads) == before
        assert len(counts) == 2
        assert all(expected == request["runtime_manifest"] for expected in counts)
        assert client.namespace_reads == 2
        queries = [call for call in client.calls if call[0] == "query"]
        assert len(queries) == 3
        assert all(call[3]["kind"] == "deployment_coding_validation" for call in queries)
        assert len([call for call in client.calls if call[0] == "describe"]) == 3
        key = registry_id(POLICY.deployment_id)
        closed = client.compact[key]
        closed.update(close_requested=True, admitted=False)
        client.compact[key] = seal(closed)
        assert await validator.permission() is False
        assert await validator.validate() is None

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["validate", "permission"])
@pytest.mark.parametrize("boundary", ["namespace", "gather"])
@pytest.mark.parametrize("change", ["component", "capacity_policy"])
def test_steady_configuration_drift_finishes_only_original_scope_reads_then_refuses(
    monkeypatch, method, boundary, change
):
    from relf_agent.governance import DeploymentAdmissionPolicy

    original = Client.describe_namespace
    armed = False
    changed = False
    runtime = None

    def drift():
        nonlocal changed
        if changed:
            return
        changed = True
        if change == "component":
            runtime.changed = True
        else:
            replacement = DeploymentAdmissionPolicy(POLICY.deployment_id, max_active_root_runs=3)
            runtime._deployment_admission_policy = replacement
            runtime._deployment_admission_policy_pin = replacement
            runtime._deployment_admission_identity = replacement.identity

    async def namespace(self, request):
        response = await original(self, request)
        if armed and boundary == "namespace":
            await asyncio.sleep(0)
            drift()
        return response

    async def query(_):
        if armed and boundary == "gather":
            await asyncio.sleep(0)
            drift()

    monkeypatch.setattr(Client, "describe_namespace", namespace)
    runtime, client, request, info, _ = environment(monkeypatch, 1)
    validator = CodingValidation(runtime, client, request, info)

    async def scenario():
        nonlocal armed
        await validator.validate()
        client.calls.clear()
        client.namespace_reads = 0
        client.read_hook = query
        armed = True
        usable = []
        with pytest.raises(DefinitionMismatch):
            usable.append(await getattr(validator, method)())
        assert changed and usable == []
        assert client.namespace_reads == 2
        assert len(client.calls) == 6
        assert all(call[0] in {"query", "describe"} for call in client.calls)
        queries = [call for call in client.calls if call[0] == "query"]
        assert all(call[3]["scope"] == request["scope"] for call in queries)
        assert all(call[3]["kind"] == "deployment_coding_validation" for call in queries)
        registry = queries[-1][3]
        assert registry["admission_policy"] == POLICY.identity

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["validate", "permission"])
@pytest.mark.parametrize("boundary", ["namespace", "gather"])
@pytest.mark.parametrize(
    "change", ["client", "service", "claim", "live_claim", "helper", "check", "check_code"]
)
def test_steady_identity_drift_still_stops_at_original_middle_boundary(
    monkeypatch, method, boundary, change
):
    from types import SimpleNamespace

    from temporalio import activity

    original = Client.describe_namespace
    armed = False
    changed = False
    validator = client = info = None
    live = [None]
    monkeypatch.setattr(activity, "info", lambda: live[0])

    def drift():
        nonlocal changed
        if changed:
            return
        changed = True
        if change == "client":
            validator._client = object()
        elif change == "service":
            client.workflow_service = SimpleNamespace()
        elif change == "claim":
            info.attempt = 2
        elif change == "live_claim":
            live[0] = SimpleNamespace(**{**vars(info), "attempt": 2})
        elif change == "helper":
            monkeypatch.setattr(validator, "_node", lambda *args: True)
        elif change == "check":
            monkeypatch.setattr(validator, "_check", lambda *args, **kwargs: None)
        else:

            def fake(self, *args, **kwargs):
                return None

            monkeypatch.setattr(CodingValidation._check, "__code__", fake.__code__)

    async def namespace(self, request):
        response = await original(self, request)
        if armed and boundary == "namespace":
            await asyncio.sleep(0)
            drift()
        return response

    async def query(_):
        if armed and boundary == "gather":
            await asyncio.sleep(0)
            drift()

    monkeypatch.setattr(Client, "describe_namespace", namespace)
    runtime, client, request, info, _ = environment(monkeypatch, 1)
    live[0] = info
    validator = CodingValidation(runtime, client, request, info)

    async def scenario():
        nonlocal armed
        await validator.validate()
        client.calls.clear()
        client.namespace_reads = 0
        client.read_hook = query
        armed = True
        with pytest.raises(DefinitionMismatch):
            await getattr(validator, method)()
        assert changed
        assert client.namespace_reads == 1
        assert len(client.calls) == (0 if boundary == "namespace" else 6)
        assert all(call[0] in {"query", "describe"} for call in client.calls)

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["validate", "permission"])
@pytest.mark.parametrize("replace_class", [False, True])
def test_fake_fresh_and_fake_check_together_cannot_bypass_public_exit(
    monkeypatch, method, replace_class
):
    runtime, client, request, info, _ = environment(monkeypatch, 1)
    validator = CodingValidation(runtime, client, request, info)

    async def scenario():
        await validator.validate()
        client.calls.clear()
        client.namespace_reads = 0

        async def fake_fresh(*args):
            return True

        target = CodingValidation if replace_class else validator
        monkeypatch.setattr(target, "_fresh", fake_fresh)
        monkeypatch.setattr(target, "_check", lambda *args, **kwargs: None)
        with pytest.raises(DefinitionMismatch):
            await getattr(validator, method)()
        assert client.calls == [] and client.namespace_reads == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["validate", "permission"])
def test_mutated_check_keyword_default_cannot_make_public_boundaries_light(monkeypatch, method):
    runtime, client, request, info, _ = environment(monkeypatch, 1)
    validator = CodingValidation(runtime, client, request, info)

    async def scenario():
        await validator.validate()
        monkeypatch.setattr(CodingValidation._check, "__kwdefaults__", {"full": False})
        runtime.changed = True
        client.calls.clear()
        client.namespace_reads = 0
        with pytest.raises(DefinitionMismatch):
            await getattr(validator, method)()
        assert client.calls == [] and client.namespace_reads == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["validate", "permission"])
@pytest.mark.parametrize("replace_class", [False, True])
def test_public_callback_refuses_replaced_fresh_before_business(monkeypatch, method, replace_class):
    runtime, client, request, info, _ = environment(monkeypatch, 1)
    validator = CodingValidation(runtime, client, request, info)

    async def scenario():
        await validator.validate()
        client.calls.clear()
        client.namespace_reads = 0
        business = []

        async def false_fresh(*args):
            return True

        monkeypatch.setattr(CodingValidation if replace_class else validator, "_fresh", false_fresh)
        with pytest.raises(DefinitionMismatch):
            await getattr(validator, method)()
            business.append("native-grant")
        assert business == []
        assert client.calls == []
        assert client.namespace_reads == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["validate", "permission"])
@pytest.mark.parametrize("change", ["release", "runtime_port", "helper_port", "activity"])
def test_last_namespace_await_keeps_public_post_io_guard(monkeypatch, method, change):
    original = Client.describe_namespace
    armed = False
    boundary = 0
    runtime = info = validator = None

    async def namespace(self, request):
        nonlocal boundary
        response = await original(self, request)
        if armed:
            boundary += 1
            if boundary == 2:
                await asyncio.sleep(0)
                if change == "release":
                    runtime.changed = True
                elif change == "runtime_port":
                    monkeypatch.setattr(runtime, "validate_release", lambda expected=None: None)
                elif change == "helper_port":
                    monkeypatch.setattr(validator, "_node", lambda *args: True)
                else:
                    info.attempt = 2
        return response

    monkeypatch.setattr(Client, "describe_namespace", namespace)
    runtime, client, request, info, _ = environment(monkeypatch, 1)
    validator = CodingValidation(runtime, client, request, info)

    async def scenario():
        nonlocal armed
        await validator.validate()
        client.calls.clear()
        client.namespace_reads = 0
        armed = True
        business = []
        with pytest.raises(DefinitionMismatch):
            await getattr(validator, method)()
            business.append("native-grant")
        assert business == []
        assert boundary == client.namespace_reads == 2
        assert len([call for call in client.calls if call[0] == "query"]) == 3
        assert len([call for call in client.calls if call[0] == "describe"]) == 3
        assert not any(call[0] == "update" for call in client.calls)

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["validate", "permission"])
@pytest.mark.parametrize("helper", ["_node", "_registry", "_description"])
def test_sync_dto_processing_release_drift_is_refused_without_further_io(
    monkeypatch, method, helper
):
    original = getattr(CodingValidation, helper)
    armed = False
    runtime = client = None
    mutations = []

    def process(self, *args):
        result = original(self, *args)
        if armed:
            runtime.changed = True
            mutations.append((len(client.calls), client.namespace_reads))
        return result

    monkeypatch.setattr(CodingValidation, helper, process)
    runtime, client, request, info, _ = environment(monkeypatch, 1)
    validator = CodingValidation(runtime, client, request, info)

    async def scenario():
        nonlocal armed
        await validator.validate()
        client.calls.clear()
        client.namespace_reads = 0
        armed = True
        business = []
        with pytest.raises(DefinitionMismatch):
            await getattr(validator, method)()
            business.append("native-grant")
        assert business == []
        assert mutations and all(at == (6, 2) for at in mutations)
        assert len(client.calls) == 6
        assert client.namespace_reads == 2
        assert not any(call[0] == "update" for call in client.calls)

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["bootstrap_method", "snapshot", "release_during_read"])
def test_ready_bootstrap_keeps_method_snapshot_and_await_guards(monkeypatch, change):
    runtime, client, request, info, _ = environment(monkeypatch, 1)
    validator = CodingValidation(runtime, client, request, info)

    async def scenario():
        await validator.validate()
        client.calls.clear()
        if change == "bootstrap_method":

            async def replaced():
                return None

            monkeypatch.setattr(validator, "_bootstrap", replaced)
        elif change == "snapshot":
            validator._snapshot["registry_epoch"] = "foreign"
        else:

            async def release_changes(_):
                runtime.manifest["providers"] = {"foreign": {"version": "changed"}}

            client.read_hook = release_changes
        with pytest.raises(DefinitionMismatch):
            await validator.permission()
        if change != "release_during_read":
            assert not client.calls
        assert not any(call[0] == "update" for call in client.calls)

    asyncio.run(scenario())
