"""Native async Redis Streams MessageBus with retained identities and PEL.

No XTRIM/MAXLEN is issued. Capacity rejects publication, including when older
entries are acknowledged; retention remains an explicit deployment operation.
"""

import asyncio
import json
import math
from dataclasses import asdict
from urllib.parse import urlsplit

from .errors import IdempotencyConflict, ValidationError
from .messaging import (
    Delivery,
    MessageBusError,
    MessageEnvelope,
    _binding,
    _delivery,
    _inputs,
    _integer,
    _json,
    _text,
)
from .ports import is_async_callable
from .types import digest

_PUBLISH = """
local previous = redis.call('HGET', KEYS[2], ARGV[1])
if previous then
    if redis.call('HGET', KEYS[3], ARGV[1]) ~= ARGV[2] then return {0} end
    return {1, previous}
end
if redis.call('XLEN', KEYS[1]) >= tonumber(ARGV[4]) then return {2} end
local id = redis.call('XADD', KEYS[1], '*', 'message', ARGV[3])
redis.call('HSET', KEYS[2], ARGV[1], id)
redis.call('HSET', KEYS[3], ARGV[1], ARGV[2])
return {1, id}
"""
_ACK = """
local pending = redis.call('XPENDING', KEYS[1], ARGV[1], ARGV[2], ARGV[2], 1)
if #pending == 0 or pending[1][2] ~= ARGV[3] then return 0 end
local entry = redis.call('XRANGE', KEYS[1], ARGV[2], ARGV[2])
if #entry == 0 or entry[1][2][2] ~= ARGV[4] then return -1 end
return redis.call('XACK', KEYS[1], ARGV[1], ARGV[2])
"""


def _decode(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


class RedisStreamsBus:
    def __init__(
        self,
        client,
        *,
        backend_id,
        prefix="ralf-mq",
        owns_client=False,
        max_entries=10000,
        timeout=10,
    ):  # noqa: ASYNC109
        _text(backend_id, "Redis backend identity")
        _text(prefix, "Redis prefix")
        if "{" in prefix or "}" in prefix:
            raise ValidationError("Redis prefix cannot contain hash tag braces")
        _integer(max_entries, "Message capacity", 1, 1000000)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValidationError("Redis timeout must be finite and positive")
        if (
            type(owns_client) is not bool
            or not callable(getattr(client, "eval", None))
            or not (
                is_async_callable(getattr(client, "eval", None))
                or is_async_callable(getattr(client, "execute_command", None))
            )
        ):
            raise ValidationError("RedisStreamsBus requires a native async Redis client")
        if owns_client and not is_async_callable(getattr(client, "aclose", None)):
            raise ValidationError("Owned Redis clients require async aclose")
        self.backend_id = backend_id
        self._prefix = prefix
        self._client = client
        self._owns_client = owns_client
        self._max_entries = max_entries
        self._timeout = timeout
        self._closed = False
        self._close_lock = asyncio.Lock()

    @classmethod
    async def connect(cls, url, *, backend_id, prefix="ralf-mq", max_entries=10000, timeout=10):  # noqa: ASYNC109
        _text(url, "Redis URL")
        try:
            if urlsplit(url).scheme not in {"redis", "rediss", "unix"}:
                raise ValidationError("Redis URL requires redis, rediss or unix")
        except ValueError as exc:
            raise ValidationError("Invalid Redis URL") from exc

        # Validate the adapter configuration before opening a connection.
        class Probe:
            async def eval(self, *args):
                pass

        cls(Probe(), backend_id=backend_id, prefix=prefix, max_entries=max_entries, timeout=timeout)
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise ValidationError("Redis Streams requires the optional redis dependency") from exc
        client = None
        try:
            client = Redis.from_url(url, socket_timeout=timeout, socket_connect_timeout=timeout)
            client.connection_pool.connection_kwargs.update(
                socket_timeout=timeout, socket_connect_timeout=timeout
            )
            async with asyncio.timeout(timeout):
                await client.ping()
            return cls(
                client,
                backend_id=backend_id,
                prefix=prefix,
                owns_client=True,
                max_entries=max_entries,
                timeout=timeout,
            )
        except BaseException as exc:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass
            if not isinstance(exc, Exception):
                raise
            raise MessageBusError("Redis message connection failed") from exc

    def _keys(self, scope, topic):
        tag = digest({"scope": asdict(scope), "topic": topic})
        return [
            f"{self._prefix}:{{{tag}}}:{suffix}" for suffix in ("stream", "identities", "digests")
        ]

    async def _call(self, method, *args, **kwargs):
        if self._closed:
            raise MessageBusError("Redis message bus is closed")
        try:
            async with asyncio.timeout(self._timeout):
                return await getattr(self._client, method)(*args, **kwargs)
        except Exception as exc:
            raise MessageBusError("Redis message operation failed") from exc

    async def ensure_group(self, scope, topic, group):
        _inputs(scope, topic, group)
        try:
            await self._call(
                "xgroup_create", self._keys(scope, topic)[0], group, id="0-0", mkstream=True
            )
        except MessageBusError as exc:
            # Exact server condition, never broad suppression of transport failures.
            from redis.exceptions import ResponseError

            if not isinstance(exc.__cause__, ResponseError) or not str(exc.__cause__).startswith(
                "BUSYGROUP "
            ):
                raise

    async def publish(self, scope, message):
        if not isinstance(message, MessageEnvelope):
            raise ValidationError("Publish requires a MessageEnvelope")
        _inputs(scope, message.topic)
        encoded = _json(message.to_dict())
        result = await self._call(
            "eval",
            _PUBLISH,
            3,
            *self._keys(scope, message.topic),
            message.message_id,
            digest(message.to_dict()),
            encoded,
            self._max_entries,
        )
        if result == [0]:
            raise IdempotencyConflict("Message identity conflict")
        if result == [2]:
            raise MessageBusError("Message capacity reached; archive before publishing")
        if not isinstance(result, list) or len(result) != 2 or result[0] != 1:
            raise MessageBusError("Redis messages returned invalid data")
        identity = _decode(result[1])
        if not isinstance(identity, str) or not identity:
            raise MessageBusError("Redis messages returned invalid data")
        return identity

    @staticmethod
    def _rows(rows, scope, topic, group, consumer, limit):
        try:
            if not isinstance(rows, (list, tuple)) or len(rows) > limit:
                raise ValueError("invalid rows")
            result = []
            for identity, fields in rows:
                if not isinstance(fields, dict) or len(fields) != 1:
                    raise ValueError("invalid fields")
                raw = fields.get("message", fields.get(b"message"))
                if not isinstance(raw, (bytes, str)) or len(raw) > 262144:
                    raise ValueError("invalid message")
                value = json.loads(raw)
                message = MessageEnvelope(**value)
                if message.topic != topic:
                    raise ValueError("invalid topic")
                result.append(
                    Delivery(_decode(identity), message, consumer, _binding(scope, topic, group))
                )
            return result
        except Exception as exc:
            raise MessageBusError("Redis messages returned invalid data") from exc

    async def receive(self, scope, topic, group, consumer, *, limit=1):
        _inputs(scope, topic, group, consumer)
        _integer(limit, "Receive limit")
        key = self._keys(scope, topic)[0]
        result = await self._call("xreadgroup", group, consumer, {key: ">"}, count=limit)
        if result == []:
            return []
        if not isinstance(result, list) or len(result) != 1 or _decode(result[0][0]) != key:
            raise MessageBusError("Redis messages returned invalid data")
        return self._rows(result[0][1], scope, topic, group, consumer, limit)

    async def claim(self, scope, topic, group, consumer, *, min_idle_ms, limit=1):
        _inputs(scope, topic, group, consumer)
        _integer(limit, "Claim limit")
        _integer(min_idle_ms, "Minimum idle time", 0, 2**31 - 1)
        # XPENDING scans only a bounded page. Repeated callers should allow idle
        # time and rotate ownership; already claimed rows acquire a fresh idle.
        key = self._keys(scope, topic)[0]
        pending = await self._call("xpending_range", key, group, "-", "+", limit, idle=min_idle_ms)
        try:
            identities = [item.get("message_id", item.get(b"message_id")) for item in pending]
            if len(identities) > limit or any(
                not isinstance(item, (bytes, str)) for item in identities
            ):
                raise ValueError("invalid pending identities")
        except Exception as exc:
            raise MessageBusError("Redis messages returned invalid data") from exc
        if not identities:
            return []
        rows = await self._call("xclaim", key, group, consumer, min_idle_ms, identities)
        return self._rows(rows, scope, topic, group, consumer, limit)

    async def ack(self, scope, topic, group, delivery):
        _delivery(scope, topic, group, delivery)
        result = await self._call(
            "eval",
            _ACK,
            1,
            self._keys(scope, topic)[0],
            group,
            delivery.broker_id,
            delivery.consumer,
            _json(delivery.message.to_dict()),
        )
        if type(result) is not int or result not in (0, 1):
            raise MessageBusError("Redis message acknowledgement failed")
        return result

    async def aclose(self):
        async with self._close_lock:
            if self._closed:
                return
            if self._owns_client:
                try:
                    async with asyncio.timeout(self._timeout):
                        await self._client.aclose()
                except Exception as exc:
                    raise MessageBusError("Redis message close failed") from exc
            self._closed = True
