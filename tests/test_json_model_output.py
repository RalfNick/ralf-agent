import asyncio
import json

import httpx
import pytest

from relf_agent.errors import ProviderError, ValidationError
from relf_agent.providers import DeepSeekChatProvider, OpenAIChatProvider


@pytest.mark.parametrize("provider_type", [OpenAIChatProvider, DeepSeekChatProvider])
def test_explicit_json_mode_pins_release_and_sends_native_response_format(provider_type):
    async def run():
        requests = []

        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": '{"status":"needs_input"}'},
                            "finish_reason": "stop",
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            default = provider_type("model", api_key="fixture", client=client)
            provider = provider_type("model", api_key="fixture", json_mode=True, client=client)
            assert "json_mode" not in default.identity
            assert provider.identity["json_mode"] is True
            result = await provider.complete([{"role": "user", "content": "Return JSON"}], [])
            assert json.loads(result.output)["status"] == "needs_input"
            assert requests[0]["response_format"] == {"type": "json_object"}

    asyncio.run(run())


def test_json_mode_rejects_prose_and_invalid_configuration():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, json={"choices": [{"message": {"content": 'Prose {"ok":true}'}}]}
                )
            )
        ) as client:
            provider = DeepSeekChatProvider(
                "model", api_key="fixture", json_mode=True, client=client
            )
            with pytest.raises(ProviderError):
                await provider.complete([{"role": "user", "content": "Return JSON"}], [])
            with pytest.raises(ValidationError):
                provider.validate_request([{"role": "user", "content": "Say hello"}], [])
        for value in (1, "true", None):
            with pytest.raises(ValidationError):
                OpenAIChatProvider("model", api_key="fixture", json_mode=value)

    asyncio.run(run())
