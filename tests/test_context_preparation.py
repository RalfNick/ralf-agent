import asyncio
import copy

import pytest

from ralf_agent import AgentSpec, ModelResponse, ToolCall, ToolRegistry, ToolSpec
from ralf_agent.types import canonical
from tests.test_managed_context import pipeline
from tests.test_managed_memory_stage import engine


class Provider:
    identity = {"kind": "context-stage-test", "version": "1"}

    def __init__(self, summary=None):
        self.business, self.summaries, self.requests = 0, 0, []
        self.summary = summary or ModelResponse(
            output={"text": "Earlier lookup returned large evidence."}
        )

    async def complete(self, messages, tools):
        self.requests.append(copy.deepcopy(messages))
        if messages[0]["content"].startswith("context-summary:"):
            assert tools == []
            self.summaries += 1
            if isinstance(self.summary, Exception):
                raise self.summary
            return self.summary
        self.business += 1
        if self.business <= 2:
            return ModelResponse(
                tool_calls=[
                    ToolCall("lookup", {"round": self.business}, call_id=f"call-{self.business}")
                ]
            )
        return ModelResponse(output="finished")


def tools():
    registry = ToolRegistry()

    def lookup(arguments, ctx):
        return "OLD" * 1000 if arguments["round"] == 1 else "LATEST evidence" + "NEW" * 400

    registry.register(
        ToolSpec(
            "lookup",
            "Read evidence",
            {"type": "object", "properties": {"round": {"type": "integer"}}, "required": ["round"]},
            effect="read_only",
            cost=0,
        ),
        lookup,
    )
    return registry


def spec():
    return AgentSpec("a", "Answer", tools=["lookup"], max_context_chars=4000)


@pytest.mark.parametrize("mode", ["excerpt", "model"])
def test_stage_is_auxiliary_pinned_and_budgeted(tmp_path, mode):
    provider = Provider()
    with engine(
        tmp_path / "run.sqlite",
        provider,
        tools=tools(),
        context_assembler=pipeline(mode=mode, summary_max_chars=512),
    ) as local:
        h = local.submit(spec(), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        records = local.context_stages(h.run_id)
        assert len(records) == 1 and records[0]["status"] == "completed"
        assert provider.business == 3 and provider.summaries == (mode == "model")
        info = local.diagnostics(h.run_id)
        assert info.budget == {"limit": 32, "held": 0, "spent": 3 + (mode == "model")}
        assert len(info.snapshot.actions) == 5
        request = next(m for m in reversed(provider.requests) if m[0]["content"] == "Answer")
        assert "Summary of untrusted" in canonical(request)
        assert "LATEST evidence" in canonical(request)
        assert "OLD" * 1000 in canonical(local.store.run(h.run_id)["messages"])


def test_unknown_summary_falls_back_and_is_not_repeated(tmp_path):
    provider = Provider(RuntimeError("connection lost"))
    with engine(
        tmp_path / "run.sqlite",
        provider,
        tools=tools(),
        context_assembler=pipeline(mode="model", summary_max_chars=512),
    ) as local:
        h = local.submit(spec(), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert local.context_stages(h.run_id)[0]["status"] == "outcome_unknown"
        assert local.diagnostics(h.run_id).budget == {"limit": 32, "held": 1, "spent": 3}
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert provider.summaries == 1 and provider.business == 3


@pytest.mark.parametrize(
    "response",
    [
        ModelResponse(),
        ModelResponse(output={"text": "  "}),
        ModelResponse(output={"text": "bad"}, tool_calls=[ToolCall("lookup", {})]),
    ],
)
def test_completed_invalid_response_is_charged_and_falls_back(tmp_path, response):
    provider = Provider(response)
    with engine(
        tmp_path / "run.sqlite",
        provider,
        tools=tools(),
        context_assembler=pipeline(mode="model", summary_max_chars=512),
    ) as local:
        h = local.submit(spec(), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert local.context_stages(h.run_id)[0]["status"] == "failed"
        assert local.diagnostics(h.run_id).budget["spent"] == 4
        assert "Summary of untrusted" not in canonical(provider.requests[-1])


class PowerLoss(BaseException):
    pass


def checkpoint(monkeypatch, event, *, before=False):
    from ralf_agent import context_preparation

    if event == "context_preparation_dispatched":
        dispatch = context_preparation._dispatch

        def fail_dispatch(*args):
            dispatch(*args)
            raise PowerLoss()

        monkeypatch.setattr(context_preparation, "_dispatch", fail_dispatch)
        return
    original = context_preparation._save

    def fail(engine, run_id, key, record, actual):
        if actual == event and before:
            raise PowerLoss()
        original(engine, run_id, key, record, actual)
        if actual == event:
            raise PowerLoss()

    monkeypatch.setattr(context_preparation, "_save", fail)


@pytest.mark.parametrize(
    "event,before,expected,held",
    [
        ("context_preparation_dispatched", False, "outcome_unknown", 1),
        ("context_preparation_response_received", True, "outcome_unknown", 1),
        ("context_preparation_response_received", False, "completed", 0),
        ("context_preparation_adopted", False, "completed", 0),
    ],
)
def test_restart_uses_original_summary_evidence(
    tmp_path, monkeypatch, event, before, expected, held
):
    path = tmp_path / "run.sqlite"
    first = Provider()
    with engine(path, first, tools=tools(), context_assembler=pipeline(mode="model")) as local:
        h = local.submit(spec(), "q", command_id="s")
        with monkeypatch.context() as patch:
            checkpoint(patch, event, before=before)
            with pytest.raises(PowerLoss):
                asyncio.run(local.drive(h.run_id))
    second = Provider()
    second.business = 2
    with engine(path, second, tools=tools(), context_assembler=pipeline(mode="model")) as local:
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert local.context_stages(h.run_id)[0]["status"] == expected
        assert second.summaries == 0 and second.business == 3
        assert first.business == 2 and first.summaries == (
            event != "context_preparation_dispatched"
        )
        assert local.diagnostics(h.run_id).budget["held"] == held


@pytest.mark.parametrize(
    "event", ["context_preparation_dispatched", "context_preparation_response_received"]
)
def test_terminal_recovery_never_starts_models(tmp_path, monkeypatch, event):
    path = tmp_path / "run.sqlite"
    provider = Provider()
    with engine(path, provider, tools=tools(), context_assembler=pipeline(mode="model")) as local:
        h = local.submit(spec(), "q", command_id="s")
        with monkeypatch.context() as patch:
            checkpoint(patch, event)
            with pytest.raises(PowerLoss):
                asyncio.run(local.drive(h.run_id))
        local.cancel(h.run_id, command_id="cancel")
        asyncio.run(local.drive(h.run_id))
        assert local.status(h.run_id).state == "cancelled"
        # Terminal reads/adoption must work without the model being available.
        local.providers = {}
        assert asyncio.run(local.drive(h.run_id)).state == "cancelled"
        record = local.context_stages(h.run_id)[0]
        assert record["status"] == ("outcome_unknown" if event.endswith("dispatched") else "failed")
        assert provider.business == 2
        assert local.diagnostics(h.run_id).budget["held"] == (event.endswith("dispatched"))


@pytest.mark.parametrize(
    "mutation",
    [
        "journal",
        "intent",
        "receipt",
        "snapshot",
        "coverage",
        "state",
        "reservation",
        "settlement",
        "action",
    ],
)
def test_missing_or_contradictory_evidence_fails_closed(tmp_path, mutation):
    from ralf_agent.errors import DefinitionMismatch

    provider = Provider()
    with engine(
        tmp_path / "run.sqlite", provider, tools=tools(), context_assembler=pipeline(mode="model")
    ) as local:
        h = local.submit(spec(), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        with local.store.transaction():
            run = local.store.run(h.run_id)
            key, record = next(iter(run["context_preparations"].items()))
            if mutation == "journal":
                run.pop("context_preparations")
            elif mutation == "intent":
                run["context_preparation_markers"].clear()
            elif mutation == "receipt":
                run["context_preparation_receipts"].clear()
            elif mutation == "snapshot":
                run["context_preparation_snapshots"].clear()
            elif mutation == "coverage":
                record["plan"]["coverage"] = []
            elif mutation == "state":
                record["status"] = "skipped"
            elif mutation == "reservation":
                local.store.conn.execute(
                    "DELETE FROM reservations WHERE id=?", (record["reservation_id"],)
                )
            elif mutation == "settlement":
                local.store.conn.execute(
                    "UPDATE reservations SET actual=0 WHERE id=?", (record["reservation_id"],)
                )
            else:
                run["actions"][-1]["context_preparation"]["key"] = "missing"
            local.store.save_run(run)
        with pytest.raises(DefinitionMismatch):
            local.context_stages(h.run_id)
        with pytest.raises(DefinitionMismatch):
            asyncio.run(local.drive(h.run_id))
        assert provider.business == 3 and provider.summaries == 1


def test_provider_drift_keeps_response_for_offline_terminal_settlement(tmp_path):
    class Drift(Provider):
        async def complete(self, messages, tools):
            response = await super().complete(messages, tools)
            if messages[0]["content"].startswith("context-summary:"):
                self.identity = {"kind": "replaced", "version": "2"}
            return response

    provider = Drift()
    with engine(
        tmp_path / "run.sqlite", provider, tools=tools(), context_assembler=pipeline(mode="model")
    ) as local:
        h = local.submit(spec(), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "failed"
        assert local.context_stages(h.run_id)[0]["status"] == "response_received"
        assert local.diagnostics(h.run_id).budget["held"] == 1
        local.providers = {}
        assert asyncio.run(local.drive(h.run_id)).state == "failed"
        assert local.context_stages(h.run_id)[0]["status"] == "failed"
        assert local.diagnostics(h.run_id).budget == {"limit": 32, "spent": 3, "held": 0}
        assert provider.business == 2


def test_cancellation_waits_for_managed_summary_and_stops_business_dispatch(tmp_path):
    from ralf_agent.errors import ValidationError

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        class Slow(Provider):
            async def complete(self, messages, tools):
                if messages[0]["content"].startswith("context-summary:"):
                    entered.set()
                    await release.wait()
                return await super().complete(messages, tools)

        provider = Slow()
        local = engine(
            tmp_path / "run.sqlite",
            provider,
            tools=tools(),
            context_assembler=pipeline(mode="model"),
        )
        try:
            h = local.submit(spec(), "q", command_id="s")
            drive = asyncio.create_task(local.drive(h.run_id))
            await asyncio.wait_for(entered.wait(), 2)
            drive.cancel()
            with pytest.raises(asyncio.CancelledError):
                await drive
            with pytest.raises(ValidationError):
                local.close()
            release.set()
            for _ in range(200):
                if not local._operation_active(h.run_id):
                    break
                await asyncio.sleep(0.001)
            assert not local._operation_active(h.run_id)
            assert (await local.drive(h.run_id)).state == "cancelled"
            assert provider.business == 2 and provider.summaries == 1
            assert local.diagnostics(h.run_id).budget["held"] == 0
        finally:
            release.set()
            local.close()

    asyncio.run(exercise())


def test_budget_or_input_limit_skips_summary_without_hidden_calls(tmp_path):
    provider = Provider()
    with engine(
        tmp_path / "run.sqlite",
        provider,
        tools=tools(),
        context_assembler=pipeline(mode="model", source_max_chars=128),
    ) as local:
        h = local.submit(spec(), "q", command_id="s", budget=3)
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert local.context_stages(h.run_id)[0]["error"]["code"] == "summary_source_limit"
        assert provider.summaries == 0
        assert local.diagnostics(h.run_id).budget == {"limit": 3, "held": 0, "spent": 3}


def test_fixed_fact_versions_are_revalidated_after_summary(tmp_path):
    from ralf_agent import InMemoryMemory, MemoryRecallPolicy, Scope

    memory = InMemoryMemory(backend_id="facts")
    memory.put_fact(Scope(), "a", "known", "old", expected_version=0)

    class Change(Provider):
        async def complete(self, messages, tools):
            result = await super().complete(messages, tools)
            if messages[0]["content"].startswith("context-summary:"):
                memory.put_fact(Scope(), "a", "known", "replacement", expected_version=1)
            return result

    provider = Change()
    with engine(
        tmp_path / "run.sqlite",
        provider,
        tools=tools(),
        context_assembler=pipeline(mode="model"),
        memory_store=memory,
        recall_policy=MemoryRecallPolicy(),
    ) as local:
        h = local.submit(spec(), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "failed"
        assert provider.business == 2 and provider.summaries == 1
        assert local.context_stages(h.run_id)[0]["status"] == "completed"
        assert local.diagnostics(h.run_id).budget["spent"] == 3


def test_sequence_and_rule_memory_share_original_budget_and_authority(tmp_path):
    from ralf_agent import InMemoryMemory, MemoryAdmissionPolicy, WorkflowSpec
    from tests.test_managed_memory_stage import policy

    memory = InMemoryMemory(backend_id="write-facts")
    provider = Provider()
    with engine(
        tmp_path / "run.sqlite",
        provider,
        tools=tools(),
        context_assembler=pipeline(mode="model"),
        stage_policy=policy(memory, admission=MemoryAdmissionPolicy({"answer": ("result",)})),
    ) as local:
        h = local.submit(
            WorkflowSpec("seq", [spec(), AgentSpec("second", "Second")]), "q", command_id="s"
        )
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert len(local.context_stages(h.run_id)) == 1
        assert len(local.memory_stages(h.run_id)) == 2
        assert local.diagnostics(h.run_id).budget["spent"] == 7
        assert local.store.conn.execute("SELECT value FROM metadata").fetchone()[0] == "8"


def test_completed_malformed_provider_value_is_charged(tmp_path):
    class Wrong(Provider):
        async def complete(self, messages, tools):
            if messages[0]["content"].startswith("context-summary:"):
                self.summaries += 1
                return {"text": "wrong DTO"}
            return await super().complete(messages, tools)

    provider = Wrong()
    with engine(
        tmp_path / "run.sqlite", provider, tools=tools(), context_assembler=pipeline(mode="model")
    ) as local:
        h = local.submit(spec(), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert local.context_stages(h.run_id)[0]["status"] == "failed"
        assert local.diagnostics(h.run_id).budget == {"limit": 32, "held": 0, "spent": 4}


def test_summary_request_validation_runs_before_reservation_and_dispatch(tmp_path):
    from ralf_agent.errors import ValidationError

    class Validating(Provider):
        def validate_request(self, messages, tools):
            if messages[0]["content"].startswith("context-summary:"):
                raise ValidationError("unsupported summary request")

    provider = Validating()
    with engine(
        tmp_path / "run.sqlite", provider, tools=tools(), context_assembler=pipeline(mode="model")
    ) as local:
        h = local.submit(spec(), "q", command_id="s", budget=3)
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert provider.summaries == 0 and provider.business == 3
        assert local.context_stages(h.run_id)[0]["status"] == "failed"
        assert local.diagnostics(h.run_id).budget == {"limit": 3, "spent": 3, "held": 0}


@pytest.mark.parametrize("proof_state", ["reserved", "unknown"])
def test_prepared_stage_cannot_reuse_existing_dispatch_reservation(
    tmp_path, monkeypatch, proof_state
):
    from ralf_agent.errors import DefinitionMismatch

    provider = Provider()
    path = tmp_path / "run.sqlite"
    with engine(path, provider, tools=tools(), context_assembler=pipeline(mode="model")) as local:
        h = local.submit(spec(), "q", command_id="s")
        with monkeypatch.context() as patch:
            checkpoint(patch, "context_preparation_response_received", before=True)
            with pytest.raises(PowerLoss):
                asyncio.run(local.drive(h.run_id))
        with local.store.transaction():
            run = local.store.run(h.run_id)
            record = next(iter(run["context_preparations"].values()))
            record["status"] = "prepared"
            if proof_state == "unknown":
                local.store.mark_unknown(record["reservation_id"])
            local.store.save_run(run)
        with pytest.raises(DefinitionMismatch):
            local.context_stages(h.run_id)
        with pytest.raises(DefinitionMismatch):
            asyncio.run(local.drive(h.run_id))
        assert provider.summaries == 1


def test_actual_summary_provider_drift_cannot_hide_behind_registry_replacement(tmp_path):
    class Summary:
        identity = {"kind": "separate-summary", "version": "1"}
        calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            self.identity = {"kind": "changed", "version": "2"}
            local.providers["summary"] = Summary()
            return ModelResponse(output={"text": "wrong release evidence"})

    primary, actual = Provider(), Summary()
    with engine(
        tmp_path / "run.sqlite",
        primary,
        tools=tools(),
        context_assembler=pipeline(mode="model", provider="summary"),
    ) as local:
        local.providers["summary"] = actual
        h = local.submit(spec(), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "failed"
        assert primary.business == 2 and actual.calls == 1
        assert local.context_stages(h.run_id)[0]["status"] == "response_received"
        local.providers = {}
        assert asyncio.run(local.drive(h.run_id)).state == "failed"
        assert local.context_stages(h.run_id)[0]["status"] == "failed"
        assert local.diagnostics(h.run_id).budget == {"limit": 32, "held": 0, "spent": 3}


def test_cancel_in_summary_validator_prevents_actual_dispatch(tmp_path):
    class Summary:
        identity = {"kind": "cancel-summary", "version": "1"}
        calls = 0

        def validate_request(self, messages, tools):
            local.cancel(h.run_id, command_id="validator-cancel")

        async def complete(self, messages, tools):
            self.calls += 1
            return ModelResponse(output={"text": "unnecessary summary"})

    primary, summary = Provider(), Summary()
    with engine(
        tmp_path / "run.sqlite",
        primary,
        tools=tools(),
        context_assembler=pipeline(mode="model", provider="summary"),
    ) as local:
        local.providers["summary"] = summary
        h = local.submit(spec(), "q", command_id="s")
        assert asyncio.run(local.drive(h.run_id)).state == "cancelled"
        assert summary.calls == 0 and primary.business == 2
        assert asyncio.run(local.drive(h.run_id)).state == "cancelled"
        assert local.context_stages(h.run_id)[0]["status"] == "skipped"
        assert local.diagnostics(h.run_id).budget == {"limit": 32, "held": 0, "spent": 2}
