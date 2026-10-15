"""Original Registry and Session pure state over a simulated SDK transport."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent import AgentSpec, Scope
from ralf_agent.errors import CapacityExceeded
from ralf_agent.temporal_session_state import SESSION_WORKFLOW, TemporalSessionState
from ralf_agent.temporal_state import COMMAND_REGISTRY_NAME
from tests.test_temporal_deployment_session_registry import NAMESPACE, POLICY, command, state


class Handle:
    def __init__(self, backend, identity, epoch=None):
        self.backend, self.id, self.epoch = backend, identity, epoch

    async def describe(self):
        b = self.backend
        if self.id == b.registry_id:
            epoch, queue, kind = "registry-original", "original-queue", COMMAND_REGISTRY_NAME
        elif self.id in b.sessions:
            epoch, queue, kind = b.epoch, "original-queue", SESSION_WORKFLOW
        else:
            from temporalio.service import RPCError, RPCStatusCode

            raise RPCError("missing", RPCStatusCode.NOT_FOUND, b"")
        return SimpleNamespace(
            id=self.id,
            run_id=epoch,
            namespace=b.namespace,
            task_queue=queue,
            workflow_type=kind,
            raw_info=SimpleNamespace(first_run_id=epoch),
            parent_id=None,
            parent_run_id=None,
        )

    async def query(self, name, value):
        b = self.backend
        if self.id == b.registry_id:
            if value["kind"] == "deployment_configuration":
                return {
                    "version": 4,
                    "registry_id": b.registry_id,
                    "policy": POLICY.identity,
                    "namespace": NAMESPACE,
                }
            return getattr(b.registry, value["kind"])(value)
        session = b.sessions[self.id]
        selector = {k: v for k, v in value.items() if k != "kind"}
        if value["kind"] == "deployment_session_receipt":
            return session.deployment_receipt(selector)
        if value["kind"] == "deployment_session_binding":
            return session.deployment_binding(selector)
        if value["kind"] == "deployment_session_intent":
            entry = session.deployment_turns.get(value["session_command_id"])
            return None if entry is None else entry.intent
        if value["kind"] == "deployment_session_start":
            return session.deployment_view(selector)
        raise AssertionError(value)

    async def execute_update(self, name, value, **options):
        b = self.backend
        if self.id == b.registry_id:
            if name == "reserve":
                result = b.registry.reserve(value)
                if b.lose_reserve:
                    b.lose_reserve = False
                    raise TimeoutError("lost accepted reserve")
                return result
            assert name == "record_deployment_session_command"
            prepared = b.registry.prepare_session_receipt(value)
            return b.registry.commit_session_receipt(value, prepared)
        session = b.sessions[self.id]
        b.updates.append((name, copy.deepcopy(value), options.get("id")))
        if name == "command":
            result = session.command(value)
            if value["kind"] == "submit" and result["apply_state"] == "applied":
                session.deployment_turns[value["command_id"]].start["phase"] = "capacity-deferred"
            return result
        if name == "retry_deployment_turn":
            return session.deployment_retry(value)
        assert name == "start_receipt"
        return session.deployment_view(value)


class Backend:
    namespace = NAMESPACE["name"]
    service_client = SimpleNamespace(config=SimpleNamespace(target_host="fixture:7233"))

    def __init__(self):
        self.registry = state()
        self.registry_id = self.registry.registry_id
        self.sessions, self.starts, self.updates = {}, [], []
        self.epoch = "session-original"
        self.lose_reserve = False
        self.workflow_service = SimpleNamespace(describe_namespace=self.describe_namespace)

    async def describe_namespace(self, value):
        return SimpleNamespace(namespace_info=SimpleNamespace(id=NAMESPACE["id"]))

    def get_workflow_handle(self, identity, *, run_id=None):
        return Handle(self, identity, run_id)

    async def start_workflow(self, kind, accepted, **options):
        from temporalio.exceptions import WorkflowAlreadyStartedError

        if kind == COMMAND_REGISTRY_NAME or options["id"] in self.sessions:
            raise WorkflowAlreadyStartedError(options["id"], kind)
        assert kind == SESSION_WORKFLOW and options["retry_policy"] is None
        self.starts.append(copy.deepcopy(options))
        self.sessions[options["id"]] = TemporalSessionState(
            accepted,
            deployment_context={"namespace": NAMESPACE, "coordinator_execution_epoch": self.epoch},
        )


def client():
    from ralf_agent.temporal_session_client import TemporalSessionClient

    backend = Backend()
    binding = command()["session_submission"]["binding"]
    engine = SimpleNamespace(
        client=backend,
        release=binding["manifest"],
        scope=Scope("workspace", "owner"),
        namespace=NAMESPACE["name"],
        task_queue="original-queue",
        activity_timeout=30,
        _closed=False,
    )
    return TemporalSessionClient(engine, NAMESPACE["id"]), backend


def test_selected_open_replays_first_registry_envelope_before_current_provider_alias():
    async def run():
        api, backend = client()
        spec = AgentSpec("ordinary", "Answer")
        first = await api.open(spec, "chat", command_id="open")
        api.engine.release = {**api.engine.release, "providers": {"moved": {"kind": "unavailable"}}}
        api.engine.task_queue = "moved-queue"
        assert await api.open(spec, "chat", command_id="open") == first
        assert len(backend.starts) == 1
        original = next(iter(backend.registry.session_commands.values()))
        assert original["session_submission"]["binding"]["task_queue"] == "original-queue"
        assert original["session_receipt"]["kind"] == "session_open"
        assert not backend.registry.roots

    asyncio.run(run())


def test_lost_zero_root_reserve_reply_recovers_without_second_session():
    async def run():
        api, backend = client()
        backend.lose_reserve = True
        with pytest.raises(TimeoutError):
            await api.open(AgentSpec("ordinary", "Answer"), "chat", command_id="open")
        assert len(backend.registry.commands) == 1 and not backend.sessions
        result = await api.open(AgentSpec("ordinary", "Answer"), "chat", command_id="open")
        assert result.apply_state == "applied" and len(backend.starts) == 1

    asyncio.run(run())


def test_capacity_deferred_duplicate_wakes_same_original_intent_with_fresh_update_id():
    async def run():
        from ralf_agent.session_types import SessionRef

        api, backend = client()
        opened = await api.open(AgentSpec("ordinary", "Answer"), "chat", command_id="open")
        ref = SessionRef.from_dict(opened.outcome["session_ref"])
        for _ in range(2):
            with pytest.raises(CapacityExceeded) as caught:
                await api.submit(ref, "question", command_id="turn", budget=4)
            assert caught.value.receipt.command_id == "turn"
            assert caught.value.start["phase"] == "capacity-deferred"
        session = next(iter(backend.sessions.values()))
        assert len(session.records) == len(session.deployment_turns) == 1
        retries = [item for item in backend.updates if item[0] == "retry_deployment_turn"]
        assert (
            len(retries) == 1 and retries[0][1]["coordinator_execution_epoch"] == "session-original"
        )
        assert not backend.registry.roots and len(backend.registry.commands) == 2

    asyncio.run(run())


def test_changed_declared_session_address_conflicts_before_resolving_new_binding():
    async def run():
        from ralf_agent.errors import IdempotencyConflict

        api, backend = client()
        await api.open(AgentSpec("ordinary", "Answer"), "chat", command_id="open")
        with pytest.raises(IdempotencyConflict):
            await api.open(AgentSpec("ordinary", "Answer"), "other", command_id="open")
        assert len(backend.starts) == 1

    asyncio.run(run())


def test_rebind_duplicate_keeps_first_resolved_binding_after_alias_moves():
    async def run():
        from ralf_agent.session_types import SessionRef

        api, backend = client()
        opened = await api.open(AgentSpec("ordinary", "Answer"), "chat", command_id="open")
        ref = SessionRef.from_dict(opened.outcome["session_ref"])
        definition = AgentSpec("ordinary", "Different instruction")
        first = await api.rebind(ref, definition, command_id="rebind", expected_binding_revision=1)
        api.engine.release = {**api.engine.release, "providers": {"moved": {"kind": "unavailable"}}}
        api.engine.task_queue = "moved-queue"
        assert (
            await api.rebind(ref, definition, command_id="rebind", expected_binding_revision=1)
            == first
        )
        session = next(iter(backend.sessions.values()))
        assert session.binding_revision == 2 and session.binding["task_queue"] == "original-queue"
        assert len(backend.registry.commands) == 2 and not backend.registry.roots

    asyncio.run(run())


def test_facade_sessions_capability_requires_explicit_publication4_marker():
    from ralf_agent.temporal_agent_runtime import TemporalClientRuntime
    from ralf_agent.temporal_deployment_protocol import publish

    runtime = object.__new__(TemporalClientRuntime)
    manifest = command()["session_submission"]["binding"]["manifest"]
    runtime._engine = SimpleNamespace(release=manifest)
    assert runtime.capabilities["shared_sessions"] is True
    old = publish(
        {
            k: v
            for k, v in manifest.items()
            if k not in {"deployment_admission_protocol", "session_deployment_protocol"}
        },
        POLICY.identity,
        public=True,
    )
    runtime._engine = SimpleNamespace(release=old)
    assert runtime.capabilities["shared_sessions"] is False


def test_host_selects_registry4_for_mixed_profiles_at_one_address():
    async def run():
        from ralf_agent.temporal_deployment_admission import registry_id
        from ralf_agent.temporal_profile_host import TemporalProfileHost

        engines = []

        class Assembly:
            def __init__(self, version):
                self.release = {"deployment_admission_protocol": {"version": version}}
                self.profile = SimpleNamespace(
                    identity={"profile_id": str(version), "version": "1"}
                )
                self._worker_lifetime = asyncio.Event()
                self._worker_start = asyncio.get_running_loop().create_future()

            def create_engine(self, client, **options):
                engine = SimpleNamespace(
                    release=self.release, command_registry_id=registry_id(POLICY.deployment_id)
                )
                engines.append(engine)
                return engine

            async def start_worker(self, client, **options):
                return self

        assemblies = [Assembly(version) for version in (2, 4, 3)]
        backend = Backend()
        host = TemporalProfileHost(
            assemblies, None, [], assemblies[0].profile.identity, Scope("workspace", "owner")
        )
        # A Host checks original Registry queues before starting Workers.
        backend.registry = None

        class MissingHandle(Handle):
            async def describe(self):
                if self.id == backend.registry_id:
                    from temporalio.service import RPCError, RPCStatusCode

                    raise RPCError("missing", RPCStatusCode.NOT_FOUND, b"")
                return await super().describe()

        backend.get_workflow_handle = lambda identity, **options: MissingHandle(
            backend, identity, options.get("run_id")
        )
        await host.start_workers(backend)
        assert [engine._deployment_registry_protocol for engine in engines] == [4, 4, 4]

    asyncio.run(run())
