"""Versioned, explicit Local starting combinations; no implicit network I/O."""

import copy

from .errors import ValidationError
from .runtime_config import RuntimeProfile


def recommended_profile(
    kind="local-basic",
    *,
    provider=None,
    components=None,
    binding_components=None,
    agent_name="assistant",
    name=None,
    version="1",
):
    """Return an editable-by-replacement Profile, not a new runtime authority.

    The offline echo verifies wiring; it is not a reasoning model. Managed
    memory writes allowlisted final results to agent_name's fact namespace.
    Customize the admission fields before using this preset for a real app.
    """
    if kind not in {"local-basic", "local-knowledge", "managed-memory"}:
        raise ValidationError("Unknown recommended Local combination")
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise ValidationError("Recommended Agent name must be non-empty text")
    defaults = {
        "context_assembler": {"adapter": "managed-data"},
        "recall_policy": {"adapter": "bounded-recall"},
        "verifier": {"adapter": "schema"},
    }
    if kind == "local-knowledge":
        defaults["knowledge"] = {"adapter": "sqlite-lexical"}
    if kind == "managed-memory":
        defaults["stage_policy"] = {
            "adapter": "sourced-memory",
            "config": {"namespace": agent_name, "fields": {"result": ["result"]}},
        }
    if components is not None:
        if not isinstance(components, dict):
            raise ValidationError("Recommended components must be explicit declarations")
        defaults.update(copy.deepcopy(components))
    return RuntimeProfile(
        "ralf." + kind if name is None else name,
        version,
        {"default": {"adapter": "offline-echo"} if provider is None else provider},
        defaults,
        binding_components,
    )
