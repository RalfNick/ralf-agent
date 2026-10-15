"""New canonical actual Worker/PG fixture; native peer is structural evidence.

The peer executes genuine child processes and writes genuine workspace files.
Its Docker inventory remains synthetic and is never real-daemon stop evidence.
All fault flags are test transport/PG controls, not execution authorities.
"""

import asyncio
import json
import os
import re
import signal
import sys
import threading
import time
from collections import Counter
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from ralf_agent import (
    ComponentRegistry,
    ModelResponse,
    Scope,
    TemporalProfile,
    TemporalProfileCatalog,
    TemporalRuntimeBuilder,
)
from ralf_agent.governance import DeploymentAdmissionPolicy
from tests.test_temporal_connected_coding_integration import (
    StructuralCompletionGate,
    StructuralProvider,
)
from tests.test_temporal_parallel_coding_service import parallel_peer


@contextmanager
def definition_mismatch_trace(directory):
    """RAISE-only private diagnostics; never install per-call Python tracing."""
    try:
        marker = Path(directory) / "trace-coding-definition-mismatch"
        monitoring = getattr(sys, "monitoring", None)
        enabled = marker.exists() or os.getenv("RALF_TEST_DEPLOYMENT_CODING_ERROR_TRACE") == "1"
        enabled = enabled and monitoring is not None
        if enabled:
            marker.touch(mode=0o600)
            import ralf_agent
            from ralf_agent.codex_rpc import CodexRPCError
            from ralf_agent.errors import CloseIncomplete, RalfError

            prefix = str(Path(ralf_agent.__file__).parent) + os.sep
            path = Path(directory) / "definition-mismatch-locations.jsonl"
    except Exception:
        enabled = False
    if not enabled:
        yield False  # Includes Python 3.11: no sys.settrace fallback.
        return
    active, seen, lock = True, set(), threading.Lock()

    def raised(code, instruction_offset, exception):
        if not active or not code.co_filename.startswith(prefix):
            return None
        try:
            kind = (type(exception).__module__, type(exception).__name__)
            if kind[0] not in {
                "ralf_agent.errors",
                "ralf_agent.codex_runner",
                "ralf_agent.codex_rpc",
            } or not isinstance(exception, (RalfError, CodexRPCError)):
                return None
            report = None
            if type(exception) is CloseIncomplete:
                original = object.__getattribute__(exception, "__dict__").get("report")
                if type(original) is dict and len(original) == 1:
                    for field, allowed in (
                        ("coding_resource", ("retirement_unconfirmed", "cleanup_still_owned")),
                        ("coding_transport", ("cleanup_unconfirmed",)),
                    ):
                        value = original.get(field)
                        if type(value) is str and value in allowed:
                            report = {field: value}
                            break
            line = next(
                (
                    line
                    for start, end, line in code.co_lines()
                    if start <= instruction_offset < end and line is not None
                ),
                code.co_firstlineno,
            )
            key = (
                Path(code.co_filename).name,
                code.co_name,
                line,
                kind,
                None if report is None else tuple(report.items()),
            )
            with lock:
                if key not in seen and len(seen) < 64:
                    seen.add(key)
                    descriptor = os.open(
                        path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600
                    )
                    try:
                        os.fchmod(descriptor, 0o600)
                        os.write(
                            descriptor,
                            (
                                json.dumps(
                                    {
                                        "pid": os.getpid(),
                                        "basename": key[0],
                                        "function": key[1],
                                        "line": key[2],
                                        "exception_module": kind[0],
                                        "exception_class": kind[1],
                                        "monotonic": time.monotonic(),
                                        **({"report": report} if report is not None else {}),
                                    }
                                )
                                + "\n"
                            ).encode(),
                        )
                    finally:
                        os.close(descriptor)
        except Exception:
            pass  # Diagnostic failures never replace the original exception.
        return None  # RAISE is nonlocal; never return monitoring.DISABLE.

    tool, previous, installed = None, None, False
    try:
        for candidate in (3, 4, 0, 1, 2, 5):
            if monitoring.get_tool(candidate) is None and monitoring.get_events(candidate) == 0:
                try:
                    monitoring.use_tool_id(candidate, "ralf-test-coding-errors")
                except ValueError:
                    continue  # Another tool won the slot; never take it over.
                tool = candidate
                break
        if tool is not None:
            previous = monitoring.register_callback(tool, monitoring.events.RAISE, raised)
            if previous is None:
                monitoring.set_events(tool, monitoring.events.RAISE)
                installed = True
    except Exception:
        pass
    try:
        yield installed
    finally:
        active = False
        if tool is not None:
            for method, args in (
                ("set_events", (tool, 0)),
                ("register_callback", (tool, monitoring.events.RAISE, previous)),
                ("free_tool_id", (tool,)),
            ):
                with suppress(Exception):
                    getattr(monitoring, method)(*args)


class CountingProvider(StructuralProvider):
    identity = {"kind": "deployment-coding-structural-provider", "version": "120"}

    def __init__(self, directory):
        self.directory = Path(directory)

    async def complete(self, messages, tools):
        with (self.directory / "model-calls.jsonl").open("a") as output:
            output.write(json.dumps({"pid": os.getpid(), "tools": len(tools)}) + "\n")
        if not tools and (self.directory / "block-aux-model").exists():
            from tests.test_temporal_deployment_dispatch_service import _eventually

            (self.directory / "block-aux-model.attempted").touch()
            await _eventually(
                lambda: asyncio.sleep(0, result=(self.directory / "block-aux-model").exists()),
                lambda blocked: not blocked,
                seconds=120,
            )
        if not tools and any("Complete plain" in str(m.get("content")) for m in messages):
            return ModelResponse(output="plain-finished")
        return await super().complete(messages, tools)


def provider_factory(config, context):
    return CountingProvider(config["directory"])


def completion_factory(config, context):
    from ralf_agent import ModelParentVerificationStage, ParentCompletionPolicy

    return {
        "checked": ParentCompletionPolicy(
            StructuralCompletionGate(),
            model_stage=ModelParentVerificationStage(
                instructions="Return fixed structural-verdict."
            ),
            verifier_budget=2,
        )
    }


def admission_factory(config, context):
    with (Path(config["directory"]) / "factory-calls.jsonl").open("a") as output:
        output.write(json.dumps({"scope": asdict(context.scope)}) + "\n")
    return DeploymentAdmissionPolicy(**config["policy"])


async def admission_async_factory(config, context):
    return admission_factory(config, context)


def _coding_cpu_enabled(directory):
    marker = Path(directory) / "capture-coding-cpu"
    enabled = os.getenv("RALF_TEST_DEPLOYMENT_CODING_CPU") == "1"
    try:
        enabled = marker.exists() or enabled
        if enabled:
            marker.touch(mode=0o600)
    except OSError:
        pass  # Diagnostic marker I/O must not change the original test operation.
    return enabled


def peer(directory, *, hold=False):
    directory = Path(directory)
    _coding_cpu_enabled(directory)
    cli = parallel_peer(directory)
    source = cli.read_text()
    kill_failure = (
        "if (root/'fail-kill').exists() or ((root/'fail-kill-cid').exists() and "
        "(root/'fail-kill-cid').read_text()==a[-1]): sys.exit(1)"
    )
    assert source.count(kill_failure) == 1
    source = source.replace(
        kill_failure,
        kill_failure.removesuffix(" sys.exit(1)")
        + "\n  fd=os.open(root/'native-stop-failures.jsonl',os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)"
        + "\n  with os.fdopen(fd,'a') as out:"
        + "\n   os.fchmod(out.fileno(),0o600);out.write(json.dumps({'cid':a[-1],'kind':'native_kill_failure'})+'\\n')"
        + "\n  sys.exit(1)",
        1,
    )
    before = "     (root/('turn-ready-'+cid)).touch()"
    after = (
        "     witness={'pid':os.getpid(),'cid':cid,'path':str(workspace/'answer.txt')}\n"
        "     with (root/'native-commits.jsonl').open('a') as out:"
        "out.write(json.dumps(witness)+'\\n')\n" + before
    )
    assert before in source
    source = source.replace(before, after, 1).replace("time.monotonic()+25", "time.monotonic()+120")
    if SDKTiming(directory).enabled:
        methods = (
            "initialize",
            "config/read",
            "configRequirements/read",
            "experimentalFeature/list",
            "permissionProfile/list",
            "mcpServerStatus/list",
            "skills/list",
            "plugin/list",
            "plugin/installed",
            "thread/start",
            "turn/start",
        )
        timing = (
            f" native_rpc_methods=frozenset({methods!r});native_rpc_counts={{}}\n"
            " def native_rpc_timing(method,phase):\n"
            "  if method not in native_rpc_methods or phase not in {'received','responded'}:return\n"
            "  if phase=='received':native_rpc_counts[method]=native_rpc_counts.get(method,0)+1\n"
            "  record={'method':method,'phase':phase,'count':native_rpc_counts[method],"
            "'pid':os.getpid(),'monotonic':time.monotonic()}\n"
            "  fd=os.open(root/'native-rpc-timing.jsonl',os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)\n"
            "  with os.fdopen(fd,'a') as out:\n"
            "   os.fchmod(out.fileno(),0o600);out.write(json.dumps(record)+'\\n')\n"
            " def send(value):\n"
            "  print(json.dumps(value),flush=True)\n"
            "  if 'id' in value and 'result' in value:native_rpc_timing(method,'responded')"
        )
        send = " def send(value):print(json.dumps(value),flush=True)"
        receive = "  message=json.loads(line);method=message['method']"
        assert source.count(send) == source.count(receive) == 1
        source = source.replace(send, timing, 1).replace(
            receive, receive + "\n  native_rpc_timing(method,'received')", 1
        )
    cli.write_text(source)
    if not hold:
        (directory / "release-turns").touch()
    return cli


def actual_create_cli(directory, executable, mode):
    """Delegate the explicitly selected real Docker; hold/lose a real CREATE reply."""
    assert mode in {"hold", "reply-loss", "unreachable"}
    path = Path(directory) / "actual-create-cli"
    program = r"""
import json,os,pathlib,subprocess,sys,time
root=pathlib.Path(__file__).parent
args=sys.argv[1:]
operation=args[args.index('--host')+2]
with (root/'actual-docker-calls.jsonl').open('a') as out:
 out.write(json.dumps({'pid':os.getpid(),'operation':operation,'args':args,'inventory_blocked':operation in {'ps','inspect'} and (root/'block-actual-inventory').exists()})+'\n')
if operation in {'ps','inspect'} and (root/'block-actual-inventory').exists():sys.exit(1)
if operation=='start':raise RuntimeError('This no-model CREATE probe never permits START')
result=subprocess.run([EXECUTABLE,*args],capture_output=True)
if operation=='create' and result.returncode==0:
 cid=result.stdout.decode().strip()
 assert len(cid)==64 and all(c in '0123456789abcdef' for c in cid)
 (root/'actual-create.json').write_text(json.dumps({'pid':os.getpid(),'cid':cid}))
 if MODE=='unreachable':(root/'block-actual-inventory').touch()
 if MODE=='hold':
  deadline=time.monotonic()+60
  while (root/'hold-actual-create').exists():
   if time.monotonic()>deadline:raise RuntimeError('Original actual CREATE gate was not released')
   time.sleep(.01)
 if MODE in {'reply-loss','unreachable'}:sys.exit(1)
sys.stdout.buffer.write(result.stdout);sys.stdout.buffer.flush()
sys.stderr.buffer.write(result.stderr);sys.stderr.buffer.flush()
sys.exit(result.returncode)
""".replace("EXECUTABLE", repr(executable)).replace("MODE", repr(mode))
    # The generated CLI is a pinned test adapter; all daemon facts come from real Docker.
    path.write_text("#!" + __import__("sys").executable + "\n" + program)
    path.chmod(0o700)
    if mode == "hold":
        (Path(directory) / "hold-actual-create").touch()
    return path


def _toml(value):
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(json.dumps(k) + " = " + _toml(v) for k, v in value.items() if v is not None)
            + "}"
        )
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return json.dumps(value)


def selected_profile(directory, profile, syntax):
    if syntax == "sdk":
        return profile
    catalog = {
        "kind": "temporal-profiles",
        "schema_version": 1,
        "default": {"name": profile.name, "version": profile.version},
        "profiles": [profile.to_dict()],
    }
    path = Path(directory) / ("coding-profile." + syntax)
    if syntax == "json":
        path.write_text(json.dumps(catalog))
    else:
        assert syntax == "toml"
        path.write_text("\n".join(k + " = " + _toml(v) for k, v in catalog.items()) + "\n")
    result = TemporalProfileCatalog.from_file(path).default_profile
    assert result.identity == profile.identity
    return result


async def application(directory):
    directory = Path(directory)
    data = json.loads((directory / "application.json").read_text())
    if data.get("never_go"):
        from ralf_agent.codex_create_supervisor import CreateSupervisor
        from tests.test_temporal_coding_create_supervision_integration import abort_before_go

        os.environ["RALF_CONNECTED_DIRECTORY"] = str(directory)
        CreateSupervisor.start_once = abort_before_go
    registry = ComponentRegistry()
    registry.register("provider", "deployment-coding-peer", provider_factory)
    registry.register("parent_completion_policies", "deployment-coding-check", completion_factory)
    registry.register("admission_policy", "deployment-coding-custom", admission_factory)
    registry.register_async(
        "admission_policy", "deployment-coding-custom-async", admission_async_factory
    )
    profile = selected_profile(directory, TemporalProfile(**data["profile"]), data["syntax"])
    return await TemporalRuntimeBuilder(registry, base_dir=directory).abuild(
        profile,
        scope=Scope(**data["scope"]),
        **(
            {"admission_policy": DeploymentAdmissionPolicy(**data["host_policy"])}
            if "host_policy" in data
            else {}
        ),
    )


class SDKTiming:
    """Opt-in SDK spans; never replace pinned production callbacks or methods."""

    names = {
        "view",
        "command",
        "reserve",
        "bind_deployment_root",
        "release_deployment_root",
        "coding_state",
        "coding_grant",
        "admit_coding_phase",
        "describe",
        "describe_namespace",
        "coding_receipt",
        "tool_execution_started",
        "tool_execution_ended",
        "deployment_call_started",
        "deployment_call_ended",
        "deployment_child_epoch",
        "deployment_seal",
        "deployment_coding_call_stopped",
        "coding_composition_child_execution",
        "coding_composition_child_stopped",
        "admit_coding_composition_submission",
        "close_deployment_coding_submissions",
        "deployment_coding_validation",
    }
    kinds = {
        "status",
        "diagnostics",
        "submission",
        "deployment_configuration",
        "deployment_admission",
        "deployment_closure",
        "deployment_retirement",
        "deployment_submission",
        "deployment_coding_call_candidate",
        "deployment_coding_validation",
        "deployment_start",
        "coding_composition_candidates",
        "coding_composition_admission",
        "coding_composition_children",
        "coding_composition_proof",
        "coding_execution",
        "owner",
        "prepared",
        "thread",
        "turn",
        "stop",
        "observation",
        "error",
        "result_candidate",
        "namespace_absent",
        "create_not_dispatched",
    }
    methods = {
        "initialize",
        "config/read",
        "configRequirements/read",
        "experimentalFeature/list",
        "permissionProfile/list",
        "mcpServerStatus/list",
        "skills/list",
        "plugin/list",
        "plugin/installed",
        "thread/start",
        "turn/start",
        "thread/read",
        "turn/interrupt",
        "check",
        "resource_state",
        "cancelled",
        "authorize",
        "adopt",
        "validate_registration",
    }
    response_keys = {
        "version",
        "scope",
        "namespace",
        "run_id",
        "execution_epoch",
        "original_execution_epoch",
        "identity_digest",
        "revision",
        "state",
        "stop_requested",
        "sealed",
        "edge",
        "proof_digest",
        "error",
        "registry_id",
        "registry_execution_epoch",
        "configuration_version",
        "policy",
        "root_identity_digest",
        "submission_digest",
        "held",
        "retired",
        "close_requested",
        "admitted",
        "activity_timeout",
        "task_queue",
        "request_digest",
        "manifest_digest",
    }
    error_codes = {
        "definition_mismatch",
        "validation_error",
        "authorization_denied",
        "not_found",
        "capacity_exceeded",
        "idempotency_conflict",
        "runtime_closed",
        "unavailable",
        "deadline_exceeded",
        "deployment_control_unavailable",
        "parent_activity_unavailable",
    }

    @classmethod
    def query_summary(cls, value):
        if type(value) is not dict:
            return {"response_type": "list" if type(value) is list else "other"}
        keys = sorted(key for key in value if type(key) is str and key in cls.response_keys)
        error = value.get("error")
        return {
            "response_type": "dict",
            "response_keys": keys,
            "unrecognized_key_count": len(value) - len(keys),
            "query_status": "domain_error" if "error" in value else "value",
            "query_error_code": error
            if type(error) is str and error in cls.error_codes
            else "omitted"
            if "error" in value
            else None,
        }

    def __init__(self, directory):
        self.directory = Path(directory)
        marker = self.directory / "capture-coding-timing"
        self.enabled = marker.exists() or os.getenv("RALF_TEST_DEPLOYMENT_CODING_TIMING") == "1"
        if self.enabled:
            marker.touch(mode=0o600)  # Separate Worker processes reuse the same opt-in.
        self.path = self.directory / "sdk-timing.jsonl"
        self.counts, self.sequence = Counter(), 0

    @staticmethod
    def _origin():
        origin, runner_await = "other", None
        frame = sys._getframe(1)
        for _ in range(32):
            if frame is None:
                break
            filename, name = Path(frame.f_code.co_filename).name, frame.f_code.co_name
            if filename == "temporal_coding_runtime.py" and name in {"validate", "query", "update"}:
                origin = "coding_" + name
            if filename == "codex_runner.py" and name in {
                "_request",
                "_terminal",
                "_authority_method",
                "_execute",
                "_retire",
            }:
                if runner_await is None:
                    method = frame.f_locals.get("method")
                    runner_await = {
                        "frame": name,
                        "method": method if method in SDKTiming.methods else None,
                    }
            frame = frame.f_back
        return origin, runner_await

    def _write(self, record):
        descriptor = os.open(
            self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600
        )
        try:
            os.write(descriptor, (json.dumps(record, sort_keys=True) + "\n").encode())
        finally:
            os.close(descriptor)

    async def _loop_lag(self):
        loop, count, interval = asyncio.get_running_loop(), 0, 0.05
        while True:
            expected = loop.time() + interval
            await asyncio.sleep(max(0, expected - loop.time()))
            observed = loop.time()
            count += 1
            descriptor = os.open(
                self.directory / "worker-loop-lag.jsonl",
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
                0o600,
            )
            try:
                os.write(
                    descriptor,
                    (
                        json.dumps(
                            {
                                "pid": os.getpid(),
                                "count": count,
                                "interval_seconds": interval,
                                "expected_monotonic": expected,
                                "observed_monotonic": observed,
                                "lag_seconds": max(0, observed - expected),
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    ).encode(),
                )
            finally:
                os.close(descriptor)

    @asynccontextmanager
    async def loop_probe(self):
        if not self.enabled:
            yield
            return
        task = asyncio.create_task(self._loop_lag())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @contextmanager
    def span(self, operation, workflow_id, name, payload):
        if not self.enabled:
            yield None
            return
        kind = payload.get("kind") if type(payload) is dict else None
        name = name if type(name) is str and name in self.names else "other"
        kind = kind if type(kind) is str and kind in self.kinds else None
        workflow_id = (
            workflow_id
            if type(workflow_id) is str
            and re.fullmatch(r"ralf-temporal-(?:deployment-)?[0-9a-f]{64}", workflow_id)
            else "omitted"
        )
        origin, runner_await = self._origin()
        self.sequence += 1
        self.counts[(operation, name, kind, origin)] += 1
        started = time.monotonic()
        record = {
            "span": self.sequence,
            "pid": os.getpid(),
            "operation": operation,
            "workflow_id": workflow_id,
            "name": name,
            "kind": kind,
            "origin": origin,
            "runner_await": runner_await,
            "count": self.counts[(operation, name, kind, origin)],
            "started_monotonic": started,
        }
        self._write({**record, "phase": "started"})
        observation = {}
        error = None
        try:
            yield observation
        except BaseException as caught:
            error = caught
            raise
        finally:
            status = getattr(error, "status", None)
            self._write(
                {
                    **record,
                    "phase": "finished",
                    "elapsed_seconds": time.monotonic() - started,
                    "outcome": "returned" if error is None else "raised",
                    "exception_type": None if error is None else type(error).__name__,
                    "rpc_status": getattr(status, "name", None),
                    **observation,
                }
            )


def loop_timing_plugin(timing):
    """SDK lifecycle hook owns the probe without changing business ports."""
    from temporalio.worker import Plugin

    class LoopTiming(Plugin):
        def configure_worker(self, config):
            return config

        async def run_worker(self, worker, next):
            from tests.temporal_deployment_coding_cpu_fixture import coding_cpu_profile

            with coding_cpu_profile(timing.directory):
                async with timing.loop_probe():
                    return await next(worker)

        def configure_replayer(self, config):
            return config

        def run_replayer(self, replayer, histories, next):
            return next(replayer, histories)

    return LoopTiming()


class TimedWorkflowService:
    def __init__(self, original, timing):
        self.original, self.timing = original, timing

    def __getattr__(self, name):
        return getattr(self.original, name)

    async def describe_namespace(self, *args, **options):
        with self.timing.span("namespace", None, "describe_namespace", None):
            return await self.original.describe_namespace(*args, **options)


class FaultClient:
    """Fail only transport to real original SDK handles; never synthesize proof."""

    def __init__(self, original, directory):
        self.original, self.directory = original, Path(directory)
        self.timing = SDKTiming(directory)
        self._workflow_service = None
        cpu_enabled = _coding_cpu_enabled(self.directory)
        self._timing_plugin = (
            loop_timing_plugin(self.timing) if self.timing.enabled or cpu_enabled else None
        )

    def __getattr__(self, name):
        return getattr(self.original, name)

    def get_workflow_handle(self, *args, **kwargs):
        return FaultHandle(self, self.original.get_workflow_handle(*args, **kwargs))

    @property
    def workflow_service(self):
        if not self.timing.enabled:
            return self.original.workflow_service
        if self._workflow_service is None:
            self._workflow_service = TimedWorkflowService(
                self.original.workflow_service, self.timing
            )
        return self._workflow_service

    def config(self, **options):
        config = self.original.config(**options)
        if self._timing_plugin is not None:
            config = {**config, "plugins": [*config["plugins"], self._timing_plugin]}
        return config


class FaultHandle:
    def __init__(self, owner, original):
        self.owner, self.original = owner, original

    def __getattr__(self, name):
        return getattr(self.original, name)

    async def describe(self, **options):
        with self.owner.timing.span("describe", self.original.id, "describe", None):
            return await self.original.describe(**options)

    async def query(self, name, *args, **options):
        with self.owner.timing.span(
            "query", self.original.id, name, args[0] if args else None
        ) as observation:
            result = await self._query(name, *args, **options)
            if observation is not None:
                observation.update(self.owner.timing.query_summary(result))
            return result

    async def _query(self, name, *args, **options):
        from temporalio.service import RPCError, RPCStatusCode

        if (self.owner.directory / "block-cold-verification").exists():
            request = args[0] if args else {}
            if name == "view" and request.get("kind") == "deployment_coding_call_candidate":
                (self.owner.directory / "block-cold-verification.attempted").touch()
                raise RPCError(
                    "Controlled original cold candidate read unavailable",
                    RPCStatusCode.UNAVAILABLE,
                    b"",
                )
        result = await self.original.query(name, *args, **options)
        gate = self.owner.directory / "block-control-observe"
        if gate.exists() and name == "view" and args and args[0].get("kind") == "diagnostics":
            from temporalio import activity

            try:
                info = activity.info()
            except RuntimeError:
                info = None
            if info is not None and info.activity_type == "ralf.temporal.control.v1":
                marker = self.owner.directory / "held-control-observe.json"
                if not marker.exists():
                    marker.write_text(
                        json.dumps(
                            {
                                "pid": os.getpid(),
                                "workflow_id": info.workflow_id,
                                "execution_epoch": info.workflow_run_id,
                                "activity_id": info.activity_id,
                            }
                        )
                    )
                    marker.chmod(0o600)
                while gate.exists():  # noqa: ASYNC110 -- parent process owns this file gate.
                    await asyncio.sleep(0.05)
        return result

    async def execute_update(self, name, payload, **options):
        with self.owner.timing.span("update", self.original.id, name, payload):
            return await self._execute_update(name, payload, **options)

    async def _execute_update(self, name, payload, **options):
        from temporalio.service import RPCError, RPCStatusCode

        flag = {
            "tool_execution_ended": "block-tool-end",
            "coding_composition_child_stopped": "block-child-stop",
            "deployment_coding_call_stopped": "block-cold-call",
            "release_deployment_root": "block-release",
        }.get(name)
        if name == "coding_receipt" and payload.get("kind") == "stop":
            flag = "block-native-stop"
        if name == "deployment_call_ended":
            # Isolate the original Coding Tool carrier, not unrelated Model/ACK calls.
            if payload.get("activity_name") == "ralf.temporal.tool.v1":
                flag = "block-deployment-end"
        if flag and (self.owner.directory / flag).exists():
            (self.owner.directory / (flag + ".attempted")).touch()
            raise RPCError(
                "Controlled original Coding ACK transport unavailable",
                RPCStatusCode.UNAVAILABLE,
                b"",
            )
        if name == "coding_receipt" and payload.get("kind") == "stop":
            gate = self.owner.directory / "hold-native-stop"
            if gate.exists():
                (self.owner.directory / "hold-native-stop.attempted").touch()
                # Delay this original ACK without discarding its execution stack.
                # This test-only bound never changes Runner or Activity deadlines.
                async with asyncio.timeout(30):
                    while gate.exists():  # noqa: ASYNC110 -- bounded, test-owned gate.
                        await asyncio.sleep(0.05)
        result = await self.original.execute_update(name, payload, **options)
        if name == "release_deployment_root":
            flag = self.owner.directory / "lose-release-reply"
            if flag.exists():
                flag.unlink()
                (self.owner.directory / "lost-release-reply.json").write_text(
                    json.dumps(
                        {"workflow_id": self.original.id, "payload": payload, "result": result}
                    )
                )
                raise RPCError(
                    "Controlled reply loss after actual original Registry release Update",
                    RPCStatusCode.UNAVAILABLE,
                    b"",
                )
        if name == "coding_receipt" and payload.get("kind") in {"turn", "result_candidate"}:
            flag = self.owner.directory / (
                "crash-after-turn" if payload["kind"] == "turn" else "crash-after-candidate"
            )
            if flag.exists():
                flag.unlink()
                (self.owner.directory / "actual-worker-crash.json").write_text(
                    json.dumps(
                        {"pid": os.getpid(), "workflow_id": self.original.id, "payload": payload}
                    )
                )
                os._exit(71)
        return result


async def run_owned_worker(built, runtime, stopped, receiver):
    """Test-only handoff: stop SDK pollers/handlers, then await original end ACKs."""
    async with built:
        print("DEPLOYMENT_CODING_WORKER_READY", flush=True)
        await stopped.wait()
        # A Workflow-only receiver must remain through the independent end ACKs
        # after the original Worker's Activity/Workflow pollers have stopped.
        async with receiver:
            await built.shutdown()
            await runtime.close_deployment_execution(wait_timeout=80)
    print("DEPLOYMENT_CODING_WORKER_HANDOFF_COMPLETE", flush=True)


async def workflow_receiver(built, client):
    """Keep the original Workflow queue available on a separate SDK runtime."""
    from dataclasses import replace

    from temporalio.client import Client
    from temporalio.runtime import Runtime, TelemetryConfig
    from temporalio.service import ServiceClient
    from temporalio.worker import Worker

    # SDK 1.34 rejects overlapping workflow pollers within one Rust runtime,
    # even while the original Worker is constructed but not yet shutting down.
    connection = replace(client.service_client.config, runtime=Runtime(telemetry=TelemetryConfig()))
    service = await ServiceClient.connect(connection)
    receiver_client = Client(**{**client.config(), "service_client": service})
    return Worker(
        **{
            **built.config(),
            "client": receiver_client,
            "activities": [],
            "no_remote_activities": True,
        }
    )


async def worker():
    from temporalio.client import Client

    from ralf_agent.temporal import build_temporal_worker

    directory = Path(os.environ["RALF_DEPLOYMENT_CODING_DIRECTORY"])
    with definition_mismatch_trace(directory):
        assembly = await application(directory)
        queue = json.loads((directory / "application.json").read_text())["queue"]
        client = FaultClient(
            await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"]), directory
        )
        built = build_temporal_worker(
            client,
            task_queue=queue,
            runtime=assembly._runtime,
            release=assembly.release,
            max_concurrent_activities=32,
            graceful_shutdown_timeout=timedelta(seconds=80),
        )
        stopped = asyncio.Event()
        receiver = await workflow_receiver(built, client)
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, stopped.set)
        try:
            await run_owned_worker(built, assembly._runtime, stopped, receiver)
        finally:
            loop.remove_signal_handler(signal.SIGTERM)


if __name__ == "__main__":
    from tests.temporal_deployment_coding_worker_fixture import worker as canonical_worker

    asyncio.run(canonical_worker())
