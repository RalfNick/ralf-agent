"""Host-authorized root conversation selection, separate from member defaults."""

import json

from .binding_sessions import SessionBindingResource
from .errors import AuthorizationDenied, DefinitionMismatch, RalfError, ValidationError
from .memory import SQLiteMemory
from .types import canonical

UNSET_NAMESPACE = object()


def select_conversation(engine, namespace=UNSET_NAMESPACE):
    resource = getattr(engine, "conversation_resource", None)
    if resource is None:
        if namespace is not UNSET_NAMESPACE and namespace is not None:
            raise AuthorizationDenied("Conversation namespace is not authorized by the host")
        from .session_composites import conversation_backend

        return conversation_backend(engine), None, None
    if type(resource) is not SessionBindingResource:
        raise ValidationError("Conversation resource requires SessionBindingResource")
    namespace = resource.default_namespace if namespace is UNSET_NAMESPACE else namespace
    view = resource.select({"namespace": namespace}, engine.scope)
    view._check(engine.scope)
    backend = view.backend
    if type(backend) is not SQLiteMemory or backend.store.conn is not getattr(
        engine.store, "conn", None
    ):
        raise ValidationError("Conversation resource requires colocated SQLiteMemory")
    descriptor = json.loads(canonical({"resource": resource.identity, "namespace": namespace}))
    return backend, namespace, descriptor


def check_conversation_run(engine, run):
    if "session_turn" not in run or run["definition"]["kind"] not in {"graph", "team", "dynamic"}:
        return
    from .agent_harness import AgentHarness
    from .local_sessions import LocalSessionAuthority
    from .session_types import TurnAdmission

    try:
        turn = TurnAdmission.from_dict(run["session_turn"])
        if turn.run.run_id != run["id"] or turn.run.release_digest != run["release_digest"]:
            raise DefinitionMismatch("Conversation Turn differs from its original Run")
        authority = LocalSessionAuthority(engine, turn.run.authority_locator)
        state = authority.validate(turn.session)
        binding = state["bindings"][str(turn.session.binding_revision)]
        configured = (
            "conversation" in binding
            or "conversation_binding" in run
            or turn.session.key.namespace is not None
        )
        if configured:
            if (
                "conversation" not in binding
                or "conversation_binding" not in run
                or run["conversation_binding"] != binding["conversation"]
            ):
                raise DefinitionMismatch("Original conversation admission evidence differs")
            if run["session_id"] != turn.session.key.storage_key:
                raise DefinitionMismatch(
                    "Composite parent Session differs from its original address"
                )
        harness = AgentHarness.__new__(AgentHarness)
        object.__setattr__(harness, "_definition_json", canonical(binding["definition"]))
        key, current = authority._pin(
            harness, turn.session.key.session_id, namespace=turn.session.key.namespace
        )
        if key != turn.session.key or current != binding or current["manifest"] != run["manifest"]:
            raise DefinitionMismatch("Original conversation publication changed")
    except DefinitionMismatch:
        raise
    except RalfError as error:
        raise DefinitionMismatch("Original conversation resource is unavailable") from error
