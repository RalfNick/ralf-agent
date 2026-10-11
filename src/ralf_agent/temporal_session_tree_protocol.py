"""Explicit candidate tree protocol; this module does not enable Worker execution."""

from .errors import DefinitionMismatch, ValidationError
from .session_types import sha
from .types import canonical


def validate_protocol(manifest):
    tree = manifest.get("session_tree_protocol")
    saves = manifest.get("session_save_protocol", {})
    if type(saves) is not dict:
        raise DefinitionMismatch("Unsupported original Session save protocol")
    if "session_tree_protocol" not in manifest:
        if saves.get("version") == 2:
            raise DefinitionMismatch("Session save-v2 requires explicit original tree topology")
        return
    if (
        type(tree) is not dict
        or set(tree) != {"version", "policy", "implementation"}
        or type(tree["version"]) is not int
        or tree["version"] != 1
        or type(tree["policy"]) is not dict
        or not tree["policy"]
        or type(tree["implementation"]) is not dict
        or set(tree["implementation"]) != {"root_address", "member_address"}
        or saves.get("version") != 2
        or type(saves.get("version")) is not int
        or manifest.get("session_protocol") != 1
        or type(manifest.get("session_protocol")) is not int
        or manifest.get("kernel") != "temporal-3"
        or len(canonical(tree).encode("utf-8")) > 65536
    ):
        raise DefinitionMismatch("Unsupported original Session tree protocol")
    try:
        for implementation in tree["implementation"].values():
            sha(implementation)
    except ValidationError:
        raise DefinitionMismatch("Session tree lost fixed original implementation") from None


def propose_manifest(manifest, topology):
    """Detach a metadata proposal; original admission and Worker pins are separate.

    Existing Runtime factories do not publish this candidate until the complete
    Parent/member save contract is available. Old save-v1 releases stay unchanged.
    """
    from .temporal_session_topology import SessionTopologyRegistration
    from .temporal_state import detached, validate_manifest

    if not isinstance(topology, SessionTopologyRegistration):
        raise ValidationError("Tree proposal requires an original fixed topology registration")
    original = validate_manifest(manifest)
    if (
        original.get("session_protocol") != 1
        or "session_save_protocol" not in original
        or original["kernel"] != "temporal-3"
    ):
        raise DefinitionMismatch("Tree proposal requires original Session admission and save ports")
    result = detached(original)
    result["session_tree_protocol"] = topology.identity
    result["session_save_protocol"]["version"] = 2
    return validate_manifest(result)
