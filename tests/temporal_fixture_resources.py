"""Release test-owned client sockets only after the original runtime loop ends.

This does not finish Runtime.close, release leases, retire roots or remove data.
In-loop recovery continues to use the exact original clients.
"""

import asyncio
import json
from pathlib import Path


class RetainedConnections:
    def __init__(self):
        self.entries = []

    def retain(self, connection, loop, processes, directory):
        if not any(item[0] is connection for item in self.entries):
            self.entries.append((connection, loop, list(processes), Path(directory)))

    def finish(self):
        # Validate every owner before detaching any client.
        for _, loop, processes, _ in self.entries:
            if not loop.is_closed() or any(p.poll() is None for p in processes):
                raise RuntimeError("Retained fixture still has an active loop or Worker")
        while self.entries:
            connection, _, _, directory = self.entries[0]
            if not connection.closed:
                asyncio.run(connection.close())
            path = directory / "retained-client-detached.json"
            path.write_text(
                json.dumps(
                    {
                        "original_loop_closed": True,
                        "owned_workers_exited": True,
                        "connection_closed": connection.closed,
                        "runtime_close_not_asserted": True,
                        "execution_evidence_unchanged": True,
                    },
                    sort_keys=True,
                )
            )
            path.chmod(0o600)
            self.entries.pop(0)


retained = RetainedConnections()


def retain_assembly_clients(assembly, processes, directory):
    from ralf_agent.temporal_journal import PostgresEffectJournal

    if assembly is None or getattr(assembly, "_closed", False):
        return
    context = getattr(assembly, "_context", None)
    loop = getattr(assembly, "_loop", None)
    if context is None or loop is None:
        return
    for owned in context._resources:
        resource = owned.resource
        if type(resource) is PostgresEffectJournal and resource._owns_connection:
            retained.retain(resource.connection, loop, processes, directory)
