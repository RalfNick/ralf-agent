"""Closing permits only this build's original, pinned maintenance handlers."""

import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import Scope
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal_assembly_lifecycle import WorkerExecutionOwner


@pytest.fixture(autouse=True)
def sdk():
    pytest.importorskip("temporalio")


def setup(monkeypatch):
    from temporalio import activity

    from ralf_agent import temporal_deployment_release as release

    manifest = {"deployment_admission_protocol": {"version": 3}}
    runtime = SimpleNamespace(orchestration_release=manifest)
    runtime.validate_release = lambda expected=None: manifest
    client = SimpleNamespace(namespace="original")
    info = SimpleNamespace(
        workflow_id="original-root",
        workflow_run_id="original-epoch",
        workflow_namespace="original",
        activity_id="release:0",
        attempt=1,
        activity_type=release.RELEASE_ACTIVITY,
    )
    monkeypatch.setattr(activity, "info", lambda: info)
    calls = []

    async def execute(runtime, client, request, info):
        calls.append(request["mode"])
        return {"original": True}

    monkeypatch.setattr(release, "execute", execute)
    original = release.registered_activity(runtime, client)
    owner = WorkerExecutionOwner(scope=Scope(), release=manifest)
    wrapped = owner.wrap_activities(
        [original], client=client, runtime=runtime, maintenance=((original, "release"),)
    )[0]
    request = {
        "scope": asdict(Scope()),
        "mode": "release",
        "run_id": "original-root",
        "execution_epoch": "original-epoch",
    }
    return owner, wrapped, original, runtime, client, info, request, calls


@pytest.mark.parametrize("mode", ["release", "verify"])
def test_original_maintenance_is_owned_while_business_admission_closed(monkeypatch, mode):
    async def run():
        owner, wrapped, _, _, _, _, request, calls = setup(monkeypatch)
        owner.stop_admission()
        request["mode"] = mode
        try:
            assert await wrapped(request) == {"ok": True, "result": {"original": True}}
            assert calls == [mode]
            with pytest.raises(ValidationError):
                await owner.execute(lambda: None, info=SimpleNamespace(), request=request)
        finally:
            await owner.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["control", "scope", "namespace", "sdk-type", "code", "closure"])
def test_closing_maintenance_refuses_drift_before_handler(monkeypatch, change):
    async def run():
        owner, wrapped, original, _, client, info, request, calls = setup(monkeypatch)
        owner.stop_admission()
        if change == "control":
            request["mode"] = "control"
        elif change == "scope":
            request["scope"] = asdict(Scope("foreign", "owner"))
        elif change == "namespace":
            client.namespace = "foreign"
        elif change == "sdk-type":
            info.activity_type = "other"
        elif change == "code":
            # Preserve the free-variable count while replacing executable code.
            original.__code__ = original.__code__.replace(co_name="foreign")
        else:
            original.__closure__[0].cell_contents = object()
        try:
            with pytest.raises((DefinitionMismatch, ValidationError)):
                await wrapped(request)
            assert calls == []
        finally:
            await owner.aclose()

    asyncio.run(run())


def test_control_verification_remains_available_before_close(monkeypatch):
    async def run():
        owner, wrapped, _, _, _, _, request, calls = setup(monkeypatch)
        request["mode"] = "control"
        try:
            assert (await wrapped(request))["ok"] is True
            assert calls == ["control"]
        finally:
            await owner.aclose()

    asyncio.run(run())


def test_same_name_and_copied_marker_do_not_select_maintenance(monkeypatch):
    from temporalio import activity

    async def run():
        owner, _, original, runtime, client, _, request, calls = setup(monkeypatch)

        @activity.defn(name="ralf.temporal.deployment-release.v2")
        async def fake(value: dict) -> dict:
            calls.append("fake")
            return {}

        fake.__ralf_deployment_release__ = original.__ralf_deployment_release__
        wrapped = owner.wrap_activities(
            [fake], client=client, runtime=runtime, maintenance=((original, "release"),)
        )[0]
        owner.stop_admission()
        try:
            with pytest.raises(ValidationError):
                await wrapped(request)
            assert calls == []
        finally:
            await owner.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["function-code", "sdk-epoch"])
def test_pins_rechecked_after_maintenance_await(monkeypatch, change):
    from ralf_agent import temporal_deployment_release as release

    async def run():
        owner, wrapped, original, _, _, info, request, calls = setup(monkeypatch)

        async def execute(*args):
            calls.append("started")
            if change == "function-code":
                original.__code__ = original.__code__.replace(co_name="foreign")
            else:
                info.workflow_run_id = "replacement-epoch"
            await asyncio.sleep(0)
            return {}

        monkeypatch.setattr(release, "execute", execute)
        owner.stop_admission()
        try:
            with pytest.raises(DefinitionMismatch):
                await wrapped(request)
            assert calls == ["started"]
        finally:
            await owner.aclose()

    asyncio.run(run())


def test_original_cold_stop_verifier_remains_owned_during_close(monkeypatch):
    from temporalio import activity

    from ralf_agent import temporal_deployment_coding_bridge as bridge

    async def run():
        owner, _, _, runtime, client, info, _, calls = setup(monkeypatch)
        info.activity_type = bridge.STOP_ACTIVITY

        async def verify(runtime, client, request, actual):
            assert actual is info
            calls.append("original-stop")
            return {"stopped": True}

        monkeypatch.setattr(bridge, "verify_call_stop", verify)
        original = bridge.registered_stop_activity(runtime, client)
        wrapped = owner.wrap_activities(
            [original], client=client, runtime=runtime, maintenance=((original, "stop"),)
        )[0]
        assert activity._Definition.from_callable(wrapped).name == bridge.STOP_ACTIVITY
        owner.stop_admission()
        try:
            assert await wrapped({"scope": asdict(Scope()), "identity": {}}) == {
                "ok": True,
                "result": {"stopped": True},
            }
            assert calls == ["original-stop"]
        finally:
            await owner.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["observe", "cancel", "register", "recover"])
def test_closing_original_control_keeps_universal_proof_and_end_ack(monkeypatch, mode):
    import temporalio.worker
    from temporalio import activity

    from ralf_agent import temporal_activities as activities
    from ralf_agent import temporal_control_activities as controls
    from ralf_agent import temporal_deployment_execution as execution
    from ralf_agent import temporal_session_activities as sessions
    from ralf_agent.temporal import build_temporal_worker
    from tests.test_temporal_deployment_coding_release import environment

    async def run():
        runtime, client, state, proof, info, _ = environment(monkeypatch)
        runtime.orchestration_release = runtime.manifest
        runtime.parent_completion_policies = {}
        info.activity_type = "ralf.temporal.control.v1"
        monkeypatch.setattr(activity, "info", lambda: info)
        calls = []

        async def validate(runtime, client, request, actual):
            assert actual is info
            calls.append("fresh-original-sdk-proof")
            return proof

        async def control(runtime, client, value, actual):
            assert value["mode"] == mode and actual is info
            calls.append(mode)
            return {"original": True}

        monkeypatch.setattr(execution, "validate_activity", validate)
        monkeypatch.setattr(controls, "control", control)
        owner = WorkerExecutionOwner(scope=Scope(**state.scope), release=runtime.manifest)
        captured = {}
        monkeypatch.setattr(activities, "TemporalRuntime", type(runtime))
        monkeypatch.setattr(activities, "registered_activities", lambda *args: [])
        monkeypatch.setattr(sessions, "registered_session_activities", lambda *args: [])
        monkeypatch.setattr(
            temporalio.worker, "Worker", lambda *args, **kwargs: captured.update(kwargs)
        )
        build_temporal_worker(
            client, task_queue="original-queue", runtime=runtime, activity_owner=owner
        )
        wrapped = next(
            function
            for function in captured["activities"]
            if activity._Definition.from_callable(function).name == info.activity_type
        )
        owner.stop_admission()
        carrier = {
            "scope": state.scope,
            "_deployment_activity_request": {"scope": state.scope, "mode": mode},
        }
        try:
            if mode in {"register", "recover"}:
                with pytest.raises(DefinitionMismatch):
                    await wrapped(carrier)
                assert calls == []
            else:
                assert await wrapped(carrier) == {"ok": True, "result": {"original": True}}
                assert calls == ["fresh-original-sdk-proof", mode]
                assert await runtime._deployment_execution_owner.wait(wait_timeout=2)
                assert all(record["stopped"] for record in state.deployment_calls.values())
        finally:
            await owner.aclose()
            await runtime._deployment_execution_owner.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        None,
        "same-name",
        "code",
        "after-code",
        "after-epoch",
        "after-tree-code",
        "after-tree-closure",
        "after-tree-validator-code",
        "business",
    ],
)
def test_closing_original_native_stop_keeps_sdk_guard_stop_and_end_ack(monkeypatch, change):
    import temporalio.worker
    from temporalio import activity

    from ralf_agent import temporal_activities as activities
    from ralf_agent import temporal_bindings as bindings
    from ralf_agent import temporal_coding_runtime as coding
    from ralf_agent import temporal_deployment_execution as execution
    from ralf_agent import temporal_session_activities as sessions
    from ralf_agent.temporal import build_temporal_worker
    from ralf_agent.temporal_coding_state import CODING_STOP_ACTIVITY
    from tests.test_temporal_deployment_coding_release import environment

    async def run():
        runtime, client, state, proof, info, _ = environment(monkeypatch)
        runtime.orchestration_release = runtime.manifest
        runtime.parent_completion_policies = {}
        runtime.model_continuation = False
        runtime.coding_execution = True
        info.activity_type = CODING_STOP_ACTIVITY
        monkeypatch.setattr(activity, "info", lambda: info)
        calls, captured, registered = [], {}, []

        async def validate(runtime, client, request, actual):
            assert actual is info
            calls.append("fresh-original-sdk-proof")
            return proof

        async def tree(*args, **kwargs):
            calls.append("original-tree")

        async def stop(selected, request, callbacks):
            assert selected is runtime and callbacks == "original-callbacks"
            calls.append("original-native-stop")
            if change == "after-code":
                registered[0].__code__ = registered[0].__code__.replace(co_name="foreign")
            elif change == "after-epoch":
                info.workflow_run_id = "replacement-epoch"
            elif change in {"after-tree-code", "after-tree-closure", "after-tree-validator-code"}:
                cells = dict(
                    zip(registered[0].__code__.co_freevars, registered[0].__closure__, strict=True)
                )
                tree = cells["tree_guard"].cell_contents
                if change == "after-tree-code":
                    tree.__code__ = tree.__code__.replace(co_name="foreign")
                else:
                    tree_cells = dict(zip(tree.__code__.co_freevars, tree.__closure__, strict=True))
                    validator = tree_cells["validate_tree_activity"]
                    if change == "after-tree-closure":
                        validator.cell_contents = object()
                    else:
                        validator.cell_contents.__code__ = validator.cell_contents.__code__.replace(
                            co_name="foreign"
                        )
            await asyncio.sleep(0)
            return {"fenced": True}

        monkeypatch.setattr(execution, "validate_activity", validate)
        monkeypatch.setattr(sessions, "validate_tree_activity", tree)
        monkeypatch.setattr(bindings, "selected_runtime", lambda *args: runtime)
        monkeypatch.setattr(coding, "callbacks", lambda *args: "original-callbacks")
        monkeypatch.setattr(coding, "stop", stop)
        monkeypatch.setattr(activities, "TemporalRuntime", type(runtime))
        monkeypatch.setattr(sessions, "registered_session_activities", lambda *args: [])
        monkeypatch.setattr(
            temporalio.worker, "Worker", lambda *args, **kwargs: captured.update(kwargs)
        )
        owner = WorkerExecutionOwner(scope=Scope(**state.scope), release=runtime.manifest)
        build_temporal_worker(
            client, task_queue="original-queue", runtime=runtime, activity_owner=owner
        )
        wrapped = next(
            f
            for f in captured["activities"]
            if activity._Definition.from_callable(f).name == CODING_STOP_ACTIVITY
        )
        registered.append(wrapped.__wrapped__.__wrapped__)
        if change == "business":
            from ralf_agent.temporal_state import TOOL_ACTIVITY

            info.activity_type = TOOL_ACTIVITY
            wrapped = next(
                f
                for f in captured["activities"]
                if activity._Definition.from_callable(f).name == TOOL_ACTIVITY
            )
        if change == "same-name":

            @activity.defn(name=CODING_STOP_ACTIVITY)
            async def fake(request: dict) -> dict:
                calls.append("fake")
                return {}

            fake.__dict__.update(registered[0].__dict__)
            wrapped = owner.wrap_activities(
                [fake],
                client=client,
                runtime=runtime,
                maintenance=((registered[0], "native-stop"),),
            )[0]
        elif change == "code":
            registered[0].__code__ = registered[0].__code__.replace(co_name="foreign")
        owner.stop_admission()
        carrier = {"scope": state.scope, "_deployment_activity_request": {"scope": state.scope}}
        try:
            if change is None:
                assert await wrapped(carrier) == {"fenced": True}
                assert calls == [
                    "fresh-original-sdk-proof",
                    "original-tree",
                    "original-native-stop",
                ]
                assert all(record["stopped"] for record in state.deployment_calls.values())
            else:
                with pytest.raises((DefinitionMismatch, ValidationError)):
                    await wrapped(carrier)
                if change in {"same-name", "code", "business"}:
                    assert calls == []
                else:
                    assert calls == [
                        "fresh-original-sdk-proof",
                        "original-tree",
                        "original-native-stop",
                    ]
        finally:
            # Restoring the test double allows the original rejected end ACK
            # to drain; production drift remains owned rather than forgotten.
            info.workflow_run_id = proof["execution_epoch"]
            await owner.aclose()
            if getattr(runtime, "_deployment_execution_owner", None) is not None:
                await runtime._deployment_execution_owner.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("publication", [2, 3])
def test_explicit_same_name_native_stop_maintenance_is_not_factory_registration(
    monkeypatch, publication
):
    from temporalio import activity

    from ralf_agent.temporal_coding_state import CODING_STOP_ACTIVITY

    owner, _, _, runtime, client, _, _, calls = setup(monkeypatch)
    runtime.orchestration_release["deployment_admission_protocol"]["version"] = publication

    @activity.defn(name=CODING_STOP_ACTIVITY)
    async def fake(request: dict) -> dict:
        calls.append("fake")
        return {}

    with pytest.raises(DefinitionMismatch):
        owner.wrap_activities(
            [fake], client=client, runtime=runtime, maintenance=((fake, "native-stop"),)
        )
    assert calls == []


def test_original_native_stop_without_universal_admission_wrapper_is_refused(monkeypatch):
    from temporalio import activity

    from ralf_agent.temporal_activities import registered_activities
    from ralf_agent.temporal_coding_state import CODING_STOP_ACTIVITY

    owner, _, _, runtime, client, _, _, calls = setup(monkeypatch)
    runtime.model_continuation, runtime.coding_execution = False, True
    original = next(
        f
        for f in registered_activities(runtime, client)
        if activity._Definition.from_callable(f).name == CODING_STOP_ACTIVITY
    )
    with pytest.raises(DefinitionMismatch):
        owner.wrap_activities(
            [original], client=client, runtime=runtime, maintenance=((original, "native-stop"),)
        )
    assert calls == []
