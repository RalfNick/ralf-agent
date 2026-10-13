"""Owned, bounded native control readback without business task admission."""

from .codex_coding_profile import CodexCodingProfile
from .codex_protocol import CodexControlProtocol
from .codex_rpc import CodexRPCTransport
from .errors import ValidationError


class CodexControlProbe:
    """One control-only connection, closed on success, failure or cancellation.

    argv/env must come from the caller's verified contained environment. This
    object checks native readback, not peer binary provenance, authentication,
    filesystem enforcement or application permission to start a business Turn.
    aclose can retry incomplete local process cleanup; container ownership stays
    with the caller, since terminating docker attach does not stop a container.
    """

    def __init__(
        self, argv: tuple[str, ...], *, env: dict[str, str], request_timeout: float = 30.0
    ):
        self._protocol = CodexControlProtocol()
        self._profile = CodexCodingProfile()
        self._transport = CodexRPCTransport(
            argv, env=env, request_timeout=request_timeout, control_only=True
        )
        self._started = False

    async def verify(self) -> dict:
        if self._started:
            raise ValidationError("Codex control probe cannot be reused")
        self._started = True
        results = {}
        try:
            await self._transport.start()
            queries = (
                (
                    "initialize",
                    {
                        "clientInfo": {"name": "ralf_control_probe", "version": "1"},
                        "capabilities": {"experimentalApi": False},
                    },
                ),
                ("config/read", {"cwd": "/workspace", "includeLayers": True}),
                ("configRequirements/read", None),
                ("experimentalFeature/list", {"limit": 200}),
                ("permissionProfile/list", {"cwd": "/workspace", "limit": 200}),
                ("mcpServerStatus/list", {"limit": 200, "detail": "full"}),
                ("skills/list", {"cwds": ["/workspace"], "forceReload": True}),
                ("plugin/list", {"cwds": ["/workspace"], "marketplaceKinds": ["local"]}),
                ("plugin/installed", {"cwds": ["/workspace"]}),
            )
            for method, params in queries:
                params = self._protocol.validate_request(method, params)
                result = await self._transport.request(method, params)
                results[method] = self._protocol.validate_response(method, result)
                if method == "initialize":
                    await self._transport.notify("initialized")
            return self._profile.validate_control(results)
        finally:
            await self._transport.aclose()

    async def aclose(self):
        await self._transport.aclose()
