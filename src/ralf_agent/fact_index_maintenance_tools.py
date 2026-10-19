"""Snapshot-bound Facts index maintenance under original ToolAction authority.

The source borrows one trusted index/catalog and owns only actual execution tasks.
Each original Action/effect key fixes one source generation before index effects.
Pages are bounded per dispatch; no lifetime allowance or hidden retry is claimed.
Only returned building/ready state or a typed source change becomes a receipt.
Generic CAS/port failures retain pending intent and their original typed refusal.
"""

import copy
import json
from dataclasses import asdict

from .binding_artifacts import _method_binding, _same_binding
from .errors import (
    AuthorizationDenied,
    DefinitionMismatch,
    IdempotencyConflict,
    RuntimeClosed,
    ValidationError,
)
from .fact_index_generation import GenerationSourceChanged
from .ports import is_async_callable
from .tool_execution import ToolExecutionOwner
from .tool_sources import ToolDescriptor
from .tools import _callable_identity
from .types import InvocationContext, Scope, canonical, digest

NAME = "facts_index_ensure_current"
STATUSES = {"ready", "partial", "source_changed"}
READY_ONLY_SCHEMA = {
    "type": "object",
    "properties": {"status": {"const": "ready"}},
    "required": ["status"],
}


def _text(value, label, *, limit=1024):
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > limit:
        raise ValidationError(label + " must be a bounded nonblank string")
    if "\x00" in value:
        raise ValidationError(label + " contains an invalid null byte")
    return value


def _pins(target, names):
    pins = []
    for name in names:
        method = getattr(target, name, None)
        if not callable(method):
            raise ValidationError("Maintenance source operation is missing")
        pins.append((name, _method_binding(method), digest(_callable_identity(method))))
    return tuple(pins)


def _check_pins(target, pins):
    for name, binding, fingerprint in pins:
        method = getattr(target, name, None)
        if (
            not callable(method)
            or not _same_binding(_method_binding(method), binding)
            or digest(_callable_identity(method)) != fingerprint
        ):
            raise DefinitionMismatch("Maintenance source original operation changed")


class FactIndexMaintenanceToolSource:
    """Fixed borrowed selection, independent CAS effect journal and real task owner."""

    def __init__(self, index, *, version, scope, namespace, max_pages=64):
        _text(version, "Maintenance behavior version", limit=256)
        if type(scope) is not Scope:
            raise ValidationError("Maintenance source requires a trusted native Scope")
        _text(scope.workspace, "Maintenance workspace")
        _text(scope.principal, "Maintenance principal")
        _text(namespace, "Maintenance namespace", limit=128)
        if type(max_pages) is not int or not 1 <= max_pages <= 256:
            raise ValidationError("Maintenance pages must be an integer from 1 through 256")
        for name in ("source_snapshot", "rebuild_for_snapshot"):
            if not is_async_callable(getattr(index, name, None)):
                raise ValidationError("Maintenance requires original async generation operations")
        catalog = getattr(index, "original_catalog", None)
        if any(not is_async_callable(getattr(catalog, name, None)) for name in ("load", "save")):
            raise ValidationError("Maintenance requires the original async CAS catalog")
        self._index = self._index_ref = index
        self._catalog = self._catalog_ref = catalog
        self._scope = Scope(scope.workspace, scope.principal)
        self._namespace = namespace
        self._selection = canonical({"scope": asdict(scope), "namespace": namespace})
        self._index_pin = canonical(index.identity)
        protocol = index.identity.get("generation_protocol", {})
        if protocol.get("selection") != json.loads(self._selection):
            raise ValidationError("Maintenance selection must match the trusted generation index")
        self._catalog_pin = canonical(catalog.identity)
        self._index_methods = _pins(index, ("source_snapshot", "rebuild_for_snapshot"))
        self._catalog_methods = _pins(catalog, ("load", "save"))
        self._owner = self._owner_ref = ToolExecutionOwner(version=version, max_calls=1)
        self._execution_ref = self._owner_ref._execution
        self._execution_methods = _pins(self._execution_ref, ("execute", "wait", "aclose"))
        self._owner_methods = _pins(self._owner, ("execute", "wait", "aclose"))
        self._owner_pin = canonical(self._owner.identity)
        self._address = digest(
            {"definition": index.identity, "scope": asdict(scope), "namespace": namespace}
        )
        self._descriptor = ToolDescriptor(
            NAME,
            "Ensure this trusted Facts index generation is current with a bounded maintenance attempt; only ready permits a reader.",
            {
                "type": "object",
                "properties": {"effect_key": {"type": "string", "minLength": 1, "maxLength": 1024}},
                "required": ["effect_key"],
                "additionalProperties": False,
            },
        )
        self._methods = _pins(
            self,
            (
                "list_tools",
                "call_tool",
                "reconcile",
                "query_refresh",
                "validate_tool_policy",
                "_check",
                "_check_execution_owner",
                "_context",
                "_base",
                "_load",
                "_validate_record",
                "_save",
                "_ensure",
                "_receipt",
                "_finish",
                "aclose",
            ),
        )
        self._identity_getter = type(self).identity.fget
        self._definition = {
            "kind": "fact-index-maintenance-tool-source",
            "version": "1",
            "behavior_version": version,
            "selection": json.loads(self._selection),
            "index": json.loads(self._index_pin),
            "catalog": json.loads(self._catalog_pin),
            "index_address": self._address,
            "max_pages_per_dispatch": max_pages,
            "max_records": index.identity["max_records"],
            "journal_scheme": "effect:sha256-key-v1",
            "execution_owner": self._owner.identity,
            "tool": self._descriptor.to_dict(),
            "implementation": {name: fingerprint for name, _, fingerprint in self._methods},
        }
        self._definition_pin = canonical(self._definition)
        self._closing = self._closed = False

    def _check(self):
        self._check_execution_owner()
        if (
            self._index is not self._index_ref
            or self._catalog is not self._catalog_ref
            or self._owner is not self._owner_ref
            or self._index.original_catalog is not self._catalog
            or type(self).identity.fget is not self._identity_getter
            or canonical({"scope": asdict(self._scope), "namespace": self._namespace})
            != self._selection
            or canonical(self._definition) != self._definition_pin
            or canonical(self._index.identity) != self._index_pin
            or canonical(self._catalog.identity) != self._catalog_pin
            or canonical(self._owner.identity) != self._owner_pin
        ):
            raise DefinitionMismatch("Maintenance source original resource or definition changed")
        _check_pins(self, self._methods)
        _check_pins(self._index, self._index_methods)
        _check_pins(self._catalog, self._catalog_methods)
        _check_pins(self._owner, self._owner_methods)

    def _check_execution_owner(self):
        if (
            getattr(self, "_owner", None) is not self._owner_ref
            or getattr(self._owner_ref, "_execution", None) is not self._execution_ref
        ):
            raise DefinitionMismatch("Maintenance original execution owner changed")
        _check_pins(self._owner_ref, self._owner_methods)
        _check_pins(self._execution_ref, self._execution_methods)

    @property
    def identity(self):
        self._check()
        return json.loads(self._definition_pin)

    async def list_tools(self):
        self._check()
        if self._closing:
            raise RuntimeClosed("Maintenance source is closing")
        return (self._descriptor,)

    def validate_tool_policy(self, descriptor, policy):
        self._check()
        if (
            not isinstance(descriptor, ToolDescriptor)
            or descriptor.to_dict() != self._descriptor.to_dict()
            or policy.effect != "idempotent_write"
            or policy.effect_key_argument != "effect_key"
            or policy.reconciler is None
            or not _same_binding(
                _method_binding(policy.reconciler), _method_binding(self.reconcile)
            )
        ):
            raise ValidationError(
                "Maintenance requires its reserved idempotent key and exact original reconciler"
            )

    def _context(self, scope, effect_key, context=None):
        if type(scope) is not Scope or canonical(asdict(scope)) != canonical(asdict(self._scope)):
            raise AuthorizationDenied("Maintenance belongs to another trusted Scope")
        _text(effect_key, "Maintenance effect key")
        if context is not None:
            if type(context) is not InvocationContext or context.effect_key != effect_key:
                raise ValidationError("Maintenance requires the original InvocationContext")
            for name in ("run_id", "action_id", "attempt_id", "execution_epoch"):
                _text(getattr(context, name), "Maintenance " + name)

    def _base(self, context):
        self._context(context.scope, context.effect_key, context)
        return {
            "definition": self.identity,
            "scope": asdict(self._scope),
            "namespace": self._namespace,
            "index_address": self._address,
            "run_id": context.run_id,
            "action_id": context.action_id,
            "effect_key": context.effect_key,
            "arguments": {},
            "max_pages_per_dispatch": self._definition["max_pages_per_dispatch"],
        }

    def _validate_record(self, record, effect_key):
        if type(record) is not dict or set(record) != {
            "schema_version",
            "request",
            "request_digest",
            "source_snapshot",
            "build_id",
            "receipt",
        }:
            raise ValidationError("Maintenance journal has an invalid original record")
        base = record["request"]
        if type(base) is not dict or set(base) != {
            "definition",
            "scope",
            "namespace",
            "index_address",
            "run_id",
            "action_id",
            "effect_key",
            "arguments",
            "max_pages_per_dispatch",
        }:
            raise ValidationError("Maintenance journal has an invalid original request")
        expected = {
            "definition": self.identity,
            "scope": asdict(self._scope),
            "namespace": self._namespace,
            "index_address": self._address,
            "effect_key": effect_key,
            "arguments": {},
            "max_pages_per_dispatch": self._definition["max_pages_per_dispatch"],
        }
        if any(canonical(base.get(key)) != canonical(value) for key, value in expected.items()):
            raise IdempotencyConflict(
                "Maintenance key belongs to another original definition or selection"
            )
        _text(base["run_id"], "Journal Run")
        _text(base["action_id"], "Journal Action")
        _text(record["source_snapshot"], "Journal snapshot")
        if (
            record["schema_version"] != 1
            or record["request_digest"] != digest(base)
            or record["build_id"] != digest([self._address, record["source_snapshot"]])
        ):
            raise ValidationError("Maintenance journal immutable evidence is invalid")
        receipt = record["receipt"]
        if receipt is not None:
            if type(receipt) is not dict or set(receipt) != {
                "schema_version",
                "status",
                "effect_key",
                "run_id",
                "action_id",
                "scope",
                "namespace",
                "definition",
                "source_snapshot",
                "build_id",
                "request_digest",
                "coverage",
                "state_digest",
            }:
                raise ValidationError("Maintenance journal receipt is invalid")
            if receipt["status"] not in STATUSES or receipt["schema_version"] != 1:
                raise ValidationError("Maintenance journal receipt has an invalid terminal state")
            expected_receipt = self._receipt(record, receipt["status"], None)
            for key in set(expected_receipt) - {"coverage", "state_digest"}:
                if canonical(receipt[key]) != canonical(expected_receipt[key]):
                    raise ValidationError("Maintenance receipt substituted original evidence")
            if receipt["status"] == "source_changed":
                if receipt["coverage"] is not None or receipt["state_digest"] is not None:
                    raise ValidationError("Changed-source receipt cannot attest index coverage")
            else:
                coverage = receipt["coverage"]
                if (
                    type(coverage) is not dict
                    or set(coverage) != {"scanned", "indexed", "expired"}
                    or any(type(n) is not int or n < 0 for n in coverage.values())
                    or coverage["indexed"] + coverage["expired"] != coverage["scanned"]
                    or coverage["scanned"] > self._definition["max_records"]
                ):
                    raise ValidationError("Maintenance receipt has invalid bounded coverage")
                if (
                    type(receipt["state_digest"]) is not str
                    or len(receipt["state_digest"]) != 64
                    or any(c not in "0123456789abcdef" for c in receipt["state_digest"])
                ):
                    raise ValidationError("Maintenance receipt lacks original state evidence")
        canonical(record)
        return copy.deepcopy(record)

    async def _load(self, effect_key):
        self._check()
        revision, record = await self._catalog.load(
            self._scope, self._address, "effect:" + digest(effect_key)
        )
        self._check()
        if type(revision) is not int or revision < 0 or (record is None) != (revision == 0):
            raise ValidationError("Maintenance catalog returned invalid revision evidence")
        return revision, None if record is None else self._validate_record(record, effect_key)

    async def _save(self, record, revision):
        self._check()
        self._validate_record(record, record["request"]["effect_key"])
        result = await self._catalog.save(
            self._scope,
            self._address,
            "effect:" + digest(record["request"]["effect_key"]),
            copy.deepcopy(record),
            expected_version=revision,
        )
        self._check()
        if type(result) is not int or result != revision + 1:
            raise ValidationError("Maintenance catalog returned invalid CAS commit evidence")
        return result

    def _receipt(self, record, status, state):
        base = record["request"]
        return {
            "schema_version": 1,
            "status": status,
            "effect_key": base["effect_key"],
            "run_id": base["run_id"],
            "action_id": base["action_id"],
            "scope": copy.deepcopy(base["scope"]),
            "namespace": base["namespace"],
            "definition": base["index_address"],
            "source_snapshot": record["source_snapshot"],
            "build_id": record["build_id"],
            "request_digest": record["request_digest"],
            "coverage": None
            if state is None
            else {key: state[key] for key in ("scanned", "indexed", "expired")},
            "state_digest": None if state is None else digest(state),
        }

    async def _finish(self, record, revision, receipt):
        terminal = {**record, "receipt": receipt}
        await self._save(terminal, revision)
        return copy.deepcopy(receipt)

    async def _ensure(self, context):
        base = self._base(context)
        revision, record = await self._load(context.effect_key)
        if record is None:
            snapshot = await self._index.source_snapshot(self._scope, self._namespace)
            self._check()
            _text(snapshot, "Maintenance original snapshot")
            record = {
                "schema_version": 1,
                "request": base,
                "request_digest": digest(base),
                "source_snapshot": snapshot,
                "build_id": digest([self._address, snapshot]),
                "receipt": None,
            }
            revision = await self._save(record, 0)
        elif canonical(record["request"]) != canonical(base):
            raise IdempotencyConflict("Maintenance key belongs to another original Run or Action")
        if record["receipt"] is not None:
            return copy.deepcopy(record["receipt"])
        try:
            state = await self._index.rebuild_for_snapshot(
                self._scope,
                self._namespace,
                record["source_snapshot"],
                max_pages=self._definition["max_pages_per_dispatch"],
            )
        except GenerationSourceChanged:
            self._check()
            return await self._finish(
                record, revision, self._receipt(record, "source_changed", None)
            )
        self._check()
        # Original inherited state validator is the adoption authority; no DTO substitute.
        state = self._index._state(state, self._address)
        if (
            state["source_snapshot"] != record["source_snapshot"]
            or state["build_id"] != record["build_id"]
        ):
            raise ValidationError("Maintenance returned another original generation")
        status = "ready" if state["status"] == "ready" else "partial"
        return await self._finish(record, revision, self._receipt(record, status, state))

    async def call_tool(self, descriptor, arguments, context):
        self._check()
        if self._closing:
            raise RuntimeClosed("Maintenance source is closing")
        if (
            not isinstance(descriptor, ToolDescriptor)
            or descriptor.to_dict() != self._descriptor.to_dict()
            or type(arguments) is not dict
            or set(arguments) != {"effect_key"}
        ):
            raise ValidationError(
                "Maintenance requires its original flat descriptor and reserved key"
            )
        if type(context) is not InvocationContext:
            raise ValidationError("Maintenance requires the original InvocationContext")
        self._context(context.scope, arguments["effect_key"], context)
        base = self._base(context)
        proof = {
            "scope": asdict(context.scope),
            "action_id": context.action_id,
            "release_digest": digest(self.identity),
            "request_digest": digest(base),
            "execution_epoch": context.execution_epoch,
        }

        async def invoke():
            return await self._ensure(context)

        return await self._owner.execute(invoke, proof=proof)

    async def query_refresh(self, scope, effect_key):
        self._check()
        self._context(scope, effect_key)
        _, record = await self._load(effect_key)
        return None if record is None else copy.deepcopy(record["receipt"])

    async def reconcile(self, arguments, context):
        self._check()
        if type(arguments) is not dict or arguments or type(context) is not InvocationContext:
            raise ValidationError(
                "Maintenance reconciliation requires original empty caller arguments"
            )
        base = self._base(context)
        _, record = await self._load(context.effect_key)
        if record is None:
            return None
        if canonical(record["request"]) != canonical(base):
            raise IdempotencyConflict(
                "Maintenance reconciliation belongs to another original Run or Action"
            )
        return copy.deepcopy(record["receipt"])

    async def aclose(self, *, wait_timeout=30):
        # Owner completion, including delegated threads, precedes closure. Borrowed
        # data connections remain the host's responsibility after successful drain.
        self._closing = True
        # Cleanup may follow a data-binding failure, so validate ownership rather
        # than requiring live data ports. Never replace the actual outstanding work
        # with an empty owner, including through ToolExecutionOwner._execution.
        _check_pins(self, self._methods)
        self._check_execution_owner()
        await self._owner_ref.aclose(wait_timeout=wait_timeout)
        _check_pins(self, self._methods)
        self._check_execution_owner()
        self._closed = True
