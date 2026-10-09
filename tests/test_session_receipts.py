import asyncio
import importlib
from dataclasses import asdict

import pytest

from ralf_agent import Scope, SessionBindingResource
from ralf_agent.errors import ValidationError

from .remote_session_fixture import RemoteMemory


def api():
    return importlib.import_module("ralf_agent.session_receipts")


def test_remote_session_view_inspects_exact_message_without_full_history(tmp_path):
    async def scenario():
        backend = RemoteMemory(tmp_path / "data.sqlite")
        try:
            view = SessionBindingResource(
                backend, namespaces=("red",), default_namespace="red"
            ).select({}, Scope())
            assert api().supports_remote_session(backend)
            missing = await view.inspect_message(Scope(), "s", "m")
            assert missing == {
                "scope": asdict(Scope()),
                "session_id": 'ralf-session-v1:["red","s"]',
                "message_id": "m",
                "revision": 0,
                "receipt": None,
            }
            message = {"role": "assistant", "content": "answer"}
            await view.append(Scope(), "s", message, expected_revision=0, message_id="m")
            receipt = await view.inspect_message(Scope(), "s", "m")
            assert receipt["revision"] == 1 and receipt["receipt"] == {
                "revision": 1,
                "message": message,
            }
            assert (
                api().validate_inspection(receipt, Scope(), 'ralf-session-v1:["red","s"]', "m")
                == receipt
            )
            assert backend.read_calls == 0
        finally:
            backend.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        {"scope": {"workspace": "other", "principal": "local-owner"}},
        {"session_id": "other"},
        {"message_id": "other"},
        {"revision": True},
        {"revision": -1},
        {"revision": float("nan")},
        {"extra": "field"},
        {"receipt": {"revision": 2, "message": {}}},
        {"receipt": {"revision": 0, "message": {}}},
        {"receipt": {"revision": True, "message": {}}},
        {"receipt": {"revision": 1, "message": []}},
        {"receipt": {"revision": 1, "message": {"value": float("nan")}}},
    ],
)
def test_invalid_scoped_receipt_cannot_be_adopted(change):
    receipt = {
        "scope": asdict(Scope()),
        "session_id": "s",
        "message_id": "m",
        "revision": 1,
        "receipt": {"revision": 1, "message": {"content": "answer"}},
    }
    with pytest.raises(ValidationError):
        api().validate_inspection({**receipt, **change}, Scope(), "s", "m")


def test_remote_receipt_protocol_is_explicit_and_completed():
    class Wrong:
        session_receipt_version = True

        async def inspect_message(self, *args):
            return {}

    assert not api().supports_remote_session(Wrong())

    async def lazy():
        raise AssertionError("must never enter lazy receipt")

    with pytest.raises(ValidationError):
        api().validate_inspection(lazy(), Scope(), "s", "m")
