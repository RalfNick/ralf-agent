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
from .codex_runner_capacity import RootCapacity
from .coding_resource_fingerprint import policy_value
from .component_fingerprint import executable_digest as _history_executable_digest
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
from .postgres_runner_journal import PostgresRunnerJournal
from .runner_journal import RunnerJournal
from .temporal_coding_authority import TemporalCodingAuthority
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


def _capacity_implementation():
    from . import codex_runner_capacity as capacity
    from .component_fingerprint import executable_digest

    if RootCapacity is not capacity.RootCapacity:
        raise DefinitionMismatch("Original physical capacity class changed")
    methods = (
        "__init__",
        "_check_root",
        "_check_lock",
        "_validate_state",
        "_read",
        "_write",
        "_drop_lock",
        "try_acquire",
        "claim",
        "_owned",
        "mark_native_intent",
        "release",
        "close",
    )
    return {
        "methods": {
            name: executable_digest(
                RootCapacity.claim.fget if name == "claim" else getattr(RootCapacity, name)
            )
            for name in methods
        },
        "helpers": {
            name: executable_digest(getattr(capacity, name))
            for name in ("_require", "_hex", "_pin", "_private_file", "_pairs")
        },
        "constants": {
            name: digest(policy_value(getattr(capacity, name)))
            for name in ("_LOCK", "_RECORD", "_LIMIT")
        },
    }


def _environment_implementation():
    from . import codex_environment as environment
    from . import coding_create_inventory, coding_process_wait
    from .component_fingerprint import executable_digest

    if DockerCodingEnvironment is not environment.DockerCodingEnvironment:
        raise DefinitionMismatch("Original Coding environment class changed")
    if (
        environment.ChildExitMonitor is not coding_process_wait.ChildExitMonitor
        or environment.signal_unreaped_group is not coding_process_wait.signal_unreaped_group
    ):
        raise DefinitionMismatch("Original direct child supervision implementation changed")
    supervised = coding_create_inventory.inventory()
    coding_create_inventory.validate_inventory(supervised)
    if supervised["inventory"] != {
        name: executable_digest(getattr(coding_create_inventory, name))
        for name in coding_create_inventory.inventory_fields()["inventory"]
    }:
        raise DefinitionMismatch("Original CREATE supervision inventory generator changed")
    methods = (
        "__init__",
        "prepare",
        "inspect",
        "stop",
        "stop_existing",
        "observe_namespace_absence",
        "observe_create_not_dispatched",
        "_observe_create_not_dispatched",
        "_submit_supervised_create",
        "_control_supervised_create",
        "_observe_namespace_absence",
        "_namespace_query",
        "aclose",
        "_owned",
        "_serialized_operation",
        "_check_root",
        "_acquire",
        "_read_metadata",
        "_write_metadata",
        "_provision",
        "_check_files",
        "_labels",
        "_create_argv",
        "_prepare",
        "_prepare_legacy_locator",
        "_create_operation_digest",
        "_validate_create_operation",
        "_create_candidates",
        "_submit_create",
        "_recover_create",
        "_inspect_raw",
        "_validate_container",
        "_inspect",
        "_stop",
        "_stop_existing",
        "_validate_retirement",
        "_container_present",
        "_record_fenced",
        "_close",
        "_cli",
        "identity",
        "transport_env",
        "active_operations",
        "transport_argv",
    )
    return {
        "create_supervision": supervised,
        "methods": {
            name: executable_digest(
                getattr(DockerCodingEnvironment, name).fget
                if isinstance(getattr(DockerCodingEnvironment, name), property)
                else getattr(DockerCodingEnvironment, name)
            )
            for name in methods
        },
        "helpers": {
            name: executable_digest(getattr(environment, name))
            for name in ("_canonical", "_digest", "_require", "_pin")
        },
        "constants": {
            name: digest(policy_value(getattr(environment, name)))
            for name in (
                "_SECCOMP_DIGEST",
                "_COMMAND",
                "_ENTRYPOINT",
                "_IMAGE_ENV",
                "_REGISTRY",
                "_REGISTRY_OPTIONS",
                "_CAP",
                "_ZERO_TIME",
            )
        },
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
                and type(journal) in (RunnerJournal, PostgresRunnerJournal)
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
            "physical_capacity_version": "1",
            "create_operation_version": 2,
            "create_supervision_version": 1,
        }
        from .component_fingerprint import executable_digest

        self._capacity_inventory = _capacity_implementation()
        self._capacity_inventory_pin = executable_digest(_capacity_implementation)
        self._environment_inventory = _environment_implementation()
        self._environment_inventory_pin = executable_digest(_environment_implementation)
        self._resource_policy_pin = executable_digest(policy_value)
        self._identity["resource_policy"] = self._resource_policy_pin
        self._identity["physical_capacity"] = {
            "version": 1,
            "implementation_digest": digest(self._capacity_inventory),
            "inventory_entry": self._capacity_inventory_pin,
        }
        self._identity["environment_implementation"] = {
            "implementation_digest": digest(self._environment_inventory),
            "inventory_entry": self._environment_inventory_pin,
        }
        self._capacity_runtime_methods = {
            name: (getattr(self, name).__func__, executable_digest(getattr(self, name)))
            for name in (
                "_acquire_capacity",
                "_release_capacity",
                "_release_unprepared_capacity",
                "_wait_owner",
                "_check_capacity",
            )
        }
        if type(journal) is PostgresRunnerJournal:
            self._identity["configuration_readonly"] = True
        self._active = None
        self._closing = False

    @property
    def identity(self):
        return copy.deepcopy(self._identity)

    @property
    def active_operations(self):
        return int(self._active is not None)

    def _check_root(self):
        from .component_fingerprint import executable_digest

        try:
            if (
                _pin(self._root) != self._root_pin
                or stat.S_IMODE(self._root.stat().st_mode) != 0o700
                or self._root.stat().st_uid != os.getuid()
                or _pin(Path(self._docker).resolve(strict=True))
                != self._identity["docker_executable"]
                or self._journal.identity != self._identity["journal"]
                or executable_digest(_capacity_implementation) != self._capacity_inventory_pin
                or _capacity_implementation() != self._capacity_inventory
                or executable_digest(_environment_implementation) != self._environment_inventory_pin
                or _environment_implementation() != self._environment_inventory
                or executable_digest(policy_value) != self._resource_policy_pin
                or self._identity["resource_policy"] != self._resource_policy_pin
                or self._identity["environment_implementation"]
                != {
                    "implementation_digest": digest(self._environment_inventory),
                    "inventory_entry": self._environment_inventory_pin,
                }
                or self._identity["physical_capacity"]
                != {
                    "version": 1,
                    "implementation_digest": digest(self._capacity_inventory),
                    "inventory_entry": self._capacity_inventory_pin,
                }
                or any(
                    getattr(getattr(self, name), "__func__", None) is not method
                    or executable_digest(getattr(self, name)) != fingerprint
                    for name, (method, fingerprint) in self._capacity_runtime_methods.items()
                )
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
        if type(authority) is not LocalCodingAuthority or type(self._journal) is not RunnerJournal:
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
            configuration_readonly=type(self._journal) is PostgresRunnerJournal,
            create_recovery=True,
            create_supervision=True,
            supervision_sources=self._environment_inventory["create_supervision"]["module_sources"],
        )

    async def _acquire_capacity(self, owner, *, recovery=False, absent_original_ok=False):
        self._check_root()
        if owner.get("capacity") is not None:
            self._check_capacity(owner)
            return owner["capacity"].claim is not None
        _, _, generation = self._location(owner["envelope"])
        gate = RootCapacity(
            Path(self._root_pin["path"]),
            root_pin=self._root_pin,
            dispatch_digest=digest(_dispatch(owner["envelope"])),
            runner_digest=digest(self.identity),
            generation=generation,
        )
        owner["capacity"] = gate
        while True:
            self._check_capacity(owner)
            if not recovery:
                await self._cancelled_owned(owner)
                if self._closing:
                    raise RunnerUnavailable("resource closing")
            claim = gate.try_acquire(recovery=recovery, absent_original_ok=absent_original_ok)
            if claim is not None:
                return True
            if recovery:
                return False
            await asyncio.sleep(0.05)

    def _check_capacity(self, owner):
        self._check_root()
        gate = owner.get("capacity")
        if type(gate) is not RootCapacity or any(
            getattr(getattr(gate, name), "__func__", None) is not getattr(RootCapacity, name)
            for name in (
                "try_acquire",
                "mark_native_intent",
                "release",
                "close",
                "_check_root",
                "_check_lock",
                "_validate_state",
                "_read",
                "_write",
                "_drop_lock",
                "_owned",
            )
        ):
            raise DefinitionMismatch("Original physical capacity instance changed")

    async def _wait_owner(self, owner):
        async with asyncio.timeout(self._timeout):
            while self._active is not None:
                if canonical(_dispatch(owner["envelope"])) == canonical(
                    _dispatch(self._active["envelope"])
                ):
                    raise CoordinatorBusy("Original Coding execution is already owned")
                if self._closing:
                    raise RunnerUnavailable("resource closing")
                await self._authority_owned(owner)
                await self._cancelled_owned(owner)
                await asyncio.sleep(0.05)

    async def _release_capacity(self, owner):
        gate = owner.get("capacity")
        if gate is None:
            return
        self._check_capacity(owner)
        claim = gate.claim
        if claim is None:
            gate.close()
            owner["capacity"] = None
            return
        original = {key: claim[key] for key in ("dispatch_digest", "runner_digest", "generation")}
        stop = owner.get("stop_evidence")
        absent = owner.get("namespace_absence")
        no_create = owner.get("create_not_dispatched")
        if no_create is not None:
            from .coding_execution_rules import create_not_dispatched_projection

            proof = create_not_dispatched_projection(
                no_create,
                owner["environment"].identity,
                token=claim["token"],
                dispatch_digest=original["dispatch_digest"],
                runner_digest=original["runner_digest"],
            )
            gate.release(claim["token"], create_not_dispatched_proof=proof)
        elif stop is not None:
            if stop.get("generation") != original["generation"]:
                raise DefinitionMismatch("Capacity stop differs from the original generation")
            gate.release(
                claim["token"],
                fenced_receipt={
                    **original,
                    **{
                        key: stop[key]
                        for key in (
                            "container_id",
                            "stopped",
                            "fenced",
                            "retired",
                            "container_present",
                            "pid",
                        )
                    },
                },
            )
        elif absent is not None:
            gate.release(
                claim["token"],
                namespace_absent_proof={
                    **original,
                    "namespace_absent": True,
                    "metadata_present": False,
                    "container_present": False,
                    "process_present": False,
                },
            )
        else:
            gate.release(claim["token"], definitely_undispatched=True)
        gate.close()
        owner["capacity"] = None

    async def _release_unprepared_capacity(self, owner):
        try:
            await self._acquire_capacity(owner, recovery=True, absent_original_ok=True)
            await self._release_capacity(owner)
        finally:
            # A failed control cannot discard the durable original obligation.
            # This branch has no executing owner or native cleanup task to hold
            # an OS descriptor; another original control may retry its evidence.
            gate = owner.get("capacity")
            if gate is not None:
                gate.close()
                owner["capacity"] = None

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
            await self._wait_owner({"envelope": envelope, "authority": authority})
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
        if self._closing:
            raise RunnerUnavailable("resource closing")
        if self._active is not None:
            await self._wait_owner(owner)
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
            if self._active is owner and owner["stop"] is not None and owner["task"].done():
                self._active = None

    async def _history_authority(self, envelope, authority):
        try:
            from .temporal_coding_authority import TemporalCodingAuthority
        except ImportError:
            raise AuthorizationDenied("Original Temporal Coding authority is unavailable") from None
        if (
            type(authority) is not TemporalCodingAuthority
            or type(self._journal) is not PostgresRunnerJournal
        ):
            raise AuthorizationDenied(
                "History Coding requires original async authority and PostgreSQL journal"
            )
        owner = {"envelope": envelope, "authority": authority, "history": True}
        return await self._authority_owned(owner)

    async def _authority_method(self, owner, method, *args):
        if not owner.get("history"):
            value = getattr(owner["authority"], method)(*args)
            if method == "adopt" and value is not None:
                raise AuthorizationDenied("Original Local receipt requires completed None")
            return value
        from .temporal_coding_authority import TemporalCodingAuthority

        authority = owner["authority"]
        if type(authority) is not TemporalCodingAuthority or method not in {
            "check",
            "resource_state",
            "cancelled",
            "authorize",
            "adopt",
            "validate_registration",
        }:
            raise AuthorizationDenied("Original History Coding authority changed")
        bound = getattr(authority, method)
        fixed = _HISTORY_METHODS[method]
        if getattr(bound, "__func__", None) is not fixed:
            raise DefinitionMismatch("Original History authority method changed")
        self._check_root()
        value = await bound(*args)
        self._check_root()
        if (
            getattr(getattr(authority, method), "__func__", None) is not fixed
            or getattr(TemporalCodingAuthority, method) is not fixed
        ):
            raise DefinitionMismatch("Original History authority method changed during await")
        if method in {"adopt", "validate_registration"}:
            if value is not None:
                raise AuthorizationDenied("Original History receipt requires completed None")
        elif method == "cancelled":
            if type(value) is not bool:
                raise AuthorizationDenied(
                    "Original History cancellation requires completed boolean"
                )
        else:
            value = _snapshot(value, "original History Coding " + method)
            if type(value) is not dict:
                raise AuthorizationDenied("Original History authority requires completed object")
        return value

    async def _authority_owned(self, owner):
        if not owner.get("history"):
            return self._authority(owner["envelope"], owner["authority"])
        return await self._authority_method(owner, "check", owner["envelope"], self.identity)

    async def _journal_method(self, owner, method, *args, **kwargs):
        if not owner.get("history"):
            return getattr(self._journal, method)(*args, **kwargs)
        if type(self._journal) is not PostgresRunnerJournal or method not in _PG_METHODS:
            raise DefinitionMismatch("Original asynchronous Coding journal changed")
        bound = getattr(self._journal, method)
        fixed = _PG_METHODS[method]
        if getattr(bound, "__func__", None) is not fixed:
            raise DefinitionMismatch("Original asynchronous journal method changed")
        self._check_root()
        await self._authority_method(owner, "validate_registration")
        value = await bound(*args, **kwargs)
        await self._authority_method(owner, "validate_registration")
        self._check_root()
        if getattr(getattr(self._journal, method), "__func__", None) is not fixed:
            raise DefinitionMismatch("Original journal method changed during await")
        return value

    async def _grant_owned(self, owner, method, params, binding):
        if not owner.get("history"):
            return self._grant(owner["authority"], method, params, binding)
        grant = await self._authority_method(owner, "authorize", method, params, binding)
        if (
            grant.get("method") != method
            or canonical(grant.get("params")) != canonical(params)
            or canonical(grant.get("binding")) != canonical(binding)
            or type(grant.get("execute")) is not bool
        ):
            raise AuthorizationDenied(
                "Native startup grant differs from the original History request"
            )
        if not grant["execute"]:
            raise RunnerOutcomeUnknown("startup already granted")

    async def _cancelled_owned(self, owner):
        if not owner.get("history"):
            return self._cancelled(owner)
        if owner.get("native_error") is not None:
            raise owner["native_error"]
        if await self._authority_method(owner, "cancelled"):
            raise RunnerOutcomeUnknown("original execution cancelled")

    async def _observe_owned(self, owner, kind, evidence):
        if not owner.get("history"):
            if kind in {"prepared", "create_not_dispatched"}:
                return owner["authority"].adopt(kind, evidence)
            return self._observe(owner, kind, evidence)
        context = owner["envelope"].context
        value = (
            evidence
            if kind in {"prepared", "namespace_absent", "create_not_dispatched"}
            else {"kind": kind, **evidence}
        )
        if kind in {"prepared", "stop", "namespace_absent", "create_not_dispatched"}:
            saved = await self._journal_method(
                owner,
                "record_resource",
                context.scope,
                context.effect_key,
                owner["intent"],
                kind=kind,
                evidence=value,
            )
            value = saved[kind]
        elif owner["journaled"]:
            await self._journal_method(
                owner,
                "record_observation",
                context.scope,
                context.effect_key,
                binding=owner["binding"],
                observation=value,
            )
        await self._authority_method(owner, "adopt", kind, value)

    async def execute_history(self, envelope: DispatchEnvelope, authority) -> EffectObservation:
        intent = await self._history_authority(envelope, authority)
        self._check_root()
        self._journal._ready()
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
            await self._wait_owner({"envelope": envelope, "authority": authority, "history": True})
        original = await self._authority_method(
            {"history": True, "authority": authority}, "resource_state", envelope, self.identity
        )
        # Retry/replacement invocation may only reconcile original evidence.
        context = envelope.context
        prior = await self._journal_method(
            {"history": True, "authority": authority},
            "resource_state",
            context.scope,
            context.effect_key,
            intent,
        )
        if prior is not None or any(value is not None for value in original.values()):
            recovered = await self.reconcile_history(envelope, authority)
            if recovered is None:
                raise RunnerOutcomeUnknown("original native preparation evidence remains uncertain")
            return recovered
        owner = {
            "history": True,
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
            "original_state": original,
        }
        if self._closing:
            raise RunnerUnavailable("resource closing")
        if self._active is not None:
            await self._wait_owner(owner)
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
            if self._active is owner and owner["stop"] is not None and owner["task"].done():
                self._active = None

    async def stop_history(self, envelope: DispatchEnvelope, authority):
        intent = await self._history_authority(envelope, authority)
        if self._active is not None:
            owner = self._active
            if not owner.get("history") or canonical(_dispatch(envelope)) != canonical(
                _dispatch(owner["envelope"])
            ):
                raise CoordinatorBusy(
                    "A different original Coding execution still owns its resource"
                )
            # A retained cleanup must adopt through the current pinned receiver.
            owner["authority"] = authority
            await self._close_owner(owner)
            return owner.get("stop_evidence")
        owner = {"history": True, "envelope": envelope, "authority": authority, "intent": intent}
        original = await self._authority_method(owner, "resource_state", envelope, self.identity)
        context = envelope.context
        resource = await self._journal_method(
            owner, "resource_state", context.scope, context.effect_key, intent
        )
        if resource is not None:
            if resource["runner"] != self.identity:
                raise DefinitionMismatch("Original pending resource runner changed")
            if resource["owner"] is not None:
                await self._authority_method(owner, "adopt", "owner", resource["owner"])
            if original.get("prepare_grant") is None:
                if resource["prepared"] is not None or resource["stop"] is not None:
                    raise DefinitionMismatch(
                        "PG native resource receipt lacks its original History preparation grant"
                    )
                evidence = {
                    "namespace_binding": resource["namespace_binding"],
                    "prepare_granted": False,
                }
                await self._journal_method(
                    owner,
                    "record_resource",
                    context.scope,
                    context.effect_key,
                    intent,
                    kind="unprepared",
                    evidence=evidence,
                )
                await self._authority_method(owner, "adopt", "unprepared", evidence)
                await self._release_unprepared_capacity(owner)
                return None
            prepared = resource["prepared"]
            original["prepared"] = prepared or original.get("prepared")
            if prepared is not None:
                original["binding"] = self._binding(envelope, intent, prepared)
            original["prepare_grant"] = original.get("prepare_grant") or {
                "binding": resource["namespace_binding"]
            }
        known = resource is not None or any(value is not None for value in original.values())
        env = self._environment(envelope, create=False)
        if env is None and not known:
            await self._release_unprepared_capacity(owner)
            return None
        owner.update(
            {
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
                "resource_intent": resource,
            }
        )
        if self._active is not None:
            active = self._active
            if not active.get("history") or canonical(_dispatch(envelope)) != canonical(
                _dispatch(active["envelope"])
            ):
                raise CoordinatorBusy(
                    "A different original Coding execution still owns its resource"
                )
            active["authority"] = authority
            await self._close_owner(active)
            return active.get("stop_evidence")
        self._active = owner
        try:
            await self._cleanup(owner)
            return owner.get("stop_evidence")
        finally:
            if self._active is owner and owner["stop"] is not None:
                self._active = None

    async def reconcile_history(self, envelope: DispatchEnvelope, authority):
        stop = await self.stop_history(envelope, authority)
        if stop is None:
            return None
        intent = await self._history_authority(envelope, authority)
        owner = {"history": True, "envelope": envelope, "authority": authority, "intent": intent}
        binding = self._binding(envelope, intent, stop)
        record = await self._journal_method(
            owner, "lookup", envelope.context.scope, envelope.context.effect_key, binding=binding
        )
        if record is None:
            raise RunnerOutcomeUnknown("original prepare-window native evidence remains uncertain")
        # Original native startup receipts precede every History adoption.
        if record["thread_id"] is not None:
            await self._authority_method(
                owner, "adopt", "thread", {"thread_id": record["thread_id"]}
            )
        if record["turn_id"] is not None:
            await self._authority_method(
                owner,
                "adopt",
                "turn",
                {"thread_id": record["thread_id"], "turn_id": record["turn_id"]},
            )
        candidate = None
        for receipt in record["observations"]:
            kind = receipt.get("kind")
            if kind in {"observation", "result_candidate", "error"}:
                await self._authority_method(owner, "adopt", kind, receipt)
                if kind == "result_candidate":
                    candidate = receipt["result"]
        if candidate is not None:
            return EffectObservation(candidate, source="codex-coding-runner-journal")
        raise RunnerOutcomeUnknown("cold original native evidence remains uncertain")

    async def _request(self, owner, method, params, *, control=False):
        adjacent = control is True or (
            control is False
            and type(method) is str
            and method in {"thread/start", "turn/start", "thread/read"}
        )
        authority = owner.get("authority") if adjacent and owner.get("history") else None
        request = authority._request if type(authority) is TemporalCodingAuthority else None
        manifest = request.get("runtime_manifest") if type(request) is dict else None
        deployment = (
            manifest.get("deployment_admission_protocol") if type(manifest) is dict else None
        )
        selected_adjacent = (
            adjacent
            and owner.get("history")
            and type(authority) is TemporalCodingAuthority
            and type(deployment) is dict
            and type(deployment.get("version")) is int
            and (
                deployment["version"] == 3
                or deployment["version"] == 4
                and "coding_execution_protocol" in manifest
            )
        )
        if selected_adjacent:
            from .component_fingerprint import executable_digest

            proof, native = authority._proof, request.get("coding_request")
            if (
                type(proof) is not dict
                or set(proof)
                != {
                    "scope",
                    "run_id",
                    "action_id",
                    "release_digest",
                    "execution_epoch",
                    "request_digest",
                    "invocation_id",
                }
                or any(
                    proof[name] != request.get(name)
                    for name in (
                        "scope",
                        "run_id",
                        "action_id",
                        "release_digest",
                        "execution_epoch",
                    )
                )
                or proof["request_digest"] != digest(request)
                or type(native) is not dict
                or native.get("release_digest") != request["release_digest"]
                or native.get("request_digest")
                != digest({k: v for k, v in native.items() if k != "request_digest"})
            ):
                raise DefinitionMismatch("Original deployment native request changed")
            identity = digest(request), copy.deepcopy(proof)
            protocol = owner["control"] if control else self._protocol
            accepted = protocol.validate_request(method, params)
            for name, (fixed, fingerprint) in _HISTORY_CONTROL_PINS.items():
                if (
                    getattr(getattr(authority, name), "__func__", None) is not fixed
                    or getattr(TemporalCodingAuthority, name) is not fixed
                    or executable_digest(fixed) != fingerprint
                ):
                    raise DefinitionMismatch("Original deployment native validation changed")
            # The original state Query already has fresh validation on both sides.
            # No I/O separates its final validation from this native send.
            # Business phase grants and PG execute checks remain independent.
            await self._cancelled_owned(owner)
            if (
                owner.get("authority") is not authority
                or digest(authority._request) != identity[0]
                or authority._proof != identity[1]
            ):
                raise DefinitionMismatch("Original deployment native authority changed")
            for name, (fixed, fingerprint) in _HISTORY_CONTROL_PINS.items():
                if (
                    getattr(getattr(authority, name), "__func__", None) is not fixed
                    or getattr(TemporalCodingAuthority, name) is not fixed
                    or executable_digest(fixed) != fingerprint
                ):
                    raise DefinitionMismatch("Original deployment native validation changed")
            authority._check_pins()
        else:
            await self._cancelled_owned(owner)
            protocol = owner["control"] if control else self._protocol
            accepted = protocol.validate_request(method, params)
            if owner.get("history"):
                await self._authority_method(owner, "validate_registration")
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
        authority = owner.get("authority") if owner.get("history") else None
        request = authority._request if type(authority) is TemporalCodingAuthority else None
        manifest = request.get("runtime_manifest") if type(request) is dict else None
        deployment = (
            manifest.get("deployment_admission_protocol") if type(manifest) is dict else None
        )
        batch = (
            type(deployment) is dict
            and type(deployment.get("version")) is int
            and deployment["version"] == 4
            and "coding_execution_protocol" in manifest
        )
        for method, params in queries[:1] if batch else queries:
            results[method] = await self._request(owner, method, params, control=True)
            if method == "initialize":
                await owner["transport"].notify("initialized")
        if batch:
            readers = asyncio.gather(
                *(
                    self._request(owner, method, params, control=True)
                    for method, params in queries[1:]
                ),
                return_exceptions=True,
            )
            try:
                completed = await asyncio.shield(readers)
            except asyncio.CancelledError:
                readers.cancel()
                while not readers.done():
                    try:
                        await asyncio.shield(readers)
                    except asyncio.CancelledError:
                        pass
                if not readers.cancelled():
                    readers.exception()
                raise
            for value in completed:
                if isinstance(value, BaseException):
                    raise value
            results.update(
                (method, value) for (method, _), value in zip(queries[1:], completed, strict=True)
            )
        self._profile.validate_control(results)

    def _make_transport(self, owner, environment):
        """Construct one transport after the original preparation/journal grant.

        A concrete, versioned Runner can specialize startup authentication while
        retaining this execution loop and its original authority and cleanup.
        This hook never resolves credentials or submits native business work.
        """
        return CodexRPCTransport(
            environment.transport_argv(),
            env=environment.transport_env,
            request_timeout=self._timeout,
            coding_mode=True,
        )

    async def _execute(self, owner):
        candidate = None
        error = None
        try:
            async with asyncio.timeout(self._timeout):
                await self._cancelled_owned(owner)
                await self._acquire_capacity(owner)
                env = self._environment(owner["envelope"], create=True)
                owner["environment"] = env
                prepare_binding = {
                    "request": owner["intent"],
                    "runner": self.identity,
                    "dispatch": _dispatch(owner["envelope"]),
                    "environment": env.identity,
                }
                if owner.get("history"):
                    context = owner["envelope"].context
                    proof = owner["authority"].owner_proof
                    if proof is None:
                        raise AuthorizationDenied(
                            "History native preparation requires original process owner proof"
                        )
                    begun = await self._journal_method(
                        owner,
                        "begin_resource",
                        owner["envelope"],
                        owner["intent"],
                        self.identity,
                        prepare_binding,
                        owner_proof=proof,
                    )
                    if not begun["execute"]:
                        raise RunnerOutcomeUnknown(
                            "original resource preparation intent already exists"
                        )
                    owner["resource_intent"] = begun["resource"]
                    await self._authority_method(owner, "adopt", "owner", proof)
                await self._grant_owned(owner, "prepare", {}, prepare_binding)
                owner["original_state"] = await self._authority_method(
                    owner, "resource_state", owner["envelope"], self.identity
                )
                capacity = owner["capacity"]
                self._check_capacity(owner)
                capacity.mark_native_intent(capacity.claim["token"])
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
                await self._observe_owned(owner, "prepared", inspected)
                await self._authority_owned(owner)
                owner["binding"] = self._binding(owner["envelope"], owner["intent"], inspected)
                context = owner["envelope"].context
                record = await self._journal_method(
                    owner,
                    "begin",
                    context.scope,
                    context.effect_key,
                    owner["binding"],
                    **({"envelope": owner["envelope"]} if owner.get("history") else {}),
                )
                owner["journaled"] = True
                if not record["execute"]:
                    raise RunnerOutcomeUnknown("original journal startup already exists")
                transport = self._make_transport(owner, env)
                owner["transport"] = transport
                await transport.start()
                await self._preflight(owner)
                owner["pump"] = asyncio.create_task(self._pump(owner))
                await self._cancelled_owned(owner)
                params = self._protocol.validate_request(
                    "thread/start",
                    {
                        "cwd": "/workspace",
                        "approvalPolicy": "never",
                        "approvalsReviewer": "user",
                        "ephemeral": False,
                    },
                )
                await self._grant_owned(owner, "thread/start", params, owner["binding"])
                submitted = await self._journal_method(
                    owner,
                    "mark_thread_submitted",
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
                await self._journal_method(
                    owner,
                    "record_thread",
                    context.scope,
                    context.effect_key,
                    binding=owner["binding"],
                    thread_id=thread_id,
                    process_epoch=inspected["generation"],
                )
                await self._authority_method(owner, "adopt", "thread", {"thread_id": thread_id})
                await self._cancelled_owned(owner)
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
                await self._grant_owned(owner, "turn/start", params, owner["binding"])
                submitted = await self._journal_method(
                    owner,
                    "mark_turn_submitted",
                    context.scope,
                    context.effect_key,
                    binding=owner["binding"],
                )
                if not submitted["execute"]:
                    raise RunnerOutcomeUnknown("original Turn submission already exists")
                started = await self._request(owner, "turn/start", params)
                turn_id = started["turn"]["id"]
                await self._journal_method(
                    owner,
                    "record_turn",
                    context.scope,
                    context.effect_key,
                    binding=owner["binding"],
                    turn_id=turn_id,
                )
                await self._authority_method(
                    owner, "adopt", "turn", {"thread_id": thread_id, "turn_id": turn_id}
                )
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
                await self._observe_owned(
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
                await self._journal_method(
                    owner,
                    "request_cancel",
                    context.scope,
                    context.effect_key,
                    binding=owner["binding"],
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
                await self._observe_owned(
                    owner, "error", {"code": getattr(error, "code", "runner_outcome_unknown")}
                )
        candidate["artifacts"] = self._artifacts(owner["environment"])
        if owner["native_error"] is not None:
            await self._observe_owned(owner, "error", {"code": owner["native_error"].code})
            raise owner["native_error"]
        if not candidate["text"].strip() and not candidate["artifacts"]:
            error = RunnerUnavailable("empty native result")
            await self._observe_owned(owner, "error", {"code": error.code})
            raise error
        candidate["stop"] = {k: owner["stop"][k] for k in ("container_id", "generation", "fenced")}
        await self._observe_owned(owner, "result_candidate", {"result": candidate})
        return EffectObservation(candidate, source="codex-coding-runner")

    async def _terminal(self, owner, thread_id, turn_id):
        for _ in range(1000):
            await self._cancelled_owned(owner)
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
                await self._observe_owned(
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
        if owner.get("retirement_complete"):
            stop = owner["stop_evidence"]
            if stop is not None:
                await self._observe_owned(owner, "stop", stop)
            elif owner.get("create_not_dispatched") is not None:
                await self._observe_owned(
                    owner, "create_not_dispatched", owner["create_not_dispatched"]
                )
            elif owner.get("namespace_absence") is not None:
                await self._observe_owned(owner, "namespace_absent", owner["namespace_absence"])
            await self._release_capacity(owner)
            owner["stop"] = stop or {"container_id": None, "generation": None, "fenced": True}
            return
        env = owner["environment"]
        stop = None
        failure = None
        owner["ending"] = True
        try:
            if owner["cold"] and owner.get("capacity") is None:
                await self._acquire_capacity(owner, recovery=True)
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
                if stop is None and getattr(env, "_create_no_submit", None) is not None:
                    owner["create_not_dispatched"] = await env.observe_create_not_dispatched()
                if stop is not None and not (
                    stop["fenced"] and stop["retired"] and not stop["container_present"]
                ):
                    raise ExecutionHostFailed(
                        "Original Coding resource retirement is not confirmed"
                    )
            known = owner.get("known_resource", False) or any(
                value is not None for value in owner["original_state"].values()
            )
            if stop is None and known and owner.get("create_not_dispatched") is None:
                original = owner["original_state"]
                resource = owner.get("resource_intent")
                if (
                    owner.get("history")
                    and env is not None
                    and resource is not None
                    and resource["owner"] is not None
                    and original.get("prepare_grant") is not None
                    and all(original.get(name) is None for name in ("prepared", "thread", "turn"))
                    and resource["prepared"] is None
                    and resource["stop"] is None
                ):
                    from .temporal_coding_runtime import original_owner_stopped

                    if not await original_owner_stopped(self, resource["owner"]):
                        raise ExecutionHostFailed(
                            "Original Worker still owns native namespace permission"
                        )
                    absent = await env.observe_namespace_absence()
                    owner["namespace_absence"] = {
                        **absent,
                        "owner": resource["owner"],
                        "process_present": False,
                    }
                else:
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
                    await self._journal_method(
                        owner,
                        "lookup",
                        context.scope,
                        context.effect_key,
                        binding=owner["binding"],
                    )
                ) is not None
        owner["stop_evidence"] = stop
        owner["retirement_complete"] = True
        # This local sentinel releases a no-process owner. It is never adopted
        # as namespace stop evidence or exposed by cold stop_existing.
        if stop is not None:
            await self._observe_owned(owner, "stop", stop)
        elif owner.get("create_not_dispatched") is not None:
            await self._observe_owned(
                owner, "create_not_dispatched", owner["create_not_dispatched"]
            )
        elif owner.get("namespace_absence") is not None:
            await self._observe_owned(owner, "namespace_absent", owner["namespace_absence"])
        await self._release_capacity(owner)
        owner["stop"] = stop or {"container_id": None, "generation": None, "fenced": True}

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
            if self._active is owner:
                self._active = None
            return
        if owner["cleanup"] is not None and owner["cleanup"].done():
            owner["cleanup"] = None
        await self._cleanup(owner)
        if self._active is owner:
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
            await self._release_unprepared_capacity({"envelope": envelope, "authority": authority})
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
        if self._active is not None:
            active = self._active
            if canonical(_dispatch(envelope)) != canonical(_dispatch(active["envelope"])):
                raise CoordinatorBusy(
                    "A different original Coding execution still owns its resource"
                )
            await self._close_owner(active)
            return active.get("stop_evidence")
        self._active = owner
        try:
            await self._cleanup(owner)
            return owner.get("stop_evidence")
        finally:
            if self._active is owner and owner["stop"] is not None:
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


# Fixed default async journal functions; no duck-typed coroutine adapters.
_PG_METHODS = {
    name: getattr(PostgresRunnerJournal, name)
    for name in (
        "begin_resource",
        "resource_state",
        "record_resource",
        "pending_resources",
        "begin",
        "lookup",
        "mark_thread_submitted",
        "mark_turn_submitted",
        "record_thread",
        "record_turn",
        "record_observation",
        "request_cancel",
    )
}

_HISTORY_METHODS = {
    name: getattr(TemporalCodingAuthority, name)
    for name in (
        "check",
        "resource_state",
        "cancelled",
        "authorize",
        "adopt",
        "validate_registration",
    )
}

# The selected adjacent path must prove that cancellation still executes the
# original fresh pre/Query/post validation, including nested helper code.
_HISTORY_CONTROL_PINS = {
    name: (method, _history_executable_digest(method))
    for name in ("cancelled", "_state", "_call", "_check_pins")
    for method in (getattr(TemporalCodingAuthority, name),)
}
