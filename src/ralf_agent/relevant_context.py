"""Opt-in pure reference ordering with original managed context effects and recovery."""

import copy
import inspect

from .context_pipeline import _Pure
from .data_context import ManagedDataContext
from .errors import DefinitionMismatch, ValidationError
from .reference_selection import OverlapReferenceSelector
from .task_controls import _binding
from .tools import _callable_identity
from .types import canonical, digest


def _indices(value, count):
    if type(value) is not list:
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise ValidationError("Reference selector must return completed integer indices")
    if (
        len(value) > 256
        or any(type(i) is not int or not 0 <= i < count for i in value)
        or len(value) != len(set(value))
    ):
        raise ValidationError("Reference selector chose duplicate or unavailable evidence")
    return list(value)


class RelevantDataContext(ManagedDataContext):
    def __init__(self, artifacts, *, selector=None, **options):
        self._selector = _Pure(
            OverlapReferenceSelector() if selector is None else selector, "select"
        )
        self._selector_pin = self._selector
        super().__init__(artifacts, **options)
        self._selection_hooks = {
            name: _binding(getattr(self, name)) for name in ("_select", "_restore")
        }
        self._identity.update(
            reference_selector=self._selector.release,
            selection_implementation={
                n: digest(_callable_identity(getattr(self, n))) for n in self._selection_hooks
            },
        )

    def check(self):
        super().check()
        if self._selector is not self._selector_pin or any(
            _binding(getattr(self, n)) != original for n, original in self._selection_hooks.items()
        ):
            raise DefinitionMismatch("Reference selection registration changed")
        self._selector.check()

    def _select(self, history, references):
        self.check()
        if (
            not isinstance(references, list)
            or len(references) > 4096
            or any(not isinstance(r, dict) for r in references)
            or len(canonical(references)) > 1048576
        ):
            raise ValidationError("Reference candidates exceed finite context bounds")
        task = history[1]["content"]
        frozen = copy.deepcopy(references)
        source = digest(frozen)
        indices = _indices(self._selector.call(task, frozen), len(references))
        if digest(frozen) != source:
            raise ValidationError("Reference selector modified source evidence")
        metadata = {
            "source_digest": source,
            "query_digest": digest(task),
            "selector": copy.deepcopy(self._selector.release),
            "indices": indices,
            "candidate_count": len(references),
            "selected_count": len(indices),
        }
        return [copy.deepcopy(references[i]) for i in indices], metadata

    def _restore(self, plan):
        self.check()
        saved = plan["fallback"]["manifest"]["reference_selection"]
        references = plan["references"]
        if (
            saved["source_digest"] != digest(references)
            or saved["query_digest"] != digest(plan["history"][1]["content"])
            or saved["selector"] != self._selector.release
            or saved["candidate_count"] != len(references)
        ):
            raise DefinitionMismatch("Saved reference selection lost its original source")
        indices = _indices(saved["indices"], len(references))
        if len(indices) != saved["selected_count"]:
            raise DefinitionMismatch("Saved reference selection counts changed")
        return [copy.deepcopy(references[i]) for i in indices]

    def assemble(self, history, references, max_chars):
        selected, metadata = self._select(history, references)
        messages, manifest = super().assemble(history, selected, max_chars)
        manifest["reference_selection"] = metadata
        return messages, manifest

    def project_references(self, references):
        self.check()
        values, coverage = [], []
        for ref in references:
            if "session" in ref:
                # Preserve source structure for the existing budgeter's complete
                # recent-turn selection, including native task/result records.
                values.append(copy.deepcopy(ref))
            else:
                projected, markers = super().project_references([ref])
                values.extend(projected)
                coverage.extend(markers)
        return values, coverage

    def finish(self, plan, summary):
        restored = copy.deepcopy(plan)
        restored["references"] = self._restore(plan)
        return super().finish(restored, summary)
