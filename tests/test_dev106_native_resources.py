"""Finite resource receipts and explicit asynchronous native entrypoints."""

import asyncio
import copy
import importlib

import pytest

from relf_agent.codex_runner import CodexCodingRunner
from relf_agent.errors import AuthorizationDenied, IdempotencyConflict, ValidationError
from relf_agent.types import digest
from tests.test_codex_runner import envelope, runner
from tests.test_codex_runner import runner_parts as runner_parts
from tests.test_postgres_runner_journal import journals, unopened
from tests.test_postgres_runner_journal import postgres_dsn as postgres_dsn


def resource_rules():
    spec = importlib.util.find_spec("relf_agent.postgres_coding_resources")
    assert spec is not None, "Missing original PG resource-intent rules"
    return importlib.import_module("relf_agent.postgres_coding_resources")


def intent():
    from relf_agent.codex_runner import _dispatch

    value = envelope()
    request = {
        "dispatch": _dispatch(value),
        "release_digest": "release",
        "reservation": {"id": "attempt", "amount": 1},
        "definition_digest": "definition",
        "deadline": None,
    }
    request["request_digest"] = digest(request)
    identity = {"kind": "runner", "version": "1"}
    namespace = {
        "request": request,
        "runner": identity,
        "dispatch": request["dispatch"],
        "environment": {
            "kind": "docker-coding-environment",
            "version": "2",
            "expected_generation": "a" * 32,
            "retire_on_stop": True,
            "resource_id": "resource",
        },
    }
    return ("coding", "owner", "effect"), request, identity, namespace


def receipt(namespace, *, stopped=False):
    return {
        "identity": namespace["environment"],
        "container_id": "c" * 64,
        "generation": "a" * 32,
        "resource_id": "resource",
        "running": False,
        "pid": 0,
        "stopped": True,
        "fenced": stopped,
        "retired": stopped,
        "container_present": not stopped,
        "execution_admitted": False,
        "status": "exited",
        "exit_code": 0,
        "transport_closed": True if stopped else None,
    }


def test_resource_intent_receipts_are_immutable_and_stop_does_not_settle_effect():
    rules = resource_rules()
    key, request, identity, namespace = intent()
    record = rules.new_resource(key, request, identity, namespace)
    prepared = receipt(namespace)
    record = rules.receive_resource(record, "prepared", prepared)
    assert record["pending_stop"] is True
    assert rules.receive_resource(copy.deepcopy(record), "prepared", prepared) == record
    with pytest.raises(IdempotencyConflict):
        rules.receive_resource(
            copy.deepcopy(record), "prepared", {**prepared, "container_id": "replacement"}
        )
    stopped = receipt(namespace, stopped=True)
    record = rules.receive_resource(record, "stop", stopped)
    assert record["pending_stop"] is False
    assert "effect_state" not in record
    with pytest.raises(IdempotencyConflict):
        rules.receive_resource(copy.deepcopy(record), "stop", {**stopped, "generation": "b" * 32})


def test_resource_intent_refuses_request_namespace_substitution_before_io():
    rules = resource_rules()
    key, request, identity, namespace = intent()
    with pytest.raises(ValidationError):
        rules.new_resource(
            key, request, identity, {**namespace, "request": {**request, "release_digest": "other"}}
        )
    with pytest.raises(ValidationError):
        rules.new_resource(key, {**request, "request_digest": "forged"}, identity, namespace)


def test_async_history_entrypoints_and_pg_resource_ports_exist_and_refuse_untrusted_authority(
    runner_parts,
):
    async def scenario():
        value = runner(runner_parts)
        for name in ("execute_history", "stop_history", "reconcile_history"):
            method = getattr(value, name, None)
            assert method is not None, "Missing fixed History native entrypoint " + name
            with pytest.raises(AuthorizationDenied):
                await method(envelope(), object())
        journal, _, _ = unopened()
        for name in ("begin_resource", "resource_state", "record_resource", "pending_resources"):
            assert callable(getattr(journal, name, None)), (
                "Missing default PG resource method " + name
            )

    asyncio.run(scenario())


def test_pg_atomic_resource_intent_original_startup_and_pending(postgres_dsn):

    async def scenario():
        async with journals(postgres_dsn, capacity=1) as (views, effects, _, _):
            journal, effect = views[0], effects[0]
            key, request, identity, namespace = intent()
            value = envelope()
            first = await journal.begin_resource(value, request, identity, namespace)
            assert first["execute"] is True
            assert (await effect._record(key))["state"] == "dispatched"
            assert len(await journal.pending_resources(value.context.scope)) == 1
            again = await journal.begin_resource(value, request, identity, namespace)
            assert again["execute"] is False
            prepared = receipt(namespace)
            await journal.record_resource(
                value.context.scope, key[2], request, kind="prepared", evidence=prepared
            )
            binding = {
                **namespace,
                "environment": {k: prepared[k] for k in ("identity", "container_id", "generation")},
            }
            startup = await journal.begin(value.context.scope, key[2], binding, envelope=value)
            assert startup["execute"] is True
            assert (await journal.begin(value.context.scope, key[2], binding, envelope=value))[
                "execute"
            ] is False
            await journal.record_resource(
                value.context.scope,
                key[2],
                request,
                kind="stop",
                evidence=receipt(namespace, stopped=True),
            )
            assert await journal.pending_resources(value.context.scope) == ()
            assert (await effect._record(key))["state"] == "dispatched"

    asyncio.run(scenario())


@pytest.mark.parametrize("lost_receipt", [None, "prepared", "thread", "stop", "result_candidate"])
def test_pg_history_native_same_loop_receipt_recovery_never_submits_again(
    postgres_dsn, tmp_path, lost_receipt
):
    from relf_agent.codex_runner import RunnerOutcomeUnknown, _dispatch
    from relf_agent.coding_execution_rules import adopt, grant
    from relf_agent.temporal_coding_authority import TemporalCodingAuthority
    from tests.test_codex_runner import native_fixture

    async def scenario():
        async with journals(postgres_dsn) as (views, effects, _, _):
            root = tmp_path / "history-native"
            root.mkdir(mode=0o700)
            cli = native_fixture(tmp_path)
            native = CodexCodingRunner(
                root,
                journal=views[0],
                docker_executable=str(cli),
                docker_host="unix:///fixture/docker.sock",
                request_timeout=3,
            )
            value = envelope()
            request = {
                "dispatch": _dispatch(value),
                "release_digest": "release",
                "reservation": {"id": value.context.attempt_id, "amount": 1},
                "definition_digest": "definition",
                "deadline": None,
            }
            request["request_digest"] = digest(request)
            state = {
                "version": "1",
                "request": request,
                "runner": native.identity,
                "phase": "intent",
                "grants": {},
                "pending_stop": False,
                "fenced": False,
                "native_unknown": False,
                "effect_case": "unknown",
            }
            tool_request = {
                "scope": request["dispatch"]["scope"],
                "run_id": value.context.run_id,
                "action_id": value.context.action_id,
                "release_digest": "release",
                "execution_epoch": value.context.execution_epoch,
                "coding_request": request,
            }
            owner_proof = {
                "version": 1,
                "pid": 123,
                "start": "fixture-start",
                "deployment": "d" * 64,
                "invocation_id": "original-invocation",
            }
            failed = False

            async def validate():
                return None

            async def query(name, proof):
                await asyncio.sleep(0)
                return {
                    "request": request,
                    "runner": native.identity,
                    "state": copy.deepcopy(state),
                    "cancelled": False,
                }

            async def update(name, payload):
                nonlocal failed
                if "method" in payload:
                    return grant(
                        state,
                        {"arguments": value.arguments},
                        native.identity,
                        payload["method"],
                        payload["params"],
                        payload["binding"],
                    )
                kind, evidence = payload["kind"], payload["evidence"]
                # Every adoption observes an already committed PG receipt.
                resource = await views[1].resource_state(
                    value.context.scope, value.context.effect_key, request
                )
                if kind == "owner":
                    assert resource["owner"] == evidence
                    state["owner"] = copy.deepcopy(evidence)
                    return {"action_id": value.context.action_id, "recorded": True}
                if kind in {"prepared", "stop"}:
                    assert resource[kind] is not None
                elif kind != "error" or "binding" in state:
                    record = await views[1].lookup(
                        value.context.scope, value.context.effect_key, binding=state["binding"]
                    )
                    if kind == "thread":
                        assert record["thread_id"] == evidence["thread_id"]
                    if kind == "turn":
                        assert record["turn_id"] == evidence["turn_id"]
                    if kind == "result_candidate":
                        assert evidence in record["observations"]
                if kind == lost_receipt and not failed:
                    failed = True
                    raise RuntimeError("finite lost History receipt response")
                adopt(state, native.identity, kind, evidence)
                return {"action_id": value.context.action_id, "recorded": True}

            authority = TemporalCodingAuthority(
                request=tool_request,
                invocation_id="original-invocation",
                query=query,
                update=update,
                validate=validate,
                owner_proof=owner_proof,
            )
            if lost_receipt is None:
                result = await native.execute_history(value, authority)
                assert result.result["text"] == "fixture solution"
            else:
                with pytest.raises(RuntimeError, match="lost History receipt"):
                    await native.execute_history(value, authority)
            path = tmp_path / "native-submissions.jsonl"
            count = len(path.read_text().splitlines()) if path.exists() else 0
            if lost_receipt in (None, "result_candidate"):
                recovered = await native.execute_history(value, authority)
                assert recovered.result["text"] == "fixture solution"
                assert count == 2
            else:
                if lost_receipt == "stop":
                    assert native.active_operations == 1
                    assert await views[0].pending_resources(value.context.scope) == ()
                    await native.stop_history(value, authority)
                    assert native.active_operations == 0
                with pytest.raises(RunnerOutcomeUnknown):
                    await native.execute_history(value, authority)
                assert count == ({"prepared": 0, "thread": 1, "stop": 2}[lost_receipt])
            assert (len(path.read_text().splitlines()) if path.exists() else 0) == count
            assert await views[0].pending_resources(value.context.scope) == ()
            assert (await effects[0]._record(("coding", "owner", "effect")))[
                "state"
            ] == "dispatched"
            await native.aclose()

    asyncio.run(scenario())


def test_original_owner_proof_is_persisted_immutable_and_strict():
    rules = resource_rules()
    key, request, identity, namespace = intent()
    owner = {
        "version": 1,
        "pid": 123,
        "start": "original-start",
        "deployment": "d" * 64,
        "invocation_id": "invocation",
    }
    record = rules.new_resource(key, request, identity, namespace, owner_proof=owner)
    owner["pid"] = 999
    assert record["owner"]["pid"] == 123
    with pytest.raises(ValidationError):
        rules.new_resource(key, request, identity, namespace, owner_proof={**owner, "pid": True})


def test_ungranted_resource_tombstone_clears_pending_without_manufacturing_native_fence():
    rules = resource_rules()
    key, request, identity, namespace = intent()
    record = rules.new_resource(key, request, identity, namespace)
    evidence = {"namespace_binding": namespace, "prepare_granted": False}
    record = rules.receive_resource(record, "unprepared", evidence)
    assert record["pending_stop"] is False
    assert record["stop"] is None and record["prepared"] is None
    assert record["unprepared"] == evidence
    with pytest.raises(IdempotencyConflict):
        rules.receive_resource(record, "prepared", receipt(namespace))


def test_retirement_receipt_fault_keeps_same_owner_and_retries_after_environment_close(
    runner_parts, tmp_path
):
    from relf_agent.codex_environment import DockerCodingEnvironment
    from tests.test_codex_environment import FAKE_DOCKER

    class ReceiptSink:
        def __init__(self):
            self.failed = False
            self.receipts = []

        def adopt(self, kind, evidence):
            if not self.failed:
                self.failed = True
                raise RuntimeError("finite adoption response loss")
            self.receipts.append((kind, copy.deepcopy(evidence)))

    async def scenario():
        value = runner(runner_parts)
        cli = tmp_path / "retire-docker"
        cli.write_text(f"#!{__import__('sys').executable}\n" + FAKE_DOCKER)
        cli.chmod(0o700)
        root = tmp_path / "retire-resource"
        root.mkdir(mode=0o700)
        env = DockerCodingEnvironment(
            root,
            "resource",
            docker_executable=str(cli),
            docker_host="unix:///fixture/docker.sock",
            retire_on_stop=True,
            expected_generation="a" * 32,
        )
        await env.prepare()
        sink = ReceiptSink()
        owner = {
            "environment": env,
            "transport": None,
            "prepared": True,
            "cold": False,
            "original_state": {},
            "journaled": False,
            "authority": sink,
            "stop": None,
            "cleanup": None,
            "task": None,
            "binding": None,
        }
        value._active = owner
        with pytest.raises(RuntimeError, match="adoption response loss"):
            await value._cleanup(owner)
        assert value.active_operations == 1
        assert owner["stop"] is None
        await value._close_owner(owner)
        assert value.active_operations == 0
        assert sink.receipts[0][0] == "stop"
        assert sink.receipts[0][1]["fenced"] is True
        assert sink.receipts[0][1]["retired"] is True

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "changed", [{"resource_id": "replacement"}, {"transport_closed": "yes"}, {"pid": False}]
)
def test_resource_fence_receipt_refuses_other_resource_or_untyped_completion(changed):
    rules = resource_rules()
    key, request, identity, namespace = intent()
    record = rules.new_resource(key, request, identity, namespace)
    with pytest.raises(IdempotencyConflict):
        rules.receive_resource(record, "stop", {**receipt(namespace, stopped=True), **changed})


def test_pg_resource_cas_capacity_scope_and_rollback(postgres_dsn):
    from relf_agent.codex_runner import _dispatch
    from relf_agent.errors import MemoryBackendError
    from relf_agent.executors import DispatchEnvelope
    from relf_agent.types import InvocationContext, Scope

    async def scenario():
        async with journals(postgres_dsn, capacity=1) as (views, effects, connections, _):
            key, request, identity, namespace = intent()
            value = envelope()
            results = await asyncio.gather(
                *[
                    views[index % 2].begin_resource(value, request, identity, namespace)
                    for index in range(12)
                ]
            )
            assert sum(result["execute"] for result in results) == 1
            assert (await views[1].resource_state(value.context.scope, key[2], request))[
                "request"
            ] == request
            assert await views[1].pending_resources(Scope("coding", "foreign")) == ()
            next_value = DispatchEnvelope(
                InvocationContext(
                    value.context.scope, "other", "action", "attempt2", "effect2", "epoch"
                ),
                value.tool_manifest,
                {"task": "different target"},
                "different-operation",
            )
            next_request = {
                **request,
                "dispatch": _dispatch(next_value),
                "reservation": {"id": "attempt2", "amount": 1},
            }
            next_request["request_digest"] = digest(
                {k: v for k, v in next_request.items() if k != "request_digest"}
            )
            next_namespace = {
                **namespace,
                "request": next_request,
                "dispatch": next_request["dispatch"],
            }
            with pytest.raises(ValidationError, match="capacity"):
                await views[1].begin_resource(next_value, next_request, identity, next_namespace)
            assert await effects[1]._record(("coding", "owner", "effect2")) is None
        async with journals(postgres_dsn) as (views, effects, connections, _):
            await connections[0].execute(
                "CREATE FUNCTION refuse_resource() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'finite resource insertion fault'; END $$"
            )
            await connections[0].execute(
                "CREATE TRIGGER refuse_resource BEFORE INSERT ON ralf_temporal_coding_resources FOR EACH ROW EXECUTE FUNCTION refuse_resource()"
            )
            key, request, identity, namespace = intent()
            with pytest.raises(MemoryBackendError):
                await views[0].begin_resource(envelope(), request, identity, namespace)
            assert await effects[1]._record(key) is None
            assert await views[1].resource_state(envelope().context.scope, key[2], request) is None

    asyncio.run(scenario())


def test_namespace_absence_query_does_not_prepare_create_or_fabricate_container(tmp_path):
    import sys

    from relf_agent.codex_environment import DockerCodingEnvironment
    from tests.test_codex_environment import FAKE_DOCKER

    async def scenario():
        root = tmp_path / "never-prepared"
        root.mkdir(mode=0o700)
        cli = tmp_path / "absence-docker"
        cli.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
        cli.chmod(0o700)
        env = DockerCodingEnvironment(
            root,
            "absence-original",
            docker_executable=str(cli),
            docker_host="unix:///fixture/docker.sock",
            retire_on_stop=True,
            expected_generation="a" * 32,
        )
        method = getattr(env, "observe_namespace_absence", None)
        assert callable(method), "Missing exact original namespace absence observer"
        evidence = await method()
        assert evidence == {
            "identity": env.identity,
            "generation": "a" * 32,
            "container_present": False,
            "namespace_confirmed": True,
        }
        assert not (root / "environment.json").exists()
        assert not (root / "workspace").exists()
        assert not (tmp_path / "docker.json").exists()
        assert set(p.name for p in root.iterdir()) == {"lease.lock"}
        await env.aclose()

    asyncio.run(scenario())


def test_namespace_absence_receipt_requires_original_dead_owner_and_no_native_locator():
    rules = resource_rules()
    key, request, identity, namespace = intent()
    owner = {
        "version": 1,
        "pid": 123,
        "start": "original",
        "deployment": "d" * 64,
        "invocation_id": "invocation",
    }
    record = rules.new_resource(key, request, identity, namespace, owner_proof=owner)
    evidence = {
        "identity": namespace["environment"],
        "generation": "a" * 32,
        "container_present": False,
        "namespace_confirmed": True,
        "owner": owner,
        "process_present": False,
    }
    record = rules.receive_resource(record, "namespace_absent", evidence)
    assert record["pending_stop"] is False
    assert record["stop"] is None and record["prepared"] is None
    assert record["namespace_absent"] == evidence
    with pytest.raises(IdempotencyConflict):
        rules.receive_resource(record, "prepared", receipt(namespace))
    original = rules.new_resource(key, request, identity, namespace, owner_proof=owner)
    with pytest.raises(IdempotencyConflict):
        rules.receive_resource(original, "namespace_absent", {**evidence, "process_present": True})


def test_pg_dead_original_owner_prepare_grant_loss_queries_absence_without_native_start(
    postgres_dsn, tmp_path
):
    import socket
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    from relf_agent.codex_runner import _dispatch
    from relf_agent.coding_execution_rules import grant
    from relf_agent.temporal_coding_authority import TemporalCodingAuthority
    from relf_agent.temporal_coding_runtime import deployment, process_start
    from tests.test_codex_environment import FAKE_DOCKER

    async def scenario():
        async with journals(postgres_dsn) as (views, effects, _, _):
            with tempfile.TemporaryDirectory(
                prefix="ralf106-absence-", dir="/private/tmp"
            ) as directory:
                sock = socket.socket(socket.AF_UNIX)
                socket_path = Path(directory) / "docker.sock"
                sock.bind(str(socket_path))
                child = await asyncio.to_thread(
                    subprocess.Popen, [sys.executable, "-c", "import time;time.sleep(30)"]
                )
                try:
                    host = "unix://" + str(socket_path)
                    cli = tmp_path / "cold-absence-docker"
                    cli.write_text(
                        f"#!{sys.executable}\n"
                        + FAKE_DOCKER.replace("unix:///fixture/docker.sock", host)
                    )
                    cli.chmod(0o700)
                    root = tmp_path / "cold-absence-runner"
                    root.mkdir(mode=0o700)
                    native = CodexCodingRunner(
                        root, journal=views[0], docker_executable=str(cli), docker_host=host
                    )
                    value = envelope()
                    request = {
                        "dispatch": _dispatch(value),
                        "release_digest": "release",
                        "reservation": {"id": "attempt", "amount": 1},
                        "definition_digest": "definition",
                        "deadline": None,
                    }
                    request["request_digest"] = digest(request)
                    env = native._environment(value, create=True)
                    namespace = {
                        "request": request,
                        "runner": native.identity,
                        "dispatch": request["dispatch"],
                        "environment": env.identity,
                    }
                    proof = {
                        "version": 1,
                        "pid": child.pid,
                        "start": await asyncio.to_thread(process_start, child.pid),
                        "deployment": deployment(native),
                        "invocation_id": "dead-original",
                    }
                    await views[0].begin_resource(
                        value, request, native.identity, namespace, owner_proof=proof
                    )
                    state = {
                        "request": request,
                        "runner": native.identity,
                        "grants": {},
                        "pending_stop": False,
                        "fenced": True,
                        "owner": proof,
                    }
                    grant(
                        state,
                        {"arguments": value.arguments},
                        native.identity,
                        "prepare",
                        {},
                        namespace,
                    )
                    tool_request = {
                        "scope": request["dispatch"]["scope"],
                        "run_id": value.context.run_id,
                        "action_id": value.context.action_id,
                        "release_digest": "release",
                        "execution_epoch": value.context.execution_epoch,
                        "coding_request": request,
                    }

                    async def validate():
                        return None

                    async def query(name, payload):
                        return {
                            "request": request,
                            "runner": native.identity,
                            "state": copy.deepcopy(state),
                            "cancelled": True,
                        }

                    async def update(name, payload):
                        kind, evidence = payload["kind"], payload["evidence"]
                        if kind == "owner":
                            assert evidence == proof
                        else:
                            assert kind == "namespace_absent"
                            saved = await views[1].resource_state(
                                value.context.scope, value.context.effect_key, request
                            )
                            assert saved["namespace_absent"] == evidence
                            assert (
                                evidence["owner"] == proof and evidence["process_present"] is False
                            )
                            assert "container_id" not in evidence
                            state["namespace_absent"] = evidence
                            state["fenced"] = True
                            state["pending_stop"] = False
                        return {"action_id": value.context.action_id, "recorded": True}

                    authority = TemporalCodingAuthority(
                        request=tool_request,
                        invocation_id="recovery",
                        query=query,
                        update=update,
                        validate=validate,
                    )
                    from relf_agent.errors import CloseIncomplete

                    with pytest.raises(CloseIncomplete):
                        await native.stop_history(value, authority)
                    assert native.active_operations == 1
                    assert not (tmp_path / "docker.json").exists()
                    child.kill()
                    await asyncio.to_thread(child.wait)
                    assert await native.stop_history(value, authority) is None
                    assert native.active_operations == 0
                    assert await views[0].pending_resources(value.context.scope) == ()
                    assert (await effects[0]._record(("coding", "owner", "effect")))[
                        "state"
                    ] == "dispatched"
                    assert not (tmp_path / "docker.json").exists()
                    assert not (Path(env.identity["root"]["path"]) / "environment.json").exists()
                    await native.aclose()
                finally:
                    if child.poll() is None:
                        child.kill()
                    await asyncio.to_thread(child.wait)
                    sock.close()

    asyncio.run(scenario())


def test_pg_await_revalidates_full_original_registration_before_and_after(postgres_dsn, tmp_path):
    import sys

    from relf_agent.temporal_coding_authority import TemporalCodingAuthority

    async def scenario():
        async with journals(postgres_dsn) as (views, _, _, _):
            root = tmp_path / "registration-runner"
            root.mkdir(mode=0o700)
            native = CodexCodingRunner(
                root,
                journal=views[0],
                docker_executable=sys.executable,
                docker_host="unix:///fixture/docker.sock",
            )
            _, request, _, _ = intent()
            dispatch = request["dispatch"]
            tool_request = {
                **{
                    name: dispatch[name]
                    for name in ("scope", "run_id", "action_id", "execution_epoch")
                },
                "release_digest": request["release_digest"],
                "coding_request": request,
            }
            registrations = []

            async def validate():
                registrations.append("original-publication")

            async def query(name, payload):
                raise AssertionError("Registration validation must not query business History")

            async def update(name, payload):
                raise AssertionError("Registration validation must not update business History")

            authority = TemporalCodingAuthority(
                request=tool_request,
                invocation_id="invocation",
                query=query,
                update=update,
                validate=validate,
            )
            owner = {"history": True, "authority": authority}
            assert (
                await native._journal_method(
                    owner, "resource_state", envelope().context.scope, "effect", request
                )
                is None
            )
            assert registrations == ["original-publication", "original-publication"]

    asyncio.run(scenario())
