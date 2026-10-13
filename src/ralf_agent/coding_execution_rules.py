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
