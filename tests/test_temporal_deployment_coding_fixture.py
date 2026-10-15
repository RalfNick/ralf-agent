"""Fixture lifecycle/transport tests; no Service, PG, Docker, or model calls."""

import ast
import asyncio
import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from ralf_agent.errors import CloseIncomplete
from tests import temporal_deployment_coding_worker_fixture as worker
from tests import test_temporal_deployment_coding_service as service

NATIVE_PREFLIGHT_METHODS = (
    "initialize",
    "config/read",
    "configRequirements/read",
    "experimentalFeature/list",
    "permissionProfile/list",
    "mcpServerStatus/list",
    "skills/list",
    "plugin/list",
    "plugin/installed",
)


def _native_control_exchange(directory, methods):
    cli = worker.peer(directory)
    client, workspace = directory / "client", directory / "workspace"
    client.mkdir()
    workspace.mkdir()
    (client / "config.json").write_text("{}")
    (directory / "docker.json").write_text(
        json.dumps(
            {
                "creates": 1,
                "containers": {
                    "fixed": {
                        "State": {},
                        "Mounts": [{"Source": str(workspace), "Destination": "/workspace"}],
                    }
                },
            }
        )
    )
    secret = "private-password sk-fixture-secret"
    requests = [
        {"id": index, "method": method, "params": {"private": secret}}
        for index, method in enumerate(methods)
    ]
    result = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--config",
            str(client),
            "--host",
            "unix:///fixture/docker.sock",
            "start",
            "fixed",
        ],
        input="".join(json.dumps(request) + "\n" for request in requests),
        text=True,
        capture_output=True,
        timeout=5,
    )
    return cli, result, secret


def test_native_rpc_timing_is_opt_in_and_control_responses_are_byte_equivalent(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_TIMING", raising=False)
    plain, timed = tmp_path / "plain", tmp_path / "timed"
    plain.mkdir()
    timed.mkdir()
    baseline, first, secret = _native_control_exchange(plain, NATIVE_PREFLIGHT_METHODS)
    assert first.returncode == 0 and not (plain / "native-rpc-timing.jsonl").exists()
    (timed / "capture-coding-timing").touch()
    observed, second, _ = _native_control_exchange(timed, NATIVE_PREFLIGHT_METHODS)
    assert second.returncode == 0 and second.stdout == first.stdout
    assert baseline.read_text() != observed.read_text()
    text = (timed / "native-rpc-timing.jsonl").read_text()
    records = [json.loads(line) for line in text.splitlines()]
    assert len(records) == 18
    assert secret not in text and "private" not in text and "params" not in text
    for index, method in enumerate(NATIVE_PREFLIGHT_METHODS):
        received, responded = records[index * 2 : index * 2 + 2]
        assert received["method"] == responded["method"] == method
        assert received["phase"] == "received" and responded["phase"] == "responded"
        assert received["count"] == responded["count"] == 1
        assert received["pid"] == responded["pid"] > 0
        assert responded["monotonic"] >= received["monotonic"]
    assert all(set(r) == {"method", "phase", "count", "pid", "monotonic"} for r in records)
    assert (timed / "native-rpc-timing.jsonl").stat().st_mode & 0o777 == 0o600
    assert not (timed / "native-submissions.jsonl").exists()
    assert not (timed / "native-commits.jsonl").exists()


def test_native_rpc_timing_counts_repeats_and_omits_unknown_method_names(tmp_path, monkeypatch):
    monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_TIMING", "1")
    unknown = "private-password sk-fixture-secret"
    _, result, _ = _native_control_exchange(tmp_path, ("initialize", "initialize", unknown))
    assert result.returncode != 0
    text = (tmp_path / "native-rpc-timing.jsonl").read_text()
    assert unknown not in text
    records = [json.loads(line) for line in text.splitlines()]
    assert [r["count"] for r in records] == [1, 1, 2, 2]
    assert all(r["method"] == "initialize" for r in records)


def test_native_thread_turn_response_timing_does_not_execute_business_or_capture_body(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_TIMING", raising=False)
    (tmp_path / "capture-coding-timing").touch()
    cli = worker.peer(tmp_path)
    tree = ast.parse(cli.read_text())
    # Execute only the generated timing/send helpers, never its native business branch.
    nodes = [
        node
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id.startswith("native_rpc_")
                for target in node.targets
            )
        )
        or (isinstance(node, ast.FunctionDef) and node.name in {"native_rpc_timing", "send"})
    ]
    namespace = {"root": tmp_path, "os": __import__("os"), "time": time, "json": json}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(cli), "exec"), namespace)
    assert namespace["native_rpc_methods"] == frozenset(
        (*NATIVE_PREFLIGHT_METHODS, "thread/start", "turn/start")
    )
    secret = "private-password sk-fixture-secret"
    response = {"id": secret, "result": {"secret": secret}}
    for method in ("thread/start", "turn/start"):
        namespace["method"] = method
        namespace["native_rpc_timing"](method, "received")
        namespace["send"](response)
        namespace["send"]({"method": secret, "params": {"private": secret}})
    text = (tmp_path / "native-rpc-timing.jsonl").read_text()
    assert secret not in text and "params" not in text
    records = [json.loads(line) for line in text.splitlines()]
    assert [(r["method"], r["phase"]) for r in records] == [
        (method, phase)
        for method in ("thread/start", "turn/start")
        for phase in ("received", "responded")
    ]
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == lines[2] == json.dumps(response)
    assert not (tmp_path / "native-submissions.jsonl").exists()
    assert not (tmp_path / "native-commits.jsonl").exists()


def test_unreachable_fault_allows_inventory_then_arms_after_completed_create(tmp_path, monkeypatch):
    cli = worker.actual_create_cli(tmp_path, "/explicit/test/docker", "unreachable")
    calls = []

    def backend(argv, **kwargs):
        calls.append(argv)
        operation = argv[argv.index("--host") + 2]
        return subprocess.CompletedProcess(
            argv, 0, b"a" * 64 + b"\n" if operation == "create" else b"", b""
        )

    monkeypatch.setattr(subprocess, "run", backend)

    def invoke(operation):
        monkeypatch.setattr(
            sys,
            "argv",
            [str(cli), "--config", str(tmp_path), "--host", "unix:///test/endpoint", operation],
        )
        with pytest.raises(SystemExit) as stopped:
            runpy.run_path(str(cli), run_name="__main__")
        return stopped.value.code

    assert not (tmp_path / "actual-create.json").exists()
    assert invoke("ps") == 0
    assert len(calls) == 1 and not (tmp_path / "block-actual-inventory").exists()
    assert invoke("create") == 1  # The successful backend reply is deliberately lost.
    assert json.loads((tmp_path / "actual-create.json").read_text())["cid"] == "a" * 64
    assert (tmp_path / "block-actual-inventory").exists()
    assert invoke("ps") == invoke("inspect") == 1
    assert len(calls) == 2
    (tmp_path / "block-actual-inventory").unlink()
    assert invoke("ps") == 0 and len(calls) == 3
    recorded = [
        json.loads(line)
        for line in (tmp_path / "actual-docker-calls.jsonl").read_text().splitlines()
    ]
    assert [call["operation"] for call in recorded] == ["ps", "create", "ps", "inspect", "ps"]
    assert [call["inventory_blocked"] for call in recorded] == [False, False, True, True, False]
    assert all(
        call["args"]
        == ["--config", str(tmp_path), "--host", "unix:///test/endpoint", call["operation"]]
        for call in recorded
    )


def test_release_reply_fault_occurs_only_after_real_update_and_once(tmp_path):
    from temporalio.service import RPCError, RPCStatusCode

    payload, response, calls = {"certificate": {"original": "seal"}}, {"released": True}, []

    class Original:
        id = "original-registry"

        async def execute_update(self, name, request, **options):
            await asyncio.sleep(0)
            calls.append((name, request, options))
            return response

    fault = worker.FaultClient(None, tmp_path)
    handle = worker.FaultHandle(fault, Original())
    (tmp_path / "lose-release-reply").touch()

    async def scenario():
        with pytest.raises(RPCError) as lost:
            await handle.execute_update("release_deployment_root", payload, id="original-update")
        assert lost.value.status == RPCStatusCode.UNAVAILABLE
        assert len(calls) == 1
        assert json.loads((tmp_path / "lost-release-reply.json").read_text()) == {
            "workflow_id": "original-registry",
            "payload": payload,
            "result": response,
        }
        assert not (tmp_path / "lose-release-reply").exists()
        assert (
            await handle.execute_update("release_deployment_root", payload, id="original-update")
            is response
        )
        assert calls == [("release_deployment_root", payload, {"id": "original-update"})] * 2

    asyncio.run(scenario())


def test_native_stop_ack_hold_releases_same_original_update_once(tmp_path):
    gate = tmp_path / "hold-native-stop"
    gate.touch()
    calls, response = [], {"recorded": True}

    class Original:
        async def execute_update(self, name, payload, **options):
            calls.append((name, payload, options))
            return response

    handle = worker.FaultHandle(SimpleNamespace(directory=tmp_path), Original())
    payload = {"kind": "stop", "evidence": {"original": "stop"}}

    async def scenario():
        task = asyncio.create_task(handle._execute_update("coding_receipt", payload, id="same-ack"))
        try:
            await asyncio.sleep(0)
            assert not task.done() and calls == []
            assert (tmp_path / "hold-native-stop.attempted").exists()
            gate.unlink()
            assert await task is response
            assert calls == [("coding_receipt", payload, {"id": "same-ack"})]
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["timeout", "cancel"])
def test_native_stop_hold_is_bounded_and_does_not_send_on_interruption(
    tmp_path, monkeypatch, failure
):
    (tmp_path / "hold-native-stop").touch()
    calls, limits = [], []
    timeout = asyncio.timeout

    def bounded(seconds):
        limits.append(seconds)
        return timeout(0 if failure == "timeout" else seconds)

    monkeypatch.setattr(worker.asyncio, "timeout", bounded)

    class Original:
        async def execute_update(self, *args, **options):
            calls.append(args)

    handle = worker.FaultHandle(SimpleNamespace(directory=tmp_path), Original())

    async def scenario():
        task = asyncio.create_task(handle._execute_update("coding_receipt", {"kind": "stop"}))
        await asyncio.sleep(0)
        if failure == "cancel":
            assert not task.done()
            task.cancel()
        with pytest.raises(TimeoutError if failure == "timeout" else asyncio.CancelledError):
            await task
        assert limits == [30] and calls == []

    asyncio.run(scenario())


def test_native_stop_unavailable_stays_a_distinct_prewrite_failure(tmp_path):
    from temporalio.service import RPCError, RPCStatusCode

    (tmp_path / "block-native-stop").touch()
    calls = []

    class Original:
        async def execute_update(self, *args, **options):
            calls.append(args)

    handle = worker.FaultHandle(SimpleNamespace(directory=tmp_path), Original())

    async def scenario():
        with pytest.raises(RPCError) as error:
            await handle._execute_update("coding_receipt", {"kind": "stop"})
        assert error.value.status == RPCStatusCode.UNAVAILABLE
        assert calls == [] and (tmp_path / "block-native-stop.attempted").exists()
        assert not (tmp_path / "hold-native-stop.attempted").exists()

    asyncio.run(scenario())


def test_sdk_timing_is_opt_in_and_does_not_record_payload_result_or_error_message(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_TIMING", raising=False)
    secret = "postgresql://private:user-password@127.0.0.1/private sk-fixture-secret"
    original_error = ConnectionError(secret)
    result = {"manifest": secret}
    calls = []

    class Original:
        id = "ralf-temporal-" + "a" * 64

        async def query(self, name, payload, **options):
            await asyncio.sleep(0)
            calls.append(("query", name))
            return result

        async def execute_update(self, name, payload, **options):
            await asyncio.sleep(0)
            calls.append(("update", name))
            raise original_error

    proxy = worker.FaultClient(None, tmp_path)
    original = Original()
    query_code, update_code = Original.query.__code__, Original.execute_update.__code__
    handle = worker.FaultHandle(proxy, original)
    payload = {"kind": "diagnostics", "manifest": secret, "dsn": secret, "key": secret}

    async def scenario():
        assert await handle.query("view", payload) is result
        assert not proxy.timing.path.exists()
        # The environment opt-in persists a private marker for a separate Worker.
        monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_TIMING", "1")
        enabled = worker.FaultClient(None, tmp_path)
        monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_TIMING")
        assert worker.SDKTiming(tmp_path).enabled
        observed = worker.FaultHandle(enabled, original)
        assert await observed.query("view", payload) is result
        assert await observed.query("view", payload) is result
        with pytest.raises(ConnectionError) as raised:
            await observed.execute_update("coding_receipt", payload)
        assert raised.value is original_error
        # Unexpected caller names/IDs/kinds cannot become a secret channel.
        with enabled.timing.span("query", secret, secret, {"kind": secret}):
            pass
        text = enabled.timing.path.read_text()
        records = [json.loads(line) for line in text.splitlines()]
        assert secret not in text and "password" not in text and "manifest" not in text
        assert len(records) == 8
        finished = [record for record in records if record["phase"] == "finished"]
        assert [record["count"] for record in finished[:2]] == [1, 2]
        assert all(record["elapsed_seconds"] >= 0 for record in finished)
        assert finished[2]["exception_type"] == "ConnectionError"
        assert finished[2]["outcome"] == "raised" and finished[2]["rpc_status"] is None
        assert finished[3]["workflow_id"] == "omitted"
        assert finished[3]["name"] == "other" and finished[3]["kind"] is None
        assert enabled.timing.path.stat().st_mode & 0o777 == 0o600

    asyncio.run(scenario())
    assert calls == [("query", "view")] * 3 + [("update", "coding_receipt")]
    assert Original.query.__code__ is query_code and Original.execute_update.__code__ is update_code


def test_sdk_timing_labels_original_validate_callback_without_replacing_code(tmp_path):
    (tmp_path / "capture-coding-timing").touch()
    timing = worker.SDKTiming(tmp_path)
    namespace = {"timing": timing, "asyncio": asyncio}
    # This unit exercises frame classification only, with no authority/oracle.
    code = compile(
        "async def validate():\n"
        " with timing.span('query', 'ralf-temporal-'+'a'*64, 'view', {'kind':'diagnostics'}):\n"
        "  await asyncio.sleep(0)\n",
        "temporal_coding_runtime.py",
        "exec",
    )
    exec(code, namespace)
    original_code = namespace["validate"].__code__
    asyncio.run(namespace["validate"]())
    assert namespace["validate"].__code__ is original_code
    records = [json.loads(line) for line in timing.path.read_text().splitlines()]
    assert len(records) == 2 and all(record["origin"] == "coding_validate" for record in records)
    assert records[1]["outcome"] == "returned" and records[1]["elapsed_seconds"] > 0


@pytest.mark.parametrize(
    "kind,name,response,expected_status,expected_error,expected_keys,unknown_count",
    [
        (
            "deployment_coding_validation",
            "deployment_coding_validation",
            {"error": "definition_mismatch"},
            "domain_error",
            "definition_mismatch",
            ["error"],
            0,
        ),
        (
            "deployment_coding_validation",
            "view",
            {"version": 1, "edge": None, "scope": "private", "proof_digest": "private"},
            "value",
            None,
            ["edge", "proof_digest", "scope", "version"],
            0,
        ),
        (
            "deployment_start",
            "view",
            {"error": "private", "private": "private"},
            "domain_error",
            "omitted",
            ["error"],
            1,
        ),
    ],
)
def test_sdk_query_timing_records_only_allowlisted_response_shape(
    tmp_path, kind, name, response, expected_status, expected_error, expected_keys, unknown_count
):
    secret = "postgresql://private:user-password@127.0.0.1/private sk-fixture-secret"
    response = {
        (secret if key == "private" else key): (secret if value == "private" else value)
        for key, value in response.items()
    }
    (tmp_path / "capture-coding-timing").touch()

    class Original:
        id = "ralf-temporal-" + "a" * 64

        async def query(self, query_name, payload, **options):
            assert query_name == name and payload == {"kind": kind, "private": secret}
            return response

    owner = worker.FaultClient(None, tmp_path)
    handle = worker.FaultHandle(owner, Original())
    assert asyncio.run(handle.query(name, {"kind": kind, "private": secret})) is response
    text = owner.timing.path.read_text()
    assert secret not in text and "password" not in text
    records = [json.loads(line) for line in text.splitlines()]
    assert len(records) == 2
    finished = records[1]
    assert finished["kind"] == kind and finished["name"] == name
    assert finished["query_status"] == expected_status
    assert finished["query_error_code"] == expected_error
    assert finished["response_keys"] == expected_keys
    assert finished["unrecognized_key_count"] == unknown_count


def test_describe_timings_preserve_ports_results_options_and_privacy(tmp_path, monkeypatch):
    from temporalio.worker import Plugin

    from ralf_agent.task_controls import _binding

    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_TIMING", raising=False)
    secret = "postgresql://private:user-password@127.0.0.1/private sk-fixture-secret"
    calls, description, namespace_result, grant_result = [], object(), object(), object()
    original_error = ConnectionError(secret)

    class Service:
        other_port = object()

        async def describe_namespace(self, request, **options):
            calls.append(("namespace", request, options))
            if options.get("fail"):
                raise original_error
            return namespace_result

    class Handle:
        id = "ralf-temporal-" + "a" * 64

        async def describe(self, **options):
            calls.append(("describe", options))
            return description

        async def execute_update(self, name, payload, **options):
            calls.append(("update", name, payload, options))
            return grant_result

    backend, handle_backend = Service(), Handle()
    configuration = {"plugins": [], "service_client": object(), "private": secret}

    class Client:
        workflow_service = backend
        service_client = configuration["service_client"]

        def config(self, **options):
            calls.append(("config", options))
            return {**configuration, "plugins": list(configuration["plugins"])}

        def get_workflow_handle(self, *args, **options):
            return handle_backend

    plain = worker.FaultClient(Client(), tmp_path)
    assert plain.workflow_service is backend
    assert plain.config() == configuration
    assert not (tmp_path / "sdk-timing.jsonl").exists()
    (tmp_path / "capture-coding-timing").touch()
    client = worker.FaultClient(Client(), tmp_path)
    proxy = client.workflow_service
    binding = _binding(proxy.describe_namespace)
    assert proxy is client.workflow_service
    assert proxy.other_port is backend.other_port
    assert _binding(client.workflow_service.describe_namespace) == binding
    config = client.config(active_config=True)
    assert client.service_client is configuration["service_client"]
    assert config["service_client"] is configuration["service_client"]
    assert configuration["plugins"] == [] and len(config["plugins"]) == 1
    assert isinstance(config["plugins"][0], Plugin)
    assert config["plugins"][0] is client.config()["plugins"][0]
    assert config["plugins"][0].configure_worker(config) is config
    assert config["plugins"][0].configure_replayer(config) is config
    handle = client.get_workflow_handle("original")

    async def scenario():
        assert await handle.describe(rpc_metadata={"private": secret}) is description
        assert (
            await proxy.describe_namespace(secret, metadata={"private": secret}) is namespace_result
        )
        with pytest.raises(ConnectionError) as error:
            await proxy.describe_namespace(secret, fail=True)
        assert error.value is original_error
        assert (
            await handle.execute_update("admit_coding_phase", {"private": secret}) is grant_result
        )

    asyncio.run(scenario())
    assert _binding(client.workflow_service.describe_namespace) == binding
    assert calls[-4:] == [
        ("describe", {"rpc_metadata": {"private": secret}}),
        ("namespace", secret, {"metadata": {"private": secret}}),
        ("namespace", secret, {"fail": True}),
        ("update", "admit_coding_phase", {"private": secret}, {}),
    ]
    text = client.timing.path.read_text()
    assert secret not in text and "password" not in text
    finished = [
        json.loads(line) for line in text.splitlines() if json.loads(line)["phase"] == "finished"
    ]
    assert [record["name"] for record in finished] == [
        "describe",
        "describe_namespace",
        "describe_namespace",
        "admit_coding_phase",
    ]
    assert finished[2]["exception_type"] == "ConnectionError"
    assert all(record["elapsed_seconds"] >= 0 for record in finished)


@pytest.mark.parametrize("outcome", ["returned", "raised", "cancelled"])
def test_worker_loop_probe_is_opt_in_private_and_joined_on_every_exit(
    tmp_path, monkeypatch, outcome
):
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_TIMING", raising=False)
    path = tmp_path / "worker-loop-lag.jsonl"
    original_error = RuntimeError("private sk-fixture-secret")

    async def scenario():
        before = asyncio.all_tasks()
        async with worker.SDKTiming(tmp_path).loop_probe():
            assert asyncio.all_tasks() == before
        assert not path.exists()
        (tmp_path / "capture-coding-timing").touch()
        timing = worker.SDKTiming(tmp_path)
        plugin = worker.loop_timing_plugin(timing)
        original_worker, entered = object(), asyncio.Event()

        async def next_worker(value):
            assert value is original_worker
            entered.set()
            if outcome == "cancelled":
                await asyncio.Event().wait()
            else:
                await asyncio.sleep(0.001)  # Let the probe establish its next due time.
                # Deliberately starve this unit's loop to measure lag; no business runs.
                time.sleep(0.08)  # noqa: ASYNC251
                await asyncio.sleep(0.01)
                if outcome == "raised":
                    raise original_error

        if outcome == "cancelled":
            task = asyncio.create_task(plugin.run_worker(original_worker, next_worker))
            await entered.wait()
            await asyncio.sleep(0.06)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif outcome == "raised":
            with pytest.raises(RuntimeError) as error:
                await plugin.run_worker(original_worker, next_worker)
            assert error.value is original_error
        else:
            await plugin.run_worker(original_worker, next_worker)
        assert asyncio.all_tasks() == before
        text = path.read_text()
        assert "private" not in text and "secret" not in text
        records = [json.loads(line) for line in text.splitlines()]
        assert records
        assert all(
            set(record)
            == {
                "pid",
                "count",
                "interval_seconds",
                "expected_monotonic",
                "observed_monotonic",
                "lag_seconds",
            }
            for record in records
        )
        assert all(
            record["interval_seconds"] == 0.05 and record["lag_seconds"] >= 0 for record in records
        )
        if outcome != "cancelled":
            assert records[0]["lag_seconds"] >= 0.02
        assert path.stat().st_mode & 0o777 == 0o600

    asyncio.run(scenario())


@pytest.mark.parametrize("close_fails", [False, True])
def test_sdk_client_setup_failure_closes_or_retains_original_assembly(
    tmp_path, monkeypatch, close_fails
):
    import psycopg

    events = []
    original = OSError("Controlled SDK client setup failure")
    close_error = CloseIncomplete({"original_native_owner": "not_stopped"})

    class Admin:
        async def execute(self, query, *args):
            events.append("drop" if "DROP SCHEMA" in str(query) else "sql")

        async def close(self):
            events.append("admin-close")

    class Assembly:
        closed = False

        async def aclose(self, **kwargs):
            events.append("assembly-close")
            if close_fails:
                raise close_error
            self.closed = True

    admin, assembly = Admin(), Assembly()

    class Socket:
        def bind(self, path):
            Path(path).touch()

        def close(self):
            events.append("socket-close")

    monkeypatch.setattr(
        service, "socket", SimpleNamespace(AF_UNIX=1, socket=lambda *args: Socket())
    )

    async def connect(*args, **kwargs):
        return admin

    async def build(*args, **kwargs):
        return assembly

    async def clients(*args, **kwargs):
        raise original

    monkeypatch.setenv("RALF_TEST_POSTGRES_DSN", "postgresql://127.0.0.1/test_fixture")
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    monkeypatch.setattr(worker, "application", build)
    monkeypatch.setattr(service, "_clients", clients)

    async def scenario():
        async with service.coding_system(tmp_path, monkeypatch):
            raise AssertionError("SDK failure must prevent yield")

    if close_fails:
        with pytest.raises(BaseExceptionGroup) as result:
            asyncio.run(scenario())
        assert result.value.exceptions == (original, close_error)
        assert not assembly.closed and "drop" not in events
        diagnostic = json.loads((tmp_path / "construction-close-error.json").read_text())
        assert diagnostic["report"] == close_error.report and diagnostic["schema_retained"] is True
        recovery = result.value.deployment_coding_fixture_recovery
        assert recovery["assembly"] is assembly
        recovery["socket"].close()
        Path(recovery["socket_path"]).unlink()
    else:
        with pytest.raises(OSError) as result:
            asyncio.run(scenario())
        assert result.value is original and assembly.closed
        assert events.index("assembly-close") < events.index("drop") < events.index("admin-close")


@pytest.mark.parametrize("ack_fails", [False, True])
def test_owned_worker_handoff_waits_for_original_end_ack_before_exit(capsys, ack_fails):
    from ralf_agent.temporal_context_execution import ContextExecutionOwner

    async def scenario():
        events = []
        stopped, body_release, ack_release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        ack_started = asyncio.Event()
        owner = ContextExecutionOwner()

        async def body():
            await body_release.wait()
            events.append("handler-ended")

        async def ended(proof):
            assert "receiver-started" in events
            if not ack_fails:
                assert "receiver-stopped" not in events
            events.append("end-ack-started")
            ack_started.set()
            await ack_release.wait()
            events.append("end-ack-complete")

        operation = asyncio.create_task(
            owner.execute(
                body,
                proof={
                    "scope": {"workspace": "fixture", "principal": "handoff"},
                    "action_id": "original-call",
                    "release_digest": "1" * 64,
                    "request_digest": "2" * 64,
                    "execution_epoch": "original-epoch",
                },
                on_end=ended,
            )
        )

        class Worker:
            closed = False

            async def __aenter__(self):
                events.append("pollers-started")
                return self

            async def __aexit__(self, *args):
                await self.shutdown()

            async def shutdown(self):
                if self.closed:
                    return
                self.closed = True
                events.append("pollers-stopped")
                body_release.set()
                await operation
                events.append("sdk-handlers-drained")

        class Runtime:
            async def close_deployment_execution(self, *, wait_timeout):
                assert wait_timeout == 80
                events.append("deployment-drain")
                if ack_fails:
                    raise RuntimeError("original end ACK unavailable")
                await owner.aclose(wait_timeout=1)

        class Receiver:
            async def __aenter__(self):
                events.append("receiver-started")

            async def __aexit__(self, *args):
                events.append("receiver-stopped")

        task = asyncio.create_task(
            worker.run_owned_worker(Worker(), Runtime(), stopped, Receiver())
        )
        await asyncio.sleep(0)
        stopped.set()
        if ack_fails:
            with pytest.raises(RuntimeError, match="original end ACK unavailable"):
                await task
            ack_release.set()
            await owner.aclose(wait_timeout=1)
        else:
            await ack_started.wait()
            assert not task.done()
            ack_release.set()
            await task
        assert events.index("pollers-stopped") < events.index("handler-ended")
        assert events.index("sdk-handlers-drained") < events.index("deployment-drain")
        assert events.index("deployment-drain") < events.index("end-ack-complete")
        if not ack_fails:
            assert events.index("end-ack-complete") < events.index("receiver-stopped")

    asyncio.run(asyncio.wait_for(scenario(), 5))
    output = capsys.readouterr().out
    assert ("DEPLOYMENT_CODING_WORKER_HANDOFF_COMPLETE" in output) is not ack_fails


@pytest.mark.parametrize("control", [False, True])
def test_original_control_observe_hold_is_test_only_and_keeps_reply(tmp_path, monkeypatch, control):
    from temporalio import activity

    monkeypatch.setattr(
        activity,
        "info",
        lambda: SimpleNamespace(
            activity_type="ralf.temporal.control.v1" if control else "ralf.temporal.model.v1",
            activity_id="original-call",
            workflow_id="original-parent",
            workflow_run_id="original-epoch",
        ),
    )
    gate = tmp_path / "block-control-observe"
    gate.touch()
    reply = {"snapshot": {"state": "waiting_approval"}}
    calls = []

    class Handle:
        async def query(self, *args, **options):
            calls.append(args)
            return reply

    async def scenario():
        handle = worker.FaultHandle(SimpleNamespace(directory=tmp_path), Handle())
        task = asyncio.create_task(handle._query("view", {"kind": "diagnostics"}))
        await asyncio.sleep(0)
        marker = tmp_path / "held-control-observe.json"
        assert marker.exists() is control
        if control:
            assert not task.done()
            held = json.loads(marker.read_text())
            assert held == {
                "workflow_id": "original-parent",
                "execution_epoch": "original-epoch",
                "activity_id": "original-call",
                "pid": os.getpid(),
            }
        gate.unlink()
        assert await task == reply
        assert len(calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("connect_fails", [False, True])
def test_workflow_receiver_uses_distinct_sdk_runtime_and_original_configuration(
    monkeypatch, connect_fails
):
    client_sdk = pytest.importorskip("temporalio.client")
    runtime_sdk = pytest.importorskip("temporalio.runtime")
    service_sdk = pytest.importorskip("temporalio.service")
    worker_sdk = pytest.importorskip("temporalio.worker")
    from dataclasses import replace

    original_runtime, converter, runner = object(), object(), object()
    connection = service_sdk.ConnectConfig(
        "127.0.0.1:7233",
        identity="original-worker",
        rpc_metadata={"fixture": "original"},
        runtime=original_runtime,
    )
    client_config = {
        "service_client": SimpleNamespace(config=connection),
        "namespace": "original-namespace",
        "data_converter": converter,
        "interceptors": [object()],
        "plugins": [object()],
    }
    client = SimpleNamespace(
        service_client=client_config["service_client"], config=lambda: client_config.copy()
    )
    config = {
        "client": client,
        "task_queue": "original-queue",
        "workflows": [object()],
        "activities": [object()],
        "workflow_runner": runner,
        "graceful_shutdown_timeout": service.timedelta(seconds=80),
    }
    built = SimpleNamespace(config=lambda: config.copy())
    connections, receivers = [], []
    error = ConnectionError("receiver transport unavailable")

    class Runtime:
        def __init__(self, *, telemetry):
            self.telemetry = telemetry

    async def connect(selected):
        connections.append(selected)
        assert selected.runtime is not original_runtime
        assert replace(selected, runtime=original_runtime) == connection
        if connect_fails:
            raise error
        return SimpleNamespace(config=selected)

    def new_client(**options):
        assert {k: v for k, v in options.items() if k != "service_client"} == {
            k: v for k, v in client_config.items() if k != "service_client"
        }
        return SimpleNamespace(service_client=options["service_client"], config=options)

    def new_worker(**options):
        assert options["client"].service_client.config.runtime is not original_runtime
        assert options["activities"] == [] and options["no_remote_activities"] is True
        assert {
            k: v
            for k, v in options.items()
            if k not in {"client", "activities", "no_remote_activities"}
        } == {k: v for k, v in config.items() if k not in {"client", "activities"}}
        receiver = SimpleNamespace(config=options)
        receivers.append(receiver)
        return receiver

    monkeypatch.setattr(runtime_sdk, "Runtime", Runtime)
    monkeypatch.setattr(service_sdk.ServiceClient, "connect", connect)
    monkeypatch.setattr(client_sdk, "Client", new_client)
    monkeypatch.setattr(worker_sdk, "Worker", new_worker)
    if connect_fails:
        with pytest.raises(ConnectionError) as caught:
            asyncio.run(worker.workflow_receiver(built, client))
        assert caught.value is error and receivers == []
    else:
        assert asyncio.run(worker.workflow_receiver(built, client)) is receivers[0]
    assert len(connections) == 1
    assert connection.runtime is original_runtime and config["activities"]


@pytest.mark.parametrize("fault", ["target", "other", None])
def test_generated_peer_records_only_an_actual_target_kill_failure(tmp_path, fault):
    cli = worker.peer(tmp_path)
    client = tmp_path / "private-client-config"
    client.mkdir()
    (client / "config.json").write_text("{}")
    target, other = "1" * 64, "2" * 64
    database = tmp_path / "docker.json"
    database.write_text(
        json.dumps({"creates": 1, "containers": {target: {"State": {"Running": True}}}})
    )
    if fault is not None:
        (tmp_path / "fail-kill-cid").write_text(target if fault == "target" else other)
    result = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--config",
            str(client),
            "--host",
            "unix:///fixture/docker.sock",
            "kill",
            target,
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    receipt = tmp_path / "native-stop-failures.jsonl"
    state = json.loads(database.read_text())["containers"][target]["State"]
    if fault == "target":
        assert result.returncode == 1 and result.stdout == result.stderr == ""
        assert state["Running"] is True
        assert [json.loads(line) for line in receipt.read_text().splitlines()] == [
            {"cid": target, "kind": "native_kill_failure"}
        ]
        assert receipt.stat().st_mode & 0o777 == 0o600
        assert str(client) not in receipt.read_text()
    else:
        assert result.returncode == 0 and result.stdout == target + "\n" and result.stderr == ""
        assert state["Running"] is False
        assert not receipt.exists()
