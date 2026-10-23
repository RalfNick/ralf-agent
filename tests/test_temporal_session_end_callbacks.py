"""Session end callbacks pin actual SDK epoch and require a completed original ACK."""

import asyncio
import copy
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("temporalio")
from temporalio import activity

from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_activities import registered_activities
from relf_agent.types import digest


@pytest.mark.parametrize("name", ["managed_session", "session_root_read"])
@pytest.mark.parametrize(
    "fault", [None, "namespace-before", "namespace-after", "proof", "ack", "uuid-after"]
)
def test_original_session_end_keeps_four_field_proof_and_actual_epoch(monkeypatch, name, fault):
    async def run():
        original_info = NS(
            workflow_id="original-run",
            workflow_run_id="original-epoch",
            workflow_namespace="original",
        )
        monkeypatch.setattr(activity, "info", lambda: original_info)
        calls, callbacks = [], []
        client = NS(namespace="original")
        request = {
            "runtime_manifest": {},
            "scope": {"workspace": "w", "principal": "p"},
            "run_id": "original-run",
            "action_id": "original-action",
            "release_digest": "a" * 64,
        }
        if fault == "uuid-after":
            request["session_lineage"] = {"namespace_id": "original-uuid"}

        async def tree_guard(*args, **kwargs):
            pass

        monkeypatch.setattr(
            "relf_agent.temporal_session_activities.validate_tree_activity", tree_guard
        )

        async def namespace_id(current):
            return "original-uuid" if not calls else "different-uuid"

        monkeypatch.setattr("relf_agent.temporal_session_activities.namespace_id", namespace_id)

        async def execute(current, run_id, operation, proof, **options):
            calls.append((run_id, operation, copy.deepcopy(proof), options))
            assert current is client and options["execution_epoch"] == "original-epoch"
            assert options["legacy_update_id"] == "ralf-session-end:original-action"
            if fault == "namespace-after":
                client.namespace = "other"
            return {
                "action_id": proof["action_id"],
                "execution_stopped": 1 if fault == "ack" else True,
            }

        monkeypatch.setattr("relf_agent.temporal_execution_end_transport.execute", execute)

        async def capture(value, *, dispatch_guard, on_end):
            callbacks.append(on_end)
            return {"ok": True}

        runtime = NS(
            validate_release=lambda: None,
            model_continuation=False,
            coding_execution=False,
            manage_session=capture,
            prepare_session_root=capture,
        )
        functions = {f.__name__: f for f in registered_activities(runtime, client)}
        await functions[name](request)
        proof = {k: request[k] for k in ("scope", "action_id", "release_digest")} | {
            "request_digest": digest(request)
        }
        assert "execution_epoch" not in proof
        # An end runs outside the original observing Activity Task.
        original_info.workflow_run_id = "replacement-activity"
        if fault == "namespace-before":
            client.namespace = "other"
        if fault == "proof":
            proof["request_digest"] = "f" * 64
        if fault is None:
            assert await callbacks[0](proof) is None
            assert calls[0][0:2] == ("original-run", "session_execution_ended")
            assert calls[0][2] == proof
        else:
            with pytest.raises(DefinitionMismatch):
                await callbacks[0](proof)
            assert len(calls) == (0 if fault in {"namespace-before", "proof"} else 1)

    asyncio.run(run())
