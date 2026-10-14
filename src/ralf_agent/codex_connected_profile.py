"""Connected Responses selection on the unchanged bounded native Coding profile."""

import copy
import hashlib
import json
import tomllib

from .codex_coding_profile import CodexCodingProfile, _canonical
from .codex_model_connection import CodexModelConnection
from .errors import ValidationError


class ConnectedCodexCodingProfile(CodexCodingProfile):
    """Only nonsecret model configuration varies; complete native control stays exact."""

    def __init__(self, connection: CodexModelConnection):
        if type(connection) is not CodexModelConnection:
            raise ValidationError("Connected Coding profile requires a fixed model connection")
        connection.__post_init__()
        CodexCodingProfile.__init__(self)
        self._connection_identity = connection.identity
        model = json.dumps(connection.model)
        effort = json.dumps(connection.reasoning_effort)
        endpoint = json.dumps(connection.base_url)
        self._config_text = (
            f'model = {model}\nmodel_provider = "ralf-connected"\n'
            f"model_reasoning_effort = {effort}\n"
            + self._config_text
            + '\n[model_providers.ralf-connected]\nname = "Ralf connected Responses"\n'
            + f"base_url = {endpoint}\n"
            + 'wire_api = "responses"\nrequires_openai_auth = true\n'
        )
        self._parsed = tomllib.loads(self._config_text)
        self._origin = "sha256:" + hashlib.sha256(_canonical(self._parsed).encode()).hexdigest()
        self._digest = hashlib.sha256(self._config_text.encode()).hexdigest()
        self._expected_config.update(
            model=connection.model,
            model_provider="ralf-connected",
            model_reasoning_effort=connection.reasoning_effort,
            model_providers={
                "ralf-connected": {
                    "name": "Ralf connected Responses",
                    "base_url": connection.base_url,
                    "wire_api": "responses",
                    "requires_openai_auth": True,
                    "supports_websockets": False,
                    **{
                        name: None
                        for name in (
                            "env_key",
                            "env_key_instructions",
                            "experimental_bearer_token",
                            "auth",
                            "aws",
                            "query_params",
                            "http_headers",
                            "env_http_headers",
                            "request_max_retries",
                            "stream_max_retries",
                            "stream_idle_timeout_ms",
                            "websocket_connect_timeout_ms",
                        )
                    },
                }
            },
        )

    @property
    def identity(self) -> dict:
        return {
            **CodexCodingProfile.identity.fget(self),
            "kind": "codex-connected-coding-candidate",
            "connection": copy.deepcopy(self._connection_identity),
        }
