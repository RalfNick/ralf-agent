"""Interrupted synchronous construction retains real resource ownership."""

import asyncio
import sqlite3

import pytest

from relf_agent import ComponentRegistry, LocalEngine, RuntimeBuilder, SQLiteStore
from relf_agent.errors import CoordinatorBusy
from relf_agent.runtime_builder import RuntimeBuildError

from .test_runtime_builder import profile

INTERRUPTIONS = (KeyboardInterrupt, asyncio.CancelledError, SystemExit)


@pytest.mark.parametrize("error_type", INTERRUPTIONS)
def test_interrupted_factory_closes_owned_resources_and_propagates_original(tmp_path, error_type):
    interruption = error_type("construction interrupted")
    owned = (tmp_path / "owned.txt").open("w")
    borrowed = (tmp_path / "borrowed.txt").open("w")
    stores = []

    def factory(config, context):
        stores.append(context.store)
        context.own(owned)
        raise interruption

    registry = ComponentRegistry()
    registry.register("provider", "interrupted", factory)
    try:
        with pytest.raises(error_type) as failure:
            RuntimeBuilder(registry).build(
                profile(providers={"default": {"adapter": "interrupted"}}),
                tmp_path / "runs.sqlite",
            )
        assert failure.value is interruption
        assert owned.closed
        assert not borrowed.closed
        with pytest.raises(sqlite3.ProgrammingError):
            stores[0].conn.execute("SELECT 1")
    finally:
        for store in stores:
            store.close()
        owned.close()
        borrowed.close()


@pytest.mark.parametrize("error_type", INTERRUPTIONS)
def test_interrupted_resource_cleanup_retains_a_retriable_stopped_handle(tmp_path, error_type):
    interruption = error_type("cleanup interrupted")
    owned = (tmp_path / "owned.txt").open("w")
    completed = (tmp_path / "completed.txt").open("w")
    stores = []

    class InterruptedResource:
        attempts = 0

        def close(self):
            self.attempts += 1
            if self.attempts == 1:
                raise interruption
            owned.close()

    resource = InterruptedResource()

    def factory(config, context):
        stores.append(context.store)
        context.own(resource)
        context.own(completed)
        raise ValueError("construction failed")

    registry = ComponentRegistry()
    registry.register("provider", "interrupted-cleanup", factory)
    failure = None
    try:
        try:
            RuntimeBuilder(registry).build(
                profile(providers={"default": {"adapter": "interrupted-cleanup"}}),
                tmp_path / "runs.sqlite",
            )
        except BaseException as error:
            failure = error
        assert isinstance(failure, RuntimeBuildError), type(failure).__name__
        assert failure.__cause__ is interruption
        assert completed.closed
        assert not owned.closed
        with pytest.raises(sqlite3.ProgrammingError):
            stores[0].conn.execute("SELECT 1")
        failure.cleanup.close()
        failure.cleanup.close()
        assert owned.closed
        assert resource.attempts == 2
    finally:
        for store in stores:
            store.close()
        owned.close()
        completed.close()


@pytest.mark.parametrize("error_type", INTERRUPTIONS)
def test_interrupted_engine_cleanup_keeps_the_lease_until_cleanup_retry(tmp_path, error_type):
    interruption = error_type("engine close interrupted")
    owned = (tmp_path / "owned.txt").open("w")
    engines = []

    class IncompleteEngine(LocalEngine):
        # A rejected candidate is still responsible for its acquired lease.
        drive = None
        close_attempts = 0

        def close(self):
            self.close_attempts += 1
            if self.close_attempts == 1:
                raise interruption
            super().close()

    def provider(config, context):
        from relf_agent.runtime_builder import EchoProvider

        context.own(owned)
        return EchoProvider("fixture")

    def engine_factory(store, **options):
        engine = IncompleteEngine(store, **options)
        engines.append(engine)
        return engine

    registry = ComponentRegistry()
    registry.register("provider", "owned", provider)
    path = tmp_path / "runs.sqlite"
    failure = None
    try:
        try:
            RuntimeBuilder(registry, engine_factory=engine_factory).build(
                profile(providers={"default": {"adapter": "owned"}}), path
            )
        except BaseException as error:
            failure = error
        assert isinstance(failure, RuntimeBuildError), type(failure).__name__
        assert failure.__cause__ is interruption
        assert not owned.closed
        with SQLiteStore(path) as other:
            with pytest.raises(CoordinatorBusy):
                other.create_coordinator().acquire()
        failure.cleanup.close()
        failure.cleanup.close()
        assert owned.closed
        assert engines[0].close_attempts == 2
        with SQLiteStore(path) as other:
            lease = other.create_coordinator()
            lease.acquire()
            lease.release()
    finally:
        for engine in engines:
            engine.close()
        owned.close()
