"""Final review regressions: delegated identities and lossless bounded provenance pages."""

import asyncio
from dataclasses import replace

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingSelection,
    InMemoryMemory,
    Scope,
    SQLiteMemory,
)
from relf_agent.errors import ValidationError
from relf_agent.recall import MemoryRecallPolicy, RecallQuery

from .test_binding_execution import bound_catalog, engine
from .test_data_binding_resources import resources


@pytest.mark.parametrize("operation", ["facts", "recall", "validate_facts"])
def test_scoped_facts_preserves_real_delegated_client_drift_guard(tmp_path, operation):
    async def run():
        class Client(InMemoryMemory):
            async def facts(self, *args):
                result = super().facts(*args)
                if operation == "facts":
                    self.backend_id = "actual-v2"
                return result

            async def recall(self, *args):
                result = super().recall(*args)
                if operation == "recall":
                    self.backend_id = "actual-v2"
                return result

            async def validate_facts(self, *args):
                result = super().validate_facts(*args)
                if operation == "validate_facts":
                    self.backend_id = "actual-v2"
                return result

        class Proxy:
            backend_id = "public-stable"

            def __init__(self, client):
                self.client = client

            def __getattr__(self, name):
                return getattr(self.client, name)

        client = Client(backend_id="actual-v1")
        client.put_fact(Scope(), "red", "fact", "evidence", expected_version=0)
        catalog = bound_catalog()
        catalog.register(
            "facts",
            "facts",
            "1",
            resources().FactsBindingResource(
                Proxy(client), namespaces=("red",), default_namespace="red"
            ),
        )
        spec = AgentDefinition(
            AgentSpec("worker", "Use evidence"),
            AgentBindingDescriptor(facts=BindingSelection.ref("facts", "1")),
        )
        with engine(
            tmp_path / "runs.sqlite",
            catalog,
            recall_policy=None if operation == "facts" else MemoryRecallPolicy(),
        ) as runtime:
            handle = runtime.submit(spec, "q", command_id="s")
            result = await runtime.drive(handle.run_id)
            assert result.state == "failed" and result.error["code"] == "definition_mismatch"
            assert not runtime.store.run(handle.run_id)["actions"]
            assert runtime.store.budget(handle.run_id)["spent"] == 0

    asyncio.run(run())


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
@pytest.mark.parametrize("max_chars", [1000, 8000])
def test_facts_that_fit_actual_provenance_budget_remain_visible(tmp_path, backend, max_chars):
    async def run():
        memory = (
            InMemoryMemory()
            if backend == "memory"
            else SQLiteMemory(tmp_path / "long-backend-identity.sqlite")
        )
        try:
            value = "v" * (500 if max_chars == 8000 else 10)
            memory.put_fact(Scope(), "red", "k", value, expected_version=0)
            view = (
                resources()
                .FactsBindingResource(memory, namespaces=("red",), default_namespace="red")
                .select({}, Scope())
            )
            page = await view.recall(Scope(), "logical", RecallQuery(max_chars=max_chars))
            assert len(page.items) == 1 and page.items[0]["value"] == value
            assert page.used_chars <= max_chars and page.skipped == 0
        finally:
            memory.close()

    asyncio.run(run())


def test_partial_provenance_pages_keep_pending_records_in_scoped_cursors():
    async def run():
        memory = InMemoryMemory(backend_id="facts")
        for index in range(6):
            memory.put_fact(Scope(), "red", str(index), "v" * 200, expected_version=0)
        view = (
            resources()
            .FactsBindingResource(memory, namespaces=("red",), default_namespace="red")
            .select({}, Scope())
        )
        query = RecallQuery(max_items=6, max_chars=1000, scan_limit=8)
        keys, cursor = [], None
        for _ in range(10):
            page = await view.recall(Scope(), "logical", replace(query, cursor=cursor))
            assert page.used_chars <= 1000 and page.scanned <= 8
            keys.extend(item["key"] for item in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert cursor is None and keys == [str(index) for index in range(6)]
        first = await view.recall(Scope(), "logical", query)
        memory.put_fact(Scope(), "red", "0", "changed", expected_version=1)
        with pytest.raises(ValidationError):
            await view.recall(Scope(), "logical", replace(query, cursor=first.next_cursor))

    asyncio.run(run())
