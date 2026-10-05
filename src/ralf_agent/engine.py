"""Single-coordinator, durable native Agent and sequential Workflow execution."""

import asyncio
import copy
import inspect
import uuid
from collections.abc import Callable
from dataclasses import asdict

from jsonschema import Draft202012Validator

from .context import ContextAssembler
from .decisions import final_output
from .errors import (
    AuthorizationDenied,
    CoordinatorBusy,
    DefinitionMismatch,
    RalfError,
    ValidationError,
)
from .memory import memory_call
from .ports import ContextBuilder, CoordinatorLease, ExecutionStore
from .tools import (
    ThreadExecutionTracker,
    ToolSpec,
    current_thread_group,
    current_thread_tracker,
    invoke,
)
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
        store: ExecutionStore,
        *,
        providers,
        tools,
        scope=None,
        session_store=None,
        memory_store=None,
        policy: Callable[[Scope, ToolSpec, dict], None] | None = None,
        coordinator: CoordinatorLease | None = None,
        context_assembler: ContextBuilder | None = None,
    ):
        # Python 3.12's Protocol isinstance check ignores proxy __getattr__.
        # Validate the declared public operations so delegating adapters work too.
        if any(
            not callable(getattr(store, name, None))
            for name in vars(ExecutionStore)
            if not name.startswith("_")
        ):
            raise ValidationError("Store must implement the version 1 ExecutionStore port")
        self._validate_policy(policy)
        self.store = store
        self.providers = dict(providers)
        self.tools = tools
        self.scope = scope or Scope()
        self.policy = policy
        self.owner = uuid.uuid4().hex
        self._active = set()
        self._inflight = {}
        self._locks = {}
        self._drive_users = {}
        self._threads = ThreadExecutionTracker()
        self._lifecycle = "open"
        if coordinator is None:
            factory = getattr(store, "create_coordinator", None)
            if factory is None:
                raise ValidationError(
                    "Custom execution stores require an explicit coordinator lease"
                )
            coordinator = factory()
        if not all(callable(getattr(coordinator, name, None)) for name in ("acquire", "release")):
            raise ValidationError("Coordinator must implement acquire and release")
        self.coordinator = coordinator
        self.coordinator.acquire()
        try:
            self._default_memory = None
            if session_store is None or memory_store is None:
                factory = getattr(store, "create_memory", None)
                if factory is None:
                    raise ValidationError(
                        "Custom stores require explicit session_store and memory_store"
                    )
                self._default_memory = factory()
            self.sessions = self._default_memory if session_store is None else session_store
            self.memory = self._default_memory if memory_store is None else memory_store
            for backend, methods in (
                (self.sessions, ("read", "append")),
                (self.memory, ("facts",)),
            ):
                if (
                    not isinstance(getattr(backend, "backend_id", None), str)
                    or not backend.backend_id
                ):
                    raise ValidationError("Memory backends require a non-empty stable backend_id")
                if any(not callable(getattr(backend, name, None)) for name in methods):
                    raise ValidationError("Memory backend does not implement its configured port")
            self.context = ContextAssembler() if context_assembler is None else context_assembler
            if (
                not callable(getattr(self.context, "assemble", None))
                or not isinstance(getattr(self.context, "identity", None), dict)
                or not self.context.identity
            ):
                raise ValidationError("Context assembler requires identity and assemble")
            canonical(self.context.identity)
        except BaseException:
            self.coordinator.release()
            raise

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._lifecycle == "closed":
            return
        if self._lifecycle == "closing":
            raise ValidationError("Engine is already closing")
        if (
            self._drive_users
            or any(not task.done() for task in self._inflight.values())
            or self._threads.has_active
        ):
            raise ValidationError(
                "Finish active drive tasks and synchronous calls before closing the coordinator"
            )
        if self._lifecycle != "store_closed":
            self._lifecycle = "closing"
            try:
                self.store.close()
            except BaseException:
                self._lifecycle = "close_failed"
                raise
            self._lifecycle = "store_closed"
        # A failed close keeps ownership and permits only a close retry. Once
        # storage is closed, a failed lease release must not reopen the Engine.
        self.coordinator.release()
        self._lifecycle = "closed"

    async def wait_for_threads(self):
        """Wait for owned synchronous calls; this does not cancel drive tasks."""
        await self._threads.drain()

    def _ensure_open(self):
        if self._lifecycle != "open":
            raise ValidationError("Engine is not open; only close may be retried")

    def _operation_active(self, run_id):
        task = self._inflight.get(run_id)
        return (task is not None and not task.done()) or self._threads.has_active_for(run_id)

    def _authorized(self, run_id):
        self._ensure_open()
        run = self.store.run(run_id)
        if run["scope"] != asdict(self.scope):
            raise AuthorizationDenied("Run belongs to another workspace or principal")
        return run

    @staticmethod
    def _validate_policy(policy):
        # Inspect async callable instances as well as ordinary async functions.
        method = getattr(policy, "__call__", None)  # noqa: B004
        if policy is not None and (
            not callable(policy)
            or any(
                inspect.iscoroutinefunction(candidate)
                or inspect.isasyncgenfunction(candidate)
                or inspect.isgeneratorfunction(candidate)
                for candidate in (policy, method)
            )
        ):
            raise ValidationError("Authorization policy must execute synchronously")

    def status(self, run_id):
        return RunSnapshot.from_record(self._authorized(run_id))

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
            if not inspect.iscoroutinefunction(getattr(provider, "complete", None)):
                raise ValidationError("ModelProvider.complete must be an async method")
            if not isinstance(getattr(provider, "identity", None), dict) or not provider.identity:
                raise ValidationError("ModelProvider.identity must be a non-empty JSON object")
            providers[step["provider"]] = copy.deepcopy(provider.identity)
            if step["output_schema"] is not None:
                Draft202012Validator.check_schema(step["output_schema"])
        return {
            "kernel": "local-3",
            "tools": self.tools.manifests(names),
            "providers": providers,
            "session_backend": self.sessions.backend_id,
            "memory_backend": self.memory.backend_id,
            "context_builder": copy.deepcopy(self.context.identity),
        }

    def _assemble_context(self, history, references, max_chars):
        try:
            messages, manifest = self.context.assemble(history, references, max_chars)
        except RalfError:
            raise
        except Exception as exc:
            raise ValidationError("Context assembler failed to build a valid snapshot") from exc
        if not isinstance(messages, list) or not isinstance(manifest, dict):
            raise ValidationError("Context assembler must return messages and a JSON manifest")
        size = len(canonical(messages))
        if size > max_chars:
            raise ValidationError("Context assembler exceeded the configured character limit")
        manifest = {**manifest, "digest": digest(messages), "chars": size}
        canonical(manifest)
        return messages, manifest

    def submit(self, spec, input, *, command_id, budget=32, session_id=None):
        self._ensure_open()
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
        run_id = uuid.uuid4().hex
        payload = {
            "definition": definition,
            "input": copy.deepcopy(input),
            "budget": budget,
            "session_id": session_id,
        }
        # Request identity contains only caller-controlled data. Configuration
        # aliases are resolved inside first acceptance, after receipt lookup.
        canonical(payload)

        def apply():
            manifest = self._manifest(definition["steps"])
            self._assemble_context(
                self._initial_messages(definition["steps"][0], payload["input"]),
                [],
                definition["steps"][0]["max_context_chars"],
            )
            if session_id is not None and self.store.session_owner(self.scope, session_id):
                raise ValidationError("Session already belongs to an active Run")
            data = {
                "id": run_id,
                "revision": 0,
                "scope": asdict(self.scope),
                "state": "queued",
                "definition": definition,
                "manifest": manifest,
                "release_digest": digest({"definition": definition, "manifest": manifest}),
                "input": payload["input"],
                "result": None,
                "error": None,
                "node": 0,
                "decisions": 0,
                "actions": [],
                "messages": self._initial_messages(definition["steps"][0], payload["input"]),
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
            active = run_id in self._active or self._operation_active(run_id)
            if not active and self._normalize_abandoned(run):
                self._commit(run, "abandoned_attempts_unknown")
            if run["state"] in {"succeeded", "failed"}:
                return {"rejected": True, "reason": "too_late"}
            if run["state"] in {"cancelled", "cancelling"}:
                return {
                    "reason": "already_terminal" if run["state"] == "cancelled" else "applied_noop"
                }
            run["state"] = "cancelling" if active else "cancelled"
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

    def _normalize_abandoned(self, run):
        changed = False
        for action in run["actions"]:
            if action["status"] == "executing":
                action["status"] = "outcome_unknown"
                action["attempts"][-1]["status"] = "unknown"
                self.store.mark_unknown(action["attempts"][-1]["id"])
                changed = True
        return changed

    def _fail(self, run_id, code):
        with self.store.transaction():
            run = self._authorized(run_id)
            if run["state"] not in TERMINAL:
                run["state"] = "cancelled" if run["state"] == "cancelling" else "failed"
                run["error"] = {"code": code}
                self._commit(run, "run_failed", {"code": code})

    async def drive(self, run_id):
        self._ensure_open()
        if self._operation_active(run_id):
            raise CoordinatorBusy("The previous Action is still running; wait for its result")
        lock = self._locks.setdefault(run_id, asyncio.Lock())
        self._drive_users[run_id] = self._drive_users.get(run_id, 0) + 1
        try:
            async with lock:
                return await self._drive_locked(run_id)
        finally:
            users = self._drive_users[run_id] - 1
            if users:
                self._drive_users[run_id] = users
            else:
                self._drive_users.pop(run_id)
            self._cleanup_execution(run_id)

    def _cleanup_execution(self, run_id):
        task = self._inflight.get(run_id)
        if task is not None and task.done():
            self._inflight.pop(run_id)
        # Count owners and queued callers, including cancelled waiters. Removing
        # a lock with waiters would let a new caller create a second Run owner.
        if run_id not in self._drive_users and run_id not in self._inflight:
            self._locks.pop(run_id, None)

    async def _drive_locked(self, run_id):
        # A queued caller may have passed the check between two Actions while
        # another drive still owned this lock. Recheck before recovery mutates
        # any attempt: a shielded executor may still be alive after caller cancellation.
        if self._operation_active(run_id):
            raise CoordinatorBusy("The previous Action is still running; wait for its result")
        run = self._authorized(run_id)
        if run["state"] in TERMINAL:
            with self.store.transaction():
                if self._normalize_abandoned(run):
                    self._commit(run, "abandoned_attempts_unknown")
            return self.status(run_id)
        self._check_release(run)
        self._active.add(run_id)
        try:
            with self.store.transaction():
                run = self._authorized(run_id)
                self._normalize_abandoned(run)
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
                        if self._authorized(run_id)["state"] == "cancelling":
                            continue
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
                        await self._guarded(
                            run_id, self._finish_node(run_id, adopted["response"]["output"])
                        )
                    else:
                        if not await self._guarded(run_id, self._model(run_id)):
                            if self._authorized(run_id)["state"] == "cancelling":
                                continue
                            break
            return self.status(run_id)
        except RalfError as exc:
            self._fail(run_id, exc.code)
            return self.status(run_id)
        finally:
            self._active.discard(run_id)

    async def _guarded(self, run_id, operation):
        # Caller cancellation must not discard an in-flight effect or free its coordinator.
        tracker_token = current_thread_tracker.set(self._threads)
        group_token = current_thread_group.set(run_id)
        try:
            task = asyncio.create_task(operation)
        finally:
            current_thread_group.reset(group_token)
            current_thread_tracker.reset(tracker_token)
        self._inflight[run_id] = task

        def completed(finished):
            if not finished.cancelled():
                finished.exception()
            if self._inflight.get(run_id) is finished:
                self._inflight.pop(run_id)
            self._cleanup_execution(run_id)

        task.add_done_callback(completed)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            self.cancel(run_id, command_id=f"drive-cancel:{uuid.uuid4().hex}")
            raise

    async def _finish_node(self, run_id, result):
        run = self._authorized(run_id)
        if run["state"] in TERMINAL or run["state"] == "cancelling":
            return
        step = run["definition"]["steps"][run["node"]]
        result = final_output(result, step["output_schema"])
        sessions = self.sessions
        revision, _ = await memory_call(sessions.read, self.scope, run["session_id"])
        current = self._authorized(run_id)
        if current["state"] in TERMINAL or current["state"] == "cancelling":
            return
        self._check_release(current)
        if sessions.backend_id != current["manifest"]["session_backend"]:
            raise DefinitionMismatch("The executing session backend differs from this Run")
        await memory_call(
            sessions.append,
            self.scope,
            run["session_id"],
            {"role": "assistant", "content": result, "task": run["input"], "agent": step["name"]},
            expected_revision=revision,
            message_id=f"{run_id}:{run['node']}:result",
        )
        with self.store.transaction():
            run = self._authorized(run_id)
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                return
            # An append may already have committed externally. A changed backend
            # cannot be silently confirmed as completing the pinned Release.
            self._check_release(run)
            if sessions.backend_id != run["manifest"]["session_backend"]:
                raise DefinitionMismatch("The executing session backend differs from this Run")
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
        if run["state"] in TERMINAL or run["state"] == "cancelling":
            return True
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
            _, session = await memory_call(self.sessions.read, self.scope, run["session_id"])
            references = await memory_call(self.memory.facts, self.scope, step["name"])
            references = references + ([{"session": session}] if session else [])
            messages, manifest = self._assemble_context(
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
            run = self._authorized(run_id)
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                return True
            self._check_release(run)
            if existing is not None:
                action = next(a for a in run["actions"] if a["id"] == action["id"])
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
            self._check_release(self._authorized(run_id))
            if not isinstance(response, ModelResponse):
                raise ValidationError("Model provider must return ModelResponse")
            encoded = asdict(response)
            canonical(encoded)
            if not response.tool_calls:
                final_output(response.output, step["output_schema"])
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
                if run["state"] not in TERMINAL:
                    run["state"] = (
                        "cancelled"
                        if run["state"] == "cancelling"
                        else "failed"
                        if isinstance(
                            exc, (ValidationError, AuthorizationDenied, DefinitionMismatch)
                        )
                        else "waiting_reconciliation"
                    )
                self._commit(run, "model_attempt_unknown", {"action_id": action["id"]})
            return False

    def _tool_result(self, run, action, result, receipt):
        canonical(result)
        if action["status"] == "completed":
            # Evidence can arrive from a handler, automatic query and operator
            # concurrently. The first ResultCommit is immutable; later evidence
            # is retained for audit without remerging the model's tool message.
            self.store.emit(
                run["id"],
                "late_effect_evidence",
                {
                    "action_id": action["id"],
                    "source": receipt["source"],
                    "result_digest": digest(result),
                    "matches_committed_result": digest(result) == digest(action["result"]),
                },
            )
            return False
        action["status"] = "completed"
        action["result"] = copy.deepcopy(result)
        action["receipt"] = receipt
        if action["attempts"]:
            attempt = action["attempts"][-1]
            attempt["status"] = "completed"
            self.store.settle(
                attempt["id"],
                run["manifest"]["tools"][action["tool"]]["cost"],
                {"effect": "confirmed"},
            )
        run["messages"].append(
            {"role": "tool", "tool_call_id": action["call_id"], "content": canonical(result)}
        )
        return True

    async def _tool(self, run_id, action_id):
        run = self._authorized(run_id)
        if run["state"] in TERMINAL or run["state"] == "cancelling":
            return True
        action = next(a for a in run["actions"] if a["id"] == action_id)
        tool = self.tools.get(action["tool"])
        self._check_release(run)
        tool.validate(action["arguments"])
        if self.policy is not None:
            policy = self.policy
            self._validate_policy(policy)
            decision = policy(self.scope, tool.spec, copy.deepcopy(action["arguments"]))
            if decision is not None:
                if inspect.iscoroutine(decision) or inspect.isgenerator(decision):
                    decision.close()
                raise ValidationError("Synchronous authorization policy must return None")
            self._check_release(self._authorized(run_id))
            run = self._authorized(run_id)
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                return True
            action = next(a for a in run["actions"] if a["id"] == action_id)
        if tool.spec.effect != "read_only":
            unresolved = self.store.unresolved_effect(
                self.scope, action["tool"], action["arguments"], action_id
            )
            if unresolved:
                with self.store.transaction():
                    run["state"] = "waiting_reconciliation"
                    run["error"] = {"code": "prior_effect_unknown", **unresolved}
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
                    result = await invoke(
                        tool.reconciler, action["arguments"], context, thread_tracker=self._threads
                    )
                except Exception:
                    result = None
                with self.store.transaction():
                    run = self._authorized(run_id)
                    action = next(a for a in run["actions"] if a["id"] == action_id)
                    if action["status"] == "completed":
                        if result is not None:
                            self._tool_result(run, action, result, {"source": "tool-reconciler"})
                        return True
                    if result is not None:
                        self._tool_result(run, action, result, {"source": "tool-reconciler"})
                        self._commit(run, "effect_reconciled", {"action_id": action_id})
                        return True
            if tool.spec.effect not in {"read_only", "idempotent_write"}:
                with self.store.transaction():
                    run = self._authorized(run_id)
                    if run["state"] not in TERMINAL and run["state"] != "cancelling":
                        run["state"] = "waiting_reconciliation"
                    self._commit(run, "effect_unknown", {"action_id": action_id})
                return False
        attempt_id = f"{action_id}:{len(action['attempts']) + 1}"
        with self.store.transaction():
            run = self._authorized(run_id)
            if run["state"] == "cancelling" or run["state"] in TERMINAL:
                return True
            self._check_release(run)
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
            result = await invoke(
                tool.handler, action["arguments"], context, thread_tracker=self._threads
            )
            with self.store.transaction():
                run = self._authorized(run_id)
                action = next(a for a in run["actions"] if a["id"] == action_id)
                committed = self._tool_result(
                    run, action, result, {"source": "tool-handler", "attempt_id": attempt_id}
                )
                if committed:
                    self._commit(run, "tool_result_committed", {"action_id": action_id})
            return True
        except Exception:
            with self.store.transaction():
                run = self._authorized(run_id)
                action = next(a for a in run["actions"] if a["id"] == action_id)
                if action["status"] == "completed":
                    self.store.emit(
                        run_id,
                        "late_effect_error",
                        {"action_id": action_id, "attempt_id": attempt_id},
                    )
                    return False
                action["status"] = "outcome_unknown"
                action["attempts"][-1]["status"] = "unknown"
                self.store.mark_unknown(attempt_id)
                if run["state"] not in TERMINAL:
                    run["state"] = (
                        "cancelled" if run["state"] == "cancelling" else "waiting_reconciliation"
                    )
                self._commit(run, "effect_unknown", {"action_id": action_id})
            return False
