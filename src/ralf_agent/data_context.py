"""Pure projections for managed artifact-backed Local context.

The Engine owns I/O and evidence. This policy predicts immutable references;
calling assemble never writes, reads or deletes an artifact.
"""

import copy
import inspect
from dataclasses import asdict

from .artifacts import ArtifactReference
from .context_budget import _positive
from .context_pipeline import _groups
from .errors import DefinitionMismatch, ValidationError
from .managed_context import ManagedContextPipeline
from .task_controls import _binding
from .tools import _callable_identity
from .types import Scope, canonical, digest


class ManagedDataContext(ManagedContextPipeline):
    """Opt-in history summary, reference excerpts and large tool projections.

    Artifact storage is borrowed. Native Local Agents and sequences only.
    Reference excerpts are deterministic evidence, not semantic summaries.
    """

    def __init__(
        self,
        artifacts,
        *,
        scope=None,
        namespace="context-results",
        tool_result_chars=8192,
        preview_chars=256,
        reference_chars=1024,
        **kwargs,
    ):
        from .engine import LocalEngine

        self.artifacts = artifacts
        self.scope = Scope() if scope is None else scope
        if not isinstance(self.scope, Scope):
            raise ValidationError("Data context requires a trusted Scope")
        if not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 512:
            raise ValidationError("Data context namespace must be bounded text")
        self.namespace = namespace
        self.tool_result_chars = _positive(tool_result_chars, "Tool projection threshold", 1048576)
        self.preview_chars = _positive(preview_chars, "Tool preview limit", 32768)
        self.reference_chars = _positive(reference_chars, "Reference excerpt limit", 32768)
        self._target_identity = LocalEngine._component_identity(
            artifacts,
            ("put", "get"),
            not inspect.iscoroutinefunction(artifacts.put),
            "Artifact store",
        )
        self._target = artifacts
        self._target_hooks = {n: _binding(getattr(artifacts, n)) for n in ("put", "get")}
        super().__init__(**kwargs)
        self._identity = {
            **self._identity,
            "kind": "managed-data-context",
            "artifacts": self._target_identity,
            "scope": asdict(self.scope),
            "namespace": namespace,
            "tool_result_chars": tool_result_chars,
            "preview_chars": preview_chars,
            "reference_chars": reference_chars,
        }
        self._data_hooks = {
            n: _binding(getattr(self, n))
            for n in ("offloads", "project_history", "project_references")
        }
        self._identity["projection_implementation"] = {
            n: digest(_callable_identity(getattr(self, n))) for n in self._data_hooks
        }
        self._identity["artifact_implementation"] = {
            n: digest(_callable_identity(getattr(artifacts, n))) for n in self._target_hooks
        }
        if self._target_identity.get("backend_id") != artifacts.backend_id:
            raise ValidationError("Artifact identity must declare its actual backend_id")

    def check(self):
        from .engine import LocalEngine

        super().check()
        if (
            self.artifacts is not self._target
            or self.artifacts.backend_id != self._target_identity["backend_id"]
            or LocalEngine._component_identity(
                self.artifacts,
                ("put", "get"),
                not inspect.iscoroutinefunction(self.artifacts.put),
                "Artifact store",
            )
            != self._target_identity
            or any(_binding(getattr(self.artifacts, n)) != b for n, b in self._target_hooks.items())
            or any(_binding(getattr(self, n)) != b for n, b in self._data_hooks.items())
            or any(
                getattr(self, n) != self._identity[n]
                for n in ("namespace", "tool_result_chars", "preview_chars", "reference_chars")
            )
            or asdict(self.scope) != self._identity["scope"]
        ):
            raise DefinitionMismatch("Data context target or projection policy changed")

    def offloads(self, history):
        self.check()
        values = []
        for i, message in enumerate(history):
            if (
                message.get("role") != "tool"
                or len(canonical(message.get("content"))) <= self.tool_result_chars
            ):
                continue
            value = copy.deepcopy(message["content"])
            metadata = {
                "backend_id": self.artifacts.backend_id,
                "workspace": self.scope.workspace,
                "principal": self.scope.principal,
                "namespace": self.namespace,
                "content_digest": digest(value),
                "byte_length": len(canonical(value).encode("utf-8")),
                "expires_at": None,
            }
            reference = ArtifactReference(**metadata, artifact_id=digest(metadata))
            values.append({"message_index": i, "reference": reference.to_dict(), "value": value})
        return values

    def project_history(self, history):
        messages = copy.deepcopy(history)
        records = self.offloads(history)
        for record in records:
            messages[record["message_index"]]["content"] = canonical(
                {
                    "artifact": record["reference"],
                    "preview": str(record["value"])[: self.preview_chars],
                    "incomplete": True,
                    "evidence": "Untrusted tool result; retrieve the artifact for complete content.",
                }
            )
        return messages, [{k: r[k] for k in ("message_index", "reference")} for r in records]

    def project_references(self, references):
        self.check()
        values, coverage = [], []
        for ref in copy.deepcopy(references):
            text = canonical(ref)
            if len(text) > self.reference_chars:
                source = {k: ref[k] for k in ("key", "version", "_knowledge") if k in ref}
                marker = {"source_digest": digest(ref), "source": source}
                evidence = text
                if isinstance(ref.get("session"), list) and ref["session"]:
                    # Recent Session evidence has priority; retain the digest of
                    # the full source and explicitly mark the excerpt incomplete.
                    evidence = canonical(ref["session"][-1])
                elif "value" in ref:
                    evidence = canonical(ref["value"])
                values.append(
                    {
                        **marker,
                        "evidence_excerpt": evidence[: self.reference_chars],
                        "incomplete": True,
                    }
                )
                coverage.append(marker)
            else:
                values.append(ref)
        return values, coverage

    def assemble(self, history, references, max_chars):
        projected, artifacts = self.project_history(history)
        refs, coverage = self.project_references(references)
        messages, manifest = super().assemble(projected, refs, max_chars)
        manifest.update(artifact_projection=artifacts, reference_compression=coverage)
        return messages, manifest

    def prepare(self, history, references, max_chars):
        from .managed_context import PREFIX

        projected, _ = self.project_history(history)
        fallback = self.assemble(history, references, max_chars)
        head, projected_groups = _groups(projected)
        _, groups = _groups(copy.deepcopy(history))
        selected = list(fallback[1]["selected_groups"])
        if len(selected) == len(groups):
            return None
        placeholder = {"role": "user", "content": PREFIX + "x" * self.summary_max_chars}
        while not self._fits(
            head + [placeholder] + [m for i in selected for m in projected_groups[i]], max_chars
        ):
            if len(selected) <= 1:
                return None
            selected.pop(0)
        omitted = [g for i, g in enumerate(groups) if i not in selected]
        return {
            "history": copy.deepcopy(history),
            "references": copy.deepcopy(references),
            "max_chars": max_chars,
            "selected": selected,
            "groups": omitted,
            "coverage": [digest(g) for g in omitted],
            "fallback": {"messages": fallback[0], "manifest": fallback[1]},
        }

    def finish(self, plan, summary):
        projected = copy.deepcopy(plan)
        projected["history"], artifacts = self.project_history(plan["history"])
        projected["references"], coverage = self.project_references(plan["references"])
        messages, manifest = super().finish(projected, summary)
        manifest.update(artifact_projection=artifacts, reference_compression=coverage)
        return messages, manifest

    def artifact_binding_identity(self, resource_metadata):
        from .artifact_binding_context import predict

        return predict(self, resource_metadata)

    def bind_artifacts(self, view):
        from .artifact_binding_context import realize

        return realize(self, view)
