"""Pure prediction and realization of an original managed Context target."""

import copy

from .binding_artifacts import ArtifactView, _scope
from .data_context import ManagedDataContext
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .managed_context import ManagedContextPipeline
from .skills import _plain
from .tools import _callable_identity
from .types import canonical, digest

_HOOKS = ("assemble", "prepare", "finish", "request", "excerpt", "validate_request", "_fits")
_DATA_HOOKS = ("offloads", "project_history", "project_references")


def _method(cls, name):
    return {
        "kind": "bound-method",
        "owner": cls.__module__ + "." + cls.__qualname__,
        "function": _callable_identity(getattr(cls, name)),
    }


def _settings(origin):
    return {
        "mode": origin.mode,
        "provider": origin.provider,
        "assembler": origin._assembler,
        "summarizer": origin._summarizer.component if origin.mode == "excerpt" else None,
        "summary_max_chars": origin.summary_max_chars,
        "source_max_chars": origin.source_max_chars,
        "timeout": origin.timeout,
    }


def _target(origin, description):
    if description is None:
        return None
    description = _plain(description)
    if (
        type(description) is not dict
        or set(description) != {"kind", "version", "backend_id", "target", "scope", "namespace"}
        or description["kind"] != "artifact-binding-view"
        or description["version"] != "1"
        or type(description["target"]) is not dict
        or description["target"].get("kind") != "artifact-binding-resource"
        or description["target"].get("version") != "1"
        or type(description["target"].get("backend")) is not dict
        or type(description["target"].get("namespaces")) is not list
        or description["backend_id"] != description["target"].get("backend", {}).get("backend_id")
        or description["namespace"] not in description["target"].get("namespaces", [])
    ):
        raise ValidationError("Artifact Context prediction requires its original selected resource")
    if description["scope"] != _scope(origin.scope):
        raise AuthorizationDenied("Artifact Context target belongs to another Scope")
    return description


def predict(origin, description):
    origin.check()
    for name in (*_HOOKS, *_DATA_HOOKS):
        if getattr(getattr(origin, name), "__func__", None) is not getattr(
            ManagedDataContext, name
        ):
            raise ValidationError(
                "Custom managed Context hooks require an explicit custom Artifact binding port"
            )
    target = _target(origin, description)
    value = _plain(origin.identity)
    cls = BoundArtifactContext if target is not None else DisabledArtifactContext
    value["implementation"] = {name: digest(_method(cls, name)) for name in _HOOKS}
    binding = {
        "version": 1,
        "mode": "ref" if target is not None else "disabled",
        "origin": _plain(origin.identity),
        "resource": target,
    }
    if target is None:
        for key in (
            "artifacts",
            "scope",
            "namespace",
            "tool_result_chars",
            "preview_chars",
            "projection_implementation",
            "artifact_implementation",
        ):
            value.pop(key, None)
        value["kind"] = "managed-context-pipeline"
    else:
        value.update(artifacts=target, namespace=target["namespace"])
        value["projection_implementation"] = {
            name: digest(_method(cls, name)) for name in _DATA_HOOKS
        }
        value["artifact_implementation"] = {
            name: digest(_method(ArtifactView, name)) for name in ("put", "get")
        }
    value["artifact_binding"] = binding
    return value


def realize(origin, target):
    if target is not None and type(target) is not ArtifactView:
        raise ValidationError("Artifact Context requires an original selected Artifact view")
    expected = predict(origin, None if target is None else target.identity)
    result = (
        DisabledArtifactContext(origin) if target is None else BoundArtifactContext(origin, target)
    )
    if result.identity != expected:
        raise DefinitionMismatch("Artifact Context realization differs from its pure prediction")
    return result


class BoundArtifactContext(ManagedDataContext):
    def __init__(self, origin, target):
        self._origin, self._origin_identity = origin, canonical(origin.identity)
        super().__init__(
            target,
            scope=origin.scope,
            namespace=target.namespace,
            tool_result_chars=origin.tool_result_chars,
            preview_chars=origin.preview_chars,
            reference_chars=origin.reference_chars,
            **_settings(origin),
        )
        self._identity["artifact_binding"] = {
            "version": 1,
            "mode": "ref",
            "origin": _plain(origin.identity),
            "resource": target.identity,
        }

    def check(self):
        super().check()
        self._origin.check()
        if canonical(self._origin.identity) != self._origin_identity:
            raise DefinitionMismatch("Original Artifact Context changed")


class DisabledArtifactContext(ManagedContextPipeline):
    def __init__(self, origin):
        self._origin, self._origin_identity = origin, canonical(origin.identity)
        super().__init__(**_settings(origin))
        self._identity["reference_chars"] = origin.reference_chars
        self._identity["artifact_binding"] = {
            "version": 1,
            "mode": "disabled",
            "origin": _plain(origin.identity),
            "resource": None,
        }

    def check(self):
        super().check()
        self._origin.check()
        if canonical(self._origin.identity) != self._origin_identity:
            raise DefinitionMismatch("Original disabled Artifact Context changed")

    def assemble(self, history, references, max_chars):
        self.check()
        references, coverage = self._origin.project_references(references)
        messages, metadata = super().assemble(history, references, max_chars)
        metadata.update(artifact_projection=[], reference_compression=coverage)
        return messages, metadata

    def finish(self, plan, summary):
        self.check()
        projected = copy.deepcopy(plan)
        projected["references"], coverage = self._origin.project_references(plan["references"])
        messages, metadata = super().finish(projected, summary)
        metadata.update(artifact_projection=[], reference_compression=coverage)
        return messages, metadata
