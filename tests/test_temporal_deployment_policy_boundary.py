"""Policy snapshots cannot run identity callbacks after their final release check."""

import pytest

from relf_agent import DeploymentAdmissionPolicy, Scope, TemporalRuntime, ToolRegistry
from relf_agent.binding_catalog import BindingCatalog
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_deployment_execution import _policy
from tests.test_temporal_deployment_public_registry import Provider


@pytest.mark.parametrize("mutate_at", range(1, 17))
def test_policy_identity_cannot_replace_provider_after_final_validation(monkeypatch, mutate_at):
    policy = DeploymentAdmissionPolicy("policy-boundary")
    expected = policy.identity
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        admission_policy=policy,
        binding_catalog=BindingCatalog(scope=Scope()),
    )
    assert runtime.manifest["kernel"] == "temporal-3"
    identity = DeploymentAdmissionPolicy.identity.fget
    reads, changed = 0, False

    def changing_identity(self):
        nonlocal reads, changed
        reads += 1
        if reads == mutate_at:
            runtime.providers["default"] = Provider()
            changed = True
        return identity(self)

    monkeypatch.setattr(DeploymentAdmissionPolicy, "identity", property(changing_identity))
    try:
        result = _policy(runtime, expected=runtime.manifest)
    except DefinitionMismatch:
        assert changed
    else:
        assert not changed, "Policy accepted an identity callback replacing a pinned provider"
        assert result == expected
