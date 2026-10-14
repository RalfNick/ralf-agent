"""Pure, bounded native grants and evidence adoption; no execution authority or I/O."""

import copy

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .types import canonical, digest


def grant(state, action, runner_identity, method, params, binding):
    canonical(params)
    canonical(binding)
    if method not in {"prepare", "thread/start", "turn/start"}:
        raise AuthorizationDenied("Native method has no original coding grant")
    if "cancel" in state or (state.get("fenced") and state["grants"]):
        raise AuthorizationDenied("Delegated coding submission was cancelled or fenced")
    if (
        binding.get("request") != state["request"]
        or binding.get("runner") != runner_identity
        or binding.get("dispatch") != state["request"]["dispatch"]
    ):
        raise DefinitionMismatch("Native grant binding differs from original intent")
    if method == "prepare":
        environment = binding.get("environment")
        generation = digest({"dispatch": state["request"]["dispatch"], "runner": runner_identity})[
            :32
        ]
        if type(environment) is not dict or environment.get("expected_generation") != generation:
            raise DefinitionMismatch("Preparation grant requires its original namespace generation")
        if (
            runner_identity.get("configuration_readonly") is True
            and environment.get("configuration_readonly") is not True
        ):
            raise DefinitionMismatch(
                "Preparation requires its original read-only configuration mount"
            )
        if runner_identity.get("kind") == "codex-coding-runner":
            from pathlib import Path

            dispatch = state["request"]["dispatch"]
            resource_key = digest(
                {"scope": dispatch["scope"], "effect_key": dispatch["effect_key"]}
            )
            expected_path = str(Path(runner_identity["root"]["path"]) / resource_key)
            if (
                environment.get("root", {}).get("path") != expected_path
                or environment.get("docker_host") != runner_identity["docker_host"]
                or environment.get("profile") != runner_identity["profile"]
                or environment.get("retire_on_stop") is not True
            ):
                raise DefinitionMismatch(
                    "Preparation grant replaced original namespace dependencies"
                )
        expected = {}
    else:
        prepared = state.get("prepared")
        if prepared is None or state.get("binding") != binding:
            raise AuthorizationDenied("Native grant requires its adopted original environment")
        expected = {
            "cwd": "/workspace",
            "approvalPolicy": "never",
            "approvalsReviewer": "user",
        }
        if method == "thread/start":
            expected["ephemeral"] = False
        else:
            if not state.get("thread"):
                raise AuthorizationDenied("Native Turn requires its adopted original Thread")
            expected.update(
                threadId=state["thread"]["thread_id"],
                input=[
                    {
                        "type": "text",
                        "text": action["arguments"]["task"],
                        "text_elements": [],
                    }
                ],
            )
    if params != expected:
        raise AuthorizationDenied("Native request differs from its bounded original grant")
    grant = {
        "request": copy.deepcopy(state["request"]),
        "method": method,
        "params": copy.deepcopy(params),
        "binding": copy.deepcopy(binding),
        "execute": False,
    }
    prior = state["grants"].get(method)
    if prior is not None:
        if any(prior[k] != grant[k] for k in ("method", "params", "binding", "request")):
            raise DefinitionMismatch("Native phase cannot replace its original submission")
        return grant
    state["grants"][method] = copy.deepcopy(grant)
    state["pending_stop"] = True
    state["fenced"] = False
    state["phase"] = method + "_submitted"
    grant["execute"] = True
    return grant


def adopt(state, runner_identity, kind, evidence):
    canonical(evidence)
    if state.get("create_not_dispatched") is not None and kind != "error":
        raise DefinitionMismatch("Sealed original CREATE cannot adopt native execution receipts")
    if (
        kind
        not in {"prepared", "thread", "turn", "observation", "stop", "result_candidate", "error"}
        or type(evidence) is not dict
    ):
        raise ValidationError("Invalid delegated receipt")
    if kind == "prepared":
        if "prepare" not in state["grants"]:
            raise AuthorizationDenied("Environment receipt has no original preparation grant")
        original = state["grants"]["prepare"]["binding"]["environment"]
        if (
            evidence.get("identity") != original
            or evidence.get("generation") != original.get("expected_generation")
            or type(evidence.get("container_id")) is not str
            or len(evidence["container_id"]) != 64
            or set(evidence["container_id"]) - set("0123456789abcdef")
        ):
            raise DefinitionMismatch("Environment receipt replaced its granted original namespace")
        if "prepared" in state and any(
            state["prepared"].get(k) != evidence.get(k)
            for k in ("identity", "container_id", "generation")
        ):
            raise DefinitionMismatch("Original environment receipt changed")
        state["prepared"] = copy.deepcopy(evidence)
        state["binding"] = {
            "request": copy.deepcopy(state["request"]),
            "runner": runner_identity,
            "dispatch": copy.deepcopy(state["request"]["dispatch"]),
            "environment": {
                "identity": evidence["identity"],
                "container_id": evidence["container_id"],
                "generation": evidence["generation"],
            },
        }
    elif kind in {"thread", "turn"}:
        required = {"thread_id"} if kind == "thread" else {"thread_id", "turn_id"}
        if set(evidence) != required or any(
            type(evidence[key]) is not str or not evidence[key].strip() or len(evidence[key]) > 1024
            for key in required
        ):
            raise ValidationError("Native receipt requires bounded original locators")
        if f"{kind}/start" not in state["grants"]:
            raise AuthorizationDenied("Native receipt has no original submission grant")
        if kind == "turn" and evidence.get("thread_id") != state.get("thread", {}).get("thread_id"):
            raise DefinitionMismatch("Native Turn receipt changed its original Thread")
        if kind in state and state[kind] != evidence:
            raise DefinitionMismatch("Native handle receipt changed")
        state[kind] = copy.deepcopy(evidence)
    elif kind == "stop":
        preparation = state["grants"].get("prepare")
        if preparation is None:
            raise AuthorizationDenied("Stop receipt has no original namespace preparation grant")
        namespace = preparation["binding"]["environment"]
        if (
            evidence.get("identity") != namespace
            or evidence.get("generation") != namespace.get("expected_generation")
            or type(evidence.get("container_id")) is not str
            or len(evidence["container_id"]) != 64
            or set(evidence["container_id"]) - set("0123456789abcdef")
        ):
            raise DefinitionMismatch("Stop receipt replaced the granted original namespace")
        prepared = state.get("prepared")
        if prepared is not None and any(
            evidence.get(k) != prepared.get(k) for k in ("container_id", "generation", "identity")
        ):
            raise DefinitionMismatch("Stop receipt belongs to another original environment")
        state["stop"] = copy.deepcopy(evidence)
        if (
            evidence.get("fenced") is True
            and evidence.get("stopped") is True
            and evidence.get("retired") is True
            and evidence.get("container_present") is False
            and evidence.get("running") is False
        ):
            state["pending_stop"] = False
            state["fenced"] = True
    elif kind == "result_candidate":
        candidate = evidence.get("result", {})
        native = candidate.get("native", {})
        observation = state.get("observation", {})
        stopped = state.get("stop", {})
        if (
            native.get("status") != "completed"
            or observation.get("native_status") != "completed"
            or observation.get("final_thread_read") is not True
            or any(native.get(k) != state.get("turn", {}).get(k) for k in ("thread_id", "turn_id"))
            or state["pending_stop"]
            or not state["fenced"]
            or candidate.get("stop")
            != {k: stopped.get(k) for k in ("container_id", "generation", "fenced")}
        ):
            raise ValidationError(
                "Native result candidate requires original completion, read and fencing receipts"
            )
        if "result_candidate" in state and state["result_candidate"] != candidate:
            raise DefinitionMismatch("Original native result candidate changed")
        state["result_candidate"] = copy.deepcopy(candidate)
    elif kind == "observation":
        if any(evidence.get(k) != state.get("turn", {}).get(k) for k in ("thread_id", "turn_id")):
            raise DefinitionMismatch("Native observation belongs to another original Turn")
        state["observation"] = copy.deepcopy(evidence)
    else:
        state["error"] = copy.deepcopy(evidence)
    state["phase"] = kind


def _create_not_dispatched_facts():
    return {
        "gate_sealed": True,
        "cli_gate_accepted": False,
        "cli_exec_started": False,
        "helpers_ended": True,
        "control_drained": True,
        "metadata_present": True,
        "namespace_query_succeeded": True,
        "namespace_confirmed": True,
        "container_present": False,
    }


def _create_not_dispatched_digests():
    return (
        "create_operation_digest",
        "supervision_declaration_digest",
        "supervision_receipt_digest",
        "proof_digest",
    )


def _create_digest(value, size=64):
    return type(value) is str and len(value) == size and not set(value) - set("0123456789abcdef")


def validate_create_not_dispatched(evidence, environment):
    """Check producer-verified original no-exec/end/query facts, without I/O."""
    canonical(evidence)
    facts = _create_not_dispatched_facts()
    if (
        type(environment) is not dict
        or type(environment.get("create_operation_version")) is not int
        or environment["create_operation_version"] != 2
        or type(environment.get("create_supervision_version")) is not int
        or environment["create_supervision_version"] != 1
        or environment.get("retire_on_stop") is not True
        or not _create_digest(environment.get("expected_generation"), 32)
        or type(evidence) is not dict
        or set(evidence)
        != {"version", "identity", "generation", *_create_not_dispatched_digests(), *facts}
        or type(evidence["version"]) is not int
        or evidence["version"] != 1
        or canonical(evidence["identity"]) != canonical(environment)
        or evidence["generation"] != environment["expected_generation"]
        or any(not _create_digest(evidence[key]) for key in _create_not_dispatched_digests())
        or any(evidence[key] is not expected for key, expected in facts.items())
        or evidence["proof_digest"]
        != digest({k: v for k, v in evidence.items() if k != "proof_digest"})
    ):
        raise DefinitionMismatch(
            "CREATE no-submit receipt requires exact original sealed supervision and namespace query"
        )
    return copy.deepcopy(evidence)


def adopt_create_not_dispatched(state, runner_identity, evidence):
    """End the one prepared grant mechanically; keep its financial/effect intent."""
    preparation = state.get("grants", {}).get("prepare")
    if (
        preparation is None
        or set(state["grants"]) != {"prepare"}
        or preparation.get("method") != "prepare"
        or preparation.get("params") != {}
        or preparation.get("execute") is not False
        or canonical(preparation.get("request")) != canonical(state["request"])
        or canonical(preparation.get("binding", {}).get("runner")) != canonical(runner_identity)
        or canonical(preparation["binding"].get("request")) != canonical(state["request"])
        or canonical(preparation["binding"].get("dispatch"))
        != canonical(state["request"]["dispatch"])
        or any(
            state.get(key) is not None
            for key in (
                "prepared",
                "binding",
                "thread",
                "turn",
                "stop",
                "namespace_absent",
                "unprepared",
            )
        )
    ):
        raise AuthorizationDenied(
            "CREATE no-submit requires its sole original unprepared preparation grant"
        )
    value = validate_create_not_dispatched(evidence, preparation["binding"].get("environment"))
    previous = state.get("create_not_dispatched")
    if previous is not None and previous != value:
        raise DefinitionMismatch("Original CREATE no-submit receipt is immutable")
    state["create_not_dispatched"] = value
    state["pending_stop"], state["fenced"] = False, True
    state["phase"] = "create_not_dispatched"


def create_not_dispatched_projection(
    evidence, environment, *, token, dispatch_digest, runner_digest
):
    """Carry validated evidence into the original capacity obligation after adoption."""
    value = validate_create_not_dispatched(evidence, environment)
    if (
        not _create_digest(token, 32)
        or not _create_digest(dispatch_digest)
        or not _create_digest(runner_digest)
    ):
        raise DefinitionMismatch(
            "CREATE no-submit capacity projection requires exact original digests and token"
        )
    return {
        "version": 1,
        "token": token,
        "dispatch_digest": dispatch_digest,
        "runner_digest": runner_digest,
        "generation": value["generation"],
        **{
            key: value[key]
            for key in (*_create_not_dispatched_digests(), *_create_not_dispatched_facts())
        },
        "evidence": value,
    }


def validate_create_not_dispatched_projection(proof, original, token):
    canonical(proof)
    if type(proof) is not dict or type(proof.get("evidence")) is not dict:
        raise DefinitionMismatch(
            "CREATE no-submit capacity requires its complete validated evidence"
        )
    expected = create_not_dispatched_projection(
        proof["evidence"],
        proof["evidence"].get("identity"),
        token=token,
        dispatch_digest=original["dispatch_digest"],
        runner_digest=original["runner_digest"],
    )
    if (
        type(proof.get("version")) is not int
        or proof != expected
        or proof.get("generation") != original["generation"]
        or any(proof.get(key) is not fact for key, fact in _create_not_dispatched_facts().items())
    ):
        raise DefinitionMismatch(
            "CREATE no-submit projection changed its original capacity obligation"
        )
