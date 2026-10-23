"""Regression evidence for the sole dev82 boundary and composition review."""

import asyncio
from dataclasses import replace

import pytest

import relf_agent as r
import relf_agent.skills as skills
from relf_agent.errors import RalfError
from relf_agent.retrieval import KnowledgeContext, RetrievalQuery


@pytest.mark.parametrize("field", ["unexpected", "scope", "kind", "next_offset"])
def test_invalid_page_tree_is_rejected_before_any_detachment(monkeypatch, field):
    poison = [0] * 10000
    traversed = []
    original = skills._plain

    def plain(value, *args, **kwargs):
        if value is poison:
            traversed.append(True)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(skills, "_plain", plain)

    class Catalog(r.InMemorySkillCatalog):
        def list(self, *args, **kwargs):
            page = super().list(*args, **kwargs)
            page[self.field] = self.poison
            return page

    source = Catalog([r.SkillSpec("help", "Help reference", "body")], version="1")
    source.field, source.poison = field, poison
    retriever = r.SkillDirectoryRetriever(source, version="1")

    async def run():
        with pytest.raises(RalfError):
            await retriever.retrieve(r.Scope(), "skills", RetrievalQuery("help"))
        assert traversed == [], "malformed envelope tree was recursively detached"

    try:
        asyncio.run(run())
    finally:
        source.close()


@pytest.mark.parametrize("field", ["text", "document_id", "metadata"])
def test_raw_native_source_fields_refuse_copy_hooks_before_validation(field):
    source = r.InMemorySkillCatalog([r.SkillSpec("help", "Help reference", "body")], version="1")
    retriever = r.SkillDirectoryRetriever(source, version="1")

    async def run():
        item = (await retriever.retrieve(r.Scope(), "skills", RetrievalQuery("help"))).items[0]
        called = []

        class ForgedText(str):
            def __deepcopy__(self, memo):
                called.append(True)
                return getattr(item, field)

        class ForgedMetadata(dict):
            def __deepcopy__(self, memo):
                called.append(True)
                return item.metadata

        forged = replace(item)
        object.__setattr__(
            forged,
            field,
            ForgedMetadata({"forged": True}) if field == "metadata" else ForgedText("forged"),
        )
        with pytest.raises(RalfError):
            await retriever.validate(r.Scope(), "skills", [forged])
        assert called == [], "validation executed a custom copy hook"

    try:
        asyncio.run(run())
    finally:
        source.close()


@pytest.mark.parametrize("shape", ["wide", "cycle"])
def test_raw_metadata_is_bounded_before_recursive_copy(monkeypatch, shape):
    source = r.InMemorySkillCatalog([r.SkillSpec("help", "Help reference", "body")], version="1")
    retriever = r.SkillDirectoryRetriever(source, version="1")

    async def run():
        item = (await retriever.retrieve(r.Scope(), "skills", RetrievalQuery("help"))).items[0]
        poison = {"unexpected": [0] * 10000}
        if shape == "cycle":
            poison["unexpected"] = poison
        object.__setattr__(item, "metadata", poison)
        copied = []
        original = skills.copy.deepcopy

        def deepcopy(value, *args, **kwargs):
            if value is poison:
                copied.append(True)
            return original(value, *args, **kwargs)

        monkeypatch.setattr(skills.copy, "deepcopy", deepcopy)
        with pytest.raises(RalfError):
            await retriever.validate(r.Scope(), "skills", [item])
        assert copied == []

    try:
        asyncio.run(run())
    finally:
        source.close()


def test_directory_composes_with_default_native_query_transform():
    source = r.InMemorySkillCatalog([r.SkillSpec("help", "Help reference", "body")], version="1")
    directory = r.SkillDirectoryRetriever(source, version="1")
    context = KnowledgeContext(r.QueryTransformRetriever(directory), namespace="skills")

    async def run():
        references = await context.references(r.Scope(), "help")
        assert len(references) == 1
        await context.validate(r.Scope(), references)

    try:
        asyncio.run(run())
    finally:
        source.close()


def test_directory_validates_native_transformed_candidate_union_above100():
    source = r.InMemorySkillCatalog(
        [
            r.SkillSpec(f"skill-{i:03}", ("alpha" if i < 64 else "beta") + " help", "body")
            for i in range(128)
        ],
        version="1",
        max_skills=128,
    )

    class Transform:
        identity = {"kind": "two-query-test", "version": "1"}

        async def transform(self, text):
            return ("alpha", "beta")

    directory = r.SkillDirectoryRetriever(source, version="1")
    wrapped = r.QueryTransformRetriever(directory, Transform(), max_candidate_chars=262144)

    async def run():
        result = await wrapped.retrieve(r.Scope(), "skills", RetrievalQuery("help", 128, 262144))
        assert len(result.items) == 128
        await wrapped.validate(r.Scope(), "skills", result.items)
        await directory.validate(r.Scope(), "skills", result.items)

    try:
        asyncio.run(run())
    finally:
        source.close()
