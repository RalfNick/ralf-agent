import asyncio

import pytest

from ralf_agent import AgentSpec, InMemoryMemory, MemoryAdmissionPolicy, ModelResponse
from tests.test_managed_memory_stage import engine
from tests.test_managed_model_memory import policy


class Provider:
    identity = {"kind": "automatic-memory-test", "version": "1"}

    def __init__(self, selection=None):
        self.business = self.selectors = 0
        self.selection = (
            ModelResponse(output={"keys": ["name"]}) if selection is None else selection
        )

    async def complete(self, messages, tools):
        if messages[0]["content"].startswith("memory-field-selector:"):
            self.selectors += 1
            assert tools == []
            if isinstance(self.selection, Exception):
                raise self.selection
            return self.selection
        self.business += 1
        return ModelResponse(output={"name": "Alice", "transient": "not durable"})


def setup(path, provider=None, **kwargs):
    memory = kwargs.pop("memory", InMemoryMemory(backend_id="facts"))
    stage = policy(
        memory,
        admission=MemoryAdmissionPolicy(
            {"name": ("result", "name"), "transient": ("result", "transient")}
        ),
        **kwargs,
    )
    return engine(path, provider or Provider(), stage_policy=stage), memory


@pytest.mark.parametrize("keys", [["name"], []])
def test_original_run_selects_grounded_fields_once(tmp_path, keys):
    p = Provider(ModelResponse(output={"keys": keys}))
    local, memory = setup(tmp_path / "run.sqlite", p)
    with local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        record = local.memory_stages(h.run_id)[0]
        assert record["selection"]["status"] == "completed"
        assert record["selection"]["keys"] == keys
        assert record["status"] == "completed" and len(record["facts"]) == len(keys)
        values = memory.facts(local.scope, "auto-memory")
        assert len(values) == len(keys)
        if keys:
            assert values[0]["value"]["value"] == "Alice"
        assert local.diagnostics(h.run_id).budget == {
            "limit": 32,
            "held": 0,
            "spent": 2 + len(keys),
        }
        assert len(local.status(h.run_id).actions) == 1
        asyncio.run(local.drive(h.run_id))
        assert p.business == 1 and p.selectors == 1


@pytest.mark.parametrize(
    "selection",
    [ModelResponse(output={"keys": ["invented"]}), ModelResponse(), RuntimeError("lost")],
)
def test_optional_failure_never_stores_all_fields_or_replays_business(tmp_path, selection):
    p = Provider(selection)
    local, memory = setup(tmp_path / "run.sqlite", p)
    with local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        record = local.memory_stages(h.run_id)[0]
        unknown = isinstance(selection, Exception)
        assert record["status"] == ("outcome_unknown" if unknown else "failed")
        assert record["selection"]["status"] == ("outcome_unknown" if unknown else "failed")
        assert local.diagnostics(h.run_id).budget == {
            "limit": 32,
            "held": int(unknown),
            "spent": 1 + int(not unknown),
        }
        assert memory.facts(local.scope, "auto-memory") == []
        asyncio.run(local.drive(h.run_id))
        assert p.business == 1 and p.selectors == 1


class PowerLoss(BaseException):
    pass


def checkpoint(monkeypatch, event, *, before=False):
    from ralf_agent import managed_memory_stage, memory_selection

    if event == "memory_selection_dispatched":
        original = memory_selection._dispatch

        def fault(*args):
            original(*args)
            raise PowerLoss()

        monkeypatch.setattr(memory_selection, "_dispatch", fault)
        return
    if event == "memory_selection_adopted":
        original_adopt = memory_selection._adopt

        def fault_adopt(*args, **kwargs):
            original_adopt(*args, **kwargs)
            raise PowerLoss()

        monkeypatch.setattr(memory_selection, "_adopt", fault_adopt)
        return
    original = managed_memory_stage._save

    def fault(e, run_id, record, actual):
        if actual == event and before:
            raise PowerLoss()
        original(e, run_id, record, actual)
        if actual == event:
            raise PowerLoss()

    monkeypatch.setattr(managed_memory_stage, "_save", fault)


@pytest.mark.parametrize(
    "event,before,expected,held",
    [
        ("memory_selection_dispatched", False, "outcome_unknown", 1),
        ("memory_selection_response_received", True, "outcome_unknown", 1),
        ("memory_selection_response_received", False, "completed", 0),
        ("memory_selection_adopted", False, "completed", 0),
        ("memory_fact_receipt_recorded", False, "completed", 0),
    ],
)
def test_restart_reuses_selection_and_cas_evidence(
    tmp_path, monkeypatch, event, before, expected, held
):
    memory = InMemoryMemory(backend_id="facts")
    path = tmp_path / "run.sqlite"
    first = Provider()
    local, _ = setup(path, first, memory=memory)
    with local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        with monkeypatch.context() as patch:
            checkpoint(patch, event, before=before)
            with pytest.raises(PowerLoss):
                asyncio.run(local.drive(h.run_id))
    second = Provider()
    local, _ = setup(path, second, memory=memory)
    with local:
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert local.memory_stages(h.run_id)[0]["status"] == expected
        assert second.business == 0 and second.selectors == 0
        assert local.diagnostics(h.run_id).budget["held"] == held
        assert len(memory.facts(local.scope, "auto-memory")) == (expected == "completed")
        assert first.business == 1 and first.selectors == (event != "memory_selection_dispatched")


@pytest.mark.parametrize(
    "mutation", ["state", "reservation", "receipt", "keys", "journal", "marker", "intent"]
)
def test_contradictory_selection_evidence_refuses_before_retry(tmp_path, monkeypatch, mutation):
    from ralf_agent.errors import DefinitionMismatch

    local, _ = setup(tmp_path / "run.sqlite")
    p = local.providers["default"]
    with local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        with monkeypatch.context() as patch:
            checkpoint(patch, "memory_selection_response_received")
            with pytest.raises(PowerLoss):
                asyncio.run(local.drive(h.run_id))
        with local.store.transaction():
            run = local.store.run(h.run_id)
            record = run["memory_stages"]["0"]
            if mutation == "state":
                record["selection"]["status"] = "prepared"
            elif mutation == "reservation":
                local.store.conn.execute(
                    "DELETE FROM reservations WHERE id=?", (record["selection"]["reservation_id"],)
                )
            elif mutation == "receipt":
                record["selection"]["response"]["output"] = {"keys": []}
            elif mutation == "keys":
                record["selection"]["keys"] = ["name"]
            elif mutation == "journal":
                record.pop("selection")
            elif mutation == "marker":
                run["actions"][0]["memory_stage"].pop("selection")
            else:
                record["selection"]["request"]["messages"][1]["content"] = "changed source"
            local.store.save_run(run)
        with pytest.raises(DefinitionMismatch):
            local.memory_stages(h.run_id)
        assert p.selectors == 1


@pytest.mark.parametrize(
    "event",
    [
        "memory_selection_dispatched",
        "memory_selection_response_received",
        "memory_selection_adopted",
    ],
)
def test_terminal_offline_selector_recovery_never_starts_new_work(tmp_path, monkeypatch, event):
    local, memory = setup(tmp_path / "run.sqlite")
    p = local.providers["default"]
    with local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        with monkeypatch.context() as patch:
            checkpoint(patch, event)
            with pytest.raises(PowerLoss):
                asyncio.run(local.drive(h.run_id))
        local.cancel(h.run_id, command_id="cancel")
        # Move cancelling to terminal as the original authority; model policy unchanged.
        with local.store.transaction():
            run = local.store.run(h.run_id)
            run["state"] = "cancelled"
            local.store.save_run(run)
        local.providers = {}
        assert asyncio.run(local.drive(h.run_id)).state == "cancelled"
        assert memory.facts(local.scope, "auto-memory") == []
        assert p.business == 1
        assert local.diagnostics(h.run_id).budget["held"] == int(event.endswith("dispatched"))


def test_provider_replacement_cannot_hide_actual_selector_drift(tmp_path):
    class Drift(Provider):
        async def complete(self, messages, tools):
            result = await super().complete(messages, tools)
            if messages[0]["content"].startswith("memory-field-selector:"):
                self.identity = {"kind": "changed", "version": "2"}
                local.providers["default"] = Provider()
            return result

    p = Drift()
    local, memory = setup(tmp_path / "run.sqlite", p)
    with local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "failed"
        assert local.memory_stages(h.run_id)[0]["selection"]["status"] == "response_received"
        local.providers = {}
        assert asyncio.run(local.drive(h.run_id)).state == "failed"
        assert local.diagnostics(h.run_id).budget["held"] == 0
        assert memory.facts(local.scope, "auto-memory") == []


def test_cancel_in_validator_prevents_selector_dispatch(tmp_path):
    class Cancel(Provider):
        def validate_request(self, messages, tools):
            if messages[0]["content"].startswith("memory-field-selector:"):
                local.cancel(h.run_id, command_id="cancel")

    p = Cancel()
    local, memory = setup(tmp_path / "run.sqlite", p)
    with local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "cancelled"
        assert p.selectors == 0 and memory.facts(local.scope, "auto-memory") == []
        assert local.diagnostics(h.run_id).budget == {"limit": 32, "spent": 1, "held": 0}


def test_custom_selection_cannot_add_other_grounded_fields(tmp_path):
    from ralf_agent import FactProposal

    class Other(type(policy())):
        def select(self, source, response):
            return [
                FactProposal("transient", source["result"]["transient"], ("result", "transient"))
            ]

    memory = InMemoryMemory(backend_id="facts")
    stage = Other(
        memory,
        admission=MemoryAdmissionPolicy(
            {"name": ("result", "name"), "transient": ("result", "transient")}
        ),
    )
    with engine(tmp_path / "run.sqlite", Provider(), stage_policy=stage) as local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert local.memory_stages(h.run_id)[0]["status"] == "failed"
        assert memory.facts(local.scope, "auto-memory") == []
        assert local.diagnostics(h.run_id).budget == {"limit": 32, "spent": 2, "held": 0}


def test_cancelled_waiter_retains_actual_selector_ownership(tmp_path):
    from ralf_agent.errors import ValidationError

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        class Slow(Provider):
            async def complete(self, messages, tools):
                if messages[0]["content"].startswith("memory-field-selector:"):
                    entered.set()
                    await release.wait()
                return await super().complete(messages, tools)

        p = Slow()
        local, memory = setup(tmp_path / "run.sqlite", p)
        try:
            h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
            task = asyncio.create_task(local.drive(h.run_id))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(ValidationError):
                local.close()
            release.set()
            for _ in range(200):
                if not local._operation_active(h.run_id):
                    break
                await asyncio.sleep(0.005)
            assert not local._operation_active(h.run_id)
            assert (await local.drive(h.run_id)).state == "cancelled"
            assert memory.facts(local.scope, "auto-memory") == [] and p.selectors == 1
            assert local.diagnostics(h.run_id).budget["held"] == 0
        finally:
            release.set()
            local.close()

    asyncio.run(exercise())
