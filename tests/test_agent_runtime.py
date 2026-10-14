"""Facade observations never drive or cancel authoritative business work."""

import asyncio
from dataclasses import replace

import pytest

import ralf_agent as r
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError

from .helpers import ScriptedProvider


def api():
    assert hasattr(r, "Runtime"), "Missing independently hosted Runtime"
    return r.Runtime


def engine(path, provider, **options):
    return r.LocalEngine(
        r.SQLiteStore(path),
        providers={"default": provider},
        tools=options.pop("tools", r.ToolRegistry()),
        **options,
    )


@pytest.mark.parametrize("cancel", [False, True])
def test_wait_timeout_or_cancellation_preserves_hosted_run(cancel, tmp_path):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class Provider:
            identity = {"kind": "facade-delayed", "version": "1"}

            async def complete(self, messages, tools):
                started.set()
                await release.wait()
                return r.ModelResponse(output="done")

        runtime = api()(engine(tmp_path / "wait.sqlite", Provider()), owned=True)
        async with runtime:
            agent = runtime.create_agent(r.AgentSpec("a", "A"))
            run = await agent.submit("q", command_id="s")
            await started.wait()
            if cancel:
                observer = asyncio.create_task(run.wait())
                await asyncio.sleep(0)
                observer.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await observer
            else:
                result = await run.wait(wait_timeout=0)
                assert result.wait_reason == "observation_timeout"
            assert (await run.status()).state == "running"
            release.set()
            result = await run.wait(wait_timeout=1)
            assert result.snapshot.result == "done"
            assert not any(event.kind == "run_cancelled" for event in await run.events())

    asyncio.run(scenario())


def test_duplicate_submission_has_one_hosted_execution(tmp_path):
    async def scenario():
        provider = ScriptedProvider([r.ModelResponse(output="ok")])
        async with api()(engine(tmp_path / "duplicate.sqlite", provider), owned=True) as runtime:
            agent = runtime.create_agent(r.AgentSpec("a", "A"))
            first = await agent.submit("q", command_id="s")
            second = await agent.submit("q", command_id="s")
            assert first.ref == second.ref
            await first.wait(wait_timeout=1)
            assert provider.calls == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["sequence", "graph", "team", "dynamic", "bound"])
def test_existing_local_compositions_execute_through_new_entry(kind, tmp_path):
    async def scenario():
        spec = r.AgentSpec("a", "A")
        definition = {
            "sequence": r.WorkflowSpec("s", [spec]),
            "graph": r.GraphWorkflowSpec("g", [r.GraphNode("a", agent=spec)], max_concurrency=2),
            "team": r.TeamSpec("t", {"a": spec}),
            "dynamic": r.DynamicWorkflowSpec("d", {"a": spec}),
            "bound": r.AgentDefinition(spec, r.AgentBindingDescriptor()),
        }[kind]
        async with api()(
            engine(tmp_path / "compose.sqlite", ScriptedProvider([r.ModelResponse(output="ok")])),
            owned=True,
        ) as runtime:
            result = await runtime.create_agent(definition).run("q", command_id="s", wait_timeout=1)
            assert result.snapshot.state == "succeeded"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "option", [{"session_id": "shared"}, {"deadline_at": True}, {"queue": True}]
)
def test_unsupported_business_semantics_refuse_before_acceptance(option, tmp_path):
    async def scenario():
        raw = engine(tmp_path / "unsupported.sqlite", ScriptedProvider([]))
        async with api()(raw, owned=True) as runtime:
            with pytest.raises(ValidationError):
                await runtime.create_agent(r.AgentSpec("a", "A")).submit(
                    "q", command_id="s", **option
                )
            assert raw.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0

    asyncio.run(scenario())


def test_attach_validates_scope_authority_release_and_never_resumes(tmp_path):
    async def scenario():
        provider = ScriptedProvider([r.ModelResponse(output="ok")])
        raw = engine(tmp_path / "attach.sqlite", provider)
        handle = raw.submit(r.AgentSpec("a", "A"), "q", command_id="s")
        async with api()(raw, owned=True) as runtime:
            ref = runtime.reference(handle.run_id)
            run = runtime.attach(ref)
            assert (await run.wait(wait_timeout=0)).snapshot.state == "queued"
            assert provider.calls == 0
            for bad in [
                replace(ref, authority_locator="wrong"),
                replace(ref, release_digest="b" * 64),
            ]:
                with pytest.raises(DefinitionMismatch):
                    runtime.attach(bad)
            with pytest.raises(AuthorizationDenied):
                runtime.attach(replace(ref, principal="other"))
            await run.resume()
            assert (await run.wait(wait_timeout=1)).snapshot.state == "succeeded"

    asyncio.run(scenario())


def test_closed_borrowed_agent_keeps_handle_and_shared_runtime_usable(tmp_path):
    async def scenario():
        provider = ScriptedProvider([r.ModelResponse(output="one"), r.ModelResponse(output="two")])
        async with api()(engine(tmp_path / "shared.sqlite", provider), owned=True) as runtime:
            agent = runtime.create_agent(r.AgentSpec("a", "A"))
            run = await agent.submit("q", command_id="one")
            await agent.aclose()
            assert (await run.wait(wait_timeout=1)).snapshot.result == "one"
            with pytest.raises(r.RuntimeClosed):
                await agent.submit("q", command_id="closed")
            assert (
                await runtime.create_agent(r.AgentSpec("b", "B")).run(
                    "q", command_id="two", wait_timeout=1
                )
            ).snapshot.result == "two"
        with pytest.raises(r.RuntimeClosed):
            await run.status()

    asyncio.run(scenario())


def test_terminal_history_is_not_retained_as_runtime_tasks(tmp_path):
    async def scenario():
        provider = ScriptedProvider([r.ModelResponse(output="ok") for _ in range(100)])
        async with api()(engine(tmp_path / "bounded.sqlite", provider), owned=True) as runtime:
            agent = runtime.create_agent(r.AgentSpec("a", "A"))
            for index in range(100):
                await agent.run("q", command_id=str(index), wait_timeout=1)
            assert runtime.hosting_status == {"running": 0, "paused": 0, "failed": 0}

    asyncio.run(scenario())


def test_changed_host_scope_refuses_before_any_run_is_accepted(tmp_path):
    async def scenario():
        raw = engine(tmp_path / "scope.sqlite", ScriptedProvider([]))
        runtime = api()(raw, owned=True)
        raw.scope = r.Scope(principal="changed")
        with pytest.raises(DefinitionMismatch):
            await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
        assert raw.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        raw.scope = r.Scope()
        await runtime.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_profile_invalid_close_configuration_does_not_allocate_store(asynchronous, tmp_path):
    async def scenario():
        from ralf_agent import RuntimeProfile

        profile = RuntimeProfile("p", "1", {"default": {"adapter": "offline-echo"}})
        path = tmp_path / "invalid.sqlite"
        with pytest.raises(ValidationError):
            if asynchronous:
                await api().afrom_profile(profile, path, close_policy="handoff")
            else:
                api().from_profile(profile, path, close_policy="handoff")
        assert not path.exists()

    asyncio.run(scenario())


def test_standalone_agent_explicit_model_and_typed_tool(tmp_path):
    async def scenario():
        api()
        tools = r.ToolRegistry()

        def lookup(value: int) -> dict:
            return {"value": value}

        tools.register_function(lookup, effect="read_only")
        from ralf_agent.types import ToolCall

        provider = ScriptedProvider(
            [
                r.ModelResponse(tool_calls=[ToolCall("lookup", {"value": 7})]),
                r.ModelResponse(output="ok"),
            ]
        )
        async with r.Agent(
            model=provider, tools=tools, db_path=tmp_path / "standalone.sqlite"
        ) as agent:
            run = await agent.submit("q", command_id="s")
            result = await run.wait(wait_timeout=1)
            assert result.snapshot.state == "succeeded"
            tool = next(a for a in result.snapshot.actions if a["kind"] == "tool")
            assert tool["result"] == {"value": 7}
        with pytest.raises(r.RuntimeClosed):
            await run.status()

    asyncio.run(scenario())


def test_explicit_cancel_preserves_business_cancel_and_close_cancel_policy(tmp_path):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class Provider:
            identity = {"kind": "cancel-facade", "version": "1"}

            async def complete(self, messages, tools):
                started.set()
                await release.wait()
                return r.ModelResponse(output="late")

        async with api()(
            engine(tmp_path / "cancel.sqlite", Provider()), owned=True, close_policy="cancel"
        ) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
            await started.wait()
            first = await run.cancel(command_id="c")
            assert await run.cancel(command_id="c") == first
            release.set()
            result = await run.wait(wait_timeout=1)
            assert result.snapshot.state == "cancelled"

    asyncio.run(scenario())


def test_missing_original_provider_reports_host_error_without_replacing_run(tmp_path):
    async def scenario():
        provider = ScriptedProvider([])
        raw = engine(tmp_path / "host-failure.sqlite", provider)
        receipt = raw.submit(r.AgentSpec("a", "A"), "q", command_id="s")
        runtime = api()(raw, owned=True)
        ref = runtime.reference(receipt.run_id)
        raw.providers.clear()
        run = await runtime.resume(ref)
        with pytest.raises(r.ExecutionHostFailed):
            await run.wait(wait_timeout=1)
        assert raw.status(ref.run_id).state == "queued" and provider.calls == 0
        raw.providers["default"] = ScriptedProvider([r.ModelResponse(output="ok")])
        await run.resume()
        assert (await run.wait(wait_timeout=1)).snapshot.state == "succeeded"
        await runtime.aclose()

    asyncio.run(scenario())


def test_nested_approval_control_wakes_root_and_exposes_original_action_owner(tmp_path):
    async def scenario():
        from ralf_agent.types import ToolCall

        writes = []
        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("change", "Change", {"type": "object"}, requires_approval=True),
            lambda a, c: writes.append(c.effect_key) or {"applied": True},
        )
        nested = r.TeamSpec(
            "outer", {"inner": r.TeamSpec("inner", {"worker": r.AgentSpec("a", "A", ("change",))})}
        )
        provider = ScriptedProvider(
            [r.ModelResponse(tool_calls=[ToolCall("change", {})]), r.ModelResponse(output="ok")]
        )
        async with api()(
            engine(tmp_path / "nested-control.sqlite", provider, tools=tools), owned=True
        ) as runtime:
            root = await runtime.create_agent(nested).submit("q", command_id="s")
            assert (await root.wait(wait_timeout=1)).snapshot.state == "waiting_approval"
            pending = await root.pending()
            assert len(pending) == 1 and pending[0]["kind"] == "approval"
            owner = runtime.attach(r.RunRef.from_dict(pending[0]["ref"]))
            assert owner.ref.run_id != root.ref.run_id
            await owner.approve(pending[0]["action_id"], pending[0]["digest"], command_id="approve")
            assert (
                await root.wait(wait_timeout=1, terminal_only=True)
            ).snapshot.state == "succeeded"
            assert len(writes) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_rejected_profile_execution_backend_cleans_up_its_real_coordinator(asynchronous, tmp_path):
    async def scenario():
        from ralf_agent import RuntimeBuilder, RuntimeProfile

        closed = []

        class Wrapped:
            def __init__(self, raw):
                self.raw = raw

            def __getattr__(self, name):
                return getattr(self.raw, name)

            def close(self):
                self.raw.close()
                closed.append(True)

        def build(store, **options):
            return Wrapped(r.LocalEngine(store, **options))

        profile = RuntimeProfile(
            "p",
            "1",
            {"default": {"adapter": "offline-echo"}},
        )
        path = tmp_path / "rejected.sqlite"
        with pytest.raises(ValidationError):
            if asynchronous:
                await api().afrom_profile(
                    profile, path, builder=RuntimeBuilder(engine_factory=build)
                )
            else:
                api().from_profile(profile, path, builder=RuntimeBuilder(engine_factory=build))
        with engine(path, ScriptedProvider([])):
            pass
        assert closed == [True]

    asyncio.run(scenario())


def test_control_arriving_before_paused_drive_finishes_is_not_lost(tmp_path):
    async def scenario():
        from ralf_agent.types import ToolCall

        paused, finish = asyncio.Event(), asyncio.Event()

        class SlowReturnEngine(r.LocalEngine):
            async def drive(self, run_id):
                snapshot = await super().drive(run_id)
                if snapshot.state == "waiting_approval":
                    paused.set()
                    await finish.wait()
                return snapshot

        writes = []
        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("change", "Change", {"type": "object"}, requires_approval=True),
            lambda a, c: writes.append(c.effect_key) or {"applied": True},
        )
        provider = ScriptedProvider(
            [r.ModelResponse(tool_calls=[ToolCall("change", {})]), r.ModelResponse(output="ok")]
        )
        raw = SlowReturnEngine(
            r.SQLiteStore(tmp_path / "wake.sqlite"), providers={"default": provider}, tools=tools
        )
        async with api()(raw, owned=True) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A", ("change",))).submit(
                "q", command_id="s"
            )
            await paused.wait()
            action = (await run.status()).pending[0]
            await run.approve(action["action_id"], action["digest"], command_id="a")
            finish.set()
            assert (
                await run.wait(wait_timeout=1, terminal_only=True)
            ).snapshot.state == "succeeded"
            assert len(writes) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_profile_entry_retains_explicit_trusted_scope(asynchronous, tmp_path):
    async def scenario():
        profile = r.RuntimeProfile("p", "1", {"default": {"adapter": "offline-echo"}})
        scope = r.Scope("workspace", "owner")
        if asynchronous:
            runtime = await api().afrom_profile(profile, tmp_path / "scoped.sqlite", scope=scope)
        else:
            runtime = api().from_profile(profile, tmp_path / "scoped.sqlite", scope=scope)
        async with runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
            assert (run.ref.workspace, run.ref.principal) == ("workspace", "owner")
            assert (await run.wait(wait_timeout=1)).snapshot.state == "succeeded"

    asyncio.run(scenario())


def test_nested_wait_reports_root_host_failure_and_allows_explicit_recovery(tmp_path):
    async def scenario():
        from ralf_agent.types import ToolCall

        writes = []
        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("change", "Change", {"type": "object"}, requires_approval=True),
            lambda a, c: writes.append(c.effect_key) or {"applied": True},
        )
        provider = ScriptedProvider(
            [r.ModelResponse(tool_calls=[ToolCall("change", {})]), r.ModelResponse(output="ok")]
        )
        raw = engine(tmp_path / "child-host.sqlite", provider, tools=tools)
        runtime = api()(raw, owned=True)
        root = await runtime.create_agent(
            r.TeamSpec("team", {"child": r.AgentSpec("a", "A", ("change",))})
        ).submit("q", command_id="s")
        assert (await root.wait(wait_timeout=1)).snapshot.state == "waiting_approval"
        action = (await root.pending())[0]
        child = runtime.attach(r.RunRef.from_dict(action["ref"]))
        try:
            raw.providers.clear()
            await child.approve(action["action_id"], action["digest"], command_id="approve")
            with pytest.raises(r.ExecutionHostFailed):
                await root.wait(wait_timeout=1, terminal_only=True)
            with pytest.raises(r.ExecutionHostFailed):
                await child.wait(wait_timeout=0.05, terminal_only=True)
        finally:
            raw.providers["default"] = provider
            await child.resume()
            assert (
                await root.wait(wait_timeout=1, terminal_only=True)
            ).snapshot.state == "succeeded"
            assert (await child.wait(wait_timeout=1)).snapshot.state == "succeeded"
            await runtime.aclose()
        assert len(writes) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("entry", ["factory", "injected"])
@pytest.mark.parametrize("operation", ["submit", "close"])
def test_wrong_loop_first_call_refuses_without_preventing_owner_loop_recovery(
    entry, operation, tmp_path
):
    owner, foreign = asyncio.new_event_loop(), asyncio.new_event_loop()
    closed = []

    class Client:
        async def aclose(self):
            assert asyncio.get_running_loop() is owner
            closed.append(True)

    async def factory(config, context):
        context.own_async(Client())
        return ScriptedProvider([r.ModelResponse(output="ok")])

    registry = r.ComponentRegistry()
    registry.register_async("provider", "managed", factory)
    builder = r.RuntimeBuilder(registry)
    profile = r.RuntimeProfile("p", "1", {"default": {"adapter": "managed"}})

    async def create():
        if entry == "factory":
            return await api().afrom_profile(profile, tmp_path / "loop.sqlite", builder=builder)
        return api()(await builder.abuild(profile, tmp_path / "loop.sqlite"), owned=True)

    runtime = owner.run_until_complete(create())
    agent = runtime.create_agent(r.AgentSpec("a", "A"))

    async def wrong():
        with pytest.raises(ValidationError):
            if operation == "submit":
                await agent.submit("q", command_id="wrong")
            else:
                await runtime.aclose()

    async def recover():
        assert runtime.state == "open"
        assert runtime.engine.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        result = await agent.run("q", command_id="owner", wait_timeout=1)
        assert result.snapshot.state == "succeeded"
        await runtime.aclose()
        assert closed == [True]

    try:
        foreign.run_until_complete(wrong())
        owner.run_until_complete(recover())
    finally:
        owner.run_until_complete(runtime.engine.aclose())
        owner.close()
        foreign.close()
