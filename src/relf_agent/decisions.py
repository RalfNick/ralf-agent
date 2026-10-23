"""Pure acceptance rules; execution authorities assign identities and commit state."""

import json

from jsonschema import Draft202012Validator

from .errors import AuthorizationDenied, ValidationError
from .harness import DecisionProposal
from .types import canonical


def final_output(output, schema):
    """Require content, or an explicit Schema that permits a JSON null result."""
    if output is None and schema is None:
        raise ValidationError("A final model decision requires output or a nullable Schema")
    if schema is not None:
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except ValueError as exc:
                raise ValidationError("Model output is not valid JSON") from exc
    if isinstance(output, str) and not output.strip():
        raise ValidationError("A final model decision requires non-empty output")
    if schema is not None and not Draft202012Validator(schema).is_valid(output):
        raise ValidationError("Model output does not match the required Schema")
    canonical(output)
    return output


def validate_call_ids(ids):
    """Validate a complete batch, including authority-generated fallback IDs."""
    seen = set()
    for call_id in ids:
        if not isinstance(call_id, str) or not call_id or call_id in seen:
            raise ValidationError("Invalid or duplicate model tool-call identity")
        seen.add(call_id)


def validate_decision(spec, proposal, tool_manifests):
    """Validate detached, effective arguments without allocating or adopting Actions.

    Registries resolve typed defaults before this boundary. Keep output raw so
    the execution authority normalizes Schema JSON exactly once at completion.
    """
    if not isinstance(proposal, DecisionProposal):
        raise ValidationError("Harness.propose must return DecisionProposal")
    proposal = DecisionProposal(proposal.output, proposal.tool_calls)
    validate_call_ids([call.call_id for call in proposal.tool_calls if call.call_id])
    for call in proposal.tool_calls:
        if call.name not in spec.tools:
            raise AuthorizationDenied("Harness requested a tool outside AgentSpec")
        manifest = tool_manifests.get(call.name)
        if manifest is None or not Draft202012Validator(manifest["input_schema"]).is_valid(
            call.arguments
        ):
            raise ValidationError("Model tool arguments do not match Schema")
    if not proposal.tool_calls:
        final_output(proposal.output, spec.output_schema)
    return proposal
