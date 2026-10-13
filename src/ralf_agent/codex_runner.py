"""Finite native Coding resource; original LocalEngine owns business authority."""

import asyncio
import copy
import hashlib
import math
import os
import stat
from pathlib import Path

from .codex_coding_profile import CodexCodingProfile
from .codex_environment import DockerCodingEnvironment
from .codex_protocol import CodexCodingProtocol, CodexProtocol, _snapshot
from .codex_rpc import CodexRPCClosed, CodexRPCError, CodexRPCTransport
from .errors import (
    AuthorizationDenied,
    CloseIncomplete,
    CoordinatorBusy,
    DefinitionMismatch,
    ExecutionHostFailed,
    IdempotencyConflict,
    ValidationError,
)
from .executors import DispatchEnvelope, EffectObservation
from .runner_journal import RunnerJournal
from .types import canonical, digest


class RunnerUnavailable(ExecutionHostFailed):
    """A native interaction or result cannot be handled by this finite resource."""

    code = "runner_unavailable"

    def __init__(self, reason):
        super().__init__("Native Coding capability is unavailable: " + reason)
        self.reason = reason


class RunnerOutcomeUnknown(ExecutionHostFailed):
    """Native submission/effects remain uncertain; repeating startup is forbidden."""

    code = "runner_outcome_unknown"

    def __init__(self, reason):
        super().__init__("Native Coding outcome is unknown: " + reason)
        self.reason = reason


def _pin(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise ValidationError("Coding runner physical aliases are unavailable")
    return {"path": str(path.resolve(strict=True)), "device": info.st_dev, "inode": info.st_ino}


def _dispatch(envelope):
    if type(envelope) is not DispatchEnvelope:
        raise ValidationError("Coding runner requires an original DispatchEnvelope")
    context = envelope.context
    return {
        "scope": {"workspace": context.scope.workspace, "principal": context.scope.principal},
        "run_id": context.run_id,
        "action_id": context.action_id,
        "attempt_id": context.attempt_id,
        "effect_key": context.effect_key,
        "execution_epoch": context.execution_epoch,
        "tool_manifest": envelope.tool_manifest,
        "arguments": envelope.arguments,
        "operation_digest": envelope.operation_digest,
    }


class CodexCodingRunner:
    """One logical Action, one native Thread/Turn, one retired contained resource.

    Construction never prepares a container or submits native work. No credentials
    are read or injected. Requests are not retried; session continuation and native
    wait replies are unavailable. Unknown usage is not reported as zero.
    """

    def __init__(
        self,
        root,
        *,
        journal: RunnerJournal,
        docker_executable: str,
        docker_host: str,
        request_timeout: float = 30,
    ):
        try:
            root = Path(root)
            executable = Path(docker_executable)
            valid = (
                root.is_absolute()
                and root.is_dir()
                and not root.is_symlink()
                and root.stat().st_uid == os.getuid()
                and stat.S_IMODE(root.stat().st_mode) == 0o700
                and type(journal) is RunnerJournal
                and executable.is_absolute()
                and executable.is_file()
                and os.access(executable, os.X_OK)
                and type(docker_host) is str
                and docker_host.startswith("unix:///")
                and not any(c in docker_host for c in ("\0", "\n", "\r", "?", "#"))
                and type(request_timeout) in (int, float)
                and math.isfinite(request_timeout)
                and 0 < request_timeout <= 60
            )
        except (OSError, TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise ValidationError(
                "Coding runner requires private pins, original journal and deadline"
            )
        self._root = root
        self._root_pin = _pin(root)
        self._journal = journal
        self._timeout = request_timeout
        self._docker = str(executable)
        self._host = docker_host
        self._profile = CodexCodingProfile()
        self._protocol = CodexProtocol()
        self._identity = {
            "kind": "codex-coding-runner",
            "version": "1",
            "root": self._root_pin,
            "docker_executable": _pin(executable.resolve(strict=True)),
            "docker_host": docker_host,
            "journal": journal.identity,
            "profile": self._profile.identity,
            "protocol": CodexCodingProtocol().identity,
            "request_timeout": request_timeout,
            "recovery_modes": ["none"],
            "resource_lifecycle_version": "2",
            "credentials": "unavailable",
            "usage_bound": "unknown",
        }
        self._active = None
        self._closing = False

    @property
    def identity(self):
        return copy.deepcopy(self._identity)

    @property
    def active_operations(self):
        return int(self._active is not None)

    def _check_root(self):
        try:
            if (
                _pin(self._root) != self._root_pin
                or stat.S_IMODE(self._root.stat().st_mode) != 0o700
                or self._root.stat().st_uid != os.getuid()
                or _pin(Path(self._docker).resolve(strict=True))
                != self._identity["docker_executable"]
                or self._journal.identity != self._identity["journal"]
            ):
                raise DefinitionMismatch("Original Coding runner dependencies changed")
        except OSError:
            raise DefinitionMismatch(
                "Original Coding runner physical pins are unavailable"
            ) from None

    def _authority(self, envelope, authority):
        try:
            from .local_delegated_coding import LocalCodingAuthority
        except ImportError:
            raise AuthorizationDenied("Original Local Coding authority is unavailable") from None
        if type(authority) is not LocalCodingAuthority:
            raise AuthorizationDenied(
                "Coding execution requires the original LocalEngine authority"
            )
        return _snapshot(authority.check(envelope, self.identity), "original authority intent")

    def _location(self, envelope):
        value = _dispatch(envelope)
        resource_key = digest({"scope": value["scope"], "effect_key": value["effect_key"]})
        generation = digest({"dispatch": value, "runner": self.identity})[:32]
        return self._root / resource_key, "action-" + resource_key[:32], generation

    def _environment(self, envelope, *, create):
        self._check_root()
        path, resource_id, generation = self._location(envelope)
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
        elif not path.exists():
            return None
        return DockerCodingEnvironment(
            path,
            resource_id,
            docker_executable=self._docker,
            docker_host=self._host,
            command_timeout=self._timeout,
            retire_on_stop=True,
            expected_generation=generation,
        )

    def _binding(self, envelope, intent, state):
        return {
            "request": intent,
            "runner": self.identity,
            "dispatch": _dispatch(envelope),
            "environment": {
                "identity": state["identity"],
                "container_id": state["container_id"],
                "generation": state["generation"],
            },
        }

    @staticmethod
    def _grant(authority, method, params, binding):
        grant = _snapshot(authority.authorize(method, params, binding), "native startup grant")
        if (
            type(grant) is not dict
            or grant.get("method") != method
            or canonical(grant.get("params")) != canonical(params)
            or canonical(grant.get("binding")) != canonical(binding)
            or type(grant.get("execute")) is not bool
        ):
            raise AuthorizationDenied("Native startup grant differs from the original request")
        if not grant["execute"]:
            raise RunnerOutcomeUnknown("startup already granted")

    def _observe(self, owner, kind, evidence):
        value = {"kind": kind, **evidence}
        if owner["journaled"]:
            context = owner["envelope"].context
            self._journal.record_observation(
                context.scope,
                context.effect_key,
                binding=owner["binding"],
                observation=value,
            )
        owner["authority"].adopt(kind, value)

    @staticmethod
    def _cancelled(owner):
        if owner.get("native_error") is not None:
            raise owner["native_error"]
        if owner["authority"].cancelled():
            raise RunnerOutcomeUnknown("original execution cancelled")

    async def execute(self, envelope: DispatchEnvelope, authority) -> EffectObservation:
        intent = self._authority(envelope, authority)
        self._check_root()
        self._journal._check()
        arguments = envelope.arguments
        if (
            set(arguments) != {"task"}
            or type(arguments["task"]) is not str
            or not arguments["task"].strip()
            or len(arguments["task"]) > 8192
            or any(0xD800 <= ord(c) <= 0xDFFF for c in arguments["task"])
        ):
            raise ValidationError("Coding runner requires one bounded task string")
        if self._closing:
            raise RunnerUnavailable("resource closing")
        if self._active is not None:
            raise CoordinatorBusy("Another original Coding resource still owns execution")
        owner = {
            "envelope": envelope,
            "authority": authority,
            "intent": intent,
            "environment": None,
            "transport": None,
            "binding": None,
            "journaled": False,
            "prepared": False,
            "stop": None,
            "cleanup": None,
            "task": None,
            "cold": False,
            "supervision": None,
            "events": asyncio.Queue(maxsize=1000),
            "pump": None,
            "native_error": None,
            "ending": False,
            "original_state": authority.resource_state(envelope, self.identity),
        }
        self._active = owner
        owner["task"] = asyncio.create_task(self._execute(owner))
        try:
            return await asyncio.shield(owner["task"])
        except asyncio.CancelledError:
            owner["task"].cancel()
            await self._settle(owner["task"])
            await self._cleanup(owner)
            raise
        finally:
            if owner["stop"] is not None and owner["task"].done():
                self._active = None

    async def _request(self, owner, method, params, *, control=False):
        self._cancelled(owner)
        protocol = owner["control"] if control else self._protocol
        accepted = protocol.validate_request(method, params)
        result = await owner["transport"].request(method, accepted)
        return protocol.validate_response(method, result)

    async def _preflight(self, owner):
        from .codex_protocol import CodexCodingProtocol, CodexControlProtocol

        owner["control"] = CodexControlProtocol()
        coding = CodexCodingProtocol()
        # CodingProtocol identity is pinned in addition to the business Schema.
        if coding.identity["external_version"] != self._protocol.identity["external_version"]:
            raise DefinitionMismatch("Coding control and business protocol versions differ")
        queries = (
            (
                "initialize",
                {
                    "clientInfo": {"name": "ralf_coding_runner", "version": "1"},
                    "capabilities": {"experimentalApi": False},
                },
            ),
            ("config/read", {"cwd": "/workspace", "includeLayers": True}),
            ("configRequirements/read", None),
            ("experimentalFeature/list", {"limit": 200}),
            ("permissionProfile/list", {"cwd": "/workspace", "limit": 200}),
            ("mcpServerStatus/list", {"limit": 200, "detail": "full"}),
            ("skills/list", {"cwds": ["/workspace"], "forceReload": True}),
            ("plugin/list", {"cwds": ["/workspace"], "marketplaceKinds": ["local"]}),
            ("plugin/installed", {"cwds": ["/workspace"]}),
        )
        results = {}
        for method, params in queries:
            results[method] = await self._request(owner, method, params, control=True)
            if method == "initialize":
                await owner["transport"].notify("initialized")
        self._profile.validate_control(results)

    async def _execute(self, owner):
        candidate = None
        error = None
        try:
            async with asyncio.timeout(self._timeout):
                self._cancelled(owner)
                env = self._environment(owner["envelope"], create=True)
                owner["environment"] = env
                prepare_binding = {
                    "request": owner["intent"],
                    "runner": self.identity,
                    "dispatch": _dispatch(owner["envelope"]),
                    "environment": env.identity,
                }
                self._grant(owner["authority"], "prepare", {}, prepare_binding)
                owner["original_state"] = owner["authority"].resource_state(
                    owner["envelope"], self.identity
                )
                prepared = await env.prepare()
                owner["prepared"] = True
                inspected = await env.inspect()
                if (
                    prepared["identity"] != env.identity
                    or inspected["identity"] != env.identity
                    or not inspected["stopped"]
                    or inspected["fenced"]
                ):
                    raise DefinitionMismatch(
                        "Original Coding environment is not a fresh stopped resource"
                    )
                owner["authority"].adopt("prepared", inspected)
                self._authority(owner["envelope"], owner["authority"])
                owner["binding"] = self._binding(owner["envelope"], owner["intent"], inspected)
                context = owner["envelope"].context
                record = self._journal.begin(context.scope, context.effect_key, owner["binding"])
                owner["journaled"] = True
                if not record["execute"]:
                    raise RunnerOutcomeUnknown("original journal startup already exists")
                transport = CodexRPCTransport(
                    env.transport_argv(),
                    env=env.transport_env,
                    request_timeout=self._timeout,
                    coding_mode=True,
                )
                owner["transport"] = transport
                await transport.start()
                await self._preflight(owner)
                owner["pump"] = asyncio.create_task(self._pump(owner))
                self._cancelled(owner)
                params = self._protocol.validate_request(
                    "thread/start",
                    {
                        "cwd": "/workspace",
                        "approvalPolicy": "never",
                        "approvalsReviewer": "user",
                        "ephemeral": False,
                    },
                )
                self._grant(owner["authority"], "thread/start", params, owner["binding"])
                submitted = self._journal.mark_thread_submitted(
                    context.scope,
                    context.effect_key,
                    binding=owner["binding"],
                )
                if not submitted["execute"]:
                    raise RunnerOutcomeUnknown("original Thread submission already exists")
                thread = await self._request(owner, "thread/start", params)
                thread_id = thread["thread"]["id"]
                if thread["cwd"] != "/workspace" or thread["thread"]["cwd"] != "/workspace":
                    raise DefinitionMismatch("Native Thread changed the frozen Coding workspace")
                self._journal.record_thread(
                    context.scope,
                    context.effect_key,
                    binding=owner["binding"],
                    thread_id=thread_id,
                    process_epoch=inspected["generation"],
                )
                owner["authority"].adopt("thread", {"thread_id": thread_id})
                self._cancelled(owner)
                params = self._protocol.validate_request(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "cwd": "/workspace",
                        "approvalPolicy": "never",
                        "approvalsReviewer": "user",
                        "input": [
                            {
                                "type": "text",
                                "text": owner["envelope"].arguments["task"],
                                "text_elements": [],
                            }
                        ],
                    },
                )
                self._grant(owner["authority"], "turn/start", params, owner["binding"])
                submitted = self._journal.mark_turn_submitted(
                    context.scope,
                    context.effect_key,
                    binding=owner["binding"],
                )
                if not submitted["execute"]:
                    raise RunnerOutcomeUnknown("original Turn submission already exists")
                started = await self._request(owner, "turn/start", params)
                turn_id = started["turn"]["id"]
                self._journal.record_turn(
                    context.scope,
                    context.effect_key,
                    binding=owner["binding"],
                    turn_id=turn_id,
                )
                owner["authority"].adopt("turn", {"thread_id": thread_id, "turn_id": turn_id})
                await self._terminal(owner, thread_id, turn_id)
                history = await self._request(
                    owner,
                    "thread/read",
                    {
                        "threadId": thread_id,
                        "includeTurns": True,
                    },
                )
                candidate = self._candidate(history, thread_id, turn_id)
                self._observe(
                    owner,
                    "observation",
                    {
                        "native_status": "completed",
                        "thread_id": thread_id,
                        "turn_id": turn_id,
                        "final_thread_read": True,
                    },
                )
        except asyncio.CancelledError:
            error = RunnerOutcomeUnknown("execution interrupted before adoption")
            if owner["journaled"]:
                context = owner["envelope"].context
                self._journal.request_cancel(
                    context.scope, context.effect_key, binding=owner["binding"]
                )
            raise
        except (TimeoutError, CodexRPCError):
            error = RunnerOutcomeUnknown("native request or observation unavailable")
            raise error from None
        except Exception as exc:
            error = exc
            raise
        finally:
            await self._cleanup(owner)
            if error is not None:
                self._observe(
                    owner, "error", {"code": getattr(error, "code", "runner_outcome_unknown")}
                )
        candidate["artifacts"] = self._artifacts(owner["environment"])
        if owner["native_error"] is not None:
            self._observe(owner, "error", {"code": owner["native_error"].code})
            raise owner["native_error"]
        if not candidate["text"].strip() and not candidate["artifacts"]:
            error = RunnerUnavailable("empty native result")
            self._observe(owner, "error", {"code": error.code})
            raise error
        candidate["stop"] = {k: owner["stop"][k] for k in ("container_id", "generation", "fenced")}
        self._observe(owner, "result_candidate", {"result": candidate})
        return EffectObservation(candidate, source="codex-coding-runner")

    async def _terminal(self, owner, thread_id, turn_id):
        for _ in range(1000):
            self._cancelled(owner)
            try:
                event = await asyncio.wait_for(owner["events"].get(), timeout=0.05)
            except TimeoutError:
                continue
            method = event["method"]
            if "id" in event or any(
                name in method.lower() for name in ("auth", "approval", "input", "login")
            ):
                raise RunnerUnavailable("native interaction")
            if method == "turn/completed":
                params = event.get("params", {})
                turn = params.get("turn", {})
                if params.get("threadId") != thread_id or turn.get("id") != turn_id:
                    raise RunnerOutcomeUnknown("native terminal locator differs")
                status = turn.get("status")
                self._observe(
                    owner,
                    "observation",
                    {
                        "thread_id": thread_id,
                        "turn_id": turn_id,
                        "native_status": status,
                    },
                )
                if status != "completed":
                    raise RunnerOutcomeUnknown("native Turn did not complete")
                return
        raise RunnerOutcomeUnknown("native observation limit")

    async def _pump(self, owner):
        """Own every native event until namespace retirement and transport end."""
        try:
            for _ in range(1000):
                event = await owner["transport"].next_event()
                if not self._accept_event(owner, event):
                    return
            owner["native_error"] = RunnerOutcomeUnknown("native observation limit")
        except asyncio.CancelledError:
            raise
        except CodexRPCError as error:
            if not owner["ending"] or type(error) is not CodexRPCClosed:
                owner["native_error"] = RunnerOutcomeUnknown("native event stream failed")

    @staticmethod
    def _accept_event(owner, event):
        method = event["method"]
        if "id" in event or any(
            name in method.lower() for name in ("auth", "approval", "input", "login")
        ):
            owner["native_error"] = RunnerUnavailable("native interaction")
        if owner["events"].full():
            owner["native_error"] = RunnerOutcomeUnknown("native event inbox overflow")
            return False
        owner["events"].put_nowait(event)
        return True

    async def _drain_closed_events(self, owner):
        # The transport is now physically closed: next_event can only return
        # its retained bounded inbox or its terminal error, never wait for IO.
        for _ in range(1001):
            try:
                event = await owner["transport"].next_event()
            except CodexRPCError as error:
                if type(error) is not CodexRPCClosed:
                    owner["native_error"] = RunnerOutcomeUnknown("native event stream failed")
                return
            self._accept_event(owner, event)
        owner["native_error"] = RunnerOutcomeUnknown("native observation limit")

    @staticmethod
    def _candidate(history, thread_id, turn_id):
        thread = history["thread"]
        turns = [turn for turn in thread["turns"] if turn["id"] == turn_id]
        if thread["id"] != thread_id or thread["cwd"] != "/workspace" or len(turns) != 1:
            raise RunnerOutcomeUnknown("final native locator differs")
        turn = turns[0]
        if turn["status"] != "completed":
            raise RunnerOutcomeUnknown("final native terminal differs")
        texts = [
            item["text"]
            for item in turn["items"]
            if item["type"] == "agentMessage" and item.get("phase") in (None, "final_answer")
        ]
        text = "\n".join(texts)
        if len(text.encode()) > 32768:
            raise RunnerUnavailable("result text bound")
        return {
            "text": text,
            "artifacts": [],
            "native": {"thread_id": thread_id, "turn_id": turn_id, "status": "completed"},
            "usage": {"status": "unknown"},
        }

    @staticmethod
    def _artifacts(environment):
        root = Path(environment.identity["root"]["path"]) / "workspace"
        pending, artifacts, nodes, total = [root], [], 0, 0
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    nodes += 1
                    if nodes > 4096:
                        raise RunnerUnavailable("workspace entry bound")
                    if entry.name.startswith("."):
                        continue
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        raise RunnerUnavailable("workspace alias")
                    path = Path(entry.path)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path)
                        continue
                    relative = path.relative_to(root).as_posix()
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_nlink != 1
                        or len(relative.encode()) > 256
                        or len(artifacts) >= 64
                        or info.st_size > 4 * 1024 * 1024
                        or total + info.st_size > 16 * 1024 * 1024
                    ):
                        raise RunnerUnavailable("workspace artifact bound")
                    hasher = hashlib.sha256()
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                    with os.fdopen(fd, "rb") as source:
                        current = os.fstat(source.fileno())
                        if (current.st_dev, current.st_ino, current.st_size) != (
                            info.st_dev,
                            info.st_ino,
                            info.st_size,
                        ):
                            raise RunnerUnavailable("workspace artifact changed")
                        while chunk := source.read(65536):
                            hasher.update(chunk)
                    total += info.st_size
                    artifacts.append(
                        {"path": relative, "sha256": hasher.hexdigest(), "size": info.st_size}
                    )
        return sorted(artifacts, key=lambda item: item["path"])

    async def _cleanup(self, owner):
        while True:
            if owner["cleanup"] is None or owner["cleanup"].cancelled():
                owner["cleanup"] = asyncio.create_task(self._retire(owner))
            try:
                return await asyncio.shield(owner["cleanup"])
            except asyncio.CancelledError:
                pass

    async def _retire(self, owner):
        env = owner["environment"]
        stop = None
        failure = None
        owner["ending"] = True
        try:
            if (
                owner["cold"]
                and owner.get("known_resource")
                and not any(value is not None for value in owner["original_state"].values())
            ):
                # A journal conflict proves prior native intent, not permission
                # to adopt whichever locator private metadata currently names.
                raise ExecutionHostFailed("Original Coding authority locator is missing")
            if owner["cold"] and env is None:
                env = self._environment(owner["envelope"], create=False)
                owner["environment"] = env
            if env is not None:
                original = owner["original_state"]
                prepared = original.get("prepared")
                binding = original.get("binding")
                grant = original.get("prepare_grant")
                locator = None
                if owner["cold"]:
                    saved = prepared or ((binding or {}).get("environment"))
                    identity = (saved or {}).get("identity") or (
                        (grant or {}).get("binding", {}).get("environment")
                    )
                    if identity is not None and identity != env.identity:
                        raise DefinitionMismatch("Original Coding namespace identity changed")
                    locator = (saved or {}).get("container_id")
                stop = await (
                    env.stop()
                    if owner["prepared"]
                    else env.stop_existing(
                        expected_container_id=locator,
                    )
                )
                if stop is not None and not (
                    stop["fenced"] and stop["retired"] and not stop["container_present"]
                ):
                    raise ExecutionHostFailed(
                        "Original Coding resource retirement is not confirmed"
                    )
            known = owner.get("known_resource", False) or any(
                value is not None for value in owner["original_state"].values()
            )
            if stop is None and known:
                raise ExecutionHostFailed("Original Coding namespace evidence is missing")
        except asyncio.CancelledError:
            raise
        except Exception:
            failure = CloseIncomplete({"coding_resource": "retirement_unconfirmed"})
        finally:
            if owner["transport"] is not None:
                try:
                    await owner["transport"].aclose(wait_timeout=self._timeout)
                    await self._drain_closed_events(owner)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    failure = CloseIncomplete({"coding_transport": "cleanup_unconfirmed"})
            if owner.get("pump") is not None:
                # The pump stays live throughout actual namespace retirement
                # and the transport's pipe close/drain, including late waits.
                await asyncio.sleep(0)
                owner["pump"].cancel()
                await self._settle(owner["pump"])
        if failure is not None:
            raise failure
        if env is not None:
            await env.aclose()
        if stop is not None:
            stop = {**stop, "transport_closed": None if owner["cold"] else True}
            if owner["cold"]:
                owner["binding"] = self._binding(owner["envelope"], owner["intent"], stop)
                context = owner["envelope"].context
                owner["journaled"] = (
                    self._journal.lookup(
                        context.scope,
                        context.effect_key,
                        binding=owner["binding"],
                    )
                    is not None
                )
        owner["stop_evidence"] = stop
        # This local sentinel releases a no-process owner. It is never adopted
        # as namespace stop evidence or exposed by cold stop_existing.
        owner["stop"] = stop or {"container_id": None, "generation": None, "fenced": True}
        if stop is not None:
            self._observe(owner, "stop", stop)

    @staticmethod
    async def _settle(task):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
            except Exception:
                break
        if not task.cancelled():
            task.exception()

    async def aclose(self, *, wait_timeout=30):
        if (
            type(wait_timeout) not in (int, float)
            or not math.isfinite(wait_timeout)
            or not 0 < wait_timeout <= 60
        ):
            raise ValidationError(
                "Coding close requires a positive finite deadline up to 60 seconds"
            )
        self._closing = True
        owner = self._active
        if owner is None:
            return
        if owner["supervision"] is None or owner["supervision"].done():
            owner["supervision"] = asyncio.create_task(self._close_owner(owner))
        try:
            await asyncio.wait_for(asyncio.shield(owner["supervision"]), timeout=wait_timeout)
        except TimeoutError:
            raise CloseIncomplete({"coding_resource": "cleanup_still_owned"}) from None
        except asyncio.CancelledError:
            await self._settle(owner["supervision"])
            await self._cleanup(owner)
            raise

    async def _close_owner(self, owner):
        if owner["task"] is not None and not owner["task"].done():
            owner["task"].cancel()
            await self._settle(owner["task"])
        if owner["stop"] is not None:
            self._active = None
            return
        if owner["cleanup"] is not None and owner["cleanup"].done():
            owner["cleanup"] = None
        await self._cleanup(owner)
        self._active = None

    async def stop_existing(self, envelope: DispatchEnvelope, authority):
        intent = self._authority(envelope, authority)
        if self._active is not None:
            owner = self._active
            if canonical(_dispatch(envelope)) != canonical(_dispatch(owner["envelope"])):
                raise CoordinatorBusy(
                    "A different original Coding execution still owns its resource"
                )
            await self._close_owner(owner)
            return owner.get("stop_evidence")
        original = _snapshot(
            authority.resource_state(envelope, self.identity), "original resource state"
        )
        known = any(value is not None for value in original.values())
        if not known:
            try:
                prior = self._journal.lookup(
                    envelope.context.scope,
                    envelope.context.effect_key,
                    binding={"no_preparation": digest(intent)},
                )
            except IdempotencyConflict:
                known = True
            else:
                known = prior is not None
        env = self._environment(envelope, create=False)
        if env is None and not known:
            return None
        owner = {
            "envelope": envelope,
            "authority": authority,
            "intent": intent,
            "environment": env,
            "transport": None,
            "binding": None,
            "journaled": False,
            "prepared": False,
            "stop": None,
            "cleanup": None,
            "task": None,
            "cold": True,
            "supervision": None,
            "original_state": original if known else {},
            "known_resource": known,
        }
        self._active = owner
        try:
            await self._cleanup(owner)
            return owner.get("stop_evidence")
        finally:
            if owner["stop"] is not None:
                self._active = None

    async def reconcile(self, envelope: DispatchEnvelope, authority):
        stop = await self.stop_existing(envelope, authority)
        if stop is None:
            return None
        intent = self._authority(envelope, authority)
        record = self._journal.lookup(
            envelope.context.scope,
            envelope.context.effect_key,
            binding=self._binding(envelope, intent, stop),
        )
        if record is None:
            return None
        candidates = [
            item["result"] for item in record["observations"] if item["kind"] == "result_candidate"
        ]
        if candidates:
            authority.adopt(
                "result_candidate", {"kind": "result_candidate", "result": candidates[-1]}
            )
            return EffectObservation(candidates[-1], source="codex-coding-runner-journal")
        raise RunnerOutcomeUnknown("cold original native evidence remains uncertain")
