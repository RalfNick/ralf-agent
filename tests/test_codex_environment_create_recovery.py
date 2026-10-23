"""Opt-in original create recovery never treats an empty list as completion."""

import asyncio
import json
import os

import pytest

from relf_agent.codex_environment import DockerCodingEnvironment
from relf_agent.errors import DefinitionMismatch, ExecutionHostFailed, ValidationError
from tests.test_codex_environment import load
from tests.test_codex_environment import resource as resource


def environment(resource, **options):
    root, cli = resource
    return DockerCodingEnvironment(
        root,
        "test-retained",
        docker_executable=str(cli),
        docker_host="unix:///fixture/docker.sock",
        retire_on_stop=True,
        expected_generation="a" * 32,
        create_recovery=True,
        **options,
    )


def crash_lease(owner):
    """Fixture crash boundary; no product cleanup or negative stop evidence."""
    if owner._lease is not None:
        os.close(owner._lease)
        owner._lease = None


def metadata(resource):
    return json.loads((resource[0] / "environment.json").read_text())


def lose_create(owner, *, completed, calls):
    original = owner._cli

    def execute(args):
        calls.append(list(args))
        if args[0] == "create":
            assert metadata((owner._root, None))["create_operation"]["phase"] == "submitted"
            if completed:
                original(args)
            raise ExecutionHostFailed("Original create reply was lost")
        return original(args)

    owner._cli = execute


def test_optin_identity_and_durable_create_phase_precede_single_submission(resource):
    async def run():
        owner = environment(resource)
        calls = []
        original = owner._cli

        def execute(args):
            calls.append(list(args))
            if args[0] == "create":
                operation = metadata(resource)["create_operation"]
                assert operation["version"] == 1 and operation["phase"] == "submitted"
                assert len(operation["operation_digest"]) == 64
            return original(args)

        owner._cli = execute
        try:
            assert owner.identity["create_operation_version"] == 1
            prepared = await owner.prepare()
            assert metadata(resource)["create_operation"]["phase"] == "located"
            assert metadata(resource)["container_id"] == prepared["container_id"]
            assert (await owner.prepare())["container_id"] == prepared["container_id"]
            assert sum(args[0] == "create" for args in calls) == 1
            await owner.aclose()
        finally:
            crash_lease(owner)

    asyncio.run(run())


@pytest.mark.parametrize("value", [1, None, "true", {}])
def test_create_recovery_requires_exact_boolean(resource, value):
    root, cli = resource
    with pytest.raises(ValidationError):
        DockerCodingEnvironment(
            root,
            "original",
            docker_executable=str(cli),
            docker_host="unix:///fixture/docker.sock",
            create_recovery=value,
        )
    assert not tuple(root.iterdir())


def test_create_recovery_requires_retirement(resource):
    root, cli = resource
    with pytest.raises(ValidationError):
        DockerCodingEnvironment(
            root,
            "original",
            docker_executable=str(cli),
            docker_host="unix:///fixture/docker.sock",
            create_recovery=True,
        )
    assert not tuple(root.iterdir())


def test_lost_create_reply_positive_cold_recovery_stops_only_original_cid(resource):
    async def run():
        original = environment(resource)
        calls = []
        lose_create(original, completed=True, calls=calls)
        try:
            with pytest.raises(ExecutionHostFailed):
                await original.prepare()
            assert metadata(resource)["container_id"] is None
            cid = next(iter(load(resource)["containers"]))
        finally:
            crash_lease(original)
        cold = environment(resource)
        original_cli = cold._cli

        def control_only(args):
            assert args[0] not in {"create", "start"}
            if (
                args[0] == "ps"
                and "--filter" in args
                and not any(arg.startswith("id=") for arg in args)
            ):
                assert "name=^/" + cold._name + "$" in args
                assert all(
                    "label=" + key + "=" + value in args for key, value in cold._labels().items()
                )
            return original_cli(args)

        cold._cli = control_only
        try:
            stopped = await cold.stop_existing()
            assert stopped["container_id"] == cid and stopped["fenced"] and stopped["retired"]
            assert metadata(resource)["create_operation"]["phase"] == "located"
            assert load(resource)["creates"] == 1 and load(resource)["removed"] == [cid]
            with pytest.raises(ValidationError):
                cold.transport_argv()
            await cold.aclose()
        finally:
            crash_lease(cold)

    asyncio.run(run())


def test_submitted_empty_queries_remain_held_without_create_or_absence(resource):
    async def run():
        owner = environment(resource)
        calls = []
        lose_create(owner, completed=False, calls=calls)
        try:
            for _ in range(2):
                with pytest.raises(ExecutionHostFailed):
                    await owner.prepare()
            assert sum(args[0] == "create" for args in calls) == 1
            assert metadata(resource)["create_operation"]["phase"] == "submitted"
            with pytest.raises(ExecutionHostFailed):
                await owner.aclose()
            assert owner._lease is not None
        finally:
            crash_lease(owner)
        cold = environment(resource)
        try:
            for _ in range(2):
                with pytest.raises(ExecutionHostFailed):
                    await cold.stop_existing()
            with pytest.raises(ValidationError):
                await cold.observe_namespace_absence()
            with pytest.raises(ValidationError):
                await cold.prepare()
            assert cold._lease is not None and metadata(resource)["container_id"] is None
        finally:
            crash_lease(cold)

    asyncio.run(run())


def test_late_original_locator_can_be_controlled_after_negative_query(resource):
    async def run():
        owner = environment(resource)
        calls = []
        lose_create(owner, completed=True, calls=calls)
        try:
            with pytest.raises(ExecutionHostFailed):
                await owner.prepare()
        finally:
            crash_lease(owner)
        cold = environment(resource)
        original = cold._cli
        visible = False

        def execute(args):
            assert args[0] not in {"create", "start"}
            if args[0] == "ps" and not visible:
                return b"", b""
            return original(args)

        cold._cli = execute
        try:
            with pytest.raises(ExecutionHostFailed):
                await cold.stop_existing()
            assert cold._lease is not None and metadata(resource)["container_id"] is None
            visible = True
            assert (await cold.stop_existing())["fenced"]
            assert load(resource)["creates"] == 1
            await cold.aclose()
        finally:
            crash_lease(cold)

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    [
        "multiple",
        "malformed",
        "foreign_generation",
        "foreign_name",
        "foreign_mount",
        "foreign_image",
    ],
)
def test_cold_candidate_must_be_unique_and_fully_original_before_persist_or_stop(resource, fault):
    async def run():
        owner = environment(resource)
        calls = []
        lose_create(owner, completed=True, calls=calls)
        try:
            with pytest.raises(ExecutionHostFailed):
                await owner.prepare()
        finally:
            crash_lease(owner)
        database = load(resource)
        cid, container = next(iter(database["containers"].items()))
        if fault == "foreign_generation":
            container["Config"]["Labels"]["ralf.coding.generation"] = "b" * 32
        elif fault == "foreign_name":
            container["Name"] = "/foreign"
        elif fault == "foreign_mount":
            container["Mounts"][0]["Source"] = "/foreign"
        elif fault == "foreign_image":
            container["Image"] = "sha256:" + "b" * 64
        (resource[1].parent / "docker.json").write_text(json.dumps(database))
        before = (resource[0] / "environment.json").read_bytes()
        cold = environment(resource)
        actual = cold._cli

        def execute(args):
            assert args[0] not in {"create", "start", "kill", "rm"}
            if args[0] == "ps" and fault in {"multiple", "malformed"}:
                return (
                    (cid + "\n" + "b" * 64).encode() if fault == "multiple" else b"not-a-CID"
                ), b""
            return actual(args)

        cold._cli = execute
        try:
            with pytest.raises((DefinitionMismatch, ExecutionHostFailed)):
                await cold.stop_existing()
            assert (resource[0] / "environment.json").read_bytes() == before
            assert cold._metadata["container_id"] is None and cold._lease is not None
        finally:
            crash_lease(cold)

    asyncio.run(run())


def test_submission_fsync_failure_cannot_send_create(resource, monkeypatch):
    async def run():
        owner = environment(resource)
        actual = os.fsync
        calls = []
        original_cli = owner._cli

        def persist(fd):
            if (owner._metadata or {}).get("create_operation", {}).get("phase") == "submitted":
                raise OSError("durable create admission failed")
            actual(fd)

        def execute(args):
            calls.append(args[0])
            return original_cli(args)

        monkeypatch.setattr(os, "fsync", persist)
        owner._cli = execute
        try:
            with pytest.raises(OSError):
                await owner.prepare()
            assert "create" not in calls
            assert metadata(resource)["create_operation"]["phase"] == "intent"
        finally:
            crash_lease(owner)

    asyncio.run(run())


def test_positive_original_running_object_is_stopped_without_start_or_prepare(resource):
    async def run():
        owner = environment(resource)
        calls = []
        lose_create(owner, completed=True, calls=calls)
        try:
            with pytest.raises(ExecutionHostFailed):
                await owner.prepare()
        finally:
            crash_lease(owner)
        database = load(resource)
        cid = next(iter(database["containers"]))
        database["containers"][cid]["State"].update(
            Running=True, Pid=123, Status="running", StartedAt="2026-10-14T00:00:01Z"
        )
        (resource[1].parent / "docker.json").write_text(json.dumps(database))
        cold = environment(resource)
        actual = cold._cli
        calls.clear()

        def execute(args):
            calls.append(list(args))
            assert args[0] not in {"create", "start"}
            if args[0] in {"kill", "rm"}:
                assert args[-1] == cid
            return actual(args)

        cold._cli = execute
        try:
            assert (await cold.stop_existing())["fenced"]
            assert any(args[0] == "kill" for args in calls)
            assert load(resource)["creates"] == 1 and load(resource)["removed"] == [cid]
            await cold.aclose()
        finally:
            crash_lease(cold)

    asyncio.run(run())


def test_intent_before_submission_stays_distinct_and_close_cannot_create(resource):
    async def run():
        owner = environment(resource)
        calls = []

        def unavailable(args):
            calls.append(args[0])
            raise ExecutionHostFailed("Initial inventory unavailable")

        owner._cli = unavailable
        try:
            with pytest.raises(ExecutionHostFailed):
                await owner.prepare()
            assert metadata(resource)["create_operation"]["phase"] == "intent"
            with pytest.raises(ExecutionHostFailed):
                await owner.aclose()
            assert "create" not in calls and owner._lease is not None
        finally:
            crash_lease(owner)

    asyncio.run(run())


def test_cold_locator_fsync_failure_cannot_stop_before_durable_locator(resource, monkeypatch):
    async def run():
        owner = environment(resource)
        calls = []
        lose_create(owner, completed=True, calls=calls)
        try:
            with pytest.raises(ExecutionHostFailed):
                await owner.prepare()
        finally:
            crash_lease(owner)
        cold = environment(resource)
        actual = os.fsync
        actual_cli = cold._cli
        calls.clear()

        def persist(fd):
            if cold._metadata["create_operation"]["phase"] == "located":
                raise OSError("Original recovered locator could not be fsynced")
            actual(fd)

        def control(args):
            calls.append(args[0])
            return actual_cli(args)

        monkeypatch.setattr(os, "fsync", persist)
        cold._cli = control
        try:
            with pytest.raises(OSError):
                await cold.stop_existing()
            assert set(calls) <= {"ps", "inspect"}
            assert metadata(resource)["container_id"] is None
            assert cold._metadata["container_id"] is None and cold._lease is not None
            monkeypatch.setattr(os, "fsync", actual)
            assert (await cold.stop_existing())["fenced"]
            assert load(resource)["creates"] == 1
            await cold.aclose()
        finally:
            crash_lease(cold)

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["missing", "foreign_digest", "version_bool", "foreign_phase", "extra"]
)
def test_optin_metadata_cannot_omit_or_rebind_create_operation(resource, fault):
    async def run():
        owner = environment(resource)
        try:
            await owner.prepare()
        finally:
            crash_lease(owner)
        value = metadata(resource)
        if fault == "missing":
            value.pop("create_operation")
        elif fault == "foreign_digest":
            value["create_operation"]["operation_digest"] = "b" * 64
        elif fault == "version_bool":
            value["create_operation"]["version"] = True
        elif fault == "foreign_phase":
            value["create_operation"]["phase"] = "unknown"
        else:
            value["create_operation"]["foreign"] = True
        (resource[0] / "environment.json").write_text(json.dumps(value))
        cold = environment(resource)
        cold._cli = lambda args: pytest.fail("Malformed create operation reached Docker")
        try:
            with pytest.raises(DefinitionMismatch):
                await cold.stop_existing()
        finally:
            crash_lease(cold)

    asyncio.run(run())


def test_false_create_recovery_preserves_legacy_identity_and_metadata_shape(resource):
    root, cli = resource
    options = dict(
        docker_executable=str(cli),
        docker_host="unix:///fixture/docker.sock",
        retire_on_stop=True,
        expected_generation="a" * 32,
    )
    omitted = DockerCodingEnvironment(root, "test-retained", **options)
    disabled = DockerCodingEnvironment(root, "test-retained", create_recovery=False, **options)
    assert omitted.identity == disabled.identity
    assert "create_operation_version" not in omitted.identity

    async def run():
        try:
            await disabled.prepare()
            assert set(metadata(resource)) == {
                "identity",
                "generation",
                "container_id",
                "files",
                "lease_pin",
                "last_state",
                "retirement",
            }
            await disabled.aclose()
        finally:
            crash_lease(disabled)

    asyncio.run(run())
