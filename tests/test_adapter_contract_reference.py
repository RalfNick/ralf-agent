"""An independently implemented persistent structural Retriever, not a wrapper."""

import asyncio
import importlib
import inspect
import os
import sqlite3
from dataclasses import asdict, replace

import pytest

from relf_agent import KnowledgeContext, Scope
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.retrieval import RetrievalQuery
from relf_agent.types import canonical


def reference():
    try:
        return importlib.import_module("relf_agent.adapter_contract_reference")
    except ModuleNotFoundError:
        pytest.fail("The independent installed adapter reference is missing")


def test_reference_reads_its_own_persistent_source_and_honors_scoped_character_budget(tmp_path):
    api = reference()
    scope = Scope("project", "person")
    source = api.ReferenceKnowledgeSource(tmp_path / "source.sqlite")
    source.put(scope, "manuals", "cache", "cache timeout inspect pool", source_uri="local://cache")
    source.put(scope, "private", "cache", "private cache secret")
    source.put(Scope("project", "other"), "manuals", "cache", "foreign cache secret")
    adapter = api.ReferenceSQLiteRetriever(source)
    query = RetrievalQuery("cache", limit=1, max_chars=2000)
    found = adapter.retrieve(scope, "manuals", query)
    assert len(found.items) == 1 and found.items[0].text == "cache timeout inspect pool"
    assert found.used_chars == len(canonical([asdict(item) for item in found.items]))
    assert adapter.validate(scope, "manuals", found.items) is None
    assert adapter.retrieve(scope, "manuals", replace(query, max_chars=2)).items == ()
    assert adapter.retrieve(scope, "manuals", RetrievalQuery("absent")).used_chars == 0
    assert source.audit()["retrieval"] == 3
    source.close()
    reopened = api.ReferenceKnowledgeSource(tmp_path / "source.sqlite")
    again = api.ReferenceSQLiteRetriever(reopened).retrieve(scope, "manuals", query)
    assert again.items == found.items
    reopened.close()


@pytest.mark.parametrize("change", ["text", "metadata", "uri", "version", "scope", "delete"])
def test_reference_reloads_actual_source_to_reject_stale_or_forged_chunks(tmp_path, change):
    api = reference()
    scope = Scope()
    source = api.ReferenceKnowledgeSource(tmp_path / "source.sqlite")
    source.put(scope, "manuals", "cache", "cache", source_uri="local://cache", metadata={"v": 1})
    adapter = api.ReferenceSQLiteRetriever(source)
    item = adapter.retrieve(scope, "manuals", RetrievalQuery("cache")).items[0]
    if change == "delete":
        source.delete(scope, "manuals", "cache")
        submitted = item
    elif change == "version":
        source.put(
            scope, "manuals", "cache", "cache", source_uri="local://cache", metadata={"v": 1}
        )
        submitted = item
    else:
        field, value = {
            "text": ("text", "fabricated cache"),
            "metadata": ("metadata", {"v": 2}),
            "uri": ("source_uri", "local://fake"),
            "scope": ("scope", Scope(principal="foreign")),
        }[change]
        submitted = replace(item, **{field: value})
    with pytest.raises(ValidationError):
        adapter.validate(scope, "manuals", (submitted,))
    source.close()


def test_reference_detects_its_actual_resource_path_change_without_identity_change(tmp_path):
    api = reference()
    source = api.ReferenceKnowledgeSource(tmp_path / "source.sqlite")
    source.put(Scope(), "manuals", "cache", "cache")
    adapter = api.ReferenceSQLiteRetriever(source)
    identity = adapter.identity
    source.path = str(tmp_path / "other.sqlite")
    assert adapter.identity == identity
    with pytest.raises(DefinitionMismatch):
        adapter.retrieve(Scope(), "manuals", RetrievalQuery("cache"))
    source.path = adapter.source_path
    source.close()


@pytest.mark.parametrize("replacement", ["replace", "delete-and-recreate"])
@pytest.mark.parametrize("operation", ["retrieve", "validate"])
def test_reference_rejects_a_different_real_database_at_the_original_path(
    tmp_path, replacement, operation
):
    api = reference()
    path = tmp_path / "source.sqlite"
    source = api.ReferenceKnowledgeSource(path)
    source.put(Scope(), "manuals", "cache", "cache original", source_uri="source://original")
    adapter = api.ReferenceSQLiteRetriever(source)
    original = adapter.retrieve(Scope(), "manuals", RetrievalQuery("cache"))
    descriptor = source._file_descriptor
    identity = adapter.identity
    alternate = api.ReferenceKnowledgeSource(tmp_path / "replacement.sqlite")
    alternate.put(
        Scope(), "manuals", "cache", "cache replacement", source_uri="source://replacement"
    )
    alternate.close()
    if replacement == "delete-and-recreate":
        path.unlink()
    os.replace(alternate.path, path)
    with sqlite3.connect(path) as connection:
        replacement_audit = list(connection.execute("SELECT kind,count FROM audit"))
    assert adapter.identity == identity
    try:
        with pytest.raises(DefinitionMismatch):
            if operation == "retrieve":
                adapter.retrieve(Scope(), "manuals", RetrievalQuery("cache"))
            else:
                adapter.validate(Scope(), "manuals", original.items)
    finally:
        source.close()
    assert source._closed
    assert source._file_descriptor is None
    with pytest.raises(OSError):
        os.fstat(descriptor)
    with pytest.raises(DefinitionMismatch):
        source.audit()
    with sqlite3.connect(path) as connection:
        assert list(connection.execute("SELECT kind,count FROM audit")) == replacement_audit
        assert connection.execute("SELECT text,source_uri FROM sources").fetchone() == (
            "cache replacement",
            "source://replacement",
        )


@pytest.mark.parametrize("phase", ["retrieve", "validate"])
def test_reference_refuses_actual_file_replacement_during_suspended_original_io(tmp_path, phase):
    from relf_agent.knowledge_adapter_contract import KnowledgeContractSession

    api = reference()

    async def scenario():
        session = api.offline_knowledge_fixture().prepare("K09", tmp_path)
        assert type(session) is KnowledgeContractSession
        original = session.sources[0]
        context = KnowledgeContext(session.retriever, namespace=original.namespace)
        references = await context.references(original.scope, original.query.text)
        pause = session.pause(phase)
        task = asyncio.create_task(
            context.references(original.scope, original.query.text)
            if phase == "retrieve"
            else context.validate(original.scope, references)
        )
        await pause.wait_entered()
        replacement = api.ReferenceKnowledgeSource(tmp_path / "replacement.sqlite")
        replacement.put(original.scope, original.namespace, "cache", "cache replacement")
        replacement.close()
        os.replace(replacement.path, session.retriever.source.path)
        pause.release()
        try:
            with pytest.raises(DefinitionMismatch):
                await task
        finally:
            for resource in session.resources:
                resource.resource.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["put", "read", "session"])
def test_partial_offline_fixture_preparation_closes_its_real_source_before_raising(
    tmp_path, monkeypatch, phase
):
    import relf_agent.knowledge_adapter_contract as contracts

    api = reference()
    created = []
    original_init = api.ReferenceKnowledgeSource.__init__

    def initialize(source, path):
        original_init(source, path)
        created.append((source, source._file_descriptor))

    def fail(*arguments, **options):
        raise ValidationError("Private preparation failure")

    monkeypatch.setattr(api.ReferenceKnowledgeSource, "__init__", initialize)
    if phase == "session":
        monkeypatch.setattr(contracts, "KnowledgeContractSession", fail)
    else:
        monkeypatch.setattr(api.ReferenceKnowledgeSource, phase, fail)
    try:
        with pytest.raises(ValidationError):
            api.offline_knowledge_fixture().prepare("K01", tmp_path)
        assert len(created) == 1
        source, descriptor = created[0]
        assert source._closed and source._file_descriptor is None
        with pytest.raises(OSError):
            os.fstat(descriptor)
    finally:
        for source, _ in created:
            source.close()


def test_source_releases_actual_file_handle_when_close_audit_has_a_real_sqlite_error(tmp_path):
    api = reference()
    source = api.ReferenceKnowledgeSource(tmp_path / "source.sqlite")
    descriptor = source._file_descriptor

    def failing_audit(kind):
        raise sqlite3.OperationalError("Private audit I/O failure")

    source.count = failing_audit
    try:
        with pytest.raises(sqlite3.OperationalError):
            source.close()
        assert source._closed and source._file_descriptor is None
        with pytest.raises(OSError):
            os.fstat(descriptor)
        source.close()
    finally:
        if not source._closed:
            source.count = lambda kind: None
            source.close()


@pytest.mark.parametrize("asynchronous", [False, True])
def test_reference_is_structural_and_context_uses_real_references(tmp_path, asynchronous):
    api = reference()
    source = api.ReferenceKnowledgeSource(tmp_path / "source.sqlite")
    source.put(
        Scope(), "manuals", "cache", "cache timeout inspect pool", source_uri="local://cache"
    )
    cls = api.AsyncReferenceSQLiteRetriever if asynchronous else api.ReferenceSQLiteRetriever
    adapter = cls(source)
    assert not any("relf_agent.retrieval" == base.__module__ for base in cls.__mro__)
    implementation = inspect.getsource(cls) + inspect.getsource(api.ReferenceKnowledgeSource)
    assert "LexicalRetriever(" not in implementation
    assert "KnowledgeStore(" not in implementation

    async def exercise():
        context = KnowledgeContext(adapter, namespace="manuals")
        references = await context.references(Scope(), "cache")
        assert references[0]["value"]["text"] == "cache timeout inspect pool"
        assert await context.validate(Scope(), references) is None

    asyncio.run(exercise())
    source.close()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("owned", [False, True])
def test_registered_reference_factory_completely_replaces_semantic_default_and_owns_explicitly(
    tmp_path, asynchronous, owned
):
    from relf_agent import (
        AgentSpec,
        ComponentRegistry,
        Runtime,
        RuntimeBuilder,
        recommended_profile,
    )

    api = reference()
    source = api.ReferenceKnowledgeSource(tmp_path / "source.sqlite")
    source.put(
        Scope(), "manuals", "cache", "cache timeout inspect pool", source_uri="local://cache"
    )
    register = getattr(api, "register_reference_components", None)
    assert callable(register), "Installed reference requires its actual configurable factories"
    registry = ComponentRegistry()
    register(registry, source, asynchronous=asynchronous, owned=owned)
    profile = recommended_profile(
        "semantic-knowledge",
        version="2",
        provider={"adapter": "external-reference-reader"},
        components={
            "knowledge": {"adapter": "external-reference", "config": {"namespace": "manuals"}}
        },
    )

    async def exercise():
        builder = RuntimeBuilder(registry, base_dir=tmp_path)
        instance = (
            await builder.abuild(profile, tmp_path / "runs.sqlite")
            if asynchronous
            else builder.build(profile, tmp_path / "runs.sqlite")
        )
        async with Runtime(instance, owned=True) as runtime:
            handle = await runtime.submit(
                AgentSpec("reader", "Answer with original references"), "cache", command_id="cache"
            )
            done = await handle.wait(wait_timeout=5)
            assert done.snapshot.state == "succeeded", done.snapshot.error
            assert done.snapshot.result["answer"] == "cache timeout inspect pool"
            assert done.snapshot.result["sources"][0]["source_uri"] == "local://cache"
            assert source.audit()["model_calls"] == 1
        assert source.audit()["close_calls"] == int(owned)

    try:
        asyncio.run(exercise())
    finally:
        source.close()


@pytest.mark.parametrize("case_id", [f"K{number:02}" for number in range(1, 13)])
def test_explicit_independent_offline_fixture_satisfies_original_black_box_case(tmp_path, case_id):
    from relf_agent.knowledge_adapter_contract import run_knowledge_case

    actual = asyncio.run(
        run_knowledge_case(case_id, reference().offline_knowledge_fixture(), tmp_path)
    )
    assert actual.status == "passed", actual.to_dict()
