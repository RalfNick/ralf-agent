"""Explicit authenticated resource specialization of the original Coding loop."""

import copy
import inspect
from dataclasses import FrozenInstanceError

from .codex_auth_transport import CodexAuthenticatedTransport
from .codex_connected_environment import ConnectedDockerCodingEnvironment
from .codex_connected_profile import ConnectedCodexCodingProfile
from .codex_credentials import (
    EnvironmentCodingCredentials,
    source_registration,
    validate_credential,
)
from .codex_model_connection import CodexModelConnection
from .codex_runner import CodexCodingRunner, RunnerUnavailable
from .component_fingerprint import _code, executable_digest
from .errors import DefinitionMismatch, ValidationError
from .task_controls import _binding
from .types import canonical, digest


def _connection_method_digest(name, method):
    # Frozen dataclass code captures precisely these trusted compiler values.
    # This narrow native declaration adapter does not relax plugin fingerprints.
    if name not in {"__init__", "__setattr__", "__delattr__"}:
        return executable_digest(method)
    captures = []
    for label, cell in zip(method.__code__.co_freevars, method.__closure__ or (), strict=True):
        value = cell.cell_contents
        if value is object:
            captured = "builtins.object"
        elif value is FrozenInstanceError:
            captured = "dataclasses.FrozenInstanceError"
        elif (
            label == "cls"
            and inspect.isclass(value)
            and value.__module__ == CodexModelConnection.__module__
            and value.__qualname__ == CodexModelConnection.__qualname__
            and value.__dataclass_fields__ is CodexModelConnection.__dataclass_fields__
        ):
            captured = "fixed-codex-model-connection-dataclass"
        else:
            raise ValidationError("Connected Coding compiler capture changed")
        captures.append({"name": label, "capture": captured})
    return digest(
        {
            "algorithm": "fixed-connection-dataclass-v1",
            "code": _code(method.__code__),
            "defaults": method.__defaults__,
            "keyword_defaults": method.__kwdefaults__,
            "captures": captures,
        }
    )


def _module_group(module, classes):
    group = {}
    for name, value in vars(module).items():
        if inspect.isfunction(value):
            group[name] = executable_digest(value)
    for cls in classes:
        for name, method in vars(cls).items():
            if name.startswith("__") and name not in {
                "__init__",
                "__post_init__",
                "__setattr__",
                "__delattr__",
            }:
                continue
            if isinstance(method, (staticmethod, classmethod)):
                method = method.__func__
            elif isinstance(method, property):
                method = method.fget
            if inspect.isfunction(method):
                group[f"{cls.__name__}.{name}"] = (
                    _connection_method_digest(name, method)
                    if cls is CodexModelConnection
                    else executable_digest(method)
                )
    return group


def _policy_value(value):
    """Type-preserving JSON for the finite nonsecret native policy constants."""
    if inspect.isfunction(value):
        return {"function": executable_digest(value)}
    if type(value) is dict:
        return {"dict": {name: _policy_value(item) for name, item in value.items()}}
    if type(value) in (tuple, list):
        return {type(value).__name__: [_policy_value(item) for item in value]}
    if type(value) is frozenset:
        return {"frozenset": sorted((_policy_value(item) for item in value), key=canonical)}
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise DefinitionMismatch("Connected Coding policy data changed")


def connection_implementation():
    """Individually pin new helpers; never discover I/O while replaying History."""
    from . import (
        codex_auth_transport,
        codex_coding_profile,
        codex_connected_environment,
        codex_connected_profile,
        codex_credentials,
        codex_environment,
        codex_model_connection,
        codex_rpc,
        codex_runner,
        codex_runner_capacity,
        coding_resource_fingerprint,
    )

    result = {}
    for module, classes in (
        (codex_auth_transport, (CodexAuthenticatedTransport,)),
        (codex_connected_environment, (ConnectedDockerCodingEnvironment,)),
        (codex_connected_profile, (ConnectedCodexCodingProfile,)),
        (codex_credentials, (EnvironmentCodingCredentials,)),
        (codex_model_connection, (CodexModelConnection,)),
        (codex_rpc, (codex_rpc.CodexRPCTransport,)),
        (codex_coding_profile, (codex_coding_profile.CodexCodingProfile,)),
        (codex_environment, (codex_environment.DockerCodingEnvironment,)),
        (codex_runner, (CodexCodingRunner,)),
        (codex_runner_capacity, (codex_runner_capacity.RootCapacity,)),
        (coding_resource_fingerprint, ()),
    ):
        result[module.__name__] = _module_group(module, classes)
        result[module.__name__]["policy_constants"] = digest(
            {
                name: _policy_value(value)
                for name, value in vars(module).items()
                if name.startswith("_") and not name.startswith("__") and name[1:].isupper()
            }
        )
    result["runner"] = {
        name: executable_digest(getattr(ConnectedCodexCodingRunner, name))
        for name in ("__init__", "_make_transport", "_environment", "_preflight", "_check_root")
    }
    result["runner"]["identity"] = executable_digest(ConnectedCodexCodingRunner.identity.fget)
    result["inventory"] = {
        "entry": executable_digest(connection_implementation),
        "module_group": executable_digest(_module_group),
        "connection_method": executable_digest(_connection_method_digest),
        "policy_value": executable_digest(_policy_value),
        "model_fields": digest(sorted(codex_model_connection._FIELDS)),
    }
    return result


class ConnectedCodexCodingRunner(CodexCodingRunner):
    """One connection, lazy borrowed source, and the original execution authority."""

    def __init__(self, root, *, connection, credential_source=None, **kwargs):
        if type(connection) is not CodexModelConnection:
            raise ValidationError("Connected Coding requires an explicit model connection")
        source = EnvironmentCodingCredentials() if credential_source is None else credential_source
        registration = source_registration(source)
        implementation = connection_implementation()
        CodexCodingRunner.__init__(self, root, **kwargs)
        self._connection = connection
        self._credential_source = source
        self._source_registration = registration
        self._connection_implementation = implementation
        self._inventory_bindings = tuple(
            _binding(method)
            for method in (
                connection_implementation,
                _module_group,
                _connection_method_digest,
                _policy_value,
                source_registration,
                validate_credential,
            )
        )
        self._profile = ConnectedCodexCodingProfile(connection)
        self._identity.update(
            {
                "version": "2",
                "profile": self._profile.identity,
                "connection": connection.identity,
                "credential_source": registration,
                # The complete independently checked inventory stays on this
                # Worker. Original dispatch/bindings repeat the public identity;
                # a bounded digest prevents that repetition exceeding journal
                # limits without weakening any per-helper drift check.
                "connection_implementation": {
                    "algorithm": "fixed-native-connection-inventory-v1",
                    "digest": digest(implementation),
                },
                "credentials": "ephemeral-api-key",
                "configuration_readonly": True,
            }
        )

    @property
    def identity(self):
        self._check_root()
        return copy.deepcopy(self._identity)

    def _check_root(self):
        CodexCodingRunner._check_root(self)
        if (
            type(self) is not ConnectedCodexCodingRunner
            or tuple(
                _binding(method)
                for method in (
                    connection_implementation,
                    _module_group,
                    _connection_method_digest,
                    _policy_value,
                    source_registration,
                    validate_credential,
                )
            )
            != self._inventory_bindings
            or canonical(self._connection.identity) != canonical(self._identity["connection"])
            or source_registration(self._credential_source) != self._source_registration
            or self._identity["connection_implementation"]
            != {
                "algorithm": "fixed-native-connection-inventory-v1",
                "digest": digest(self._connection_implementation),
            }
            or connection_implementation() != self._connection_implementation
        ):
            raise DefinitionMismatch("Connected Coding dependencies changed")
        expected = ConnectedCodexCodingProfile(self._connection)
        if (
            canonical(self._profile.identity) != canonical(self._identity["profile"])
            or self._profile.config_text != expected.config_text
            or canonical(self._profile._expected_config) != canonical(expected._expected_config)
        ):
            raise DefinitionMismatch("Connected Coding profile changed")

    def _environment(self, envelope, *, create):
        self._check_root()
        path, resource_id, generation = self._location(envelope)
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
        elif not path.exists():
            return None
        return ConnectedDockerCodingEnvironment(
            path,
            resource_id,
            connection=self._connection,
            docker_executable=self._docker,
            docker_host=self._host,
            command_timeout=self._timeout,
            retire_on_stop=True,
            expected_generation=generation,
            configuration_readonly=True,
            create_recovery=True,
        )

    def _make_transport(self, owner, environment):
        self._check_root()
        return CodexAuthenticatedTransport(
            environment.transport_argv(),
            env=environment.transport_env,
            request_timeout=self._timeout,
            coding_mode=True,
        )

    async def _preflight(self, owner):
        await CodexCodingRunner._preflight(self, owner)
        self._check_root()
        await self._cancelled_owned(owner)
        # Resolution and the auth wire never pass through journal/observe helpers.
        credential = None
        failed = False
        try:
            credential = await self._credential_source.resolve(
                copy.deepcopy(self._connection.identity)
            )
            credential = validate_credential(credential)
        except Exception:
            failed = True
        if failed:
            credential = None
            # Raise outside the source exception handler: no raw secret-bearing
            # source exception remains in the public exception context chain.
            raise RunnerUnavailable("authentication unavailable")
        try:
            self._check_root()
            await self._cancelled_owned(owner)
            await owner["transport"].authenticate_api_key(credential)
            await self._cancelled_owned(owner)
            self._check_root()
        finally:
            credential = None
