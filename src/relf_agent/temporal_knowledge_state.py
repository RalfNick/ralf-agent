"""Pure scoped Knowledge publication and source evidence rules."""

from .errors import DefinitionMismatch, ValidationError
from .types import canonical, digest


def validate_protocol(manifest):
    records = manifest.get("binding_catalog", {}).get("records", {}).values()
    enabled = any("knowledge_registration" in r.get("configuration", {}) for r in records)
    if enabled or "knowledge_protocol" in manifest:
        if (
            manifest.get("kernel") != "temporal-3"
            or type(manifest.get("knowledge_protocol")) is not int
            or manifest["knowledge_protocol"] != 1
        ):
            raise DefinitionMismatch("Unsupported scoped Temporal Knowledge protocol")


def validate_snapshot(snapshot, manifest, scope):
    if "knowledge_registration" not in manifest:
        return
    identity = manifest["knowledge_context"]
    if identity.get("kind") != "scoped-knowledge-context" or identity["scope"] != scope:
        raise DefinitionMismatch("Knowledge snapshot differs from its scoped publication")
    references = snapshot.get("references")
    if "facts_context" in manifest:
        references = snapshot.get("knowledge_references")
    elif "knowledge_references" in snapshot and snapshot["knowledge_references"] != references:
        raise ValidationError("Knowledge snapshot changed source classification")
    if (
        type(references) is not list
        or len(references) > identity["context"]["limit"]
        or len(canonical(references)) > identity["context"]["max_chars"]
    ):
        raise ValidationError("Knowledge snapshot exceeded the original source allowance")
    seen = set()
    try:
        for reference in references:
            source, value = reference["_knowledge"], reference["value"]
            if (
                source["scope"] != scope
                or source["namespace"] != identity["namespace"]
                or reference["key"] != "knowledge:" + source["chunk_id"]
                or type(reference["version"]) is not int
                or reference["version"] < 1
                or reference["version"] != source["version"]
                or value["document_id"] != source["document_id"]
                or digest(value["text"]) != source["text_digest"]
                or source["chunk_id"] in seen
            ):
                raise ValidationError("Knowledge snapshot changed original source evidence")
            seen.add(source["chunk_id"])
    except (KeyError, TypeError) as exc:
        raise ValidationError("Invalid adopted Knowledge references") from exc
