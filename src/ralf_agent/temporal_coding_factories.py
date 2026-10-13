"""Explicit History Coding resources borrowing the exact original effect owner."""

import math

from .coding_factories import _absolute, _check_paths, validate_binding
from .delegated_coding import register_coding_tool
from .errors import ValidationError
from .runner_journal_state import _json, _text
from .tools import ToolRegistry
from .types import canonical, credits

_FIELDS = frozenset(
    {
        "name",
        "description",
        "cost",
        "runner_root",
        "fixed_dependencies",
        "docker_executable",
        "docker_host",
        "request_timeout",
    }
)


def entries(config):
    if type(config) is not dict:
        raise ValidationError("Temporal Coding requires explicit declarations")
    values = config.get("tools", [config])
    if "tools" in config and (
        set(config) != {"tools"} or type(values) is not list or not 1 <= len(values) <= 16
    ):
        raise ValidationError("Temporal Coding requires one to 16 explicit tools")
    names, roots, dependencies = set(), [], None
    for entry in values:
        if type(entry) is not dict or set(entry) != _FIELDS:
            raise ValidationError("Temporal Coding requires explicit original PostgreSQL resources")
        _text(entry["name"], "Coding tool name", limit=128)
        _text(entry["description"], "Coding tool description", limit=8192)
        credits(entry["cost"])
        for field in ("runner_root", "docker_executable"):
            _absolute(entry[field], "Coding " + field)
        identity = _json(entry["fixed_dependencies"], "Coding fixed dependencies")
        if dependencies is not None and identity != dependencies:
            raise ValidationError("Temporal Coding tools must share original journal dependencies")
        dependencies = identity
        host = _text(entry["docker_host"], "Coding Docker host", limit=4096)
        if not host.startswith("unix:///") or any(c in host for c in ("?", "#")):
            raise ValidationError("Coding Docker host requires a fixed Unix endpoint")
        _absolute(host[len("unix://") :], "Coding Docker socket")
        timeout = entry["request_timeout"]
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValidationError("Coding deadline requires seconds in (0,60]")
        root = entry["runner_root"]
        if entry["name"] in names or any(
            root == other or root.startswith(other + "/") or other.startswith(root + "/")
            for other in roots
        ):
            raise ValidationError("Temporal Coding requires distinct names and private roots")
        names.add(entry["name"])
        roots.append(root)
    return values


def validate(config):
    entries(config)


def preflight_coding_references(profile):
    tool = profile.components.get("tools")
    coding = profile.execution.get("coding_execution", False)
    postgres = tool is not None and tool["adapter"] == "codex-coding-postgres"
    if postgres and not coding:
        raise ValidationError("PostgreSQL tools require explicit Coding execution")
    if coding and tool is not None and tool["adapter"] == "codex-coding":
        raise ValidationError("Temporal Coding requires the original PostgreSQL effect journal")
    names = {entry["name"] for entry in entries(tool["config"])} if postgres else None
    if postgres and "effect_journal" not in profile.components:
        raise ValidationError("Temporal Coding requires a declared original effect journal")
    for declaration in profile.binding_components or ():
        component = declaration["component"]
        if declaration["role"] != "runner" or component["adapter"] != "registered-tool":
            continue
        validate_binding(component["config"])
        if tool is None or (names is not None and component["config"]["name"] not in names):
            raise ValidationError("Runner reference requires the declared original Coding tool")


async def build(config, context):
    from .codex_runner import CodexCodingRunner
    from .postgres_runner_journal import PostgresRunnerJournal
    from .temporal_journal import PostgresEffectJournal

    values = entries(config)
    effect = getattr(context, "effect_journal", None)
    if (
        getattr(context, "coding_execution", False) is not True
        or type(effect) is not PostgresEffectJournal
    ):
        raise ValidationError(
            "Temporal Coding requires explicit execution and exact original effect owner"
        )
    roots = []
    for entry in values:
        root = _check_paths(entry)
        if any(
            root == other or root.startswith(other + "/") or other.startswith(root + "/")
            for other in roots
        ):
            raise ValidationError("Coding physical roots must remain separate")
        roots.append(root)
    journal = context.own_async(
        PostgresRunnerJournal(effect, identity=values[0]["fixed_dependencies"])
    )
    await journal.initialize()
    if journal._effect is not effect or canonical(journal._effect.identity) != canonical(
        effect.identity
    ):
        raise ValidationError("Temporal Coding journal changed its original effect owner")
    tools = ToolRegistry()
    for entry in values:
        runner = context.own_async(
            CodexCodingRunner(
                entry["runner_root"],
                journal=journal,
                docker_executable=entry["docker_executable"],
                docker_host=entry["docker_host"],
                request_timeout=entry["request_timeout"],
            )
        )
        register_coding_tool(
            tools, runner, name=entry["name"], description=entry["description"], cost=entry["cost"]
        )
    return tools


def register_temporal_coding_factories(registry):
    registry.register_async("tools", "codex-coding-postgres", build, validator=validate)
