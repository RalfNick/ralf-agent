"""Pure original Session read acceptance; no storage or extra execution state."""

import json
from dataclasses import asdict, replace

from .errors import DefinitionMismatch, ValidationError
from .recall import RecallPage, RecallQuery
from .types import canonical, digest


def validate_protocol(manifest):
    values = ([manifest["session_data"]] if "session_data" in manifest else []) + [
        r["configuration"].get("session_data")
        for r in manifest.get("binding_catalog", {}).get("records", {}).values()
        if r.get("role") == "session"
    ]
    if not values and "session_data_protocol" not in manifest:
        return
    if (
        type(manifest.get("session_data_protocol")) is not int
        or manifest["session_data_protocol"] != 1
        or manifest["kernel"] != "temporal-3"
    ):
        raise DefinitionMismatch("Unsupported Temporal Session data read protocol")
    for value in values:
        if (
            type(value) is not dict
            or set(value)
            != {"version", "identity", "physical", "port", "query", "namespace", "receipt_version"}
            or value["version"] != 1
            or type(value["version"]) is not int
            or value["receipt_version"] != 1
            or type(value["receipt_version"]) is not int
        ):
            raise ValidationError("Invalid Session read registration")
        identity = value["identity"]
        if (
            type(identity) is not dict
            or identity.get("kind") != "session-binding-resource"
            or type(value["physical"]) is not dict
            or not value["physical"]
            or type(value["port"]) is not dict
        ):
            raise ValidationError("Session read requires a fixed scoped physical resource")
        if value["namespace"] not in identity["namespaces"]:
            raise ValidationError("Session read namespace escaped host allowlist")
        query = RecallQuery(**value["query"])
        if query.cursor is not None:
            raise ValidationError("Session query cannot start from an unfixed cursor")
        canonical(value)


def expected_read(manifest, request, *, proposed_address=None):
    value = manifest.get("session_data")
    if value is None:
        return None
    query = RecallQuery(**value["query"])
    if request.get("session_source") == "root":
        from .session_types import SessionRef
        from .temporal_session_tree import validate_lineage

        if "session_tree_protocol" not in manifest:
            raise DefinitionMismatch("Root Session read requires its original tree protocol")
        accepted = validate_lineage(
            {**request["session_declaration"], "session_lineage": request["session_lineage"]},
            request["session_lineage"]["root_binding"]["manifest"],
            request["scope"],
        )
        address = SessionRef.from_dict(accepted["root_ref"]).key.storage_key
        if (
            accepted["parent_run_id"] is not None
            or accepted["run_id"] != request["run_id"]
            or request["session_data_node"] != "root"
            or request["address"] != address
            or proposed_address is not None
            and proposed_address != address
            or request["query"] != asdict(query)
            or digest({k: v for k, v in manifest.items() if k != "orchestration"})
            != digest(
                {
                    k: v
                    for k, v in request["session_lineage"]["root_binding"]["manifest"].items()
                    if k != "orchestration"
                }
            )
        ):
            raise DefinitionMismatch("Root read changed original resource or ownership")
        return {
            "version": 1,
            "scope": request["scope"],
            "run_id": request["run_id"],
            "node": "root",
            "registration_digest": digest(value),
            "address": address,
            "query": asdict(query),
        }
    query = replace(query, max_chars=min(query.max_chars, request["step"]["max_context_chars"]))
    address = session_storage_key(
        value["namespace"], private_address(request["run_id"], request["session_data_node"])
    )
    if request.get("session_turn") is not None:
        from .session_types import SessionRef

        address = SessionRef.from_dict(request["session_turn"]["session_ref"]).key.storage_key
    if request.get("session_lineage", {}).get("links"):
        from .session_types import SessionRef
        from .temporal_bindings import effective_manifest
        from .temporal_session_topology import CompositeSessionTopology, seal_member_address
        from .temporal_session_tree import member_projection, validate_root_snapshot

        full = request["session_lineage"]["root_binding"]["manifest"]
        declaration = {
            **request["session_declaration"],
            "session_lineage": request["session_lineage"],
            **(
                {"session_root_snapshot": request["session_root_snapshot"]}
                if "session_root_snapshot" in request
                else {}
            ),
        }
        accepted = member_projection(
            declaration, full, request["scope"], request["session_data_node"]
        )
        validate_root_snapshot(declaration, full, request["scope"])
        if accepted["run_id"] != request["run_id"] or digest(
            {
                k: v
                for k, v in effective_manifest(full, accepted["bindings"]).items()
                if k != "orchestration"
            }
        ) != digest({k: v for k, v in manifest.items() if k != "orchestration"}):
            raise DefinitionMismatch("Member read changed original selected resource or Run")
        address = CompositeSessionTopology().member_address(
            SessionRef.from_dict(accepted["root_ref"]),
            accepted["path"],
            accepted["definition_digest"],
            namespace=value["namespace"],
        )
        if proposed_address is not None:
            address = seal_member_address(
                SessionRef.from_dict(accepted["root_ref"]),
                accepted["path"],
                accepted["definition_digest"],
                proposed_address,
                namespace=value["namespace"],
            )
    elif proposed_address is not None and proposed_address != address:
        raise DefinitionMismatch("Session proposal changed its original address")
    return {
        "version": 1,
        "scope": request["scope"],
        "run_id": request["run_id"],
        "node": request["session_data_node"],
        "registration_digest": digest(value),
        "address": address,
        "query": asdict(query),
    }


def validate_snapshot(snapshot, manifest, request):
    cached = request.get("session_private_snapshot")
    if cached is not None:
        if (
            not request.get("session_lineage", {}).get("links")
            or type(cached) is not dict
            or set(cached) != {"session_data", "session_data_references"}
        ):
            raise DefinitionMismatch("Invalid original private Session snapshot")
        validate_snapshot(
            cached, manifest, {k: v for k, v in request.items() if k != "session_private_snapshot"}
        )
        if any(snapshot.get(k) != v for k, v in cached.items()):
            raise DefinitionMismatch("Member context replaced its original private snapshot")
    proposed = (
        snapshot.get("session_data", {}).get("address")
        if request.get("session_lineage", {}).get("links")
        and type(snapshot.get("session_data")) is dict
        else None
    )
    expected = expected_read(manifest, request, proposed_address=proposed)
    if expected is None:
        if "session_data" in snapshot or "session_data_references" in snapshot:
            raise DefinitionMismatch("Unexpected Session data evidence")
        return
    evidence = snapshot.get("session_data")
    if (
        type(evidence) is not dict
        or set(evidence) != set(expected) | {"page", "revision"}
        or any(evidence.get(k) != v for k, v in expected.items())
    ):
        raise DefinitionMismatch("Session read snapshot lost original address or registration")
    page = RecallPage(**evidence["page"])
    query = RecallQuery(**expected["query"])
    try:
        source = json.loads(page.snapshot_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Session snapshot must carry a committed revision") from exc
    revision = source.get("revision") if type(source) is dict else None
    if (
        type(revision) is not int
        or revision < 0
        or evidence["revision"] != revision
        or type(evidence["revision"]) is not int
    ):
        raise ValidationError("Session snapshot revision is invalid")
    if (
        not page.backend_bounded
        or page.scanned > query.scan_limit
        or len(page.items) > query.max_items
        or page.used_chars > query.max_chars
        or len(page.items) > revision
    ):
        raise ValidationError("Session read exceeded fixed bounded allowance")
    if snapshot.get("session_data_references") != references(evidence):
        raise DefinitionMismatch("Session source reference changed accepted evidence")


def private_address(run_id, node):
    if type(run_id) is not str or not run_id.strip() or type(node) is not int or node < 0:
        raise ValidationError("Session read requires original Run/node identity")
    return "ralf-temporal-private-read-v1:" + canonical([run_id, node])


def session_storage_key(namespace, session_id):
    return (
        session_id if namespace is None else "ralf-session-v1:" + canonical([namespace, session_id])
    )


def references(evidence):
    items = evidence["page"]["items"]
    return (
        []
        if not items
        else [
            {
                "key": "session:data:" + digest([evidence["scope"], evidence["address"]]),
                "version": evidence["revision"],
                "session": items,
                "source_digest": digest(evidence),
            }
        ]
    )
