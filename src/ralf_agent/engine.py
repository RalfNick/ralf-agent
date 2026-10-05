"""Single-coordinator, durable native Agent and sequential Workflow execution."""

import asyncio
import copy
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from jsonschema import Draft202012Validator

from .context import ContextAssembler
from .errors import (
    AuthorizationDenied,
    CoordinatorBusy,
    DefinitionMismatch,
    RalfError,
    ValidationError,
)
from .memory import SQLiteMemory
from .tools import invoke
from .types import (
    AgentSpec,
    InvocationContext,
    ModelResponse,
    RunHandle,
    RunSnapshot,
    Scope,
    WorkflowSpec,
    canonical,
    digest,
)

TERMINAL = {"succeeded", "failed", "cancelled"}


class LocalEngine:
    def __init__(
        self,
        store,
        *,
        providers,
        tools,
        scope=None,
        session_store=None,
        memory_store=None,
        policy=None,
    ):
        self.store = store
        self.providers = dict(providers)
        self.tools = tools
        self.scope = scope or Scope()
        self.policy = policy
        self.owner = uuid.uuid4().hex
        self._active = set()
        self._inflight = {}
        self._locks = {}
        self._lock_file = None
        if store.path != ":memory:":
            try:
                import fcntl
            except ImportError as exc:
                raise ValidationError(
                    "File-backed LocalEngine currently requires POSIX file locks"
                ) from exc
            self._lock_file = open(str(Path(store.path).resolve()) + ".coordinator", "a+b")
            try:
                fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                self._lock_file.close()
                raise CoordinatorBusy("Another coordinator owns this execution database") from exc
        self._default_memory = SQLiteMemory(store)
        self.sessions = session_store or self._default_memory
        self.memory = memory_store or self._default_memory
        self.context = ContextAssembler()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._active or any(not task.done() for task in self._inflight.values()):
            raise ValidationError("Finish active drive tasks before closing the coordinator")
        self.store.close()
        if self._lock_file is not None:
            self._lock_file.close()
            self._lock_file = None

    def _authorized(self, run_id):
        run = self.store.run(run_id)
        if run["scope"] != asdict(self.scope):
            raise AuthorizationDenied("Run belongs to another workspace or principal")
        return run

    def status(self, run_id):
        run = self._authorized(run_id)
        pending = tuple(
            {
                "action_id": action["id"],
                "digest": action["digest"],
                "tool": action["tool"],
                "arguments": copy.deepcopy(action["arguments"]),
            }
            for action in run["actions"]
            if action["status"] == "waiting_approval"
        )
        return RunSnapshot(
            run_id,
            run["state"],
            run["revision"],
            run["result"],
            run["error"],
            pending,
            tuple(run["actions"]),
        )

    def events(self, run_id, *, after=0, limit=1000):
        self._authorized(run_id)
        return self.store.events(run_id, after, limit)

    def _manifest(self, steps):
        names = sorted({name for step in steps for name in step["tools"]})
        providers = {}
        for step in steps:
            provider = self.providers.get(step["provider"])
            if provider is None:
                raise DefinitionMismatch(f"Model provider not configured: {step['provider']}")
            providers[step["provider"]] = copy.deepcopy(provider.identity)
            if step["output_schema"] is not None:
                Draft202012Validator.check_schema(step["output_schema"])
        return {
            "kernel": "local-1",
            "tools": self.tools.manifests(names),
            "providers": providers,
            "session_backend": self.sessions.backend_id,
            "memory_backend": self.memory.backend_id,
        }

    def submit(self, spec, input, *, command_id, budget=32, session_id=None):
        if isinstance(spec, AgentSpec):
            definition = {
                "kind": "agent",
                "name": spec.name,
                "version": spec.version,
                "steps": [asdict(spec)],
            }
        elif isinstance(spec, WorkflowSpec):
            definition = {
                "kind": "sequence",
                "name": spec.name,
                "version": spec.version,
                "steps": [asdict(step) for step in spec.steps],
            }
        else:
            raise ValidationError("Submit an AgentSpec or sequential WorkflowSpec")
        manifest = self._manifest(definition["steps"])
        run_id = uuid.uuid4().hex
        payload = {
            "definition": definition,
            "manifest": manifest,
            "input": input,
            "budget": budget,
            "session_id": session_id,
        }
        # Validate the immutable task before accepting anything.
        canonical(payload)
        self.context.assemble(
            self._initial_messages(definition["steps"][0], input),
            [],
            definition["steps"][0]["max_context_chars"],
        )

        def apply():
            if session_id is not None:
                for row in self.store.conn.execute("SELECT data FROM runs"):
                    previous = json.loads(row[0])
                    if (
                        previous["scope"] == asdict(self.scope)
                        and previous["session_id"] == session_id
                        and previous["state"] not in TERMINAL
                    ):
                        raise ValidationError("Session already belongs to an active Run")
            data = {
                "id": run_id,
                "revision": 0,
                "scope": asdict(self.scope),
                "state": "queued",
                "definition": definition,
                "manifest": manifest,
                "release_digest": digest({"definition": definition, "manifest": manifest}),
                "input": input,
                "result": None,
                "error": None,
                "node": 0,
                "decisions": 0,
                "actions": [],
                "messages": self._initial_messages(definition["steps"][0], input),
                "session_id": session_id or run_id,
            }
            self.store.insert_run(data)
            self.store.create_budget(run_id, budget)
            self.store.emit(run_id, "run_submitted", {"release_digest": data["release_digest"]})
            return {"state_revision": 0}

        receipt = self.store.command(self.scope, command_id, "submit", payload, run_id, apply)
        return RunHandle(receipt.run_id, receipt)

    @staticmethod
    def _initial_messages(step, input):
        return [
            {"role": "system", "content": step["instructions"]},
            {"role": "user", "content": input if isinstance(input, str) else canonical(input)},
        ]

    def approve(self, run_id, action_id, target_digest, *, command_id, approved=True):
        self._authorized(run_id)

        def apply():
            run = self._authorized(run_id)
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                return {"rejected": True, "reason": "target_closed"}
            action = next((a for a in run["actions"] if a["id"] == action_id), None)
            if (
                action is None
                or action["status"] != "waiting_approval"
                or action["digest"] != target_digest
            ):
                raise ValidationError("Approval does not match the pending operation")
            action["approved"] = approved
            action["status"] = "ready" if approved else "failed"
            run["state"] = "running" if approved else "failed"
            if not approved:
                run["error"] = {"code": "approval_rejected"}
            self.store.save_run(run)
            self.store.emit(
                run_id,
                "approval_applied",
                {"action_id": action_id, "digest": target_digest, "approved": approved},
            )
            return {"state_revision": run["revision"]}

        return self.store.command(
            self.scope,
            command_id,
            "approve",
            {
                "run_id": run_id,
                "action_id": action_id,
                "digest": target_digest,
                "approved": approved,
            },
            run_id,
            apply,
        )

    def cancel(self, run_id, *, command_id):
        self._authorized(run_id)

        def apply():
            run = self._authorized(run_id)
            if run["state"] in {"succeeded", "failed"}:
                return {"rejected": True, "reason": "too_late"}
            if run["state"] in {"cancelled", "cancelling"}:
                return {
                    "reason": "already_terminal" if run["state"] == "cancelled" else "applied_noop"
                }
            run["state"] = "cancelling" if run_id in self._active else "cancelled"
            self.store.save_run(run)
            self.store.emit(run_id, "cancel_applied", {"state": run["state"]})
            return {"state_revision": run["revision"]}

        return self.store.command(
            self.scope, command_id, "cancel", {"run_id": run_id}, run_id, apply
        )

    def reconcile(self, run_id, action_id, result, *, command_id):
        """Local owner's explicit confirmation of an already-completed external effect."""
        self._authorized(run_id)
        canonical(result)

        def apply():
            run = self._authorized(run_id)
            action = next((a for a in run["actions"] if a["id"] == action_id), None)
            if action is None or action["kind"] != "tool" or action["status"] != "outcome_unknown":
                raise ValidationError("No unknown tool effect to reconcile")
            self._tool_result(
                run, action, result, {"source": "local-owner", "command_id": command_id}
            )
            if run["state"] not in TERMINAL and run["state"] != "cancelling":
                run["state"] = "running"
            self.store.save_run(run)
            self.store.emit(
                run_id, "effect_reconciled", {"action_id": action_id, "source": "local-owner"}
            )
            return {"state_revision": run["revision"]}

        return self.store.command(
            self.scope,
            command_id,
            "reconcile",
            {"run_id": run_id, "action_id": action_id, "result": result},
            run_id,
            apply,
        )

    def _check_release(self, run):
        if digest(self._manifest(run["definition"]["steps"])) != digest(run["manifest"]):
            raise DefinitionMismatch(
                "Pinned tool, provider or memory backend differs from this Run"
            )

    def _commit(self, run, kind, data=None):
        self.store.save_run(run)
        self.store.emit(run["id"], kind, data)

    def _fail(self, run_id, code):
        with self.store.transaction():
            run = self._authorized(run_id)
            if run["state"] not in TERMINAL:
                run["state"] = "cancelled" if run["state"] == "cancelling" else "failed"
                run["error"] = {"code": code}
                self._commit(run, "run_failed", {"code": code})

    async def drive(self, run_id):
        if run_id in self._inflight and not self._inflight[run_id].done():
            raise CoordinatorBusy("The previous Action is still running; wait for its result")
        lock = self._locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            run = self._authorized(run_id)
            if run["state"] in TERMINAL:
                return self.status(run_id)
            self._check_release(run)
            self._active.add(run_id)
            try:
                with self.store.transaction():
                    run = self._authorized(run_id)
                    for action in run["actions"]:
                        if action["status"] == "executing":
                            action["status"] = "outcome_unknown"
                            action["attempts"][-1]["status"] = "unknown"
                            self.store.mark_unknown(action["attempts"][-1]["id"])
                    if run["state"] != "cancelling":
                        run["state"] = "running"
                    self._commit(run, "run_resumed")
                while True:
                    run = self._authorized(run_id)
                    if run["state"] in TERMINAL:
                        break
                    if run["state"] == "cancelling":
                        with self.store.transaction():
                            run["state"] = "cancelled"
                            self._commit(run, "run_cancelled")
                        break
                    pending = next(
                        (
                            a
                            for a in run["actions"]
                            if a["node"] == run["node"]
                            and a["kind"] == "tool"
                            and a["status"] != "completed"
                        ),
                        None,
                    )
                    if pending:
                        if not await self._guarded(run_id, self._tool(run_id, pending["id"])):
                            break
                    else:
                        adopted = next(
                            (
                                a
                                for a in reversed(run["actions"])
                                if a["node"] == run["node"]
                                and a["kind"] == "model"
                                and a["status"] == "completed"
                            ),
                            None,
                        )
                        if adopted and not adopted["response"]["tool_calls"]:
                            self._finish_node(run_id, adopted["response"]["output"])
                        else:
                            if not await self._guarded(run_id, self._model(run_id)):
                                break
                return self.status(run_id)
            except RalfError as exc:
                self._fail(run_id, exc.code)
                return self.status(run_id)
            finally:
                self._active.discard(run_id)

    async def _guarded(self, run_id, operation):
        # Caller cancellation must not discard an in-flight effect or free its coordinator.
        task = asyncio.create_task(operation)
        self._inflight[run_id] = task
        task.add_done_callback(
            lambda finished: None if finished.cancelled() else finished.exception()
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            self.cancel(run_id, command_id=f"drive-cancel:{uuid.uuid4().hex}")
            raise

    def _finish_node(self, run_id, result):
        run = self._authorized(run_id)
        step = run["definition"]["steps"][run["node"]]
        if step["output_schema"] is not None:
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except ValueError as exc:
                    raise ValidationError("Model output is not valid JSON") from exc
            if not Draft202012Validator(step["output_schema"]).is_valid(result):
                raise ValidationError("Model output does not match the required Schema")
        revision, _ = self.sessions.read(self.scope, run["session_id"])
        self.sessions.append(
            self.scope,
            run["session_id"],
            {"role": "assistant", "content": result, "task": run["input"], "agent": step["name"]},
            expected_revision=revision,
            message_id=f"{run_id}:{run['node']}:result",
        )
        with self.store.transaction():
            run = self._authorized(run_id)
            run["node"] += 1
            if run["node"] == len(run["definition"]["steps"]):
                run["state"] = "succeeded"
                run["result"] = result
                self._commit(run, "run_succeeded")
            else:
                run["decisions"] = 0
                run["messages"] = self._initial_messages(
                    run["definition"]["steps"][run["node"]], result
                )
                self._commit(run, "workflow_node_completed", {"node": run["node"] - 1})

    async def _model(self, run_id):
        run = self._authorized(run_id)
        step = run["definition"]["steps"][run["node"]]
        existing = next(
            (
                a
                for a in run["actions"]
                if a["node"] == run["node"] and a["kind"] == "model" and a["status"] != "completed"
            ),
            None,
        )
        if existing is None and run["decisions"] >= step["max_decisions"]:
            raise ValidationError("Agent decision limit reached")
        self._check_release(run)
        if existing:
            action = existing
            messages = copy.deepcopy(action["snapshot"])
        else:
            _, session = self.sessions.read(self.scope, run["session_id"])
            references = self.memory.facts(self.scope, step["name"]) + (
                [{"session": session}] if session else []
            )
            messages, manifest = self.context.assemble(
                run["messages"], references, step["max_context_chars"]
            )
            action = {
                "id": uuid.uuid4().hex,
                "kind": "model",
                "node": run["node"],
                "status": "ready",
                "snapshot": messages,
                "context_manifest": manifest,
                "attempts": [],
            }
        attempt_id = f"{action['id']}:{len(action['attempts']) + 1}"
        with self.store.transaction():
            self.store.reserve(run_id, attempt_id, step["model_credits"])
            action["attempts"].append({"id": attempt_id, "status": "executing"})
            action["status"] = "executing"
            if existing is None:
                run["actions"].append(action)
                run["decisions"] += 1
            self._commit(
                run, "model_dispatched", {"action_id": action["id"], "attempt_id": attempt_id}
            )
        try:
            response = await self.providers[step["provider"]].complete(
                copy.deepcopy(messages), self.tools.descriptions(step["tools"])
            )
            if not isinstance(response, ModelResponse):
                raise ValidationError("Model provider must return ModelResponse")
            encoded = asdict(response)
            canonical(encoded)
            proposals = []
            call_ids = set()
            for call in response.tool_calls:
                if call.name not in step["tools"]:
                    raise AuthorizationDenied("Model requested a tool outside AgentSpec")
                tool = self.tools.get(call.name)
                tool.validate(call.arguments)
                action_id = uuid.uuid4().hex
                call_id = call.call_id or action_id
                if call_id in call_ids:
                    raise ValidationError("Duplicate model tool-call identity")
                call_ids.add(call_id)
                operation = {
                    "run_id": run_id,
                    "action_id": action_id,
                    "tool": tool.manifest,
                    "arguments": call.arguments,
                    "scope": asdict(self.scope),
                }
                proposals.append(
                    {
                        "id": action_id,
                        "kind": "tool",
                        "node": run["node"],
                        "tool": call.name,
                        "arguments": copy.deepcopy(call.arguments),
                        "digest": digest(operation),
                        "effect_key": f"{self.scope.workspace}:{run_id}:{action_id}",
                        "call_id": call_id,
                        "approved": False,
                        "status": "ready",
                        "attempts": [],
                    }
                )
            with self.store.transaction():
                run = self._authorized(run_id)
                action = next(a for a in run["actions"] if a["id"] == action["id"])
                action["response"] = encoded
                action["status"] = "completed"
                action["attempts"][-1]["status"] = "completed"
                self.store.settle(
                    attempt_id, step["model_credits"], response.usage or {"usage": "unknown"}
                )
                if run["state"] != "cancelling":
                    run["actions"].extend(proposals)
                    if proposals:
                        run["messages"].append(
                            {
                                "role": "assistant",
                                "content": response.output
                                if isinstance(response.output, str)
                                else None,
                                "tool_calls": [
                                    {
                                        "id": a["call_id"],
                                        "type": "function",
                                        "function": {
                                            "name": a["tool"],
                                            "arguments": canonical(a["arguments"]),
                                        },
                                    }
                                    for a in proposals
                                ],
                            }
                        )
                self._commit(
                    run,
                    "decision_adopted",
                    {
                        "action_id": action["id"],
                        "proposed_actions": [a["id"] for a in proposals]
                        if run["state"] != "cancelling"
                        else [],
                    },
                )
            return True
        except Exception as exc:
            with self.store.transaction():
                run = self._authorized(run_id)
                action = next(a for a in run["actions"] if a["id"] == action["id"])
                action["status"] = "outcome_unknown"
                action["attempts"][-1]["status"] = "unknown"
                self.store.mark_unknown(attempt_id)
                run["error"] = {
                    "code": exc.code if isinstance(exc, RalfError) else "model_call_unknown"
                }
                run["state"] = (
                    "cancelled"
                    if run["state"] == "cancelling"
                    else "failed"
                    if isinstance(exc, (ValidationError, AuthorizationDenied))
                    else "waiting_reconciliation"
                )
                self._commit(run, "model_attempt_unknown", {"action_id": action["id"]})
            return False

    def _tool_result(self, run, action, result, receipt):
        canonical(result)
        action["status"] = "completed"
        action["result"] = copy.deepcopy(result)
        action["receipt"] = receipt
        if action["attempts"]:
            attempt = action["attempts"][-1]
            attempt["status"] = "completed"
            self.store.settle(
                attempt["id"], self.tools.get(action["tool"]).spec.cost, {"effect": "confirmed"}
            )
        run["messages"].append(
            {"role": "tool", "tool_call_id": action["call_id"], "content": canonical(result)}
        )

    async def _tool(self, run_id, action_id):
        run = self._authorized(run_id)
        action = next(a for a in run["actions"] if a["id"] == action_id)
        tool = self.tools.get(action["tool"])
        self._check_release(run)
        tool.validate(action["arguments"])
        if self.policy is not None:
            self.policy(self.scope, tool.spec, copy.deepcopy(action["arguments"]))
        if tool.spec.effect != "read_only":
            for row in self.store.conn.execute("SELECT data FROM runs"):
                previous = json.loads(row[0])
                if previous["scope"] != run["scope"]:
                    continue
                unresolved = next(
                    (
                        a
                        for a in previous["actions"]
                        if a["kind"] == "tool"
                        and a["id"] != action_id
                        and a["tool"] == action["tool"]
                        and a["status"] == "outcome_unknown"
                        and a["arguments"] == action["arguments"]
                    ),
                    None,
                )
                if unresolved:
                    with self.store.transaction():
                        run["state"] = "waiting_reconciliation"
                        run["error"] = {
                            "code": "prior_effect_unknown",
                            "run_id": previous["id"],
                            "action_id": unresolved["id"],
                        }
                        self._commit(run, "prior_effect_blocks_write", run["error"])
                    return False
        if tool.spec.requires_approval and not action["approved"]:
            with self.store.transaction():
                action["status"] = "waiting_approval"
                run["state"] = "waiting_approval"
                self._commit(
                    run, "approval_requested", {"action_id": action_id, "digest": action["digest"]}
                )
            return False
        context = InvocationContext(
            self.scope,
            run_id,
            action_id,
            action["attempts"][-1]["id"] if action["attempts"] else "",
            action["effect_key"],
            self.owner,
        )
        if action["status"] == "outcome_unknown":
            if tool.reconciler is not None:
                try:
                    result = await invoke(tool.reconciler, action["arguments"], context)
                except Exception:
                    result = None
                if result is not None:
                    with self.store.transaction():
                        run = self._authorized(run_id)
                        action = next(a for a in run["actions"] if a["id"] == action_id)
                        self._tool_result(run, action, result, {"source": "tool-reconciler"})
                        self._commit(run, "effect_reconciled", {"action_id": action_id})
                    return True
            if tool.spec.effect not in {"read_only", "idempotent_write"}:
                with self.store.transaction():
                    run = self._authorized(run_id)
                    if run["state"] != "cancelling":
                        run["state"] = "waiting_reconciliation"
                    self._commit(run, "effect_unknown", {"action_id": action_id})
                return False
        attempt_id = f"{action_id}:{len(action['attempts']) + 1}"
        with self.store.transaction():
            run = self._authorized(run_id)
            if run["state"] == "cancelling" or run["state"] in TERMINAL:
                return True
            action = next(a for a in run["actions"] if a["id"] == action_id)
            self.store.reserve(run_id, attempt_id, tool.spec.cost)
            action["attempts"].append({"id": attempt_id, "status": "executing"})
            action["status"] = "executing"
            self._commit(
                run,
                "tool_dispatch_intent",
                {
                    "action_id": action_id,
                    "attempt_id": attempt_id,
                    "digest": action["digest"],
                    "effect_key": action["effect_key"],
                },
            )
        context = InvocationContext(
            self.scope, run_id, action_id, attempt_id, action["effect_key"], self.owner
        )
        try:
            result = await invoke(tool.handler, action["arguments"], context)
            with self.store.transaction():
                run = self._authorized(run_id)
                action = next(a for a in run["actions"] if a["id"] == action_id)
                self._tool_result(
                    run, action, result, {"source": "tool-handler", "attempt_id": attempt_id}
                )
                self._commit(run, "tool_result_committed", {"action_id": action_id})
            return True
        except Exception:
            with self.store.transaction():
                run = self._authorized(run_id)
                action = next(a for a in run["actions"] if a["id"] == action_id)
                action["status"] = "outcome_unknown"
                action["attempts"][-1]["status"] = "unknown"
                self.store.mark_unknown(attempt_id)
                run["state"] = (
                    "cancelled" if run["state"] == "cancelling" else "waiting_reconciliation"
                )
                self._commit(run, "effect_unknown", {"action_id": action_id})
            return False
