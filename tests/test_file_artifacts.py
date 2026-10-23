import asyncio
import importlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from relf_agent import Scope
from relf_agent.errors import BudgetExceeded, DefinitionMismatch, NotFound, ValidationError
from tests.context_crash_assertions import assert_context_crash_effects


def api():
    module = importlib.import_module("relf_agent")
    assert hasattr(module, "FileArtifactStore"), "Missing durable file artifact backend"
    return module.FileArtifactStore


def test_file_payload_and_reference_survive_reopen(tmp_path):
    root = tmp_path / "artifacts"
    with api()(root) as store:
        reference = store.put(Scope(), "results", {"evidence": "中文🙂"})
        payloads = list(root.glob("*.json"))
        assert len(payloads) == 1
        assert json.loads(payloads[0].read_bytes()) == {"evidence": "中文🙂"}
        assert store.put(Scope(), "results", {"evidence": "中文🙂"}) == reference
    with api()(root) as reopened:
        assert reopened.get(Scope(), reference) == {"evidence": "中文🙂"}
        assert reopened.delete(Scope(), reference)
        assert not reopened.delete(Scope(), reference)
        assert list(root.glob("*.json")) == []


def test_missing_corrupt_or_aliased_file_never_returns_success(tmp_path):
    with api()(tmp_path / "artifacts") as store:
        reference = store.put(Scope(), "results", {"evidence": 7})
        path = tmp_path / "artifacts" / (reference.artifact_id + ".json")
        saved = path.read_bytes()
        path.write_bytes(b'{"evidence":8}')
        with pytest.raises(ValidationError):
            store.get(Scope(), reference)
        with pytest.raises(ValidationError):
            store.put(Scope(), "results", {"evidence": 7})
        path.unlink()
        with pytest.raises(NotFound):
            store.get(Scope(), reference)
        assert store.put(Scope(), "results", {"evidence": 7}) == reference
        path.unlink()
        outside = tmp_path / "outside.json"
        outside.write_bytes(saved)
        os.symlink(outside, path)
        with pytest.raises(ValidationError):
            store.get(Scope(), reference)
        path.unlink()
        os.link(outside, path)
        with pytest.raises(ValidationError):
            store.get(Scope(), reference)


def test_root_replacement_refuses_old_handle(tmp_path):
    root = tmp_path / "artifacts"
    with api()(root) as store:
        reference = store.put(Scope(), "results", {"evidence": 7})
        root.rename(tmp_path / "moved")
        root.mkdir()
        with pytest.raises(DefinitionMismatch):
            store.get(Scope(), reference)


def test_full_namespace_does_not_publish_unlimited_orphan_payloads(tmp_path):
    with api()(tmp_path / "artifacts", capacity=1) as store:
        store.put(Scope(), "results", {"n": 0})
        for i in range(1, 5):
            with pytest.raises(BudgetExceeded):
                store.put(Scope(), "results", {"n": i})
        assert len(list((tmp_path / "artifacts").glob("*.json"))) == 1


def test_two_handles_preserve_atomic_namespace_capacity(tmp_path):
    root = tmp_path / "artifacts"
    first, second = api()(root, capacity=1), api()(root, capacity=1)
    barrier, results = threading.Barrier(2), []

    def write(store, value):
        barrier.wait()
        try:
            results.append(store.put(Scope(), "results", value))
        except BudgetExceeded:
            results.append("full")

    threads = [
        threading.Thread(target=write, args=(first, {"n": 1})),
        threading.Thread(target=write, args=(second, {"n": 2})),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert all(not thread.is_alive() for thread in threads)
        assert len(results) == 2 and results.count("full") == 1
        reference = next(result for result in results if result != "full")
        assert first.get(Scope(), reference) in [{"n": 1}, {"n": 2}]
        assert len(list(root.glob("*.json"))) == 1
    finally:
        first.close()
        second.close()


def test_owned_index_cannot_move_behind_unchanged_backend_identity(tmp_path):
    from relf_agent import SQLiteArtifactStore

    with api()(tmp_path / "artifacts") as store:
        original = store._index
        replacement = SQLiteArtifactStore(
            tmp_path / "other.sqlite",
            backend_id=original.backend_id,
            max_bytes=16384,
            capacity=1024,
        )
        try:
            store._index = replacement
            with pytest.raises(DefinitionMismatch):
                store.put(Scope(), "results", {"value": 1})
            assert list((tmp_path / "artifacts").glob("*.json")) == []
        finally:
            store._index = original
            replacement.close()


def test_backend_identity_at_contract_limit_is_supported(tmp_path):
    with api()(tmp_path / "artifacts", backend_id="x" * 512) as store:
        reference = store.put(Scope(), "results", {"n": 1})
        assert store.get(Scope(), reference) == {"n": 1}


def test_missing_lock_is_typed_and_cannot_recreate_execution_lock(tmp_path):
    with api()(tmp_path / "artifacts") as store:
        (tmp_path / "artifacts" / ".artifact.lock").unlink()
        with pytest.raises(DefinitionMismatch):
            store.put(Scope(), "results", {"n": 1})
        assert list((tmp_path / "artifacts").glob("*.json")) == []


def test_new_root_is_private_and_parent_directory_creation_is_synced(tmp_path, monkeypatch):
    import stat

    original = os.fsync
    synced = []

    def sync(fd):
        info = os.fstat(fd)
        synced.append((info.st_dev, info.st_ino))
        return original(fd)

    monkeypatch.setattr(os, "fsync", sync)
    root = tmp_path / "one" / "two" / "artifacts"
    with api()(root) as store:
        reference = store.put(Scope(), "results", {"n": 1})
        assert store.get(Scope(), reference) == {"n": 1}
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for directory in [tmp_path, tmp_path / "one", tmp_path / "one" / "two"]:
        info = directory.stat()
        assert (info.st_dev, info.st_ino) in synced


def test_index_swap_during_publication_cannot_write_replacement_index(tmp_path):
    from relf_agent import SQLiteArtifactStore

    replacement = SQLiteArtifactStore(tmp_path / "replacement.sqlite")

    class Changed(api()):
        def _publish(self, *args, **kwargs):
            super()._publish(*args, **kwargs)
            self._index = replacement

    try:
        with Changed(tmp_path / "artifacts") as store:
            with pytest.raises(DefinitionMismatch):
                store.put(Scope(), "results", {"n": 1})
        assert replacement.conn.execute("SELECT COUNT(*) FROM ralf_artifacts").fetchone()[0] == 0
    finally:
        replacement.close()


def test_index_file_change_during_payload_read_is_refused_before_confirmation(tmp_path):
    with api()(tmp_path / "artifacts") as store:
        reference = store.put(Scope(), "results", {"n": 1})
        original = store._payload

        def changed(*args):
            value = original(*args)
            index = Path(store._index.path)
            index.rename(tmp_path / "old-index.sqlite")
            index.touch()
            return value

        store._payload = changed
        with pytest.raises(ValidationError):
            store.get(Scope(), reference)


@pytest.mark.parametrize("extension", ["json", "toml"])
@pytest.mark.parametrize("assembly", ["sync", "async"])
def test_configured_file_adapter_owns_lifecycle_and_reopens_original_receipt(
    tmp_path, extension, assembly
):
    from relf_agent import AgentSpec, RuntimeBuilder, load_catalog

    config = {
        "adapter": "managed-data",
        "config": {
            "artifacts": {"adapter": "file", "config": {"path": "payloads", "capacity": 1}},
            "counter": "utf8-bytes",
            "output_reserve": 32,
            "max_units": 2000,
        },
    }
    profile = {
        "name": "app",
        "version": "1",
        "providers": {"default": {"adapter": "offline-echo"}},
        "components": {"context_assembler": config},
    }
    path = tmp_path / ("runtime." + extension)
    if extension == "json":
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "default": {"name": "app", "version": "1"},
                    "profiles": [profile],
                }
            )
        )
    else:
        path.write_text("""schema_version = 1
[default]
name = "app"
version = "1"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.context_assembler]
adapter = "managed-data"
[profiles.components.context_assembler.config]
counter = "utf8-bytes"
output_reserve = 32
max_units = 2000
[profiles.components.context_assembler.config.artifacts]
adapter = "file"
[profiles.components.context_assembler.config.artifacts.config]
path = "payloads"
capacity = 1
""")

    async def run():
        catalog = load_catalog(path)
        builder = RuntimeBuilder(base_dir=tmp_path)
        runtime = (
            builder.build(catalog.default, tmp_path / "runs.sqlite")
            if assembly == "sync"
            else await builder.abuild(catalog.default, tmp_path / "runs.sqlite")
        )
        store = runtime.context.artifacts
        try:
            assert isinstance(store, api())
            reference = store.put(Scope(), "results", {"n": 1})
            handle = runtime.submit(AgentSpec("answer", "Answer"), "hello", command_id="one")
            assert (await runtime.drive(handle.run_id)).state == "succeeded"
        finally:
            await runtime.aclose()
        with pytest.raises(ValidationError):
            store.get(Scope(), reference)
        restored = await builder.abuild(catalog.default, tmp_path / "runs.sqlite")
        try:
            assert restored.context.artifacts.get(Scope(), reference) == {"n": 1}
            assert (
                restored.submit(AgentSpec("answer", "Answer"), "hello", command_id="one") == handle
            )
            assert (await restored.drive(handle.run_id)).state == "succeeded"
        finally:
            await restored.aclose()

    asyncio.run(run())


def package_env():
    import relf_agent

    return {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join(
            [str(Path(relf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
        ),
    }


@pytest.mark.parametrize(
    "phase", ["before-publish", "payload-published", "before-index-commit", "after-index-commit"]
)
def test_process_loss_never_confirms_unindexed_payload_and_replays_exact_reference(tmp_path, phase):
    from relf_agent import ArtifactReference

    crashed = subprocess.run(
        [sys.executable, "-m", "tests.file_artifact_crash_fixture", str(tmp_path), phase],
        env=package_env(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert crashed.returncode == 79 and "file-artifact-crash-window" in crashed.stdout, (
        crashed.stderr
    )
    reference = ArtifactReference.from_dict(json.loads((tmp_path / "reference.json").read_text()))
    with api()(tmp_path / "artifacts") as store:
        count = store._index.conn.execute("SELECT COUNT(*) FROM ralf_artifacts").fetchone()[0]
        assert count == (1 if phase == "after-index-commit" else 0)
        if phase == "after-index-commit":
            assert store.get(Scope(), reference) == {"evidence": "中文🙂"}
        else:
            with pytest.raises(NotFound):
                store.get(Scope(), reference)
        assert store.put(Scope(), "results", {"evidence": "中文🙂"}) == reference
        assert store.get(Scope(), reference) == {"evidence": "中文🙂"}
        assert store._index.conn.execute("SELECT COUNT(*) FROM ralf_artifacts").fetchone()[0] == 1
        assert len(list((tmp_path / "artifacts").glob("*.json"))) == 1


def test_concurrent_processes_share_capacity_and_original_duplicate_reference(tmp_path):
    path = tmp_path / "artifacts"
    with api()(path, capacity=1):
        pass
    code = """import sys,json
from relf_agent import FileArtifactStore,Scope
from relf_agent.errors import BudgetExceeded
with FileArtifactStore(sys.argv[1],capacity=1) as store:
 try:
  ref=store.put(Scope(),'results',{'value':sys.argv[2]})
  print(json.dumps({'id':ref.artifact_id,'value':store.get(Scope(),ref)}))
 except BudgetExceeded: print(json.dumps({'full':True}))
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(path), value],
            env=package_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for value in ("same", "same", "different")
    ]
    outputs = []
    try:
        for process in processes:
            out, err = process.communicate(timeout=15)
            assert process.returncode == 0, err
            outputs.append(json.loads(out))
        successes = [v for v in outputs if "id" in v]
        assert successes and len({v["id"] for v in successes}) == 1
        with api()(path, capacity=1) as store:
            assert (
                store._index.conn.execute("SELECT COUNT(*) FROM ralf_artifacts").fetchone()[0] == 1
            )
            assert len(list(path.glob("*.json"))) == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize("kind", ["parallel", "team", "dynamic-dag", "nested"])
@pytest.mark.parametrize("window", ["artifact_commit", "context_preparation_response_received"])
def test_composite_file_offload_recovers_without_repeating_business_or_artifact_write(
    tmp_path, kind, window
):
    fixture = Path(__file__).with_name("composite_context_crash_fixture.py")
    for mode, expected in (("crash", 77), ("resume", 0)):
        outcome = subprocess.run(
            [sys.executable, str(fixture), str(tmp_path), kind, window, mode, "file"],
            env=package_env(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert outcome.returncode == expected, outcome.stderr
    assert_context_crash_effects(tmp_path, file_artifacts=True)


def test_temporal_file_stage_receipt_survives_resource_reopen(tmp_path):
    import copy

    from tests.test_temporal_managed_context import finish, setup, step

    async def run():
        with api()(tmp_path / "artifacts") as store:
            runtime, state, provider, writes = setup(store)
            for _ in range(100):
                action, _ = await step(runtime, state)
                if action.get("phase") == "write":
                    break
            else:
                raise AssertionError("Expected original artifact write")
            assert len(writes) == 1
            restored = copy.deepcopy(state)
            release = runtime.manifest
        with api()(tmp_path / "artifacts") as store:
            runtime, _, _, remaining = setup(store, provider=provider)
            assert runtime.manifest == release
            await finish(runtime, restored)
            assert restored.state == "succeeded" and len(remaining) == 3
            assert any(e["kind"] == "context_artifact_verified" for e in restored.event_log)
            assert len(list((tmp_path / "artifacts").glob("*.json"))) == 1

    asyncio.run(run())


def test_actual_worker_assembly_selects_file_resource_and_stable_release(tmp_path):
    from tests.temporal_managed_context_worker import runtime

    execution, artifacts = runtime(tmp_path, "file-queue", artifact_backend="file")
    try:
        assert isinstance(artifacts, api())
        original = execution.orchestration_release
    finally:
        artifacts.close()
    execution, artifacts = runtime(tmp_path, "file-queue", artifact_backend="file")
    try:
        assert execution.orchestration_release == original
    finally:
        artifacts.close()


def test_orphan_replay_syncs_payload_and_directory_before_receipt_commit(tmp_path, monkeypatch):
    outcome = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.file_artifact_crash_fixture",
            str(tmp_path),
            "payload-published",
        ],
        env=package_env(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert outcome.returncode == 79, outcome.stderr
    root = tmp_path / "artifacts"
    import relf_agent.file_artifacts as module

    original_sync = os.fsync
    synced = []

    def sync(fd):
        info = os.fstat(fd)
        synced.append((info.st_dev, info.st_ino))
        return original_sync(fd)

    original_index = module.SQLiteArtifactStore

    class Index(original_index):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            connection = self.conn

            class Observed:
                def __getattr__(self, name):
                    return getattr(connection, name)

                def execute(self, sql, *args):
                    if sql == "COMMIT":
                        for path in [next(root.glob("*.json")), root]:
                            info = path.stat()
                            assert (info.st_dev, info.st_ino) in synced
                    return connection.execute(sql, *args)

            self.conn = Observed()

    # Observe native durability before the actual SQL COMMIT, retaining SDK guards.
    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(module, "SQLiteArtifactStore", Index)
    with api()(root) as restored:
        synced.clear()
        reference = restored.put(Scope(), "results", {"evidence": "中文🙂"})
        assert restored.get(Scope(), reference) == {"evidence": "中文🙂"}


def test_initial_index_symlink_is_rejected_without_opening_external_database(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside.sqlite"
    (root / ".index.sqlite").symlink_to(outside)
    with pytest.raises(ValidationError):
        api()(root)
    assert not outside.exists()


@pytest.mark.parametrize("descriptor", ["_lock_fd", "_root_fd"])
def test_held_descriptor_drift_cannot_confirm_or_close_borrowed_descriptor(tmp_path, descriptor):
    store = api()(tmp_path / "artifacts")
    borrowed = os.open(tmp_path / "other", os.O_CREAT | os.O_RDWR, 0o600)
    original = getattr(store, descriptor)
    try:
        setattr(store, descriptor, borrowed)
        with pytest.raises(DefinitionMismatch):
            store.put(Scope(), "results", {"n": 1})
        store.close()
        os.fstat(borrowed)
        with pytest.raises(OSError):
            os.fstat(original)
        assert list((tmp_path / "artifacts").glob("*.json")) == []
    finally:
        setattr(store, descriptor, original)
        store.close()
        os.close(borrowed)


@pytest.mark.parametrize("descriptor", ["_lock_fd", "_root_fd"])
def test_reused_native_descriptor_is_refused_and_not_closed_as_owned(tmp_path, descriptor):
    store = api()(tmp_path / "artifacts")
    original = getattr(store, descriptor)
    borrowed = os.open(tmp_path / "other", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.dup2(borrowed, original)
        with pytest.raises(DefinitionMismatch):
            store.put(Scope(), "results", {"n": 1})
        store.close()
        os.fstat(original)
    finally:
        store.close()
        try:
            os.close(original)
        except OSError:
            pass
        os.close(borrowed)
