"""One-shot model calls; providers do not execute tools or retry business calls."""

import json
import math
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
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not isinstance(self.api_key, str) or not self.api_key:
            raise ValidationError("Provide api_key or set OPENAI_API_KEY")
        self.base_url = base_url.rstrip("/") if isinstance(base_url, str) else base_url
        self.max_output_tokens = max_output_tokens
        self.token_parameter = token_parameter
        self.timeout = timeout
        self.client = client
        _ = self.identity  # Validate before an engine accepts this provider.

    @property
    def identity(self):
        """A fresh identity of the same configuration used for actual requests."""
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValidationError("Model must be a non-empty string")
        if not isinstance(self.base_url, str):
            raise ValidationError("Base URL must be HTTP(S) without embedded credentials or query")
        try:
            url = urlsplit(self.base_url)
        except ValueError as exc:
            raise ValidationError("Invalid model provider base URL") from exc
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
            not isinstance(self.token_parameter, str)
            or self.token_parameter not in {"max_tokens", "max_completion_tokens"}
            or type(self.max_output_tokens) is not int
            or self.max_output_tokens < 1
        ):
            raise ValidationError("Invalid output token configuration")
        if self.timeout is not None and (
            type(self.timeout) not in {int, float}
            or not math.isfinite(self.timeout)
            or self.timeout <= 0
        ):
            raise ValidationError("Timeout must be positive finite seconds or None")
        return {
            "kind": "openai-chat-completions",
            "version": "1",
            "model": self.model,
            "base_url": self.base_url,
            "max_output_tokens": self.max_output_tokens,
            "token_parameter": self.token_parameter,
            "timeout": self.timeout,
        }

    async def complete(self, messages, tools):
        configuration = self.identity
        body = {
            "model": configuration["model"],
            "messages": messages,
            configuration["token_parameter"]: configuration["max_output_tokens"],
        }
        if tools:
            body["tools"] = tools
        try:
            if self.client is not None:
                response = await self.client.post(
                    configuration["base_url"].rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                    timeout=configuration["timeout"],
                )
            else:
                async with httpx.AsyncClient(follow_redirects=False) as client:
                    response = await client.post(
                        configuration["base_url"].rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=body,
                        timeout=configuration["timeout"],
                    )
            if not 200 <= response.status_code < 300:
                raise ProviderError(f"Model provider returned HTTP {response.status_code}")
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Response must be an object")
            choice = data["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict) or message.get("role", "assistant") != "assistant":
                raise ValueError("Unsupported message shape")
            if message.get("refusal") is not None or (
                "finish_reason" in choice and choice["finish_reason"] not in {"stop", "tool_calls"}
            ):
                raise ProviderError("Model response was refused or incomplete")
            native_calls = message.get("tool_calls") or []
            if not isinstance(native_calls, list):
                raise ValueError("Tool calls must be a list")
            calls = []
            for call in native_calls:
                if (
                    not isinstance(call, dict)
                    or not isinstance(call.get("id"), str)
                    or not call["id"]
                    or not isinstance(call.get("function"), dict)
                ):
                    raise ValueError("Invalid tool-call identity")
                if (
                    not isinstance(call["function"].get("name"), str)
                    or not call["function"]["name"]
                ):
                    raise ValueError("Invalid tool name")
                arguments = json.loads(call["function"]["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be an object")
                calls.append(ToolCall(call["function"]["name"], arguments, call["id"]))
            if not calls and (
                not isinstance(message.get("content"), str) or not message["content"].strip()
            ):
                raise ProviderError("Model response contained no final content or tool calls")
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
