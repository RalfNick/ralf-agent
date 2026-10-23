"""Original SDK tree transport: ancestry admission and postorder physical closure."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from relf_agent.errors import CloseIncomplete, DefinitionMismatch
from relf_agent.temporal_parent_state import child_run_id
from relf_agent.types import digest
from tests import test_temporal_coding_composition_control as fixture


class TreeHandle(fixture.Handle):
    async def query(self, name, value):
        if value["kind"] == "coding_composition_children":
            self.client.calls.append(("children", self.run_id, self.epoch))
            return copy.deepcopy(self.client.tree.get(self.run_id, []))
        return await super().query(name, value)

    async def execute_update(self, name, value, **kwargs):
        if name in {"coding_composition_child_epoch", "coding_composition_child_stopped"}:
            self.client.calls.append(("adopt", self.run_id, value["child_run_id"], name))
            call = next(
                c for c in self.client.tree[self.run_id] if c["run_id"] == value["child_run_id"]
            )
            evidence = value["evidence"]
            call["child_execution"] = {
                k: evidence[k] for k in ("namespace", "execution_epoch", "original_execution_epoch")
            }
            if name == "coding_composition_child_stopped":
                call["physical_stop_proof"] = copy.deepcopy(evidence)
                self.client.refresh(self.run_id)
            return {"run_id": call["run_id"], "recorded": True}
        if name == "command":
            self.client.calls.append(("command", self.run_id, self.epoch, value["payload"]["kind"]))
            self.client.proofs[self.run_id]["state"] = "cancelling"
            self.client.refresh(self.run_id)
            return {"run_id": self.run_id}
        return await super().execute_update(name, value, **kwargs)


class TreeClient(fixture.Client):
    def get_workflow_handle(self, workflow_id, **kwargs):
        return TreeHandle(self, workflow_id, kwargs.get("run_id"))

    def refresh(self, run_id):
        proof = self.proofs[run_id]
        closed = (
            proof["state"] in {"cancelling", "cancelled"}
            and run_id not in self.blocked
            and all(
                c.get("physical_stop_proof", {}).get("physical_stopped")
                for c in self.tree.get(run_id, [])
            )
        )
        proof.update(physical_stopped=closed)
        if closed:
            proof["state"] = "cancelled"
        proof["revision"] += 1
        proof["proof_digest"] = digest({k: v for k, v in proof.items() if k != "proof_digest"})


@pytest.fixture
def tree(monkeypatch, namespace):
    manifest = {
        "kernel": "temporal-3",
        "binding_protocol": 23,
        "coding_composition_protocol": {
            "version": 7,
            "topology": "bounded-recursive-orchestration",
        },
    }
    monkeypatch.setattr(fixture, "MANIFEST", manifest)
    client = TreeClient({"definition": {"kind": "team"}, "input": "task", "budget": 64})
    client.tree, client.blocked = {"root": []}, set()
    parent_id = "root"
    for depth, kind in [(1, "team"), (2, "sequence")]:
        parent = client.proofs[parent_id]
        command = f"child-{depth}"
        run_id = child_run_id(fixture.SCOPE, command)
        base = {"definition": {"kind": kind}, "input": "task", "budget": 16 // depth}
        link = {
            "version": 1,
            "scope": fixture.SCOPE,
            "namespace": copy.deepcopy(fixture.NAMESPACE),
            "parent_run_id": parent_id,
            "parent_execution_epoch": parent["execution_epoch"],
            "parent_request_digest": parent["request_digest"],
            "parent_release_digest": parent["release_digest"],
            "call_id": command,
            "command_id": command,
            "member": "member",
            "planning_revision": 0,
            "child_run_id": run_id,
            "child_projection_digest": digest(base),
            "cap": base["budget"],
            "depth": depth,
        }
        request = {**base, "coding_parent": link}
        proof = fixture.proof(run_id, request=request, epoch=f"epoch-{depth}")
        client.proofs[run_id] = proof
        client.epochs[run_id] = proof["execution_epoch"]
        call = {
            "id": command,
            "call_id": command,
            "command_id": command,
            "member": "member",
            "run_id": run_id,
            "cap": base["budget"],
            "depth": depth,
            "planning_revision": 0,
            "request": request,
            "child_request_digest": digest(request),
            "dispatch_started": True,
            "child_execution": {
                k: proof[k] for k in ("namespace", "execution_epoch", "original_execution_epoch")
            },
        }
        client.tree[parent_id].append(call)
        client.tree[run_id] = []
        parent_id = run_id
    client.nested_id = client.tree["root"][0]["run_id"]
    client.leaf_id = parent_id
    client.candidate.update(execution_epoch="root-epoch", namespace=fixture.NAMESPACE)
    return client


@pytest.fixture
def namespace(monkeypatch):
    from relf_agent import temporal_session_activities

    async def identity(client):
        return fixture.NAMESPACE["id"]

    monkeypatch.setattr(temporal_session_activities, "namespace_id", identity)


def test_nested_parent_admission_uses_original_root_registry_only(tree):
    current = tree.proofs[tree.nested_id]
    value = {
        "scope": fixture.SCOPE,
        "run_id": current["run_id"],
        "execution_epoch": current["execution_epoch"],
        "command_id": "child-1",
        "request": current["request"],
        "runtime_manifest": fixture.MANIFEST,
    }
    info = SimpleNamespace(
        workflow_id=value["run_id"],
        workflow_run_id=value["execution_epoch"],
        workflow_namespace="original",
    )
    result = asyncio.run(fixture.module().root_admission(fixture.runtime(), tree, value, info))
    assert result["admitted"] is True
    assert result["execution_epoch"] == "epoch-1"
    assert not any(
        c[0] == "update" and c[3] == "admit_coding_composition_submission" for c in tree.calls
    )
    assert all(
        c[3].get("run_id") == "root"
        for c in tree.calls
        if c[0] == "query"
        and c[1].startswith("ralf-temporal-commands-")
        and c[3]["kind"] == "coding_composition_admission"
    )


def test_all_original_ancestors_required_before_native_activity(tree):
    tree.proofs["root"]["state"] = "cancelling"
    tree.refresh("root")
    leaf = tree.proofs[tree.leaf_id]
    request = {
        "scope": fixture.SCOPE,
        "run_id": leaf["run_id"],
        "execution_epoch": leaf["execution_epoch"],
        "runtime_manifest": fixture.MANIFEST,
    }
    asyncio.run(fixture.module().validate_activity(tree, request, workflow_id=leaf["run_id"]))
    assert tree.proofs[leaf["run_id"]]["state"] == "cancelled"


def test_owned_close_adopts_every_original_edge_postorder(tree):
    asyncio.run(
        fixture.module().close(fixture.runtime(), client=tree, scope=fixture.Scope(**fixture.SCOPE))
    )
    assert all(p["physical_stopped"] is True for p in tree.proofs.values())
    adopted = [
        c for c in tree.calls if c[0] == "adopt" and c[3] == "coding_composition_child_stopped"
    ]
    assert [(c[1], c[2]) for c in adopted][-2:] == [
        (tree.nested_id, tree.leaf_id),
        ("root", tree.nested_id),
    ]


def test_live_grandchild_keeps_all_ancestor_obligations(tree):
    tree.blocked.add(tree.leaf_id)
    with pytest.raises(CloseIncomplete):
        asyncio.run(
            fixture.module().close(
                fixture.runtime(), client=tree, scope=fixture.Scope(**fixture.SCOPE)
            )
        )
    assert not tree.proofs["root"]["physical_stopped"]
    assert not tree.proofs[tree.nested_id]["physical_stopped"]
    tree.blocked.clear()
    asyncio.run(
        fixture.module().close(fixture.runtime(), client=tree, scope=fixture.Scope(**fixture.SCOPE))
    )
    assert tree.proofs["root"]["physical_stopped"]


@pytest.mark.parametrize(
    "field", ["depth", "parent_execution_epoch", "parent_request_digest", "member"]
)
def test_forged_ancestor_link_refused_before_cancel(tree, field):
    leaf = tree.proofs[tree.leaf_id]
    leaf["request"]["coding_parent"][field] = 1 if field == "depth" else "foreign"
    leaf["request_digest"] = digest(leaf["request"])
    leaf["proof_digest"] = digest({k: v for k, v in leaf.items() if k != "proof_digest"})
    with pytest.raises(DefinitionMismatch):
        asyncio.run(fixture.module()._ancestry(tree, leaf, fixture.MANIFEST, fixture.NAMESPACE))
    assert not any(c[0] == "command" for c in tree.calls)


def test_child_transport_checks_depth_before_any_sdk_io(tree):
    parent = tree.proofs["root"]
    call = copy.deepcopy(tree.tree["root"][0])
    call["depth"] = 2
    with pytest.raises(DefinitionMismatch):
        asyncio.run(
            fixture.module()._child_proof(tree, parent, call, fixture.MANIFEST, fixture.NAMESPACE)
        )
    assert tree.calls == []


def test_registry_close_revokes_nested_admission_without_new_root(tree):
    tree.candidate["close_requested"] = True
    chain, admitted = asyncio.run(
        fixture.module()._ancestry_admission(
            tree, tree.proofs[tree.leaf_id], fixture.MANIFEST, fixture.NAMESPACE
        )
    )
    assert len(chain) == 2 and admitted is False
    assert not any(c[0] == "command" for c in tree.calls)
    assert not any(
        c[0] == "update" and c[3] == "admit_coding_composition_submission" for c in tree.calls
    )


def test_resource_proof_climbs_exact_original_ancestors(tree):
    asyncio.run(
        fixture.module().close(fixture.runtime(), client=tree, scope=fixture.Scope(**fixture.SCOPE))
    )
    tree.calls.clear()
    asyncio.run(
        fixture.module()._adopt_resource_ancestry(
            fixture.runtime(),
            tree,
            tree.proofs[tree.leaf_id],
            {"root": tree.proofs["root"]},
            fixture.MANIFEST,
            fixture.NAMESPACE,
        )
    )
    edges = [
        (c[1], c[2])
        for c in tree.calls
        if c[0] == "adopt" and c[3] == "coding_composition_child_stopped"
    ]
    assert edges == [(tree.nested_id, tree.leaf_id), ("root", tree.nested_id)]


def test_resource_ancestry_cannot_use_foreign_root_epoch(tree):
    root = {**tree.proofs["root"], "execution_epoch": "replacement"}
    with pytest.raises(CloseIncomplete):
        asyncio.run(
            fixture.module()._adopt_resource_ancestry(
                fixture.runtime(),
                tree,
                tree.proofs[tree.leaf_id],
                {"root": root},
                fixture.MANIFEST,
                fixture.NAMESPACE,
            )
        )
    assert not any(c[0] == "adopt" for c in tree.calls)


@pytest.mark.parametrize("closed_by", ["registry", "ancestor"])
def test_registration_cannot_start_business_under_closed_ancestor(tree, monkeypatch, closed_by):
    from relf_agent import temporal, temporal_state

    submitted = []

    class Guard:
        def __init__(self, *args, **kwargs):
            pass

        async def _guard(self, *args):
            submitted.append(args)

    monkeypatch.setattr(temporal, "TemporalEngine", Guard)
    monkeypatch.setattr(temporal_state, "validate_request", lambda *args: None)
    if closed_by == "registry":
        tree.candidate["close_requested"] = True
    else:
        tree.proofs["root"]["state"] = "cancelling"
        tree.refresh("root")
    parent = tree.proofs[tree.nested_id]
    value = {
        "mode": "register",
        "child": copy.deepcopy(tree.tree[tree.nested_id][0]),
        "parent_id": parent["run_id"],
        "parent_execution_epoch": parent["execution_epoch"],
        "parent_request_digest": parent["request_digest"],
        "parent_release_digest": parent["release_digest"],
        "scope": fixture.SCOPE,
        "task_queue": "original",
        "runtime_manifest": fixture.MANIFEST,
        "namespace": fixture.NAMESPACE,
    }
    info = SimpleNamespace(
        workflow_id=parent["run_id"],
        workflow_run_id=parent["execution_epoch"],
        workflow_namespace="original",
    )
    with pytest.raises(DefinitionMismatch):
        asyncio.run(fixture.module().control(fixture.runtime(), tree, value, info))
    assert submitted == []


def test_parent_cancel_failure_still_attempts_other_known_descendants(tree, monkeypatch):
    original = TreeHandle.execute_update

    async def fail_root(self, name, value, **kwargs):
        if self.run_id == "root" and name == "command":
            raise RuntimeError("original root update unavailable")
        return await original(self, name, value, **kwargs)

    monkeypatch.setattr(TreeHandle, "execute_update", fail_root)
    tree.proofs["root"]["state"] = "cancelling"
    tree.refresh("root")
    with pytest.raises(CloseIncomplete):
        asyncio.run(
            fixture.module().close(
                fixture.runtime(), client=tree, scope=fixture.Scope(**fixture.SCOPE)
            )
        )
    assert tree.proofs[tree.leaf_id]["physical_stopped"] is True


def test_deep_pg_resource_retained_after_ancestor_adoption_failure_and_retry(tree, monkeypatch):
    from relf_agent import delegated_coding, temporal_bindings
    from relf_agent.postgres_coding_resources import receive_resource

    resource = fixture.native_resource(tree, tree.leaf_id)
    original_update = TreeHandle.execute_update
    fault, scans = {"enabled": True}, []

    async def resources(scope):
        assert scope == fixture.Scope(**fixture.SCOPE)
        scans.append(resource["pending_stop"])
        return (copy.deepcopy(resource),)

    async def update(self, name, value, **kwargs):
        if (
            self.run_id == "root"
            and name == "coding_composition_child_stopped"
            and fault["enabled"]
        ):
            raise OSError("controlled original ancestor adoption failure")
        return await original_update(self, name, value, **kwargs)

    async def fence(runtime, client, leaf, namespace):
        nonlocal resource
        assert leaf["run_id"] == tree.leaf_id
        resource = receive_resource(
            resource,
            "unprepared",
            {"namespace_binding": resource["namespace_binding"], "prepare_granted": False},
        )

    monkeypatch.setattr(TreeHandle, "execute_update", update)
    monkeypatch.setattr(fixture.module(), "_fence_leaf", fence)
    handler = SimpleNamespace(
        identity=resource["runner"],
        runner=SimpleNamespace(_journal=SimpleNamespace(composition_resources=resources)),
    )
    monkeypatch.setattr(delegated_coding, "registered_coding_tool", lambda tool: handler)
    monkeypatch.setattr(temporal_bindings, "selected_runtime", lambda runtime, request: runtime)
    runtime = fixture.runtime()
    runtime.tools = SimpleNamespace(_tools=["coding"], get=lambda name: object())
    with pytest.raises(CloseIncomplete):
        asyncio.run(
            fixture.module().close(runtime, client=tree, scope=fixture.Scope(**fixture.SCOPE))
        )
    assert resource["pending_stop"] is False
    assert not tree.proofs["root"]["physical_stopped"]
    assert tree.proofs[tree.nested_id]["physical_stopped"]
    fault["enabled"] = False
    asyncio.run(fixture.module().close(runtime, client=tree, scope=fixture.Scope(**fixture.SCOPE)))
    assert tree.proofs["root"]["physical_stopped"]
    assert scans == [True, False, False, False]


def test_ancestry_reuses_current_verified_proof_only_within_one_walk(tree):
    chain = asyncio.run(
        fixture.module()._ancestry(
            tree, tree.proofs[tree.leaf_id], fixture.MANIFEST, fixture.NAMESPACE
        )
    )
    assert [p["run_id"] for p, _ in chain] == [tree.nested_id, "root"]
    proof_queries = [
        c[1] for c in tree.calls if c[0] == "query" and c[3]["kind"] == "coding_composition_proof"
    ]
    # The caller already read the current original leaf. Every ancestor is
    # freshly read once in this walk; no proof survives into another call.
    assert proof_queries == [tree.nested_id, "root"]
