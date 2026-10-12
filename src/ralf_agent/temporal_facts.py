"""Opt-in bounded Facts reads; acceptance stays in the original Context History."""

from dataclasses import asdict, replace

from .binding_data import FactsBindingResource, FactsView, facts_identity
from .data_resources import remote_physical as _physical
from .errors import DefinitionMismatch, ValidationError
from .fact_index_ports import _FixedPorts
from .memory import memory_call
from .recall import LegacyMemoryRecallAdapter, MemoryRecallPolicy, RecallPage, _fact_records
from .temporal_state import detached
from .types import Scope, canonical, digest


def registration(facts):
    backend = facts.backend if isinstance(facts, (FactsBindingResource, FactsView)) else facts
    identity = (
        facts.identity if isinstance(facts, FactsBindingResource) else facts_identity(backend)
    )
    methods = [
        name
        for name in ("facts", "recall", "validate_facts")
        if callable(getattr(backend, name, None))
    ]
    fixed = _FixedPorts({"facts": (backend, methods, True)})
    return {
        "version": 1,
        "identity": detached(identity),
        "ports": fixed.identity,
        "physical": _physical(backend),
    }


def pins(facts):
    backend = facts.backend if isinstance(facts, FactsBindingResource) else facts
    methods = [
        name
        for name in ("facts", "recall", "validate_facts")
        if callable(getattr(backend, name, None))
    ]
    client = getattr(backend, "_client", None)
    connection = getattr(backend, "connection", None)
    return (
        facts,
        backend,
        _FixedPorts({"facts": (backend, methods, True)}),
        client,
        getattr(client, "connection_pool", None),
        connection,
        digest(_physical(backend)),
    )


def check_pin(pin):
    source, backend, fixed, client, pool, connection, physical = pin
    if isinstance(source, FactsBindingResource) and source.backend is not backend:
        raise DefinitionMismatch("Temporal Facts resource changed")
    fixed.check()
    if (
        getattr(backend, "_client", None) is not client
        or getattr(client, "connection_pool", None) is not pool
        or getattr(backend, "connection", None) is not connection
        or digest(_physical(backend)) != physical
    ):
        raise DefinitionMismatch("Temporal Facts physical resource changed")


def recall_registration(policy, planner):
    from .temporal_activities import component_identity

    if policy is not None and planner is not None:
        raise ValidationError("Configure a recall policy or planner, not both")
    if policy is not None and not isinstance(policy, MemoryRecallPolicy):
        raise ValidationError("Temporal recall requires MemoryRecallPolicy")
    if planner is not None:
        return {"planner": component_identity(planner, ("plan",), synchronous=True)}
    return {"policy": (policy or MemoryRecallPolicy()).identity}


def _query(runtime, request):
    planner = runtime.recall_planner
    scope, step = Scope(**request["scope"]), request["step"]
    policy = runtime.recall_policy or MemoryRecallPolicy()
    if planner is not None:
        policy = planner.plan(
            scope,
            step["name"],
            request.get("session_id") or request["run_id"],
            (
                request.get("current_task")
                if isinstance(request.get("current_task"), str)
                else canonical(request["current_task"])
                if "current_task" in request
                else request["messages"][1]["content"]
            ),
        )
        if not isinstance(policy, MemoryRecallPolicy):
            from .temporal_activities import _close_lazy

            _close_lazy(policy)
            raise ValidationError("Recall planner must return a completed MemoryRecallPolicy")
    # Reconstruct the complete immutable proposal before any backend await.
    return MemoryRecallPolicy(
        facts=replace(policy.facts), session=replace(policy.session), max_pages=policy.max_pages
    )


async def validate(runtime, request, snapshot):
    """Validate only original facts, independently of Knowledge reference formats."""
    if runtime.facts is None:
        return
    from .temporal_facts_state import validate_snapshot

    validate_snapshot(snapshot, runtime.manifest)
    facts = snapshot.get("facts")
    if (
        type(facts) is not list
        or snapshot.get("references") != snapshot.get("knowledge_references", []) + facts
        or (runtime.knowledge is None and snapshot.get("knowledge_references") != [])
        or snapshot.get("facts_recall", {}).get("digest") != digest(facts)
    ):
        raise ValidationError("Temporal Facts context requires original recall evidence")
    source = runtime.facts
    method = getattr(source, "validate_facts", None)
    if not callable(method):
        method = LegacyMemoryRecallAdapter(source).validate_facts
    result = await memory_call(
        method, Scope(**request["scope"]), request["step"]["name"], detached(facts)
    )
    runtime.validate_release(request["runtime_manifest"])
    if result is not None:
        from .temporal_activities import _close_lazy

        _close_lazy(result)
        raise ValidationError("Facts validation must return None")


async def load(runtime, request, knowledge_references):
    if runtime.facts is None:
        return {"references": detached(knowledge_references)}
    policy, source = _query(runtime, request), runtime.facts
    runtime.validate_release(request["runtime_manifest"])
    method = getattr(source, "recall", None)
    if not callable(method):
        method = LegacyMemoryRecallAdapter(source).recall
    pages = min(policy.max_pages, policy.facts.max_items, policy.facts.max_chars // 2)
    page_query = replace(
        policy.facts,
        max_items=policy.facts.max_items // pages,
        max_chars=policy.facts.max_chars // pages,
        scan_limit=policy.facts.scan_limit // pages,
    )
    query, facts, receipts, seen, snapshot, cursors = page_query, [], [], set(), None, set()
    for _ in range(pages):
        page = await memory_call(method, Scope(**request["scope"]), request["step"]["name"], query)
        runtime.validate_release(request["runtime_manifest"])
        if not isinstance(page, RecallPage):
            from .temporal_activities import _close_lazy

            _close_lazy(page)
            raise ValidationError("Facts recall must return RecallPage")
        if (
            len(page.items) > query.max_items
            or page.used_chars > query.max_chars
            or page.scanned > query.scan_limit
        ):
            raise ValidationError("Facts backend exceeded recall allowance")
        if snapshot is not None and snapshot != page.snapshot_id:
            raise ValidationError("Facts recall snapshot changed between pages")
        snapshot = page.snapshot_id
        items = _fact_records(page.items)
        if len(items) != len(page.items):
            raise ValidationError("Facts recall contains duplicate identities")
        for item in items:
            if item["key"] in seen:
                raise ValidationError("Facts recall repeated a record")
            seen.add(item["key"])
        facts.extend(items)
        receipts.append({k: v for k, v in asdict(page).items() if k != "items"})
        if page.next_cursor is None:
            break
        if page.next_cursor == query.cursor or page.scanned == 0:
            raise ValidationError("Facts recall cursor did not advance")
        if page.next_cursor in cursors:
            raise ValidationError("Facts recall repeated a cursor")
        cursors.add(page.next_cursor)
        query = replace(page_query, cursor=page.next_cursor)
    if (
        len(facts) > policy.facts.max_items
        or len(canonical(facts)) > policy.facts.max_chars
        or sum(p["scanned"] for p in receipts) > policy.facts.scan_limit
    ):
        raise ValidationError("Combined Facts pages exceeded recall allowance")
    result = {
        "references": detached(knowledge_references) + detached(facts),
        "knowledge_references": detached(knowledge_references),
        "facts": detached(facts),
        "facts_recall": {
            "version": 1,
            "query": asdict(policy.facts),
            "max_pages": policy.max_pages,
            "page_query": asdict(page_query),
            "pages": receipts,
            "digest": digest(facts),
        },
    }
    await validate(runtime, request, result)
    return result
