"""Optional execution-store extensions must not break capability discovery."""

import pytest

from relf_agent import InMemoryMemory, LocalEngine, Runtime, SQLiteStore, ToolRegistry

from .test_extension_contracts import HostCoordinator, StoreAdapter


def test_basic_execution_store_reports_no_durable_session_extension(tmp_path):
    store = StoreAdapter(tmp_path / "port.sqlite")
    memory = InMemoryMemory(backend_id="capabilities-memory")
    with LocalEngine(
        store,
        providers={},
        tools=ToolRegistry(),
        coordinator=HostCoordinator(),
        session_store=memory,
        memory_store=memory,
    ) as engine:
        runtime = Runtime(engine, authority_locator="basic-port")
        capabilities = runtime.capabilities
        assert capabilities["local_hosting"] is True
        assert capabilities["shared_sessions"] is False
        assert capabilities["durable_turns"] is False
        assert capabilities["session_definitions"] == []
        assert capabilities["session_storage"] is None
        assert capabilities["conversation_namespaces"] is False
        assert capabilities["remote_session_definitions"] == []


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, None, True, "5", 6])
def test_session_extensions_are_reported_only_with_the_admission_factory(tmp_path, version):
    store = StoreAdapter(tmp_path / "version-only.sqlite")
    store.session_admission_version = version
    memory = InMemoryMemory(backend_id="version-only-memory")
    with LocalEngine(
        store,
        providers={},
        tools=ToolRegistry(),
        coordinator=HostCoordinator(),
        session_store=memory,
        memory_store=memory,
    ) as engine:
        capabilities = Runtime(engine, authority_locator="version-only").capabilities
        assert capabilities["shared_sessions"] is False
        assert capabilities["session_definitions"] == []
        assert capabilities["conversation_namespaces"] is False
        assert capabilities["remote_session_definitions"] == []


@pytest.mark.parametrize(
    "version,definitions,namespaces,remote",
    [
        (1, ["agent", "sequence"], False, []),
        (2, ["agent", "sequence", "graph", "team", "dynamic"], False, []),
        (3, ["agent", "sequence", "graph", "team", "dynamic"], True, []),
        (4, ["agent", "sequence", "graph", "team", "dynamic"], True, ["agent", "sequence"]),
        (
            5,
            ["agent", "sequence", "graph", "team", "dynamic"],
            True,
            ["agent", "sequence", "graph", "team", "dynamic"],
        ),
        (None, ["agent", "sequence"], False, []),
        (True, ["agent", "sequence"], False, []),
        ("5", ["agent", "sequence"], False, []),
        (6, ["agent", "sequence"], False, []),
    ],
)
def test_sqlite_session_capabilities_keep_the_existing_version_gates(
    tmp_path, version, definitions, namespaces, remote
):
    store = SQLiteStore(tmp_path / "sqlite.sqlite")
    store.session_admission_version = version
    with LocalEngine(store, providers={}, tools=ToolRegistry()) as engine:
        capabilities = Runtime(engine).capabilities
        assert capabilities["shared_sessions"] is True
        assert capabilities["durable_turns"] is True
        assert capabilities["session_storage"] == "colocated-sqlite"
        assert capabilities["session_definitions"] == definitions
        assert capabilities["conversation_namespaces"] is namespaces
        assert capabilities["remote_session_definitions"] == remote
