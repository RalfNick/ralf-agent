"""Worker-only grounded memory effects; observations go to original History."""

import asyncio
import time

from .errors import DefinitionMismatch, ValidationError
from .memory import memory_call
from .memory_extraction import MemoryAdmissionPolicy
from .model_evidence import snapshot_model_response
from .recall import _fact_records
from .temporal_state import detached
from .types import ModelResponse, Scope, canonical, digest

ACTIVITY = "ralf.temporal.memory.v1"


def _facts(policy, source, proposals):
    if type(proposals) is not list or len(proposals) > policy.admission.identity["max_facts"]:
        raise ValidationError("Memory proposals exceed granted limits")
    values, seen = [], set()
    for proposal in proposals:
        admission = MemoryAdmissionPolicy(
            **{
                k: policy.admission.identity[k]
                for k in ("fields", "max_facts", "max_value_chars", "expires_at")
            }
        )
        p = admission.validate(proposal, detached(source)).to_dict()
        if p["key"] in seen:
            raise ValidationError("Duplicate selected memory key")
        seen.add(p["key"])
        key = "auto:" + digest([source["run_id"], source["node"], p["key"]])
        values.append(
            {
                "key": key,
                "value": {
                    "key": p["key"],
                    "value": p["value"],
                    "source_path": p["source_path"],
                    "source_run_id": source["run_id"],
                    "source_node": source["node"],
                    "source_digest": digest(source),
                    "release_digest": source["release_digest"],
                    "trust": "completed-result-observation",
                },
                "expires_at": policy.admission.identity["expires_at"],
                "status": "prepared",
            }
        )
    return values


async def execute(runtime, request, *, dispatch_guard=None):
    dispatched, received = False, None
    policy, scope = runtime.stage_policy, Scope(**request["scope"])

    def check():
        runtime.validate_release(request["runtime_manifest"])
        if runtime.stage_policy is not policy:
            raise DefinitionMismatch("Executing memory policy changed")
        policy.check(scope)
        from .temporal_bindings import memory_registration

        if digest(memory_registration(policy, runtime.providers)["policy"]) != digest(
            request["policy"]
        ):
            raise DefinitionMismatch("Memory request differs from fixed target")

    try:
        check()
        phase, source = request["phase"], request["source"]
        if (
            source["run_id"] != request["run_id"]
            or source["scope"] != request["scope"]
            or source["release_digest"] != request["release_digest"]
        ):
            raise DefinitionMismatch("Memory source lost original ownership")
        if len(canonical(source)) > 65536:
            raise ValidationError("Memory source exceeds bounded allowance")
        if phase == "plan":
            if "selection" in policy.identity:
                proposed = policy.request(detached(source))
                value = {
                    "selection_request": {"messages": proposed.messages, "tools": proposed.tools}
                }
                if proposed.tools:
                    raise ValidationError("Memory selector cannot use tools")
            else:
                value = {"facts": _facts(policy, source, policy.propose(detached(source)))}
            check()
            return {"ok": True, "source_digest": digest(source), **detached(value)}
        if phase == "select":
            provider = runtime.providers[policy.provider]
            from .temporal_managed_context import admit_dispatch

            await admit_dispatch(request, dispatch_guard)
            check()
            dispatched = True
            response = await asyncio.wait_for(
                provider.complete(detached(request["selection_request"]["messages"]), []),
                policy.timeout,
            )
            if not isinstance(response, ModelResponse):
                raise ValidationError("Memory selector must return ModelResponse")
            received = snapshot_model_response(response)
            check()
            return {"ok": True, "received_response": received}
        if phase == "adopt":
            facts = _facts(
                policy,
                source,
                policy.select(detached(source), detached(request["received_response"])),
            )
            check()
            return {"ok": True, "facts": facts}
        fact = request["fact"]
        expiry = fact["expires_at"]
        if phase == "memory-write":
            from .temporal_managed_context import admit_dispatch

            if expiry is not None and expiry <= time.time():
                raise ValidationError("Memory fact expired before dispatch")
            await admit_dispatch(request, dispatch_guard)
            check()
            dispatched = True
            version = await asyncio.wait_for(
                memory_call(
                    policy.memory.put_fact,
                    scope,
                    policy.namespace,
                    fact["key"],
                    detached(fact["value"]),
                    expected_version=0,
                    expires_at=expiry,
                ),
                policy.timeout,
            )
            check()
            if type(version) is not int or version != 1:
                raise ValidationError("CAS must acknowledge exact first version")
            return {"ok": True, "dispatched": True}
        if phase in {"read", "verify"}:
            found = await asyncio.wait_for(
                memory_call(policy.memory.inspect_fact, scope, policy.namespace, fact["key"]),
                policy.timeout,
            )
            check()
            if found is None:
                return {"ok": True, "found": False}
            _fact_records([found])
            if (
                found.get("key") != fact["key"]
                or type(found.get("version")) is not int
                or found["version"] != 1
                or canonical(found["value"]) != canonical(fact["value"])
                or found.get("expires_at") != expiry
            ):
                raise DefinitionMismatch("Exact fact differs from original CAS intent")
            result = await asyncio.wait_for(
                memory_call(policy.memory.validate_facts, scope, policy.namespace, [found]),
                policy.timeout,
            )
            check()
            if result is not None:
                raise ValidationError("Memory validation must finish with None")
            return {
                "ok": True,
                "found": True,
                "fact": {k: detached(fact[k]) for k in ("key", "value", "expires_at")},
            }
        raise ValidationError("Unknown memory phase")
    except Exception as exc:
        return {
            "ok": False,
            "code": getattr(exc, "code", "memory_failed"),
            "dispatched": dispatched,
            "execution_uncertain": isinstance(exc, TimeoutError),
            **({"received_response": received} if received is not None else {}),
        }
