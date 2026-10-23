"""Pure target derivation and disabled offload preserve existing Context stages."""

import copy

import pytest

import relf_agent as r
from relf_agent.data_context import ManagedDataContext
from relf_agent.errors import DefinitionMismatch, RalfError
from relf_agent.managed_context import ManagedContextPipeline

from .test_managed_data_context import history


def origin(**kwargs):
    return ManagedDataContext(
        r.InMemoryArtifactStore(backend_id="original"),
        tool_result_chars=1024,
        preview_chars=64,
        reference_chars=128,
        **kwargs,
    )


def view():
    cls = getattr(r, "ArtifactBindingResource", None)
    assert cls is not None
    return cls(
        r.InMemoryArtifactStore(backend_id="selected"),
        version="1",
        namespaces=["selected"],
        default_namespace="selected",
    ).select({}, r.Scope())


def bind(base, target):
    method = getattr(base, "bind_artifacts", None)
    assert callable(method), "Missing pure managed Artifact Context binding port"
    return method(target)


@pytest.mark.parametrize("mode", ["excerpt", "model"])
def test_pure_prediction_matches_realization_and_preserves_settings(mode):
    base = origin(
        mode=mode, provider="summary", timeout=3, summary_max_chars=128, source_max_chars=4096
    )
    target = view()
    before = copy.deepcopy(base.identity)
    selected = bind(base, target)
    assert isinstance(selected, ManagedDataContext) and selected.artifacts is target
    assert selected.namespace == "selected" and selected.scope == base.scope
    assert selected.identity == base.artifact_binding_identity(target.identity)
    assert base.identity == before and base.artifacts.backend_id == "original"
    assert (
        selected.mode,
        selected.provider,
        selected.timeout,
        selected.summary_max_chars,
        selected.source_max_chars,
    ) == (mode, "summary", 3, 128, 4096)
    assert selected._assembler is base._assembler
    messages, metadata = selected.assemble(history(), [], 2000)
    assert metadata["artifact_projection"][0]["reference"]["backend_id"] == "selected"
    assert metadata["artifact_projection"][0]["reference"]["namespace"] == "selected"
    assert messages[-1]["tool_call_id"] == "c"


@pytest.mark.parametrize("mode", ["excerpt", "model"])
def test_disabled_offload_retains_summary_and_reference_compression_without_store(mode):
    base = origin(mode=mode, provider="summary")
    disabled = bind(base, None)
    assert isinstance(disabled, ManagedContextPipeline) and not isinstance(
        disabled, ManagedDataContext
    )
    assert disabled.identity == base.artifact_binding_identity(None)
    assert not hasattr(disabled, "artifacts") and not hasattr(disabled, "offloads")
    references = [{"key": "doc", "version": 1, "value": "evidence" * 1000}]
    messages, metadata = disabled.assemble(history(), references, 12000)
    assert metadata["artifact_projection"] == [] and metadata["reference_compression"]
    assert messages[-1]["content"] == history()[-1]["content"]
    assert base.assemble(history(), [], 2000)[1]["artifact_projection"]
    assert (disabled.mode, disabled.provider, disabled.timeout) == (
        base.mode,
        base.provider,
        base.timeout,
    )


def test_binding_prediction_and_assembly_never_use_original_or_selected_backend():
    class NoIO(r.InMemoryArtifactStore):
        def put(self, *args, **kwargs):
            raise AssertionError("pure binding accessed store")

        def get(self, *args, **kwargs):
            raise AssertionError("pure binding accessed store")

    base = ManagedDataContext(NoIO(backend_id="old"), tool_result_chars=1024)
    cls = getattr(r, "ArtifactBindingResource", None)
    assert cls is not None
    target = cls(NoIO(backend_id="new"), version="1").select({}, r.Scope())
    selected = bind(base, target)
    assert selected.identity == base.artifact_binding_identity(target.identity)
    assert selected.offloads(history())
    assert selected.assemble(history(), [], 4000)[1]["artifact_projection"]


@pytest.mark.parametrize("field", ["origin", "target"])
def test_original_context_or_target_changes_refuse_before_projection(field):
    base = origin()
    target = view()
    selected = bind(base, target)
    if field == "origin":
        base.preview_chars += 1
    else:
        target._namespace = "foreign"
    with pytest.raises(DefinitionMismatch):
        selected.assemble(history(), [], 2000)


def test_foreign_scope_and_invalid_prediction_metadata_are_rejected():
    base = origin()
    cls = getattr(r, "ArtifactBindingResource", None)
    assert cls is not None
    target = cls(r.InMemoryArtifactStore(), version="1").select({}, r.Scope("foreign", "user"))
    with pytest.raises(RalfError):
        bind(base, target)
    for metadata in [[], {"kind": "other"}, {"kind": "artifact-binding-view", "backend_id": "x"}]:
        with pytest.raises(RalfError):
            base.artifact_binding_identity(metadata)


def test_disabled_finish_compresses_original_reference_once_and_keeps_summary_coverage():
    base = origin(summary_max_chars=64)
    disabled = bind(base, None)
    source = history() + [{"role": "assistant", "content": "last"}]
    # A larger completed first group supplies omitted history while the newest
    # group remains protected; disabled offload leaves tool evidence unmodified.
    references = [{"key": "doc", "version": 1, "value": "evidence" * 1000}]
    plan = disabled.prepare(source, references, 2500)
    assert plan is not None
    result, metadata = disabled.finish(plan, disabled.excerpt(plan))
    assert metadata["summary"]["group_digests"] == plan["coverage"]
    assert metadata["artifact_projection"] == [] and metadata["reference_compression"]
    assert "source_digest" in str(result) and "evidence_excerpt" in str(result)


def test_malformed_target_backend_metadata_is_typed_before_realization():
    base = origin()
    metadata = view().identity
    metadata["target"]["backend"] = []
    with pytest.raises(RalfError):
        base.artifact_binding_identity(metadata)


def test_custom_context_hooks_require_its_explicit_artifact_binding_port():
    class Custom(ManagedDataContext):
        def prepare(self, *args, **kwargs):
            return super().prepare(*args, **kwargs)

    base = Custom(r.InMemoryArtifactStore(backend_id="custom"))
    with pytest.raises(RalfError):
        bind(base, view())
