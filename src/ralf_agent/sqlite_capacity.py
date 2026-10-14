"""Durable deployment claims under the original SQLite execution transactions."""

import json
import sqlite3
from dataclasses import asdict

from .capacity_rules import capacity_obligations
from .errors import AuthorizationDenied, CapacityExceeded, ValidationError
from .governance import DeploymentAdmissionPolicy
from .types import Scope, canonical, digest


def _writing(store):
    if store.readonly or not store.conn.in_transaction:
        raise ValidationError("Deployment admission requires its original execution transaction")


def _scope(scope):
    if type(scope) is not Scope:
        raise ValidationError("Deployment admission requires an original Scope")
    return scope.workspace, scope.principal


def _identifier(identifier):
    if type(identifier) is not str or not identifier.strip() or len(identifier) > 1024:
        raise ValidationError("Capacity requires a bounded original root identity")
    return identifier


def _identity(identity):
    policy = DeploymentAdmissionPolicy.from_identity(identity)
    if policy.identity != identity:
        raise ValidationError("Deployment admission requires the complete policy identity")
    return policy.identity


def policy(store):
    version = store.conn.execute(
        "SELECT value FROM metadata WHERE key='schema_version'"
    ).fetchone()[0]
    marker = store.conn.execute(
        "SELECT value FROM metadata WHERE key='local_admission_active'"
    ).fetchone()
    try:
        schema = int(version)
        table = store.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='deployment_admission_policy'"
        ).fetchone()
        if schema < 16:
            if marker is not None or table is not None:
                raise ValidationError("Original deployment admission activation changed")
            return None
        if marker is None or table is None:
            raise ValidationError("Original deployment admission activation is unavailable")
        rows = store.conn.execute("SELECT data FROM deployment_admission_policy").fetchall()
        if len(rows) != 1:
            raise ValidationError("Original deployment admission policy is unavailable")
        original = _identity(json.loads(rows[0][0]))
        if marker[0] != digest(original):
            raise ValidationError("Original deployment admission policy identity changed")
        return original
    except (ValueError, TypeError, KeyError, sqlite3.DatabaseError) as error:
        raise ValidationError("Original deployment admission policy is invalid") from error


def prepare(store, identity):
    _writing(store)
    identity = _identity(identity)
    original = policy(store)
    if original is not None:
        if original != identity:
            raise ValidationError("Original deployment admission policy cannot change")
        return
    store.prepare_native_history()
    store.create_session_admission()._prepare(16)
    store.conn.execute(
        "CREATE TABLE deployment_admission_policy (singleton INTEGER PRIMARY KEY CHECK(singleton=1),data TEXT NOT NULL)"
    )
    store.conn.execute(
        "CREATE TABLE deployment_root_claims (root_id TEXT PRIMARY KEY,workspace TEXT NOT NULL,principal TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('held','released')))"
    )
    store.conn.execute(
        "CREATE INDEX deployment_root_claims_scope ON deployment_root_claims(workspace,principal,state)"
    )
    store.conn.execute(
        "INSERT INTO deployment_admission_policy VALUES (1,?)", (canonical(identity),)
    )
    store.conn.execute(
        "INSERT INTO metadata VALUES ('local_admission_active',?)", (digest(identity),)
    )
    records = {row[0]: json.loads(row[1]) for row in store.conn.execute("SELECT id,data FROM runs")}
    roots, children = {}, {}
    for run in records.values():
        parent = _parent(run)
        if parent is not None:
            children.setdefault(parent, set()).add(run["id"])
        root = _root(store, run, records)
        roots[root["id"]] = root
    for identifier, root in roots.items():
        scope = Scope(**root["scope"])
        members = _tree(store, identifier, scope, records, children)
        if any(_member_pending(store, member) for member in members):
            store.conn.execute(
                "INSERT INTO deployment_root_claims VALUES (?,?,?,'held')",
                (identifier, *_scope(scope)),
            )


def acquire(store, scope, root_id):
    _writing(store)
    workspace, principal = _scope(scope)
    root_id = _identifier(root_id)
    current = policy(store)
    if current is None:
        raise ValidationError("Deployment admission policy has not been activated")
    existing = _claim(store, scope, root_id)
    if existing is not None:
        if existing["state"] == "held":
            return
        raise ValidationError("A released original root claim cannot be reopened")
    if store.conn.execute("SELECT 1 FROM runs WHERE id=?", (root_id,)).fetchone() is not None:
        raise ValidationError("An accepted original Run cannot acquire a new root identity")
    total = store.conn.execute(
        "SELECT COUNT(*) FROM deployment_root_claims WHERE state='held'"
    ).fetchone()[0]
    own = store.conn.execute(
        "SELECT COUNT(*) FROM deployment_root_claims WHERE workspace=? AND principal=? AND state='held'",
        (workspace, principal),
    ).fetchone()[0]
    if total >= current["max_active_root_runs"] or (
        current["max_active_root_runs_per_scope"] is not None
        and own >= current["max_active_root_runs_per_scope"]
    ):
        raise CapacityExceeded("Deployment admission capacity is unavailable")
    store.conn.execute(
        "INSERT INTO deployment_root_claims VALUES (?,?,?,'held')", (root_id, workspace, principal)
    )


def _claim(store, scope, root_id):
    workspace, principal = _scope(scope)
    row = store.conn.execute(
        "SELECT workspace,principal,state FROM deployment_root_claims WHERE root_id=?", (root_id,)
    ).fetchone()
    if row is not None and (row["workspace"], row["principal"]) != (workspace, principal):
        raise AuthorizationDenied("Capacity ownership belongs to another Scope")
    return row


def holders(store, scope):
    workspace, principal = _scope(scope)
    if policy(store) is None:
        return ()
    rows = store.conn.execute(
        "SELECT root_id FROM deployment_root_claims WHERE workspace=? AND principal=? AND state='held' ORDER BY root_id LIMIT 10001",
        (workspace, principal),
    ).fetchall()
    if len(rows) > 10000:
        raise ValidationError("Scoped capacity holder query exceeds its finite limit")
    return tuple(row[0] for row in rows)


def release(store, scope, root_id):
    _writing(store)
    _identifier(root_id)
    if policy(store) is None:
        raise ValidationError("Deployment admission policy has not been activated")
    claim = _claim(store, scope, root_id)
    if claim is None:
        raise ValidationError("Original root capacity claim is unavailable")
    if claim["state"] == "released":
        return True
    try:
        members = _tree(store, root_id, scope)
    except ValidationError:
        return False
    if any(_member_pending(store, member) for member in members):
        return False
    store.conn.execute(
        "UPDATE deployment_root_claims SET state='released' WHERE root_id=?", (root_id,)
    )
    return True


def _parent(run):
    binding = run.get("parent_call")
    parent = run.get("parent_id")
    if binding is None:
        if parent is not None:
            raise ValidationError("Original capacity parent ownership is incomplete")
        return None
    if type(binding) is not dict or binding.get("parent_id") != parent:
        raise ValidationError("Original capacity parent ownership changed")
    _identifier(parent)
    if binding.get("call_id") != run.get("call_id"):
        raise ValidationError("Original capacity call ownership changed")
    return parent


def _root(store, run, records=None):
    seen = set()
    scope = run["scope"]
    while True:
        if run["id"] in seen:
            raise ValidationError("Original capacity parent topology is cyclic")
        seen.add(run["id"])
        if run["scope"] != scope:
            raise AuthorizationDenied("Original capacity parent Scope differs")
        parent = _parent(run)
        if parent is None:
            return run
        try:
            run = records[parent] if records is not None else store.run(parent)
        except (KeyError, LookupError) as error:
            raise ValidationError("Original capacity parent is unavailable") from error


def _tree(store, root_id, scope, records=None, children_by_parent=None):
    expected = asdict(scope)
    pending, seen, result = [root_id], set(), []
    while pending:
        identifier = pending.pop()
        if identifier in seen:
            raise ValidationError("Original capacity child topology is not a tree")
        seen.add(identifier)
        try:
            run = records[identifier] if records is not None else store.run(identifier)
        except Exception as error:
            raise ValidationError("Original capacity member is unavailable") from error
        if run.get("scope") != expected:
            raise AuthorizationDenied("Original capacity child Scope differs")
        if identifier == root_id and _parent(run) is not None:
            raise ValidationError("Capacity root is an original child")
        result.append(run)
        children = run.get("orchestration", {}).get("children", [])
        if type(children) is not list:
            raise ValidationError("Original capacity children are malformed")
        linked = set()
        for link in children:
            if type(link) is not dict:
                raise ValidationError("Original capacity child link is malformed")
            child_id = _identifier(link.get("run_id"))
            try:
                child = records[child_id] if records is not None else store.run(child_id)
            except Exception as error:
                raise ValidationError("Original capacity child is unavailable") from error
            if (
                child_id in linked
                or _parent(child) != identifier
                or (
                    child["parent_call"].get("call_id") != link.get("id")
                    or child["parent_call"].get("reservation") != link.get("reservation")
                )
            ):
                raise ValidationError("Original capacity child ownership differs")
            linked.add(child_id)
            pending.append(child_id)
        if children_by_parent is not None:
            reverse = children_by_parent.get(identifier, set())
        else:
            reverse = {
                row[0]
                for row in store.conn.execute(
                    "SELECT id FROM runs WHERE json_extract(data,'$.parent_id')=? OR json_extract(data,'$.parent_call.parent_id')=?",
                    (identifier, identifier),
                )
            }
        if reverse != linked:
            raise ValidationError("Original capacity descendant links are incomplete")
    return result


def _member_pending(store, run):
    return (
        capacity_obligations(run)
        or store.conn.execute("SELECT 1 FROM budgets WHERE run_id=?", (run["id"],)).fetchone()
        is None
        or store.conn.execute(
            "SELECT 1 FROM reservations WHERE run_id=? AND state IN ('reserved','unknown') LIMIT 1",
            (run["id"],),
        ).fetchone()
        is not None
    )


def validate_insert(store, data):
    """Original mandatory insertion refuses adapters that hide the opt-in port."""
    current = policy(store)
    if current is None:
        return
    _writing(store)
    admission = data.get("local_admission")
    manifest = data.get("manifest", {})
    if (
        type(admission) is not dict
        or set(admission) != {"version", "root_run_id"}
        or type(admission["version"]) is not int
        or admission["version"] != 1
        or data.get("local_admission_digest") != digest(admission)
        or manifest.get("local_admission_protocol") != 1
        or manifest.get("admission_policy") != current
    ):
        raise ValidationError("Original deployment requires its accepted admission protocol")
    scope = Scope(**data["scope"])
    root_id = _identifier(admission["root_run_id"])
    root = _root(store, data)
    if root["id"] != root_id:
        raise ValidationError("Original admission root identity differs")
    claim = _claim(store, scope, root_id)
    if claim is None or claim["state"] != "held":
        raise ValidationError("Original admission requires its held root capacity claim")
