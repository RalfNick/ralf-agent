# Codex delegated Runner implementation plan

> **For agentic workers:** Use the executing-plans and dispatching-parallel-agents skills. Shared interfaces are integrated by the parent; workers own separate files.

**Goal:** Implement the first concrete Codex App Server bridge under the existing Runner contract, with evidence-based acceptance of an isolated read/write/test application.

**Architecture:** Codex owns its internal loop. Local Coordinator and Temporal History remain the only Run/Action authorities. Native evidence storage and transport are mechanical components; neither schedules business work nor decides Run states.

**Tech stack:** Python 3.11+, existing JSON Schema and SQLite dependencies, POSIX subprocesses, pinned Codex App Server protocol.

**Spec:** `architecture/specs/runner-capability-contract.md` and `docs/delivery-gates.md`, phase 2.

## Constraints and review focus

- Preserve dev99 acceptance and existing release/default/history behavior. Never push remote commits.
- One delegated Action corresponds to one native Turn. A JSON-RPC request ID is correlation, not business idempotency.
- Persist submission intent before native I/O. Lost receipts remain unknown; recovery never blindly submits another Turn.
- Cancellation acknowledgment, native terminal state and controlled successor stop are separate evidence. Existing terminal-before-stop behavior cannot be silently repurposed.
- Native sandbox declarations need actual enforcement evidence. Default `workspaceWrite`, cwd and process-group cleanup alone do not prove the required isolated environment.
- Unknown usage remains unknown. Unsupported governance, hard budgets and native waits must fail closed.

## Batch A: protocol and durable native-start foundation

- [x] Pin the locally installed Codex 0.144.4 generated stable protocol subset; validate selected outgoing parameters and received responses without executing a task.
- [x] Implement bounded stdio transport: fixed argv/environment, request correlation, notifications/server requests, no automatic approvals/retries, actual transport cleanup.
- [x] Implement exclusive durable native StartIntent/Thread/Turn evidence, immutable identity, at-most-one submission permission, independent cancel intent, restart and alias tests.
- [x] Test these components together with a real finite fake App Server process, including lost Turn receipt and acknowledgment without native-stop evidence.
- [ ] Review, document implemented versus unverified boundaries, verify wheel packaging and locally commit.

Batch A is an implementation milestone, **not** acceptance of an external Coding Runner. It deliberately exposes no Engine selection or factory claiming a runnable isolated application.

## Batch B: restricted environment and authority integration

- [ ] Prove a concrete restricted environment: retained scoped workspace, read/write/test capability, denied protected roots and general network, disabled unapproved MCP/plugins/hooks, credential separation, successor containment and output export.
- [ ] Add explicitly versioned delegated admission and stop-gated cancellation to Local and Temporal, including cold restoration; preserve old Run behavior and old-worker rejection before business I/O.
- [ ] Integrate the concrete bridge through managed Actions, approved input, native query and original receipt adoption. Add enabled native interaction handling only with independent evidence.
- [ ] Provide the installed reference application/configuration and recovery tests; run real Codex smoke and actual Temporal/Worker recovery in the verified environment.
- [ ] Publish descriptor × external version × profile conformance evidence. Unverified capabilities stay open.

## Verification

Development uses affected tests. Phase integration adds full regression, installation and compatibility checks. Failed attempts and exact environment/schema/binary identities are retained. Completion is measured by delivery gates, not module count.
