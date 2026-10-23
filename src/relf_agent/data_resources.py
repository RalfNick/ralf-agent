"""Non-sensitive native data resource addresses for fixed Worker registrations."""


def remote_physical(backend):
    from .postgres import PostgresMemory
    from .redis_memory import RedisMemory

    if isinstance(backend, RedisMemory):
        pool = backend._client.connection_pool
        settings = pool.connection_kwargs
        return {
            "kind": "redis",
            "prefix": backend._prefix,
            "address": {k: settings[k] for k in ("host", "port", "db", "path") if k in settings},
            "connection_class": pool.connection_class.__module__
            + "."
            + pool.connection_class.__qualname__,
        }
    if isinstance(backend, PostgresMemory):
        info = backend.connection.info
        return {
            "kind": "postgres",
            "address": {k: getattr(info, k) for k in ("host", "port", "dbname")},
        }
    return {}
