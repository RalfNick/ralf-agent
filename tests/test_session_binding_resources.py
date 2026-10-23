"""Host-authorized Session views preserve backend CAS, scope and page cursors."""

import asyncio
import importlib

import pytest

from relf_agent import BindingCatalog, BindingSelection, InMemoryMemory, Scope
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.recall import RecallQuery


def resource_type():
    try:
        return importlib.import_module("relf_agent.binding_sessions").SessionBindingResource
    except ModuleNotFoundError:
        pytest.fail("Session binding resource implementation is missing")


def test_session_ref_reads_and_appends_selected_backend_with_cas():
    async def run():
        backend = InMemoryMemory(backend_id="selected")
        catalog = BindingCatalog(scope=Scope())
        catalog.register("session", "history", "1", backend)
        view, record = catalog.resolve("session", BindingSelection.ref("history", "1"), Scope())
        assert await view.read(Scope(), "s") == (0, [])
        assert (
            await view.append(Scope(), "s", {"text": "hello"}, expected_revision=0, message_id="m")
            == 1
        )
        assert backend.read(Scope(), "s") == (1, [{"text": "hello"}])
        assert record["resource"] == {"backend_id": "selected", "namespace": None}

    asyncio.run(run())


def test_allowlisted_namespaces_share_client_without_cross_talk_and_keep_cursor_scope():
    async def run():
        backend = InMemoryMemory(backend_id="shared")
        resource = resource_type()(backend, namespaces=("red", "blue"), default_namespace="red")
        catalog = BindingCatalog(scope=Scope())
        catalog.register("session", "history", "1", resource)
        red, _ = catalog.resolve("session", BindingSelection.ref("history", "1"), Scope())
        blue, _ = catalog.resolve(
            "session", BindingSelection.ref("history", "1", selector={"namespace": "blue"}), Scope()
        )
        for i in range(3):
            await red.append(
                Scope(), "same", {"text": f"red-{i}"}, expected_revision=i, message_id=str(i)
            )
        assert await blue.read(Scope(), "same") == (0, [])
        page = await red.read_page(Scope(), "same", RecallQuery(max_items=1, scan_limit=1))
        assert page.items == [{"text": "red-2"}] and page.next_cursor
        with pytest.raises(ValidationError):
            await blue.read_page(
                Scope(), "same", RecallQuery(max_items=1, scan_limit=1, cursor=page.next_cursor)
            )
        assert red.storage_key("same") != blue.storage_key("same")
        assert (await red.read(Scope(), "same"))[0] == 3

    asyncio.run(run())


@pytest.mark.parametrize(
    "selector", [{"namespace": "other"}, {"namespace": None}, {"path": "other"}, {"namespace": ""}]
)
def test_session_selector_is_host_authorized_before_io(selector):
    backend = InMemoryMemory(backend_id="shared")
    resource = resource_type()(backend, namespaces=("red",), default_namespace="red")
    catalog = BindingCatalog(scope=Scope())
    catalog.register("session", "history", "1", resource)
    with pytest.raises((ValidationError, AuthorizationDenied)):
        catalog.resolve("session", BindingSelection.ref("history", "1", selector=selector), Scope())
    assert backend.read(Scope(), "s") == (0, [])


def test_scope_is_fixed_in_view_and_cannot_be_mutated():
    async def run():
        catalog = BindingCatalog(scope=Scope())
        catalog.register("session", "history", "1", InMemoryMemory(backend_id="shared"))
        view, record = catalog.resolve("session", BindingSelection.ref("history", "1"), Scope())
        with pytest.raises(AuthorizationDenied):
            await view.read(Scope("other", "owner"), "s")
        with pytest.raises((AttributeError, TypeError)):
            view.namespace = "other"
        record["resource"]["namespace"] = "other"
        assert (
            catalog.resolve("session", BindingSelection.ref("history", "1"), Scope())[1][
                "resource"
            ]["namespace"]
            is None
        )

    asyncio.run(run())


def test_view_refuses_actual_backend_drift_after_await():
    async def run():
        class Backend(InMemoryMemory):
            async def read(self, scope, session):
                await asyncio.sleep(0)
                self.backend_id = "changed"
                return (0, [])

        catalog = BindingCatalog(scope=Scope())
        catalog.register("session", "history", "1", Backend(backend_id="original"))
        view, _ = catalog.resolve("session", BindingSelection.ref("history", "1"), Scope())
        with pytest.raises(DefinitionMismatch):
            await view.read(Scope(), "s")

    asyncio.run(run())


@pytest.mark.parametrize("namespace", ["", 1, "x" * 129])
def test_invalid_host_namespace_registration_is_rejected(namespace):
    with pytest.raises(ValidationError):
        resource_type()(
            InMemoryMemory(backend_id="shared"),
            namespaces=(namespace,),
            default_namespace=namespace,
        )


def test_selected_view_cannot_be_registered_as_an_unprojected_backend():
    resource = resource_type()(
        InMemoryMemory(backend_id="physical"), namespaces=("red",), default_namespace="red"
    )
    view = resource.select({}, Scope())
    catalog = BindingCatalog(scope=Scope())
    with pytest.raises(ValidationError):
        catalog.register("session", "selected-view", "1", view)
