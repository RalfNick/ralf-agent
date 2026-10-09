"""Root conversation declarations borrow the existing execution connection."""

from .binding_sessions import SessionBindingResource, namespace_options
from .errors import ValidationError
from .memory import SQLiteMemory


def conversation_config(config):
    if set(config) - {"namespaces", "default_namespace"}:
        raise ValidationError("Unknown colocated conversation configuration fields")
    namespace_options(config.get("namespaces", [None]), config.get("default_namespace"))


def colocated_conversation(config, context):
    conversation_config(config)
    return SessionBindingResource(
        SQLiteMemory(context.store),
        namespaces=config.get("namespaces", [None]),
        default_namespace=config.get("default_namespace"),
    )
