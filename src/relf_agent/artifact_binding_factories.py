"""Scoped Artifact declarations reuse the original store registry and ownership."""

from .artifacts import InMemoryArtifactStore
from .binding_artifacts import ArtifactBindingResource
from .ports import is_async_callable
from .runtime_config import component_declaration


def register_artifact_bindings(registry):
    from .runtime_builder import _fields

    def memory_options(config):
        _fields(config, {"backend_id", "max_bytes", "capacity"})
        InMemoryArtifactStore(**config)

    registry.register(
        "artifact_store",
        "memory",
        lambda config, context: context.own(InMemoryArtifactStore(**config)),
        validator=memory_options,
    )


def prepare_artifact_binding(registry, declaration):
    from .errors import ValidationError
    from .runtime_builder import _completed, _fields

    config = declaration.get("config", {})
    _fields(config, {"backend", "version", "namespaces", "default_namespace", "sync_mode"})
    if "version" not in config:
        raise ValidationError("Artifact binding requires an explicit behavior version")
    options = {k: v for k, v in config.items() if k != "backend"}
    # Validate bounded ordinary resource options without connecting a store.
    ArtifactBindingResource(InMemoryArtifactStore(), **options)
    backend = component_declaration(config.get("backend", {"adapter": "memory"}))
    factory, settings = registry.prepare("artifact_store", backend)
    if is_async_callable(factory):

        async def construct(config, context):
            backend = _completed(await factory(config, context), "Artifact store factory")
            return ArtifactBindingResource(backend, **options)
    else:

        def construct(config, context):
            backend = _completed(factory(config, context), "Artifact store factory")
            return ArtifactBindingResource(backend, **options)

    return construct, settings
