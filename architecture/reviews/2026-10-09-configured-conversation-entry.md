# dev37 — Configured conversation entry

Baseline: committed dev36/1cad308. Root declarations use the existing Profile1/2
shape and sync/async RuntimeBuilder; the builtin colocated-session factory borrows
the original execution connection. Configuration validation occurs before Store
creation, and schema4 still activates only on a valid composite Session open.
An installed sessions starter provides run/replay, original Turn/Profile reconnect
and pure status. The original Engine and SQLite Session authority own all facts.

One fresh read-only review verified25 new tests and extra preflight/lazy cleanup,
Coordinator reacquisition and cancelled-wait reconnect fixtures. It found one
Important issue, no Critical or Minor issues: replacing a terminal Run's saved
Profile with a different genuine Profile could bypass the missing-original guard.
The regression failed first (expected refusal, actual success); resume now compares
the reference with the scoped persisted runtime_profile and resolves that original
identity before runtime construction. A single fix pass was verified; no re-review.

Final evidence:

- Task gates106/104 passed; post-fix focused26 passed.
- Full regression, warnings as errors: **2457 passed,56 conditional skips**.
- Actual installed wheel outside checkout: **212 contract tests passed**.
- **44 actual old/new wheel recovery scenarios**,22 each direction, across
  native/sequence schema1/2, six composite schema3, six schema4 red and six explicit
  None cases. Turns, manifests, approvals and control receipts remain original;
  effects occur once per Action. Old dev36 rejects the new Profile declaration;
  its existing schema4 SDK assembly remains compatible.
- Old wheel matches149 baseline SDK files; wheel/sdist/installed dev37 matches151
  SDK files byte-for-byte.294 public exports resolve with optional clients blocked;
  previous20 installed starter trees are unchanged. The new21st starter runs,
  replays and reconnects from an installed SDK. Dependencies/extras/scripts unchanged.
- Ruff, format, whitespace, local docs links and package hygiene pass. No credentials,
  environment files, databases or private workspaces are included. No paid calls.

Rulings and practical costs:

1. Continue the approved architecture inline and commit verified increments without
   approval stops, as explicitly requested. Cost: routine design choices are made
   autonomously and documented for review.
2. Extend component declarations without a new Profile schema because absence keeps
   old payloads identical and unknown kinds already refuse. Cost: older SDKs cannot
   load the new built-in declaration.
3. Correct the compatibility gate: dev36 already supports schema4; verify old
   declaration refusal and bidirectional schema1/2/3/4 recovery. Cost: new Profile
   syntax needs dev37, while compatible explicit SDK assembly does not.
4. Remote conversations, Temporal Session bindings, queues and enterprise identity
   remain separate gates. Cost: this stage exposes only the published colocated path.
5. Offline fixtures verify integration without paid/provider calls. Cost: no real
   model quality or provider compatibility inference follows.
6. The executor completed the post-fix full/installed/wheel gates; the reviewer ran
   focused and extra boundary fixtures. Cost: unconfigured live services remain
   unverified by these offline checks.

Deferred minors: none reported. Continue remote Session storage and Temporal
capability binding work; complete H2/H3 and framework parity remain open.
