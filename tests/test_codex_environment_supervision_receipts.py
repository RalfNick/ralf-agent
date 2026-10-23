"""Environment producer boundaries; supervision stubs are not broker lifecycle evidence."""

import asyncio
import copy
import hashlib
import json
import os
import shutil

import pytest

from relf_agent.codex_create_supervisor import CreateSupervisor
from relf_agent.errors import DefinitionMismatch, ExecutionHostFailed, ValidationError
from relf_agent.types import digest
from tests.test_codex_environment import resource as resource
from tests.test_codex_environment_supervision import environment


class DrainedHandle:
    """Only the validated-result interface is stubbed; no broker is launched."""

    def __init__(self, declaration, result):
        self.declaration = copy.deepcopy(declaration)
        self.result = result
        self.aborts = self.closes = 0

    def abort(self):
        self.aborts += 1

    def drain(self, *, timeout):
        return copy.deepcopy(self.result)

    def close(self):
        self.closes += 1


@pytest.fixture
def original(resource):
    owner = environment(resource, create_supervision=True)
    owner._acquire()
    owner._provision()
    operation = owner._metadata["create_operation"]
    handle = CreateSupervisor.create(
        owner._root,
        binding={
            "environment": owner.identity,
            "generation": "a" * 32,
            "operation_digest": operation["operation_digest"],
        },
        argv=[
            owner._docker,
            "--config",
            str(owner._root / "docker-client"),
            "--host",
            owner._host,
            *owner._create_argv(),
        ],
        namespace_lease_fd=owner._lease,
        cli_env=owner.transport_env,
    )
    declaration = handle.declaration
    handle.close()  # No child was ever launched by this boundary fixture.
    receipt = {
        "version": 1,
        "declaration_digest": digest(declaration),
        "binding_digest": digest(declaration["binding"]),
        "token": declaration["token"],
        "command_digest": declaration["command_digest"],
        "broker": {"pid": 12345, "birth": "fixture-original"},
        "child": None,
        "outer_gate_accepted": False,
        "gate_sealed": True,
        "cli_gate_accepted": False,
        "cli_exec_started": False,
        "child_ended": True,
        "exit_code": None,
        "output_complete": True,
        "stdout_digest": hashlib.sha256(b"").hexdigest(),
        "stderr_digest": hashlib.sha256(b"").hexdigest(),
        "cid": None,
        "reason": "outer_never",
    }
    result = {
        "declaration_digest": digest(declaration),
        "receipt": receipt,
        "receipt_digest": digest(receipt),
        "complete": True,
        "helpers_ended": True,
        "control_drained": True,
    }
    stub = DrainedHandle(declaration, result)
    owner._create_supervisor = stub
    operation.update(phase="submitted", declaration=declaration)
    owner._write_metadata()
    try:
        yield owner, stub, resource
    finally:
        if owner._lease is not None:
            os.close(owner._lease)
            owner._lease = None
        handle.close()
        shutil.rmtree(declaration["control_directory"]["path"])


def original_filters(owner):
    identity = owner.identity
    root_digest = hashlib.sha256(
        json.dumps(identity["root"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return [
        "label=ralf.coding.environment=1",
        "label=ralf.coding.resource=supervised",
        "label=ralf.coding.profile=" + identity["profile"]["config_digest"],
        "label=ralf.coding.root=" + root_digest,
        "label=ralf.coding.generation=" + "a" * 32,
    ]


def tracked_queries(owner):
    queries = []
    cli = owner._cli

    def query(args):
        assert args[0] == "ps", "Cold no-submit control must never CREATE/START"
        queries.append(list(args))
        return cli(args)

    owner._cli = query
    return queries


def test_only_three_successful_original_empty_views_produce_metadata_present_proof(original):
    owner, handle, resource = original
    queries = tracked_queries(owner)
    proof = asyncio.run(owner.observe_create_not_dispatched())
    named = ["name=^/" + owner._name + "$"]
    labels = original_filters(owner)
    expected = []
    for filters in (named + labels, named, labels):
        args = ["ps", "-a", "--no-trunc"]
        for value in filters:
            args.extend(("--filter", value))
        expected.append([*args, "--format", "{{.ID}}"])
    assert queries == expected
    assert proof["metadata_present"] is True and proof["container_present"] is False
    assert proof["generation"] == "a" * 32
    assert proof["identity"] == owner.identity
    assert (
        proof["create_operation_digest"] == owner._metadata["create_operation"]["operation_digest"]
    )
    assert proof["supervision_declaration_digest"] == digest(handle.declaration)
    assert proof["supervision_receipt_digest"] == digest(handle.result["receipt"])
    assert proof["proof_digest"] == digest({k: v for k, v in proof.items() if k != "proof_digest"})
    assert owner._metadata["create_operation"]["phase"] == "not_dispatched"
    assert owner._metadata["create_operation"]["no_submit"] == proof
    assert not (resource[1].parent / "docker.json").exists()
    with pytest.raises(ValidationError):
        asyncio.run(owner.observe_namespace_absence())


@pytest.mark.parametrize("field", ["complete", "helpers_ended", "control_drained"])
@pytest.mark.parametrize("value", [False, None, 1])
def test_helper_and_control_end_must_be_exact_true_before_any_empty_query(original, field, value):
    owner, handle, _ = original
    handle.result[field] = value
    owner._cli = lambda args: pytest.fail("Undrained supervision reached namespace query")
    with pytest.raises(ExecutionHostFailed):
        asyncio.run(owner.observe_create_not_dispatched())
    assert owner._metadata["create_operation"]["phase"] == "submitted"


@pytest.mark.parametrize(
    "field,value",
    [
        ("gate_sealed", False),
        ("gate_sealed", 1),
        ("cli_gate_accepted", True),
        ("cli_gate_accepted", None),
        ("cli_gate_accepted", 0),
        ("cli_exec_started", True),
        ("cli_exec_started", None),
        ("cli_exec_started", 0),
        ("child_ended", False),
        ("child_ended", 1),
    ],
)
def test_gate_or_exec_or_child_end_cannot_be_relabelled_by_empty_inventory(original, field, value):
    owner, handle, _ = original
    handle.result["receipt"][field] = value
    handle.result["receipt_digest"] = digest(handle.result["receipt"])
    owner._cli = lambda args: pytest.fail("Unsealed gate reached namespace query")
    with pytest.raises(DefinitionMismatch):
        asyncio.run(owner.observe_create_not_dispatched())
    assert owner._metadata["create_operation"]["no_submit"] is None


@pytest.mark.parametrize("fault", ["declaration_digest", "receipt_digest", "receipt_declaration"])
def test_producer_rejects_changed_original_supervision_digests(original, fault):
    owner, handle, _ = original
    if fault == "receipt_declaration":
        handle.result["receipt"]["declaration_digest"] = "f" * 64
        handle.result["receipt_digest"] = digest(handle.result["receipt"])
    else:
        handle.result[fault] = "f" * 64
    owner._cli = lambda args: pytest.fail("Foreign receipt reached namespace query")
    with pytest.raises(DefinitionMismatch):
        asyncio.run(owner.observe_create_not_dispatched())


@pytest.mark.parametrize(
    "fault", ["generation", "operation_digest", "environment", "argv", "cli_env", "executable"]
)
def test_foreign_declaration_is_refused_before_control_or_inventory(original, fault):
    owner, handle, _ = original
    operation = owner._metadata["create_operation"]
    if fault in {"generation", "operation_digest"}:
        operation["declaration"]["binding"][fault] = "f" * (32 if fault == "generation" else 64)
    elif fault == "environment":
        operation["declaration"]["binding"]["environment"]["resource_id"] = "foreign"
    elif fault == "argv":
        operation["declaration"]["argv"][-1] = "foreign"
    elif fault == "cli_env":
        operation["declaration"]["cli_env"]["PATH"] = "/foreign"
    else:
        operation["declaration"]["executable"]["inode"] += 1
    owner._write_metadata()
    owner._cli = lambda args: pytest.fail("Foreign operation reached namespace query")
    with pytest.raises(DefinitionMismatch):
        asyncio.run(owner.observe_create_not_dispatched())
    assert handle.aborts == 0


@pytest.mark.parametrize("view", ["intersection", "name", "labels"])
@pytest.mark.parametrize("fault", ["present", "query_error"])
def test_each_original_namespace_view_must_succeed_and_be_empty(original, view, fault):
    owner, _, _ = original
    cli = owner._cli
    queries = []

    def query(args):
        assert args[0] == "ps"
        queries.append(list(args))
        filters = [args[i + 1] for i, value in enumerate(args[:-1]) if value == "--filter"]
        selected = (
            "intersection" if len(filters) == 6 else "name" if len(filters) == 1 else "labels"
        )
        if selected == view:
            if fault == "query_error":
                raise ExecutionHostFailed("Fixture original query unavailable")
            return ("f" * 64 + "\n").encode(), b""
        return cli(args)

    owner._cli = query
    with pytest.raises((DefinitionMismatch, ExecutionHostFailed)):
        asyncio.run(owner.observe_create_not_dispatched())
    assert len(queries) == {"intersection": 1, "name": 2, "labels": 3}[view]
    assert owner._metadata["create_operation"]["phase"] == "submitted"
    assert owner._metadata["create_operation"]["no_submit"] is None


def test_sealed_no_submit_never_reopens_prepare_or_creates_during_cold_stop_close(
    original, monkeypatch
):
    owner, handle, resource = original
    tracked_queries(owner)
    proof = asyncio.run(owner.observe_create_not_dispatched())
    with pytest.raises(ExecutionHostFailed):
        asyncio.run(owner.prepare())
    assert owner._metadata["create_operation"]["no_submit"] == proof
    asyncio.run(owner.aclose())
    assert handle.closes == 1
    cold = environment(resource, create_supervision=True)
    monkeypatch.setattr(
        CreateSupervisor, "open", classmethod(lambda cls, root, declaration: handle)
    )
    tracked_queries(cold)
    try:
        assert asyncio.run(cold.stop_existing()) is None
        assert cold._metadata["create_operation"]["no_submit"] == proof
        asyncio.run(cold.aclose())
        assert cold._closed and cold._lease is None
        assert not (resource[1].parent / "docker.json").exists()
    finally:
        if cold._lease is not None:
            os.close(cold._lease)
            cold._lease = None


@pytest.mark.parametrize("field", ["create_operation_digest", "supervision_declaration_digest"])
def test_stored_no_submit_self_hash_cannot_rebind_original_operation(original, field):
    owner, handle, _ = original
    tracked_queries(owner)
    asyncio.run(owner.observe_create_not_dispatched())
    value = owner._metadata["create_operation"]["no_submit"]
    value[field] = "f" * 64
    value["proof_digest"] = digest({k: v for k, v in value.items() if k != "proof_digest"})
    owner._write_metadata()
    controls = handle.aborts
    with pytest.raises(DefinitionMismatch):
        owner._read_metadata()
    assert handle.aborts == controls
