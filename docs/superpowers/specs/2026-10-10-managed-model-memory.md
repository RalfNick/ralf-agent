# H3a2 Managed model-selected memory (dev42)

Purpose: complete opt-in automatic model field selection after Local native/sequence
completion, using the existing stage_policy grant and original Run authority.
Baseline0d17976/dev41. User authorizes continuous inline development/local commits,
no push or routine approval menus. Original296 exports/21 starters and schema1–8/default
release identities remain compatible. No dependencies or paid model calls this stage.

ManagedModelMemoryPolicy subclasses ManagedMemoryPolicy, accepts a host provider alias
and bounded selector input size, and exposes pure request(source)->ModelRequest and
select(source,received_response)->list[FactProposal]. It reuses ModelMemoryExtractor's
field-selector instructions/schema, not its standalone child-Run executor. Model may
return unique allowlisted keys only; values/paths are copied from fixed result evidence.
Model I/O never runs in propose, admission, ContextBuilder or binding resolution.

The Engine fixes the selector provider's identity in managed_memory release metadata.
Catalog registration checks policy only; Run acceptance resolves/pins the host alias.
Actual policy/method/provider/target identities are checked before and after I/O.
Default ManagedMemoryPolicy identity and behavior are unchanged.

Original memory_stages journal records selector request/dispatch/response/selected keys
before normal fact proposal/CAS stages. The adopted model Action carries independent
intent/response/selection markers. Selector reserve costs1 original Run execution credit;
actual fact writes retain existing1-per-fact accounting. Returned invalid output pays1
and writes nothing; undispatched invalid/expired/exhausted input pays0. Missing response
holds1 as unknown, never retries, never falls back to storing all fields.

Prepared selector must have no reservation; executing/received/final evidence must agree
with independent Store proof. Response acceptance and field/CAS proposal adoption are
separate checkpoints. Restart reuses saved response/keys and does not rerun business
model/tools, Session save or completed CAS writes. Empty keys is valid, completed no-op.
No current record, Scope, source, marker or reservation contradiction is tolerated.

Cancellation is rechecked inside dispatch transaction; managed operation remains owned
by the existing Engine guard/thread tracker until real completion. Terminal selector
recovery only settles saved response or marks interrupted dispatch unknown, never starts
model selection or new facts and never upgrades business state. Evidence-only terminal
selector settlement works without a current provider. Existing fact-write reconciliation
continues under its existing exact-target/release contract.

New policy activates optional Store model_memory_stage_version=1 and atomic
prepare_model_memory_stages() semantic9, before accepting the Run. dev41 refuses9.
Graph/Team/dynamic/nested/Temporal automatic policies remain refused. Per-Agent stage_policy
inherit/ref/disabled and JSON/TOML sourced-memory/sourced-memory-async factories support
explicit mode=model plus host provider alias, reusing existing owned-client factories.

Auxiliary unknown/failure does not replay or invalidate a completed business result;
Facade pending controls expose unfinished/unknown selector stages. Unknown credits are
not released automatically; there is no model-response query/retry protocol.
Semantic memory revision, automatic free-form synthesis, Session/RAG compression,
artifact offloading, recommended presets, advanced/Temporal stages and true model quality
remain open. Source observations are not proof of business truth or verified beliefs.
