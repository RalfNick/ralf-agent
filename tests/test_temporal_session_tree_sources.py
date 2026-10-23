"""A composite root must use its host root source, never an inferred member."""

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    InMemoryMemory,
    Scope,
    SessionBindingResource,
    TeamSpec,
    ToolRegistry,
)
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_bindings import effective_manifest, normalize_request
from relf_agent.types import digest, submission_request

from .test_temporal_sessions import Provider


def setup(*, root=True):
    scope = Scope()
    root_store, writer_store, reader_store = InMemoryMemory(), InMemoryMemory(), InMemoryMemory()
    catalog = BindingCatalog(scope=scope)
    catalog.register(
        "session",
        "writer",
        "1",
        SessionBindingResource(writer_store, namespaces=("write",), default_namespace="write"),
    )
    catalog.register(
        "session",
        "reader",
        "1",
        SessionBindingResource(reader_store, namespaces=("read",), default_namespace="read"),
    )
    host = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        enable_sessions=True,
        session_store=SessionBindingResource(
            root_store, namespaces=("chat",), default_namespace="chat"
        )
        if root
        else None,
        session_writes=True,
        binding_catalog=catalog,
    )
    definition = TeamSpec(
        "team",
        {
            "writer": AgentSpec("writer", "Write"),
            "reader": AgentSpec("reader", "Read"),
            "disabled": AgentSpec("disabled", "Answer"),
        },
    )
    request = normalize_request(
        submission_request(
            BoundDefinition(
                definition,
                {
                    "team/members/writer": AgentBindingDescriptor(
                        session=BindingSelection.ref("writer", "1")
                    ),
                    "team/members/reader": AgentBindingDescriptor(
                        session=BindingSelection.ref("reader", "1")
                    ),
                    "team/members/disabled": AgentBindingDescriptor(
                        session=BindingSelection.disabled()
                    ),
                },
            ),
            None,
        )
    )
    return host, request, (root_store, writer_store, reader_store)


def root_source(manifest):
    from relf_agent.temporal_session_tree import root_source

    return root_source(manifest)


def test_root_source_uses_original_host_dataset_independent_of_member_selection():
    host, request, stores = setup()
    manifest = host.orchestration_release
    root = root_source(manifest)
    assert root["namespace"] == "chat"
    assert root["dataset_id"] == digest(["ralf-session-dataset-v1", stores[0].session_dataset_id])
    assert root["physical"] == manifest["session_data"]["physical"]
    for name, namespace, backend in [("writer", "write", stores[1]), ("reader", "read", stores[2])]:
        selected = effective_manifest(manifest, request["agent_bindings"]["team/members/" + name])
        member = selected["session_data"]
        assert member["namespace"] == namespace
        member_dataset = manifest["session_save_protocol"]["dataset_ids"][
            digest(member["physical"])
        ]
        assert member_dataset == digest(["ralf-session-dataset-v1", backend.session_dataset_id])
        assert member_dataset != root["dataset_id"]
    disabled = effective_manifest(manifest, request["agent_bindings"]["team/members/disabled"])
    assert root_source(disabled) is None
    assert root_source(manifest) == root


def test_history_only_root_with_external_private_members_is_not_inferred():
    host, _, _ = setup(root=False)
    manifest = host.orchestration_release
    assert len(manifest["session_save_protocol"]["dataset_ids"]) == 2
    assert root_source(manifest) is None


@pytest.mark.parametrize("damage", ["dataset", "port", "namespace"])
def test_missing_or_escaped_original_root_resource_is_refused(damage):
    host, _, _ = setup()
    manifest = host.orchestration_release
    key = digest(manifest["session_data"]["physical"])
    if damage == "dataset":
        manifest["session_save_protocol"]["dataset_ids"][key] = "same-name-is-not-a-dataset"
    elif damage == "port":
        del manifest["session_save_protocol"]["dataset_ports"][key]
    else:
        manifest["session_data"]["namespace"] = "ungranted"
    with pytest.raises(DefinitionMismatch):
        root_source(manifest)


def test_tree_source_helper_does_not_open_unsupported_advanced_execution():
    from relf_agent.errors import ValidationError
    from relf_agent.temporal_state import validate_request

    host, request, _ = setup()
    assert root_source(host.orchestration_release) is not None
    with pytest.raises(ValidationError, match="not implemented"):
        validate_request(request, host.orchestration_release)
