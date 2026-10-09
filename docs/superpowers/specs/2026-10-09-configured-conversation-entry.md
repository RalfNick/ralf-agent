# H2b3 configuration and first-use completion

Continue the user-approved architecture without new approval stops. Local SQLite
remains the only execution and Turn authority. Complete the configuration and
installed-example path for authorized composite conversations before extending
the execution/data boundary to remote services.

RuntimeProfile components gains `conversation_resource`, assembled by the existing
sync/async RuntimeBuilder and Runtime.from_profile/afrom_profile lifecycle. The
built-in adapter is `colocated-session`; config contains only `namespaces` (default
[None]) and `default_namespace` (default None). Its wrapper borrows SQLiteMemory
on BuildContext.store. It neither opens another store nor owns the shared connection.
Namespace validation precedes database construction. Unknown fields, backend/path,
invalid default/allowlist and unregistered adapters refuse before creating a store.
Explicit registered custom sync/async factories retain existing ownership, cleanup,
lazy-result refusal and actual colocated Engine validation.

Existing Profile1/2 declarations/identities remain unchanged when the component is
absent. No new catalog shape/version is needed: old SDKs explicitly reject the new
component. Actual SQLite schema4 still activates only on configured composite
Session open/rebind, never on loading/building a Profile. Native/sequence/raw
behavior and member defaults remain unchanged. Saved runtime_profile and independent
conversation admission evidence remain the original recovery guards.

Add a `sessions` wheel starter (the previous20 remain byte-identical). It uses
offline-echo, a one-Agent graph, JSON spec and TOML Profile with support/sales root
namespaces. `python -m session_app run --input ... --command-id ...` opens its
explicit stable namespace/Session ID and submits a Turn. Results include an
immutable reference file for explicit `resume`; that file contains SessionRef,
RunRef and original Profile identity, not execution state or secrets. Resume resolves
the original Profile from the catalog before construction, validates the original
references and never submits another Turn. Original versions must be retained.
`status --run-id` uses the existing scoped read-only SQLite reader and dispatches
nothing. Reference writes use exclusive creation or equality-checked replay.
App paths are fixed from the chosen --db, with refs namespaced by its absolute
identity; duplicate commands cannot silently overwrite a different reference.

The starter runs offline and keeps its simple graph/tool behavior explicit. Custom
tools/model registrations remain trusted factory code, not configuration imports.
This stage does not add remote conversation writes, Temporal bindings, automatic
H3 I/O, queues or enterprise authentication. Those require separate authority and
evidence gates; declaring a component must never advertise them as available.

Acceptance: real SQLite SDK tests in JSON/TOML and sync/async assembly; same-ID
namespace separation; unchanged members; profile pinning and approval recovery with
original write receipts; default movement/missing original rejection; no database
or model dispatch on invalid assembly; borrowed/owned cleanup; actual installed
starter run/replay/resume/pure status and previous20 starter equality; actual old/new
schema1/2/3/4 compatibility and old Profile-declaration refusal; full warnings-as-errors regression,
package byte equality, lint/docs hygiene and one fresh read-only final review.
