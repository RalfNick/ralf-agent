"""Local Session commands, accepted by the existing Run authority transaction."""

import inspect
import json
import uuid

from .agent_harness import AgentHarness
from .agent_run import RunRef
from .binding_runtime import descriptor_for, unwrap_definition
from .binding_sessions import SessionView
from .errors import (
    AuthorizationDenied,
    DefinitionMismatch,
    NotFound,
    SessionBindingMismatch,
    SessionBusy,
    ValidationError,
)
from .memory import SQLiteMemory
from .ports import is_sync_callable
from .session_conversations import UNSET_NAMESPACE, select_conversation
from .session_ports import SessionAdmissionStore, ValidatedSessionAdmission
from .session_types import SessionKey, SessionRef, SessionSnapshot, TurnAdmission, integer
from .sqlite_sessions import admission_permit
from .types import canonical, credits, digest, submission_request

TERMINAL = {"succeeded", "failed", "cancelled"}


class LocalSessionAuthority:
    def __init__(self, engine, locator, *, hosting=None):
        factory = getattr(engine.store, "create_session_admission", None)
        if not is_sync_callable(factory):
            raise ValidationError("Local Sessions require authority-bound Session admission")
        store = factory()
        if (
            getattr(store, "transaction_owner", None) is not engine.store
            or getattr(store, "authority_backend_id", None) != engine.store.backend_id
            or any(
                not is_sync_callable(getattr(store, name, None))
                for name in vars(SessionAdmissionStore)
                if not name.startswith("_")
            )
        ):
            if inspect.iscoroutine(store) or inspect.isgenerator(store):
                store.close()
            raise ValidationError("Session admission must use the existing execution transaction")
        self.engine, self.store, self.locator, self.hosting = (
            engine,
            ValidatedSessionAdmission(store),
            locator,
            hosting,
        )
        self.resource_id = digest(["sqlite-session-resource", engine.store.backend_id])
        self.coordination_ref = digest(
            ["local-session-coordination-v1", engine.store.backend_id, locator]
        )

    @staticmethod
    def _harness(definition):
        return definition if isinstance(definition, AgentHarness) else AgentHarness(definition)

    def _pin(self, harness, session_id, *, namespace=UNSET_NAMESPACE):
        declaration = json.loads(harness._definition_json)
        definition = (
            unwrap_definition(declaration)
            if declaration["kind"] in {"bound_agent", "bound_definition"}
            else declaration
        )
        from .session_composites import KINDS, composite_manifest

        composite = definition["kind"] in KINDS
        conversation = None
        if composite:
            self._composite_extension()
            _, namespace, conversation = select_conversation(self.engine, namespace)
            if conversation is not None:
                self._composite_extension(conversation=True)
        elif definition["kind"] not in {"agent", "sequence"}:
            raise ValidationError("Unsupported Session definition")
        bound = "binding_definition" in definition
        namespaces = []
        resources = []
        remote = None
        for index, step in enumerate([] if composite else definition["steps"]):
            backend = (
                self.engine._bindings.resolve(step, descriptor_for(definition, index))[0].sessions
                if bound
                else self.engine.sessions
            )
            namespace = None
            if isinstance(backend, SessionView):
                backend._check(self.engine.scope)
                namespace, backend = backend.namespace, backend.backend
            if type(backend) is SQLiteMemory and backend.store.conn is getattr(
                self.engine.store, "conn", None
            ):
                resources.append(None)
            else:
                from .session_receipts import supports_remote_session

                if not supports_remote_session(backend):
                    raise ValidationError("Remote Sessions require bounded exact write receipts")
                self._remote_extension()
                resources.append(
                    {"backend_id": backend.backend_id, "namespace": namespace, "receipt_version": 1}
                )
            namespaces.append(namespace)
        if not composite and len(set(namespaces)) != 1:
            raise ValidationError("All Session steps must share one authorized namespace")
        if resources:
            if any(value != resources[0] for value in resources):
                raise ValidationError(
                    "All Session steps must share one storage resource and receipt protocol"
                )
            remote = resources[0]
        key = SessionKey(
            self.engine.scope.workspace,
            self.engine.scope.principal,
            self.resource_id
            if remote is None
            else digest(["remote-session-resource-v1", remote["backend_id"]]),
            namespace if composite else namespaces[0],
            session_id,
        )
        manifest = (
            composite_manifest(self.engine, definition)
            if composite
            else (
                self.engine._bindings.manifest(definition)
                if bound
                else self.engine._manifest(definition["steps"])
            )
        )
        binding = {"definition": declaration, "manifest": manifest}
        if conversation is not None:
            binding["conversation"] = conversation
        if remote is not None:
            binding["remote_session"] = remote
        return key, binding

    def _remote_extension(self):
        version = getattr(self.engine.store, "session_admission_version", 1)
        if (
            type(version) is not int
            or version != 4
            or any(
                not is_sync_callable(getattr(self.store.delegate, method, None))
                for method in ("prepare_remote_sessions", "remote_owner")
            )
        ):
            raise ValidationError("Remote Sessions require authority-bound admission version4")

    def _composite_extension(self, *, conversation=False):
        version = getattr(self.engine.store, "session_admission_version", 1)
        method = "prepare_conversations" if conversation else "prepare_composites"
        if (
            type(version) is not int
            or version not in ({3, 4} if conversation else {2, 3, 4})
            or not is_sync_callable(getattr(self.store.delegate, method, None))
        ):
            raise ValidationError(
                "Composite Sessions require the authority-bound admission extension"
            )

    def _prepare(self, binding):
        if "remote_session" in binding:
            self._remote_extension()
            self.store.prepare_remote_sessions()
            return
        declaration = binding["definition"]
        definition = (
            unwrap_definition(declaration)
            if declaration["kind"] in {"bound_agent", "bound_definition"}
            else declaration
        )
        if definition["kind"] in {"graph", "team", "dynamic"}:
            conversation = "conversation" in binding
            self._composite_extension(conversation=conversation)
            if conversation:
                self.store.prepare_conversations()
            else:
                self.store.prepare_composites()
        else:
            self.store.prepare()

    def _ref(self, state, revision=None):
        revision = state["binding_revision"] if revision is None else revision
        binding = state["bindings"].get(str(revision))
        if binding is None:
            raise DefinitionMismatch("Original Session binding revision unavailable")
        return SessionRef(
            SessionKey.from_dict(state["key"]),
            state["coordination_ref"],
            revision,
            digest(binding["definition"]),
        )

    def validate(self, ref):
        self.engine._ensure_open()
        if not isinstance(ref, SessionRef):
            raise ValidationError("Session attach requires immutable SessionRef")
        if (ref.key.workspace, ref.key.principal) != (
            self.engine.scope.workspace,
            self.engine.scope.principal,
        ):
            raise AuthorizationDenied("Session belongs to another trusted Scope")
        if ref.coordination_ref != self.coordination_ref:
            raise DefinitionMismatch("Session route belongs to another resource or authority")
        state = self.store.load(self.engine.scope, ref.key.key_id)
        if state is None:
            raise NotFound("Session route not found")
        from .remote_session_saves import validate_remote_binding

        remote = validate_remote_binding(state, ref.binding_revision, self.resource_id)
        expected_resource = (
            self.resource_id
            if remote is None
            else digest(["remote-session-resource-v1", remote["backend_id"]])
        )
        if ref.key.resource_id != expected_resource:
            raise DefinitionMismatch("Session route belongs to another storage resource")
        if self._ref(state, ref.binding_revision) != ref:
            raise DefinitionMismatch("Session reference differs from its original binding")
        return state

    def _run_ref(self, run_id):
        run = self.engine._authorized(run_id)
        if "session_turn" in run:
            return TurnAdmission.from_dict(run["session_turn"]).run
        return RunRef(
            self.locator,
            self.engine.scope.workspace,
            self.engine.scope.principal,
            run_id,
            run["release_digest"],
        )

    def _blocker(self, state):
        run_id = state["active_run"]
        if run_id is not None:
            run = self.engine._authorized(run_id)
            from .session_composites import KINDS, composite_turn_busy

            if run["definition"]["kind"] in KINDS and composite_turn_busy(
                self.engine, run, self.hosting
            ):
                return self._run_ref(run_id)
            if (
                run["state"] not in TERMINAL
                or self.engine._operation_active(run_id)
                or self.engine._drive_users.get(run_id)
                or (self.hosting is not None and self.hosting(run_id))
            ):
                return self._run_ref(run_id)
            if any(
                action["kind"] == "tool"
                and action["status"] in {"executing", "outcome_unknown", "receipt_received"}
                for action in run["actions"]
            ):
                return self._run_ref(run_id)
            if "remote_session_binding" in run or state["key"]["resource_id"] != self.resource_id:
                from .remote_session_saves import remote_saves_settled

                if not remote_saves_settled(self.engine, run):
                    return self._run_ref(run_id)
            elif run["state"] == "succeeded":
                from .session_composites import KINDS

                composite = run["definition"]["kind"] in KINDS
                step = None if composite else run["definition"]["steps"][-1]
                expected = {
                    "role": "assistant",
                    "content": run["result"],
                    "agent": run["definition"]["name"] if composite else step["name"],
                    "task": run["input"],
                }
                if not self.store.confirmed_result(
                    self.engine.scope,
                    SessionKey.from_dict(state["key"]).storage_key,
                    run_id + ":turn:result"
                    if composite
                    else f"{run_id}:{len(run['definition']['steps']) - 1}:result",
                    expected,
                ):
                    return self._run_ref(run_id)
        owner = (
            self.store.remote_owner
            if state["key"]["resource_id"] != self.resource_id
            else self.store.legacy_owner
        )
        legacy = owner(
            self.engine.scope,
            SessionKey.from_dict(state["key"]).storage_key,
            exclude_run_id=run_id,
        )
        return None if legacy is None else self._run_ref(legacy)

    @staticmethod
    def _outcome(receipt):
        if receipt.apply_state == "rejected":
            if receipt.outcome["reason"] == "session_busy":
                raise SessionBusy(receipt, RunRef.from_dict(receipt.outcome["run_ref"]))
            raise SessionBindingMismatch(receipt)
        return receipt

    def open(self, harness, session_id, *, command_id, namespace=UNSET_NAMESPACE):
        harness = self._harness(harness)
        # Validate caller syntax, without resolving current components before replay.
        SessionKey(
            self.engine.scope.workspace,
            self.engine.scope.principal,
            self.resource_id,
            None if namespace is UNSET_NAMESPACE else namespace,
            session_id,
        )
        declaration = json.loads(harness._definition_json)
        payload = {"definition": declaration, "session_id": session_id}
        if namespace is not UNSET_NAMESPACE:
            definition = (
                unwrap_definition(declaration)
                if declaration["kind"] in {"bound_agent", "bound_definition"}
                else declaration
            )
            if definition["kind"] not in {"graph", "team", "dynamic"}:
                raise ValidationError(
                    "Conversation namespace selection requires a composite definition"
                )
            payload["namespace"] = namespace

        def apply():
            key, binding = self._pin(harness, session_id, namespace=namespace)
            state = self.store.load_address(self.engine.scope, key.storage_key)
            if state is not None:
                if (
                    state["key"] != key.to_dict()
                    or state["coordination_ref"] != self.coordination_ref
                    or self._ref(state).definition_digest != digest(declaration)
                    or state["bindings"][str(state["binding_revision"])].get("conversation")
                    != binding.get("conversation")
                    or state["bindings"][str(state["binding_revision"])].get("remote_session")
                    != binding.get("remote_session")
                ):
                    return {"rejected": True, "reason": "session_binding_mismatch"}
                return {"session_ref": self._ref(state).to_dict()}
            self._prepare(binding)
            state = {
                "key": key.to_dict(),
                "coordination_ref": self.coordination_ref,
                "revision": 0,
                "binding_revision": 1,
                "bindings": {"1": binding},
                "last_turn_seq": 0,
                "active_run": None,
            }
            self.store.insert(state)
            return {"session_ref": self._ref(state).to_dict()}

        receipt = self.engine.store.command(
            self.engine.scope, command_id, "session_open", payload, uuid.uuid4().hex, apply
        )
        return self._outcome(receipt)

    def submit(self, ref, input, *, command_id, budget=32):
        self.validate(ref)
        credits(budget)
        input = json.loads(canonical(input))
        payload = {"session_ref": ref.to_dict(), "input": input, "budget": budget}
        canonical(payload)
        run_id = uuid.uuid4().hex

        def apply():
            state = self.validate(ref)
            if ref.binding_revision != state["binding_revision"]:
                return {"rejected": True, "reason": "session_binding_mismatch"}
            blocker = self._blocker(state)
            if blocker is not None:
                return {"rejected": True, "reason": "session_busy", "run_ref": blocker.to_dict()}
            binding = state["bindings"][str(ref.binding_revision)]
            harness = AgentHarness.__new__(AgentHarness)
            object.__setattr__(harness, "_definition_json", canonical(binding["definition"]))
            key, current = self._pin(harness, ref.key.session_id, namespace=ref.key.namespace)
            if key != ref.key or current != binding:
                return {"rejected": True, "reason": "session_binding_mismatch"}
            raw_payload = submission_request(
                harness.definition,
                input,
                budget=budget,
                session_id=ref.key.storage_key if "conversation" in binding else ref.key.session_id,
            )
            with admission_permit(self.engine.store, self.engine.scope, ref.key.storage_key):
                self.engine._accept_submission(run_id, raw_payload)
            run = self.engine._authorized(run_id)
            if "conversation" in binding:
                # Independent admission evidence distinguishes configured None
                # from a genuine legacy Turn, even in a mixed schema4 database.
                run["conversation_binding"] = json.loads(canonical(binding["conversation"]))
            if "remote_session" in binding:
                run["remote_session_binding"] = json.loads(canonical(binding["remote_session"]))
                run["remote_session_saves"] = {}
            run_ref = self._run_ref(run_id)
            turn = TurnAdmission(
                uuid.uuid4().hex,
                state["last_turn_seq"] + 1,
                ref,
                run_ref,
                digest(input),
                command_id,
            )
            run["session_turn"] = turn.to_dict()
            self.engine.store.save_run(run)
            self.engine.store.emit(
                run_id,
                "turn_admitted",
                {
                    "turn_id": turn.turn_id,
                    "turn_seq": turn.turn_seq,
                    "session_key": ref.key.key_id,
                    "binding_revision": ref.binding_revision,
                },
            )
            self.store.insert_turn(turn.to_dict())
            state["active_run"], state["last_turn_seq"] = run_id, turn.turn_seq
            self.store.save(state, expected_revision=state["revision"])
            return {"turn": turn.to_dict(), "state_revision": run["revision"]}

        return self._outcome(
            self.engine.store.command(
                self.engine.scope, command_id, "session_submit", payload, run_id, apply
            )
        )

    def rebind(self, ref, harness, *, expected_binding_revision, command_id):
        self.validate(ref)
        integer(expected_binding_revision)
        harness = self._harness(harness)
        payload = {
            "session_ref": ref.to_dict(),
            "definition": json.loads(harness._definition_json),
            "expected_binding_revision": expected_binding_revision,
        }

        def apply():
            state = self.validate(ref)
            if (
                state["binding_revision"] != expected_binding_revision
                or ref.binding_revision != expected_binding_revision
            ):
                return {"rejected": True, "reason": "session_binding_mismatch"}
            blocker = self._blocker(state)
            if blocker is not None:
                return {"rejected": True, "reason": "session_busy", "run_ref": blocker.to_dict()}
            key, binding = self._pin(harness, ref.key.session_id, namespace=ref.key.namespace)
            if key != ref.key:
                return {"rejected": True, "reason": "session_resource_change"}
            revision = state["binding_revision"] + 1
            self._prepare(binding)
            state["bindings"][str(revision)] = binding
            state["binding_revision"], state["active_run"] = revision, None
            self.store.save(state, expected_revision=state["revision"])
            return {"session_ref": self._ref(state).to_dict()}

        return self._outcome(
            self.engine.store.command(
                self.engine.scope, command_id, "session_rebind", payload, uuid.uuid4().hex, apply
            )
        )

    def status(self, ref):
        state = self.validate(ref)
        blocker = self._blocker(state)
        return SessionSnapshot(
            ref, state["binding_revision"], state["last_turn_seq"], blocker, blocker is not None
        )

    def turns(self, ref, *, after=0, limit=100):
        self.validate(ref)
        return [
            TurnAdmission.from_dict(row)
            for row in self.store.turns(self.engine.scope, ref.key.key_id, after=after, limit=limit)
        ]
