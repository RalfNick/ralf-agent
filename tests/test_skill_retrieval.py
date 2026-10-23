"""Native retrieval of explicitly scoped passive skill directory metadata."""

import asyncio
import json
import threading
from dataclasses import replace

import pytest

import relf_agent as r
from relf_agent.errors import RalfError
from relf_agent.retrieval import KnowledgeContext, RetrievalQuery


def api():
    value = getattr(r, "SkillDirectoryRetriever", None)
    assert value is not None
    return value


class Catalog(r.InMemorySkillCatalog):
    def get(self, *args, **kwargs):
        raise AssertionError("directory discovery must never fetch instruction bodies")


def catalog():
    return Catalog(
        [
            r.SkillSpec("billing", "Invoice payment help", "private body"),
            r.SkillSpec("deploy", "发布部署失败排查", "private deploy body"),
        ],
        version="1",
    )


def test_native_chunks_context_references_and_source_validation_no_body_reads():
    source = catalog()
    retriever = api()(source, version="1")

    async def run():
        result = await retriever.retrieve(r.Scope(), "skills", RetrievalQuery("invoice", 5, 8000))
        assert len(result.items) == 1
        item = result.items[0]
        assert item.document_id == "billing" and item.version == 1
        assert item.metadata["reference_kind"] == "skill-directory"
        assert item.metadata["permissions"] == "none"
        assert "private" not in item.text and "instructions" not in str(item.metadata)
        await retriever.validate(r.Scope(), "skills", result.items)
        context = KnowledgeContext(retriever, namespace="skills")
        refs = await context.references(r.Scope(), "invoice")
        await context.validate(r.Scope(), refs)
        assert refs[0]["key"].startswith("knowledge:")
        assert refs[0]["value"]["metadata"]["reference_kind"] == "skill-directory"
        with pytest.raises(RalfError):
            await retriever.validate(r.Scope(), "skills", [replace(item, text="forged")])

    asyncio.run(run())
    source.close()


def test_explicit_names_filter_and_foreign_scope_refusal():
    source = catalog()
    retriever = api()(source, version="1", names=["billing"])

    async def run():
        result = await retriever.retrieve(r.Scope(), "skills", RetrievalQuery("部署", 5, 8000))
        assert result.items == ()
        with pytest.raises(RalfError):
            await retriever.retrieve(
                r.Scope("foreign", "user"), "skills", RetrievalQuery("", 5, 8000)
            )

    asyncio.run(run())
    source.close()


@pytest.mark.parametrize("names", [[], ["billing", "billing"], ["UNKNOWN"], "billing", [True]])
def test_invalid_name_allowlist_refuses_before_catalog_io(names):
    source = catalog()
    with pytest.raises(RalfError):
        api()(source, version="1", names=names)
    source.close()


def test_catalog_over_bound_refuses_without_silent_truncation():
    source = catalog()
    retriever = api()(source, version="1", max_entries=1)

    async def run():
        with pytest.raises(RalfError):
            await retriever.retrieve(r.Scope(), "skills", RetrievalQuery("", 5, 8000))

    asyncio.run(run())
    source.close()


@pytest.mark.parametrize("choice", [["billing", "billing"], ["foreign"], ("billing",), None])
def test_custom_selector_cannot_return_foreign_duplicate_or_unfinished_contract(choice):
    class Selector:
        identity = {"kind": "test-selector", "version": "1"}

        def select(self, query, entries, *, limit):
            return choice

    source = catalog()
    retriever = api()(source, version="1", selector=Selector())

    async def run():
        with pytest.raises(RalfError):
            await retriever.retrieve(r.Scope(), "skills", RetrievalQuery("", 5, 8000))

    asyncio.run(run())
    source.close()


def test_fixed_catalog_and_selector_identity_change_refuses():
    source = catalog()
    selector = r.LexicalSkillSelector(version="1")
    retriever = api()(source, version="1", selector=selector)
    selector.version = "changed"
    with pytest.raises(RalfError):
        _ = retriever.identity
    source.close()


def test_foreign_and_disallowed_reference_validation_cannot_reuse_known_chunk():
    source = catalog()
    retriever = api()(source, version="1", names=["billing"])

    async def run():
        result = await retriever.retrieve(r.Scope(), "skills", RetrievalQuery("", 5, 8000))
        item = result.items[0]
        for forged in [
            replace(item, scope=r.Scope("foreign", "p")),
            replace(item, namespace="other"),
        ]:
            with pytest.raises(RalfError):
                await retriever.validate(r.Scope(), "skills", [forged])

    asyncio.run(run())
    source.close()


def test_ordinary_identity_rejects_copy_hooks_before_deep_copy():
    class Unsafe(dict):
        def __deepcopy__(self, memo):
            raise AssertionError("copy hook must not run")

    class Selector:
        identity = Unsafe(kind="bad", version="1")

        def select(self, query, entries, *, limit):
            return []

    source = catalog()
    with pytest.raises(RalfError):
        api()(source, version="1", selector=Selector())
    source.close()


def test_custom_selector_identity_structure_is_bounded_before_detachment():
    nested = {"leaf": "x"}
    for _ in range(18):
        nested = {"child": nested}

    class Selector:
        identity = nested

        def select(self, query, entries, *, limit):
            return []

    source = catalog()
    with pytest.raises(RalfError):
        api()(source, version="1", selector=Selector())
    source.close()


def test_sync_directory_reads_use_original_actual_thread_tracker():
    from relf_agent.tools import ThreadExecutionTracker, current_thread_tracker

    main = threading.get_ident()

    class Tracked(Catalog):
        def list(self, *args, **kwargs):
            self.thread_ids.append(threading.get_ident())
            return super().list(*args, **kwargs)

    source = Tracked([r.SkillSpec("billing", "Invoice", "private")], version="1")
    source.thread_ids = []
    retriever = api()(source, version="1")

    async def run():
        tracker = ThreadExecutionTracker()
        token = current_thread_tracker.set(tracker)
        try:
            await retriever.retrieve(r.Scope(), "skills", RetrievalQuery("", 5, 8000))
            await tracker.drain()
            assert not tracker.has_active
        finally:
            current_thread_tracker.reset(token)

    asyncio.run(run())
    source.close()
    assert source.thread_ids and all(value != main for value in source.thread_ids)


def test_real_file_directory_keeps_fd_and_actual_read_after_observer_cancel(tmp_path, monkeypatch):
    from relf_agent.errors import CloseIncomplete
    from relf_agent.temporal_context_execution import ContextExecutionOwner
    from relf_agent.types import digest

    (tmp_path / "help.md").write_text("private skill body")
    (tmp_path / "skills.json").write_text(
        json.dumps(
            {
                "version": "1",
                "skills": [
                    {"name": "help", "description": "Reference", "version": "1", "path": "help.md"}
                ],
            }
        )
    )
    source = r.FileSystemSkillCatalog(tmp_path, version="1")
    retriever = api()(source, version="1")
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    original = source._workspace.stat

    def blocked(*args, **kwargs):
        entered.set()
        try:
            assert release.wait(5)
            return original(*args, **kwargs)
        finally:
            stopped.set()

    monkeypatch.setattr(source._workspace, "stat", blocked)

    async def run():
        owner = ContextExecutionOwner()

        async def operation():
            return await retriever.retrieve(r.Scope(), "skills", RetrievalQuery("", 5, 8000))

        proof = {
            "scope": {"workspace": "local", "principal": "local-user"},
            "action_id": "directory",
            "release_digest": digest({}),
            "request_digest": digest({}),
            "execution_epoch": "epoch",
        }
        observer = asyncio.create_task(owner.execute(operation, proof=proof))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            with pytest.raises(CloseIncomplete):
                await owner.aclose(wait_timeout=0)
            with pytest.raises(r.WorkspaceError):
                source.close()
            assert not stopped.is_set() and source._workspace._root_fd is not None
        finally:
            release.set()
            await owner.aclose(wait_timeout=2)
            source.close()
        assert stopped.is_set() and source._workspace._root_fd is None

    asyncio.run(run())
