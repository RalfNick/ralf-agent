"""Pure bounded candidate selection; Knowledge ranking and source data stay intact."""

from typing import Protocol

from .context_budget import _positive
from .errors import ValidationError
from .retrieval import _tokens
from .types import canonical


class ReferenceSelector(Protocol):
    identity: dict

    def select(self, task: str, references: list[dict]) -> list[int]: ...


class OverlapReferenceSelector:
    def __init__(self, *, max_references=32, max_query_chars=4096):
        self._max_references = _positive(max_references, "Selected reference limit", 256)
        self._max_query_chars = _positive(max_query_chars, "Selection query limit", 65536)

    @property
    def identity(self):
        return {
            "kind": "overlap-reference-selector",
            "version": "1",
            "max_references": self._max_references,
            "max_query_chars": self._max_query_chars,
            "mixed_source_policy": "relevant-fact-first-alternating-v1",
        }

    def select(self, task, references):
        if not isinstance(task, str):
            raise ValidationError("Reference selection requires serialized task text")
        query = _tokens(task[: self._max_query_chars])
        sessions, knowledge, facts = [], [], []
        for index, ref in enumerate(references):
            if "session" in ref:
                sessions.append(index)
            elif "_knowledge" in ref:
                knowledge.append(index)
            else:
                value = ref.get("value")
                if isinstance(value, dict) and value.get("trust") == "completed-result-observation":
                    value = {"key": value.get("key"), "value": value.get("value")}
                else:
                    value = {"key": ref.get("key"), "value": value}
                score = len(query & _tokens(canonical(value)))
                facts.append((-score, index))
        facts.sort()
        relevant = [i for score, i in facts if score < 0]
        remaining = [i for score, i in facts if score == 0]
        mixed = []
        for offset in range(max(len(relevant), len(knowledge))):
            if offset < len(relevant):
                mixed.append(relevant[offset])
            if offset < len(knowledge):
                mixed.append(knowledge[offset])
        return (sessions + mixed + remaining)[: self._max_references]
