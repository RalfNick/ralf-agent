"""Persistent member identity must be independent of temporary Turn Run IDs."""

from dataclasses import replace

import pytest

from relf_agent import SessionKey, SessionRef
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.types import digest


def root():
    key = SessionKey("app", "owner", digest("actual namespace/dataset"), "root", "chat")
    return SessionRef(key, digest("original coordination"), 1, digest("definition"))


def topology():
    from relf_agent.temporal_session_topology import CompositeSessionTopology

    return CompositeSessionTopology()


def test_root_and_member_addresses_are_distinct_stable_and_structured():
    layout, ref = topology(), root()
    arguments = (ref, ("graph", "nodes", "research"), digest("research-agent"))
    first = layout.member_address(*arguments, namespace="private")
    assert first == layout.member_address(*arguments, namespace="private")
    assert layout.root_address(ref) == ref.key.storage_key != first
    assert first != layout.member_address(
        ref, ("graph", "nodes", "research/answer"), arguments[2], namespace="private"
    )
    assert first != layout.member_address(
        ref, ("graph", "nodes/research"), arguments[2], namespace="private"
    )
    assert first != layout.member_address(
        ref, arguments[1], digest("another-agent"), namespace="private"
    )
    assert first != layout.member_address(
        replace(ref, binding_revision=2), arguments[1], arguments[2], namespace="private"
    )
    assert first != layout.member_address(ref, arguments[1], arguments[2], namespace="other")


def test_member_identity_includes_original_scope_and_root_resource():
    ref, layout = root(), topology()
    arguments = (("team", "members", "writer"), digest("agent"))
    original = layout.member_address(ref, *arguments)
    for key in [
        replace(ref.key, principal="other"),
        replace(ref.key, resource_id=digest("other dataset")),
    ]:
        assert original != layout.member_address(replace(ref, key=key), *arguments)


@pytest.mark.parametrize(
    "path", [None, [], [""], [True], [1], "graph/nodes/research", ["x" * 257], ["x"] * 65]
)
def test_invalid_member_paths_are_rejected(path):
    with pytest.raises(ValidationError):
        topology().member_address(root(), path, digest("agent"))


def test_native_topology_keeps_existing_private_and_root_addresses():
    from relf_agent.temporal_session_data_state import private_address, session_storage_key
    from relf_agent.temporal_session_topology import NativeSessionTopology

    layout = NativeSessionTopology()
    assert layout.root_address(root()) == root().key.storage_key
    assert layout.run_address("original-run", 2, namespace="private") == session_storage_key(
        "private", private_address("original-run", 2)
    )


def test_separator_in_atom_does_not_alias_nested_member():
    ref, layout = root(), topology()
    assert layout.member_address(ref, ("a/b",), digest("agent")) != layout.member_address(
        ref, ("a", "b"), digest("agent")
    )


def registration(value):
    from relf_agent.temporal_session_topology import SessionTopologyRegistration

    return SessionTopologyRegistration(value)


class CustomTopology:
    def __init__(self, suffix="custom"):
        self.suffix = suffix

    @property
    def identity(self):
        return {"kind": "custom-topology", "version": "1", "suffix": self.suffix}

    def root_address(self, session):
        return session.key.storage_key

    def member_address(self, session, path, definition_digest, *, namespace=None):
        from relf_agent.temporal_session_data_state import session_storage_key

        base = topology().member_address(session, path, definition_digest)
        return session_storage_key(namespace, base + ":" + self.suffix)


def test_registered_custom_policy_keeps_generation_and_namespace():
    selected = registration(CustomTopology())
    ref = root()
    address = selected.member_address(ref, ("team", "writer"), digest("writer"), namespace="p")
    assert address == CustomTopology().member_address(
        ref, ("team", "writer"), digest("writer"), namespace="p"
    )
    assert address != selected.member_address(
        ref, ("team", "reader"), digest("writer"), namespace="p"
    )
    assert selected.root_address(ref) == ref.key.storage_key
    identity = selected.identity
    identity["policy"]["suffix"] = "edited copy"
    assert selected.identity["policy"]["suffix"] == "custom"


def test_registration_refuses_configuration_and_method_drift():
    value = CustomTopology()
    selected = registration(value)
    value.suffix = "changed"
    with pytest.raises(DefinitionMismatch):
        selected.member_address(root(), ("writer",), digest("agent"))
    value.suffix = "custom"
    value.member_address = lambda *args, **kwargs: "fake"
    with pytest.raises(DefinitionMismatch):
        selected.root_address(root())


@pytest.mark.parametrize("result", [None, True, "chat", "x" * 2049])
def test_registered_proposal_cannot_alias_root_or_another_generation(result):
    class Invalid(CustomTopology):
        def member_address(self, *args, **kwargs):
            return result

    selected = registration(Invalid())
    with pytest.raises(ValidationError):
        selected.member_address(root(), ("writer",), digest("agent"))


def test_registered_proposal_cannot_escape_namespace():
    class Invalid(CustomTopology):
        def member_address(self, session, path, definition_digest, *, namespace=None):
            return super().member_address(session, path, definition_digest, namespace="other")

    selected = registration(Invalid())
    with pytest.raises(ValidationError):
        selected.member_address(root(), ("writer",), digest("agent"), namespace="private")


def test_registration_rejects_async_and_lazy_policies():
    class Async(CustomTopology):
        async def root_address(self, session):
            return session.key.storage_key

    with pytest.raises(ValidationError):
        registration(Async())

    class Lazy(CustomTopology):
        def root_address(self, session):
            return (item for item in [session.key.storage_key])

    selected = registration(Lazy())
    with pytest.raises(ValidationError):
        selected.root_address(root())


@pytest.mark.parametrize("namespace", [True, 1, "", "x" * 129])
def test_invalid_selected_member_namespace_refuses_before_policy(namespace):
    selected = registration(CustomTopology())
    with pytest.raises(ValidationError):
        selected.member_address(root(), ("writer",), digest("agent"), namespace=namespace)


def test_public_topology_ports_are_importable_from_package():
    from relf_agent import CompositeSessionTopology, NativeSessionTopology, SessionTopology

    assert CompositeSessionTopology().root_address(root()) == root().key.storage_key
    assert NativeSessionTopology().root_address(root()) == root().key.storage_key
    assert callable(SessionTopology.member_address)
