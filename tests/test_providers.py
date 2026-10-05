import asyncio
import json

import httpx
import pytest

from ralf_agent.errors import ProviderError, ValidationError
from ralf_agent.providers import OpenAIChatProvider


def test_chat_provider_normalizes_tools_usage_and_sends_no_hidden_retries():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": '{"id":1}'},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = OpenAIChatProvider(
                "test-model", api_key="secret", base_url="https://example.test/v1", client=client
            )
            result = await provider.complete([{"role": "user", "content": "look up"}], [])
            assert result.tool_calls[0].arguments == {"id": 1}
            assert result.tool_calls[0].call_id == "call-1"
            assert result.usage == {"input_tokens": 12, "output_tokens": 4}
            assert "secret" not in json.dumps(provider.identity)

    asyncio.run(exercise())
    assert len(requests) == 1
    assert requests[0]["model"] == "test-model"


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"id": "x", "function": {"name": "x", "arguments": "not JSON"}}
                        ]
                    }
                }
            ]
        },
    ],
)
def test_invalid_provider_responses_fail_before_tools_can_run(body):
    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
        ) as client:
            provider = OpenAIChatProvider("test", api_key="secret", client=client)
            with pytest.raises(ProviderError):
                await provider.complete([], [])

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "choice",
    [
        {"message": {}},
        {"message": {"content": None, "refusal": "Cannot comply"}},
        {"message": {"content": "partial"}, "finish_reason": "length"},
        {"message": {"tool_calls": [{"id": 1, "function": {"name": "x", "arguments": "{}"}}]}},
    ],
)
def test_empty_refused_incomplete_or_invalid_calls_do_not_become_success(choice):
    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"choices": [choice]})
            )
        ) as client:
            provider = OpenAIChatProvider("test", api_key="secret", client=client)
            with pytest.raises(ProviderError):
                await provider.complete([], [])

    asyncio.run(exercise())


def test_provider_failure_does_not_leak_upstream_error_or_key():
    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(401, text="key=secret"))
        ) as client:
            provider = OpenAIChatProvider("test", api_key="secret", client=client)
            with pytest.raises(ProviderError) as error:
                await provider.complete([], [])
            assert "secret" not in str(error.value)

    asyncio.run(exercise())


def test_provider_identity_tracks_actual_public_configuration_and_is_a_snapshot():
    requests = []

    def respond(request):
        requests.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = OpenAIChatProvider("approved", api_key="dummy", client=client)
            original = provider.identity
            provider.model = "replacement"
            provider.base_url = "https://replacement.test/v1"
            provider.max_output_tokens = 2048
            provider.token_parameter = "max_tokens"
            provider.timeout = 15
            current = provider.identity
            assert current != original
            assert current["model"] == "replacement"
            assert current["base_url"] == "https://replacement.test/v1"
            assert current["max_output_tokens"] == 2048
            assert current["token_parameter"] == "max_tokens"
            assert current["timeout"] == 15
            current["model"] = "identity-mutation"
            assert provider.identity["model"] == "replacement"
            await provider.complete([], [])

    asyncio.run(exercise())
    assert requests == [
        (
            "https://replacement.test/v1/chat/completions",
            {"model": "replacement", "messages": [], "max_tokens": 2048},
        )
    ]


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("model", ""),
        ("base_url", "https://user:password@replacement.test/v1"),
        ("max_output_tokens", True),
        ("token_parameter", "other"),
        ("timeout", -1),
    ],
)
def test_mutated_invalid_configuration_is_rejected_before_request(attribute, value):
    requests = []

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200, json={})
            )
        ) as client:
            provider = OpenAIChatProvider("test", api_key="dummy", client=client)
            setattr(provider, attribute, value)
            with pytest.raises(ValidationError):
                await provider.complete([], [])

    asyncio.run(exercise())
    assert requests == []
