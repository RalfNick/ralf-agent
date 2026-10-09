"""Host-granted grounded rule proposals and borrowed writable memory targets."""

import copy
import math
from dataclasses import asdict

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .memory_extraction import FactProposal, MemoryAdmissionPolicy, source_value
from .ports import is_sync_callable
from .task_controls import _binding
from .types import Scope, canonical, digest


class ManagedMemoryPolicy:
    """Opt-in, synchronous selection; I/O remains the Local Engine's responsibility.

    Registering this component in a scoped host catalog grants its write target.
    Facts read views cannot grant writes. All targets are borrowed, never closed.
    Subclasses may override propose, but only grounded concrete proposals are admitted.
    """

    def __init__(self, memory, *, admission=None, namespace="auto-memory", scope=None, timeout=5):
        self.memory = memory
        self.admission = MemoryAdmissionPolicy() if admission is None else admission
        self.scope = Scope() if scope is None else scope
        self.namespace, self.timeout = namespace, timeout
        if not isinstance(self.scope, Scope) or not isinstance(
            self.admission, MemoryAdmissionPolicy
        ):
            raise ValidationError("Managed memory requires trusted Scope and admission policy")
        if not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 128:
            raise ValidationError("Memory namespace must be bounded text")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValidationError("Managed memory timeout must be finite and between 0 and 60")
        backend = getattr(memory, "backend_id", None)
        if not isinstance(backend, str) or not backend.strip():
            raise ValidationError("Managed memory requires a stable backend identity")
        self._methods = {}
        for name in ("put_fact", "recall", "validate_facts"):
            method = getattr(memory, name, None)
            if not callable(method):
                raise ValidationError(
                    "Managed memory requires a writable CAS/recall/validation port"
                )
            self._methods[name] = _binding(method)
        version = getattr(memory, "fact_inspection_version", None)
        if version is not None:
            if (
                type(version) is not int
                or version != 1
                or not callable(getattr(memory, "inspect_fact", None))
            ):
                raise ValidationError(
                    "Exact fact inspection requires optional completed port version 1"
                )
            self._methods["inspect_fact"] = _binding(memory.inspect_fact)
        self._inspection = version
        from .memory import ThreadedMemoryAdapter

        self._thread_target = memory.backend if isinstance(memory, ThreadedMemoryAdapter) else None
        self._thread_methods = (
            {name: _binding(getattr(self._thread_target, name)) for name in self._methods}
            if self._thread_target is not None
            else {}
        )
        if not is_sync_callable(self.propose) or not is_sync_callable(self.admission.validate):
            raise ValidationError("Managed memory selection and admission must be synchronous")
        self._propose = _binding(self.propose)
        self._validate = _binding(self.admission.validate)
        self._identity = {
            "kind": "managed-rule-memory",
            "version": "1",
            "scope": asdict(self.scope),
            "backend_id": backend,
            "namespace": namespace,
            "timeout": timeout,
            "admission": self.admission.identity,
            "credits_per_fact": 1,
            "inspection": "exact-v1" if version == 1 else "bounded-recall-v1",
        }
        canonical(self._identity)

    @property
    def identity(self):
        self.check(self.scope)
        return copy.deepcopy(self._identity)

    def check(self, scope):
        if scope != self.scope or asdict(self.scope) != self._identity["scope"]:
            raise AuthorizationDenied("Managed memory belongs to another trusted Scope")
        if (
            self.memory.backend_id != self._identity["backend_id"]
            or self.namespace != self._identity["namespace"]
            or self.timeout != self._identity["timeout"]
            or getattr(self.memory, "fact_inspection_version", None) != self._inspection
            or type(getattr(self.memory, "fact_inspection_version", None))
            is not type(self._inspection)
            or (
                self._thread_target is not None
                and (
                    self.memory.backend is not self._thread_target
                    or any(
                        _binding(getattr(self._thread_target, n, None)) != b
                        for n, b in self._thread_methods.items()
                    )
                )
            )
            or digest(self.admission.identity) != digest(self._identity["admission"])
            or _binding(self.propose) != self._propose
            or _binding(self.admission.validate) != self._validate
            or any(
                _binding(getattr(self.memory, name, None)) != b for name, b in self._methods.items()
            )
        ):
            raise DefinitionMismatch("Managed memory policy or writable target changed")

    def propose(self, evidence):
        return [
            FactProposal(key, source_value(evidence, path), path)
            for key, path in self.admission.identity["fields"].items()
        ]


def stage_identity(stage, scope):
    if not isinstance(stage, ManagedMemoryPolicy):
        raise ValidationError("stage_policy must be a ManagedMemoryPolicy")
    stage.check(scope)
    return stage.identity


def _enabled(manifest):
    from .binding_manifests import all_step_manifests

    return any("managed_memory" in view for view in all_step_manifests(manifest)) or any(
        _enabled(value) for value in manifest.get("orchestration", {}).get("members", {}).values()
    )


def admit_stages(engine, manifest, kind, parent_call=None):
    if not _enabled(manifest):
        return
    if kind not in {"agent", "sequence"} or parent_call is not None:
        raise ValidationError("Managed memory stages currently support native Agents and sequences")
    store = engine.store
    from .ports import _invoke_sync_none

    if (
        type(getattr(store, "managed_stage_version", None)) is not int
        or store.managed_stage_version != 1
    ):
        raise ValidationError("Managed memory requires optional atomic Store stage version 1")
    if not is_sync_callable(getattr(store, "managed_stage_reservation", None)):
        raise ValidationError(
            "Managed memory requires independent synchronous reservation evidence"
        )
    _invoke_sync_none(getattr(store, "prepare_managed_stages", None), "Managed stage activation")
