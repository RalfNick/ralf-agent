"""Explicit nonsecret connected declarations on original Local/PG ownership."""

from .codex_model_connection import CodexModelConnection
from .coding_factories import _check_paths, _entries
from .delegated_coding import register_coding_tool
from .errors import ValidationError
from .tools import ToolRegistry


def entries(config, *, temporal=False):
    if type(config) is not dict:
        raise ValidationError("Connected Coding requires explicit declarations")
    values = config.get("tools", [config])
    if "tools" in config and (
        set(config) != {"tools"} or type(values) is not list or not 1 <= len(values) <= 16
    ):
        raise ValidationError("Connected Coding requires one to 16 explicit tools")
    stripped = []
    for entry in values:
        if type(entry) is not dict or "connection" not in entry:
            raise ValidationError("Connected Coding requires a nonsecret model connection")
        CodexModelConnection.from_dict(entry["connection"])
        stripped.append({name: value for name, value in entry.items() if name != "connection"})
    if temporal:
        from .temporal_coding_factories import entries as postgres_entries

        postgres_entries({"tools": stripped})
    else:
        _entries({"tools": stripped})
    return values


def validate(config):
    entries(config)


def validate_postgres(config):
    entries(config, temporal=True)


def _roots(values):
    roots = []
    for entry in values:
        root = _check_paths(entry)
        if any(
            root == other or root.startswith(other + "/") or other.startswith(root + "/")
            for other in roots
        ):
            raise ValidationError("Connected Coding physical roots must remain separate")
        roots.append(root)


def _register(values, context, journal_factory):
    from .codex_connected_runner import ConnectedCodexCodingRunner

    tools = ToolRegistry()
    for entry in values:
        runner = context.own_async(
            ConnectedCodexCodingRunner(
                entry["runner_root"],
                connection=CodexModelConnection.from_dict(entry["connection"]),
                journal=journal_factory(entry),
                docker_executable=entry["docker_executable"],
                docker_host=entry["docker_host"],
                request_timeout=entry["request_timeout"],
            )
        )
        register_coding_tool(
            tools, runner, name=entry["name"], description=entry["description"], cost=entry["cost"]
        )
    return tools


async def build(config, context):
    from .runner_journal import RunnerJournal

    values = entries(config)
    _roots(values)
    return _register(
        values,
        context,
        lambda entry: context.own(
            RunnerJournal(entry["journal_path"], identity=entry["fixed_dependencies"])
        ),
    )


async def build_postgres(config, context):
    from .postgres_runner_journal import PostgresRunnerJournal
    from .temporal_journal import PostgresEffectJournal
    from .types import canonical

    values = entries(config, temporal=True)
    effect = getattr(context, "effect_journal", None)
    if (
        getattr(context, "coding_execution", False) is not True
        or type(effect) is not PostgresEffectJournal
    ):
        raise ValidationError("Connected Temporal Coding requires the original effect owner")
    _roots(values)
    journal = context.own_async(
        PostgresRunnerJournal(effect, identity=values[0]["fixed_dependencies"])
    )
    await journal.initialize()
    if journal._effect is not effect or canonical(journal._effect.identity) != canonical(
        effect.identity
    ):
        raise ValidationError("Connected Coding journal changed its original effect owner")
    return _register(values, context, lambda entry: journal)


def register_local(registry):
    registry.register_async("tools", "codex-coding-connected", build, validator=validate)


def register_postgres(registry):
    registry.register_async(
        "tools", "codex-coding-connected-postgres", build_postgres, validator=validate_postgres
    )
