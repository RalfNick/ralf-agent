"""Root admission obligations owned by the original Local execution authority."""

import copy
import inspect

from .errors import DefinitionMismatch, ValidationError
from .governance import DeploymentAdmissionPolicy
from .ports import is_sync_callable
from .types import digest

METHODS = (
    "local_capacity_policy",
    "prepare_local_capacity",
    "local_capacity_acquire",
    "local_capacity_release",
    "local_capacity_holders",
)


def registration(store):
    from .task_controls import _binding

    version = getattr(store, "local_admission_version", None)
    if version is None:
        return None
    if (
        type(version) is not int
        or version != 1
        or any(not is_sync_callable(getattr(store, name, None)) for name in METHODS)
    ):
        raise ValidationError("Local admission requires completed optional Store operations")
    return store, store.backend_id, {name: _binding(getattr(store, name)) for name in METHODS}


def check_store(engine):
    from .binding_artifacts import _same_binding
    from .node_coding_projection import original_engine

    engine = original_engine(engine)
    current, original = registration(engine.store), engine._admission_store_pin
    if (
        current is None
        or original is None
        or current[0] is not original[0]
        or current[1] != original[1]
    ):
        raise DefinitionMismatch("Original admission Store capability changed")
    if any(not _same_binding(current[2][name], original[2][name]) for name in METHODS):
        raise DefinitionMismatch("Original admission Store operations changed")


def _call(engine, method, *args):
    from .node_coding_projection import original_engine

    engine = original_engine(engine)
    check_store(engine)
    value = getattr(engine.store, method)(*args)
    if inspect.isawaitable(value) or inspect.isgenerator(value) or inspect.isasyncgen(value):
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise ValidationError("Admission Store operations must complete synchronously")
    check_store(engine)
    return value


def _policy(engine):
    value = _call(engine, "local_capacity_policy")
    if value is None:
        return None
    if type(value) is not dict or DeploymentAdmissionPolicy.from_identity(value).identity != value:
        raise DefinitionMismatch("Stored deployment admission identity is incomplete")
    return copy.deepcopy(value)


def policy_identity(engine):
    from .node_coding_projection import original_engine

    engine = original_engine(engine)
    if engine.admission_policy is not engine._admission_policy_pin:
        raise DefinitionMismatch("Original deployment admission policy changed")
    value = None if engine.admission_policy is None else engine.admission_policy.identity
    if value != engine._admission_policy_identity:
        raise DefinitionMismatch("Original deployment admission identity changed")
    if engine._admission_store_pin is not None and _policy(engine) != value:
        raise DefinitionMismatch("Deployment policy must match its original stored identity")
    return copy.deepcopy(value)


def initialize(engine):
    if engine._admission_store_pin is None:
        return
    stored = _policy(engine)
    selected = engine._admission_policy_identity
    if selected is None:
        if stored is not None:
            raise DefinitionMismatch("Configured deployment requires its original admission policy")
        return
    if stored is not None and stored != selected:
        raise DefinitionMismatch("Deployment admission policy cannot be replaced")
    with engine.store.transaction():
        if _call(engine, "prepare_local_capacity", copy.deepcopy(selected)) is not None:
            raise ValidationError("Admission preparation must complete with None")
        if _policy(engine) != selected:
            raise DefinitionMismatch("Admission preparation did not fix its original policy")


def publish(engine, manifest, run=None):
    if run is not None and "local_admission" not in run:
        manifest.pop("local_admission_protocol", None)
        manifest.pop("admission_policy", None)
        return manifest
    selected = policy_identity(engine)
    if selected is not None:
        manifest.update(local_admission_protocol=1, admission_policy=selected)
    return manifest


def root_id(engine, run, *, pending=False):
    seen = set()
    while run.get("parent_call") is not None:
        if run["id"] in seen or len(seen) >= 16:
            raise DefinitionMismatch("Admission parent ownership is cyclic or unbounded")
        seen.add(run["id"])
        parent = engine._authorized(run["parent_call"]["parent_id"])
        if (
            not pending
            and run.get("parent_id") is not None
            and engine.parent_run_id(run["id"]) != parent["id"]
        ):
            raise DefinitionMismatch("Admission parent ownership differs")
        run = parent
        pending = False
    return run["id"]


def _holders(engine, *, pending=None):
    value = _call(engine, "local_capacity_holders", engine.scope)
    if (
        type(value) is not tuple
        or len(value) > 10000
        or any(type(item) is not str or not item.strip() for item in value)
        or len(value) != len(set(value))
    ):
        raise ValidationError("Admission holders must be a completed bounded unique tuple")
    # The optional read never grants permission to disclose a foreign locator.
    for run_id in value:
        if run_id != pending:
            engine._authorized(run_id)
    return value


def accept(engine, data):
    selected = policy_identity(engine)
    if selected is None:
        return
    refresh(engine)
    root = root_id(engine, data, pending=True)
    if root == data["id"]:
        if _call(engine, "local_capacity_acquire", engine.scope, root) is not None:
            raise ValidationError("Admission acquire must complete with None")
    if root not in _holders(engine, pending=data["id"] if root == data["id"] else None):
        raise DefinitionMismatch("Original root admission is unavailable")
    data["local_admission"] = {"version": 1, "root_run_id": root}
    data["local_admission_digest"] = digest(data["local_admission"])
    publish(engine, data["manifest"], data)
    data["release_digest"] = digest(
        {"definition": data["definition"], "manifest": data["manifest"]}
    )


def validate(engine, run):
    from .node_coding_projection import original_engine

    if original_engine(engine) is not engine:
        return
    selected = policy_identity(engine)
    binding = run.get("local_admission")
    if binding is None:
        if run["manifest"].get("local_admission_protocol") is not None:
            raise DefinitionMismatch("Original admission binding is missing")
        return
    if (
        type(binding) is not dict
        or set(binding) != {"version", "root_run_id"}
        or type(binding["version"]) is not int
        or binding["version"] != 1
        or run.get("local_admission_digest") != digest(binding)
        or selected is None
        or run["manifest"].get("local_admission_protocol") != 1
        or run["manifest"].get("admission_policy") != selected
        or binding["root_run_id"] != root_id(engine, run)
    ):
        raise DefinitionMismatch("Original deployment admission differs")
    if run["state"] not in {"succeeded", "failed", "cancelled"} and binding[
        "root_run_id"
    ] not in _holders(engine):
        raise DefinitionMismatch("Active Run lost its original root admission")


def _tree(engine, root):
    todo, members = [root], {}
    while todo:
        run_id = todo.pop()
        if run_id in members or len(members) >= 4096:
            raise DefinitionMismatch("Admission tree is cyclic or exceeds original bound")
        run = engine._authorized(run_id)
        members[run_id] = run
        for child in run.get("orchestration", {}).get("children", []):
            if engine.parent_run_id(child["run_id"]) != run_id:
                raise DefinitionMismatch("Admission child lost its original owner")
            todo.append(child["run_id"])
    return members


def release(engine, run_id):
    from .capacity_rules import capacity_obligations
    from .node_coding_projection import original_engine

    owner = original_engine(engine)
    if owner is not engine:
        return False
    if engine._admission_policy_identity is None or engine._lifecycle != "open":
        return False
    policy_identity(engine)
    root = root_id(engine, engine._authorized(run_id))
    with engine.store.transaction():
        if root not in _holders(engine):
            return False
        members = _tree(engine, root)
        if any(capacity_obligations(record) for record in members.values()):
            return False
        if any(
            key in engine._active or key in engine._drive_users or engine._operation_active(key)
            for key in members
        ):
            return False
        outcome = _call(engine, "local_capacity_release", engine.scope, root)
        if type(outcome) is not bool:
            raise ValidationError("Admission release must complete with a bool")
        remaining = root in _holders(engine)
        if remaining == outcome:
            raise DefinitionMismatch("Admission release receipt disagrees with original ownership")
        if outcome:
            engine._admission_failures.pop(root, None)
            engine.store.emit(root, "deployment_admission_released", {})
        return outcome


def refresh(engine):
    if engine._admission_policy_identity is None:
        return
    policy_identity(engine)
    for run_id in _holders(engine):
        release(engine, run_id)


def diagnostic(engine, run):
    from .errors import RalfError

    root = root_id(engine, run)
    code = engine._admission_failures.get(root) or engine._admission_failures.get(run["id"])
    try:
        policy_identity(engine)
        held = root in _holders(engine)
    except RalfError as exc:
        held, code = None, exc.code
    except Exception:
        held, code = None, "admission_host_failed"
    return {
        "root_run_id": root,
        "policy": copy.deepcopy(engine._admission_policy_identity),
        "held": held,
        "host_failure": code,
    }


def try_release(engine, run_id):
    from .errors import RalfError
    from .node_coding_projection import original_engine

    if original_engine(engine) is not engine or engine._admission_policy_identity is None:
        return
    try:
        run = engine._authorized(run_id)
        if (
            run["state"] in {"failed", "cancelled"}
            and run_id not in engine._active
            and run_id not in engine._drive_users
            and not engine._operation_active(run_id)
        ):
            from .local_parent_completion import recover_terminal_completion

            recover_terminal_completion(engine, run_id)
        release(engine, run_id)
    except RalfError as exc:
        engine._admission_failures[run_id] = exc.code
    except Exception:
        engine._admission_failures[run_id] = "admission_host_failed"
