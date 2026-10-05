import asyncio
import json

import httpx
import pytest

from ralf_agent.errors import ProviderError
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
