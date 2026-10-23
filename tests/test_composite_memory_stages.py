import asyncio

import pytest

from relf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    InMemoryMemory,
    ManagedMemoryPolicy,
    ManagedModelMemoryPolicy,
    MemoryAdmissionPolicy,
    ModelResponse,
    Scope,
    TeamSpec,
    WorkflowSpec,
)
from relf_agent.errors import DefinitionMismatch, MemoryBackendError, ValidationError
from tests.test_managed_memory_stage import engine, schema


class Provider:
    identity = {"kind": "composite-memory-fixture", "version": "1"}

    def __init__(self):
        self.business = self.selectors = 0

    async def complete(self, messages, tools):
        await asyncio.sleep(0)
        if messages[0]["content"].startswith("memory-field-selector:"):
            self.selectors += 1
            assert tools == []
            return ModelResponse(output={"keys": ["name"]})
        self.business += 1
        return ModelResponse(output={"name": messages[0]["content"]})


def definition(kind):
    a, b = AgentSpec("a", "a-result"), AgentSpec("b", "b-result")
    if kind in {"graph", "parallel"}:
        return GraphWorkflowSpec(
            "graph",
            [GraphNode("a", agent=a), GraphNode("b", agent=b)],
            max_concurrency=2 if kind == "parallel" else 1,
        )
    if kind in {"team", "nested"}:
        return TeamSpec(
            "team",
            {"a": WorkflowSpec("sequence", [a]) if kind == "nested" else a, "b": b},
            child_budget=12,
            max_depth=4,
        )
    return DynamicWorkflowSpec(
        "dynamic",
        {"a": a, "b": b},
        child_budget=12,
        plan_mode="dag" if kind == "dynamic-dag" else "flat",
    )


def policy(memory, mode="rule", **kwargs):
    cls = ManagedMemoryPolicy if mode == "rule" else ManagedModelMemoryPolicy
    return cls(
        memory,
        admission=MemoryAdmissionPolicy({"name": ("result", "name")}),
        namespace="observations",
        **kwargs,
    )


def records(local, run_id):
    result = local.memory_stages(run_id)
    for child in local.store.run(run_id).get("orchestration", {}).get("children", []):
        result.extend(records(local, child["run_id"]))
    return result


@pytest.mark.parametrize("kind", ["graph", "parallel", "team", "dynamic", "dynamic-dag", "nested"])
@pytest.mark.parametrize("mode", ["rule", "model"])
def test_actual_composites_write_distinct_grounded_facts_and_reconnect(tmp_path, kind, mode):
    memory, provider = InMemoryMemory(backend_id="facts"), Provider()
    path, spec = tmp_path / "runs.sqlite", definition(kind)
    with engine(path, provider, stage_policy=policy(memory, mode)) as local:
        h = local.submit(spec, "task", command_id="s", budget=32)
        assert schema(local) == "12"
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        facts = memory.facts(local.scope, "observations")
        assert len(facts) == 2 and len({f["key"] for f in facts}) == 2
        assert {f["value"]["value"] for f in facts} == {"a-result", "b-result"}
        evidence = records(local, h.run_id)
        assert len(evidence) == 2 and all(r["status"] == "completed" for r in evidence)
        assert local.diagnostics(h.run_id).budget == {
            "limit": 32,
            "spent": 4 if mode == "rule" else 6,
            "held": 0,
        }
        if kind == "parallel":
            assert {r["workflow_node"] for r in evidence} == {"a", "b"}
            assert {r["source"]["workflow_node"] for r in evidence} == {"a", "b"}
        expected = (provider.business, provider.selectors)
        assert expected == (2, 0 if mode == "rule" else 2)
    with engine(path, provider, stage_policy=policy(memory, mode)) as restored:
        assert restored.submit(spec, "task", command_id="s", budget=32) == h
        assert asyncio.run(restored.drive(h.run_id)).state == "succeeded"
        assert (provider.business, provider.selectors) == expected
        assert len(memory.facts(restored.scope, "observations")) == 2
        assert len(records(restored, h.run_id)) == 2


@pytest.mark.parametrize(
    "mutation", ["missing_frame", "wrong_source_node", "missing_record", "missing_reservation"]
)
def test_parallel_memory_rejects_missing_or_moved_original_evidence(tmp_path, mutation):
    with engine(
        tmp_path / "runs.sqlite", Provider(), stage_policy=policy(InMemoryMemory())
    ) as local:
        h = local.submit(definition("parallel"), "task", command_id="s")
        asyncio.run(local.drive(h.run_id))
        with local.store.transaction():
            root = local.store.run(h.run_id)
            node = root["workflow"]["nodes"]["a"]
            if mutation == "missing_frame":
                node.pop("execution")
            else:
                record = node["execution"]["memory_stages"]["0"]
                if mutation == "wrong_source_node":
                    record["source"]["workflow_node"] = "b"
                elif mutation == "missing_record":
                    node["execution"].pop("memory_stages")
                else:
                    local.store.conn.execute(
                        "DELETE FROM reservations WHERE id=?",
                        (record["facts"][0]["reservation_id"],),
                    )
            local.store.save_run(root)
        with pytest.raises(DefinitionMismatch):
            local.memory_stages(h.run_id)
        with pytest.raises(DefinitionMismatch):
            asyncio.run(local.drive(h.run_id))


@pytest.mark.parametrize("mode", ["rule", "model"])
def test_exhausted_parallel_budget_never_dispatches_optional_memory(tmp_path, mode):
    memory, provider = InMemoryMemory(), Provider()
    with engine(tmp_path / "runs.sqlite", provider, stage_policy=policy(memory, mode)) as local:
        h = local.submit(definition("parallel"), "task", command_id="s", budget=2)
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert provider.business == 2 and provider.selectors == 0
        assert memory.facts(local.scope, "observations") == []
        assert local.diagnostics(h.run_id).budget == {"limit": 2, "spent": 2, "held": 0}
        assert all(r["status"] == "failed" for r in local.memory_stages(h.run_id))


@pytest.mark.parametrize("mode", ["rule", "model"])
def test_unknown_child_memory_holds_parent_allowance_until_explicit_root_recovery(tmp_path, mode):
    class LostAck(InMemoryMemory):
        writes = 0

        def put_fact(self, *args, **kwargs):
            self.writes += 1
            result = super().put_fact(*args, **kwargs)
            if args[3]["value"] == "a-result":
                raise MemoryBackendError("lost acknowledgement")
            return result

    memory, provider = LostAck(), Provider()
    with engine(tmp_path / "runs.sqlite", provider, stage_policy=policy(memory, mode)) as local:
        h = local.submit(definition("team"), "task", command_id="s", budget=32)
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert memory.writes == 2
        assert local.diagnostics(h.run_id).budget["held"] == 12
        assert not local.store.run(h.run_id)["orchestration"]["quiescent"]
        unknown = next(r for r in records(local, h.run_id) if r["status"] == "outcome_unknown")
        original_calls = (provider.business, provider.selectors)
        assert local.status(unknown["source"]["run_id"]).state == "succeeded"
        assert local.diagnostics(h.run_id).budget["held"] == 12
        asyncio.run(local.drive(h.run_id))
        assert local.diagnostics(h.run_id).budget["held"] == 0
        assert (provider.business, provider.selectors) == original_calls and memory.writes == 2


@pytest.mark.parametrize("mode", ["rule", "model"])
def test_cancel_during_parallel_fact_write_preserves_receipt_and_stops_new_writes(tmp_path, mode):
    class CancelMemory(InMemoryMemory):
        writes = 0

        async def put_fact(self, *args, **kwargs):
            self.writes += 1
            result = super().put_fact(*args, **kwargs)
            local.cancel(h.run_id, command_id="cancel")
            await asyncio.sleep(0)
            return result

    memory, provider = CancelMemory(), Provider()
    with engine(tmp_path / "runs.sqlite", provider, stage_policy=policy(memory, mode)) as local:
        h = local.submit(definition("parallel"), "task", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "cancelled"
        before = (provider.business, provider.selectors, memory.writes)
        assert memory.writes == 1
        assert local.diagnostics(h.run_id).budget["held"] == 0
        assert asyncio.run(local.drive(h.run_id)).state == "cancelled"
        assert (provider.business, provider.selectors, memory.writes) == before


@pytest.mark.parametrize("kind", ["parallel", "team", "dynamic-dag", "nested"])
def test_members_choose_distinct_host_authorized_write_targets(tmp_path, kind):
    from relf_agent import AgentBindingDescriptor, BindingCatalog, BindingSelection, BoundDefinition

    catalog = BindingCatalog(scope=Scope())
    first, second = InMemoryMemory(backend_id="first"), InMemoryMemory(backend_id="second")
    catalog.register("stage_policy", "first", "1", policy(first))
    catalog.register("stage_policy", "second", "1", policy(second, "model"))
    paths = (
        ["graph/nodes/a", "graph/nodes/b"]
        if kind == "parallel"
        else ["team/members/a/sequence/steps/0", "team/members/b"]
        if kind == "nested"
        else [
            f"{'dynamic' if kind == 'dynamic-dag' else 'team'}/members/{name}"
            for name in ("a", "b")
        ]
    )
    spec = BoundDefinition(
        definition(kind),
        {
            path: AgentBindingDescriptor(stage_policy=BindingSelection.ref(name, "1"))
            for path, name in zip(paths, ("first", "second"), strict=True)
        },
    )
    with engine(tmp_path / "runs.sqlite", Provider(), binding_catalog=catalog) as local:
        h = local.submit(spec, "task", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert first.facts(local.scope, "observations")[0]["value"]["value"] == "a-result"
        assert second.facts(local.scope, "observations")[0]["value"]["value"] == "b-result"
        assert {r["policy"]["backend_id"] for r in records(local, h.run_id)} == {"first", "second"}


def test_composite_memory_activation_rolls_back_with_failed_admission(tmp_path):
    from relf_agent import LocalEngine, SQLiteStore, ToolRegistry

    class Store(SQLiteStore):
        def prepare_composite_memory_stages(self):
            super().prepare_composite_memory_stages()
            raise ValidationError("activation failed")

    with LocalEngine(
        Store(tmp_path / "runs.sqlite"),
        providers={"default": Provider()},
        tools=ToolRegistry(),
        stage_policy=policy(InMemoryMemory()),
    ) as local:
        with pytest.raises(ValidationError):
            local.submit(definition("parallel"), "task", command_id="s")
        assert schema(local) == "1"
        assert local.store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_parallel_write_target_drift_after_await_requires_original_target_restoration(tmp_path):
    class Drift(InMemoryMemory):
        writes = 0

        async def put_fact(self, *args, **kwargs):
            self.writes += 1
            result = super().put_fact(*args, **kwargs)
            await asyncio.sleep(0)
            self.backend_id = "changed"
            return result

    memory = Drift(backend_id="original")
    with engine(tmp_path / "runs.sqlite", Provider(), stage_policy=policy(memory)) as local:
        h = local.submit(definition("parallel"), "task", command_id="s")
        result = asyncio.run(local.drive(h.run_id))
        assert result.state == "failed" and result.error["code"] == "definition_mismatch"
        before = memory.writes
        assert local.status(h.run_id).state == "failed"
        assert local.diagnostics(h.run_id).budget["held"] > 0
        memory.backend_id = "original"
        assert asyncio.run(local.drive(h.run_id)).state == "failed"
        assert memory.writes == before
        assert local.diagnostics(h.run_id).budget["held"] == 0


@pytest.mark.parametrize("nested", [False, True])
def test_facade_explicit_root_resume_recovers_closed_child_memory_without_dispatch(
    tmp_path, nested
):
    from relf_agent import Runtime
    from tests.test_remote_session_recovery import settled

    class LostAck(InMemoryMemory):
        writes = 0

        def put_fact(self, *args, **kwargs):
            self.writes += 1
            super().put_fact(*args, **kwargs)
            raise MemoryBackendError("lost acknowledgement")

    async def run():
        memory, provider = LostAck(), Provider()
        spec = (
            TeamSpec("outer", {"inner": definition("team")}, child_budget=32, max_depth=4)
            if nested
            else definition("team")
        )
        local = engine(tmp_path / "runs.sqlite", provider, stage_policy=policy(memory, "model"))
        async with Runtime(local, owned=True) as runtime:
            h = await runtime.submit(spec, "task", command_id="s", budget=64)
            assert (await h.wait(wait_timeout=5)).snapshot.state == "succeeded"
            await settled(runtime)
            assert (await h.diagnostics()).budget["held"] > 0
            before = (provider.business, provider.selectors, memory.writes)
            assert len([p for p in await h.pending() if p["source"] == "memory"]) == 2
            await h.resume()
            await settled(runtime)
            assert (await h.diagnostics()).budget["held"] == 0
            assert all(r["status"] == "completed" for r in records(local, h.ref.run_id))
            assert (provider.business, provider.selectors, memory.writes) == before

    asyncio.run(run())


def test_root_recovery_keeps_missing_child_fact_unknown_without_new_cas(tmp_path):
    class Unknown(InMemoryMemory):
        writes = 0

        def put_fact(self, *args, **kwargs):
            self.writes += 1
            raise MemoryBackendError("outcome unavailable")

    memory, provider = Unknown(), Provider()
    with engine(tmp_path / "runs.sqlite", provider, stage_policy=policy(memory)) as local:
        h = local.submit(definition("team"), "task", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert local.diagnostics(h.run_id).budget["held"] == 24
        assert provider.business == memory.writes == 2
        assert all(r["status"] == "outcome_unknown" for r in records(local, h.run_id))


def test_root_memory_recovery_rejects_changed_original_child_owner(tmp_path):
    class Unknown(InMemoryMemory):
        def put_fact(self, *args, **kwargs):
            raise MemoryBackendError("outcome unavailable")

    with engine(tmp_path / "runs.sqlite", Provider(), stage_policy=policy(Unknown())) as local:
        h = local.submit(definition("team"), "task", command_id="s")
        asyncio.run(local.drive(h.run_id))
        child_id = local.store.run(h.run_id)["orchestration"]["children"][0]["run_id"]
        with local.store.transaction():
            child = local.store.run(child_id)
            child["parent_id"] = local.store.run(h.run_id)["orchestration"]["children"][1]["run_id"]
            local.store.save_run(child)
        with pytest.raises(DefinitionMismatch):
            asyncio.run(local.drive(h.run_id))


@pytest.mark.parametrize("kind", ["graph", "parallel", "team", "dynamic-dag"])
@pytest.mark.parametrize(
    "selection,window",
    [
        ("model", "memory_stage_source_recorded"),
        ("model", "memory_selection_response_received"),
        ("model", "cas_committed"),
        ("model", "memory_fact_receipt_recorded"),
        ("model", "memory_stage_finished"),
        ("rule", "cas_committed"),
    ],
)
def test_real_process_memory_recovery_never_repeats_received_selector_or_cas(
    tmp_path, kind, selection, window
):
    import os
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path

    import relf_agent

    fixture = Path(__file__).with_name("composite_memory_crash_fixture.py")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": os.pathsep.join(
            [str(Path(relf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
        ),
    }
    args = [sys.executable, str(fixture), str(tmp_path), kind, window]
    first = subprocess.run(
        [*args, "crash", selection], env=env, capture_output=True, text=True, timeout=30
    )
    assert first.returncode == 77, first.stderr
    second = subprocess.run(
        [*args, "resume", selection], env=env, capture_output=True, text=True, timeout=30
    )
    assert second.returncode == 0, second.stderr
    with sqlite3.connect(tmp_path / "audit.sqlite") as db:
        counts = dict(db.execute("SELECT kind, COUNT(*) FROM calls GROUP BY kind"))
    assert counts == (
        {"business": 2, "cas": 2, "selector": 2}
        if selection == "model"
        else {"business": 2, "cas": 2}
    )
