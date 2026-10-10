# H3 explicit HTTP reranking

Baseline 8c606d7/dev47. User requests continued delivery along the capability/architecture checklist and retains continuous local implementation/commit authorization, no push. This architectural adapter increment follows R17; it does not introduce another execution authority.

## Design and alternatives

Add HTTPReranker implementing the existing AsyncReranker and a detached RerankResponse. Use explicit Cohere-style indexed-results JSON over caller-selected base_url + /rerank: model/query/documents/top_n, results(index,relevance_score), optional meta.billed_units.search_units. Protocol checked against https://docs.cohere.com/v2/reference/rerank on 2026-10-10. No vendor SDK dependency, paid default, model download or automatic retry. Do not assert every rerank vendor/model conforms.

Alternatives considered: generative LLM ranking would need a managed Agent/schema and separate token costs; local cross-encoder inference would need optional dependencies/model acquisition. The selected HTTP adapter reuses already async retrieval and current owned factories without changing old default rankings or introducing hidden I/O in pure ReferenceSelector/Harness.

## Adapter and lifecycle

HTTPReranker(model,base_url=explicit,api_key=None,client=None,timeout=60,max_documents=256,max_query_chars=4096,max_document_chars=32768,max_total_chars=262144,max_response_bytes=1048576). Validate integer/finite limits, UTF-8 scalar text, unique original candidates and full request before client allocation. Only query/candidate texts reach HTTP; source metadata, IDs, Scope and provenance are retained locally. For no candidates return an empty report without a request; otherwise require a nonblank query. Send one bounded POST, disable redirects and retries, bounded stream decode; errors redact response/input/secret details. Results must give exactly min(limit,candidate_count) unique in-range exact integer indices, finite scores in nonincreasing order; optional response model, if present, must match. Return original IDs in response order. Never adopt remotely supplied documents.

Identity fixes protocol/model/endpoint/limits/implementation, excludes credentials. Pinned method/resource/config checks across awaits; caller owns borrowed client, factory owns lazy HTTP client. Event-loop affinity, actual active request tracking, cancellation cleanup, concurrent requests and retryable failed close. A closed/closing component cannot dispatch again. RerankResponse returns detached IDs/scores/search-unit usage, missing usage unknown. Relevance scores only order evidence, not correctness/confidence/currency or fusion scores.

Review refinement: actual owned transport/response-stream completion, not HTTPX's early closed flags, gates successful shutdown. Interrupted stream release stays owned for aclose retry; no detached cleanup task is relied upon. Concurrent close rejects, failed/cancelled close blocks new requests. Owned HTTP has an explicit transport with trust_env=False; host proxy/certificate overrides require a configured borrowed SDK client.

## Configuration and source authority

Keep old reranker string declarations preserve-order/token-overlap and old component identities. New nested declaration reranker={type:"http",config:{model,base_url,api_key_env or anonymous:true,limits...}}. Explicit async sqlite-hybrid-rerank-http supports hash baseline plus HTTP rerank; existing sqlite-hybrid-http and postgres-qdrant-hybrid accept nested HTTP rerank through abuild. Offline sqlite-hybrid rejects HTTP reranker before opening databases. Credentials are host env references read only when explicitly chosen; runtime checks config preflight, factory owns reranker via own_async. Optional recommended_profile(semantic-knowledge,reranker=declaration) appends declaration; absent option retains every dev47 preset identity.

HybridRetriever remains unchanged: fixed candidate bodies validated immediately before and after remote rerank, no forged or expanded IDs; branch degrade does not silently degrade a failed reranker. Retrieval calls occur before model context acceptance, not durable model Actions: interrupted preparation may repeat paid retrieval, and execution credits do not account for rerank/embedding fees. No exactly-once/currency ceiling claim. Temporal can explicitly register the same Knowledge port, but Local Profile does not assemble Workers.

## Acceptance

Test-first malformed HTTP results, count/index/score/usage bounds, input preflight/UTF-8, redirects/no retry, owned/borrowed close and real cancellation. Explicit JSON/TOML assembly, no bootstrap HTTP, cleanup on later failure, old identity comparisons. Real localhost HTTP fixture with source-update refusal and native Agent; process exit after durable model response reuses captured context and does not rerank that Action again, then approval emits one business effect. Temporal Activity/History integration without real service. Full suite, installed contracts, dev47/dev48 bidirectional old-combination approval recovery, build/lint/format/whitespace. One fresh whole-increment read-only reviewer as required by executing-plans, one Important RED/GREEN fix pass. Final local dev48 commit and delete only own scratch. No live semantic quality or remote deployment claim.
