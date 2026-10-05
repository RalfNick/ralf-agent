"""One-shot model calls; providers do not execute tools or retry business calls."""

import json
import os
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from .errors import ProviderError, ValidationError
from .types import ModelResponse, ToolCall


class ModelProvider(Protocol):
    identity: dict

    async def complete(self, messages: list[dict], tools: list[dict]) -> ModelResponse: ...


class OpenAIChatProvider:
    def __init__(
        self,
        model,
        *,
        api_key=None,
        base_url="https://api.openai.com/v1",
        max_output_tokens=1024,
        token_parameter="max_completion_tokens",
        timeout=60,
        client=None,
    ):
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.netloc
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValidationError("Base URL must be HTTP(S) without embedded credentials or query")
        if (
            token_parameter not in {"max_tokens", "max_completion_tokens"}
            or type(max_output_tokens) is not int
            or max_output_tokens < 1
        ):
            raise ValidationError("Invalid output token configuration")
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValidationError("Provide api_key or set OPENAI_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.max_output_tokens = max_output_tokens
        self.token_parameter = token_parameter
        self.timeout = timeout
        self.client = client
        self.identity = {
            "kind": "openai-chat-completions",
            "version": "1",
            "model": model,
            "base_url": self.base_url,
            "max_output_tokens": max_output_tokens,
            "token_parameter": token_parameter,
        }

    async def complete(self, messages, tools):
        body = {
            "model": self.model,
            "messages": messages,
            self.token_parameter: self.max_output_tokens,
        }
        if tools:
            body["tools"] = tools
        try:
            if self.client is not None:
                response = await self.client.post(
                    self.base_url + "/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                    timeout=self.timeout,
                )
            else:
                async with httpx.AsyncClient(follow_redirects=False) as client:
                    response = await client.post(
                        self.base_url + "/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=body,
                        timeout=self.timeout,
                    )
            if not 200 <= response.status_code < 300:
                raise ProviderError(f"Model provider returned HTTP {response.status_code}")
            data = response.json()
            message = data["choices"][0]["message"]
            calls = []
            for call in message.get("tool_calls") or []:
                arguments = json.loads(call["function"]["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be an object")
                calls.append(ToolCall(call["function"]["name"], arguments, call["id"]))
            usage = data.get("usage")
            if usage is not None:
                usage = {
                    "input_tokens": usage["prompt_tokens"],
                    "output_tokens": usage["completion_tokens"],
                }
            return ModelResponse(
                output=message.get("content"), tool_calls=tuple(calls), usage=usage
            )
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Model call failed or returned an invalid response") from exc
