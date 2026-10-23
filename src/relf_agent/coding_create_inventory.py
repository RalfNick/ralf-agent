"""Explicit CREATE supervision code/policy schema; discover I/O only on Workers."""

from .errors import DefinitionMismatch


def inventory_fields():
    """Fixed pure schema safe for History; no discovery or physical imports."""
    return {
        "process_functions": (
            "_default_child_policy",
            "_darwin_group_members",
            "signal_unreaped_group",
        ),
        "process_methods": ("__init__", "register", "_events", "exited", "close"),
        "process_policy": ("_GROUP_LIMIT", "_PGRP_ONLY"),
        "no_create_rules": (
            "_create_not_dispatched_facts",
            "_create_not_dispatched_digests",
            "_create_digest",
            "validate_create_not_dispatched",
            "adopt_create_not_dispatched",
            "create_not_dispatched_projection",
            "validate_create_not_dispatched_projection",
        ),
        "journal_functions": (
            "require",
            "hex_value",
            "pin",
            "private_directory",
            "private_file",
            "pairs",
            "birth",
            "process_ended",
            "check_fd",
            "lock_released",
            "registration",
            "check_registration",
            "gate_message",
            "accepted_frame",
            "load_declaration",
        ),
        "journal_methods": ("__init__", "check", "read", "write"),
        "journal_policy": ("_MAX_RECORD", "_WRITERS"),
        "broker_functions": (
            "_peer",
            "_socket_pin",
            "_request",
            "_serve",
            "_receipt",
            "validate_receipt",
            "run_broker",
            "_spawn_argv",
            "main",
        ),
        "broker_methods": (
            "__init__",
            "create",
            "open",
            "launch",
            "start_once",
            "query",
            "drain",
            "abort",
            "close",
        ),
        "broker_properties": ("declaration",),
        "broker_policy": ("_PYTHON_ENV", "_RECEIPT_FIELDS", "_BOOTSTRAP"),
        "gate_functions": ("run_gate", "main"),
        "fingerprint": (
            "policy_value",
            "_constant",
            "_code",
            "_super_capture",
            "_function",
            "_plain_digest",
            "_cacheable_constant",
            "_cacheable_code",
            "_cache_helpers",
            "executable_digest",
        ),
        "inventory": (
            "inventory_fields",
            "validate_inventory",
            "_validate_aliases",
            "source_paths",
            "_source_digest",
            "source_inventory",
            "check_source_inventory",
            "inventory",
        ),
        "module_sources": (
            "__init__",
            "errors",
            "types",
            "component_fingerprint",
            "coding_resource_fingerprint",
            "coding_process_wait",
            "coding_execution_rules",
            "coding_create_inventory",
            "codex_create_journal",
            "codex_create_supervisor",
            "codex_create_gate",
        ),
    }


def validate_inventory(value):
    """Validate only the exact serialized SHA schema, never execute Worker code."""
    fields = inventory_fields()
    if type(value) is not dict or set(value) != set(fields):
        raise DefinitionMismatch("CREATE supervision inventory groups changed")
    for group, names in fields.items():
        values = value[group]
        if type(values) is not dict or set(values) != set(names):
            raise DefinitionMismatch("CREATE supervision inventory fields changed")
        if any(
            type(sha) is not str or len(sha) != 64 or set(sha) - set("0123456789abcdef")
            for sha in values.values()
        ):
            raise DefinitionMismatch(
                "CREATE supervision inventory requires complete implementation SHA"
            )


def _validate_aliases():
    """Worker-only exact roles; a rebound import is not its defining helper."""
    import subprocess

    from . import (
        codex_create_gate,
        codex_create_journal,
        codex_create_supervisor,
        coding_create_inventory,
        coding_execution_rules,
        coding_process_wait,
        coding_resource_fingerprint,
        component_fingerprint,
        errors,
        types,
    )

    for module, names in (
        (
            codex_create_supervisor,
            (
                "OperationJournal",
                "accepted_frame",
                "birth",
                "process_ended",
                "check_fd",
                "check_registration",
                "gate_message",
                "hex_value",
                "load_declaration",
                "lock_released",
                "pairs",
                "pin",
                "private_directory",
                "registration",
                "require",
            ),
        ),
        (
            codex_create_gate,
            (
                "OperationJournal",
                "accepted_frame",
                "check_fd",
                "gate_message",
                "load_declaration",
                "registration",
                "require",
            ),
        ),
    ):
        if any(getattr(module, name) is not getattr(codex_create_journal, name) for name in names):
            raise errors.DefinitionMismatch("Original CREATE supervision imported alias changed")
    roles = (
        (codex_create_supervisor.ChildExitMonitor, coding_process_wait.ChildExitMonitor),
        (codex_create_supervisor.signal_unreaped_group, coding_process_wait.signal_unreaped_group),
        (coding_process_wait.Popen, subprocess.Popen),
        (codex_create_supervisor.policy_value, coding_resource_fingerprint.policy_value),
        (codex_create_journal.policy_value, coding_resource_fingerprint.policy_value),
        (codex_create_supervisor.canonical, types.canonical),
        (codex_create_supervisor.digest, types.digest),
        (codex_create_journal.canonical, types.canonical),
        (codex_create_journal.digest, types.digest),
        (codex_create_supervisor.DefinitionMismatch, errors.DefinitionMismatch),
        (codex_create_supervisor.ExecutionHostFailed, errors.ExecutionHostFailed),
        (codex_create_supervisor.ValidationError, errors.ValidationError),
        (codex_create_journal.DefinitionMismatch, errors.DefinitionMismatch),
        (coding_execution_rules.canonical, types.canonical),
        (coding_execution_rules.digest, types.digest),
        (coding_execution_rules.AuthorizationDenied, errors.AuthorizationDenied),
        (coding_execution_rules.DefinitionMismatch, errors.DefinitionMismatch),
        (coding_execution_rules.ValidationError, errors.ValidationError),
        (coding_resource_fingerprint.canonical, types.canonical),
        (coding_resource_fingerprint.DefinitionMismatch, errors.DefinitionMismatch),
        (component_fingerprint.canonical, types.canonical),
        (component_fingerprint.digest, types.digest),
        (component_fingerprint.ValidationError, errors.ValidationError),
        (coding_create_inventory.DefinitionMismatch, errors.DefinitionMismatch),
    )
    if any(actual is not expected for actual, expected in roles):
        raise errors.DefinitionMismatch("Original CREATE supervision imported alias changed")


def source_paths():
    """Resolve only fixed product source filenames; Worker-side physical discovery."""
    from pathlib import Path

    package = Path(__file__).resolve(strict=True).parent
    return {name: str(package / (name + ".py")) for name in inventory_fields()["module_sources"]}


def _source_digest(path):
    """Hash a bounded original regular source without following a final alias."""
    import hashlib
    import os
    import stat
    from pathlib import Path

    path = Path(path)
    fd = None
    try:
        if str(path) != str(path.resolve(strict=True)):
            raise DefinitionMismatch("CREATE supervision source alias changed")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= 8 * 1024 * 1024
        ):
            raise DefinitionMismatch("CREATE supervision source is unavailable or unbounded")
        state = hashlib.sha256()
        length = 0
        while chunk := os.read(fd, 65536):
            length += len(chunk)
            if length > before.st_size:
                raise DefinitionMismatch("CREATE supervision source changed during read")
            state.update(chunk)
        after = os.fstat(fd)
        current = path.lstat()
        for actual in (after, current):
            if any(
                getattr(actual, key) != getattr(before, key)
                for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            ):
                raise DefinitionMismatch("CREATE supervision source changed during read")
        if length != before.st_size:
            raise DefinitionMismatch("CREATE supervision source read is incomplete")
        return state.hexdigest()
    except OSError:
        raise DefinitionMismatch("CREATE supervision source is unavailable") from None
    finally:
        if fd is not None:
            os.close(fd)


def source_inventory():
    return {name: _source_digest(path) for name, path in source_paths().items()}


def check_source_inventory(required_sources):
    """Recheck original source declarations before physical spawn/exec on Workers."""
    if (
        type(required_sources) is not dict
        or set(required_sources) != set(inventory_fields()["module_sources"])
        or any(
            type(sha) is not str or len(sha) != 64 or set(sha) - set("0123456789abcdef")
            for sha in required_sources.values()
        )
        or required_sources != source_inventory()
    ):
        raise DefinitionMismatch("Original CREATE supervision source declaration changed")


def inventory():
    """Worker-only fixed discovery; no reflection over exports or arbitrary classes."""
    from . import (
        codex_create_gate,
        codex_create_journal,
        codex_create_supervisor,
        coding_create_inventory,
        coding_execution_rules,
        coding_process_wait,
        coding_resource_fingerprint,
        component_fingerprint,
    )
    from .component_fingerprint import executable_digest
    from .types import digest

    _validate_aliases()
    fields = inventory_fields()
    result = {
        "process_functions": {
            name: executable_digest(getattr(coding_process_wait, name))
            for name in fields["process_functions"]
        },
        "process_methods": {
            name: executable_digest(getattr(coding_process_wait.ChildExitMonitor, name))
            for name in fields["process_methods"]
        },
        "process_policy": {
            name: digest(
                coding_resource_fingerprint.policy_value(getattr(coding_process_wait, name))
            )
            for name in fields["process_policy"]
        },
        "no_create_rules": {
            name: executable_digest(getattr(coding_execution_rules, name))
            for name in fields["no_create_rules"]
        },
        "journal_functions": {
            name: executable_digest(getattr(codex_create_journal, name))
            for name in fields["journal_functions"]
        },
        "journal_methods": {
            name: executable_digest(getattr(codex_create_journal.OperationJournal, name))
            for name in fields["journal_methods"]
        },
        "journal_policy": {
            name: digest(
                coding_resource_fingerprint.policy_value(getattr(codex_create_journal, name))
            )
            for name in fields["journal_policy"]
        },
        "broker_functions": {
            name: executable_digest(getattr(codex_create_supervisor, name))
            for name in fields["broker_functions"]
        },
        "broker_methods": {
            name: executable_digest(getattr(codex_create_supervisor.CreateSupervisor, name))
            for name in fields["broker_methods"]
        },
        "broker_properties": {
            name: executable_digest(getattr(codex_create_supervisor.CreateSupervisor, name).fget)
            for name in fields["broker_properties"]
        },
        "broker_policy": {
            name: digest(
                coding_resource_fingerprint.policy_value(getattr(codex_create_supervisor, name))
            )
            for name in fields["broker_policy"]
        },
        "gate_functions": {
            name: executable_digest(getattr(codex_create_gate, name))
            for name in fields["gate_functions"]
        },
        "fingerprint": {
            "policy_value": executable_digest(coding_resource_fingerprint.policy_value),
            **{
                name: executable_digest(getattr(component_fingerprint, name))
                for name in fields["fingerprint"]
                if name != "policy_value"
            },
        },
        "inventory": {
            name: executable_digest(getattr(coding_create_inventory, name))
            for name in fields["inventory"]
        },
        "module_sources": source_inventory(),
    }
    validate_inventory(result)
    return result
