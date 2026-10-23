"""Native 0.144.4 quota updates are observations, never authentication or policy."""

import asyncio
import copy
import sys

import pytest

from relf_agent.codex_auth_transport import CodexAuthenticatedTransport
from tests.test_codex_auth_transport import CANARY, assert_secret_absent, peer


def update():
    return {
        "method": "account/rateLimits/updated",
        "params": {
            "rateLimits": {
                "limitId": None,
                "limitName": None,
                "primary": None,
                "secondary": None,
                "credits": None,
                "individualLimit": None,
                "planType": None,
                "rateLimitReachedType": None,
            }
        },
    }


def transport():
    rpc = CodexAuthenticatedTransport((sys.executable,), env={})
    rpc._authenticated = True
    rpc._coding_business = True
    return rpc


def test_actual_sparse_quota_update_is_discarded_before_business_inbox():
    rpc = transport()
    rpc._route(update())
    assert list(rpc._events) == []


def test_exact_typed_native_quota_variants_remain_discard_only():
    rpc = transport()
    message = update()
    message["params"]["rateLimits"].update(
        limitId="codex",
        limitName="Codex",
        primary={"usedPercent": 25, "windowDurationMins": 15, "resetsAt": 123},
        secondary={"usedPercent": 50, "windowDurationMins": None, "resetsAt": None},
        credits={"hasCredits": True, "unlimited": False, "balance": "1.50"},
        individualLimit={"limit": "100", "used": "50", "remainingPercent": 50, "resetsAt": 123},
        planType="plus",
        rateLimitReachedType="rate_limit_reached",
    )
    rpc._route(message)
    assert list(rpc._events) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("limitId", "x" * 257),
        ("limitName", "bad\n"),
        ("primary", {"usedPercent": 1}),
        ("secondary", {"usedPercent": 2**31, "windowDurationMins": None, "resetsAt": None}),
        ("primary", {"usedPercent": 1, "windowDurationMins": 2**63, "resetsAt": None}),
        ("credits", {"hasCredits": 1, "unlimited": False, "balance": None}),
        ("credits", {"hasCredits": True, "unlimited": False, "balance": False}),
        ("individualLimit", {"limit": "1", "used": "1", "remainingPercent": 0, "resetsAt": True}),
        ("planType", "new-unreviewed-plan"),
        ("planType", []),
        ("rateLimitReachedType", {}),
    ],
)
def test_invalid_typed_quota_variants_are_not_admitted(field, value):
    rpc = transport()
    message = update()
    message["params"]["rateLimits"][field] = value
    with pytest.raises(ValueError):
        rpc._route(message)
    assert list(rpc._events) == []


def test_native_quota_does_not_prevent_correlated_business_reply(tmp_path):
    rpc, _ = peer(
        tmp_path,
        extra="request=read()\nassert request['method']=='thread/start'\n"
        + f"send({update()!r})\n"
        + "send({'id':request['id'],'result':{'accepted':True}})\n",
    )

    async def run():
        await rpc.start()
        try:
            await rpc.authenticate_api_key(CANARY)
            assert await rpc.request("thread/start", {}) == {"accepted": True}
            assert_secret_absent(rpc)
        finally:
            await rpc.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    ["id", "extra", "missing", "echo", "bool", "before_business", "before_auth", "overflow"],
)
def test_unreviewed_quota_shapes_and_phases_are_rejected(change):
    rpc = transport()
    message = copy.deepcopy(update())
    snapshot = message["params"]["rateLimits"]
    if change == "id":
        message["id"] = 7
    elif change == "extra":
        message["params"]["extra"] = CANARY
    elif change == "missing":
        del snapshot["primary"]
    elif change == "echo":
        snapshot["apiKey"] = CANARY
    elif change == "bool":
        snapshot["primary"] = {"usedPercent": True, "windowDurationMins": None, "resetsAt": None}
    elif change == "before_business":
        rpc._coding_business = False
    elif change == "before_auth":
        rpc._authenticated = False
    else:
        rpc._quota_notifications = rpc._max_events
    with pytest.raises(ValueError):
        rpc._route(message)
    assert_secret_absent(rpc)
