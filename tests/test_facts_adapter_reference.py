"""Independent durable Facts behavior and the original assembly boundary."""

import asyncio
import importlib
import os
import sqlite3
from dataclasses import asdict, replace

import pytest

from ralf_agent import AgentSpec, ComponentRegistry, RuntimeBuilder, Scope, recommended_profile
from ralf_agent.errors import (
    AuthorizationDenied,
    DefinitionMismatch,
    MemoryBackendError,
    ValidationError,
)
from ralf_agent.memory import memory_call
from ralf_agent.recall import RecallQuery


def reference():
    try:
        return importlib.import_module("ralf_agent.facts_adapter_contract_reference")
    except ModuleNotFoundError:
        pytest.fail("The independent Facts source is missing")


def test_core_cas_detachment_expiry_revival_and_exact_current_inspection(tmp_path):
    api = reference()
    source = api.ReferenceFactsSource(tmp_path / "facts.sqlite")
    store = api.ReferenceSQLiteFactsStore(source)
    managed = api.ReferenceSQLiteManagedFactsStore(source)
    scope = Scope("workspace", "person")
    try:
        assert store.facts(scope, "知識") == []
        assert managed.inspect_fact(scope, "知識", "一") is None
        value = {"nested": [None, {"truth": True}]}
        assert store.put_fact(scope, "知識", "一", value, expected_version=0) == 1
        value["nested"].append(99)
        want = {
            "key": "一",
            "value": {"nested": [None, {"truth": True}]},
            "version": 1,
            "expires_at": None,
        }
        assert store.facts(scope, "知識") == [want]
        read = store.facts(scope, "知識")
        read[0]["value"]["nested"].append(88)
        for version in (0, 2):
            with pytest.raises(ValidationError):
                store.put_fact(scope, "知識", "一", "refused", expected_version=version)
        assert store.facts(scope, "知識") == [want]
        assert store.put_fact(scope, "知識", "一", False, expected_version=1, expires_at=1) == 2
        assert store.facts(scope, "知識") == []
        assert managed.inspect_fact(scope, "知識", "一") == {
            "key": "一",
            "value": False,
            "version": 2,
            "expires_at": 1.0,
        }
        assert store.put_fact(scope, "知識", "一", None, expected_version=2) == 3
        assert store.facts(scope, "知識")[0]["value"] is None
        assert not hasattr(store, "recall") and not hasattr(store, "fact_inspection_version")
        assert type(managed.fact_inspection_version) is int and managed.fact_inspection_version == 1
        original = store.backend_id
        assert source.reopen() is None
        assert store.backend_id == original
    finally:
        descriptor = source._file_descriptor
        source.close()
    assert source._file_descriptor is None
    with pytest.raises(OSError):
        os.fstat(descriptor)
    reopened = api.ReferenceFactsSource(tmp_path / "facts.sqlite")
    try:
        assert api.ReferenceSQLiteFactsStore(reopened).backend_id == original
        assert reopened.facts(scope, "知識")[0]["version"] == 3
    finally:
        reopened.close()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), {"nested": float("-inf")}, object()])
def test_invalid_values_and_versions_leave_durable_facts_unchanged(tmp_path, bad):
    api = reference()
    source = api.ReferenceFactsSource(tmp_path / "facts.sqlite")
    try:
        store = api.ReferenceSQLiteFactsStore(source)
        with pytest.raises(ValidationError):
            store.put_fact(Scope(), "facts", "bad", bad, expected_version=0)
        for version in (True, -1, 0.0):
            with pytest.raises(ValidationError):
                store.put_fact(Scope(), "facts", "bad", None, expected_version=version)
        for expiry in (True, "later", float("inf")):
            with pytest.raises(ValidationError):
                store.put_fact(Scope(), "facts", "bad", None, expected_version=0, expires_at=expiry)
        assert store.facts(Scope(), "facts") == []
        assert source.audit()["write_count"] == 0
    finally:
        source.close()


def test_bounded_recall_progress_metering_bound_cursor_and_snapshot_refusal(tmp_path):
    api = reference()
    source = api.ReferenceFactsSource(tmp_path / "facts.sqlite")
    store = api.ReferenceSQLiteManagedFactsStore(source)
    scope = Scope()
    try:
        for key, value, expiry in [
            ("expired", 0, 1),
            ("large", "x" * 300, None),
            ("one", "hit", None),
            ("two", "hit", None),
        ]:
            store.put_fact(scope, "n", key, value, expected_version=0, expires_at=expiry)
        query = RecallQuery(max_items=1, max_chars=150, scan_limit=2)
        page = store.recall(scope, "n", query)
        assert page.items == [] and page.scanned == page.skipped == 2
        assert page.used_chars == 2 and page.next_cursor and page.backend_bounded
        second = store.recall(scope, "n", replace(query, cursor=page.next_cursor))
        assert [fact["key"] for fact in second.items] == ["one"]
        assert second.scanned == 1 and second.skipped == 0 and second.next_cursor
        assert second.used_chars == len(
            '[{"expires_at":null,"key":"one","value":"hit","version":1}]'
        )
        for other_scope, namespace, changed in [
            (Scope(principal="other"), "n", query),
            (scope, "other", query),
            (scope, "n", replace(query, text="hit")),
            (scope, "n", replace(query, max_chars=151)),
        ]:
            with pytest.raises(ValidationError):
                store.recall(other_scope, namespace, replace(changed, cursor=page.next_cursor))
        store.put_fact(scope, "n", "one", "changed", expected_version=1)
        with pytest.raises(ValidationError):
            store.recall(scope, "n", replace(query, cursor=page.next_cursor))
        assert source.audit()["scanned"] >= 3
    finally:
        source.close()


def test_validation_refuses_changed_deleted_expired_and_value_tampered_references(tmp_path):
    api = reference()
    source = api.ReferenceFactsSource(tmp_path / "facts.sqlite")
    store = api.ReferenceSQLiteManagedFactsStore(source)
    scope = Scope()
    try:
        store.put_fact(scope, "n", "k", {"real": 1}, expected_version=0)
        facts = store.facts(scope, "n")
        assert store.validate_facts(scope, "n", facts) is None
        altered = [{**facts[0], "value": {"real": 2}}]
        with pytest.raises(ValidationError):
            store.validate_facts(scope, "n", altered)
        for other in (Scope(principal="other"), Scope(workspace="other")):
            with pytest.raises(ValidationError):
                store.validate_facts(other, "n", facts)
        for mode in ("expire", "change", "delete"):
            assert source.mutate_fact(scope, "n", "k", mode) is None
            with pytest.raises(ValidationError):
                store.validate_facts(scope, "n", facts)
        assert store.inspect_fact(scope, "n", "k") is None
    finally:
        source.close()


@pytest.mark.parametrize(
    "operation", ["facts", "put_fact", "recall", "validate_facts", "inspect_fact"]
)
def test_live_physical_file_replacement_is_refused_without_writing_replacement(tmp_path, operation):
    api = reference()
    source = api.ReferenceFactsSource(tmp_path / "facts.sqlite")
    store = api.ReferenceSQLiteManagedFactsStore(source)
    alternate = api.ReferenceFactsSource(tmp_path / "alternate.sqlite")
    alternate.close()
    os.replace(alternate.path, source.path)
    with sqlite3.connect(source.path) as connection:
        before = list(connection.execute("SELECT kind,count FROM audit"))
    try:
        args = {
            "facts": (Scope(), "n"),
            "put_fact": (Scope(), "n", "k", 1),
            "recall": (Scope(), "n", RecallQuery()),
            "validate_facts": (Scope(), "n", []),
            "inspect_fact": (Scope(), "n", "k"),
        }[operation]
        with pytest.raises(DefinitionMismatch):
            getattr(store, operation)(
                *args, **({"expected_version": 0} if operation == "put_fact" else {})
            )
    finally:
        source.close()
    with sqlite3.connect(source.path) as connection:
        assert list(connection.execute("SELECT kind,count FROM audit")) == before


def test_dataset_uuid_edit_on_original_file_is_refused(tmp_path):
    api = reference()
    source = api.ReferenceFactsSource(tmp_path / "facts.sqlite")
    try:
        with sqlite3.connect(source.path) as connection:
            connection.execute("UPDATE facts_resource SET dataset_id='replacement'")
        with pytest.raises(DefinitionMismatch):
            source.facts(Scope(), "n")
    finally:
        source.close()


def test_invalid_core_addresses_are_domain_errors_before_any_accepted_write(tmp_path):
    api = reference()
    source = api.ReferenceFactsSource(tmp_path / "facts.sqlite")
    store = api.ReferenceSQLiteFactsStore(source)
    try:
        for scope, namespace, key in [
            (object(), "n", "k"),
            (Scope(), None, "k"),
            (Scope(), "", "k"),
            (Scope(), "n", ""),
            (Scope(), "n", None),
            (Scope(), "n" * 129, "k"),
        ]:
            with pytest.raises(ValidationError):
                store.put_fact(scope, namespace, key, None, expected_version=0)
        assert source.audit()["write_count"] == 0
    finally:
        source.close()


def test_partial_fault_preserves_command_binding_and_first_observation_only(tmp_path):
    api = reference()
    source = api.ReferenceFactsSource(tmp_path / "facts.sqlite")
    store = api.ReferenceSQLiteManagedFactsStore(source)
    store._fault = "put-after-first"
    try:
        assert store.put_fact(Scope(), "n:commands", "command", "bound", expected_version=0) == 1
        assert store.put_fact(Scope(), "n", "first", "accepted", expected_version=0) == 1
        with pytest.raises(ConnectionError):
            store.put_fact(Scope(), "n", "second", "refused", expected_version=0)
        assert store.facts(Scope(), "n") == [
            {"key": "first", "value": "accepted", "version": 1, "expires_at": None}
        ]
        assert source.audit()["write_count"] == 2
    finally:
        source.close()


def test_fixture_full_eight_addresses_real_faults_mutations_and_suspended_put(tmp_path):
    async def scenario():
        session = reference().offline_facts_fixture().prepare("F03", tmp_path)
        try:
            assert len(session.addresses) == 8
            assert {
                (a.scope.workspace, a.scope.principal, a.namespace) for a in session.addresses
            } == {
                (w, p, n)
                for w in ("contract-alpha", "contract-beta")
                for p in ("author-a", "author-b")
                for n in ("first", "second")
            }
            for a in session.addresses:
                value = {"scope": asdict(a.scope), "namespace": a.namespace}
                assert (
                    await memory_call(
                        session.store.put_fact,
                        a.scope,
                        a.namespace,
                        "same",
                        value,
                        expected_version=0,
                    )
                    == 1
                )
            for a in session.addresses:
                assert (await memory_call(session.store.facts, a.scope, a.namespace))[0][
                    "value"
                ] == {"scope": asdict(a.scope), "namespace": a.namespace}
            a = session.addresses[0]
            for kind, error in [
                ("backend-error", MemoryBackendError),
                ("authorization-denied", AuthorizationDenied),
                ("backend-swap", DefinitionMismatch),
            ]:
                assert session.inject_fault(kind) is None
                with pytest.raises(error):
                    await memory_call(session.store.facts, a.scope, a.namespace)
                assert session.inject_fault("reset") is None
            assert session.inject_fault("put-ack-lost") is None
            with pytest.raises(MemoryBackendError):
                await memory_call(
                    session.store.put_fact,
                    a.scope,
                    a.namespace,
                    "accepted",
                    None,
                    expected_version=0,
                )
            assert (
                await memory_call(session.store.inspect_fact, a.scope, a.namespace, "accepted")
            )["version"] == 1
            gate = session.pause("put_fact")
            task = asyncio.create_task(
                memory_call(
                    session.store.put_fact, a.scope, a.namespace, "paused", 2, expected_version=0
                )
            )
            assert await gate.wait_entered() is None
            assert not task.done()
            assert gate.release() is None
            assert await task == 1
            assert session.mutate_fact(a.scope, a.namespace, "paused", "delete") is None
            assert session.reopen() is None
        finally:
            for resource in session.resources:
                await resource.resource.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("owned", [False, True])
def test_factory_registration_is_lazy_and_original_buildcontext_owns_only_requested_source(
    tmp_path, asynchronous, owned
):
    api = reference()
    path = tmp_path / "facts.sqlite"
    source = None if owned else api.ReferenceFactsSource(path)
    registry = ComponentRegistry()
    api.register_facts_reference_components(
        registry, source, asynchronous=asynchronous, owned=owned
    )
    if owned:
        assert not path.exists()
    profile = recommended_profile(
        "local-basic",
        name="reference",
        provider={"adapter": "external-facts-reader", "config": {"path": str(path)}},
        components={
            "memory_store": {
                "adapter": "external-facts",
                "config": {"path": str(path), "managed": True},
            },
            "context_assembler": {"adapter": "default"},
        },
    )

    async def scenario():
        builder = RuntimeBuilder(registry)
        instance = (
            await builder.abuild(profile, tmp_path / "runs.sqlite")
            if asynchronous
            else builder.build(profile, tmp_path / "runs.sqlite")
        )
        actual_source = instance.memory._original_source
        assert instance.providers["default"].source is actual_source
        try:
            await memory_call(
                instance.memory.put_fact,
                instance.scope,
                "reader",
                "seed",
                "actual",
                expected_version=0,
            )
            handle = instance.submit(
                AgentSpec("reader", "Read actual facts"), "input", command_id="read", budget=5
            )
            done = await instance.drive(handle.run_id)
            assert done.state == "succeeded" and done.result["facts"][0]["value"] == "actual"
        finally:
            await instance.aclose()
        assert actual_source._closed is owned
        if not owned:
            assert source.facts(Scope(), "reader")[0]["value"] == "actual"
            source.close()

    asyncio.run(scenario())
