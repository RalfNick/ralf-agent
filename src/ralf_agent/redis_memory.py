"""Native async Redis Session/Facts ports with atomic CAS and bounded recall.

Fact expiry is logical: records and versions remain until the deployment removes
them. Configure Redis persistence/eviction according to the application's needs.
Redis memory is independent from the execution journal's authority.
"""

import asyncio
import json
import math
import secrets
import time
from dataclasses import asdict
from urllib.parse import urlsplit

from .errors import BudgetExceeded, IdempotencyConflict, MemoryBackendError, ValidationError
from .memory import _session_cursor, _validate_expires_at
from .ports import is_async_callable
from .recall import (
    _binding,
    _current_fact,
    _decode_cursor,
    _fact_inputs,
    _fact_records,
    _integer,
    _name,
    _page,
)
from .types import Scope, canonical, digest

# Lua never decodes user JSON. In particular, cjson would round large integers
# and re-encode floats, defeating exact message identity comparisons.
_APPEND = """
local revision = redis.call('LLEN', KEYS[1])
local generation = redis.call('GET', KEYS[3])
local previous = redis.call('HGET', KEYS[2], ARGV[2])
if previous then
    if redis.call('LINDEX', KEYS[1], tonumber(previous) - 1) ~= ARGV[3] then
        return {2}
    end
    return {1, previous}
end
if tostring(revision) ~= ARGV[1] then return {0} end
if not generation then redis.call('SET', KEYS[3], ARGV[4]) end
redis.call('RPUSH', KEYS[1], ARGV[3])
redis.call('HSET', KEYS[2], ARGV[2], tostring(revision + 1))
return {1, revision + 1}
"""

_READ = """
local revision = redis.call('LLEN', KEYS[1])
return {revision, redis.call('LRANGE', KEYS[1], 0, -1)}
"""

_INSPECT = """
local revision = redis.call('LLEN', KEYS[1])
local previous = redis.call('HGET', KEYS[2], ARGV[1])
if not previous then return {revision, 0, ''} end
return {revision, previous, redis.call('LINDEX', KEYS[1], tonumber(previous) - 1) or ''}
"""

_SESSION_PAGE = """
local revision = redis.call('LLEN', KEYS[1])
local generation = redis.call('GET', KEYS[2]) or '0'
local before = tonumber(ARGV[1]) or (revision + 1)
local start = math.max(0, before - tonumber(ARGV[2]) - 1)
local rows = {}
if before > 1 then rows = redis.call('LRANGE', KEYS[1], start, before - 2) end
return {generation, revision, before, start, rows}
"""

_PUT_FACT = """
local actual = redis.call('HGET', KEYS[2], ARGV[1]) or '0'
local generation = redis.call('GET', KEYS[4])
redis.call('HLEN', KEYS[1])
redis.call('LLEN', KEYS[3])
if actual ~= ARGV[2] then return {0} end
if not generation then redis.call('SET', KEYS[4], ARGV[5]) end
if actual == '0' then redis.call('RPUSH', KEYS[3], ARGV[1]) end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[4])
redis.call('HSET', KEYS[2], ARGV[1], ARGV[3])
redis.call('INCR', KEYS[4])
return {1, ARGV[3]}
"""

_FACTS = "return redis.call('HVALS', KEYS[1])"

_FACT_PAGE = """
local generation = redis.call('GET', KEYS[3]) or '0'
local count = redis.call('LLEN', KEYS[2])
local after = tonumber(ARGV[1])
local keys = redis.call('LRANGE', KEYS[2], after, after + tonumber(ARGV[2]) - 1)
local rows = {}
for i, key in ipairs(keys) do rows[i] = redis.call('HGET', KEYS[1], key) end
return {generation, count, rows}
"""

_VALIDATE_FACTS = """
local rows = {}
for i, key in ipairs(ARGV) do rows[i] = redis.call('HGET', KEYS[1], key) end
return rows
"""

_FACT_SCAN_HEADER = """
local epoch = redis.call('GET', KEYS[1])
if not epoch then
    redis.call('SET', KEYS[1], ARGV[1])
    epoch = ARGV[1]
end
return {epoch, redis.call('GET', KEYS[2]) or '0'}
"""

_FACT_SCAN = """
local epoch = redis.call('GET', KEYS[4])
if not epoch then redis.call('SET', KEYS[4], ARGV[1]); epoch = ARGV[1] end
local generation = redis.call('GET', KEYS[3]) or '0'
local count = redis.call('LLEN', KEYS[2])
local after, limit, budget = tonumber(ARGV[4]), tonumber(ARGV[5]), tonumber(ARGV[6])
if ARGV[2] ~= '' and (epoch ~= ARGV[2] or generation ~= ARGV[3]) then return {0} end
if after > count then return {0} end
local keys = redis.call('LRANGE', KEYS[2], after, after + limit - 1)
local rows, used, position = {}, 2, after
for i, key in ipairs(keys) do
    local row = redis.call('HGET', KEYS[1], key)
    if not row then return {3} end
    local separator = 0
    if #rows > 0 then separator = 1 end
    if used + #row + separator > budget then
        if #rows == 0 then return {2} end
        break
    end
    rows[#rows + 1] = row
    used = used + #row + separator
    position = after + i
end
return {1, epoch, generation, count, position, used, rows}
"""


def _text(value, label):
    _name(value, label)
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValidationError(f"{label} must contain valid Unicode text") from exc


def _inputs(scope, name):
    if not isinstance(scope, Scope):
        raise ValidationError("Redis memory requires a trusted Scope")
    _text(scope.workspace, "Scope workspace")
    _text(scope.principal, "Scope principal")
    _text(name, "Memory namespace or session")


def _config(backend_id, prefix):
    _text(backend_id, "Redis backend identity")
    _text(prefix, "Redis key prefix")
    if "{" in prefix or "}" in prefix:
        raise ValidationError("Redis key prefix cannot contain hash tag braces")


def _payload(value):
    payload = canonical(value)
    try:
        payload.encode("utf-8")
    except UnicodeError as exc:
        raise ValidationError("Memory values must contain valid Unicode text") from exc
    return payload


def _number(value):
    if type(value) is int:
        number = value
    elif isinstance(value, (str, bytes)):
        number = int(value)
    else:
        raise ValueError("Invalid Redis count")
    if number < 0:
        raise ValueError("Invalid Redis count")
    return number


def _objects(rows):
    try:
        if not isinstance(rows, list):
            raise ValueError("Invalid Redis rows")
        items = [json.loads(row) for row in rows]
        if any(not isinstance(item, dict) for item in items):
            raise ValueError("Invalid Redis JSON object")
        canonical(items)
        return items
    except Exception as exc:
        raise MemoryBackendError("Redis memory returned invalid data") from exc


def _facts(rows):
    try:
        return _fact_records(_objects(rows))
    except ValidationError as exc:
        raise MemoryBackendError("Redis memory returned invalid data") from exc


class RedisMemory:
    """Borrow an async Redis client, or create an owned one with ``connect``.

    ``backend_id`` is a stable deployment identity used to bind recall cursors;
    ``prefix`` chooses the Redis data namespace. All keys for one scoped domain
    share a hash tag. The adapter does not apply physical key TTLs to facts.
    """

    fact_inspection_version = 1

    def __init__(self, client, *, backend_id, prefix="ralf", owns_client=False):
        _config(backend_id, prefix)
        if type(owns_client) is not bool:
            raise ValidationError("Redis client ownership must be a boolean")
        if not callable(getattr(client, "eval", None)) or not (
            is_async_callable(getattr(client, "eval", None))
            or is_async_callable(getattr(client, "execute_command", None))
        ):
            raise ValidationError("RedisMemory requires an async Redis client")
        if owns_client and not is_async_callable(getattr(client, "aclose", None)):
            raise ValidationError("Owned Redis clients require async aclose")
        self._backend_id = backend_id
        self._prefix = prefix
        self._client = client
        self._owns_client = owns_client
        self._closed = False
        self._close_lock = asyncio.Lock()

    @property
    def backend_id(self):
        return self._backend_id

    @classmethod
    async def connect(cls, url, *, backend_id, prefix="ralf", timeout=10):  # noqa: ASYNC109 -- public connection setting
        """Create, ping, and own a client with finite socket/connect timeouts."""
        _config(backend_id, prefix)
        _text(url, "Redis URL")
        try:
            valid_url = urlsplit(url).scheme in {"redis", "rediss", "unix"}
        except ValueError as exc:
            raise ValidationError("Redis URL is invalid") from exc
        if not valid_url:
            raise ValidationError("Redis URL must use redis, rediss or unix")
        timeout = _validate_expires_at(timeout)
        if timeout is None or timeout <= 0 or not math.isfinite(timeout):
            raise ValidationError("Redis timeout must be finite and positive")
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise ValidationError("RedisMemory requires the optional redis dependency") from exc
        client = None
        try:
            client = Redis.from_url(url, socket_timeout=timeout, socket_connect_timeout=timeout)
            # redis-py URL query options override from_url kwargs. Keep the
            # explicit adapter timeout authoritative for later operations too.
            client.connection_pool.connection_kwargs.update(
                socket_timeout=timeout, socket_connect_timeout=timeout
            )
            async with asyncio.timeout(timeout):
                await client.ping()
            return cls(client, backend_id=backend_id, prefix=prefix, owns_client=True)
        except BaseException as exc:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass
            if not isinstance(exc, Exception):
                raise
            raise MemoryBackendError("Redis memory connection failed") from exc

    def _keys(self, scope, domain, name, *suffixes):
        tag = digest({"scope": asdict(scope), "domain": domain, "name": name})
        return [f"{self._prefix}:{{{tag}}}:{suffix}" for suffix in suffixes]

    async def _eval(self, script, keys, *arguments):
        if self._closed:
            raise MemoryBackendError("Redis memory is closed")
        try:
            return await self._client.eval(script, len(keys), *keys, *arguments)
        except Exception as exc:
            raise MemoryBackendError("Redis memory operation failed") from exc

    @staticmethod
    def _counts(response, length):
        try:
            if not isinstance(response, list) or len(response) != length:
                raise ValueError("Invalid Redis response")
            return [_number(item) for item in response]
        except Exception as exc:
            raise MemoryBackendError("Redis memory returned invalid data") from exc

    session_receipt_version = 1

    async def inspect_message(self, scope, session_id, message_id):
        from .session_receipts import validate_inspection

        _inputs(scope, session_id)
        _text(message_id, "Message identity")
        response = await self._eval(
            _INSPECT, self._keys(scope, "session", session_id, "messages", "identities"), message_id
        )
        try:
            if not isinstance(response, list) or len(response) != 3:
                raise ValueError("Invalid Redis receipt")
            revision, sequence = _number(response[0]), _number(response[1])
            receipt = (
                {"revision": sequence, "message": _objects([response[2]])[0]} if sequence else None
            )
            if not sequence and response[2] not in ("", b""):
                raise ValueError("Invalid Redis missing receipt")
            return validate_inspection(
                {
                    "scope": asdict(scope),
                    "session_id": session_id,
                    "message_id": message_id,
                    "revision": revision,
                    "receipt": receipt,
                },
                scope,
                session_id,
                message_id,
            )
        except Exception as exc:
            raise MemoryBackendError("Redis memory returned invalid write evidence") from exc

    async def read(self, scope, session_id):
        _inputs(scope, session_id)
        response = await self._eval(_READ, self._keys(scope, "session", session_id, "messages"))
        try:
            revision = _number(response[0])
            rows = response[1]
            if len(response) != 2 or len(rows) != revision:
                raise ValueError("Invalid Redis session")
        except Exception as exc:
            raise MemoryBackendError("Redis memory returned invalid data") from exc
        return revision, _objects(rows)

    async def append(self, scope, session_id, message, *, expected_revision, message_id):
        _inputs(scope, session_id)
        _text(message_id, "Message identity")
        _integer(expected_revision, "Session expected revision", 0, 2**53 - 2)
        if not isinstance(message, dict):
            raise ValidationError("Session messages must be JSON objects")
        payload = _payload(message)
        response = await self._eval(
            _APPEND,
            self._keys(scope, "session", session_id, "messages", "identities", "generation"),
            str(expected_revision),
            message_id,
            payload,
            str(secrets.randbits(52) + 1),
        )
        if response == [0]:
            raise ValidationError("Session revision conflict")
        if response == [2]:
            raise IdempotencyConflict("Message identity conflict")
        status, revision = self._counts(response, 2)
        if status != 1 or revision < 1:
            raise MemoryBackendError("Redis memory returned invalid data")
        return revision

    async def facts(self, scope, namespace):
        _inputs(scope, namespace)
        rows = await self._eval(_FACTS, self._keys(scope, "facts", namespace, "values"))
        now = time.time()
        return sorted(
            (
                item
                for item in _facts(rows)
                if item["expires_at"] is None or item["expires_at"] > now
            ),
            key=lambda item: item["key"],
        )

    async def inspect_fact(self, scope, namespace, key):
        _inputs(scope, namespace)
        _text(key, "Fact key")
        rows = await self._eval(
            _VALIDATE_FACTS, self._keys(scope, "facts", namespace, "values"), key
        )
        if not isinstance(rows, list) or len(rows) != 1:
            raise MemoryBackendError("Redis fact inspection returned invalid data")
        return None if rows[0] is None else _facts(rows)[0]

    async def put_fact(self, scope, namespace, key, value, *, expected_version, expires_at=None):
        _inputs(scope, namespace)
        _text(key, "Fact key")
        _integer(expected_version, "Fact expected version", 0, 2**53 - 2)
        expires_at = _validate_expires_at(expires_at)
        version = expected_version + 1
        payload = _payload(
            {"key": key, "value": value, "version": version, "expires_at": expires_at}
        )
        response = await self._eval(
            _PUT_FACT,
            self._keys(scope, "facts", namespace, "values", "versions", "order", "generation"),
            key,
            str(expected_version),
            str(version),
            payload,
            str(secrets.randbits(52) + 1),
        )
        if response == [0]:
            raise ValidationError("Fact version conflict")
        status, stored_version = self._counts(response, 2)
        if status != 1 or stored_version != version:
            raise MemoryBackendError("Redis memory returned invalid data")
        return version

    async def read_page(self, scope, session_id, query):
        _inputs(scope, session_id)
        binding = _binding(self.backend_id, scope, "session", session_id, query)
        query.__post_init__()
        decoded = _decode_cursor(query.cursor, binding)
        before = ""
        if decoded is not None:
            previous, before = decoded
            # Validate cursor shape/counts before crossing the client boundary.
            if set(previous) != {"generation", "revision"}:
                raise ValidationError("Session recall snapshot is invalid")
            _integer(previous["generation"], "Session generation")
            _integer(previous["revision"], "Session revision", 0, 2**53 - 2)
            _session_cursor(query, binding, previous["generation"], previous["revision"])
        response = await self._eval(
            _SESSION_PAGE,
            self._keys(scope, "session", session_id, "messages", "generation"),
            str(before),
            str(query.scan_limit),
        )
        try:
            if not isinstance(response, list) or len(response) != 5:
                raise ValueError("Invalid Redis page")
            generation, revision, actual_before, start = self._counts(response[:4], 4)
            rows = response[4]
            if not isinstance(rows, list) or len(rows) > query.scan_limit:
                raise ValueError("Invalid Redis page")
        except Exception as exc:
            raise MemoryBackendError("Redis memory returned invalid data") from exc
        snapshot, before = _session_cursor(query, binding, generation, revision)
        if actual_before != before or len(rows) != before - 1 - start:
            raise MemoryBackendError("Redis memory returned invalid data")
        candidates = list(zip(range(before - 1, start, -1), reversed(_objects(rows)), strict=True))
        return _page(candidates, query, "session", binding, snapshot, has_more=start > 0)

    async def recall(self, scope, namespace, query):
        _inputs(scope, namespace)
        binding = _binding(self.backend_id, scope, "facts", namespace, query)
        query.__post_init__()
        decoded = _decode_cursor(query.cursor, binding)
        after = 0
        if decoded is not None:
            previous, after = decoded
            if set(previous) != {"generation"}:
                raise ValidationError("Fact recall snapshot is invalid")
            _integer(previous["generation"], "Fact generation")
        response = await self._eval(
            _FACT_PAGE,
            self._keys(scope, "facts", namespace, "values", "order", "generation"),
            str(after),
            str(query.scan_limit),
        )
        try:
            if not isinstance(response, list) or len(response) != 3:
                raise ValueError("Invalid Redis page")
            generation, count = self._counts(response[:2], 2)
            rows = response[2]
            if not isinstance(rows, list) or len(rows) > query.scan_limit:
                raise ValueError("Invalid Redis page")
        except Exception as exc:
            raise MemoryBackendError("Redis memory returned invalid data") from exc
        snapshot = {"generation": generation}
        if decoded is not None and (previous != snapshot or after > count):
            raise ValidationError("Fact recall snapshot is no longer available")
        if len(rows) != min(query.scan_limit, count - after):
            raise MemoryBackendError("Redis memory returned invalid data")
        candidates = list(enumerate(_facts(rows), start=after + 1))
        return _page(
            candidates, query, "facts", binding, snapshot, has_more=after + len(rows) < count
        )

    fact_scan_version = 1

    async def fact_snapshot(self, scope, namespace):
        from .fact_scan import _scan_snapshot

        _inputs(scope, namespace)
        response = await self._eval(
            _FACT_SCAN_HEADER,
            self._keys(scope, "facts", namespace, "scan-epoch", "generation"),
            secrets.token_hex(16),
        )
        if not isinstance(response, list) or len(response) != 2:
            raise MemoryBackendError("Redis fact snapshot returned invalid data")
        epoch = response[0].decode("ascii") if isinstance(response[0], bytes) else response[0]
        return canonical(_scan_snapshot(scope, namespace, epoch, _number(response[1])))

    async def scan_facts(self, scope, namespace, query):
        from .fact_scan import FactScanPage, _scan_binding, _scan_size, _scan_snapshot
        from .recall import _encode_cursor

        _inputs(scope, namespace)
        binding, query = _scan_binding(self.backend_id, scope, namespace, query)
        decoded = _decode_cursor(query.cursor, binding)
        previous, after = decoded if decoded is not None else (None, 0)
        if previous is not None and (
            not isinstance(previous, dict) or set(previous) != {"epoch", "generation", "address"}
        ):
            raise ValidationError("Invalid Redis fact scan snapshot")
        if previous is not None:
            if (
                _scan_snapshot(scope, namespace, previous["epoch"], previous["generation"])
                != previous
            ):
                raise ValidationError("Invalid Redis fact scan address")
        response = await self._eval(
            _FACT_SCAN,
            self._keys(scope, "facts", namespace, "values", "order", "generation", "scan-epoch"),
            secrets.token_hex(16),
            "" if previous is None else previous["epoch"],
            "" if previous is None else str(previous["generation"]),
            str(after),
            str(query.limit),
            str(query.max_bytes),
        )
        if response == [0]:
            raise ValidationError("Fact scan snapshot or position is no longer current")
        if response == [2]:
            raise BudgetExceeded("Fact record does not fit scan byte budget")
        if not isinstance(response, list) or len(response) != 7 or response[0] != 1:
            raise MemoryBackendError("Redis fact scan returned invalid data")
        epoch = response[1].decode("ascii") if isinstance(response[1], bytes) else response[1]
        generation, count, position, used = self._counts(response[2:6], 4)
        snapshot = _scan_snapshot(scope, namespace, epoch, generation)
        items = _facts(response[6])
        if (
            position < after
            or position > count
            or position - after != len(items)
            or len(items) > query.limit
            or _scan_size(items) != used
            or used > query.max_bytes
            or (previous is not None and previous != snapshot)
            or (not items and position < count)
        ):
            raise MemoryBackendError("Redis fact scan exceeded its declared bounds")
        cursor = _encode_cursor(binding, snapshot, position) if position < count else None
        return FactScanPage(items, cursor, used, len(items), canonical(snapshot), True)

    async def validate_facts(self, scope, namespace, items):
        _inputs(scope, namespace)
        references = _fact_inputs(scope, namespace, items)
        _integer(len(references), "Fact reference count", 0, 10_000)
        for reference in references:
            _text(reference["key"], "Fact reference key")
        if not references:
            return None
        rows = await self._eval(
            _VALIDATE_FACTS,
            self._keys(scope, "facts", namespace, "values"),
            *(item["key"] for item in references),
        )
        if not isinstance(rows, list) or len(rows) != len(references):
            raise MemoryBackendError("Redis memory returned invalid data")
        now = time.time()
        for reference, row in zip(references, rows, strict=True):
            if row is None:
                raise ValidationError("Fact reference is no longer current")
            actual = _facts([row])[0]
            if actual["key"] != reference["key"] or canonical(actual["value"]) != canonical(
                reference["value"]
            ):
                raise ValidationError("Fact reference is no longer current")
            _current_fact(reference, actual["version"], actual["expires_at"], now)
        return None

    async def aclose(self):
        """Close owned clients exactly once; borrowed clients remain caller-owned."""
        async with self._close_lock:
            if self._closed:
                return
            if self._owns_client:
                try:
                    await self._client.aclose()
                except Exception as exc:
                    raise MemoryBackendError("Redis memory close failed") from exc
            self._closed = True
