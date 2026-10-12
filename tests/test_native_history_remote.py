"""Real native history read contracts on explicitly supplied disposable services.

Set RALF_DEV89_REDIS_URL / RALF_DEV89_POSTGRES_DSN to the isolated services.
Every case has its own Scope and Redis prefix; no existing service is selected.
"""

import asyncio
import copy
import os
import uuid
from contextlib import asynccontextmanager

import pytest

from ralf_agent import (
    Scope,
    native_history_address,
    native_history_envelope,
    read_native_history,
)
from ralf_agent.binding_sessions import SessionBindingResource
from ralf_agent.errors import IdempotencyConflict, ValidationError
from ralf_agent.types import canonical, digest


@pytest.fixture(params=["redis", "postgres"])
def endpoint(request):
    variable = {
        "redis": "RALF_DEV89_REDIS_URL",
        "postgres": "RALF_DEV89_POSTGRES_DSN",
    }[request.param]
    value = os.environ.get(variable)
    if not value:
        pytest.skip(f"Set {variable} to an isolated disposable service for real integration")
    pytest.importorskip("redis.asyncio" if request.param == "redis" else "psycopg")
    return request.param, value


@asynccontextmanager
async def remote(endpoint):
    kind, url = endpoint
    unique = uuid.uuid4().hex
    scope = Scope("dev89-native-" + unique, "native-test-owner")
    if kind == "redis":
        from ralf_agent.redis_memory import RedisMemory

        prefix = "dev89-native-" + unique
        backend = await RedisMemory.connect(url, prefix=prefix, backend_id="dev89-native-redis")
    else:
        from ralf_agent.postgres import PostgresMemory

        backend = await PostgresMemory.connect(url, backend_id="dev89-native-postgres")
        await backend.initialize()
    try:
        yield backend, scope, digest({"workspace": scope.workspace, "stream": "root/agent"})
    finally:
        if kind == "redis":
            keys = [key async for key in backend._client.scan_iter(match=prefix + ":*")]
            if keys:
                await backend._client.delete(*keys)
        else:
            for table in ("ralf_memory_messages", "ralf_memory_sessions"):
                await backend.connection.execute(
                    f"DELETE FROM {table} WHERE workspace=%s",
                    (scope.workspace,),
                )
        await backend.aclose()


def turn(stream, seq, *, tool_chars=0):
    history = [
        {"role": "system", "content": "Retain the original signed native evidence."},
        {"role": "user", "content": f"current task {seq}"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "reused-per-complete-group",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"q":"原文","integer":9007199254740997}',
                    },
                }
            ],
            "model_continuation": {"opaque": {"signature": f"signed-{seq}"}},
        },
        {
            "role": "tool",
            "tool_call_id": "reused-per-complete-group",
            "name": "lookup",
            "content": {
                "original": "x" * tool_chars,
                "exact": 9007199254740997,
                "unicode": "原文🌍",
            },
        },
        {
            "role": "assistant",
            "content": '{"answer":' + str(seq) + "}",
            "tool_calls": [],
            "model_continuation": {"opaque": {"final_signature": f"final-{seq}"}},
        },
    ]
    return native_history_envelope(
        stream,
        {
            "root_run_id": f"root-{seq}",
            "run_id": f"run-{seq}",
            "node": "root/agent",
            "release_digest": "b" * 64,
            "turn_id": f"turn-{seq}",
            "turn_seq": seq,
        },
        history,
        "c" * 64,
    )


async def publish(backend, scope, stream, count, *, tool_chars=0):
    address = native_history_address(stream)
    values = [turn(stream, seq, tool_chars=tool_chars) for seq in range(count)]
    for seq, value in enumerate(values):
        assert (
            await backend.append(
                scope, address, value, expected_revision=seq, message_id=f"native-{seq}"
            )
            == seq + 1
        )
    return values


def test_real_remote_native_reader_restores_all_128_signed_tool_turns(endpoint):
    async def run():
        async with remote(endpoint) as (backend, scope, stream):
            original = await publish(backend, scope, stream, 128)
            result = await read_native_history(
                backend, scope, native_history_address(stream), stream=stream
            )
            assert result["revision"] == 128
            assert canonical(result["turns"]) == canonical(original)
            result["turns"][0]["history"][2]["model_continuation"]["opaque"]["signature"] = (
                "changed"
            )
            again = await read_native_history(
                backend, scope, native_history_address(stream), stream=stream
            )
            assert (
                again["turns"][0]["history"][2]["model_continuation"]["opaque"]["signature"]
                == "signed-0"
            )

    asyncio.run(run())


def test_real_remote_native_reader_fixes_high_water_snapshot_during_append(endpoint):
    async def run():
        async with remote(endpoint) as (backend, scope, stream):
            await publish(backend, scope, stream, 101)

            class AppendAfterFirstPage:
                backend_id = "dev89-native-snapshot-source"

                async def read_page(self, actual_scope, address, query):
                    page = await backend.read_page(actual_scope, address, query)
                    if query.cursor is None:
                        await backend.append(
                            actual_scope,
                            address,
                            turn(stream, 101),
                            expected_revision=101,
                            message_id="late-101",
                        )
                    return page

                async def read(self, *args):
                    pytest.fail("Native data must never use an unbounded full remote read")

            result = await read_native_history(
                AppendAfterFirstPage(), scope, native_history_address(stream), stream=stream
            )
            assert result["revision"] == 101
            assert [item["source"]["turn_seq"] for item in result["turns"]] == list(range(101))
            later = await read_native_history(
                backend, scope, native_history_address(stream), stream=stream
            )
            assert later["revision"] == 102
            assert later["turns"][-1]["source"]["turn_seq"] == 101

    asyncio.run(run())


def test_real_remote_native_exact_receipt_recovers_duplicate_ack_without_rewrite(endpoint):
    async def run():
        async with remote(endpoint) as (backend, scope, stream):
            original = (await publish(backend, scope, stream, 1))[0]
            address = native_history_address(stream)
            assert (
                await backend.append(
                    scope, address, original, expected_revision=999, message_id="native-0"
                )
                == 1
            )
            receipt = await backend.inspect_message(scope, address, "native-0")
            assert receipt["receipt"] == {"revision": 1, "message": original}
            changed = copy.deepcopy(original)
            changed["history"][3]["content"]["exact"] = 1
            with pytest.raises(IdempotencyConflict):
                await backend.append(
                    scope, address, changed, expected_revision=1, message_id="native-0"
                )
            result = await read_native_history(backend, scope, address, stream=stream)
            assert result["revision"] == 1 and result["turns"] == [original]

    asyncio.run(run())


def test_real_remote_native_history_isolates_scope_and_namespace(endpoint):
    async def run():
        async with remote(endpoint) as (backend, scope, stream):
            resource = SessionBindingResource(
                backend, namespaces=("first", "second"), default_namespace="first"
            )
            first, second = (
                resource.select({}, scope),
                resource.select({"namespace": "second"}, scope),
            )
            original = await publish(first, scope, stream, 2)
            visible = await read_native_history(
                first, scope, native_history_address(stream), stream=stream
            )
            assert visible["turns"] == original
            hidden = await read_native_history(
                second, scope, native_history_address(stream), stream=stream
            )
            assert hidden["revision"] == 0 and hidden["turns"] == []
            other = await read_native_history(
                backend,
                Scope(scope.workspace, "other-owner"),
                native_history_address(stream),
                stream=stream,
            )
            assert other["revision"] == 0 and other["turns"] == []

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["turns", "record", "budget", "stream"])
def test_real_remote_native_reader_rejects_incomplete_or_untrusted_data(endpoint, boundary):
    async def run():
        async with remote(endpoint) as (backend, scope, stream):
            if boundary == "turns":
                await publish(backend, scope, stream, 129)
            elif boundary == "record":
                oversized = turn(stream, 0)
                oversized["history"][3]["content"]["original"] = "x" * 1_000_001
                await backend.append(
                    scope,
                    native_history_address(stream),
                    oversized,
                    expected_revision=0,
                    message_id="oversized",
                )
            elif boundary == "stream":
                await backend.append(
                    scope,
                    native_history_address(stream),
                    turn("d" * 64, 0),
                    expected_revision=0,
                    message_id="wrong-stream",
                )
            else:
                await publish(backend, scope, stream, 2)
            with pytest.raises(ValidationError):
                await read_native_history(
                    backend,
                    scope,
                    native_history_address(stream),
                    stream=stream,
                    **({"max_chars": 1500} if boundary == "budget" else {}),
                )

    asyncio.run(run())


def test_real_remote_native_reader_retains_two_large_valid_tool_turns(endpoint):
    async def run():
        async with remote(endpoint) as (backend, scope, stream):
            original = await publish(backend, scope, stream, 2, tool_chars=600_000)
            result = await read_native_history(
                backend, scope, native_history_address(stream), stream=stream
            )
            assert result["revision"] == 2
            assert result["turns"] == original

    asyncio.run(run())
