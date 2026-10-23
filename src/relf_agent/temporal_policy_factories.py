"""Pure configuration for limits enforced by the existing Temporal authority."""

from .errors import ValidationError
from .governance import TemporalExecutionPolicy


def _policy(config):
    try:
        return TemporalExecutionPolicy(**config)
    except TypeError:
        raise ValidationError("Invalid execution policy configuration fields") from None


def register_execution_policy(registry):
    def validate(config):
        _policy(config)

    def build(config, context):
        return _policy(config)

    registry.register("execution_policy", "bounded", build, validator=validate)
