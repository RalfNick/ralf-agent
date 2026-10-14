"""Portable policy declarations; admission remains in each execution authority."""

from .errors import ValidationError
from .governance import DeploymentAdmissionPolicy


def _policy(config):
    try:
        return DeploymentAdmissionPolicy(**config)
    except TypeError:
        raise ValidationError("Invalid deployment admission policy fields") from None


def register_admission_policy(registry):
    registry.register(
        "admission_policy",
        "bounded",
        lambda c, ctx: _policy(c),
        validator=lambda c: _policy(c) and None,
    )


def validate_admission_result(options):
    if (
        "admission_policy" in options
        and type(options["admission_policy"]) is not DeploymentAdmissionPolicy
    ):
        raise ValidationError("Admission policy factory must return DeploymentAdmissionPolicy")


def host_options(profile, policy):
    if policy is None:
        return {}
    if type(policy) is not DeploymentAdmissionPolicy:
        raise ValidationError("Host admission policy must be DeploymentAdmissionPolicy")
    if "admission_policy" in profile.components:
        raise ValidationError("Select one admission policy source: host or Profile")
    return {"admission_policy": policy}
