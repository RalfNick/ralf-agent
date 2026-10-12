"""Unsupported inherited options must fail before dispatch, never be ignored."""

import pytest

from ralf_agent import OpenAIResponsesReasoningProvider
from ralf_agent.errors import ValidationError


@pytest.mark.parametrize("field,value", [("temperature", 0.5), ("top_p", 0.9), ("stop", ["stop"])])
def test_mutated_unsupported_option_rejects_before_request(field, value):
    provider = OpenAIResponsesReasoningProvider("fixture", api_key="fixture")
    setattr(provider, field, value)
    with pytest.raises(ValidationError):
        provider.validate_request([{"role": "user", "content": "task"}], [])


@pytest.mark.parametrize("stream", [False, True], ids=["json", "sse"])
def test_optional_output_logprobs_null_is_preserved(stream):
    import asyncio

    import httpx

    from .test_responses_provider import frames
    from .test_responses_reasoning import assistant, completed, message

    async def run():
        native = message("done", phase="final_answer")
        native["content"][0]["logprobs"] = None
        snapshot = completed([native])
        wire = frames([{"type": "response.completed", "response": snapshot}])

        def reply(request):
            if stream:
                return httpx.Response(200, stream=wire)
            return httpx.Response(200, json=snapshot)

        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            provider = OpenAIResponsesReasoningProvider(
                "fixture", api_key="fixture", client=client, stream=stream
            )
            result = await provider.complete([{"role": "user", "content": "task"}], [])
            assert result.output == "done"
            assert result.continuation.data["output"] == [native]
            _, body, _, _ = provider._prepared([assistant(result)], [])
            assert body["input"] == [native]
        if stream:
            assert wire.closed

    asyncio.run(run())
