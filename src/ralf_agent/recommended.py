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
    embedding=None,
    knowledge_namespace="default",
    reranker=None,
    query_transform=None,
):
    """Return an editable-by-replacement Profile, not a new runtime authority.

    The offline echo verifies wiring; it is not a reasoning model. Managed
    memory writes allowlisted final results to agent_name's fact namespace.
    Customize the admission fields before using this preset for a real app.
    Version 2 replaces inherited recall policy/planner alternatives and lets
    complete semantic resource declarations supply their own configuration.
    """
    if kind not in {
        "local-basic",
        "local-knowledge",
        "managed-memory",
        "semantic-knowledge",
        "memory-recall",
        "semantic-memory",
        "plan-and-execute",
        "team",
    }:
        raise ValidationError("Unknown recommended Local combination")
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise ValidationError("Recommended Agent name must be non-empty text")
    defaults = {
        "context_assembler": {"adapter": "managed-data"},
        "recall_policy": {"adapter": "bounded-recall"},
        "verifier": {"adapter": "schema"},
    }
    if kind in {
        "semantic-knowledge",
        "memory-recall",
        "semantic-memory",
        "plan-and-execute",
        "team",
    }:
        defaults["context_assembler"] = {"adapter": "relevant-data"}
    if kind in {"semantic-knowledge", "semantic-memory"}:
        semantic_replaced = (
            version == "2"
            and isinstance(components, dict)
            and ("memory_store" if kind == "semantic-memory" else "knowledge") in components
        )
        if not semantic_replaced and (
            not isinstance(embedding, dict)
            or set(embedding) != {"type", "config"}
            or embedding["type"] != "openai"
            or not isinstance(embedding["config"], dict)
            or not {"model", "dimensions"} <= set(embedding["config"])
        ):
            raise ValidationError(
                "Semantic combination requires explicit HTTP embedding model/dimensions"
            )
        if not semantic_replaced and (
            not isinstance(knowledge_namespace, str) or not knowledge_namespace.strip()
        ):
            raise ValidationError("Knowledge namespace must be non-empty text")
        if kind == "semantic-memory":
            defaults["context_assembler"]["config"] = {"selector": {"adapter": "ordered"}}
            defaults.pop("recall_policy")
            defaults["recall_planner"] = {"adapter": "task-text"}
            defaults["memory_store"] = {
                "adapter": "semantic-recall-async",
                "config": {
                    "backend": {"adapter": "sqlite"},
                    "embedding": copy.deepcopy(embedding),
                    **(
                        {"query_transform": copy.deepcopy(query_transform)}
                        if query_transform is not None
                        else {}
                    ),
                },
            }
        else:
            defaults["knowledge"] = {
                "adapter": "sqlite-hybrid-http",
                "config": {
                    "namespace": knowledge_namespace,
                    "embedding": copy.deepcopy(embedding),
                    "failure_policy": "strict",
                    "reranker": "preserve-order" if reranker is None else copy.deepcopy(reranker),
                },
            }
            if query_transform is not None:
                defaults["knowledge"]["config"]["query_transform"] = copy.deepcopy(query_transform)
    elif embedding is not None:
        raise ValidationError("Embedding configuration requires semantic-knowledge")
    if reranker is not None and kind != "semantic-knowledge":
        raise ValidationError(
            "Reranker option requires semantic-knowledge or explicit knowledge component"
        )
    if query_transform is not None and kind not in {"semantic-knowledge", "semantic-memory"}:
        raise ValidationError(
            "Query transform option requires a semantic combination or explicit knowledge component"
        )
    if kind == "plan-and-execute":
        defaults["planners"] = {"adapter": "model"}
    if kind == "local-knowledge":
        defaults["knowledge"] = {"adapter": "sqlite-lexical"}
    if kind in {"managed-memory", "memory-recall", "semantic-memory"}:
        defaults["stage_policy"] = {
            "adapter": "sourced-memory",
            "config": {"namespace": agent_name, "fields": {"result": ["result"]}},
        }
    if components is not None:
        if not isinstance(components, dict):
            raise ValidationError("Recommended components must be explicit declarations")
        if version == "2":
            if "recall_planner" in components and "recall_policy" not in components:
                defaults.pop("recall_policy", None)
            elif "recall_policy" in components and "recall_planner" not in components:
                defaults.pop("recall_planner", None)
        defaults.update(copy.deepcopy(components))
    return RuntimeProfile(
        "ralf." + kind if name is None else name,
        version,
        {"default": {"adapter": "offline-echo"} if provider is None else provider},
        defaults,
        binding_components,
    )
