"""Pure Session address proposals; original Histories retain admission authority."""

import copy
import json
from typing import Protocol

from .component_fingerprint import executable_digest
from .errors import DefinitionMismatch, ValidationError
from .session_types import SessionRef, sha
from .temporal_session_data_state import private_address, session_storage_key
from .types import digest


class SessionTopology(Protocol):
    """A synchronous address policy, without clients, I/O or execution ownership."""

    @property
    def identity(self) -> dict: ...

    def root_address(self, session: SessionRef) -> str: ...

    def member_address(
        self, session: SessionRef, path: tuple[str, ...], definition_digest: str, *, namespace=None
    ) -> str: ...


def _root(session):
    if not isinstance(session, SessionRef):
        raise ValidationError("Session topology requires an original SessionRef")
    return SessionRef.from_dict(session.to_dict())


def _member(session, path, definition_digest, namespace):
    session = _root(session)
    if (
        type(path) not in {tuple, list}
        or not 1 <= len(path) <= 64
        or any(type(atom) is not str or not atom.strip() or len(atom) > 256 for atom in path)
    ):
        raise ValidationError("Member path requires 1 to 64 bounded nonempty string atoms")
    sha(definition_digest)
    if namespace is not None and (
        type(namespace) is not str or not namespace.strip() or len(namespace) > 128
    ):
        raise ValidationError("Member namespace requires 1 to 128 characters or None")
    return session, tuple(path)


class NativeSessionTopology:
    """Legacy native/sequence addresses, unchanged for existing releases."""

    @property
    def identity(self):
        return {"kind": "temporal-native-session-topology", "version": "1"}

    def root_address(self, session):
        return _root(session).key.storage_key

    def run_address(self, run_id, node, *, namespace=None):
        if namespace is not None and (
            type(namespace) is not str or not namespace.strip() or len(namespace) > 128
        ):
            raise ValidationError("Member namespace requires 1 to 128 characters or None")
        return session_storage_key(namespace, private_address(run_id, node))


class CompositeSessionTopology:
    """Stable private member addresses across Turns, forked by idle rebind."""

    @property
    def identity(self):
        return {"kind": "temporal-composite-session-topology", "version": "1"}

    def root_address(self, session):
        return _root(session).key.storage_key

    def member_address(self, session, path, definition_digest, *, namespace=None):
        session, path = _member(session, path, definition_digest, namespace)
        logical_id = "ralf-temporal-member-v1:" + digest(
            [session.key.to_dict(), session.binding_revision, list(path), definition_digest]
        )
        return session_storage_key(namespace, logical_id)


class SessionTopologyRegistration:
    """Fixed borrowed pure proposal port, with mandatory lineage/namespace sealing.

    Custom policies may add a bounded routing suffix to the default member ID.
    They cannot remove the original lineage, rewrite the root or grant membership.
    The original History still validates ancestry and resource selection before I/O.
    """

    def __init__(self, policy):
        from .task_controls import _binding

        self.policy = policy
        self._owner = policy
        self._methods = {
            name: _binding(getattr(policy, name, None))
            for name in ("root_address", "member_address")
        }
        self._identity = self._capture()

    def _capture(self):
        from .temporal_activities import component_identity

        methods = ("root_address", "member_address")
        return {
            "version": 1,
            "policy": component_identity(self.policy, methods, synchronous=True),
            "implementation": {
                name: executable_digest(getattr(self.policy, name)) for name in methods
            },
        }

    def check(self):
        from .task_controls import _binding

        if self.policy is not self._owner or any(
            _binding(getattr(self.policy, name, None)) != method
            for name, method in self._methods.items()
        ):
            raise DefinitionMismatch("Temporal Session topology method or owner changed")
        if self._capture() != self._identity:
            raise DefinitionMismatch("Temporal Session topology configuration changed")

    @property
    def identity(self):
        self.check()
        return copy.deepcopy(self._identity)

    def _call(self, name, *args, **kwargs):
        from .temporal_activities import _close_lazy

        self.check()
        original = digest([args[0].to_dict(), list(args[1:]), kwargs])
        supplied = copy.deepcopy(args)
        result = getattr(self.policy, name)(*supplied, **kwargs)
        self.check()
        if (
            type(result) is not str
            or not result.strip()
            or len(result) > 1024
            or digest([supplied[0].to_dict(), list(supplied[1:]), kwargs]) != original
        ):
            _close_lazy(result)
            raise ValidationError("Session topology must return a bounded completed address")
        return result

    def root_address(self, session):
        session = _root(session)
        result = self._call("root_address", session)
        if result != session.key.storage_key:
            raise ValidationError("Session topology cannot rewrite the original root address")
        return result

    def member_address(self, session, path, definition_digest, *, namespace=None):
        session, path = _member(session, path, definition_digest, namespace)
        result = self._call("member_address", session, path, definition_digest, namespace=namespace)
        return seal_member_address(session, path, definition_digest, result, namespace=namespace)


def seal_member_address(session, path, definition_digest, result, *, namespace=None):
    """Pure mandatory lineage seal, also enforced when History adopts a proposal."""
    session, path = _member(session, path, definition_digest, namespace)
    if type(result) is not str or len(result) > 1024:
        raise ValidationError("Session topology requires a bounded completed address")
    base = CompositeSessionTopology().member_address(session, path, definition_digest)
    logical_id = result
    if namespace is not None:
        try:
            selected, logical_id = json.loads(result.removeprefix("ralf-session-v1:"))
        except (TypeError, ValueError):
            raise ValidationError("Session topology escaped selected namespace") from None
        if selected != namespace:
            raise ValidationError("Session topology escaped selected namespace")
    if (
        type(logical_id) is not str
        or not (
            logical_id == base
            or logical_id.startswith(base + ":")
            and 1 <= len(logical_id) - len(base) - 1 <= 128
        )
        or result != session_storage_key(namespace, logical_id)
    ):
        raise ValidationError("Session topology removed original member lineage")
    return result
