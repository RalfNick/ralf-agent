import asyncio
from contextlib import asynccontextmanager, contextmanager

import pytest

from ralf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore
from ralf_agent.errors import AuthorizationDenied

from .helpers import ScriptedProvider, tool_response
from .test_review_engine_boundaries import write_registry


@pytest.mark.parametrize(
    "wrapper,return_from_function",
    [
        pytest.param(contextmanager, False, id="contextmanager-policy"),
        pytest.param(asynccontextmanager, False, id="asynccontextmanager-policy"),
        pytest.param(contextmanager, True, id="returned-contextmanager"),
        pytest.param(asynccontextmanager, True, id="returned-asynccontextmanager"),
    ],
)
def test_context_manager_policy_cannot_authorize_a_write(tmp_path, wrapper, return_from_function):
    effects, policy_body_calls = [], []

    if wrapper is contextmanager:

        @contextmanager
        def deferred_deny(scope, spec, arguments):
            policy_body_calls.append(arguments)
            raise AuthorizationDenied("The host denied this write")
            yield

    else:

        @asynccontextmanager
        async def deferred_deny(scope, spec, arguments):
            policy_body_calls.append(arguments)
            raise AuthorizationDenied("The host denied this write")
            yield

    def returning_policy(scope, spec, arguments):
        return deferred_deny(scope, spec, arguments)

    policy = returning_policy if return_from_function else deferred_deny
    provider = ScriptedProvider([tool_response(), ModelResponse(output="must not succeed")])
    with LocalEngine(
        SQLiteStore(tmp_path / "context-policy.db"),
        providers={"default": provider},
        tools=write_registry(effects),
        policy=policy,
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="start")
        snapshot = asyncio.run(runtime.drive(run.run_id))

        assert snapshot.state == "failed"
        assert snapshot.error == {"code": "validation_error"}
        assert effects == []
        assert provider.calls == 1
        assert policy_body_calls == []
        assert not any(event.kind == "tool_dispatch_intent" for event in runtime.events(run.run_id))


@pytest.mark.parametrize(
    "decision",
    [
        pytest.param(True, id="true"),
        pytest.param(False, id="false"),
        pytest.param(0, id="zero"),
        pytest.param("allow", id="text"),
        pytest.param({}, id="empty-mapping"),
        pytest.param({"allowed": True}, id="mapping"),
        pytest.param([], id="empty-list"),
        pytest.param(object(), id="opaque-object"),
    ],
)
def test_only_none_is_a_valid_synchronous_authorization_return(tmp_path, decision):
    effects = []

    def policy(scope, spec, arguments):
        return decision

    provider = ScriptedProvider([tool_response(), ModelResponse(output="must not succeed")])
    with LocalEngine(
        SQLiteStore(tmp_path / "return-policy.db"),
        providers={"default": provider},
        tools=write_registry(effects),
        policy=policy,
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="start")
        snapshot = asyncio.run(runtime.drive(run.run_id))

        assert snapshot.state == "failed"
        assert snapshot.error == {"code": "validation_error"}
        assert effects == []
        assert provider.calls == 1
        assert not any(event.kind == "tool_dispatch_intent" for event in runtime.events(run.run_id))


@pytest.mark.parametrize("deny", [False, True])
def test_sync_policy_allow_and_raise_remain_supported(tmp_path, deny):
    effects, policy_calls = [], []

    def policy(scope, spec, arguments):
        policy_calls.append((scope, spec.name, arguments))
        if deny:
            raise AuthorizationDenied("The host denied this write")
        return None

    provider = ScriptedProvider([tool_response(), ModelResponse(output="confirmed")])
    with LocalEngine(
        SQLiteStore(tmp_path / "sync-policy.db"),
        providers={"default": provider},
        tools=write_registry(effects),
        policy=policy,
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="start")
        snapshot = asyncio.run(runtime.drive(run.run_id))

        assert snapshot.state == ("failed" if deny else "succeeded")
        assert snapshot.error == ({"code": "authorization_denied"} if deny else None)
        assert len(effects) == (0 if deny else 1)
        assert len(policy_calls) == 1
        assert any(
            event.kind == "tool_dispatch_intent" for event in runtime.events(run.run_id)
        ) is (not deny)
