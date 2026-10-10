import asyncio

import pytest

import ralf_agent as r
from ralf_agent.errors import ProviderError
from tests.test_memory_selection import Provider


def test_selector_requires_independent_dispatch_proof_before_call(tmp_path):
    class Store(r.SQLiteStore):
        def reserve(self, run_id, reservation_id, amount):
            if not reservation_id.startswith("memory-selection:"):
                return super().reserve(run_id, reservation_id, amount)

    memory = r.InMemoryMemory()
    p = Provider()
    with r.LocalEngine(
        Store(tmp_path / "run.sqlite"),
        providers={"default": p},
        tools=r.ToolRegistry(),
        stage_policy=r.ManagedModelMemoryPolicy(memory),
    ) as engine:
        run = engine.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(engine.drive(run.run_id)).state == "failed"
        assert p.business == 1 and p.selectors == 0
        assert engine.diagnostics(run.run_id).budget["spent"] == 1
        assert memory.facts(engine.scope, "auto-memory") == []


def test_expiry_is_rechecked_after_request_validation(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("time.time", lambda: now[0])

    class Expiring(Provider):
        def validate_request(self, messages, tools):
            if messages[0]["content"].startswith("memory-field-selector:"):
                now[0] = 102.0

    p = Expiring()
    memory = r.InMemoryMemory()
    local = r.LocalEngine(
        r.SQLiteStore(tmp_path / "run.sqlite"),
        providers={"default": p},
        tools=r.ToolRegistry(),
        stage_policy=r.ManagedModelMemoryPolicy(
            memory,
            admission=r.MemoryAdmissionPolicy({"name": ("result", "name")}, expires_at=101.0),
        ),
    )
    with local:
        h = local.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert p.selectors == 0
        assert local.diagnostics(h.run_id).budget == {"limit": 32, "held": 0, "spent": 1}
        assert local.memory_stages(h.run_id)[0]["status"] == "failed"
        assert memory.facts(local.scope, "auto-memory") == []


@pytest.mark.parametrize("hook", ["request", "select"])
def test_actual_hook_drift_cannot_be_hidden_by_policy_replacement(tmp_path, hook):
    memory = r.InMemoryMemory()
    admission = r.MemoryAdmissionPolicy({"name": ("result", "name")})

    class Drift(r.ManagedModelMemoryPolicy):
        def request(self, source):
            result = super().request(source)
            if hook == "request":
                replace(self)
            return result

        def select(self, source, response):
            result = super().select(source, response)
            if hook == "select":
                replace(self)
            return result

    def replace(actual):
        actual.namespace = "changed"
        engine.stage_policy = Drift(memory, admission=admission)

    p = Provider()
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "run.sqlite"),
        providers={"default": p},
        tools=r.ToolRegistry(),
        stage_policy=Drift(memory, admission=admission),
    ) as engine:
        h = engine.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(engine.drive(h.run_id)).state == "failed"
        assert memory.facts(engine.scope, "auto-memory") == []
        assert p.selectors == int(hook == "select")


@pytest.mark.parametrize("method", ["put_fact", "inspect_fact", "validate_facts", "recall"])
@pytest.mark.parametrize("mutation", ["method", "scope"])
def test_actual_target_method_drift_cannot_be_repinned_after_io(tmp_path, method, mutation):
    class Drift(r.InMemoryMemory):
        fact_inspection_version = None if method == "recall" else 1

        def put_fact(self, *args, **kwargs):
            result = super().put_fact(*args, **kwargs)
            if method == "put_fact":
                replace(self, "put_fact")
            return result

        def inspect_fact(self, *args, **kwargs):
            result = super().inspect_fact(*args, **kwargs)
            if method == "inspect_fact":
                replace(self, "inspect_fact")
            return result

        def validate_facts(self, *args, **kwargs):
            result = super().validate_facts(*args, **kwargs)
            if method == "validate_facts":
                replace(self, "validate_facts")
            return result

        def recall(self, *args, **kwargs):
            result = super().recall(*args, **kwargs)
            if method == "recall":
                replace(self, "recall")
            return result

    admission = r.MemoryAdmissionPolicy({"name": ("result", "name")})
    memory = Drift()

    def replace(actual, name):
        if mutation == "method":
            setattr(actual, name, getattr(super(Drift, actual), name))
        else:
            engine.stage_policy.scope = r.Scope("changed", "principal")
        engine.stage_policy = r.ManagedModelMemoryPolicy(memory, admission=admission)

    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "run.sqlite"),
        providers={"default": Provider()},
        tools=r.ToolRegistry(),
        stage_policy=r.ManagedModelMemoryPolicy(memory, admission=admission),
    ) as engine:
        h = engine.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(engine.drive(h.run_id)).state == "failed"
        record = engine.memory_stages(h.run_id)[0]
        assert record["facts"][0]["status"] == "writing"
        assert record["facts"][0]["receipt"] is None
        assert engine.diagnostics(h.run_id).budget["held"] == 1


def test_actual_admission_drift_is_checked_before_cas_reservation(tmp_path):
    memory = r.InMemoryMemory()

    class Admission(r.MemoryAdmissionPolicy):
        def validate(self, proposal, source):
            result = super().validate(proposal, source)
            actual.namespace = "changed"
            engine.stage_policy = r.ManagedModelMemoryPolicy(
                memory, admission=Admission({"name": ("result", "name")})
            )
            return result

    actual = r.ManagedModelMemoryPolicy(memory, admission=Admission({"name": ("result", "name")}))
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "run.sqlite"),
        providers={"default": Provider()},
        tools=r.ToolRegistry(),
        stage_policy=actual,
    ) as engine:
        h = engine.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(engine.drive(h.run_id)).state == "failed"
        assert memory.facts(engine.scope, "auto-memory") == []
        assert engine.diagnostics(h.run_id).budget["held"] == 0


@pytest.mark.parametrize("boundary", ["request", "validate"])
def test_ordinary_preflight_error_is_durable_auxiliary_failure(tmp_path, boundary):
    class Policy(r.ManagedModelMemoryPolicy):
        def request(self, source):
            if boundary == "request":
                raise RuntimeError("custom preparation failed")
            return super().request(source)

    class ValidationFailure(Provider):
        def validate_request(self, messages, tools):
            if messages[0]["content"].startswith("memory-field-selector:"):
                raise ProviderError("selector unavailable")

    memory, p = r.InMemoryMemory(), ValidationFailure()
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "run.sqlite"),
        providers={"default": p},
        tools=r.ToolRegistry(),
        stage_policy=Policy(memory),
    ) as engine:
        h = engine.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(engine.drive(h.run_id)).state == "succeeded"
        assert engine.memory_stages(h.run_id)[0]["selection"]["status"] == "failed"
        assert asyncio.run(engine.drive(h.run_id)).state == "succeeded"
        assert p.business == 1 and p.selectors == 0
        assert engine.diagnostics(h.run_id).budget == {"limit": 32, "held": 0, "spent": 1}
        assert memory.facts(engine.scope, "auto-memory") == []


def test_proposal_persistence_failure_is_not_an_auxiliary_hook_failure(tmp_path, monkeypatch):
    from tests.test_memory_selection import setup

    local, memory = setup(tmp_path / "run.sqlite")
    with local:
        h = local.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        original = local._commit

        def failed_commit(run, kind, data=None):
            if kind == "memory_stage_proposal_adopted":
                raise RuntimeError("execution store unavailable")
            return original(run, kind, data)

        with monkeypatch.context() as patch:
            patch.setattr(local, "_commit", failed_commit)
            with pytest.raises(RuntimeError, match="execution store"):
                asyncio.run(local.drive(h.run_id))
        assert local.memory_stages(h.run_id)[0]["status"] == "proposing"
        assert memory.facts(local.scope, "auto-memory") == []
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert local.providers["default"].business == local.providers["default"].selectors == 1
