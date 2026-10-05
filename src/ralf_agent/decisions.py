"""Pure final-decision validation shared by adoption and node completion."""

import json

from jsonschema import Draft202012Validator

from .errors import ValidationError
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
