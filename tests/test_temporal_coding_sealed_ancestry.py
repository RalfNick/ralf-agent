"""A verified sealed ancestor must not re-adopt a later diagnostic revision."""

import asyncio
import copy

import pytest

from ralf_agent.errors import CloseIncomplete, DefinitionMismatch
from ralf_agent.types import digest
from tests import test_temporal_coding_composition_control as fixture
from tests.test_temporal_coding_nested_control import namespace as namespace
from tests.test_temporal_coding_nested_control import tree as tree


def signed(proof):
    proof["proof_digest"] = digest({k: v for k, v in proof.items() if k != "proof_digest"})
    return proof


@pytest.fixture
def closed_tree(tree):
    for proof in tree.proofs.values():
        proof.update(state="cancelled", physical_stopped=True, revision=30)
        signed(proof)
    for calls in tree.tree.values():
        for call in calls:
            call["physical_stop_proof"] = copy.deepcopy(tree.proofs[call["run_id"]])
    return tree


async def adopt_ancestry(runtime, client, *, roots=None):
    return await fixture.module()._adopt_resource_ancestry(
        runtime,
        client,
        copy.deepcopy(client.proofs[client.leaf_id]),
        roots if roots is not None else {"root": copy.deepcopy(client.proofs["root"])},
        fixture.MANIFEST,
        fixture.NAMESPACE,
    )


def boundaries(monkeypatch, client, *, sealed=True, error=None):
    control, runtime = fixture.module(), fixture.runtime()
    events, adoptions = [], []
    original_proof = control._proof

    async def verified(owner, actual_client, parent, namespace):
        assert owner is runtime and actual_client is client
        assert namespace == fixture.NAMESPACE
        assert parent["run_id"] in {"root", client.nested_id}
        assert parent["execution_epoch"] == client.epochs[parent["run_id"]]
        events.append(("verified-seal", parent["run_id"]))
        if error is not None:
            raise error
        return sealed

    async def adopt(actual_client, parent, child, *, epoch=False):
        assert actual_client is client
        events.append(("epoch" if epoch else "stop", parent["run_id"]))
        adoptions.append((parent["run_id"], child["run_id"], epoch, copy.deepcopy(child)))

    async def fresh(*args, **kwargs):
        proof = await original_proof(*args, **kwargs)
        events.append(("fresh-proof", proof["run_id"]))
        return proof

    monkeypatch.setattr(control, "_deployment_sealed", verified)
    monkeypatch.setattr(control, "_adopt", adopt)
    monkeypatch.setattr(control, "_proof", fresh)
    return runtime, events, adoptions


def test_verified_sealed_ancestry_keeps_original_receipt_when_fresh_child_revision_advances(
    closed_tree, monkeypatch
):
    client = closed_tree
    stored = copy.deepcopy(client.tree[client.nested_id][0]["physical_stop_proof"])
    fresh = client.proofs[client.leaf_id]
    fresh["revision"] = 33
    signed(fresh)
    assert fresh != stored
    assert {k: v for k, v in fresh.items() if k not in {"revision", "proof_digest"}} == {
        k: v for k, v in stored.items() if k not in {"revision", "proof_digest"}
    }
    before = copy.deepcopy(client.tree)
    runtime, events, adoptions = boundaries(monkeypatch, client)
    asyncio.run(adopt_ancestry(runtime, client))
    assert adoptions == [], "A verified seal must suppress both redundant Parent Updates"
    assert client.tree == before
    for identity in (client.nested_id, "root"):
        assert events.index(("verified-seal", identity)) < events.index(("fresh-proof", identity))
    assert not any(call[0] == "command" for call in client.calls)


def test_unsealed_ancestry_still_adopts_original_epoch_and_stop_for_each_edge(
    closed_tree, monkeypatch
):
    client = closed_tree
    runtime, events, adoptions = boundaries(monkeypatch, client, sealed=False)
    asyncio.run(adopt_ancestry(runtime, client))
    assert [(parent, child, epoch) for parent, child, epoch, _ in adoptions] == [
        (client.nested_id, client.leaf_id, True),
        (client.nested_id, client.leaf_id, False),
        ("root", client.nested_id, True),
        ("root", client.nested_id, False),
    ]
    for identity in (client.nested_id, "root"):
        assert events.index(("verified-seal", identity)) < events.index(("epoch", identity))
        assert events.index(("epoch", identity)) < events.index(("stop", identity))
        assert events.index(("stop", identity)) < events.index(("fresh-proof", identity))


@pytest.mark.parametrize(
    "error",
    [DefinitionMismatch("foreign seal identity"), ConnectionError("seal proof unavailable")],
)
def test_seal_verification_refusal_or_transport_failure_never_counts_as_a_seal(
    closed_tree, monkeypatch, error
):
    runtime, _, adoptions = boundaries(monkeypatch, closed_tree, error=error)
    with pytest.raises(type(error)) as caught:
        asyncio.run(adopt_ancestry(runtime, closed_tree))
    assert caught.value is error and adoptions == []


@pytest.mark.parametrize("sealed", [False, True])
def test_live_child_cannot_be_bypassed_by_a_parent_seal(closed_tree, monkeypatch, sealed):
    client = closed_tree
    child = client.proofs[client.leaf_id]
    child.update(physical_stopped=False, state="cancelling")
    signed(child)
    runtime, events, adoptions = boundaries(monkeypatch, client, sealed=sealed)
    with pytest.raises(CloseIncomplete):
        asyncio.run(adopt_ancestry(runtime, client))
    assert adoptions == [] and not any(event[0] == "verified-seal" for event in events)


@pytest.mark.parametrize("sealed", [False, True])
def test_parent_is_reread_and_must_still_be_physically_stopped(closed_tree, monkeypatch, sealed):
    client = closed_tree
    runtime, events, adoptions = boundaries(monkeypatch, client, sealed=sealed)
    original_proof = fixture.module()._proof

    async def live_parent(*args, **kwargs):
        proof = await original_proof(*args, **kwargs)
        if proof["run_id"] == client.nested_id:
            proof = signed({**proof, "physical_stopped": False, "state": "cancelling"})
        return proof

    monkeypatch.setattr(fixture.module(), "_proof", live_parent)
    with pytest.raises(CloseIncomplete):
        asyncio.run(adopt_ancestry(runtime, client))
    assert ("fresh-proof", client.nested_id) in events
    assert len(adoptions) == (0 if sealed else 2)


@pytest.mark.parametrize("fault", ["missing", "epoch", "request"])
def test_sealed_ancestor_does_not_replace_original_root_acceptance(closed_tree, monkeypatch, fault):
    client = closed_tree
    root = copy.deepcopy(client.proofs["root"])
    if fault == "epoch":
        root["execution_epoch"] = "replacement-root-epoch"
    elif fault == "request":
        root["request"]["input"] = "replacement-business"
    roots = {} if fault == "missing" else {"root": root}
    runtime, events, adoptions = boundaries(monkeypatch, client)
    with pytest.raises(CloseIncomplete):
        asyncio.run(adopt_ancestry(runtime, client, roots=roots))
    assert adoptions == [] and not any(event[0] == "verified-seal" for event in events)


@pytest.mark.parametrize("fault", ["namespace", "parent_epoch", "child_request"])
def test_original_ancestry_identity_is_checked_before_any_seal_exemption(
    closed_tree, monkeypatch, fault
):
    client = closed_tree
    original_namespace = copy.deepcopy(fixture.NAMESPACE)
    child = client.proofs[client.leaf_id]
    if fault == "namespace":
        child["request"]["coding_parent"]["namespace"]["id"] = (
            "22222222-2222-2222-2222-222222222222"
        )
    elif fault == "parent_epoch":
        child["request"]["coding_parent"]["parent_execution_epoch"] = "replacement-parent-epoch"
    else:
        child["request"]["input"] = "replacement-child-input"
    child["request_digest"] = digest(child["request"])
    signed(child)
    runtime, events, adoptions = boundaries(monkeypatch, client)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(adopt_ancestry(runtime, client))
    assert adoptions == [] and not any(event[0] == "verified-seal" for event in events)
    assert fixture.NAMESPACE == original_namespace
