"""Pure registration/evidence checks for original History decision adoption."""

from .errors import DefinitionMismatch, ValidationError
from .types import canonical, digest


def validate_protocol(manifest):
    records = manifest.get("binding_catalog", {}).get("records", {}).values()
    selected = [r for r in records if r.get("role") == "decision_policy"]
    if (
        not selected
        and "decision_protocol" not in manifest
        and "decision_registration" not in manifest
    ):
        return
    if (
        type(manifest.get("decision_protocol")) is not int
        or manifest["decision_protocol"] != 1
        or manifest.get("kernel") != "temporal-3"
    ):
        raise DefinitionMismatch("Unsupported Temporal DecisionPolicy protocol")
    pairs = [(manifest.get("decision_registration"), manifest.get("harness"))] + [
        (
            r.get("configuration", {}).get("decision_registration"),
            r.get("configuration", {}).get("harness"),
        )
        for r in selected
    ]
    for registration, identity in pairs:
        if (
            type(registration) is not dict
            or set(registration) != {"identity", "prepare_digest", "propose_digest"}
            or type(registration.get("identity")) is not dict
            or not registration["identity"]
            or registration["identity"] != identity
            or any(
                type(registration.get(name)) is not str
                or len(registration[name]) != 64
                or any(c not in "0123456789abcdef" for c in registration[name])
                for name in ("prepare_digest", "propose_digest")
            )
        ):
            raise ValidationError("Invalid Temporal DecisionPolicy registration")


def valid_adoption(state, action, response):
    """Return data, so the actual Workflow raises its own sandbox-local error."""
    try:
        canonical(response)
        evidence = response["decision_evidence"]
        if (
            type(response["model_evidence_version"]) is not int
            or response["model_evidence_version"] != 2
            or type(response["ok"]) is not bool
            or type(evidence) is not dict
            or set(evidence)
            != {
                "registration",
                "request_digest",
                "prepared_request",
                "received_response_digest",
                "proposal_digest",
            }
            or evidence["registration"] != state.step_manifest["decision_registration"]
            or evidence["request_digest"] != action["dispatch_request_digest"]
            or evidence["received_response_digest"] != digest(response["received_response"])
            or evidence["proposal_digest"]
            != digest({"output": response["output"], "tool_calls": response["tool_calls"]})
        ):
            return False
        prepared = evidence["prepared_request"]
        if type(prepared) is not dict or set(prepared) != {"messages", "tools"}:
            return False
        messages = prepared["messages"]
        if (
            type(messages) is not list
            or not messages
            or any(type(m) is not dict for m in messages)
            or len(canonical(messages)) > state.step["max_context_chars"]
        ):
            return False
        tools = prepared["tools"]
        if type(tools) is not list:
            return False
        values = [canonical(t) for t in tools]
        authorized = {
            canonical(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": state.manifest["tools"][name]["description"],
                        "parameters": state.manifest["tools"][name]["input_schema"],
                    },
                }
            )
            for name in state.step["tools"]
        }
        return len(set(values)) == len(values) and set(values) <= authorized
    except (KeyError, TypeError, ValueError, ValidationError):
        return False
