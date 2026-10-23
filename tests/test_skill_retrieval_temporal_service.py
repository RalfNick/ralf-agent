"""Actual Workers discover native skill metadata and recover original approvals."""

import asyncio
import json
import os
import threading
import uuid

import pytest

import relf_agent as r
from relf_agent.temporal import replay_temporal_history

from .test_skill_retrieval_execution import DiscoveryReader, definition

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires owned actual Temporal service"
)


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_actual_directory_discovery_original_tool_approval_restart_history(tmp_path, kind):
    for name in ("alpha", "beta"):
        root = tmp_path / name
        root.mkdir()
        (root / "help.md").write_text(name)
        (root / "skills.json").write_text(
            json.dumps(
                {
                    "version": "1",
                    "skills": [
                        {
                            "name": "help",
                            "description": name + " help reference",
                            "version": "1",
                            "path": "help.md",
                        }
                    ],
                }
            )
        )

    class Catalog(r.FileSystemSkillCatalog):
        def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            self.observed.append(value["skill"]["instructions"])
            return value

    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "skill-discovery-" + uuid.uuid4().hex
        scope = r.Scope("skill-discovery", queue)
        observed, reader = [], DiscoveryReader()
        factories = r.ComponentRegistry()
        factories.register("provider", "reader", lambda config, context: reader)

        async def tools(config, context):
            registry = r.ToolRegistry()
            for name in ("alpha", "beta"):
                catalog = context.own(Catalog(tmp_path / name, version="1", scopes=[context.scope]))
                catalog.observed = observed
                source = context.own_async(r.SkillToolSource(catalog, version="1"))
                await r.register_tool_source(
                    registry,
                    source,
                    prefix=name + "_",
                    policies={
                        "skill_get": r.ToolPolicy("1", effect="read_only", requires_approval=True)
                    },
                )
            registry.register(
                r.ToolSpec("business", "Business", {"type": "object"}),
                lambda args, context: "business",
            )
            return registry

        factories.register_async("tools", "discovery-tools", tools)
        profile = r.TemporalProfile(
            "skill-discovery",
            "1",
            {"default": {"adapter": "reader"}},
            {"tools": {"adapter": "discovery-tools"}},
            binding_components=[
                item
                for name in ("alpha", "beta")
                for item in [
                    {
                        "role": "skills",
                        "component_id": name,
                        "version": "1",
                        "component": {
                            "adapter": "registered-tools",
                            "config": {"names": [name + "_skill_get"]},
                        },
                    },
                    {
                        "role": "knowledge",
                        "component_id": name,
                        "version": "1",
                        "component": {
                            "adapter": "knowledge-resource",
                            "config": {
                                "namespaces": ["skills"],
                                "default_namespace": "skills",
                                "backend": {
                                    "adapter": "skills-directory-file",
                                    "config": {"root": str(tmp_path / name), "version": "1"},
                                },
                            },
                        },
                    },
                ]
            ],
            execution={"context_reads": True},
        )
        saved, first = None, None
        for stage in range(3):
            assembly = await r.TemporalRuntimeBuilder(factories).abuild(profile, scope=scope)
            try:
                await assembly.start_worker(client, task_queue=queue)
                engine = assembly.create_engine(client, task_queue=queue, activity_timeout=10)
                handle = await engine.submit(definition(kind), "help", command_id="same", budget=64)
                if stage == 0:
                    first = handle
                    waiting = await engine.drive(handle.run_id, wait_seconds=20)
                    assert (
                        waiting.state == "waiting_approval" and reader.discovered and observed == []
                    ), waiting
                    continue
                assert handle == first
                deadline, approved = asyncio.get_running_loop().time() + 60, set()
                while asyncio.get_running_loop().time() < deadline:
                    done = await engine.drive(handle.run_id, wait_seconds=20)
                    if done.state != "waiting_approval":
                        break
                    for pending in done.pending:
                        target = pending.get("run_id", handle.run_id)
                        key = target, pending["action_id"]
                        if key in approved:
                            continue
                        receipt = await engine.approve(
                            target,
                            pending["action_id"],
                            pending["digest"],
                            command_id="approve-" + pending["action_id"],
                        )
                        assert (
                            await engine.approve(
                                target,
                                pending["action_id"],
                                pending["digest"],
                                command_id="approve-" + pending["action_id"],
                            )
                            == receipt
                        )
                        approved.add(key)
                    await asyncio.sleep(0.05)
                assert done.state == "succeeded", done
                if stage == 1:
                    saved = done.result
                else:
                    assert done.result == saved
                await replay_temporal_history(
                    await client.get_workflow_handle(handle.run_id).fetch_history()
                )
            finally:
                await assembly.aclose(wait_timeout=30)
        expected = ["alpha"] if kind == "agent" else ["alpha", "beta"]
        assert sorted(reader.discovered) == expected and sorted(observed) == expected

    asyncio.run(asyncio.wait_for(run(), 150))


@pytest.mark.parametrize("kind", ["native", "graph"])
def test_actual_directory_cancel_retains_file_read_and_worker_until_real_exit(tmp_path, kind):
    from relf_agent.errors import CloseIncomplete
    from relf_agent.retrieval import KnowledgeContext

    from .test_temporal_context_read_composition import definition as read_definition

    (tmp_path / "help.md").write_text("private body")
    (tmp_path / "skills.json").write_text(
        json.dumps(
            {
                "version": "1",
                "skills": [
                    {
                        "name": "help",
                        "description": "help reference",
                        "version": "1",
                        "path": "help.md",
                    }
                ],
            }
        )
    )
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()

    class Catalog(r.FileSystemSkillCatalog):
        def list(self, scope, **options):
            with self._workspace._operation(scope):
                self.entered.set()
                try:
                    assert self.release.wait(30)
                    return super().list(scope, **options)
                finally:
                    self.stopped.set()

    class Never:
        identity = {"kind": "cancelled-directory-never-model", "version": "1"}

        def __init__(self):
            self.calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            return r.ModelResponse(output="unexpected")

    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "directory-cancel-" + uuid.uuid4().hex
        scope = r.Scope("directory-cancel", queue)
        provider, catalogs = Never(), []
        factories = r.ComponentRegistry()
        factories.register("provider", "never", lambda config, context: provider)

        async def knowledge(config, context):
            catalog = context.own(Catalog(tmp_path, version="1", scopes=[context.scope]))
            catalog.entered, catalog.release, catalog.stopped = entered, release, stopped
            catalogs.append(catalog)
            return KnowledgeContext(
                r.SkillDirectoryRetriever(catalog, version="1"), namespace="skills"
            )

        factories.register_async("knowledge", "blocked-directory", knowledge)
        profile = r.TemporalProfile(
            "directory-cancel",
            "1",
            {"default": {"adapter": "never"}},
            {"knowledge": {"adapter": "blocked-directory"}},
            execution={"context_reads": True},
        )
        assembly = await r.TemporalRuntimeBuilder(factories).abuild(profile, scope=scope)
        restarted = None
        try:
            await assembly.start_worker(client, task_queue=queue)
            engine = assembly.create_engine(client, task_queue=queue, activity_timeout=10)
            handle = await engine.submit(
                read_definition(kind), "help", command_id="same", budget=32
            )
            assert await asyncio.to_thread(entered.wait, 15)
            receipt = await engine.cancel(handle.run_id, command_id="cancel")
            assert await engine.cancel(handle.run_id, command_id="cancel") == receipt
            with pytest.raises(CloseIncomplete):
                await assembly.aclose(wait_timeout=0)
            assert assembly._worker_stop is None and not stopped.is_set()
            assert catalogs[0]._workspace._root_fd is not None and provider.calls == 0
            release.set()
            await assembly.aclose(wait_timeout=15)
            assert stopped.is_set() and catalogs[0]._workspace._root_fd is None
            restarted = await r.TemporalRuntimeBuilder(factories).abuild(profile, scope=scope)
            await restarted.start_worker(client, task_queue=queue)
            recovered = restarted.create_engine(client, task_queue=queue, activity_timeout=10)
            view = await recovered.status(handle.run_id)
            assert view.state == "cancelled" and provider.calls == 0
            await replay_temporal_history(
                await client.get_workflow_handle(handle.run_id).fetch_history()
            )
        finally:
            release.set()
            await assembly.aclose(wait_timeout=15)
            if restarted is not None:
                await restarted.aclose(wait_timeout=15)

    asyncio.run(asyncio.wait_for(run(), 75))
