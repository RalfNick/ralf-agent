import ralf_agent as r

from .composite_session_fixture import Provider


def engine(path, *, default="red", namespaces=(None, "red", "blue"), tools=None, provider=None):
    store = r.SQLiteStore(path)
    backend = r.SQLiteMemory(store)
    resource = r.SessionBindingResource(backend, namespaces=namespaces, default_namespace=default)
    return r.LocalEngine(
        store,
        providers={"default": provider or Provider()},
        tools=tools or r.ToolRegistry(),
        conversation_resource=resource,
    )
