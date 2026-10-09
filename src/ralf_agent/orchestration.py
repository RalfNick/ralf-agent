"""Parent/child transactions and escrow; strategies never own execution facts."""

import asyncio
import copy
from dataclasses import asdict

from .errors import DefinitionMismatch, RalfError, ValidationError
from .orchestration_types import ChildCall, TeamRequest, TeamSelection
from .planning import CompleteVerifier, PlanningRequest, PlanProposal, RulePlanner, Verification
from .teams import RouterTeam, SequentialTeam, SupervisorTeam
from .types import AgentSpec, canonical, digest

TERMINAL = {"succeeded", "failed", "cancelled"}


def is_orchestrated(run):
    return run["definition"]["kind"] in {"team", "dynamic"}


class ChildRunFailed(RalfError):
    code = "child_run_failed"


class PlanRevisionLimit(ValidationError):
    code = "plan_revision_limit"


class _Caller:
    def __init__(self, runtime, run_id):
        self.runtime, self.run_id = runtime, run_id
        limit = runtime.engine._authorized(run_id)["definition"]["max_concurrency"]
        self._slots = asyncio.Semaphore(limit)

    async def call(self, call_id, member, input):
        if member != "@planner":
            raise ValidationError("Planning may call only its declared tool-free planner Agent")
        async with self._slots:
            call = self.runtime.delegate(
                self.run_id, ChildCall(call_id, member, input), planning=True
            )
            snapshot = await self.runtime.engine.drive(call["run_id"])
            self.runtime.observe(self.run_id)
            return snapshot


class OrchestrationRuntime:
    def __init__(self, engine, *, team_strategies=None, planners=None, plan_verifiers=None):
        self.engine = engine
        self.teams = {
            "sequential": SequentialTeam(),
            "router": RouterTeam(),
            "supervisor": SupervisorTeam(),
            **(team_strategies or {}),
        }
        self.planners = {"rule": RulePlanner(), **(planners or {})}
        from .dag_planning import ModelDAGPlanner, RuleDAGPlanner
        from .dag_runtime import DAGRuntime

        self.planners = {
            "dag-rule": RuleDAGPlanner(),
            "dag-model": ModelDAGPlanner(),
            **self.planners,
        }
        self._dag = DAGRuntime(self)
        self.verifiers = {"complete": CompleteVerifier(), **(plan_verifiers or {})}
        for registry, methods, pure in (
            (self.teams, ("select",), True),
            (self.planners, ("plan",), False),
            (self.verifiers, ("verify",), True),
        ):
            for name, component in registry.items():
                if not isinstance(name, str) or not name.strip():
                    raise ValidationError("Orchestration components require named registrations")
                engine._component_identity(component, methods, pure, "Orchestration component")

    def component(self, registry, name):
        try:
            return registry[name]
        except KeyError as exc:
            raise DefinitionMismatch(
                "The registered orchestration component is unavailable"
            ) from exc

    def manifest(self, definition, *, member_manifests=None):
        from .spec_codec import agent_steps

        engine = self.engine
        steps = agent_steps(definition) if member_manifests is None else []
        mode = definition["kind"]
        if mode == "team":
            strategy = self.component(self.teams, definition["strategy"])
            identities = {
                "strategy": engine._component_identity(strategy, ("select",), True, "Team")
            }
        else:
            planner = self.component(self.planners, definition["planner"])
            verifier = self.component(self.verifiers, definition["verifier"])
            agent = getattr(planner, "agent", None)
            if agent is not None:
                if not isinstance(agent, AgentSpec) or agent.tools:
                    raise ValidationError("The planner child must be a fixed tool-free AgentSpec")
                steps.append(asdict(agent))
            identities = {
                "planner": engine._component_identity(planner, ("plan",), False, "Planner"),
                "verifier": engine._component_identity(verifier, ("verify",), True, "Verifier"),
                "planning_agent": None if agent is None else asdict(agent),
            }
        nested = {
            name: value
            for name, value in definition["members"].items()
            if value.get("kind", "agent") != "agent"
        }
        releases = (
            {name: self._member_manifest(value) for name, value in nested.items()}
            if member_manifests is None
            else member_manifests
        )
        result = {
            **engine._manifest(steps),
            "orchestration": {
                "version": "2"
                if releases or definition.get("plan_mode") == "dag" or "max_depth" in definition
                else "1",
                "kind": mode,
                **identities,
                **({"members": releases} if releases else {}),
                **(
                    {"dag": {"format": "ralf-dag", "version": "1"}}
                    if definition.get("plan_mode") == "dag"
                    else {}
                ),
            },
        }
        for release in releases.values():
            from .binding_manifests import all_step_manifests

            for view in all_step_manifests(release):
                result["tools"].update(view["tools"])
        return result

    def _member_manifest(self, value):
        if value.get("kind", "agent") in {"team", "dynamic"}:
            return self.manifest(value)
        if value.get("kind") == "graph":
            return self.engine._workflow.manifest(self.engine._workflow.compile(value))
        from .spec_codec import agent_steps

        return self.engine._manifest(agent_steps(value))

    @staticmethod
    def initial():
        return {
            "children": [],
            "results": {},
            "queue": [],
            "revision": 0,
            "revisions": [],
            "proposal": None,
            "request": None,
            "stage": "select",
            "quiescent": True,
        }

    def accept(self, run_id, definition, input, budget, session_id, parent_call=None):
        from .spec_codec import agent_steps

        engine = self.engine
        session = session_id or run_id
        manifest = (
            engine._bindings.manifest(definition)
            if "binding_definition" in definition
            else self.manifest(definition)
        )
        if parent_call is not None:
            parent = engine._authorized(parent_call["parent_id"])
            if parent.get("orchestration") is None or parent["state"] in TERMINAL | {"cancelling"}:
                raise ValidationError("Nested calls require an active orchestration parent")
            engine._check_parent_limits(parent, parent_call, manifest)
            manifest["parent_call"] = copy.deepcopy(parent_call)
        execution_definition = {**definition, "steps": agent_steps(definition)}
        from .managed_memory import admit_stages

        admit_stages(engine, manifest, definition["kind"], parent_call)
        from .session_resources import admit_sessions

        session_claim_data = admit_sessions(engine, manifest, [session])
        data = {
            "id": run_id,
            "revision": 0,
            "scope": asdict(engine.scope),
            "state": "queued",
            "definition": execution_definition,
            "manifest": manifest,
            "release_digest": digest({"definition": execution_definition, "manifest": manifest}),
            "input": input,
            "result": None,
            "error": None,
            "node": 0,
            "decisions": 0,
            "actions": [],
            "messages": [],
            "session_id": session,
            **session_claim_data,
            "orchestration": self.initial(),
            **(
                {
                    "parent_call": copy.deepcopy(parent_call),
                    "parent_id": parent_call["parent_id"],
                    "call_id": parent_call["call_id"],
                }
                if parent_call is not None
                else {}
            ),
        }
        engine.store.insert_run(data)
        engine.store.create_budget(run_id, budget)
        engine.store.emit(run_id, "run_submitted", {"release_digest": data["release_digest"]})
        return {"state_revision": 0}

    def _key(self, run, call, *, planning=False):
        if run["definition"]["kind"] == "team":
            return call.id
        return f"r{run['orchestration']['revision']}.{'planner' if planning else 'step'}.{call.id}"

    def delegate(self, run_id, call, *, planning=False):
        engine = self.engine
        with engine.store.transaction():
            run = engine._authorized(run_id)
            engine._check_release(run)
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                raise ValidationError("A stopped parent cannot dispatch a child")
            state, definition = run["orchestration"], run["definition"]
            if planning and state["stage"] != "select":
                raise ValidationError("Managed planning calls require the planning stage")
            key = self._key(run, call, planning=planning)
            existing = next((c for c in state["children"] if c["id"] == key), None)
            if existing is not None:
                if existing["proposal"] != call.to_dict() or existing["planning"] != planning:
                    raise DefinitionMismatch("The stable child call changed")
                return existing
            member = definition["members"].get(call.member)
            if planning and call.member == "@planner":
                planner = self.component(self.planners, definition["planner"])
                agent = getattr(planner, "agent", None)
                member = None if agent is None else asdict(agent)
            if member is None:
                raise ValidationError("Delegation must name a registered member")
            self._check_depth(run)
            if (
                planning
                and sum(
                    engine._authorized(c["run_id"])["state"] not in TERMINAL
                    for c in state["children"]
                )
                >= definition["max_concurrency"]
            ):
                raise ValidationError("Pending children occupy the managed planning capacity")
            limit = (
                len(definition["members"])
                if definition["kind"] == "team"
                else definition["max_steps"]
            )
            if len(state["children"]) >= limit:
                raise ValidationError("The child step limit was exhausted")
            reservation = f"child:{run_id}:{key}"
            allowance = definition["child_budget"]
            engine.store.reserve(run_id, reservation, allowance)
            from .binding_paths import has_disabled_session, member_spec
            from .spec_codec import decode_spec

            child_spec = decode_spec(member) if planning else member_spec(definition, call.member)
            child_session = (
                None if has_disabled_session(child_spec) else f"{run['session_id']}:child:{key}"
            )
            from .agent_limits import has_agent_limits

            parent_binding = {"parent_id": run_id, "call_id": key, "reservation": reservation}
            if has_agent_limits(run["manifest"]):
                parent_binding["limits_member"] = call.member

            handle = engine.submit(
                child_spec,
                call.input,
                command_id=f"child-submit:{run_id}:{key}",
                budget=allowance,
                session_id=child_session,
                _parent_call=parent_binding,
            )
            child = engine._authorized(handle.run_id)
            child.update(parent_id=run_id, call_id=key)
            engine._commit(child, "child_linked", {"parent_id": run_id, "call_id": key})
            record = {
                "id": key,
                "member": call.member,
                "run_id": handle.run_id,
                "proposal": call.to_dict(),
                "reservation": reservation,
                "planning": planning,
                "settled": False,
                "state": "queued",
            }
            state["children"].append(record)
            state["quiescent"] = False
            engine._commit(run, "child_submitted", {"call_id": key, "run_id": handle.run_id})
            return copy.deepcopy(record)

    def _check_depth(self, run):
        depth, seen, current, limit = 1, {run["id"]}, run, run["definition"].get("max_depth", 8)
        while current.get("parent_call") is not None:
            current = self.engine._authorized(current["parent_call"]["parent_id"])
            if current["id"] in seen:
                raise DefinitionMismatch("Nested parent links contain a cycle")
            seen.add(current["id"])
            depth += 1
            ancestor_limit = current["definition"].get("max_depth", 8)
            if depth > ancestor_limit:
                raise ValidationError("Nested child depth limit was exhausted")
        if depth > 8 or limit < 1:
            raise ValidationError("Nested child depth limit was exhausted")

    def observe(self, run_id):
        engine = self.engine
        with engine.store.transaction():
            run = engine._authorized(run_id)
            state = run["orchestration"]
            before = canonical(state)
            for call in state["children"]:
                child = engine._authorized(call["run_id"])
                if child.get("parent_id") != run_id or child.get("call_id") != call["id"]:
                    raise DefinitionMismatch("The child ownership link changed")
                call["state"] = child["state"]
                if child.get("orchestration") is not None:
                    self.observe(child["id"])
                    child = engine._authorized(child["id"])
                if child["state"] == "succeeded" and not call["planning"]:
                    state["results"][call["id"]] = copy.deepcopy(child["result"])
                if child["state"] not in TERMINAL or call["settled"]:
                    continue
                budget = engine.store.budget(child["id"])
                if (
                    budget["held"]
                    or engine._operation_active(child["id"])
                    or child["id"] in engine._active
                ):
                    engine.store.mark_unknown(call["reservation"])
                    continue
                engine.store.settle(
                    call["reservation"], budget["spent"], {"child_run_id": child["id"]}
                )
                call["settled"] = True
            if "quiescent" in state:
                state["quiescent"] = all(call["settled"] for call in state["children"])
            if before != canonical(state):
                engine._commit(run, "children_observed")
            return run

    def cancel_children(self, run):
        for call in run["orchestration"]["children"]:
            self.engine.cancel(call["run_id"], command_id=f"parent-cancel:{run['id']}:{call['id']}")

    def _validate_calls(self, run, calls):
        names, ids = set(), set()
        for value in calls:
            call = ChildCall(**value)
            if call.member not in run["definition"]["members"] or call.id in ids:
                raise ValidationError("Plan calls must be unique and within the member allowlist")
            if run["definition"]["kind"] == "team":
                old = run["orchestration"]["children"]
                if call.member in names or any(c["member"] == call.member for c in old):
                    raise ValidationError("A team member cannot be delegated twice")
            names.add(call.member)
            ids.add(call.id)
        remaining = (
            len(run["definition"]["members"])
            if run["definition"]["kind"] == "team"
            else run["definition"]["max_steps"]
        ) - len(run["orchestration"]["children"])
        if len(calls) > remaining:
            raise ValidationError("The proposal exceeds the remaining child step limit")

    async def _drive_children(self, run_id, pending):
        engine = self.engine
        tasks = {asyncio.create_task(engine.drive(call["run_id"])) for call in pending}
        active = tasks.copy()
        try:
            while active:
                completed, active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                if engine._authorized(run_id)["state"] in TERMINAL | {"cancelling"}:
                    return
                for task in completed:
                    snapshot = task.result()
                    if snapshot.state in {"failed", "cancelled"}:
                        # Stop subsequent sibling dispatch immediately. Calls already
                        # running still retain their evidence, escrow and coordinator.
                        engine._fail(run_id, ChildRunFailed.code)
                        raise ChildRunFailed("A child Run did not succeed")
        except BaseException:
            self.cancel_children(engine._authorized(run_id))
            raise
        finally:
            await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
            self.observe(run_id)

    async def _queue(self, run_id):
        engine = self.engine
        while True:
            run = self.observe(run_id)
            state = run["orchestration"]
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                self.cancel_children(run)
                return False
            if any(c["state"] in {"failed", "cancelled"} for c in state["children"]):
                raise ChildRunFailed("A child Run did not succeed")
            pending = [c for c in state["children"] if c["state"] not in TERMINAL]
            slots = run["definition"]["max_concurrency"] - len(pending)
            if state["queue"] and slots > 0:
                for proposal in state["queue"][:slots]:
                    self.delegate(run_id, ChildCall(**proposal))
                    with engine.store.transaction():
                        latest = engine._authorized(run_id)
                        latest["orchestration"]["queue"].pop(0)
                        engine._commit(latest, "child_call_dispatched")
                continue
            if not pending:
                return not state["queue"]
            await self._drive_children(run_id, pending)
            run = self.observe(run_id)
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                return False
            pending = [c for c in run["orchestration"]["children"] if c["state"] not in TERMINAL]
            if any(c["state"] in {"failed", "cancelled"} for c in run["orchestration"]["children"]):
                raise ChildRunFailed("A child Run did not succeed")
            if pending and (
                not run["orchestration"]["queue"]
                or len(pending) >= run["definition"]["max_concurrency"]
            ):
                with engine.store.transaction():
                    latest = engine._authorized(run_id)
                    if latest["state"] not in TERMINAL and latest["state"] != "cancelling":
                        latest["state"] = (
                            "waiting_approval"
                            if any(c["state"] == "waiting_approval" for c in pending)
                            else "outcome_unknown"
                        )
                        engine._commit(latest, "children_waiting")
                return False

    async def _finish(self, run_id, result):
        canonical(result)
        from .remote_composite_saves import save_result

        if await save_result(self.engine, run_id, result) is False:
            return
        with self.engine.store.transaction():
            run = self.engine._authorized(run_id)
            self.engine._check_release(run)
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                return
            from .session_composites import save_composite_turn_result

            save_composite_turn_result(self.engine, run, result)
            run["state"], run["result"] = "succeeded", copy.deepcopy(result)
            self.engine._commit(run, "run_succeeded")

    async def _team(self, run_id):
        engine = self.engine
        run = engine._authorized(run_id)
        if run["orchestration"]["queue"] or any(
            c["state"] not in TERMINAL for c in run["orchestration"]["children"]
        ):
            return await self._queue(run_id)
        strategy = self.component(self.teams, run["definition"]["strategy"])
        results = {
            c["member"]: run["orchestration"]["results"][c["id"]]
            for c in run["orchestration"]["children"]
            if c["state"] == "succeeded"
        }
        request = TeamRequest(
            run["input"],
            run["definition"]["member_order"],
            results,
            run["definition"]["strategy_config"],
        )
        selection = engine._component_result(strategy.select(request), TeamSelection, "Team.select")
        engine._check_release(engine._authorized(run_id))
        if selection.done:
            await self._finish(run_id, selection.result)
            return False
        self._validate_calls(run, selection.calls)
        with engine.store.transaction():
            latest = engine._authorized(run_id)
            latest["orchestration"]["queue"] = selection.calls
            engine._commit(latest, "team_selection_adopted")
        return True

    def _request(self, run):
        state = run["orchestration"]
        results = [
            {"id": c["id"], "member": c["member"], "result": state["results"][c["id"]]}
            for c in state["children"]
            if not c["planning"] and c["state"] == "succeeded"
        ]
        return PlanningRequest(
            run["input"],
            run["definition"]["member_order"],
            results,
            state["revision"],
            **(
                {
                    "capabilities": run["definition"]["members"],
                    "constraints": {
                        "remaining_steps": run["definition"]["max_steps"] - len(state["children"]),
                        "remaining_revisions": run["definition"]["max_revisions"]
                        - state["revision"],
                        "max_concurrency": run["definition"]["max_concurrency"],
                        "child_budget": run["definition"]["child_budget"],
                        "parent_budget": self.engine.store.budget(run["id"]),
                    },
                }
                if run["definition"].get("plan_mode") == "dag"
                else {}
            ),
        )

    async def _plan(self, run_id):
        engine = self.engine
        run = engine._authorized(run_id)
        state, definition = run["orchestration"], run["definition"]
        dag = definition.get("plan_mode") == "dag"
        if state["stage"] == "execute":
            if not await (self._dag.execute(run_id) if dag else self._queue(run_id)):
                return False
            run = self.observe(run_id)
            verifier = self.component(self.verifiers, definition["verifier"])
            verdict = engine._component_result(
                Verification("succeeded", run["orchestration"]["dag"]["result"])
                if dag and type(verifier) is CompleteVerifier
                else verifier.verify(self._request(run)),
                Verification,
                "Verifier.verify",
            )
            engine._check_release(engine._authorized(run_id))
            with engine.store.transaction():
                latest = engine._authorized(run_id)
                latest["orchestration"]["revisions"][-1]["verification"] = verdict.to_dict()
                engine._commit(latest, "plan_verified")
            if verdict.status == "succeeded":
                await self._finish(run_id, verdict.result)
                return False
            if verdict.status == "failed":
                raise ChildRunFailed("Plan verification did not succeed")
            if state["revision"] + 1 >= definition["max_revisions"]:
                raise PlanRevisionLimit("The plan revision limit was exhausted")
            with engine.store.transaction():
                latest = engine._authorized(run_id)
                current = latest["orchestration"]
                current.update(
                    revision=current["revision"] + 1, proposal=None, request=None, stage="select"
                )
                engine._commit(latest, "plan_replanning")
            return True
        if state["proposal"] is None:
            if state["request"] is None:
                with engine.store.transaction():
                    state["request"] = self._request(run).to_dict()
                    engine._commit(run, "planning_request_saved")
            planner = self.component(self.planners, definition["planner"])
            proposal = await planner.plan(
                PlanningRequest(**state["request"]), _Caller(self, run_id)
            )
            engine._check_release(engine._authorized(run_id))
            if proposal is None:
                latest = self.observe(run_id)
                if not any(c["state"] not in TERMINAL for c in latest["orchestration"]["children"]):
                    raise ValidationError("A planner may pause only for a managed pending child")
                with engine.store.transaction():
                    if latest["state"] not in TERMINAL and latest["state"] != "cancelling":
                        latest["state"] = "outcome_unknown"
                        engine._commit(latest, "planner_waiting")
                return False
            from .dag_planning import DAGProposal, PlanningConclusion

            proposal = engine._component_result(
                proposal, (DAGProposal, PlanningConclusion) if dag else PlanProposal, "Planner.plan"
            )
            with engine.store.transaction():
                latest = engine._authorized(run_id)
                latest["orchestration"]["proposal"] = proposal.to_dict()
                engine._commit(latest, "plan_proposal_received")
        with engine.store.transaction():
            run = engine._authorized(run_id)
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                return False
            state = run["orchestration"]
            if dag:
                advance = self._dag.adopt(run)
            else:
                self._validate_calls(run, state["proposal"]["steps"])
                state["queue"] = copy.deepcopy(state["proposal"]["steps"])
                state["revisions"].append(
                    {"revision": state["revision"], "proposal": state["proposal"]}
                )
                state["stage"] = "execute"
                engine._commit(run, "plan_revision_adopted")
                advance = True
        if not advance:
            await self._finish(run_id, run["orchestration"]["proposal"])
        return advance

    async def drive(self, run_id):
        engine = self.engine
        try:
            while True:
                run = engine._authorized(run_id)
                if run["state"] in TERMINAL or run["state"] == "cancelling":
                    self.cancel_children(run)
                    if run["state"] == "cancelling":
                        with engine.store.transaction():
                            run["state"] = "cancelled"
                            engine._commit(run, "run_cancelled")
                    self.observe(run_id)
                    break
                engine._check_release(run)
                advance = await (
                    self._team(run_id)
                    if run["definition"]["kind"] == "team"
                    else self._plan(run_id)
                )
                if not advance:
                    if engine._authorized(run_id)["state"] == "cancelling":
                        continue
                    break
            return engine.status(run_id)
        except asyncio.CancelledError:
            engine.cancel(run_id, command_id=f"orchestration-cancel:{run_id}")
            raise
        except RalfError:
            run = engine._authorized(run_id)
            if run["state"] == "cancelling":
                with engine.store.transaction():
                    run["state"] = "cancelled"
                    engine._commit(run, "run_cancelled")
                self.terminal(run_id)
                return engine.status(run_id)
            if run["state"] == "cancelled":
                self.terminal(run_id)
                return engine.status(run_id)
            raise
        except Exception as exc:
            raise ValidationError("Orchestration component failed") from exc

    def terminal(self, run_id):
        run = self.engine._authorized(run_id)
        if run["state"] != "succeeded":
            self.cancel_children(run)
        self.observe(run_id)
