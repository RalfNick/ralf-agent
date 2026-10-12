"""Explicit native Sandbox admission using the original resource ledger."""

from .docker_sandbox import DockerSandbox
from .errors import ValidationError
from .sandbox_tools import SandboxToolSource
from .skills import _text
from .tool_sources import ToolPolicy, register_tool_source
from .tools import ToolRegistry, ToolSpec
from .types import Scope
from .workspace import _authorize, _configuration, _utf8

NATIVE_FIELDS = frozenset(
    {
        "socket_path",
        "image",
        "version",
        "api_version",
        "memory_bytes",
        "nano_cpus",
        "pids_limit",
        "max_calls",
        "max_output_bytes",
        "scratch_bytes",
        "control_timeout",
        "lease_root_path",
    }
)


def _parse(config):
    if (
        type(config) is not dict
        or not {"socket_path", "image", "version"} <= set(config)
        or set(config)
        - NATIVE_FIELDS
        - {"scopes", "max_timeout", "prefix", "requires_approval", "cost"}
    ):
        raise ValidationError("Sandbox declaration requires fixed socket, image and version")
    scopes = None
    if "scopes" in config:
        values = config["scopes"]
        if (
            type(values) is not list
            or not 1 <= len(values) <= 256
            or any(type(v) is not dict or set(v) != {"workspace", "principal"} for v in values)
        ):
            raise ValidationError("Sandbox declaration requires explicit Scope objects")
        for value in values:
            for item in value.values():
                _text(item, "Sandbox declared Scope", 512)
        scopes = _configuration(config["version"], [Scope(**value) for value in values])
    native = {n: config[n] for n in NATIVE_FIELDS if n in config}
    # The default constructor is pure; admission/client allocation is only aopen.
    DockerSandbox(**native, scopes=scopes or (Scope(),))
    timeout = config.get("max_timeout", 30)
    if type(timeout) not in (int, float) or not 0 < timeout <= 300:
        raise ValidationError("Sandbox declared timeout requires seconds in (0,300]")
    prefix = config.get("prefix", "")
    _utf8(prefix, "Sandbox declared tool prefix", max_bytes=256)
    policy = ToolPolicy(
        config["version"],
        effect="read_only",
        requires_approval=config.get("requires_approval", True),
        cost=config.get("cost", 1),
    )
    ToolSpec(
        prefix + "sandbox_run",
        "Native Sandbox",
        {"type": "object"},
        policy.version,
        policy.effect,
        policy.requires_approval,
        policy.cost,
    )
    return native, scopes, timeout, prefix, policy


def validate(config):
    _parse(config)


async def build(config, context):
    native, scopes, timeout, prefix, policy = _parse(config)
    _authorize(context.scope, scopes or (context.scope,))
    provider = context.own_async(DockerSandbox(**native, scopes=scopes or (context.scope,)))
    await provider.aopen()
    source = context.own_async(
        SandboxToolSource(
            provider,
            version=config["version"],
            max_timeout=timeout,
            max_output_bytes=config.get("max_output_bytes", 1048576),
            max_calls=config.get("max_calls", 4),
        )
    )
    registry = ToolRegistry()
    await register_tool_source(registry, source, policies={"sandbox_run": policy}, prefix=prefix)
    return registry


def register_sandbox_tools(registry):
    registry.register_async("tools", "sandbox-docker", build, validator=validate)
