"""Serializable locators and detached observations; no execution authority."""

import copy
import math
import re
from dataclasses import asdict, dataclass

from .errors import ValidationError
from .types import RunSnapshot, Scope


@dataclass(frozen=True)
class RunRef:
    authority_locator: str
    workspace: str
    principal: str
    run_id: str
    release_digest: str
    schema_version: int = 1

    def __post_init__(self):
        Scope(self.workspace, self.principal)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValidationError("RunRef requires schema_version=1")
        if not isinstance(self.authority_locator, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]{1,128}", self.authority_locator
        ):
            raise ValidationError("RunRef requires a non-secret opaque authority locator")
        if not isinstance(self.run_id, str) or not self.run_id.strip() or len(self.run_id) > 1024:
            raise ValidationError("RunRef requires a bounded Run ID")
        if not isinstance(self.release_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.release_digest
        ):
            raise ValidationError("RunRef requires the original release digest")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValidationError("RunRef requires exact locator fields")
        return cls(**value)


@dataclass(frozen=True)
class WaitResult:
    ref: RunRef
    snapshot: RunSnapshot
    wait_reason: str
    observed_at: float

    def __post_init__(self):
        if (
            not isinstance(self.ref, RunRef)
            or not isinstance(self.snapshot, RunSnapshot)
            or self.ref.run_id != self.snapshot.run_id
        ):
            raise ValidationError("WaitResult requires matching Run reference and snapshot")
        if self.wait_reason not in {"state_reached", "observation_timeout", "control_available"}:
            raise ValidationError("Unsupported observation reason")
        if type(self.observed_at) not in {int, float} or not math.isfinite(self.observed_at):
            raise ValidationError("Observation time must be finite")
        object.__setattr__(self, "snapshot", copy.deepcopy(self.snapshot))
