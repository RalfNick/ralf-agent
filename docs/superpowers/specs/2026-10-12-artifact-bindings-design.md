# Per-Agent Artifact binding design

## Scope and authority

Continue R01/R18 under the standing continuous-development instruction. Local commits
only, no push. Dev83 baseline30e1746 is accepted:5280 passed/418 configured skips,
core182/SDK149, actual source32/installed32, old82/22 starters and287 modules. Full
R01–R26 remains active. This document is a design, not a dev84 delivery claim.

ArtifactStore/AsyncArtifactStore, memory/SQLite/POSIX file JSON defaults, fixed references,
managed offload intents/receipts and Local/Temporal six compositions already exist.
The independent artifacts binding role is declared but rejected. Implement that role
by composing existing Context and storage, without a new execution authority.

Alternatives: whole Context registration already permits custom storage but couples
independent choices; mutating shared Context leaks configuration between Agents.
Select an explicit scoped Artifact resource and pure effective Context derivation.
Original Engine/Action/History owns writes, receipts, validation and result adoption.

## Resource port and defaults

ArtifactBindingResource borrows one original store; constructor accepts backend,
namespaces(default context-results),default_namespace(default context-results), and required
nonblank ordinary UTF-8 version≤256 bytes.
Optional sync_mode is thread(default) or coordinator, fixed in resource identity.
The backend supplies ordinary bounded fixed identity including its actual backend_id
and completed put/get methods in one sync/async mode. Pin original receiver and code,
physical identity, allowlist and version. Constructor/selection never perform I/O.
A custom store follows the same contract; existing memory/SQLite/file remain defaults.

Namespace allowlist is nonempty/unique, max256 entries, each ordinary UTF-8 nonblank
string≤512 bytes without NUL, and includes default. Selector supports only namespace;
selection outside the allowlist raises AuthorizationDenied before accepting a Run.
Catalog Scope supplies identity. No model-provided backend ID, URI, credentials or path.

ArtifactView is a borrowed async port for existing managed Context put/get. It preserves
physical backend_id/Scope/namespace in ArtifactReference and does not rewrite references
into a new authority. Before/after I/O it checks original resource, receiver/methods,
Scope, selected namespace and exact raw reference. Sync delegation uses original ThreadExecutionTracker ownership by default; all existing
Artifact defaults are thread-safe. Explicit sync_mode=coordinator supports a thread-affine
custom store on the caller thread; it can block that loop and is never secretly threaded.
Async uses the original completed memory_call contract. Resource.wait_for_calls drains
its fallback actual tracker for standalone callers; borrowed backend is not closed. Invalid/lazy/
wrong reference, lost identity and unbounded values fail before adoption. put references
must match the independently predicted reference; original managed stage performs the
read-back. The view does not close/delete or expand permissions on the original store.
Existing JSON artifact1MiB upper bound stays; binary transfers/GC/cache/S3 are separate.

## Pure Context binding

An explicit artifacts ref/disabled requires an effective managed Context that supports
a pure artifact binding port. Port artifact_binding_identity(resource_metadata_or_none)
predicts finite bounded policy identity without clients; bind_artifacts(view_or_none)
returns a completed ManagedContextPipeline with exactly that predicted identity and fixed
origin/selected resource metadata. Check equality before publication/dispatch; no I/O, hidden
model call or permission grant. Original ManagedDataContext supplies the default.
Host custom managed Context implementations may implement the same port; incompatible
Context fails before Run submission, never silently ignores an explicit selection.

ref derives a ManagedDataContext with selected target and physical namespace. Preserve
original assembler, summarizer/model mode/provider/time/source limits, projection and
reference-excerpt settings. Check the original Context and target on every use.
disabled removes offload while retaining history summaries/reference excerpts; use a
pure managed reference Context, never a fake store that pretends to accept writes.
inherit preserves exact original Context object/identity and absent release fields.

Use a weak-value cache in the original Local binding resolver keyed by original Context
and backend object identities plus fixed Scope/resource/selection. Derived objects hold
origins while alive, preventing identity reuse collisions. Revalidate before cache reuse;
weak entries avoid retention proportional to historical Runs. Keep the same derived
object through a managed phase so existing post-await _actual checks remain meaningful.
Cache is assembly-only and stores no Run/Action/adoption state. Temporal selected runtime
realizes an equivalent pure view; effective_manifest computes matching finite identity
from registration metadata and the pure prediction port, without constructing clients or
performing I/O. Custom prediction and realization must share the same metadata schema;
a mismatch is DefinitionMismatch before any artifact operation.
Temporal host publication precomputes the bounded pure prediction for each approved
resource/namespace and disabled target for each compatible Context. History selects only
these fixed JSON templates; it never imports or calls a custom Context predictor.
Explicit incompatible Context fails before Run acceptance; an unused incompatible
Context registration need not be silently converted. Target/provider/implementation
registration is derived from the same prediction, and actual selected runtime equality
is checked before dispatch. Publication pins the original two binding methods.

## Binding and version admission

Reuse existing AgentBindingDescriptor.artifacts, BindingCatalog and stable six member
paths. Selectors only narrow the registered resource. Root/member target choices remain
fixed in accepted manifests, auxiliary actions, intents, receipts and context snapshots.
Original Context writes/reads/cancellation/end evidence and quotas continue unchanged.
All six Local/Temporal actual Agent compositions support ref/disabled/inherit: native,
sequence, graph, Team, dynamic and nested. Incompatible selections fail before any
model/tool/storage dispatch. Already accepted results use original authority evidence.

Local explicit selection publishes local-bindings-15; old inherited releases unchanged.
Temporal Artifact resources or explicit selections publish artifacts_binding_protocol1
with recognized binding_protocol5; verify old83 pure admission BEFORE wiring and actual
old83 Worker pre-Activity refusal before delivery. Validators admit5 only with the joint
Artifact protocol and original effective Context proof; preserve exact legacy1/2/3/4.
Older Worker construction refusal has History evidence but no queryable RALF state.
For protocol5 only, an Artifact read/verify Activity timeout before any allowed original
History dispatch grant can recreate that read Action once per phase/artifact. Original
History fences the old Action before admitting the replacement; late grants are denied.
The retry is durable and bounded, does not repeat tools or writes, and never applies to
an admitted handler or legacy protocols1–4. An uncertain dispatched writer remains
nonquiescent even after content is verified: content receipts do not prove actual end.

## Configuration and lifecycle

Add artifacts/scoped-store binding declaration containing version,namespaces,
default_namespace and a nested artifact_store declaration; reuse existing registry
SQLite/file/custom factories, with a memory default for SDK and deterministic explicit
persistent paths in Profile examples. Both build/abuild support ordinary sync stores;
async store requires abuild and has no implicit connection during pure preflight.
BuildContext owns declared stores and derived resource assembly; injected stores and
Catalog resources are borrowed. Partial assembly closes only owned resources, reverse
order; shared stores remain usable after another Agent closes. No default-profile or
starter-tree identity churn; historical original release routes remain available.

## Acceptance and remaining boundary

TDD exact ordinary fields, namespace denial, raw/lazy references, identity/receiver/code
mutation, sync/async replacements, borrowed ownership and no-I/O preflight. Prove pure
Context derivation, disabled offload without fake receipts, stable weak phase cache and
no historical retention. Original Local/Temporal stage recovery, write receipt loss,
actual-thread/global-loop cancellation/end and six member compositions require evidence.
Use real SQLite/file defaults and a separate explicit async contract store; no fabricated
storage/stop proof. Old83 two-way defaults/native Sandbox/default22 starters, new Worker
refusal, core-only/SDK installed docs and frozen package/full-suite gates all required.
Version stays83 until actual compositions pass; one fresh strongest read-only final
review per batch, all findings/Declined regraded before one Important fix pass; Minor
ledgered. Dev83 M1/M2 remain separately deferred here, not silently included as fixes.

Artifact binding subset does not complete H1/H3/R18 or AgentScope parity. Remote artifacts,
retention/GC/cache/binary transfers, other resource selectors, business/model quality and
enterprise governance need their separate contracts/evidence. All owned test services
must actually stop and be waited; preserve user Docker platform/other plan workspaces.
