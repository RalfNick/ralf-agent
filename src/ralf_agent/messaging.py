"""Bounded scoped message handoff, independent of execution authority.

Entries and identities are retained; reaching capacity rejects new messages.
Neither implementation silently trims pending or acknowledged data. Deployments
must choose archival/retention outside this port after accounting for all groups.
"""

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Protocol

from .errors import IdempotencyConflict, RalfError, ValidationError
from .types import Scope, canonical, digest

MAX_MESSAGE_BYTES = 262144


class MessageBusError(RalfError):
    code = "message_bus_error"


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValidationError(f"{label} must be nonempty text of at most 512 characters")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValidationError(f"{label} requires valid Unicode") from exc


def _integer(value, label, minimum=1, maximum=1000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"{label} is outside its integer limit")


def _json(value):
    try:
        encoded = canonical(value)
        if len(encoded.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ValidationError("Message JSON exceeds its byte limit")
        return encoded
    except (UnicodeError, RecursionError) as exc:
        raise ValidationError("Message requires bounded finite Unicode JSON") from exc


def _inputs(scope, topic, group=None, consumer=None):
    if not isinstance(scope, Scope):
        raise ValidationError("Message handoff requires a trusted Scope")
    _text(scope.workspace, "Workspace")
    _text(scope.principal, "Principal")
    _text(topic, "Topic")
    if group is not None:
        _text(group, "Group")
    if consumer is not None:
        _text(consumer, "Consumer")


def _binding(scope, topic, group):
    return digest({"scope": asdict(scope), "topic": topic, "group": group})


@dataclass(frozen=True, init=False)
class MessageEnvelope:
    message_id: str
    topic: str
    _payload_json: str = field(repr=False)

    def __init__(self, message_id, topic, payload):
        _text(message_id, "Message identity")
        _text(topic, "Topic")
        if not isinstance(payload, dict):
            raise ValidationError("Message payload must be a JSON object")
        object.__setattr__(self, "message_id", message_id)
        object.__setattr__(self, "topic", topic)
        object.__setattr__(self, "_payload_json", _json(payload))
        _json(self.to_dict())

    @property
    def payload(self):
        return json.loads(self._payload_json)

    def to_dict(self):
        return {"message_id": self.message_id, "topic": self.topic, "payload": self.payload}


@dataclass(frozen=True)
class Delivery:
    broker_id: str
    message: MessageEnvelope
    consumer: str
    binding: str = field(repr=False)


def _delivery(scope, topic, group, delivery):
    _inputs(scope, topic, group)
    if not isinstance(delivery, Delivery) or delivery.binding != _binding(scope, topic, group):
        raise ValidationError("Delivery does not belong to this scoped group")
    _text(delivery.broker_id, "Broker identity")
    _text(delivery.consumer, "Consumer")
    if not isinstance(delivery.message, MessageEnvelope) or delivery.message.topic != topic:
        raise ValidationError("Delivery topic mismatch")


class MessageBus(Protocol):
    async def ensure_group(self, scope: Scope, topic: str, group: str): ...
    async def publish(self, scope: Scope, message: MessageEnvelope) -> str: ...
    async def receive(
        self, scope: Scope, topic: str, group: str, consumer: str, *, limit=1
    ) -> list[Delivery]: ...
    async def claim(
        self, scope: Scope, topic: str, group: str, consumer: str, *, min_idle_ms, limit=1
    ) -> list[Delivery]: ...
    async def ack(self, scope: Scope, topic: str, group: str, delivery: Delivery) -> int: ...
    async def aclose(self): ...


class InMemoryMessageBus:
    """Default non-durable bus with group cursors and explicit pending claims."""

    def __init__(self, *, max_entries=10000):
        _integer(max_entries, "Message capacity", 1, 1000000)
        self.max_entries = max_entries
        self._streams = {}
        self._groups = {}
        self._closed = False
        self._lock = asyncio.Lock()

    def _open(self):
        if self._closed:
            raise MessageBusError("Message bus is closed")

    async def ensure_group(self, scope, topic, group):
        _inputs(scope, topic, group)
        async with self._lock:
            self._open()
            self._groups.setdefault((scope, topic, group), {"cursor": 0, "pending": {}})

    async def publish(self, scope, message):
        if not isinstance(message, MessageEnvelope):
            raise ValidationError("Publish requires a MessageEnvelope")
        _inputs(scope, message.topic)
        async with self._lock:
            self._open()
            entries = self._streams.setdefault((scope, message.topic), [])
            previous = next(
                (item for item in entries if item.message.message_id == message.message_id), None
            )
            if previous is not None:
                if previous.message != message:
                    raise IdempotencyConflict("Message identity conflict")
                return previous.broker_id
            if len(entries) >= self.max_entries:
                raise MessageBusError("Message capacity reached; archive before publishing")
            identity = f"{len(entries) + 1}-0"
            entries.append(Delivery(identity, message, "", ""))
            return identity

    def _group(self, scope, topic, group):
        self._open()
        try:
            return self._groups[(scope, topic, group)]
        except KeyError as exc:
            raise MessageBusError("Message group has not been created") from exc

    async def receive(self, scope, topic, group, consumer, *, limit=1):
        _inputs(scope, topic, group, consumer)
        _integer(limit, "Receive limit")
        async with self._lock:
            state = self._group(scope, topic, group)
            entries = self._streams.get((scope, topic), [])[
                state["cursor"] : state["cursor"] + limit
            ]
            result = [
                Delivery(item.broker_id, item.message, consumer, _binding(scope, topic, group))
                for item in entries
            ]
            state["cursor"] += len(result)
            for item in result:
                state["pending"][item.broker_id] = (item, time.monotonic())
            return result

    async def claim(self, scope, topic, group, consumer, *, min_idle_ms, limit=1):
        _inputs(scope, topic, group, consumer)
        _integer(limit, "Claim limit")
        _integer(min_idle_ms, "Minimum idle time", 0, 2**31 - 1)
        async with self._lock:
            state = self._group(scope, topic, group)
            now = time.monotonic()
            result = []
            for identity, (previous, started) in tuple(state["pending"].items()):
                if (now - started) * 1000 >= min_idle_ms and len(result) < limit:
                    item = Delivery(identity, previous.message, consumer, previous.binding)
                    state["pending"][identity] = (item, now)
                    result.append(item)
            return result

    async def ack(self, scope, topic, group, delivery):
        _delivery(scope, topic, group, delivery)
        async with self._lock:
            state = self._group(scope, topic, group)
            pending = state["pending"].get(delivery.broker_id)
            if pending is None or pending[0] != delivery:
                return 0
            del state["pending"][delivery.broker_id]
            return 1

    async def aclose(self):
        async with self._lock:
            self._closed = True
