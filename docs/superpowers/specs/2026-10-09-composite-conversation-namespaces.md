# H2b3 — authorized composite conversation namespaces

Continue approved H2 capability work from the current dev35 workspace, preserving
all existing uncommitted changes. One LocalEngine/SQLite authority owns admission,
Turn ordering, approval, evidence and final result. No independent Facade state machine.

## Public behavior

LocalEngine accepts an optional host-configured `conversation_resource` using
SessionBindingResource backed by actual colocated SQLiteMemory. It is borrowed;
the actual Store connection still follows the Engine owner. The ordinary
`session_store` remains the original member default and refuses selected views.

Agent/Runtime.open_session gains optional `namespace`. Omission selects the host
conversation resource default; explicit None selects None when allowed. Explicit
namespace selection is composite-only; native/sequence continue existing leaf
bindings and reject this new option. With no conversation resource, default
composite opens remain byte-compatible with dev35; unauthorized selectors refuse.

Root selection records the concrete resource identity and namespace in the original
Session binding revision. Same logical ID in red/blue roots has independent keys,
physical addresses and original child addresses.
Each configured Turn independently records this descriptor on its original Run in
the admission transaction, including None. Missing/inconsistent evidence refuses
before effects and final save; genuine legacy Turns in mixed schema4 remain valid.
The composite parent Session ID
is the canonical storage key, preventing shared sequential-node history/occupancy
across root namespaces. Default None IDs/definitions/manifests/receipts are unchanged.

Duplicate open/submit/control replay precedes current selection resolution. New
admission/rebind requires original/current binding agreement and the same actual
route. Rebind may cross native/composite kinds only when existing leaf binding and
root selection resolve to the identical key. Changing namespace uses a new Session.

The authority revalidates original conversation binding before effects through
existing _check_release calls, including parent checks in descendants, and before
atomic final append. Reads/attach/status remain pure and can inspect original
records with unavailable/moved configuration. No global current-namespace pointer.

## Compatibility and admission

An optional synchronous `prepare_conversations()->None` admission extension and
exact Store marker3 enable the new descriptor. Successful configured composite open
or idle rebind atomically enables semantic schema4. Failed/busy/mismatched requests
roll back activation. Existing default composite opens remain schema3; native-only2,
raw1. Later preparation never downgrades4. New readers support1/2/3/4; actual dev35
readers refuse4 before dispatch, because they cannot validate the new binding.
Marker2 adapters retain default composite support; marker1 retains native support.

Allowlist, Scope, actual backend/connection, completed port values and raw-route
protection are checked before acceptance. Root metadata is not a model input or
enterprise authentication. Remote conversations/Temporal bindings, FIFO, H3 and
enterprise governance remain separate gates. No default dependency/export/starter
changes, paid calls, auto commit or push.

## Acceptance

Real SQLite tests cover seven compositions, red/blue same-ID independence,
canonical parent/member addresses, actual final saved content, original submit/control
receipts across restart, selected leaf bindings, raw alias refusal, allowlist/backend
and scope drift before tool execution, evidence-preserving late drift, rebind,
malformed/lazy ports and activation rollback/monotonicity. Actual captured dev35
wheel recovers1/2/3 in both directions and refuses4; installed dev36 recovers4
approval with once-per-Action effects. Full regression, package/source byte equality,
optional-free imports, docs/lint and one fresh read-only review are required.
