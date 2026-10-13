"""Independent supplier behavior and original owned factory construction."""

import asyncio
import importlib
import os
import sqlite3

import pytest

from ralf_agent import AgentSpec, ComponentRegistry, RuntimeBuilder, recommended_profile
from ralf_agent.errors import DefinitionMismatch, ProviderError, ValidationError


def reference():
    try:
        return importlib.import_module("ralf_agent.model_adapter_contract_reference")
    except ModuleNotFoundError:
        pytest.fail("Independent ModelProvider source is missing")


def test_actual_requests_and_generic_responses_are_detached_without_call_deduplication(tmp_path):
    async def exercise():
        api = reference()
        source = api.ReferenceModelSource(tmp_path / "supplier.sqlite")
        provider = api.ReferenceSQLiteModelProvider(source)
        try:
            output = {"nested": [None, True, 3]}
            source.configure("output", {"output": output})
            output["nested"].append(99)
            messages = [{"role": "user", "content": "actual supplied input"}]
            result = await provider.complete(messages, [])
            messages[0]["content"] = "changed"
            assert result.output == {"nested": [None, True, 3]}
            result.output["nested"].append(88)
            second = await provider.complete(
                [{"role": "user", "content": "actual supplied input"}], []
            )
            assert second.output == {"nested": [None, True, 3]}
            assert second.usage is None
            assert source.requests()[0]["messages"] == [
                {"role": "user", "content": "actual supplied input"}
            ]
            assert source.audit()["model_calls"] == source.audit()["request_count"] == 2
            assert source.audit()["response_count"] == 2
            assert source.audit()["received_count"] == source.audit()["adopted_count"] == 0
            identity = provider.identity
            source.reopen()
            assert provider.identity == identity
        finally:
            descriptor = source._file_descriptor
            await source.aclose()
        with pytest.raises(OSError):
            os.fstat(descriptor)
        assert source.audit()["close_calls"] == 1

    asyncio.run(exercise())


def test_provider_reads_actual_descriptors_and_followup_tool_receipts(tmp_path):
    async def exercise():
        api = reference()
        source = api.ReferenceModelSource(tmp_path / "supplier.sqlite")
        try:
            source.configure("tools", {"name": "business.lookup", "arguments": {"key": "cache"}})
            provider = api.ReferenceSQLiteModelProvider(source)
            descriptors = [
                {
                    "type": "function",
                    "function": {"name": "business.lookup", "parameters": {"type": "object"}},
                }
            ]
            proposed = await provider.complete([{"role": "user", "content": "read"}], descriptors)
            assert len(proposed.tool_calls) == 1
            assert proposed.tool_calls[0].name == "business.lookup"
            assert proposed.tool_calls[0].arguments == {"key": "cache"}
            assert proposed.tool_calls[0].call_id is None
            followed = await provider.complete(
                [{"role": "tool", "content": '{"original":42}'}], descriptors
            )
            assert followed.output == {"tool_receipts": [{"original": 42}]}
            assert followed.tool_calls == ()
            with pytest.raises(ValidationError):
                await provider.complete([{"role": "user", "content": "read"}], [])
        finally:
            source.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("owned", [False, True])
def test_provider_factories_validate_before_allocation_and_observe_original_ownership(
    tmp_path, asynchronous, owned
):
    async def exercise():
        api = reference()
        path = tmp_path / "supplier.sqlite"
        source = api.ReferenceModelSource(path) if not owned else None
        registry = ComponentRegistry()
        api.register_model_reference_components(
            registry, source, asynchronous=asynchronous, owned=owned
        )
        profile = recommended_profile(
            provider={"adapter": "external-sqlite-model", "config": {"path": str(path)}}
        )
        builder = RuntimeBuilder(registry, base_dir=tmp_path)
        if source is None:
            assert not path.exists()
        instance = (
            await builder.abuild(profile, tmp_path / "runs.sqlite")
            if asynchronous
            else builder.build(profile, tmp_path / "runs.sqlite")
        )
        source = instance.providers["default"].source
        async with instance:
            handle = instance.submit(
                AgentSpec("reader", "Read supplied messages"), "actual", command_id="one", budget=4
            )
            done = await instance.drive(handle.run_id)
            assert done.state == "succeeded"
            assert done.result["last_user"] == "actual"
        assert source.audit()["close_calls"] == int(owned)
        source.close()
        bad_path = tmp_path / "not-allocated.sqlite"
        bad = recommended_profile(
            provider={
                "adapter": "external-sqlite-model",
                "config": {"path": str(bad_path), "key": "forbidden"},
            }
        )
        with pytest.raises(ValidationError):
            if asynchronous:
                await builder.abuild(bad, tmp_path / "bad-runs.sqlite")
            else:
                builder.build(bad, tmp_path / "bad-runs.sqlite")
        assert not bad_path.exists()

    asyncio.run(exercise())


def test_pinned_supplier_rejects_physical_and_dataset_replacement(tmp_path):
    api = reference()
    source = api.ReferenceModelSource(tmp_path / "supplier.sqlite")
    try:
        with sqlite3.connect(source.path) as connection:
            connection.execute("UPDATE model_resource SET dataset_id='changed'")
        with pytest.raises(DefinitionMismatch):
            source.record_request([], [])
    finally:
        source.close()


def test_actual_business_task_selects_incident_instead_of_fixed_fixture_prompt(tmp_path):
    async def exercise():
        api = reference()
        source = api.ReferenceModelSource(tmp_path / "supplier.sqlite")
        try:
            source.seed()
            with sqlite3.connect(source.path) as connection:
                connection.execute(
                    "INSERT INTO business_documents VALUES ('default','local-owner','database','Read the actual database runbook.','business://runbooks/database',1)"
                )
            provider = api.ReferenceSQLiteModelProvider(source)
            descriptors = [{"type": "function", "function": {"name": "lookup_incident"}}]
            response = await provider.complete(
                [{"role": "user", "content": '{"incident":"database"}'}], descriptors
            )
            assert response.tool_calls[0].arguments == {"incident": "database"}
        finally:
            source.close()

    asyncio.run(exercise())


def test_fixture_provider_domain_error_records_actual_request_before_failure(tmp_path):
    async def exercise():
        session = reference().offline_model_fixture().prepare("P05", tmp_path)
        try:
            session.inject_fault("provider-error")
            with pytest.raises(ProviderError):
                await session.provider.complete([{"role": "user", "content": "actual"}], [])
            assert session.audit()["request_count"] == 1
            assert session.audit()["response_count"] == 0
        finally:
            await session.resources[0].resource.aclose()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "task",
    [
        {"incident": "cache"},
        {"task": {"incident": "cache"}, "prior": []},
        {"task": {"incident": "cache"}, "results": {}},
        '{"incident":"cache"}',
        "Use the default incident",
    ],
)
def test_original_run_rejects_actual_receipt_for_a_different_requested_incident(tmp_path, task):
    from ralf_agent import ModelResponse, RuntimeProfile, ToolCall

    async def exercise():
        api = reference()
        source = api.ReferenceModelSource(tmp_path / "supplier.sqlite")
        source.seed()
        with sqlite3.connect(source.path) as connection:
            connection.execute(
                "INSERT INTO business_documents VALUES ('default','local-owner','database','Read the actual database runbook.','business://runbooks/database',1)"
            )
        registry = ComponentRegistry()
        api.register_model_reference_components(registry, source, owned=False)

        class WrongIncidentProvider:
            identity = {"kind": "actual-wrong-incident", "version": "1"}

            async def complete(self, messages, tools):
                import json

                receipts = [
                    json.loads(message["content"])
                    for message in messages
                    if message["role"] == "tool"
                ]
                if not receipts:
                    return ModelResponse(
                        tool_calls=(ToolCall("lookup_incident", {"incident": "database"}),)
                    )
                record = receipts[-1]
                return ModelResponse(
                    output={**record, "lookup": record, "sources": [], "members": []}
                )

        registry.register(
            "provider", "wrong-incident", lambda values, context: WrongIncidentProvider()
        )
        profile = RuntimeProfile(
            "actual-business",
            "1",
            {"default": {"adapter": "wrong-incident"}},
            {
                "tools": {"adapter": "incident-tools", "config": {"path": source.path}},
                "verifier": {"adapter": "incident-receipts"},
            },
        )
        instance = RuntimeBuilder(registry, base_dir=tmp_path).build(
            profile, tmp_path / "runs.sqlite"
        )
        try:
            async with instance:
                handle = instance.submit(
                    AgentSpec("reader", "Answer the actual incident", tools=("lookup_incident",)),
                    task,
                    command_id="wrong-incident",
                    budget=8,
                )
                done = await instance.drive(handle.run_id)
                actual = instance.store.run(handle.run_id)
                assert actual["actions"][1]["result"]["incident"] == "database"
                assert actual["actions"][1]["receipt"]
                assert done.state == "failed"
                assert done.error == {"code": "completion_rejected"}
        finally:
            source.close()

    asyncio.run(exercise())


def test_original_parent_rejects_consistent_child_receipts_for_a_different_parent_incident(
    tmp_path,
):
    from ralf_agent import DynamicWorkflowSpec, RuntimeProfile
    from ralf_agent.planning import PlanProposal, PlanStep

    async def exercise():
        api = reference()
        source = api.ReferenceModelSource(tmp_path / "supplier.sqlite")
        source.seed()
        with sqlite3.connect(source.path) as connection:
            connection.execute(
                "INSERT INTO business_documents VALUES ('default','local-owner','database','Read the actual database runbook.','business://runbooks/database',1)"
            )
        registry = ComponentRegistry()
        api.register_model_reference_components(registry, source, owned=False)

        class WrongIntentPlanner:
            identity = {"kind": "actual-wrong-intent-plan", "version": "1"}

            async def plan(self, request, caller):
                return PlanProposal(
                    [
                        PlanStep("research", "research", {"incident": "database"}),
                        PlanStep("review", "review", {"incident": "database"}),
                    ]
                )

        registry.register(
            "planners",
            "wrong-intent",
            lambda values, context: {"wrong-intent": WrongIntentPlanner()},
        )
        profile = RuntimeProfile(
            "actual-parent-business",
            "1",
            {"default": {"adapter": "external-sqlite-model", "config": {"path": source.path}}},
            {
                "tools": {"adapter": "incident-tools", "config": {"path": source.path}},
                "verifier": {"adapter": "incident-receipts"},
                "planners": {"adapter": "wrong-intent"},
                "parent_completion_policies": {"adapter": "incident-members"},
            },
        )
        child = AgentSpec(
            "reader", "Answer actual supplied child incident", tools=("lookup_incident",)
        )
        definition = DynamicWorkflowSpec(
            "business",
            {"research": child, "review": child},
            planner="wrong-intent",
            child_budget=8,
            max_revisions=1,
            completion_policy="business",
        )
        instance = RuntimeBuilder(registry, base_dir=tmp_path).build(
            profile, tmp_path / "runs.sqlite"
        )
        try:
            async with instance:
                handle = instance.submit(
                    definition, {"incident": "cache"}, command_id="wrong-parent-intent", budget=32
                )
                done = await instance.drive(handle.run_id)
                actual = instance.store.run(handle.run_id)
                children = actual["orchestration"]["children"]
                assert all(
                    instance.store.run(child["run_id"])["state"] == "succeeded"
                    for child in children
                )
                assert all(
                    instance.store.run(child["run_id"])["result"]["incident"] == "database"
                    for child in children
                )
                assert done.state == "failed"
                assert done.error == {"code": "completion_rejected"}
        finally:
            source.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "task",
    [
        {"incident": "database"},
        '{"incident":"database"}',
        {"task": '{"incident":"database"}', "prior": []},
    ],
)
def test_original_run_accepts_requested_incident_in_object_string_and_child_wrapper(tmp_path, task):
    from ralf_agent import RuntimeProfile

    async def exercise():
        api = reference()
        source = api.ReferenceModelSource(tmp_path / "supplier.sqlite")
        source.seed()
        with sqlite3.connect(source.path) as connection:
            connection.execute(
                "INSERT INTO business_documents VALUES ('default','local-owner','database','Read the actual database runbook.','business://runbooks/database',1)"
            )
        registry = ComponentRegistry()
        api.register_model_reference_components(registry, source, owned=False)
        profile = RuntimeProfile(
            "actual-correct-business",
            "1",
            {"default": {"adapter": "external-sqlite-model", "config": {"path": source.path}}},
            {
                "tools": {"adapter": "incident-tools", "config": {"path": source.path}},
                "verifier": {"adapter": "incident-receipts"},
            },
        )
        instance = RuntimeBuilder(registry, base_dir=tmp_path).build(
            profile, tmp_path / "runs.sqlite"
        )
        try:
            async with instance:
                handle = instance.submit(
                    AgentSpec(
                        "reader", "Answer actual supplied incident", tools=("lookup_incident",)
                    ),
                    task,
                    command_id="correct-wrapped-intent",
                    budget=8,
                )
                done = await instance.drive(handle.run_id)
                assert done.state == "succeeded"
                assert done.result["incident"] == "database"
                assert done.result["recommendation"] == "Read the actual database runbook."
        finally:
            source.close()

    asyncio.run(exercise())
