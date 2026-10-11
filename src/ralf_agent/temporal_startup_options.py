"""Pure basic startup contracts; rich SDK objects stay borrowed and delegated."""

import inspect
import math
from datetime import timedelta

from .errors import DefinitionMismatch, ValidationError
from .types import digest

ENGINE_FIELDS = frozenset({"activity_timeout", "drive_timeout"})
OWNED_WORKER_FIELDS = frozenset(
    {"client", "task_queue", "runtime", "activity_owner", "workflows", "activities"}
)
SLOTS = frozenset(
    {
        "max_concurrent_workflow_tasks",
        "max_concurrent_activities",
        "max_concurrent_local_activities",
        "max_concurrent_nexus_tasks",
    }
)
NULLABLE_INTEGERS = SLOTS | {
    "max_concurrent_workflow_task_polls",
    "max_concurrent_activity_task_polls",
}
BOOLEANS = frozenset(
    {
        "no_remote_activities",
        "debug_mode",
        "disable_eager_activity_execution",
        "use_worker_versioning",
        "disable_safe_workflow_eviction",
        "disable_payload_error_limit",
    }
)
RATES = frozenset({"max_activities_per_second", "max_task_queue_activities_per_second"})
DURATIONS = frozenset(
    {
        "sticky_queue_schedule_to_start_timeout",
        "max_heartbeat_throttle_interval",
        "default_heartbeat_throttle_interval",
        "graceful_shutdown_timeout",
    }
)


def validate_seconds(value, *, strict=False):
    numeric = type(value) in (int, float) if strict else isinstance(value, (int, float))
    if not numeric or (not strict and isinstance(value, bool)) or not 0 < value <= 86400:
        raise ValidationError("Temporal timeouts must be positive seconds up to 86400")


def _options(value):
    if value is None:
        return {}
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValidationError("Startup options require explicit dictionaries with string fields")
    return dict(value)


def validate_engine_options(options):
    options = _options(options)
    if set(options) - ENGINE_FIELDS:
        raise ValidationError("Unknown or Host-owned Engine startup option")
    for value in options.values():
        validate_seconds(value, strict=True)
    return options


def _worker_parameters():
    from .temporal import _sdk

    _sdk()
    from temporalio.worker import Worker

    return inspect.signature(Worker).parameters


def _rate(value, *, allow_zero=False):
    if type(value) not in (int, float) or value < 0 or (not allow_zero and value == 0):
        raise ValidationError("Worker rates and ratios require finite numbers within field bounds")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValidationError("Worker rates and ratios require finite numbers within field bounds")


def validate_worker_options(options, *, releases):
    options = _options(options)
    if set(options) & OWNED_WORKER_FIELDS:
        raise ValidationError("Worker startup cannot override original Host-owned registrations")
    for key, value in options.items():
        if key in NULLABLE_INTEGERS and value is not None:
            if type(value) is not int or value <= 0:
                raise ValidationError("Worker capacities and poll counts require positive integers")
        elif key in {
            "max_cached_workflows",
            "max_eager_activity_reservations_per_workflow_task",
            "max_workflow_task_external_storage_concurrency",
        }:
            minimum = 0 if key == "max_cached_workflows" else 1
            if type(value) is not int or value < minimum:
                raise ValidationError(
                    "Worker capacity requires a valid nonnegative/positive integer"
                )
        elif key in BOOLEANS and type(value) is not bool:
            raise ValidationError("Worker switches require explicit booleans")
        elif key in RATES:
            if value is not None:
                _rate(value, allow_zero=key == "max_task_queue_activities_per_second")
        elif key == "nonsticky_to_sticky_poll_ratio":
            _rate(value, allow_zero=True)
        elif key == "identity" and value is not None and type(value) is not str:
            raise ValidationError("Worker identity requires a string or None")
        elif key in DURATIONS:
            if type(value) is not timedelta or value.total_seconds() < 0:
                raise ValidationError("Worker duration requires a nonnegative timedelta")
    parameters = _worker_parameters()
    if set(options) - set(parameters):
        raise ValidationError("Unknown Worker startup option for the installed Temporal SDK")
    if options.get("tuner") is not None and any(options.get(key) is not None for key in SLOTS):
        raise ValidationError("Worker tuner cannot combine with explicit slot capacities")
    default = parameters.get("max_cached_workflows") if hasattr(parameters, "get") else None
    cached = options.get("max_cached_workflows", default.default if default is not None else 1000)
    if cached:
        for key in ("max_concurrent_workflow_tasks", "max_concurrent_workflow_task_polls"):
            if options.get(key) is not None and options[key] < 2:
                raise ValidationError("Cached workflows require at least two workflow slots/polls")
    if "build_id" in options:
        if (
            type(options["build_id"]) is not str
            or not releases
            or any(options["build_id"] != digest(release) for release in releases)
        ):
            raise DefinitionMismatch("Worker build identity must match every original Host release")
    return options
