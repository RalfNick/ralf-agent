"""One exclusive, ephemeral API-key startup phase on the original stdio owner.

The finite wire contract is pinned to official native 0.144.4. Its exclusive
account-auth queue completes login notifications before the following read.
This proves a startup barrier, not absence of future account traffic. This
transport owns only its original local process group; namespace retirement
remains the Runner owner's responsibility.
"""

import asyncio

from .codex_rpc import (
    _MAX_ID,
    CodexRPCCloseIncomplete,
    CodexRPCError,
    CodexRPCTransport,
)

_PROGRESS_FIELDS = {
    "item/agentMessage/delta": None,
    "item/reasoning/textDelta": "contentIndex",
    "item/reasoning/summaryTextDelta": "summaryIndex",
    "item/commandExecution/outputDelta": None,
}
_MAX_PROGRESS_NOTIFICATIONS = 16384


def _progress_update(message, max_bytes):
    if set(message) != {"method", "params"} or type(message["params"]) is not dict:
        return False
    value = message["params"]
    index = _PROGRESS_FIELDS[message["method"]]
    fields = {"threadId", "turnId", "itemId", "delta"} | ({index} if index else set())
    return (
        set(value) == fields
        and all(
            type(value[k]) is str
            and 0 < len(value[k]) <= 256
            and all(32 <= ord(c) <= 126 for c in value[k])
            for k in ("threadId", "turnId", "itemId")
        )
        and type(value["delta"]) is str
        and len(value["delta"]) <= max_bytes
        and not any(0xD800 <= ord(c) <= 0xDFFF for c in value["delta"])
        and (index is None or _quota_int(value[index], 64))
    )


def _quota_text(value):
    return type(value) is str and len(value) <= 256 and all(32 <= ord(c) <= 126 for c in value)


def _quota_int(value, bits):
    return type(value) is int and -(2 ** (bits - 1)) <= value < 2 ** (bits - 1)


def _quota_window(value):
    return value is None or (
        type(value) is dict
        and set(value) == {"usedPercent", "windowDurationMins", "resetsAt"}
        and _quota_int(value["usedPercent"], 32)
        and all(
            value[k] is None or _quota_int(value[k], 64) for k in ("windowDurationMins", "resetsAt")
        )
    )


def _quota_update(message):
    """Validate the exact native 0.144.4 sparse quota notification, then discard.

    Quotas are neither auth state nor an execution-budget decision. No fields
    are retained in futures, event inboxes, journals or diagnostics.
    """
    if (
        set(message) != {"method", "params"}
        or type(message["params"]) is not dict
        or set(message["params"]) != {"rateLimits"}
    ):
        return False
    value = message["params"]["rateLimits"]
    if type(value) is not dict or set(value) != {
        "limitId",
        "limitName",
        "primary",
        "secondary",
        "credits",
        "individualLimit",
        "planType",
        "rateLimitReachedType",
    }:
        return False
    credits, individual = value["credits"], value["individualLimit"]
    return (
        all(value[k] is None or _quota_text(value[k]) for k in ("limitId", "limitName"))
        and _quota_window(value["primary"])
        and _quota_window(value["secondary"])
        and (
            credits is None
            or (
                type(credits) is dict
                and set(credits) == {"hasCredits", "unlimited", "balance"}
                and type(credits["hasCredits"]) is bool
                and type(credits["unlimited"]) is bool
                and (credits["balance"] is None or _quota_text(credits["balance"]))
            )
        )
        and (
            individual is None
            or (
                type(individual) is dict
                and set(individual) == {"limit", "used", "remainingPercent", "resetsAt"}
                and _quota_text(individual["limit"])
                and _quota_text(individual["used"])
                and _quota_int(individual["remainingPercent"], 32)
                and _quota_int(individual["resetsAt"], 64)
            )
        )
        and (
            value["planType"] is None
            or type(value["planType"]) is str
            and value["planType"]
            in {
                "free",
                "go",
                "plus",
                "pro",
                "prolite",
                "team",
                "self_serve_business_usage_based",
                "business",
                "enterprise_cbp_usage_based",
                "enterprise",
                "edu",
                "unknown",
            }
        )
        and (
            value["rateLimitReachedType"] is None
            or type(value["rateLimitReachedType"]) is str
            and value["rateLimitReachedType"]
            in {
                "rate_limit_reached",
                "workspace_owner_credits_depleted",
                "workspace_member_credits_depleted",
                "workspace_owner_usage_limit_reached",
                "workspace_member_usage_limit_reached",
            }
        )
    )


class CodexAuthenticatedTransport(CodexRPCTransport):
    """Coding transport whose business admission requires one successful login.

    Generic requests never admit account methods. Authentication bypasses only
    that admission gate; framing, pipes, PID ownership and cleanup stay shared.
    No credential or raw authentication result is retained on the transport.
    """

    def __init__(
        self,
        argv: tuple[str, ...],
        *,
        env: dict[str, str],
        max_message_bytes: int = 1048576,
        max_events: int = 256,
        request_timeout: float = 30.0,
        control_only: bool = False,
        coding_mode: bool = True,
    ):
        if coding_mode is not True or control_only is not False:
            raise ValueError("authenticated transport requires coding_mode=True")
        CodexRPCTransport.__init__(
            self,
            argv,
            env=env,
            max_message_bytes=max_message_bytes,
            max_events=max_events,
            request_timeout=request_timeout,
            control_only=control_only,
            coding_mode=coding_mode,
        )
        self._auth_used = False
        self._auth_active = False
        self._authenticated = False
        self._auth_stage = None
        self._auth_pending_id = None
        self._auth_response_ids = set()
        self._auth_login_replied = False
        self._auth_notifications = 0
        self._public_calls = 0
        self._quota_notifications = 0
        self._progress_notifications = 0

    async def request(self, method: str, params: dict | None) -> dict:
        self._require_open()
        # Authentication admission cannot depend on the borrowed base subset:
        # even an expanded allowlist must never expose this private phase.
        if type(method) is str and (
            method.startswith("account/")
            or method
            in {
                "loginApiKey",
                "loginChatGpt",
                "cancelLoginChatGpt",
                "logoutChatGpt",
                "getAuthStatus",
                "authStatusChange",
                "loginChatGptComplete",
            }
        ):
            raise ValueError("account methods require the dedicated authentication phase")
        if self._auth_active:
            raise CodexRPCError("authentication requires exclusive transport admission")
        # Preserve the base subset's ValueError for all non-admitted methods.
        if (
            type(method) is str
            and method
            in {"thread/start", "thread/read", "thread/resume", "turn/start", "turn/interrupt"}
            and not self._authenticated
        ):
            raise CodexRPCError("authentication is required before Coding requests")
        self._public_calls += 1
        try:
            result = await super().request(method, params)
            # Auth traffic can invalidate a reply in the same reader batch,
            # including after business admission has begun.
            self._require_open()
            return result
        finally:
            self._public_calls -= 1

    async def notify(self, method: str, params: dict | None = None):
        self._require_open()
        if self._auth_active:
            raise CodexRPCError("authentication requires exclusive transport admission")
        self._public_calls += 1
        try:
            await super().notify(method, params)
        finally:
            self._public_calls -= 1

    async def authenticate_api_key(self, credential: str) -> dict:
        self._require_open()
        if self._auth_used or self._public_calls or self._pending or self._notifications:
            raise CodexRPCError("authentication requires an unused exclusive transport phase")
        if (
            type(credential) is not str
            or not credential
            or any(character in credential for character in ("\0", "\r", "\n"))
        ):
            raise ValueError("API-key credential must be a nonempty NUL/CR/LF-free string")
        self._auth_used = True
        self._auth_active = True
        try:
            await self._auth_request("initial", "account/read", {"refreshToken": False})
            await self._auth_request(
                "login", "account/login/start", {"type": "apiKey", "apiKey": credential}
            )
            credential = None
            await self._auth_request("barrier", "account/read", {"refreshToken": False})
            self._require_open()
            self._authenticated = True
            return {"mode": "apiKey", "ephemeral": True, "barrier_verified": True}
        except asyncio.CancelledError:
            self._begin_close()
            try:
                await self._complete_close()
            except CodexRPCCloseIncomplete:
                # The original cleanup owner and PID remain available for retry.
                # Incomplete local retirement must not replace caller cancellation.
                pass
            raise
        except (CodexRPCError, TimeoutError, ValueError):
            self._fail(CodexRPCError("Codex API-key authentication failed"))
            await self._complete_close()
            raise CodexRPCError("Codex API-key authentication failed") from None
        finally:
            credential = None
            self._auth_active = False
            self._auth_stage = "complete" if self._authenticated else "failed"

    async def _auth_request(self, stage, method, params):
        self._require_open()
        if self._last_id == _MAX_ID:
            raise CodexRPCError("local request ID space exhausted")
        request_id = self._last_id + 1
        payload = self._encode({"id": request_id, "method": method, "params": params})
        params = None
        self._last_id = request_id
        self._auth_response_ids.add(request_id)
        self._auth_stage = stage
        self._auth_pending_id = request_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        async def exchange():
            await self._send(payload)
            await future

        try:
            await asyncio.wait_for(exchange(), timeout=self._request_timeout)
            # A reply followed by rejected traffic in the same reader batch is
            # not evidence of a successful exchange.
            self._require_open()
        finally:
            payload = None
            self._pending.pop(request_id, None)
            self._auth_pending_id = None
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    def _route(self, message):
        if self._auth_active:
            self._route_auth(message)
            return
        if type(message) is dict:
            method = message.get("method")
            if type(method) is str and method in _PROGRESS_FIELDS:
                if (
                    not self._authenticated
                    or not self._coding_business
                    or self._progress_notifications >= _MAX_PROGRESS_NOTIFICATIONS
                    or not _progress_update(message, self._max_message_bytes)
                ):
                    raise ValueError("unreviewed or overflowing native progress notification")
                self._progress_notifications += 1
                return
            if method == "account/rateLimits/updated":
                if (
                    not self._authenticated
                    or not self._coding_business
                    or self._quota_notifications >= self._max_events
                    or not _quota_update(message)
                ):
                    raise ValueError("unreviewed or overflowing native quota notification")
                self._quota_notifications += 1
                return
            if type(method) is str and (
                method.startswith("account/")
                or method in {"authStatusChange", "loginChatGptComplete"}
            ):
                raise ValueError("unexpected account traffic outside authentication")
            if "method" not in message:
                request_id = message.get("id")
                if type(request_id) is not int or request_id in self._auth_response_ids:
                    raise ValueError("uncorrelated or retired authentication response")
                if "error" in message:
                    self._sanitized_error(message)
                    return
        super()._route(message)

    def _route_auth(self, message):
        if type(message) is not dict:
            raise ValueError("invalid authentication frame")
        if "method" in message:
            if (
                set(message) != {"method", "params"}
                or not self._auth_login_replied
                or self._auth_stage not in {"login", "barrier"}
                or type(message["params"]) is not dict
            ):
                raise ValueError("unexpected authentication notification")
            params = message["params"]
            if self._auth_notifications == 0:
                valid = (
                    message["method"] == "account/login/completed"
                    and set(params) == {"loginId", "success", "error"}
                    and params["loginId"] is None
                    and params["success"] is True
                    and params["error"] is None
                )
            elif self._auth_notifications == 1:
                valid = (
                    message["method"] == "account/updated"
                    and set(params) == {"authMode", "planType"}
                    and params["authMode"] == "apikey"
                    and params["planType"] is None
                )
            else:
                valid = False
            if not valid:
                raise ValueError("unreviewed or duplicate authentication notification")
            self._auth_notifications += 1
            return
        request_id = message.get("id")
        future = self._pending.get(request_id) if type(request_id) is int else None
        if (
            type(request_id) is not int
            or request_id != self._auth_pending_id
            or future is None
            or future.done()
        ):
            raise ValueError("uncorrelated authentication response")
        if set(message) == {"id", "error"}:
            # Never put peer errors (including nested data) in a future or state.
            self._fail(CodexRPCError("Codex API-key authentication failed"))
            return
        if set(message) != {"id", "result"} or type(message["result"]) is not dict:
            raise ValueError("invalid authentication response envelope")
        result = message["result"]
        if self._auth_stage == "login":
            valid = set(result) == {"type"} and result["type"] == "apiKey"
            if valid:
                self._auth_login_replied = True
        else:
            valid = (
                set(result) == {"account", "requiresOpenaiAuth"}
                and result["requiresOpenaiAuth"] is True
            )
            if valid and self._auth_stage == "initial":
                valid = result["account"] is None
            elif valid and self._auth_stage == "barrier":
                account = result["account"]
                valid = (
                    type(account) is dict
                    and set(account) == {"type"}
                    and account["type"] == "apiKey"
                    and self._auth_notifications == 2
                )
            else:
                valid = False
        if not valid:
            raise ValueError("unreviewed authentication result")
        # Resolve only a sentinel, never a native auth object or credential echo.
        future.set_result(None)

    def _sanitized_error(self, message):
        request_id = message.get("id")
        error = message.get("error")
        if (
            set(message) != {"id", "error"}
            or type(request_id) is not int
            or not 1 <= request_id <= self._last_id
            or type(error) is not dict
            or set(error) not in ({"code", "message"}, {"code", "message", "data"})
            or type(error.get("code")) is not int
            or type(error.get("message")) is not str
        ):
            raise ValueError("invalid JSON-RPC error")
        future = self._pending.get(request_id)
        if future is not None and not future.done():
            future.set_exception(CodexRPCError("Codex App Server rejected the request"))
