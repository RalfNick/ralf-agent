"""Declarative Local policy values; the original Engine enforces them."""

from .errors import ValidationError
from .governance import LocalExecutionPolicy


def _policy(config):
    try:
        return LocalExecutionPolicy(**config)
    except TypeError:
        raise ValidationError("Invalid Local execution policy fields") from None


def register_local_execution_policy(registry):
    def validate(config):
        _policy(config)

    def build(config, context):
        return _policy(config)

    registry.register("execution_policy", "local-bounded", build, validator=validate)


def validate_local_policy_result(options):
    if (
        "execution_policy" in options
        and type(options["execution_policy"]) is not LocalExecutionPolicy
    ):
        raise ValidationError("Declared Local execution policy must return LocalExecutionPolicy")
