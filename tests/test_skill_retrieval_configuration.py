"""Default directory discovery adapters preflight before owned root allocation."""

import asyncio

import pytest

import relf_agent as r
from relf_agent.errors import RalfError

from .test_skill_document_configuration import bundle


def profile(config, *, adapter="skills-directory-file"):
    return r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"knowledge": {"adapter": adapter, "config": config}},
    )


@pytest.mark.parametrize("adapter", ["skills-directory-file", "skills-directory-markdown"])
def test_default_native_knowledge_owns_catalog_and_keeps_tools_empty(tmp_path, adapter):
    root = bundle(tmp_path)
    config = {"root": str(root), "version": "1", "names": ["help"]}
    if adapter.endswith("markdown"):
        pytest.importorskip("yaml")
        config["paths"] = ["help/SKILL.md"]

    async def run():
        instance = await r.RuntimeBuilder().abuild(
            profile(config, adapter=adapter), tmp_path / "runs.sqlite"
        )
        context = instance._engine.knowledge
        assert type(context).__name__ == "KnowledgeContext"
        assert context.namespace == "skills" and context.limit == 5
        assert instance._engine.tools._tools == {}
        references = await context.references(r.Scope(), "Reference")
        assert references[0]["value"]["metadata"]["reference_kind"] == "skill-directory"
        assert "Use allowed tools" not in str(references)
        catalog = context.retriever.catalog
        await instance.aclose()
        with pytest.raises(RalfError):
            catalog.list(r.Scope())

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"names": []},
        {"names": ["help", "help"]},
        {"limit": True},
        {"limit": 0},
        {"limit": 101},
        {"max_chars": True},
        {"max_chars": 1},
        {"max_chars": 65537},
        {"namespace": ""},
        {"selector": {"adapter": "model"}},
        {"selector": {"adapter": "lexical", "config": {"version": ""}}},
        {"unknown": True},
    ],
)
def test_invalid_directory_configuration_has_no_data_allocation(tmp_path, change):
    config = {"root": "absent", "version": "1", **change}

    async def run():
        with pytest.raises(RalfError):
            await r.RuntimeBuilder(base_dir=tmp_path).abuild(
                profile(config), tmp_path / "runs.sqlite"
            )

    asyncio.run(run())
    assert list(tmp_path.iterdir()) == []
