# Independent Temporal execution

Dev119 completes the bounded public ordinary deployment subset: source and independently installed packages each pass 953 checks from 46 affected modules, 27 public v2 actual Service cases and 17 private v1 cases, all with zero skips. Select `TemporalRuntime(admission_policy=DeploymentAdmissionPolicy(...))`, then construct `TemporalEngine` with that Runtime's selected release. Profile／JSON／TOML use the existing `components.admission_policy`／`bounded` factory; `TemporalRuntimeBuilder.abuild` and `abuild_catalog` also accept a host policy, which cannot coexist with Profile policy selection. Default-off publication and original dev118 History replay／continuation compatibility pass, with zero new Provider calls. See the [public contract](../architecture/specs/temporal-deployment-public-contract.md) and [acceptance record](../architecture/reviews/2026-10-15-temporal-deployment-public.md).

Dev120 completes the selected Coding deployment subset using deployment v3 and Registry3; see the [batch acceptance](../architecture/reviews/2026-10-15-temporal-deployment-coding.md) for the separate original matrix and corrected normal recovery verification. Configuration, original-envelope recovery, unknown obligations and owned-close diagnostics are described in the [Coding deployment guide](temporal-deployment-coding.md). SDK Session-coordinator admission remains unavailable; phase-three batch 2 is open.

Public ordinary deployment uses protocol v2; the selected Coding deployment uses v3. Original Registry History fixes the first request, Manifest, Activity timeout and task queue; repeated submissions first recover that envelope or receipt by the original command and request, then restore under the original release; host authorization and actual identity checks remain required. Actual SDK namespace UUID, original epoch, queue and accepted timeout must match. Lost reserve/start replies retain the same root claim. Original Run／Parent Histories record physical Activity obligations and closure seals; only the Registry's own SDK verification of the closed tree retires quota. Unknown effects, zero-cost unsettled work, live handlers and failed durable end acknowledgements keep the claim held. `await engine.deployment_diagnostics()` provides scoped read-only observation.

If a sealed root remains held after a deferred Registry retirement RPC, restore its original Service／Worker route and call `await engine.drive(run_id)`. The Engine verifies original acceptance and SDK identity, then sends a fresh SDK Update with the exact original seal payload to wake retirement in the original root History. Its certificate and business terminal state remain fixed; the Facade does not directly release Registry quota. `drive` may return the existing terminal snapshot before retirement finishes: inspect `await engine.deployment_diagnostics()` for the original held／retired root. A Parent cancel receipt with `outcome["remote_stop_confirmed"] == False` requires waiting for actual descendants and current diagnostics; an accepted cancellation receipt does not prove their stop. For an already completed Action whose effect acknowledgement is deferred, resume the original `drive` after fixing the journal route. `reconcile(query=True)` is for uncertain effect evidence, not an acknowledgement retry or a new tool attempt.

The dev119 zero-cost write and ACK recovery windows used a test-only SQLite effect-evidence adapter; other deterministic cases used default components. That batch made no model, PostgreSQL or Docker calls, and its owned Workers／Workflows and dedicated Service were closed. Dev120 uses its original PostgreSQL journals; installed representative Service, physical-close and unknown-retention evidence is recorded in the batch acceptance.

The private Worker-only v1 mode retains its held-only contract; public Engine rejects v1, and an existing v1 Registry is not replaced or silently upgraded. The dev119 selected deployment mode refused Coding and SDK Session-coordinator Turns. Dev120 adds the selected Coding chain; SDK Session-coordinator Turns remain refused and required next work. Ordinary non-Coding managed Session writes retain their original stage contracts. Batch 2, the third phase and complete R01–R26 remain open. The dev119 increment adds no model-quality claim and was delivered with a local commit, with no push.

Current dev65: [Temporal automatic memory and per-Agent bindings](temporal-memory-bindings.md) adds the opt-in temporal-3 protocol. [Facts namespace selection and bounded recall](temporal-facts.md) and [Knowledge namespace selectors](temporal-knowledge-bindings.md) extend the original Context History. Opt-in [History Sessions](temporal-sessions.md) provide durable serial Turns with actual Namespace UUID identities. [Agent limits](temporal-agent-limits.md) add pure replaceable policy proposals and pinned per-node caps. Default-off protocol identities remain unchanged. Full external SessionStore writes/persistent routing and remaining environment roles are unsupported; dev65 supports stateless native/sequence bounded Session reads only.
[Completion verification](temporal-completion-verification.md) pins pure policies and current-node receipts; original History accepts, rejects or retries before memory/completion.

`TemporalEngine` implements the public AsyncExecutionEngine/AsyncRuntimeDiagnostics
ports. Network controls are explicitly awaited. A Temporal Workflow owns commands,
Actions, approvals, credit reservations, evidence adoption and terminal decisions
in its History. Model/tool Activities use registered components; they do not wrap
LocalEngine or open a local execution store.

Install `ralf-agent[temporal]`; provide your Temporal Service and worker registration.
The SDK starts no server or worker implicitly. A minimal worker uses:

```python
from temporalio.client import Client
from ralf_agent import (
    TemporalRuntime,
    TemporalEngine,
    build_temporal_worker,
    ToolRegistry,
    AgentSpec,
)
from ralf_agent.runtime_builder import EchoProvider


async def run_example():
    client = await Client.connect("127.0.0.1:7233")
    runtime = TemporalRuntime(providers={"default": EchoProvider("offline")}, tools=ToolRegistry())
    worker = build_temporal_worker(client, task_queue="ralf-v1", runtime=runtime)
    engine = TemporalEngine(client, task_queue="ralf-v1", release=runtime.manifest)
    async with worker:
        handle = await engine.submit(AgentSpec("answer", "Answer"), "hello", command_id="first")
        result = await engine.drive(handle.run_id)
        assert result.state == "succeeded"
    await engine.aclose()
```

Run multiple worker processes on that queue with the same registered release.
The facade's Client and runtime dependencies are borrowed; the host closes owned
Provider/journal resources after worker shutdown. The release contains immutable
identities/code digests, never serialized live clients or credentials. Worker drift
is refused before new external dispatch. Changes require retaining workers capable
of the old release and its recorded queue; this increment adds no rolling-upgrade
or deployment-version management service.

## Supported capability subset

Native Agent and sequential Workflow are supported with the default NativeHarness
and History context. Provider and ToolExecutor ports are replaceable; synchronous
policy must return None after completed authorization, or raise a typed denial.
The default `runtime.manifest` supports this native subset. The explicit
`runtime.orchestration_release` adds Graph/DAG/Team/nesting and registered RAG,
as described in [distributed composition](temporal-composition.md). The opt-in temporal-3 release adds catalog routing and bounded Facts/Knowledge reads. `enable_sessions=True` adds History-owned shared Sessions. Session binding selection, external SessionStore routing and custom Harness remain refused.
Do not assume LocalEngine feature parity.

Scoped command IDs are checked across Runs/control kinds by a History-backed
identity registry; the target Run Workflow alone issues applied receipts.
Submit replay recovers the original release and receipt. Approval binds Action
and operation digest. Queries authenticate the trusted Scope. `drive` is a bounded
wait for progress; service/workers continue after a disconnected caller. Temporal
Updates and replay implement durable controls as described in its
[message-passing documentation](https://docs.temporal.io/develop/python/message-passing).

Dev106 的显式 [Temporal Coding](temporal-coding.md)已实现、正在验证 Agent／顺序
Workflow 子集：`coding_execution=True`、原 History 阶段准入、精确共享 PG journal、
Runner 绑定和 owned 停止／关闭。PG／History 固定 readonly 配置 bind 的真实原生
控制、原 CID 移除与 History／PG 收尾通过；最终交付检查待登记。默认发布保持；复杂 Temporal Coding、跨宿主恢复、
专用原生认证和真实 Coding 任务质量继续开放，最终证据见
[本批登记](../architecture/reviews/2026-10-14-temporal-coding-delegation.md)。

## External effects

Write tools require an EffectJournal. The default
`await PostgresEffectJournal.connect(dsn, backend_id="effects-v1")`, followed by
`await journal.initialize()`, persists dispatch intent and immutable received
observations. Pass it to TemporalRuntime(journal=journal). The public structural
EffectJournal port supports replacement with matching atomicity/exclusion contracts.
PostgreSQL is evidence storage, not a second execution authority.

Activities use one dispatch attempt, with no automatic write retry after a lost
reply. Uncertain Actions keep their credit hold. Reconcile by the original key with
`await engine.reconcile(run_id, action_id, command_id="query-1", query=True)` or
verified manual evidence. A cross-Run scoped tool/argument guard remains until
Workflow History adopts evidence and acknowledges the journal. Received evidence
alone cannot clear the guard. Cancellation stops new dispatch; late observations
remain evidence and cannot replace a cancelled terminal result.

History persists model/tool evidence before decision/result adoption. History can
be downloaded from the Client and checked with `replay_temporal_history(history)`.
Real worker kills after external commit, lost-receipt reconciliation and repeat
controls are acceptance probes. They establish these tested boundaries, not
arbitrary external exactly-once execution.

This preview keeps business-terminal Run Workflows open for receipt replay/late
evidence; command registry capacity is finite (4096). History compaction,
Continue-As-New, retention, cross-deployment quotas, recovery administration,
enterprise identity and deployment failover remain unimplemented. Use separate
queues/retained registrations for trials and inspect actual History/service state.

The current default scoped Worker preserves one first pure cancellation of an
original submitted target after normal command capacity is full. Synchronous Run
reservations use the original Registry's bounded Signal/Query observations;
confirmed legacy Workers keep their original Update path and limits. Session
commands retain their original transport. The default scoped Registry also
provides one repeatable pure drive identity per original submitted target.
Default Parent repeats recover original evidence under a Temporal History patch;
old Workers retain their original drive behavior. It does not cover scoped manual
confirmation or guarantee unlimited History.
See the [capacity contract](../architecture/specs/temporal-recovery-capacity-contract.md#default-scoped-first-cancellation)
for identity, retry, compatibility and remaining gates.


In dev16 the same facade can be borrowed by A2AApplication with PostgresInbox; see [async handoff](async-handoff.md). Workflow state is initialized before Queries/Updates can arrive. Actual dev15 Run/registry History replay remains compatible. dev17 extends the execution subset through an explicit orchestration release; native identities remain unchanged.

Effect confirmation through a reconciler cannot prove a lost handler has stopped. A parent retains escrow when remote stop remains uncertain, even after effect credits have been settled. Recovery/remote-stop administration is a future contract. Native default History replay remains independent of the opt-in composition release.

Dev21 registers pure custom ContextBuilders through an additive release and a
separate History snapshot; default native context remains compatible. See
[custom context](temporal-custom-context.md).

[DecisionPolicy](temporal-decision-policy.md) adds host/per-Agent pure Harness selection with original request/response/proposal evidence. No new state authority; external Session stores remain pending.


dev65 [Session data reads](temporal-session-data-reads.md) adds opt-in fixed bounded reads for stateless native/sequence only; external durable Session writes and advanced addressing remain unsupported.

## Control failure diagnostics

Unexpected child-control failures retain the original `child_control_failed` result and retry behavior. The Worker emits a warning through `ralf_agent.temporal_control_activities`, with structured `child_control_failure` metadata: a fixed operation label, bounded static traceback locations, real RPC status and up to four wrapped cause codes from a fixed allowlist. Unknown codes are reported as `unknown`. Request bodies, Scope, exception messages/details, locals and absolute file paths are excluded. Known RALF errors retain their existing codes without this extra warning.

Diagnostic collection and logging failures cannot replace the original control response. Business cancellation continues to propagate. These logs are observations, not execution or recovery evidence; original Run/Action/Session receipts remain authoritative. Selected Coding Histories still require their matching immutable Worker.
