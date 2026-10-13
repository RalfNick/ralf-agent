"""Explicit contained Coding declarations; original assembly owns each resource once."""

import math
import os
import stat
from pathlib import Path

from .delegated_coding import register_coding_tool, registered_coding_tool
from .errors import ValidationError
from .runner_journal_state import _json, _text
from .tools import ToolRegistry
from .types import credits

_FIELDS = frozenset(
    {
        "name",
        "description",
        "cost",
        "runner_root",
        "journal_path",
        "fixed_dependencies",
        "docker_executable",
        "docker_host",
        "request_timeout",
    }
)


def _absolute(value, label):
    _text(value, label, limit=4096)
    if not os.path.isabs(value) or os.path.abspath(value) != value:
        raise ValidationError(f"{label} requires a canonical absolute path")


def _entry(config):
    if type(config) is not dict or set(config) != _FIELDS:
        raise ValidationError("Coding declaration requires explicit tool and fixed dependencies")
    _text(config["name"], "Coding tool name", limit=128)
    _text(config["description"], "Coding tool description", limit=8192)
    credits(config["cost"])
    for field in ("runner_root", "journal_path", "docker_executable"):
        _absolute(config[field], "Coding " + field)
    _json(config["fixed_dependencies"], "Coding fixed dependencies")
    host = _text(config["docker_host"], "Coding Docker host", limit=4096)
    if not host.startswith("unix:///") or any(c in host for c in ("?", "#")):
        raise ValidationError("Coding Docker host requires a fixed Unix endpoint")
    _absolute(host[len("unix://") :], "Coding Docker socket")
    timeout = config["request_timeout"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValidationError("Coding deadline requires seconds in (0,60]")


def _entries(config):
    if type(config) is not dict:
        raise ValidationError("Coding config requires explicit declarations")
    if "tools" in config:
        entries = config["tools"]
        if set(config) != {"tools"} or type(entries) is not list or not 1 <= len(entries) <= 16:
            raise ValidationError("Coding tools require one to 16 explicit declarations")
    else:
        entries = [config]
    names, roots, journals = set(), [], set()
    for entry in entries:
        _entry(entry)
        root, journal = entry["runner_root"], entry["journal_path"]
        if entry["name"] in names:
            raise ValidationError("Coding declarations require distinct tool names")
        if any(
            root == other or root.startswith(other + "/") or other.startswith(root + "/")
            for other in roots
        ):
            raise ValidationError("Coding declarations require separate private runner roots")
        if (
            journal in journals
            or journal + ".owner" in journals
            or journal.removesuffix(".owner") in journals
        ):
            raise ValidationError("Coding declarations require separate journal paths")
        names.add(entry["name"])
        roots.append(root)
        journals.add(journal)
    if set(roots) & journals or set(roots) & {path + ".owner" for path in journals}:
        raise ValidationError("Coding root and journal resources cannot share a path")
    return entries


def validate(config):
    _entries(config)


def _check_paths(config):
    """Check filesystem admission before journal acquisition; never run Docker."""
    root, executable = Path(config["runner_root"]), Path(config["docker_executable"])
    try:
        valid = (
            root.is_dir()
            and not root.is_symlink()
            and root.stat().st_uid == os.getuid()
            and stat.S_IMODE(root.stat().st_mode) == 0o700
            and executable.is_file()
            and os.access(executable, os.X_OK)
        )
    except OSError:
        valid = False
    if not valid:
        raise ValidationError("Coding assembly requires a private root and executable Docker")
    return str(root.resolve(strict=True))


async def build(config, context):
    from .codex_runner import CodexCodingRunner
    from .runner_journal import RunnerJournal

    entries = _entries(config)
    roots = []
    for entry in entries:
        root = _check_paths(entry)
        if any(
            root == other or root.startswith(other + "/") or other.startswith(root + "/")
            for other in roots
        ):
            raise ValidationError("Coding runner physical roots must remain separate")
        roots.append(root)
    registry = ToolRegistry()
    for entry in entries:
        journal = context.own(
            RunnerJournal(entry["journal_path"], identity=entry["fixed_dependencies"])
        )
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
            registry,
            runner,
            name=entry["name"],
            description=entry["description"],
            cost=entry["cost"],
        )
    return registry


def validate_binding(config):
    if type(config) is not dict or set(config) != {"name"}:
        raise ValidationError("Runner binding requires an existing registered Coding tool name")
    _text(config["name"], "Runner bound tool name", limit=128)


def binding(config, context):
    validate_binding(config)
    if not isinstance(context.tools, ToolRegistry):
        raise ValidationError("Runner binding requires the original registered tools")
    handler = registered_coding_tool(context.tools.get(config["name"]))
    if handler is None:
        raise ValidationError("Runner binding requires an explicitly registered Coding tool")
    return handler.runner


def preflight_coding_references(profile):
    tools = profile.components.get("tools")
    names = (
        {entry["name"] for entry in _entries(tools["config"])}
        if tools is not None and tools["adapter"] == "codex-coding"
        else None
    )
    for declaration in profile.binding_components or ():
        component = declaration["component"]
        if declaration["role"] != "runner" or component["adapter"] != "registered-tool":
            continue
        validate_binding(component["config"])
        if tools is None or (names is not None and component["config"]["name"] not in names):
            raise ValidationError("Runner reference requires the declared original Coding tool")


def register_coding_factories(registry):
    registry.register_async("tools", "codex-coding", build, validator=validate)
    registry.register("runner", "registered-tool", binding, validator=validate_binding)
