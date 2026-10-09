"""Optional durable Session admission, atomic with its execution authority."""

from typing import Protocol

from .types import Scope


class SessionAdmissionStore(Protocol):
    transaction_owner: object
    authority_backend_id: str

    def prepare(self) -> None: ...
    def load(self, scope: Scope, key_id: str) -> dict | None: ...
    def load_address(self, scope: Scope, address: str) -> dict | None: ...
    def insert(self, data: dict) -> None: ...
    def save(self, data: dict, *, expected_revision: int) -> None: ...
    def insert_turn(self, data: dict) -> None: ...
    def turns(self, scope: Scope, key_id: str, *, after: int, limit: int) -> list[dict]: ...
    def confirmed_result(
        self, scope: Scope, address: str, message_id: str, expected: dict
    ) -> bool: ...
    def route_owner(self, scope: Scope, resource: dict) -> str | None: ...

    def legacy_owner(
        self, scope: Scope, address: str, *, exclude_run_id: str | None = None
    ) -> str | None: ...


class CompositeSessionAdmissionStore(SessionAdmissionStore, Protocol):
    """Optional schema3 extension, completed inside the authority transaction."""

    def prepare_composites(self) -> None: ...


class ConversationSessionAdmissionStore(CompositeSessionAdmissionStore, Protocol):
    """Optional schema4 extension for original root conversation bindings."""

    def prepare_conversations(self) -> None: ...


class RemoteSessionAdmissionStore(ConversationSessionAdmissionStore, Protocol):
    """Optional schema5: remote data with original local admission authority."""

    def prepare_remote_sessions(self) -> None: ...
    def remote_owner(
        self, scope: Scope, address: str, *, exclude_run_id: str | None = None
    ) -> str | None: ...


class ValidatedSessionAdmission:
    """Require completed port results; never enter a deferred adapter operation."""

    def __init__(self, delegate):
        self.delegate = delegate

    def _call(self, method, kind, *args, **kwargs):
        import inspect
        import json

        from .errors import ValidationError
        from .ports import _complete_sync_none
        from .types import canonical

        value = getattr(self.delegate, method)(*args, **kwargs)
        if kind == "mutation":
            _complete_sync_none(value, "Session admission " + method)
            return None
        valid = (
            kind == "load"
            and (value is None or type(value) is dict)
            or kind == "rows"
            and type(value) is list
            and all(type(row) is dict for row in value)
            or kind == "confirm"
            and type(value) is bool
            or kind == "owner"
            and (value is None or isinstance(value, str) and bool(value.strip()))
        )
        if not valid:
            if inspect.iscoroutine(value) or inspect.isgenerator(value):
                value.close()
            raise ValidationError(
                "Session admission " + method + " returned an incomplete or invalid result"
            )
        return json.loads(canonical(value)) if kind in {"load", "rows"} else value

    def prepare(self):
        return self._call("prepare", "mutation")

    def prepare_composites(self):
        return self._call("prepare_composites", "mutation")

    def prepare_conversations(self):
        return self._call("prepare_conversations", "mutation")

    def prepare_remote_sessions(self):
        return self._call("prepare_remote_sessions", "mutation")

    def remote_owner(self, *args, **kwargs):
        return self._call("remote_owner", "owner", *args, **kwargs)

    def load(self, *args, **kwargs):
        return self._call("load", "load", *args, **kwargs)

    def load_address(self, *args, **kwargs):
        return self._call("load_address", "load", *args, **kwargs)

    def insert(self, *args, **kwargs):
        return self._call("insert", "mutation", *args, **kwargs)

    def save(self, *args, **kwargs):
        return self._call("save", "mutation", *args, **kwargs)

    def insert_turn(self, *args, **kwargs):
        return self._call("insert_turn", "mutation", *args, **kwargs)

    def turns(self, *args, **kwargs):
        return self._call("turns", "rows", *args, **kwargs)

    def confirmed_result(self, *args, **kwargs):
        return self._call("confirmed_result", "confirm", *args, **kwargs)

    def legacy_owner(self, *args, **kwargs):
        return self._call("legacy_owner", "owner", *args, **kwargs)
