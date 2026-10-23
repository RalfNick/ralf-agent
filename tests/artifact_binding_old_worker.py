"""Old-package-compatible subprocess probes; never import the current Artifact API."""

import asyncio
import json
import os
import signal
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

import ralf_agent as r


def data_root():
    return Path(os.environ["RALF_TEST_DATA_ROOT"])


def scope():
    return r.Scope(**json.loads(os.environ["RALF_TEST_SCOPE"]))


def record(kind, value=""):
    with sqlite3.connect(data_root() / "audit.sqlite") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT, value TEXT)")
        conn.execute("INSERT INTO calls VALUES (?, ?)", (kind, value))


class Provider:
    identity = {"kind": "artifact-upgrade-compat", "version": "1"}

    def __init__(self, mode):
        self.mode = mode

    async def complete(self, messages, tools):
        record("model")
        if self.mode == "refusal":
            raise AssertionError("Unsupported release must never dispatch this model")
        if any(message["role"] == "tool" for message in messages):
            return r.ModelResponse(output="answer")
        if self.mode == "sandbox4":
            return r.ModelResponse(
                tool_calls=[r.ToolCall("sandbox_run", {"argv": ["/bin/echo", "compat"]}, "read")]
            )
        return r.ModelResponse(tool_calls=[r.ToolCall("lookup", {}, "read")])


async def lookup(arguments, context):
    record("tool", context.effect_key)
    return "evidence"


class DockerEvidence(r.DockerSandbox):
    async def run(self, scope, request, *, invocation_id):
        value = await super().run(scope, request, invocation_id=invocation_id)
        # The inherited provider waits for actual native stop and deletion before returning.
        record("sandbox", json.dumps(value.to_dict(), sort_keys=True))
        return value


def definition(mode="default"):
    return r.AgentSpec("compat", "Answer", ("sandbox_run" if mode == "sandbox4" else "lookup",))


async def runtime(mode):
    from ralf_agent.temporal_activities import TemporalRuntime

    with sqlite3.connect(data_root() / "audit.sqlite") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT, value TEXT)")
    resources = []
    tools = r.ToolRegistry()
    options = {}
    if mode == "sandbox4":
        port = DockerEvidence(
            os.environ["RALF_TEST_DOCKER_SOCKET"],
            os.environ["RALF_TEST_DOCKER_IMAGE"],
            version="compat",
            scopes=[scope()],
            lease_root_path=str(data_root() / "native-leases"),
        )
        await port.aopen()
        source = r.SandboxToolSource(port, version="1")
        resources.extend([port, source])
        await r.register_tool_source(
            tools,
            source,
            policies={"sandbox_run": r.ToolPolicy("1", effect="read_only", requires_approval=True)},
        )
    else:
        tools.register(
            r.ToolSpec("lookup", "Read", {"type": "object"}, requires_approval=True), lookup
        )
    if mode == "native":
        options.update(
            session_store=r.SQLiteMemory(data_root() / "sessions.sqlite"),
            enable_sessions=True,
            session_writes=True,
        )
    elif mode == "binding1":
        options["binding_catalog"] = r.BindingCatalog(scope=scope())
    elif mode == "context2":
        options["context_reads"] = True
    elif mode == "tool3":
        options["tool_execution"] = r.ToolExecutionOwner(version="compat")
    return TemporalRuntime(providers={"default": Provider(mode)}, tools=tools, **options), resources


async def close_runtime(execution, resources):
    errors = []
    for close in (execution.close_context_execution, execution.close_session_execution):
        try:
            await close(wait_timeout=15)
        except Exception as error:
            errors.append(error)
    try:
        if execution.session_store is not None:
            execution.session_store.store.close()
    except Exception as error:
        errors.append(error)
    for resource in reversed(resources):
        try:
            await resource.aclose(wait_timeout=15)
        except Exception as error:
            errors.append(error)
    if errors:
        raise ExceptionGroup("Owned compatibility runtime cleanup failed", errors)


async def worker(mode):
    from ralf_agent.temporal import build_temporal_worker
    from temporalio.client import Client

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    execution, resources = await runtime(mode)
    finished = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, finished.set)
    try:
        async with build_temporal_worker(
            client, task_queue=os.environ["RALF_TEST_TEMPORAL_QUEUE"], runtime=execution
        ):
            await asyncio.to_thread(
                Path(os.environ["RALF_TEST_MANIFEST_FILE"]).write_text,
                json.dumps(execution.manifest, sort_keys=True),
            )
            print("COMPAT_READY", r.__version__, flush=True)
            await finished.wait()
    finally:
        await close_runtime(execution, resources)
    print("COMPAT_STOPPED", flush=True)


def legacy_defaults(mode):
    from ralf_agent.starter import create_starter

    root = data_root() / "defaults"
    root.mkdir(exist_ok=True)
    profiles = {}
    for adapter in ("budgeted", "managed-summary", "managed-data"):
        profile = r.RuntimeProfile(
            "app",
            "1",
            {"default": {"adapter": "offline-echo"}},
            components={"context_assembler": {"adapter": adapter}},
        )
        with r.RuntimeBuilder().build(profile, root / (adapter + ".sqlite")) as host:
            handle = host.submit(r.AgentSpec("answer", "Answer"), "hello", command_id="same")
            assert asyncio.run(host.drive(handle.run_id)).state == "succeeded"
            profiles[adapter] = {
                "run": handle.run_id,
                "manifest": host.diagnostics(handle.run_id).manifest,
                "context": host.context.identity,
            }
    with r.SQLiteArtifactStore(root / "original-artifacts.sqlite") as artifacts:
        reference = artifacts.put(scope(), "results", {"original": "中文🙂"})
        assert artifacts.get(scope(), reference) == {"original": "中文🙂"}
        profiles["artifact"] = reference.to_dict()
    state = root / "state.json"
    if mode == "old-first":
        state.write_text(json.dumps(profiles))
    else:
        assert profiles == json.loads(state.read_text())
    templates = (
        "oncall",
        "rag",
        "config",
        "model",
        "graph",
        "mcp",
        "parallel",
        "async",
        "plan",
        "team",
        "dag",
        "nested",
        "a2a",
        "temporal",
        "ingest",
        "hybrid",
        "context",
        "memory",
        "model-check",
        "observable",
        "sessions",
        "cli",
    )
    for name in templates:
        create_starter(root / mode / name, template=name)
        if mode != "old-first":
            old, new = root / "old-first" / name, root / mode / name
            assert {
                str(p.relative_to(old)): p.read_bytes() for p in old.rglob("*") if p.is_file()
            } == {str(p.relative_to(new)): p.read_bytes() for p in new.rglob("*") if p.is_file()}
    with closing(r.SQLiteMemory(root / "typed-original.sqlite")) as memory:
        if mode == "old-first":
            memory.append(scope(), "s", {"content": "numeric"}, expected_revision=0, message_id=1)
        elif mode == "new":
            assert memory.inspect_message(scope(), "s", "1")["receipt"] is None
            memory.append(scope(), "s", {"content": "text"}, expected_revision=1, message_id="1")
        elif mode == "old-again":
            memory.append(scope(), "s", {"content": "old-after"}, expected_revision=2, message_id=2)
        else:
            assert memory.inspect_message(scope(), "s", "2")["receipt"] is None
            assert memory.inspect_message(scope(), "s", "1")["receipt"] == {
                "revision": 2,
                "message": {"content": "text"},
            }
    print(r.__version__, mode, "legacy profiles, SQLite references, typed Session, 22 starters")


def change(arguments, context):
    record("tool", context.effect_key)
    with sqlite3.connect(data_root() / "effects.sqlite") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS effects (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO effects VALUES (?)", (context.action_id,))
    return {"applied": True}


class SessionProvider:
    identity = {"kind": "session-artifact-upgrade-compat", "version": "1"}

    async def complete(self, messages, tools):
        record("model")
        if any(message["role"] == "tool" for message in messages):
            return r.ModelResponse(output="applied")
        return r.ModelResponse(tool_calls=[r.ToolCall("change", {})])


async def local_session(mode):
    root = data_root()
    tools = r.ToolRegistry()
    tools.register(
        r.ToolSpec(
            "change",
            "Change",
            {"type": "object"},
            effect="idempotent_write",
            requires_approval=True,
        ),
        change,
    )
    raw = r.LocalEngine(
        r.SQLiteStore(root / "run.sqlite"),
        providers={"default": SessionProvider()},
        tools=tools,
        scope=scope(),
    )
    async with r.Runtime(raw, owned=True) as host:
        if mode == "old-first":
            session = await host.create_agent(r.AgentSpec("a", "Apply", ("change",))).open_session(
                "s", command_id="open"
            )
            handle = await session.submit("q", command_id="submit")
            assert (await handle.wait(wait_timeout=3)).snapshot.state == "waiting_approval"
            state = {
                "session": session.ref.to_dict(),
                "run": handle.ref.to_dict(),
                "receipt": asdict(handle.receipt),
                "control": (await handle.pending())[0],
            }
            (root / "state.json").write_text(json.dumps(state))
        else:
            state = json.loads((root / "state.json").read_text())
            session = host.attach_session(r.SessionRef.from_dict(state["session"]))
            handle = await host.aattach(r.RunRef.from_dict(state["run"]))
            control = state["control"]
            approval = await handle.approve(
                control["action_id"], control["digest"], command_id="approve"
            )
            if mode == "new":
                (root / "approval.json").write_text(json.dumps(asdict(approval)))
            else:
                assert asdict(approval) == json.loads((root / "approval.json").read_text())
            assert (await handle.wait(wait_timeout=3)).snapshot.state == "succeeded"
            assert (
                asdict((await session.submit("q", command_id="submit")).receipt) == state["receipt"]
            )
            assert not (await session.status()).busy
        assert (
            raw.store.conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            == "2"
        )
    with sqlite3.connect(root / "audit.sqlite") as conn:
        counts = dict(conn.execute("SELECT kind, count(*) FROM calls GROUP BY kind"))
    assert counts == ({"model": 1} if mode == "old-first" else {"model": 2, "tool": 1})
    if mode != "old-first":
        with sqlite3.connect(root / "effects.sqlite") as conn:
            assert conn.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
    print(r.__version__, mode, "Local Session/Run/typed receipt and one real SQLite effect")


def main():
    operation, mode = sys.argv[1:]
    if operation == "worker":
        asyncio.run(worker(mode))
    elif operation == "defaults":
        legacy_defaults(mode)
    elif operation == "local-session":
        asyncio.run(local_session(mode))
    else:
        raise AssertionError(operation)
