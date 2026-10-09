"""Portable Session/Turn identities, independent of clients and scheduling."""

import re
from dataclasses import asdict, dataclass, fields

from .agent_run import RunRef
from .binding_sessions import session_storage_key
from .errors import ValidationError
from .types import Scope, digest


def sha(value):
    if not isinstance(value, str) or re.fullmatch("[a-f0-9]{64}", value) is None:
        raise ValidationError("Session identity requires a SHA-256 digest")


def integer(value, *, minimum=1):
    if type(value) is not int or not minimum <= value < 2**63:
        raise ValidationError("Session revision/sequence requires a bounded integer")


def exact(cls, value):
    if not isinstance(value, dict) or set(value) != {f.name for f in fields(cls)}:
        raise ValidationError("Unknown or missing Session identity fields")
    return dict(value)


@dataclass(frozen=True)
class SessionKey:
    workspace: str
    principal: str
    resource_id: str
    namespace: str | None
    session_id: str
    schema_version: int = 1

    def __post_init__(self):
        Scope(self.workspace, self.principal)
        sha(self.resource_id)
        if self.namespace is not None and (
            not isinstance(self.namespace, str)
            or not self.namespace.strip()
            or len(self.namespace) > 128
        ):
            raise ValidationError("Session namespace requires 1 to 128 characters")
        if (
            not isinstance(self.session_id, str)
            or not self.session_id.strip()
            or len(self.session_id) > 256
        ):
            raise ValidationError("Session ID requires 1 to 256 characters")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValidationError("Unsupported Session key Schema")

    @property
    def key_id(self):
        return digest(self.to_dict())

    @property
    def storage_key(self):
        return session_storage_key(self.namespace, self.session_id)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**exact(cls, value))


@dataclass(frozen=True)
class SessionRef:
    key: SessionKey
    coordination_ref: str
    binding_revision: int
    definition_digest: str
    schema_version: int = 1

    def __post_init__(self):
        if not isinstance(self.key, SessionKey):
            raise ValidationError("SessionRef requires a SessionKey")
        sha(self.coordination_ref)
        sha(self.definition_digest)
        integer(self.binding_revision)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValidationError("Unsupported Session reference Schema")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        value = exact(cls, value)
        value["key"] = SessionKey.from_dict(value["key"])
        return cls(**value)


@dataclass(frozen=True)
class TurnAdmission:
    turn_id: str
    turn_seq: int
    session: SessionRef
    run: RunRef
    input_digest: str
    command_id: str
    schema_version: int = 1

    def __post_init__(self):
        integer(self.turn_seq)
        if not isinstance(self.session, SessionRef) or not isinstance(self.run, RunRef):
            raise ValidationError("Turn requires original Session and Run references")
        if (self.session.key.workspace, self.session.key.principal) != (
            self.run.workspace,
            self.run.principal,
        ):
            raise ValidationError("Turn references must share trusted Scope")
        for text in [self.turn_id, self.command_id]:
            if not isinstance(text, str) or not text.strip():
                raise ValidationError("Turn and command IDs must be nonempty strings")
        sha(self.input_digest)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValidationError("Unsupported Turn Schema")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        value = exact(cls, value)
        value["session"] = SessionRef.from_dict(value["session"])
        value["run"] = RunRef.from_dict(value["run"])
        return cls(**value)


@dataclass(frozen=True)
class SessionSnapshot:
    ref: SessionRef
    binding_revision: int
    last_turn_seq: int
    active_run: RunRef | None
    busy: bool
