"""Connected model profile with the original retained Docker lifecycle and mechanics."""

from pathlib import Path

from .codex_connected_profile import ConnectedCodexCodingProfile
from .codex_environment import DockerCodingEnvironment, _canonical, _digest, _require
from .codex_model_connection import CodexModelConnection
from .errors import DefinitionMismatch, ValidationError


def _profile_state(profile):
    return (
        profile.config_text,
        _canonical(profile.identity),
        _canonical(profile._parsed),
        _canonical(profile._expected_config),
    )


class ConnectedDockerCodingEnvironment(DockerCodingEnvironment):
    """One fixed connection, read-only config mount, original v2 namespace retirement."""

    def __init__(
        self,
        root: str | Path,
        resource_id: str,
        *,
        connection: CodexModelConnection,
        docker_executable: str,
        docker_host: str,
        command_timeout: float = 20.0,
        retire_on_stop: bool = True,
        expected_generation: str | None = None,
        configuration_readonly: bool = True,
        create_recovery: bool = False,
        create_supervision: bool = False,
        supervision_sources: dict | None = None,
    ):
        if (
            type(connection) is not CodexModelConnection
            or retire_on_stop is not True
            or configuration_readonly is not True
        ):
            raise ValidationError(
                "Connected Coding requires a fixed connection and protected v2 resource"
            )
        connection.__post_init__()
        DockerCodingEnvironment.__init__(
            self,
            root,
            resource_id,
            docker_executable=docker_executable,
            docker_host=docker_host,
            command_timeout=command_timeout,
            retire_on_stop=retire_on_stop,
            expected_generation=expected_generation,
            configuration_readonly=configuration_readonly,
            create_recovery=create_recovery,
            create_supervision=create_supervision,
            supervision_sources=supervision_sources,
        )
        self._connection = connection
        self._connection_pin = _canonical(connection.identity)
        self._profile = ConnectedCodexCodingProfile(connection)
        self._profile_pin = _profile_state(self._profile)
        self._identity["profile"] = self._profile.identity
        self._name = "ralf-coding-" + _digest(_canonical(self._identity).encode())[:32]

    def _check_root(self):
        DockerCodingEnvironment._check_root(self)
        try:
            _require(type(self._connection) is CodexModelConnection)
            _require(type(self._profile) is ConnectedCodexCodingProfile)
            _require(_canonical(self._connection.identity) == self._connection_pin)
            _require(_profile_state(self._profile) == self._profile_pin)
            _require(_canonical(self._identity["profile"]) == self._profile_pin[1])
            _require(self._identity.get("configuration_readonly") is True)
            _require(self._identity.get("retire_on_stop") is True)
        except (AttributeError, KeyError, TypeError, ValueError):
            raise DefinitionMismatch(
                "Connected Coding profile differs from its fixed declaration"
            ) from None
