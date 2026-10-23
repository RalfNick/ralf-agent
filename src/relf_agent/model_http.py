"""Single HTTP request/stream lifetime; protocol fragments are never decisions."""

import os
from contextlib import asynccontextmanager
from dataclasses import asdict

import httpx

from .errors import ProviderError, ValidationError
from .model_protocol import ModelCapabilities, ModelStreamEvent, configuration, generation, request

MAX_STREAM_BYTES = 4_000_000
MAX_FRAME_BYTES = 1_000_000


async def sse_events(response):
    buffer, data, event, total, frame_bytes = b"", [], None, 0, 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_STREAM_BYTES:
            raise ValueError("Model stream exceeds response limit")
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            frame_bytes += len(line)
            if frame_bytes > MAX_FRAME_BYTES:
                raise ValueError("Model stream frame exceeds limit")
            line = line.rstrip(b"\r").decode("utf-8")
            if not line:
                if data:
                    yield event, "\n".join(data)
                data, event, frame_bytes = [], None, 0
            elif line.startswith("data:"):
                data.append(line[5:].removeprefix(" "))
            elif line.startswith("event:"):
                event = line[6:].strip()
        if len(buffer) + frame_bytes > MAX_FRAME_BYTES:
            raise ValueError("Model stream frame exceeds limit")
    if data or buffer.strip():
        raise ValueError("Unterminated model stream frame")


class HTTPModelProvider:
    supported = ModelCapabilities()
    max_temperature = 2
    allow_seed = True

    def _configure(
        self,
        model,
        api_key,
        key_env,
        base_url,
        max_output_tokens,
        timeout,
        client,
        temperature,
        top_p,
        stop,
        seed,
        stream,
        capabilities,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get(key_env)
        if not isinstance(self.api_key, str) or not self.api_key:
            raise ValidationError(f"Provide api_key or set {key_env}")
        self.base_url = base_url.rstrip("/") if isinstance(base_url, str) else base_url
        self.max_output_tokens, self.timeout, self.client = max_output_tokens, timeout, client
        self.temperature, self.top_p, self.stop, self.seed = temperature, top_p, stop, seed
        self.stream_response = stream
        self.capabilities = self.supported if capabilities is None else capabilities
        _ = self.identity

    def _configuration(self, kind):
        configuration(self.model, self.base_url, self.max_output_tokens, self.timeout)
        if (
            not isinstance(self.capabilities, ModelCapabilities)
            or type(self.stream_response) is not bool
            or any(
                value and not asdict(self.supported)[name]
                for name, value in asdict(self.capabilities).items()
            )
        ):
            raise ValidationError("Capabilities cannot enable unsupported adapter behavior")
        if self.stream_response and not self.capabilities.streaming:
            raise ValidationError("Streaming is disabled by model capabilities")
        value = {
            "kind": kind,
            "version": "1",
            "model": self.model,
            "base_url": self.base_url,
            "max_output_tokens": self.max_output_tokens,
            "timeout": self.timeout,
        }
        options = generation(
            self.temperature,
            self.top_p,
            self.stop,
            self.seed,
            max_temperature=self.max_temperature,
            allow_seed=self.allow_seed,
        )
        if options:
            value["generation"] = options
        if self.stream_response:
            value["stream"] = True
        if self.capabilities != self.supported:
            value["capabilities"] = asdict(self.capabilities)
        return value

    def validate_request(self, messages, tools):
        self._prepared(messages, tools)

    @asynccontextmanager
    async def _client(self):
        if self.client is not None:
            yield self.client
        else:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                yield client

    def _prepared(self, messages, tools, *, streaming=False):
        config = self.identity
        if streaming and not self.capabilities.streaming:
            raise ValidationError("Streaming is disabled by model capabilities")
        if not isinstance(self.api_key, str) or not self.api_key:
            raise ValidationError("Model credential is unavailable")
        messages, tools = request(messages, tools, self.capabilities)
        try:
            url, body = self._body(messages, tools, config)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError) as exc:
            raise ValidationError("Model request cannot be represented by this protocol") from exc
        headers = self._headers(self.api_key)
        if streaming:
            url, body = self._stream_body(url, body)
        return url, body, headers, config["timeout"]

    async def complete(self, messages, tools):
        if self.stream_response:
            async for event in self.stream(messages, tools):
                if event.kind == "response":
                    return event.response
            raise ProviderError("Model stream did not complete")
        url, body, headers, timeout = self._prepared(messages, tools)
        capabilities = self.capabilities
        try:
            async with self._client() as client:
                result = await client.post(
                    url, json=body, headers=headers, timeout=timeout, follow_redirects=False
                )
                if not 200 <= result.status_code < 300:
                    raise ProviderError(f"Model provider returned HTTP {result.status_code}")
                if len(result.content) > MAX_STREAM_BYTES:
                    raise ValueError("Model response exceeds limit")
                completed = self._parse(result.text)
                if completed.tool_calls and not capabilities.tools:
                    raise ValueError("Tool response exceeds configured capability")
                return completed
        except ProviderError:
            raise
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            RecursionError,
        ) as exc:
            raise ProviderError("Model call failed or returned an invalid response") from exc

    async def stream(self, messages, tools):
        url, body, headers, timeout = self._prepared(messages, tools, streaming=True)
        capabilities = self.capabilities
        state = self._stream_state()
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST", url, json=body, headers=headers, timeout=timeout, follow_redirects=False
                ) as result:
                    if not 200 <= result.status_code < 300:
                        raise ProviderError(f"Model provider returned HTTP {result.status_code}")
                    async for event, data in sse_events(result):
                        for text in state.feed(event, data):
                            yield ModelStreamEvent("text", text=text)
                    completed = state.finish()
                    if completed.tool_calls and not capabilities.tools:
                        raise ValueError("Tool response exceeds configured capability")
            yield ModelStreamEvent("response", response=completed)
        except ProviderError:
            raise
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            RecursionError,
        ) as exc:
            raise ProviderError(
                "Model stream failed or did not return a complete response"
            ) from exc
