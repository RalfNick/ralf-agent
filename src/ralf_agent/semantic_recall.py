"""Pure task-aware recall planner; recent Session selection remains unchanged."""

from dataclasses import replace

from .errors import ValidationError
from .query_transform import query_text
from .recall import MemoryRecallPolicy
from .retrieval import _scope, _text


class TaskRecallPlanner:
    def __init__(self, policy=None):
        self.policy = MemoryRecallPolicy() if policy is None else policy
        if (
            not isinstance(self.policy, MemoryRecallPolicy)
            or self.policy.max_pages != 1
            or self.policy.facts.text is not None
        ):
            raise ValidationError("Task recall requires one page and no constant Facts text filter")

    @property
    def identity(self):
        return {"kind": "task-text-recall-planner", "version": "1", "policy": self.policy.identity}

    def plan(self, scope, namespace, session_id, text):
        _scope(scope, namespace)
        _text(session_id, "Recall session")
        return MemoryRecallPolicy(
            facts=replace(self.policy.facts, text=query_text(text)),
            session=self.policy.session,
            max_pages=1,
        )
