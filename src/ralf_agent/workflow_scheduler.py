"""Pure bounded scheduling; the Engine validates every proposed batch."""

import copy
from dataclasses import dataclass
from typing import Protocol

from .errors import ValidationError
from .types import canonical
from .workflow import ExecutionPlan, WorkflowSelection, _choices, _concurrency, _resolve


@dataclass(frozen=True)
class WorkflowBatch:
    selections: tuple[WorkflowSelection, ...] = ()
    skipped: tuple[str, ...] = ()
    done: bool = False
    result: object = None

    def __post_init__(self):
        if (
            not isinstance(self.selections, (list, tuple))
            or any(not isinstance(s, WorkflowSelection) for s in self.selections)
            or not isinstance(self.skipped, (list, tuple))
            or any(not isinstance(s, str) for s in self.skipped)
            or type(self.done) is not bool
        ):
            raise ValidationError("Invalid Workflow batch")
        canonical(self.result)
        object.__setattr__(self, "selections", tuple(copy.deepcopy(self.selections)))
        object.__setattr__(self, "skipped", tuple(self.skipped))
        object.__setattr__(self, "result", copy.deepcopy(self.result))


class WorkflowScheduler(Protocol):
    identity: dict

    def select(self, plan: ExecutionPlan, input, states: dict, limit: int) -> WorkflowBatch: ...


class StaticWorkflowScheduler:
    identity = {"kind": "static-workflow-scheduler", "version": "1"}

    def select(self, plan, input, states, limit):
        _concurrency(limit)
        ready, skipped, settled, result = _choices(plan, input, states, parallel=True)
        done = all(s["state"] in {"completed", "skipped"} for s in settled.values())
        return WorkflowBatch(
            [WorkflowSelection(n.id, _resolve(n.input, input, settled)) for n in ready[:limit]],
            skipped,
            done,
            result,
        )


def validate_batch(plan, input, states, limit, batch):
    _concurrency(limit)
    ready, skipped, settled, result = _choices(plan, input, states, parallel=True)
    done = all(s["state"] in {"completed", "skipped"} for s in settled.values())
    if (
        len(batch.skipped) != len(skipped)
        or set(batch.skipped) != set(skipped)
        or batch.done != done
        or canonical(batch.result) != canonical(result)
        or len(batch.selections) > limit
        or (done and batch.selections)
        or (ready and not batch.selections)
    ):
        raise ValidationError("Scheduler returned an invalid Workflow batch")
    eligible = {n.id: n for n in ready}
    seen = set()
    for selection in batch.selections:
        node = eligible.get(selection.node_id)
        if (
            node is None
            or node.id in seen
            or selection.skipped
            or selection.done
            or selection.result is not None
            or canonical(selection.input) != canonical(_resolve(node.input, input, settled))
        ):
            raise ValidationError("Scheduler returned an ineligible node or input")
        seen.add(node.id)
