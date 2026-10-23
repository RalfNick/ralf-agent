"""Replaceable Store admission requires completed, pinned and scoped evidence."""

import asyncio
import copy
from contextlib import contextmanager

import pytest

import relf_agent as r
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.governance import DeploymentAdmissionPolicy
from relf_agent.types import digest

DEFAULT = object()
METHODS = (
    "local_capacity_policy",
    "prepare_local_capacity",
    "local_capacity_acquire",
    "local_capacity_release",
    "local_capacity_holders",
)
POLICY = DeploymentAdmissionPolicy("business", max_active_root_runs=2)


class HiddenStore:
    """Only the declared Store port is exposed; no SQLite connection reflection."""

    local_admission_version = 1

    def __init__(self, inner):
        self.inner = inner
        self.policy_result = self.prepare_result = self.acquire_result = DEFAULT
        self.release_result = self.holders_result = DEFAULT
        self.release_calls = 0
        self.backend_override = None

    @property
    def backend_id(self):
        return self.inner.backend_id if self.backend_override is None else self.backend_override

    def __getattr__(self, name):
        if name in {"conn", "path", "db_path"}:
            raise AttributeError(name)
        return getattr(self.inner, name)

    def local_capacity_policy(self):
        return (
            self.inner.local_capacity_policy()
            if self.policy_result is DEFAULT
            else self.policy_result
        )

    def prepare_local_capacity(self, policy):
        self.inner.prepare_local_capacity(policy)
        return None if self.prepare_result is DEFAULT else self.prepare_result

    def local_capacity_acquire(self, scope, run_id):
        self.inner.local_capacity_acquire(scope, run_id)
        return None if self.acquire_result is DEFAULT else self.acquire_result

    def local_capacity_release(self, scope, run_id):
        self.release_calls += 1
        actual = self.inner.local_capacity_release(scope, run_id)
        return actual if self.release_result is DEFAULT else self.release_result

    def local_capacity_holders(self, scope):
        return (
            self.inner.local_capacity_holders(scope)
            if self.holders_result is DEFAULT
            else self.holders_result
        )


class Provider:
    identity = {"kind": "admission-store-port-provider", "version": "1"}
    calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        return r.ModelResponse(output="completed")


def engine(store, **options):
    return r.LocalEngine(
        store, providers={"default": Provider()}, tools=r.ToolRegistry(), **options
    )


def test_connection_hidden_store_preserves_original_policy_and_recovers_held_root(tmp_path):
    path = tmp_path / "hidden.sqlite"
    original = None
    with r.SQLiteStore(path) as inner:
        store = HiddenStore(inner)
        assert not hasattr(store, "conn") and not hasattr(store, "path")
        with engine(store, admission_policy=POLICY) as owner:
            original = owner.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
            assert inner.local_capacity_holders(owner.scope) == (original.run_id,)
    with r.SQLiteStore(path) as inner:
        with engine(HiddenStore(inner), admission_policy=POLICY) as recovered:
            assert recovered.submit(r.AgentSpec("a", "Answer"), "q", command_id="s") == original
            assert asyncio.run(recovered.drive(original.run_id)).state == "succeeded"
            assert inner.local_capacity_holders(recovered.scope) == ()


@pytest.mark.parametrize("version", [True, 0, 2, "1"])
def test_invalid_advertised_admission_version_refuses_before_activation(tmp_path, version):
    with r.SQLiteStore(tmp_path / "version.sqlite") as inner:
        store = HiddenStore(inner)
        store.local_admission_version = version
        with pytest.raises(ValidationError):
            engine(store, admission_policy=POLICY)
        assert inner.local_capacity_policy() is None


@pytest.mark.parametrize("method", METHODS)
def test_advertised_admission_with_missing_operation_refuses(tmp_path, method):
    with r.SQLiteStore(tmp_path / "missing.sqlite") as inner:
        store = HiddenStore(inner)
        setattr(store, method, None)
        with pytest.raises(ValidationError):
            engine(store, admission_policy=POLICY)
        assert inner.local_capacity_policy() is None


@pytest.mark.parametrize("kind", ["async", "generator"])
def test_advertised_lazy_operation_is_not_a_completed_store_capability(tmp_path, kind):
    with r.SQLiteStore(tmp_path / "lazy-method.sqlite") as inner:
        store = HiddenStore(inner)
        if kind == "async":

            async def policy():
                return None
        else:

            def policy():
                yield None

        store.local_capacity_policy = policy
        with pytest.raises(ValidationError):
            engine(store, admission_policy=POLICY)
        assert inner.local_capacity_policy() is None


@pytest.mark.parametrize(
    "kind",
    ["coroutine", "generator", "context-manager", "partial-identity", "extra-identity", "list"],
)
def test_stored_policy_read_requires_original_complete_identity_and_no_lazy_result(tmp_path, kind):
    events = []

    async def lazy():
        events.append("unexpected-I/O")
        return POLICY.identity

    def generator():
        events.append("unexpected-I/O")
        yield POLICY.identity

    @contextmanager
    def context_value():
        events.append("unexpected-I/O")
        yield POLICY.identity

    values = {
        "coroutine": lazy,
        "generator": generator,
        "context-manager": context_value,
        "partial-identity": lambda: {
            "kind": "deployment-admission-policy",
            "deployment_id": "business",
        },
        "extra-identity": lambda: {**POLICY.identity, "extra": 1},
        "list": lambda: [POLICY.identity],
    }
    with r.SQLiteStore(tmp_path / "policy-read.sqlite") as inner:
        store = HiddenStore(inner)
        value = store.policy_result = values[kind]()
        with pytest.raises((ValidationError, DefinitionMismatch)):
            engine(store, admission_policy=POLICY)
        assert inner.local_capacity_policy() is None and events == []
        if kind == "coroutine":
            assert value.cr_frame is None
        if kind == "generator":
            assert value.gi_frame is None


@pytest.mark.parametrize("operation", ["prepare", "acquire"])
def test_prepare_and_acquire_must_return_completed_none_and_roll_back(tmp_path, operation):
    with r.SQLiteStore(tmp_path / "none-receipt.sqlite") as inner:
        store = HiddenStore(inner)
        if operation == "prepare":
            store.prepare_result = True
            with pytest.raises(ValidationError):
                engine(store, admission_policy=POLICY)
            assert inner.local_capacity_policy() is None
        else:
            with engine(store, admission_policy=POLICY) as owner:
                store.acquire_result = True
                with pytest.raises(ValidationError):
                    owner.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
                assert inner.local_capacity_holders(owner.scope) == ()
                assert inner.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


@pytest.mark.parametrize("kind", ["list", "generator", "coroutine", "duplicate", "foreign-scope"])
def test_holder_query_rejects_lazy_malformed_or_foreign_locators_without_release(tmp_path, kind):
    path = tmp_path / "holders.sqlite"
    with r.SQLiteStore(path) as inner:
        store = HiddenStore(inner)
        owner = engine(store, admission_policy=POLICY)
        original = owner.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        value = None
        try:
            if kind == "foreign-scope":
                with inner.transaction():
                    foreign_id = "foreign-original-root"
                    inner.local_capacity_acquire(r.Scope("other", "owner"), foreign_id)
                    foreign = copy.deepcopy(inner.run(original.run_id))
                    foreign.update(
                        id=foreign_id, scope={"workspace": "other", "principal": "owner"}
                    )
                    foreign["local_admission"] = {"version": 1, "root_run_id": foreign_id}
                    foreign["local_admission_digest"] = digest(foreign["local_admission"])
                    inner.insert_run(foreign)
                store.holders_result = (foreign_id,)
            elif kind == "generator":
                value = (item for item in (original.run_id,))
                store.holders_result = value
            elif kind == "coroutine":

                async def holders():
                    return (original.run_id,)

                value = store.holders_result = holders()
            else:
                store.holders_result = (
                    [original.run_id] if kind == "list" else (original.run_id, original.run_id)
                )
            with pytest.raises((ValidationError, DefinitionMismatch, AuthorizationDenied)):
                owner.submit(r.AgentSpec("next", "Answer"), "q", command_id="next")
            assert inner.local_capacity_holders(owner.scope) == (original.run_id,)
            assert store.release_calls == 0
            if kind == "coroutine":
                assert value.cr_frame is None
            if kind == "generator":
                assert value.gi_frame is None
        finally:
            store.holders_result = DEFAULT
            owner.close()


@pytest.mark.parametrize("value", [None, 0, 1, "true", {"released": True}])
def test_nonboolean_release_receipt_cannot_commit_quota_release(tmp_path, value):
    with r.SQLiteStore(tmp_path / "release.sqlite") as inner:
        store = HiddenStore(inner)
        owner = engine(store, admission_policy=POLICY)
        original = owner.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        try:
            store.release_result = value
            assert asyncio.run(owner.drive(original.run_id)).state == "succeeded"
            assert store.release_calls > 0
            assert inner.local_capacity_holders(owner.scope) == (original.run_id,)
            with pytest.raises(ValidationError):
                owner.submit(r.AgentSpec("next", "Answer"), "q", command_id="next")
            assert inner.local_capacity_holders(owner.scope) == (original.run_id,)
        finally:
            store.release_result = DEFAULT
            owner.close()


@pytest.mark.parametrize("kind", ["backend", "method", "policy-object", "stored-policy"])
def test_live_store_and_policy_drift_refuses_without_releasing_original_claim(tmp_path, kind):
    with r.SQLiteStore(tmp_path / "drift.sqlite") as inner:
        store = HiddenStore(inner)
        owner = engine(store, admission_policy=POLICY)
        original = owner.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        original_method = store.local_capacity_holders
        try:
            if kind == "backend":
                store.backend_override = "replacement-backend"
            if kind == "method":
                store.local_capacity_holders = lambda scope: inner.local_capacity_holders(scope)
            if kind == "policy-object":
                owner.admission_policy = DeploymentAdmissionPolicy(
                    "business", max_active_root_runs=2
                )
            if kind == "stored-policy":
                store.policy_result = DeploymentAdmissionPolicy(
                    "replacement", max_active_root_runs=2
                ).identity
            with pytest.raises(DefinitionMismatch):
                owner.submit(r.AgentSpec("next", "Answer"), "q", command_id="next")
            assert inner.local_capacity_holders(owner.scope) == (original.run_id,)
            assert store.release_calls == 0
        finally:
            store.backend_override = None
            store.local_capacity_holders = original_method
            store.policy_result = DEFAULT
            owner.admission_policy = POLICY
            owner.close()


def test_omitted_optional_capability_supports_default_but_explicit_policy_refuses(tmp_path):
    class LegacyStore(HiddenStore):
        local_admission_version = None

    with r.SQLiteStore(tmp_path / "legacy.sqlite") as inner:
        with engine(LegacyStore(inner)) as owner:
            handle = owner.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
            assert asyncio.run(owner.drive(handle.run_id)).state == "succeeded"
        with pytest.raises(ValidationError):
            engine(LegacyStore(inner), admission_policy=POLICY)
