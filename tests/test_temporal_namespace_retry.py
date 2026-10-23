"""A cancelled namespace read may repeat once; identity and caller still win."""

import asyncio
from types import SimpleNamespace as NS

import pytest

from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_session_activities import namespace_id

pytest.importorskip("temporalio")
from temporalio.service import RPCError, RPCStatusCode  # noqa: E402


def test_transport_cancel_repeats_only_the_same_read_once():
    async def scenario():
        calls = []

        async def describe(request):
            calls.append(request.namespace)
            if len(calls) == 1:
                raise RPCError("operation was canceled", RPCStatusCode.CANCELLED, b"")
            return NS(namespace_info=NS(id="original-uuid"))

        client = NS(namespace="original", workflow_service=NS(describe_namespace=describe))
        assert await namespace_id(client) == "original-uuid"
        assert calls == ["original", "original"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status",
    [
        RPCStatusCode.CANCELLED,
        RPCStatusCode.NOT_FOUND,
        RPCStatusCode.DEADLINE_EXCEEDED,
        RPCStatusCode.UNAVAILABLE,
    ],
)
def test_read_retry_is_bounded_and_other_failures_are_not_retried(status):
    async def scenario():
        calls = []
        failures = [RPCError("original", status, b"first"), RPCError("last", status, b"last")]

        async def describe(request):
            calls.append(request.namespace)
            raise failures[len(calls) - 1]

        client = NS(namespace="original", workflow_service=NS(describe_namespace=describe))
        expected = 2 if status == RPCStatusCode.CANCELLED else 1
        with pytest.raises(RPCError) as caught:
            await namespace_id(client)
        assert len(calls) == expected and caught.value is failures[expected - 1]

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["namespace", "service", "port", "body"])
@pytest.mark.parametrize("successful_second", [False, True])
def test_drift_at_read_boundaries_cannot_retarget_or_confirm_the_retry(
    monkeypatch, fault, successful_second
):
    async def scenario():
        calls = []

        async def foreign(request):
            raise AssertionError("changed namespace port must not be called")

        class Service:
            async def describe_namespace(self, request):
                self.calls.append(request.namespace)
                if self.successful_second and len(self.calls) == 1:
                    raise RPCError("operation was canceled", RPCStatusCode.CANCELLED, b"")
                if self.fault == "namespace":
                    self.client.namespace = "other"
                elif self.fault == "service":
                    self.client.workflow_service = NS(describe_namespace=self.foreign)
                elif self.fault == "port":
                    self.describe_namespace = self.foreign
                else:

                    async def changed(self, request):
                        raise AssertionError("changed source must not be called")

                    self.patch.setattr(type(self).describe_namespace, "__code__", changed.__code__)
                if self.successful_second:
                    return NS(namespace_info=NS(id="original-uuid"))
                raise RPCError("operation was canceled", RPCStatusCode.CANCELLED, b"")

        service = Service()
        client = NS(namespace="original", workflow_service=service)
        service.client, service.fault = client, fault
        service.calls, service.foreign, service.patch = calls, foreign, monkeypatch
        service.successful_second = successful_second
        with pytest.raises(DefinitionMismatch):
            await namespace_id(client)
        assert calls == ["original"] * (2 if successful_second else 1)

    asyncio.run(scenario())


def test_cancel_between_read_attempts_does_not_start_another_rpc():
    async def scenario():
        calls = []

        async def describe(request):
            calls.append(request.namespace)
            asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
            raise RPCError("operation was canceled", RPCStatusCode.CANCELLED, b"")

        client = NS(namespace="original", workflow_service=NS(describe_namespace=describe))
        with pytest.raises(asyncio.CancelledError):
            await namespace_id(client)
        assert calls == ["original"]

    asyncio.run(scenario())


def test_request_construction_error_is_not_retried_as_a_transport_cancel(monkeypatch):
    async def scenario():
        from temporalio.api.workflowservice import v1

        constructed = []
        error = RPCError("local construction failed", RPCStatusCode.CANCELLED, b"")

        def construct(**kwargs):
            constructed.append(kwargs)
            raise error

        async def describe(request):
            raise AssertionError("no RPC for an unconstructed request")

        monkeypatch.setattr(v1, "DescribeNamespaceRequest", construct)
        client = NS(namespace="original", workflow_service=NS(describe_namespace=describe))
        with pytest.raises(RPCError) as caught:
            await namespace_id(client)
        assert caught.value is error and constructed == [{"namespace": "original"}]

    asyncio.run(scenario())
