"""One fixed HTTP POST lifetime, retained until its owned client closes."""

import time

import httpx

from .tool_json import decode_output
from .tool_sources import ToolSourceError


def execute(url, headers, payload, timeout, output_limit, stopped):
    deadline = time.monotonic() + timeout

    def check():
        if stopped.is_set() or time.monotonic() >= deadline:
            raise ToolSourceError("HTTP tool request stopped or timed out")

    try:
        check()
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            with client.stream(
                "POST",
                url,
                content=payload,
                headers={
                    **headers,
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                },
            ) as response:
                check()
                if not 200 <= response.status_code < 300:
                    raise ToolSourceError("HTTP tool request returned an unsuccessful status")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise ToolSourceError("HTTP tool response requires identity encoding")
                output = bytearray()
                for chunk in response.iter_raw():
                    check()
                    if len(output) + len(chunk) > output_limit:
                        raise ToolSourceError("HTTP tool response exceeds its byte limit")
                    output.extend(chunk)
                check()
                return decode_output(output)
    except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError, RecursionError):
        raise ToolSourceError("HTTP tool transport or JSON response failed") from None
