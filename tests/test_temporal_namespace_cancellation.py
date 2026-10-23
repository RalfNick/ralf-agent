"""Namespace observations preserve caller cancellation across the SDK bridge."""

import asyncio
from types import SimpleNamespace

import pytest

from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_session_activities import namespace_id

pytest.importorskip("temporalio")
from temporalio.service import RPCError, RPCStatusCode  # noqa: E402


def client_with(operation):
    return SimpleNamespace(
        namespace="original", workflow_service=SimpleNamespace(describe_namespace=operation)
    )


async def suppressed_prior_cancel(enabled):
    if enabled:
        asyncio.current_task().cancel()
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass


@pytest.mark.parametrize("prior_cancel", [False, True])
def test_namespace_wait_deadline_survives_sdk_cancellation_conversion(prior_cancel):
    async def scenario():
        await suppressed_prior_cancel(prior_cancel)
        task = asyncio.current_task()
        previous = task.cancelling()

        async def describe(request):
            assert request.namespace == "original"
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                # The observed SDK bridge can surface cancellation as RPCError.
                raise RPCError("operation was canceled", RPCStatusCode.CANCELLED, b"") from None

        deadline = asyncio.timeout(0)
        with pytest.raises(TimeoutError):
            async with deadline:
                await namespace_id(client_with(describe))
        assert deadline.expired() and task.cancelling() == previous

    asyncio.run(scenario())


@pytest.mark.parametrize("prior_cancel", [False, True])
def test_namespace_explicit_waiter_cancel_is_not_a_business_rpc_error(prior_cancel):
    async def scenario():
        entered = asyncio.Event()

        async def describe(request):
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                raise RPCError("operation was canceled", RPCStatusCode.CANCELLED, b"") from None

        async def observe():
            await suppressed_prior_cancel(prior_cancel)
            return await namespace_id(client_with(describe))

        pending = asyncio.create_task(observe())
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert pending.cancelled() and pending.cancelling() == 1 + prior_cancel

    asyncio.run(scenario())


@pytest.mark.parametrize("prior_cancel", [False, True])
@pytest.mark.parametrize(
    "status", [RPCStatusCode.CANCELLED, RPCStatusCode.NOT_FOUND, RPCStatusCode.DEADLINE_EXCEEDED]
)
def test_namespace_rpc_error_without_new_caller_cancel_is_unchanged(status, prior_cancel):
    async def scenario():
        await suppressed_prior_cancel(prior_cancel)
        task = asyncio.current_task()
        previous = task.cancelling()
        error = RPCError("original transport failure", status, b"original-details")

        async def describe(request):
            raise error

        with pytest.raises(RPCError) as caught:
            await namespace_id(client_with(describe))
        assert caught.value is error and task.cancelling() == previous

    asyncio.run(scenario())


@pytest.mark.parametrize("identity", ["namespace-uuid", ""])
def test_namespace_success_and_missing_uuid_contract_remain(identity):
    async def scenario():
        async def describe(request):
            return SimpleNamespace(namespace_info=SimpleNamespace(id=identity))

        if identity:
            assert await namespace_id(client_with(describe)) == identity
        else:
            with pytest.raises(DefinitionMismatch):
                await namespace_id(client_with(describe))

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [RPCStatusCode.NOT_FOUND, RPCStatusCode.DEADLINE_EXCEEDED])
def test_new_waiter_cancel_does_not_reclassify_another_rpc_status(status):
    async def scenario():
        entered = asyncio.Event()
        error = RPCError("other transport failure", status, b"original-details")

        async def describe(request):
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                raise error from None

        pending = asyncio.create_task(namespace_id(client_with(describe)))
        await entered.wait()
        pending.cancel()
        with pytest.raises(RPCError) as caught:
            await pending
        assert caught.value is error and pending.cancelling() == 1

    asyncio.run(scenario())
