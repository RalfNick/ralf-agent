"""Pure progress bursts cannot displace authoritative native terminal evidence."""

import asyncio

import pytest

from tests.test_codex_auth_transport import CANARY, peer
from tests.test_codex_quota_notifications import transport


def progress(method="item/reasoning/textDelta"):
    params = {"threadId": "thread", "turnId": "turn", "itemId": "item", "delta": "text"}
    if method == "item/reasoning/textDelta":
        params["contentIndex"] = 0
    elif method == "item/reasoning/summaryTextDelta":
        params["summaryIndex"] = 0
    return {"method": method, "params": params}


@pytest.mark.parametrize(
    "method",
    [
        "item/reasoning/textDelta",
        "item/reasoning/summaryTextDelta",
        "item/agentMessage/delta",
        "item/commandExecution/outputDelta",
    ],
)
def test_valid_progress_burst_is_discarded_without_occupying_terminal_inbox(method):
    rpc = transport()
    for _ in range(2000):
        rpc._route(progress(method))
    terminal = {
        "method": "turn/completed",
        "params": {"threadId": "thread", "turn": {"id": "turn"}},
    }
    rpc._route(terminal)
    assert list(rpc._events) == [terminal]


def test_real_stdio_burst_preserves_business_reply_and_terminal(tmp_path):
    terminal = {
        "method": "turn/completed",
        "params": {"threadId": "thread", "turn": {"id": "turn"}},
    }
    rpc, _ = peer(
        tmp_path,
        extra="request=read()\nassert request['method']=='thread/start'\n"
        + f"for _ in range(2000):send({progress()!r})\n"
        + f"send({terminal!r})\n"
        + "send({'id':request['id'],'result':{'accepted':True}})\n",
    )

    async def run():
        await rpc.start()
        try:
            await rpc.authenticate_api_key(CANARY)
            assert await rpc.request("thread/start", {}) == {"accepted": True}
            assert await rpc.next_event() == terminal
            assert not rpc._events
        finally:
            await rpc.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    ["id", "extra", "index", "missing", "locators", "before_business", "before_auth", "overflow"],
)
def test_invalid_progress_is_rejected_instead_of_silently_discarded(change):
    rpc = transport()
    message = progress()
    if change == "id":
        message["id"] = 1
    elif change == "extra":
        message["params"]["extra"] = CANARY
    elif change == "index":
        message["params"]["contentIndex"] = True
    elif change == "missing":
        del message["params"]["delta"]
    elif change == "locators":
        message["params"]["threadId"] = ""
    elif change == "before_business":
        rpc._coding_business = False
    elif change == "before_auth":
        rpc._authenticated = False
    else:
        rpc._progress_notifications = 16384
    with pytest.raises(ValueError):
        rpc._route(message)
    assert not rpc._events
