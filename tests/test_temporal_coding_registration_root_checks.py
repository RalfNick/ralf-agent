"""Native registration checks each physical root freshly, without duplicate plain checks."""

import asyncio

import pytest

from ralf_agent import DeploymentAdmissionPolicy, TemporalRuntime, ToolRegistry
from ralf_agent import temporal_coding_protocol as native
from ralf_agent.codex_connected_runner import ConnectedCodexCodingRunner
from ralf_agent.codex_runner import CodexCodingRunner
from ralf_agent.delegated_coding import register_coding_tool
from ralf_agent.errors import DefinitionMismatch
from tests.test_codex_connected_runner import connection
from tests.test_temporal_deployment_publication_cost import construct, count, profile_call


async def selected_four(tmp_path, monkeypatch, *, runners=1, connected=False):
    original, context = await construct(tmp_path, monkeypatch, composition=False)
    plain = original.tools.get("coding").handler.runner
    tools = original.tools
    if connected:
        runner = context.own_async(
            ConnectedCodexCodingRunner(
                plain._root,
                journal=plain._journal,
                docker_executable=plain._docker,
                docker_host=plain._host,
                connection=connection(),
            )
        )
        tools = ToolRegistry()
        register_coding_tool(tools, runner)
    elif runners == 2:
        root = tmp_path / "second-runner"
        root.mkdir(mode=0o700)
        second = context.own_async(
            CodexCodingRunner(
                root,
                journal=plain._journal,
                docker_executable=plain._docker,
                docker_host=plain._host,
            )
        )
        register_coding_tool(tools, second, name="coding_second")
    runtime = TemporalRuntime(
        providers=original.providers,
        tools=tools,
        journal=original.journal,
        coding_execution=True,
        enable_sessions=True,
        deployment_sessions=True,
        admission_policy=DeploymentAdmissionPolicy("registration-root-checks"),
    )
    assert runtime.manifest["deployment_admission_protocol"]["version"] == 4
    return runtime, context, plain


@pytest.mark.parametrize("runners", [1, 2])
@pytest.mark.parametrize("calls", [1, 2])
def test_plain_registration_checks_each_root_once_per_fresh_call(
    tmp_path, monkeypatch, runners, calls
):
    async def scenario():
        runtime, context, _ = await selected_four(tmp_path, monkeypatch, runners=runners)
        try:
            fixed = runtime.manifest["coding_execution_protocol"]

            def registrations():
                return [native.registration(runtime) for _ in range(calls)]

            values, profile = profile_call(registrations)
            for value in values:
                # Source fingerprints may change with the reviewed registration
                # implementation; the actual fixed native configuration may not.
                assert value["version"] == fixed["version"] == 6
                assert value["tools"] == fixed["tools"]
            assert count(profile, CodexCodingRunner._check_root) == runners * calls
        finally:
            await context.cleanup_async()

    asyncio.run(scenario())


def test_registration_rechecks_changed_physical_root_permissions(tmp_path, monkeypatch):
    async def scenario():
        runtime, context, runner = await selected_four(tmp_path, monkeypatch)
        try:
            native.registration(runtime)
            runner._root.chmod(0o750)
            with pytest.raises(DefinitionMismatch):
                native.registration(runtime)
        finally:
            runner._root.chmod(0o700)
            await context.cleanup_async()

    asyncio.run(scenario())


def test_connected_override_retains_independent_base_root_check(tmp_path, monkeypatch):
    async def scenario():
        runtime, context, _ = await selected_four(tmp_path, monkeypatch, connected=True)
        try:
            fixed = runtime.manifest["coding_execution_protocol"]
            value, profile = profile_call(lambda: native.registration(runtime))
            assert value["tools"] == fixed["tools"]
            override_calls = count(profile, ConnectedCodexCodingRunner._check_root)
            base_calls = count(profile, CodexCodingRunner._check_root)
            assert override_calls > 0
            # The real Connected override itself calls the base. Registration
            # must also retain its independent base check for this specialization.
            assert base_calls == override_calls + 1
        finally:
            await context.cleanup_async()

    asyncio.run(scenario())
