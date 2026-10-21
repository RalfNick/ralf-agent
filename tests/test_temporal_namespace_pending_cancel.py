"""An undelivered entry cancellation is not a retryable RPC failure."""

import asyncio
from types import SimpleNamespace as NS

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_session_activities import namespace_id
from tests.test_temporal_namespace_cancellation import client_with, suppressed_prior_cancel

pytest.importorskip("temporalio")
from temporalio.service import RPCError, RPCStatusCode  # noqa: E402


@pytest.mark.parametrize("prior_cancel", [False, True])
def test_undelivered_entry_cancel_never_starts_or_retries_a_namespace_rpc(prior_cancel):
    async def scenario():
        await suppressed_prior_cancel(prior_cancel)
        calls = []

        async def describe(request):
            calls.append(request.namespace)
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise RPCError("operation was canceled", RPCStatusCode.CANCELLED, b"") from None
            return NS(namespace_info=NS(id="original-uuid"))

        task = asyncio.current_task()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await namespace_id(client_with(describe))
        assert calls == [] and task.cancelling() == 1 + prior_cancel

    asyncio.run(scenario())


def test_already_delivered_old_cancel_does_not_disable_transport_read_recovery():
    async def scenario():
        await suppressed_prior_cancel(True)
        calls = []

        async def describe(request):
            calls.append(request.namespace)
            if len(calls) == 1:
                raise RPCError("operation was canceled", RPCStatusCode.CANCELLED, b"")
            return NS(namespace_info=NS(id="original-uuid"))

        assert await namespace_id(client_with(describe)) == "original-uuid"
        assert calls == ["original", "original"] and asyncio.current_task().cancelling() == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["namespace", "service", "port", "body"])
def test_entry_cancel_checkpoint_keeps_original_read_pins(monkeypatch, fault):
    async def scenario():
        await suppressed_prior_cancel(True)

        class Service:
            def __init__(self):
                self.calls = []

            async def describe_namespace(self, request):
                self.calls.append(request.namespace)
                return NS(namespace_info=NS(id="original-uuid"))

        service = Service()
        client = NS(namespace="original", workflow_service=service)

        async def foreign(request):
            raise AssertionError("foreign port must not be called")

        def drift():
            if fault == "namespace":
                client.namespace = "other"
            elif fault == "service":
                client.workflow_service = NS(describe_namespace=foreign)
            elif fault == "port":
                service.describe_namespace = foreign
            else:

                async def changed(self, request):
                    raise AssertionError("changed source must not be called")

                monkeypatch.setattr(Service.describe_namespace, "__code__", changed.__code__)

        asyncio.get_running_loop().call_soon(drift)
        with pytest.raises(DefinitionMismatch):
            await namespace_id(client)
        assert service.calls == []

    asyncio.run(scenario())
