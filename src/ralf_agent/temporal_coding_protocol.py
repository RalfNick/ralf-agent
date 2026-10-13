"""Explicit Temporal Coding publication and fixed original resource contracts."""

from .errors import DefinitionMismatch, ValidationError
from .types import digest

RUNNER_METHODS = (
    "execute_history",
    "reconcile_history",
    "stop_history",
    "_execute",
    "_retire",
    "_terminal",
    "_request",
    "_authority_method",
    "_authority_owned",
    "_journal_method",
    "_grant_owned",
    "_observe_owned",
    "_cancelled_owned",
    "_cleanup",
    "_check_root",
    "_location",
    "_environment",
    "_binding",
    "_history_authority",
    "_preflight",
    "_pump",
    "_accept_event",
    "_drain_closed_events",
    "_candidate",
    "_artifacts",
    "_settle",
    "_close_owner",
)
JOURNAL_METHODS = (
    "begin_resource",
    "resource_state",
    "record_resource",
    "pending_resources",
    "begin",
    "mark_thread_submitted",
    "record_thread",
    "mark_turn_submitted",
    "record_turn",
    "record_observation",
    "lookup",
    "request_cancel",
    "_ready",
    "_check",
    "_key",
    "_record",
    "_validate_effect",
    "_record_transaction",
    "_resource",
    "_validate_resource_effect",
    "_resource_capacity",
    "_save",
    "_submit",
    "_receipt",
    "_validate_metadata",
)


def enabled(manifest):
    return "coding_execution_protocol" in manifest


def owns(manifest, name):
    return enabled(manifest) and name in manifest["coding_execution_protocol"].get("tools", {})


HISTORY_METHODS = (
    "enabled",
    "selected",
    "prepare",
    "_record",
    "query",
    "grant",
    "adopt",
    "admit_stop",
    "request_stop",
    "stopped_action",
    "stopped",
    "refresh",
    "unknown",
    "next_stop",
    "accept_stop",
    "retry_stops",
    "accepts_result",
    "owner_stopped",
    "requests",
    "validate_owner",
    "admit_dispatch",
)
IMPLEMENTATION_FIELDS = {
    "glue": {
        "execute_tool",
        "_execute_tool",
        "registered_activities",
        "tracked_execution",
        "tracked_callbacks",
    },
    "runtime": {
        "callbacks",
        "execute",
        "stop",
        "close",
        "deployment",
        "process_start",
        "owner_proof",
        "original_owner_stopped",
        "_completed_received",
    },
    "resource_rules": {"new_resource", "receive_resource", "validate_resource", "_receipt"},
    "environment": {
        "observe_namespace_absence",
        "_observe_namespace_absence",
        "_namespace_query",
        "__init__",
        "_create_argv",
        "_validate_container",
    },
    "rules": {"grant", "adopt"},
    "history": set(HISTORY_METHODS),
    "authority": {
        "check",
        "resource_state",
        "cancelled",
        "authorize",
        "adopt",
        "validate_registration",
        "_call",
        "_state",
        "_check_pins",
    },
}


def validate_implementation(value):
    from . import coding_execution_rules as rules
    from . import temporal_coding_state as state
    from .component_fingerprint import executable_digest
    from .session_types import sha

    if type(value) is not dict or set(value) != set(IMPLEMENTATION_FIELDS):
        raise DefinitionMismatch("Coding requires complete fixed implementation metadata")
    for group, methods in IMPLEMENTATION_FIELDS.items():
        if type(value[group]) is not dict or set(value[group]) != methods:
            raise DefinitionMismatch("Coding implementation method metadata changed")
        for fingerprint in value[group].values():
            sha(fingerprint)
    if value["rules"] != {
        name: executable_digest(getattr(rules, name)) for name in ("grant", "adopt")
    } or value["history"] != {
        name: executable_digest(getattr(state, name)) for name in HISTORY_METHODS
    }:
        raise DefinitionMismatch("Original pure Coding History rules changed")


def implementation():
    from . import coding_execution_rules as rules
    from . import postgres_coding_resources as resources
    from . import temporal_coding_runtime as runtime
    from . import temporal_coding_state as state
    from . import temporal_tool_execution_activities as callbacks
    from . import temporal_tool_execution_runtime as tools
    from .codex_environment import DockerCodingEnvironment
    from .component_fingerprint import executable_digest
    from .temporal_activities import TemporalRuntime, registered_activities
    from .temporal_coding_authority import TemporalCodingAuthority

    return {
        "glue": {
            name: executable_digest(method)
            for name, method in {
                "execute_tool": TemporalRuntime.execute_tool,
                "_execute_tool": TemporalRuntime._execute_tool,
                "registered_activities": registered_activities,
                "tracked_execution": tools.execute,
                "tracked_callbacks": callbacks.callbacks,
            }.items()
        },
        "runtime": {
            name: executable_digest(getattr(runtime, name))
            for name in (
                "callbacks",
                "execute",
                "stop",
                "close",
                "deployment",
                "process_start",
                "owner_proof",
                "original_owner_stopped",
                "_completed_received",
            )
        },
        "resource_rules": {
            name: executable_digest(getattr(resources, name))
            for name in ("new_resource", "receive_resource", "validate_resource", "_receipt")
        },
        "environment": {
            name: executable_digest(getattr(DockerCodingEnvironment, name))
            for name in (
                "__init__",
                "_create_argv",
                "_validate_container",
                "observe_namespace_absence",
                "_observe_namespace_absence",
                "_namespace_query",
            )
        },
        "rules": {name: executable_digest(getattr(rules, name)) for name in ("grant", "adopt")},
        "history": {name: executable_digest(getattr(state, name)) for name in HISTORY_METHODS},
        "authority": {
            name: executable_digest(getattr(TemporalCodingAuthority, name))
            for name in (
                "check",
                "resource_state",
                "cancelled",
                "authorize",
                "adopt",
                "validate_registration",
                "_call",
                "_state",
                "_check_pins",
            )
        },
    }


def registration(runtime):
    from .codex_runner import CodexCodingRunner
    from .component_fingerprint import executable_digest
    from .delegated_coding import registered_coding_tool
    from .postgres_runner_journal import PostgresRunnerJournal
    from .temporal_tool_execution import ordinary

    result = {}
    for name in sorted(runtime.tools._tools):
        handler = registered_coding_tool(runtime.tools.get(name))
        if handler is None:
            continue
        runner = handler.runner
        if (
            type(runner) is not CodexCodingRunner
            or type(runner._journal) is not PostgresRunnerJournal
            or runner._journal._effect is not runtime.journal
            or runner.identity.get("configuration_readonly") is not True
        ):
            raise ValidationError(
                "Temporal Coding requires the exact shared PostgreSQL journal and concrete Runner"
            )
        CodexCodingRunner._check_root(runner)
        runner._journal._ready()
        result[name] = {
            "runner": handler.identity,
            "journal": ordinary(runner._journal.identity),
            "implementation": {
                name: executable_digest(getattr(runner, name)) for name in RUNNER_METHODS
            },
            "journal_implementation": {
                name: executable_digest(getattr(runner._journal, name)) for name in JOURNAL_METHODS
            },
        }
    if not result:
        raise ValidationError("Temporal Coding requires at least one registered original Runner")
    return {"version": 1, "tools": result, "implementation": implementation()}


def validate_protocol(manifest):
    if not enabled(manifest):
        if manifest.get("binding_protocol") == 11:
            raise DefinitionMismatch("Temporal Coding publication is missing")
        return
    value = manifest["coding_execution_protocol"]
    if (
        manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"] != 11
        or manifest.get("dispatch_admission") != "history-1"
        or "tool_execution_protocol" not in manifest
        or type(value) is not dict
        or set(value) != {"version", "tools", "implementation"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or type(value["tools"]) is not dict
        or not 1 <= len(value["tools"]) <= 16
        or type(value["implementation"]) is not dict
    ):
        raise DefinitionMismatch("Unsupported original Temporal Coding protocol")
    from .session_types import sha
    from .temporal_tool_execution import ordinary

    validate_implementation(value["implementation"])
    for name, resource in value["tools"].items():
        if (
            type(resource) is not dict
            or set(resource) != {"runner", "journal", "implementation", "journal_implementation"}
            or type(resource["implementation"]) is not dict
            or set(resource["implementation"]) != set(RUNNER_METHODS)
        ):
            raise DefinitionMismatch("Temporal Coding lost its fixed resource registration")
        marker = (
            manifest.get("tools", {}).get(name, {}).get("config", {}).get("delegated_runner", {})
        )
        if marker.get("runner") != resource["runner"] or marker.get("version") != 1:
            raise DefinitionMismatch("Temporal Coding registration differs from its actual Tool")
        ordinary(resource)
        if (
            type(resource["journal_implementation"]) is not dict
            or set(resource["journal_implementation"]) != set(JOURNAL_METHODS)
            or resource["journal"].get("effect_journal") != manifest.get("effect_journal")
        ):
            raise DefinitionMismatch(
                "Temporal Coding journal differs from its original effect owner"
            )
        for fingerprint in (
            *resource["implementation"].values(),
            *resource["journal_implementation"].values(),
        ):
            sha(fingerprint)


def publish(manifest, runtime):
    from .temporal_state import detached

    result = detached(manifest)
    result.update(
        kernel="temporal-3",
        binding_protocol=11,
        dispatch_admission="history-1",
        coding_execution_protocol=registration(runtime),
    )
    validate_protocol(result)
    return result


def check(runtime, manifest):
    validate_protocol(manifest)
    if not getattr(runtime, "coding_execution", False) or digest(registration(runtime)) != digest(
        manifest["coding_execution_protocol"]
    ):
        raise DefinitionMismatch("Temporal Coding original resources changed")
