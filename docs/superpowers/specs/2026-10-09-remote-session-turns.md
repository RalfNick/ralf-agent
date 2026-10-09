# H2b4a — Remote-backed native/sequence Session Turns

Continue uninterrupted implementation from dev37/1f27300. Extend the existing Local
Session authority to remote data; do not create distributed admission or another
state machine. This increment supports native/sequence durable Turns on a single
remote backend/namespace. Composite roots keep their existing colocated behavior.

Session backends opt in with exact session_receipt_version=1 and async
inspect_message(scope,session_id,message_id). The result is completed finite JSON:
{scope,session_id,message_id,revision,receipt}; receipt is null or
{revision,message}. The outer revision is the current session revision; a receipt's
positive revision does not exceed it and its message is the exact stored payload.
Redis uses atomic Lua lookup and PostgreSQL a scoped transaction; neither reads
full history. Existing read/append/page and stable message-ID deduplication remain.
Custom backends must implement that same atomic CAS/dedup/inspection contract.

Existing SessionBindingResource/Profile session-resource declarations work without
a new caller role/class. All native/sequence steps must select the same backend,
namespace and receipt protocol. SessionKey fixes the declared remote resource while
coordination_ref fixes the original local authority/locator. Slot addresses remain
conservatively unique within Scope across backends; raw address reuse is refused
regardless of backend alias on remote registered addresses. A different backend
requires a new namespace/Session ID. Original backend_id must identify real storage;
trusted adapters remain responsible for that identity.

First valid remote open/rebind activates semantic schema5 through an optional
prepare_remote_sessions()->None port and exact Store marker4; old dev37 refuses5
before dispatch. Default native/composite schema1/2/3/4 paths and original identities
remain unchanged. Failed activation rolls back. Run admission independently records
the original remote descriptor, including namespace=None. Missing/drifted metadata
refuses before effects, and observations need no remote connection or current model.

Before a required remote result append, the original Run commits the immutable
node/message/source intent. Inspect first; a matching already-stored receipt skips
append. Otherwise commit the dispatch attempt, append with the observed revision and
stable original message ID, then inspect and durably record the scoped matching
receipt before final node/Run success. A numeric append result alone is insufficient.
CAS conflict, connection failure, ambiguous outcome or missing confirmation pause
at waiting_reconciliation; explicit resume makes at most one save attempt and uses
the already-adopted model output without another model/tool execution. Conflicting
payload/identity refuses. No cross-database atomicity or arbitrary exactly-once claim.

Actual in-flight operations retain the original Engine/Coordinator lifetime. Caller
wait cancellation only observes; cancellation/failed commit may leave a remote write.
Terminal explicit resume queries pending intents without another append/business
operation, records any real receipt and leaves the original terminal outcome intact.
Unknown terminal writes hold Session capacity when no receipt is available. Pure
status derives eligibility from validated journal receipt evidence; it is not a
remote availability/data-retention check. Saved messages are sourced observations,
not proof of a successful business Run. Composite remote roots, cross-authority
shared Turn admission and Temporal Session binding are subsequent gates.

Acceptance: actual SQLite authority plus an async foreign-SQLite contract fixture,
native/sequence red/blue/default namespaces, receipts and no full-history final read,
remote append committed before response failure, one effect and no repeated model,
missing/malformed receipts, metadata/Scope/backend drift, raw alias protection,
restart approval and data-save recovery, cancellation/real-operation capacity,
monotonic/rollback schema5 and actual old reader refusal. Redis/PG inspector
conformance and configured live-service probes when locally available; unavailable
services remain explicit skips. Full regression, installed wheel, default old/new
compatibility, lint/docs/package hygiene and one fresh review are required.
