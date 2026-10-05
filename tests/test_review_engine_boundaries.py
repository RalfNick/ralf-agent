import asyncio
import inspect

import pytest

from ralf_agent import (
    AgentSpec,
    InMemoryMemory,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
)
from ralf_agent.errors import AuthorizationDenied, ValidationError

from .helpers import ScriptedProvider, tool_response


def write_registry(effects):
    async def change(arguments, context):
        effects.append(context.effect_key)
        return arguments

    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "change",
            "Write a test business value",
            {"type": "object"},
            effect="unqueryable_write",
            requires_approval=False,
        ),
        change,
    )
    return tools


@pytest.mark.parametrize("callable_object", [False, True])
def test_async_authorization_configuration_is_rejected(tmp_path, callable_object):
    effects = []

    async def deny(scope, spec, arguments):
        raise AuthorizationDenied("The host denied this write")

    class AsyncPolicy:
        async def __call__(self, scope, spec, arguments):
            await deny(scope, spec, arguments)

    policy = AsyncPolicy() if callable_object else deny
    with SQLiteStore(tmp_path / "async-policy.db") as store:
        runtime = None
        try:
            with pytest.raises(ValidationError):
                runtime = LocalEngine(
                    store,
                    providers={"default": ScriptedProvider([tool_response()])},
                    tools=write_registry(effects),
                    policy=policy,
                )
            assert effects == []
            assert store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        finally:
            if runtime is not None:
                runtime.close()


@pytest.mark.parametrize("callable_object", [False, True])
def test_generator_authorization_configuration_is_rejected(tmp_path, callable_object):
    effects = []

    def deny(scope, spec, arguments):
        raise AuthorizationDenied("The host denied this write")
        yield

    class GeneratorPolicy:
        def __call__(self, scope, spec, arguments):
            yield from deny(scope, spec, arguments)

    policy = GeneratorPolicy() if callable_object else deny
    with SQLiteStore(tmp_path / "generator-policy.db") as store:
        runtime = None
        try:
            with pytest.raises(ValidationError):
                runtime = LocalEngine(
                    store,
                    providers={"default": ScriptedProvider([tool_response()])},
                    tools=write_registry(effects),
                    policy=policy,
                )
            assert effects == []
            assert store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        finally:
            if runtime is not None:
                runtime.close()


def test_sync_policy_returning_a_generator_cannot_dispatch_a_write(tmp_path):
    effects, generators = [], []

    def deny():
        raise AuthorizationDenied("The host denied this write")
        yield

    def policy(scope, spec, arguments):
        decision = deny()
        generators.append(decision)
        return decision

    provider = ScriptedProvider([tool_response(), ModelResponse(output="must not succeed")])
    with LocalEngine(
        SQLiteStore(tmp_path / "returned-generator-policy.db"),
        providers={"default": provider},
        tools=write_registry(effects),
        policy=policy,
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="start")
        try:
            snapshot = asyncio.run(runtime.drive(run.run_id))
            assert snapshot.state == "failed"
            assert snapshot.error == {"code": "validation_error"}
            assert effects == []
            assert provider.calls == 1
            assert all(inspect.getgeneratorstate(g) == inspect.GEN_CLOSED for g in generators)
        finally:
            for decision in generators:
                decision.close()


def test_sync_policy_returning_a_coroutine_cannot_dispatch_a_write(tmp_path):
    effects, coroutines = [], []

    async def deny():
        raise AuthorizationDenied("The host denied this write")

    def policy(scope, spec, arguments):
        decision = deny()
        coroutines.append(decision)
        return decision

    provider = ScriptedProvider([tool_response(), ModelResponse(output="must not succeed")])
    with LocalEngine(
        SQLiteStore(tmp_path / "awaitable-policy.db"),
        providers={"default": provider},
        tools=write_registry(effects),
        policy=policy,
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="start")
        try:
            snapshot = asyncio.run(runtime.drive(run.run_id))
            assert snapshot.state == "failed"
            assert snapshot.error == {"code": "validation_error"}
            assert effects == []
            assert provider.calls == 1
            assert all(inspect.getcoroutinestate(c) == inspect.CORO_CLOSED for c in coroutines)
        finally:
            for decision in coroutines:
                decision.close()


def test_sync_policy_returning_another_awaitable_cannot_dispatch_a_write(tmp_path):
    effects = []

    class AuthorizationDecision:
        awaited = False

        def __await__(self):
            self.awaited = True
            raise AuthorizationDenied("The host denied this write")
            yield

    decision = AuthorizationDecision()
    provider = ScriptedProvider([tool_response(), ModelResponse(output="must not succeed")])
    with LocalEngine(
        SQLiteStore(tmp_path / "custom-awaitable-policy.db"),
        providers={"default": provider},
        tools=write_registry(effects),
        policy=lambda scope, spec, arguments: decision,
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="start")
        snapshot = asyncio.run(runtime.drive(run.run_id))
        assert snapshot.state == "failed"
        assert snapshot.error == {"code": "validation_error"}
        assert effects == []
        assert not decision.awaited
        assert provider.calls == 1


@pytest.mark.parametrize("output", [None, "", " \n\t "])
def test_empty_custom_provider_output_is_not_a_successful_decision(tmp_path, output):
    sessions = InMemoryMemory()
    with LocalEngine(
        SQLiteStore(tmp_path / "empty-response.db"),
        providers={"default": ScriptedProvider([ModelResponse(output=output)])},
        tools=ToolRegistry(),
        session_store=sessions,
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x"), "x", command_id="start", session_id="shared")
        snapshot = asyncio.run(runtime.drive(run.run_id))
        assert snapshot.state == "failed"
        assert snapshot.error == {"code": "validation_error"}
        assert sessions.read(runtime.scope, "shared") == (0, [])
        assert not any(event.kind == "decision_adopted" for event in runtime.events(run.run_id))


@pytest.mark.parametrize("output", ['""', '"  "'])
def test_json_encoded_empty_text_cannot_bypass_final_decision_validation(tmp_path, output):
    sessions = InMemoryMemory()
    with LocalEngine(
        SQLiteStore(tmp_path / "encoded-empty-response.db"),
        providers={"default": ScriptedProvider([ModelResponse(output=output)])},
        tools=ToolRegistry(),
        session_store=sessions,
    ) as runtime:
        run = runtime.submit(
            AgentSpec("a", "x", output_schema={"type": "string"}),
            "x",
            command_id="start",
            session_id="shared",
        )
        snapshot = asyncio.run(runtime.drive(run.run_id))
        assert snapshot.state == "failed"
        assert snapshot.error == {"code": "validation_error"}
        assert sessions.read(runtime.scope, "shared") == (0, [])
        assert not any(event.kind == "decision_adopted" for event in runtime.events(run.run_id))


@pytest.mark.parametrize("output", [None, "null"])
@pytest.mark.parametrize("schema", [{"type": "null"}, {"type": ["string", "null"]}])
def test_output_schema_can_explicitly_allow_a_null_result(tmp_path, output, schema):
    sessions = InMemoryMemory()
    with LocalEngine(
        SQLiteStore(tmp_path / "null-response.db"),
        providers={"default": ScriptedProvider([ModelResponse(output=output)])},
        tools=ToolRegistry(),
        session_store=sessions,
    ) as runtime:
        run = runtime.submit(
            AgentSpec("a", "x", output_schema=schema),
            "x",
            command_id="start",
            session_id="shared",
        )
        snapshot = asyncio.run(runtime.drive(run.run_id))
        assert snapshot.state == "succeeded"
        assert snapshot.result is None
        revision, messages = sessions.read(runtime.scope, "shared")
        assert revision == 1
        assert messages[0]["content"] is None


@pytest.mark.parametrize("output", [False, 0, {}, []])
def test_valid_falsy_json_output_is_a_complete_decision(tmp_path, output):
    with LocalEngine(
        SQLiteStore(tmp_path / "falsy-response.db"),
        providers={"default": ScriptedProvider([ModelResponse(output=output)])},
        tools=ToolRegistry(),
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x"), "x", command_id="start")
        snapshot = asyncio.run(runtime.drive(run.run_id))
        assert snapshot.state == "succeeded"
        assert snapshot.result == output


def test_tool_proposal_does_not_require_a_final_output(tmp_path):
    effects = []
    provider = ScriptedProvider([tool_response(), ModelResponse(output="write confirmed")])
    with LocalEngine(
        SQLiteStore(tmp_path / "proposal-response.db"),
        providers={"default": provider},
        tools=write_registry(effects),
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="start")
        snapshot = asyncio.run(runtime.drive(run.run_id))
        assert snapshot.state == "succeeded"
        assert snapshot.result == "write confirmed"
        assert len(effects) == 1
        assert provider.calls == 2


@pytest.mark.parametrize("replacement", ["adapter_backend", "engine_component"])
def test_session_backend_change_during_append_cannot_confirm_the_old_release(tmp_path, replacement):
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()
        first = InMemoryMemory(backend_id="remote:first")
        second = InMemoryMemory(backend_id="remote:second")

        class SwitchingSession:
            def __init__(self):
                self.backend = first

            @property
            def backend_id(self):
                return self.backend.backend_id

            async def read(self, *args):
                return self.backend.read(*args)

            async def append(self, *args, **kwargs):
                started.set()
                await release.wait()
                return self.backend.append(*args, **kwargs)

        sessions = SwitchingSession()
        with LocalEngine(
            SQLiteStore(tmp_path / "append-release.db"),
            providers={"default": ScriptedProvider([ModelResponse(output="completed")])},
            tools=ToolRegistry(),
            session_store=sessions,
        ) as runtime:
            run = runtime.submit(AgentSpec("a", "x"), "x", command_id="start", session_id="shared")
            drive = asyncio.create_task(runtime.drive(run.run_id))
            try:
                await asyncio.wait_for(started.wait(), 1)
                if replacement == "adapter_backend":
                    sessions.backend = second
                else:
                    runtime.sessions = second
            finally:
                release.set()
                snapshot = await drive
            assert snapshot.state == "failed"
            assert snapshot.error == {"code": "definition_mismatch"}
            assert snapshot.result is None
            assert not any(event.kind == "run_succeeded" for event in runtime.events(run.run_id))
            written_backend = second if replacement == "adapter_backend" else first
            revision, messages = written_backend.read(runtime.scope, "shared")
            assert revision == 1
            assert messages[0]["content"] == "completed"

    asyncio.run(exercise())
