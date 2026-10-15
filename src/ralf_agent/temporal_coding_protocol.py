"""Explicit Temporal Coding publication and fixed original resource contracts."""

from .errors import DefinitionMismatch, ValidationError
from .types import digest

RUNNER_METHODS = (
    "__init__",
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
    "_make_transport",
    "_acquire_capacity",
    "_release_capacity",
    "_release_unprepared_capacity",
    "_wait_owner",
    "_check_capacity",
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

# Physical implementations are discovered only on a Worker. These are fixed,
# reviewed inventories, never reflection over whatever a deployment exports.
CAPACITY_FUNCTIONS = ("_require", "_hex", "_pin", "_private_file", "_pairs")
CAPACITY_METHODS = (
    "__init__",
    "_check_root",
    "_check_lock",
    "_validate_state",
    "_read",
    "_write",
    "_drop_lock",
    "try_acquire",
    "_owned",
    "mark_native_intent",
    "release",
    "close",
)
CAPACITY_PROPERTIES = ("claim",)
CAPACITY_CONSTANTS = ("_LOCK", "_RECORD", "_LIMIT")
ENVIRONMENT_METHODS = (
    "__init__",
    "prepare",
    "inspect",
    "stop",
    "stop_existing",
    "observe_namespace_absence",
    "observe_create_not_dispatched",
    "_observe_create_not_dispatched",
    "_submit_supervised_create",
    "_control_supervised_create",
    "_observe_namespace_absence",
    "_namespace_query",
    "aclose",
    "_owned",
    "_serialized_operation",
    "_check_root",
    "_acquire",
    "_read_metadata",
    "_write_metadata",
    "_provision",
    "_check_files",
    "_labels",
    "_create_argv",
    "_prepare",
    "_prepare_legacy_locator",
    "_create_operation_digest",
    "_validate_create_operation",
    "_create_candidates",
    "_submit_create",
    "_recover_create",
    "_inspect_raw",
    "_validate_container",
    "_inspect",
    "_stop",
    "_stop_existing",
    "_validate_retirement",
    "_container_present",
    "_record_fenced",
    "_close",
    "_cli",
)
ENVIRONMENT_PROPERTIES = ("identity", "transport_env", "active_operations", "transport_argv")
ENVIRONMENT_FUNCTIONS = ("_canonical", "_digest", "_require", "_pin")
ENVIRONMENT_CONSTANTS = (
    "_SECCOMP_DIGEST",
    "_COMMAND",
    "_ENTRYPOINT",
    "_IMAGE_ENV",
    "_REGISTRY",
    "_REGISTRY_OPTIONS",
    "_CAP",
    "_ZERO_TIME",
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
    "create_supervision": set(),
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
        *ENVIRONMENT_METHODS,
        *ENVIRONMENT_PROPERTIES,
        *("module." + name for name in ENVIRONMENT_FUNCTIONS),
        *ENVIRONMENT_CONSTANTS,
    },
    "capacity": {
        *CAPACITY_FUNCTIONS,
        *("RootCapacity." + name for name in CAPACITY_METHODS),
        *("RootCapacity." + name + ".fget" for name in CAPACITY_PROPERTIES),
        *CAPACITY_CONSTANTS,
    },
    "io_inventory": {
        "implementation",
        "_physical_digest",
        "RUNNER_METHODS",
        "CAPACITY_FUNCTIONS",
        "CAPACITY_METHODS",
        "CAPACITY_PROPERTIES",
        "CAPACITY_CONSTANTS",
        "ENVIRONMENT_METHODS",
        "ENVIRONMENT_PROPERTIES",
        "ENVIRONMENT_FUNCTIONS",
        "ENVIRONMENT_CONSTANTS",
    },
    "runner_support": {
        "_capacity_implementation",
        "_environment_implementation",
        "CodexCodingRunner.__init__",
        "policy_value",
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
    from .coding_create_inventory import inventory_fields, validate_inventory
    from .component_fingerprint import executable_digest
    from .session_types import sha

    if type(value) is not dict or set(value) != set(IMPLEMENTATION_FIELDS):
        raise DefinitionMismatch("Coding requires complete fixed implementation metadata")
    for group, methods in IMPLEMENTATION_FIELDS.items():
        if group == "create_supervision":
            validate_inventory(value[group])
            if value[group]["no_create_rules"] != {
                name: executable_digest(getattr(rules, name))
                for name in inventory_fields()["no_create_rules"]
            } or any(
                value[group]["inventory"][name] != executable_digest(function)
                for name, function in (
                    ("inventory_fields", inventory_fields),
                    ("validate_inventory", validate_inventory),
                )
            ):
                raise DefinitionMismatch("Original pure CREATE supervision rules changed")
            continue
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


def _physical_digest(owner, name):
    """Fingerprint a listed callable/getter without constructing or invoking it."""
    from .component_fingerprint import executable_digest

    value = getattr(owner, name)
    return executable_digest(value.fget if isinstance(value, property) else value)


def implementation():
    from . import codex_environment as environment
    from . import codex_runner as runner
    from . import codex_runner_capacity as capacity
    from . import coding_execution_rules as rules
    from . import coding_resource_fingerprint as policy
    from . import postgres_coding_resources as resources
    from . import temporal_coding_runtime as runtime
    from . import temporal_coding_state as state
    from . import temporal_tool_execution_activities as callbacks
    from . import temporal_tool_execution_runtime as tools
    from .codex_environment import DockerCodingEnvironment
    from .codex_runner_capacity import RootCapacity
    from .coding_create_inventory import inventory
    from .component_fingerprint import executable_digest
    from .temporal_activities import TemporalRuntime, registered_activities
    from .temporal_coding_authority import TemporalCodingAuthority

    return {
        "create_supervision": inventory(),
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
            **{
                name: _physical_digest(DockerCodingEnvironment, name)
                for name in (*ENVIRONMENT_METHODS, *ENVIRONMENT_PROPERTIES)
            },
            **{
                "module." + name: _physical_digest(environment, name)
                for name in ENVIRONMENT_FUNCTIONS
            },
            **{
                name: digest(policy.policy_value(getattr(environment, name)))
                for name in ENVIRONMENT_CONSTANTS
            },
        },
        "capacity": {
            **{name: _physical_digest(capacity, name) for name in CAPACITY_FUNCTIONS},
            **{
                "RootCapacity." + name: _physical_digest(RootCapacity, name)
                for name in CAPACITY_METHODS
            },
            **{
                "RootCapacity." + name + ".fget": _physical_digest(RootCapacity, name)
                for name in CAPACITY_PROPERTIES
            },
            **{
                name: digest(policy.policy_value(getattr(capacity, name)))
                for name in CAPACITY_CONSTANTS
            },
        },
        "runner_support": {
            "_capacity_implementation": _physical_digest(runner, "_capacity_implementation"),
            "_environment_implementation": _physical_digest(runner, "_environment_implementation"),
            "CodexCodingRunner.__init__": _physical_digest(runner.CodexCodingRunner, "__init__"),
            "policy_value": _physical_digest(policy, "policy_value"),
        },
        "io_inventory": {
            "implementation": executable_digest(implementation),
            "_physical_digest": executable_digest(_physical_digest),
            **{
                name: digest(policy.policy_value(value))
                for name, value in {
                    "RUNNER_METHODS": RUNNER_METHODS,
                    "CAPACITY_FUNCTIONS": CAPACITY_FUNCTIONS,
                    "CAPACITY_METHODS": CAPACITY_METHODS,
                    "CAPACITY_PROPERTIES": CAPACITY_PROPERTIES,
                    "CAPACITY_CONSTANTS": CAPACITY_CONSTANTS,
                    "ENVIRONMENT_METHODS": ENVIRONMENT_METHODS,
                    "ENVIRONMENT_PROPERTIES": ENVIRONMENT_PROPERTIES,
                    "ENVIRONMENT_FUNCTIONS": ENVIRONMENT_FUNCTIONS,
                    "ENVIRONMENT_CONSTANTS": ENVIRONMENT_CONSTANTS,
                }.items()
            },
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
    from .codex_connected_runner import ConnectedCodexCodingRunner
    from .codex_runner import CodexCodingRunner
    from .coding_resource_fingerprint import policy_value
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
            type(runner) not in (CodexCodingRunner, ConnectedCodexCodingRunner)
            or type(runner._journal) is not PostgresRunnerJournal
            or runner._journal._effect is not runtime.journal
            or runner.identity.get("configuration_readonly") is not True
        ):
            raise ValidationError(
                "Temporal Coding requires the exact shared PostgreSQL journal and concrete Runner"
            )
        root_check = type(runner)._check_root
        root_check(runner)
        if root_check is not CodexCodingRunner._check_root:
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
    metadata = implementation()
    # Independently compare the inventory generator: a cached old inventory
    # must not conceal a replaced physical body or a narrowed discovery list.
    expected_inventory = {
        "implementation": executable_digest(implementation),
        "_physical_digest": executable_digest(_physical_digest),
        **{
            name: digest(policy_value(value))
            for name, value in {
                "RUNNER_METHODS": RUNNER_METHODS,
                "CAPACITY_FUNCTIONS": CAPACITY_FUNCTIONS,
                "CAPACITY_METHODS": CAPACITY_METHODS,
                "CAPACITY_PROPERTIES": CAPACITY_PROPERTIES,
                "CAPACITY_CONSTANTS": CAPACITY_CONSTANTS,
                "ENVIRONMENT_METHODS": ENVIRONMENT_METHODS,
                "ENVIRONMENT_PROPERTIES": ENVIRONMENT_PROPERTIES,
                "ENVIRONMENT_FUNCTIONS": ENVIRONMENT_FUNCTIONS,
                "ENVIRONMENT_CONSTANTS": ENVIRONMENT_CONSTANTS,
            }.items()
        },
    }
    if type(metadata) is not dict or metadata.get("io_inventory") != expected_inventory:
        raise DefinitionMismatch("Coding physical implementation inventory changed")
    return {"version": 6, "tools": result, "implementation": metadata}


def validate_protocol(manifest):
    from .temporal_coding_composition_protocol import validate_protocol as validate_composition

    if manifest.get("binding_protocol") in (20, 21):
        raise DefinitionMismatch("Temporal Coding 20/21 requires the immutable dev112 Worker")
    validate_composition(manifest)
    if not enabled(manifest):
        if manifest.get("binding_protocol") in (11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23):
            raise DefinitionMismatch("Temporal Coding publication is missing")
        return
    value = manifest["coding_execution_protocol"]
    if (
        manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"] not in (22, 23)
        or manifest.get("dispatch_admission") != "history-1"
        or "tool_execution_protocol" not in manifest
        or type(value) is not dict
        or set(value) != {"version", "tools", "implementation"}
        or type(value["version"]) is not int
        or value["version"] != 6
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


def publish(manifest, runtime, *, _validate=True, _copy=True):
    from .temporal_state import detached
    from .types import canonical

    if not _copy:
        canonical(manifest)
    result = detached(manifest) if _copy else manifest
    result.update(
        kernel="temporal-3",
        binding_protocol=22,
        dispatch_admission="history-1",
        coding_execution_protocol=registration(runtime),
    )
    if _validate:
        validate_protocol(result)
    return result


def check(runtime, manifest):
    validate_protocol(manifest)
    if not getattr(runtime, "coding_execution", False) or digest(registration(runtime)) != digest(
        manifest["coding_execution_protocol"]
    ):
        raise DefinitionMismatch("Temporal Coding original resources changed")
