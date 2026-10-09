import asyncio
import importlib.util
import shutil
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from ralf_agent.errors import IdempotencyConflict, MemoryBackendError, ValidationError
from ralf_agent.recall import RecallQuery, _binding, _encode_cursor
from ralf_agent.types import Scope


def adapter():
    name = "ralf_agent.redis_memory"
    assert importlib.util.find_spec(name) is not None, "Missing RedisMemory adapter"
    return importlib.import_module(name).RedisMemory


@pytest.fixture
def redis_service():
    pytest.importorskip("redis.asyncio")
    binary = shutil.which("redis-server")
    if binary is None and Path("/opt/homebrew/bin/redis-server").is_file():
        binary = "/opt/homebrew/bin/redis-server"
    if binary is None:
        pytest.skip("Real Redis integration requires redis-server")
    with tempfile.TemporaryDirectory(prefix="ralf-redis-", dir="/tmp") as directory:
        socket = Path(directory) / "redis.sock"
        with (Path(directory) / "service.log").open("w+") as log:
            process = subprocess.Popen(
                [
                    binary,
                    "--port",
                    "0",
                    "--unixsocket",
                    str(socket),
                    "--unixsocketperm",
                    "700",
                    "--save",
                    "",
                    "--appendonly",
                    "no",
                    "--dir",
                    directory,
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 5
                while (
                    not socket.exists() and process.poll() is None and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                if not socket.exists() or process.poll() is not None:
                    log.seek(0)
                    pytest.fail("Isolated Redis failed to start: " + log.read())
                yield "unix://" + str(socket)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@asynccontextmanager
async def memory_at(url, prefix, *, decode_responses=False):
    from redis.asyncio import Redis

    client = Redis.from_url(url, decode_responses=decode_responses, socket_timeout=1)
    memory = adapter()(client, prefix=prefix, backend_id="redis:test")
    try:
        await client.ping()
        yield memory, client
    finally:
        await memory.aclose()
        await client.aclose()


@pytest.mark.parametrize("identity", [None, "", "  ", 123, False])
def test_backend_identity_is_explicit_nonempty_text(identity):
    with pytest.raises(ValidationError):
        adapter()(client=object(), prefix="tests", backend_id=identity)


@pytest.mark.parametrize("prefix", [None, "", " ", 1, "unsafe{slot}"])
def test_key_prefix_is_validated_before_client_use(prefix):
    with pytest.raises(ValidationError):
        adapter()(client=object(), prefix=prefix, backend_id="test")


def test_synchronous_redis_clients_are_rejected_before_io():
    redis = pytest.importorskip("redis")
    with pytest.raises(ValidationError):
        adapter()(redis.Redis(), backend_id="sync")


def test_owned_client_requires_async_close():
    class Client:
        async def eval(self, *args):
            pytest.fail("Invalid owned client reached Redis")

        def aclose(self):
            pass

    with pytest.raises(ValidationError):
        adapter()(Client(), backend_id="test", owns_client=True)


def test_connect_timeout_cannot_be_overridden_by_url_query(redis_service):
    async def check():
        from redis.asyncio import Redis

        client = Redis.from_url(redis_service)
        connected = None
        try:
            await client.execute_command("CLIENT", "PAUSE", 400, "ALL")
            started = time.monotonic()
            with pytest.raises(MemoryBackendError):
                connected = await adapter().connect(
                    redis_service + "?socket_timeout=10&socket_connect_timeout=10",
                    backend_id="paused",
                    timeout=0.03,
                )
            assert time.monotonic() - started < 0.25
        finally:
            if connected is not None:
                await connected.aclose()
            await client.aclose()

    asyncio.run(check())


@pytest.mark.parametrize("decode_responses", [False, True])
def test_real_sessions_preserve_json_and_original_message_identity(redis_service, decode_responses):
    async def check():
        async with memory_at(
            redis_service, f"sessions:{decode_responses}", decode_responses=decode_responses
        ) as (memory, client):
            scope = Scope("工作区{A}", "所有者")
            message = {
                "role": "user",
                "content": "你好🌍",
                "number": 9007199254740997,
                "float": 1.2345678901234567,
                "values": [None, True, {}],
            }
            assert await memory.read(scope, "会话") == (0, [])
            assert (
                await memory.append(
                    scope, "会话", message, expected_revision=0, message_id="原始🌍"
                )
                == 1
            )
            assert (
                await memory.append(
                    scope, "会话", message, expected_revision=99, message_id="原始🌍"
                )
                == 1
            )
            with pytest.raises(IdempotencyConflict):
                await memory.append(
                    scope, "会话", {"content": "changed"}, expected_revision=1, message_id="原始🌍"
                )
            with pytest.raises(ValidationError):
                await memory.append(scope, "会话", {}, expected_revision=0, message_id="other")
            assert await memory.read(scope, "会话") == (1, [message])
            assert await memory.read(Scope(scope.workspace, "other"), "会话") == (0, [])
            keys = await client.keys(f"sessions:{decode_responses}:*")
            from redis.crc import key_slot

            encoded = [key.encode() if isinstance(key, str) else key for key in keys]
            assert len({key_slot(key) for key in encoded}) == 1
            hashes = [key for key in keys if await client.type(key) in ("hash", b"hash")]
            assert any([await client.hexists(key, "原始🌍") for key in hashes])

    asyncio.run(check())


def test_real_concurrent_initial_cas_and_duplicate_message_conflict(redis_service):
    async def check():
        async with memory_at(redis_service, "races") as (memory, _):
            results = await asyncio.gather(
                *[
                    memory.append(
                        Scope(), "s", {"winner": i}, expected_revision=0, message_id=f"m{i}"
                    )
                    for i in range(20)
                ],
                return_exceptions=True,
            )
            assert results.count(1) == 1
            assert sum(isinstance(result, ValidationError) for result in results) == 19
            results = await asyncio.gather(
                *[
                    memory.append(
                        Scope(), "dedup", {"winner": i}, expected_revision=0, message_id="same"
                    )
                    for i in range(20)
                ],
                return_exceptions=True,
            )
            assert results.count(1) == 1
            assert sum(isinstance(result, IdempotencyConflict) for result in results) == 19
            results = await asyncio.gather(
                *[
                    memory.put_fact(Scope(), "facts", "key", i, expected_version=0)
                    for i in range(20)
                ],
                return_exceptions=True,
            )
            assert results.count(1) == 1
            assert sum(isinstance(result, ValidationError) for result in results) == 19

    asyncio.run(check())


def test_real_fact_expiry_retains_version_and_references_are_rechecked(redis_service):
    async def check():
        async with memory_at(redis_service, "expiry") as (memory, _):
            scope = Scope()
            assert (
                await memory.put_fact(
                    scope, "n", "expired", "旧值", expected_version=0, expires_at=time.time() - 1
                )
                == 1
            )
            assert await memory.facts(scope, "n") == []
            with pytest.raises(ValidationError):
                await memory.put_fact(scope, "n", "expired", "reset", expected_version=0)
            assert (
                await memory.put_fact(
                    scope, "n", "expired", {"中文": 9007199254740997}, expected_version=1
                )
                == 2
            )
            references = await memory.facts(scope, "n")
            assert references == [
                {
                    "key": "expired",
                    "value": {"中文": 9007199254740997},
                    "version": 2,
                    "expires_at": None,
                }
            ]
            await memory.validate_facts(scope, "n", references)
            with pytest.raises(ValidationError):
                await memory.validate_facts(scope, "n", [{**references[0], "value": "tampered"}])
            with pytest.raises(ValidationError):
                await memory.validate_facts(Scope(principal="other"), "n", references)
            assert (
                await memory.put_fact(scope, "n", "expired", "replacement", expected_version=2) == 3
            )
            with pytest.raises(ValidationError):
                await memory.validate_facts(scope, "n", references)
            await memory.put_fact(
                scope, "n", "short", 1, expected_version=0, expires_at=time.time() + 0.03
            )
            expiring = [item for item in await memory.facts(scope, "n") if item["key"] == "short"]
            await asyncio.sleep(0.04)
            with pytest.raises(ValidationError):
                await memory.validate_facts(scope, "n", expiring)

    asyncio.run(check())


def test_real_session_pages_keep_high_watermark_and_bounded_candidates(redis_service):
    async def check():
        async with memory_at(redis_service, "pages") as (memory, _):
            scope = Scope()
            for i in range(7):
                await memory.append(scope, "s", {"i": i}, expected_revision=i, message_id=str(i))
            query = RecallQuery(max_items=2, scan_limit=3)
            first = await memory.read_page(scope, "s", query)
            assert first.items == [{"i": 5}, {"i": 6}]
            assert first.scanned == 2 and first.backend_bounded and first.next_cursor
            await memory.append(scope, "s", {"i": 7}, expected_revision=7, message_id="7")
            second = await memory.read_page(scope, "s", replace(query, cursor=first.next_cursor))
            third = await memory.read_page(scope, "s", replace(query, cursor=second.next_cursor))
            fourth = await memory.read_page(scope, "s", replace(query, cursor=third.next_cursor))
            assert second.items == [{"i": 3}, {"i": 4}]
            assert third.items == [{"i": 1}, {"i": 2}]
            assert fourth.items == [{"i": 0}] and fourth.next_cursor is None
            assert len({page.snapshot_id for page in (first, second, third, fourth)}) == 1
            filtered = await memory.read_page(
                scope, "s", RecallQuery(max_items=1, scan_limit=2, text="missing")
            )
            assert filtered.items == [] and filtered.scanned == filtered.skipped == 2
            assert filtered.next_cursor is not None
            with pytest.raises(ValidationError):
                await memory.read_page(
                    Scope(principal="other"), "s", replace(query, cursor=first.next_cursor)
                )
            with pytest.raises(ValidationError):
                await memory.read_page(
                    scope, "s", replace(query, max_chars=20, cursor=first.next_cursor)
                )

    asyncio.run(check())


def test_real_fact_pages_use_insertion_order_and_invalidate_after_write(redis_service):
    async def check():
        async with memory_at(redis_service, "fact-pages") as (memory, _):
            scope = Scope()
            for key in ("z", "a", "m", "b"):
                await memory.put_fact(scope, "n", key, {"name": key}, expected_version=0)
            query = RecallQuery(max_items=2, scan_limit=2)
            first = await memory.recall(scope, "n", query)
            second = await memory.recall(scope, "n", replace(query, cursor=first.next_cursor))
            assert [item["key"] for item in first.items + second.items] == ["z", "a", "m", "b"]
            assert second.next_cursor is None and first.snapshot_id == second.snapshot_id
            assert [item["key"] for item in await memory.facts(scope, "n")] == ["a", "b", "m", "z"]
            await memory.put_fact(scope, "n", "a", "changed", expected_version=1)
            with pytest.raises(ValidationError):
                await memory.recall(scope, "n", replace(query, cursor=first.next_cursor))
            empty = await memory.recall(scope, "other", query)
            assert empty.items == [] and empty.scanned == 0 and empty.next_cursor is None

    asyncio.run(check())


def test_invalid_inputs_are_rejected_before_any_io():
    class NoIO:
        async def eval(self, *args):
            pytest.fail("Invalid memory inputs reached Redis")

    async def check():
        memory = adapter()(NoIO(), backend_id="test")
        scope = Scope()
        operations = [
            memory.read({}, "s"),
            memory.read(scope, " "),
            memory.facts({}, "n"),
            memory.facts(scope, ""),
            memory.append(scope, "s", [], expected_revision=0, message_id="m"),
            memory.append(scope, "s", {}, expected_revision=True, message_id="m"),
            memory.append(scope, "s", {}, expected_revision=-1, message_id="m"),
            memory.append(scope, "s", {}, expected_revision=0, message_id=""),
            memory.put_fact(scope, "n", "k", 1, expected_version=False),
            memory.put_fact(scope, "n", " ", 1, expected_version=0),
            memory.put_fact(scope, "n", "k", float("nan"), expected_version=0),
            memory.read_page(scope, "s", {}),
            memory.recall(scope, "n", {}),
            memory.read_page(scope, "s", RecallQuery(cursor="invalid")),
            memory.recall(scope, "n", RecallQuery(cursor="invalid")),
            memory.validate_facts({}, "n", []),
            memory.validate_facts(scope, "n", [{"key": "k"}]),
        ]
        operations.extend(
            memory.put_fact(scope, "n", "k", 1, expected_version=0, expires_at=expiry)
            for expiry in (True, "1", float("inf"), float("nan"), 10**1000)
        )
        for operation in operations:
            with pytest.raises(ValidationError):
                await operation
        await memory.aclose()

    asyncio.run(check())


def test_owned_and_borrowed_lifecycles_and_disconnect_errors(redis_service):
    async def check():
        async with memory_at(redis_service, "borrowed") as (borrowed, client):
            connection = await client.connection_pool.get_connection()
            await client.connection_pool.release(connection)
            assert connection.is_connected
            await borrowed.aclose()
            assert connection.is_connected
            assert await client.ping() is True
            with pytest.raises(MemoryBackendError):
                await borrowed.read(Scope(), "s")
        owned = await adapter().connect(
            redis_service, backend_id="owned", prefix="owned", timeout=1
        )
        await owned.append(Scope(), "s", {}, expected_revision=0, message_id="m")
        await owned.aclose()
        await owned.aclose()
        with pytest.raises(MemoryBackendError):
            await owned.read(Scope(), "s")
        with pytest.raises(MemoryBackendError) as error:
            await adapter().connect(
                "unix:///tmp/ralf-redis-missing/secret.sock", backend_id="fail", timeout=0.05
            )
        assert "secret.sock" not in str(error.value)

    asyncio.run(check())


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"generation": 1},
        {"generation": 1, "revision": None},
        {"generation": 1, "revision": True},
        {"generation": 1, "revision": -1},
    ],
)
def test_session_cursor_shape_is_rejected_before_io(snapshot):
    class NoIO:
        async def eval(self, *args):
            pytest.fail("Malformed cursor reached Redis")

    async def check():
        memory = adapter()(NoIO(), backend_id="test")
        scope = Scope()
        query = RecallQuery()
        binding = _binding("test", scope, "session", "s", query)
        query = replace(query, cursor=_encode_cursor(binding, snapshot, 1))
        with pytest.raises(ValidationError):
            await memory.read_page(scope, "s", query)

    asyncio.run(check())


def test_real_pages_skip_oversized_and_expired_candidates(redis_service):
    async def check():
        async with memory_at(redis_service, "bounds") as (memory, _):
            scope = Scope()
            await memory.put_fact(scope, "n", "gone", "expired", expected_version=0, expires_at=-1)
            await memory.put_fact(scope, "n", "big", "界" * 1000, expected_version=0)
            await memory.put_fact(scope, "n", "fit", "好", expected_version=0)
            page = await memory.recall(
                scope, "n", RecallQuery(max_items=1, scan_limit=3, max_chars=150)
            )
            assert [item["key"] for item in page.items] == ["fit"]
            assert page.scanned == 3 and page.skipped == 2 and page.next_cursor is None
            assert page.used_chars <= 150
            await memory.append(
                scope, "s", {"value": "界" * 1000}, expected_revision=0, message_id="0"
            )
            await memory.append(scope, "s", {"value": "好"}, expected_revision=1, message_id="1")
            page = await memory.read_page(
                scope, "s", RecallQuery(max_items=2, scan_limit=2, max_chars=50)
            )
            assert page.items == [{"value": "好"}]
            assert page.scanned == 2 and page.skipped == 1 and page.used_chars == 15

    asyncio.run(check())


def test_real_server_disconnect_has_safe_typed_error(redis_service):
    async def check():
        async with memory_at(redis_service, "disconnect") as (memory, client):
            await memory.append(Scope(), "s", {}, expected_revision=0, message_id="m")
            await client.shutdown(nosave=True)
            with pytest.raises(MemoryBackendError) as error:
                await memory.read(Scope(), "s")
            assert "redis.sock" not in str(error.value)
            assert "ralf-redis-" not in str(error.value)

    asyncio.run(check())


def test_owned_adapter_closes_real_connection_through_build_context(redis_service):
    async def check():
        from redis.asyncio import Redis

        from ralf_agent.runtime_lifecycle import BuildContext

        client = Redis.from_url(redis_service, socket_timeout=1)
        memory = adapter()(client, backend_id="context", owns_client=True)
        context = BuildContext(object(), ":memory:", Scope(), ".", allow_async=True)
        assert context.own_async(memory) is memory
        await memory.read(Scope(), "s")
        connection = await client.connection_pool.get_connection()
        await client.connection_pool.release(connection)
        assert connection.is_connected
        await asyncio.gather(context.cleanup_async(), memory.aclose())
        assert not connection.is_connected
        await memory.aclose()
        assert not context.has_async_resources

    asyncio.run(check())


@pytest.mark.parametrize("timeout", [0, -1, True, "1", float("inf"), float("nan")])
def test_connect_rejects_invalid_timeout_before_connection(timeout):
    async def check():
        with pytest.raises(ValidationError):
            await adapter().connect("redis://localhost", backend_id="test", timeout=timeout)

    asyncio.run(check())
