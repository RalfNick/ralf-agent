"""Only the original Coding4 callback aggregates its own full release checks."""

import asyncio

import pytest

from ralf_agent.temporal_coding_runtime import callbacks
from ralf_agent.types import digest
from tests.test_temporal_session_coding_projection import sdk_session_environment
from tests.test_temporal_session_deployment_control import Client as SessionClient
from tests.test_temporal_session_deployment_control import Handle as SessionHandle


def environment(monkeypatch):
    from ralf_agent import temporal_session_deployment_verification as verification

    original_origin = verification.validate_session_origin
    runtime, client, request, info = sdk_session_environment(monkeypatch)
    # The existing Run/Registry SDK-proof fixture injects origin verification.
    # Restore the real seven-fact Session verifier for this aggregate cost test.
    monkeypatch.setattr(verification, "validate_session_origin", original_origin)
    intent = client.record["intent"]
    session = SessionClient(
        {
            "intent": intent,
            **{key: intent[key] for key in ("namespace", "coordinator_execution_epoch")},
        }
    )
    original_handle = client.get_workflow_handle

    def handle(identity, **options):
        if identity == intent["coordinator_id"]:
            return SessionHandle(session, options.get("run_id"))
        return original_handle(identity, **options)

    client.get_workflow_handle = handle
    client.data_converter = session.data_converter
    request.update(action_id="original-action", release_digest=digest(request["runtime_manifest"]))
    native = {"release_digest": request["release_digest"]}
    native["request_digest"] = digest(native)
    request["coding_request"] = native
    runtime.rebuilds = 0
    validate_release = runtime.validate_release

    def counted(manifest=None):
        runtime.rebuilds += 1
        return validate_release(manifest)

    runtime.validate_release = counted
    return runtime, client, session, request, info


def test_warm_callback_aggregates_coding_checks_but_retains_all_session_sdk_facts(monkeypatch):
    async def run():
        runtime, client, session, request, info = environment(monkeypatch)
        authority = await callbacks(client, request, info, runtime)("original", None, recovery=True)
        await authority.validate_registration()  # Full original bootstrap is unchanged.
        runtime.rebuilds = 0
        client.namespace_reads = 0
        client.calls.clear()
        session.events.clear()
        await authority.validate_registration()
        # Two outer checks plus the real Session verifier's constructor and
        # entry/exit checks. Only CodingValidation's own redundant full checks go.
        assert runtime.rebuilds == 5
        assert client.namespace_reads == 4  # Two Coding plus two Session UUID reads.
        assert session.events == [
            "describe",
            "deployment_session_intent",
            "deployment_session_command",
            "history",
            "describe",
        ]
        assert len([call for call in client.calls if call[0] == "query"]) == 2
        assert len([call for call in client.calls if call[0] == "describe"]) == 2

    asyncio.run(run())


def test_public_validation_and_permission_keep_complete_runtime_checks(monkeypatch):
    from ralf_agent.temporal_deployment_coding_validation import CodingValidation

    async def run():
        runtime, client, session, request, info = environment(monkeypatch)
        validator = CodingValidation(runtime, client, request, info)
        await validator.validate()
        for operation in (validator.validate, validator.permission):
            runtime.rebuilds = 0
            assert await operation() in (None, True)
            assert runtime.rebuilds == 9

    asyncio.run(run())


def test_runtime_drift_during_real_sdk_readset_never_returns_authority(monkeypatch):
    from ralf_agent.errors import DefinitionMismatch

    async def run():
        runtime, client, session, request, info = environment(monkeypatch)
        authority = await callbacks(client, request, info, runtime)("original", None, recovery=True)
        await authority.validate_registration()

        async def changed(identity):
            runtime.changed = True

        client.read_hook = changed
        with pytest.raises(DefinitionMismatch):
            await authority.validate_registration()

    asyncio.run(run())


@pytest.mark.parametrize("when", ["before", "after"])
def test_outer_runtime_check_is_independent_of_private_inner_readset(monkeypatch, when):
    from ralf_agent import temporal_deployment_coding_validation as product
    from ralf_agent.errors import DefinitionMismatch

    entered = []

    class IndependentInner:
        def __init__(self, runtime, client, request, info):
            self.runtime = runtime

        async def validate(self):
            raise AssertionError("Coding4 callback must select its private read set")

        async def permission(self):
            return True

        async def _validate_readset(self):
            # This test intentionally removes all inner resource checking. The
            # real outer callback must still reject before returning authority.
            entered.append("inner")
            self.runtime.changed = True
            return None

    async def run():
        runtime, client, session, request, info = environment(monkeypatch)
        monkeypatch.setattr(product, "CodingValidation", IndependentInner)
        authority = await callbacks(client, request, info, runtime)("original", None, recovery=True)
        runtime.rebuilds = 0
        runtime.changed = when == "before"
        with pytest.raises(DefinitionMismatch):
            await authority.validate_registration()
        assert runtime.rebuilds == (1 if when == "before" else 2)
        assert entered == ([] if when == "before" else ["inner"])
        assert not client.calls and not session.events

    asyncio.run(run())


def test_private_callback_method_remains_pinned_before_sdk_reads(monkeypatch):
    from ralf_agent.errors import DefinitionMismatch
    from ralf_agent.temporal_deployment_coding_validation import CodingValidation

    async def changed(self):
        raise AssertionError("Replaced private validator must not execute")

    async def run():
        runtime, client, session, request, info = environment(monkeypatch)
        authority = await callbacks(client, request, info, runtime)("original", None, recovery=True)
        await authority.validate_registration()
        client.calls.clear()
        session.events.clear()
        monkeypatch.setattr(CodingValidation, "_validate_readset", changed)
        with pytest.raises(DefinitionMismatch):
            await authority.validate_registration()
        assert not client.calls and not session.events

    asyncio.run(run())


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
@pytest.mark.parametrize("method", ["_fresh", "_session_origin"])
def test_full_release_selection_requires_exact_bool_before_sdk_reads(monkeypatch, value, method):
    from ralf_agent.errors import DefinitionMismatch
    from ralf_agent.temporal_deployment_coding_validation import CodingValidation

    async def run():
        runtime, client, session, request, info = environment(monkeypatch)
        validator = CodingValidation(runtime, client, request, info)
        args = (
            ()
            if method == "_fresh"
            else ({key: client.record[key] for key in ("intent", "session_origin")},)
        )
        with pytest.raises(DefinitionMismatch):
            await getattr(validator, method)(*args, _full_release=value)
        assert not client.calls and not session.events

    asyncio.run(run())


def test_publication_three_callback_keeps_public_full_validation(monkeypatch):
    from tests.test_temporal_deployment_coding_validation import environment as legacy

    async def run():
        runtime, client, request, info, bootstrap_reads = legacy(monkeypatch)
        request.update(
            action_id="original-action", release_digest=digest(request["runtime_manifest"])
        )
        native = {"release_digest": request["release_digest"]}
        native["request_digest"] = digest(native)
        request["coding_request"] = native
        runtime.rebuilds = 0
        original = runtime.validate_release

        def counted(manifest=None):
            runtime.rebuilds += 1
            return original(manifest)

        runtime.validate_release = counted
        authority = await callbacks(client, request, info, runtime)("original", None, recovery=True)
        await authority.validate_registration()
        runtime.rebuilds = 0
        assert await authority.validate_registration() is None
        assert runtime.rebuilds == 6

    asyncio.run(run())


def test_default_callback_keeps_original_tree_validator(monkeypatch):
    from types import SimpleNamespace

    from ralf_agent import temporal_session_activities
    from tests.test_temporal_coding_authority import setup
    from tests.test_temporal_session_deployment_control import Runtime

    _, request = setup()
    request["runtime_manifest"] = {}
    events = []

    async def original_tree(client, accepted, *, workflow_id):
        assert accepted == request and workflow_id == request["run_id"]
        events.append("original-tree")

    monkeypatch.setattr(temporal_session_activities, "validate_tree_activity", original_tree)
    runtime = Runtime({})
    client = SimpleNamespace(
        namespace="original", get_workflow_handle=lambda *args, **kwargs: object()
    )
    info = SimpleNamespace(
        workflow_id=request["run_id"],
        workflow_run_id=request["execution_epoch"],
        workflow_namespace="original",
    )

    async def run():
        authority = await callbacks(client, request, info, runtime)("original", None, recovery=True)
        assert await authority.validate_registration() is None
        assert events == ["original-tree"]

    asyncio.run(run())
