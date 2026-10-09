# Hybrid Retrieval Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. One fresh final review, no implementer agents. User continuation and developer autonomy authorize implementation; no repeated design approval/commit/publication gate.

**Goal:** Review/harden dev18 and deliver offline-default composable D2 retrieval with explicit semantic HTTP adapter.
**Architecture:** Closed embedding DTO/HTTP lifetime; pure fusion/rerank ID proposals; Hybrid validates candidates through one knowledge authority. New opt-in assembly names retain old defaults and templates.
**Tech Stack:** Python3.11+, httpx/jsonschema existingbase; existingSQLite/asyncPG/Qdrant.
**Spec:** ../specs/2026-10-07-hybrid-retrieval-design.md

## Global Constraints
- Base2dependencies/6extras unchanged; current84SDKmodules/211exports baseline actualdev18wheel.
- No implicit paidcalls/retry/URLfetch/indexing; no realsemantic qualityclaim.
- Defaultnative local-4/nativeTemporalHistory/old15templates preserved; hostresourceownership.
- Specbounds4096texts/32768each/4MiBtotal/4000000values/32batch/262144batchchars/8MiBresponse; Hybrid8branches/256candidates/1MiBJSON maximum.

## Review Focus
- Async receive/close/cancel and invalid laterbatch preflight beforeanypaidcall.
- Fusion/rerank tampering/lazy/mutable methods cannot bypass authority, provenance or budgets.
- Degraded results explicitly name missingbranches; malformed/scope/source failures neverdowngrade.
- Concurrentrankers and expiry acrossawaits; structured branchcleanup beforeborrowedresources close.
- Old default identities/templates/history and profilealiasreplay survive additiveconfig.

### Task0: dev18 review corrections
Files ingestion_types.py/status; tests/test_document_ingestion.py.
- [x] RED malformedchunk-ID/nonmonotonic/outofboundlocator accepted.
- [x] Validate self-consistentimmutable receipt; preserve historicaldefaultpipeline.

### Task1: explicit HTTP embeddings
Files embedding_http.py/embedding_response.py; tests/test_embedding_http.py.
Consumes oldEmbeddingProvider/VectorRetriever; produces OpenAIEmbeddingProvider.embed/embed_result, EmbeddingResponse.
- [x] RED API missing; strictrequest/sortedindices/usage/float/count/dimensions/bounds/errorredaction/borrowedownedclose/cancellation/failclose.
- [x] Implement bounded HTTP batches, pureimmutableconfig, lazyownedclient and loopsafe trackedlifetime; GREEN wirefixtures andexplicitlocalHTTP.

### Task2: composable rank/retrieve
Files retrieval_ranking.py/retrieval_pipeline.py; tests/test_hybrid_retrieval.py.
Consumes authorityChunk/GetChunk and KnowledgeRetriever; produces FusionRank/RankFusion/RRFFusion/Reranker/AsyncReranker/PreserveOrderReranker/TokenOverlapReranker/HybridRetriever.
- [x] RED literalRRF/replaceablefusion+ranker, boundedparallelunion/dedup/conflict/failures/cancel/drift/lazy/scope/expiry/revalidation.
- [x] Implement oneauthorityvalidation, ID-only proposals and structuredbranchlifetime; GREEN meaningfulsourcedata behaviors.

### Task3: default assembly, installed starter, verification
Files knowledge_factories.py/hybrid_starter.py; builder/starter/CLI/__init__/metadata/docs/CI; tests/test_hybrid_configuration.py/test_hybrid_starter.py/test_hybrid_remote.py.
- [x] RED strictnewfactoryconfig and16thuserdocofflinehybridstarter; noopeningremote resourceoninvalidpreflight.
- [x] Implement additivefactorynames, explicitsecretrefs/ownedcleanup, installedindex/query/reopen/resume; old15dictsunchanged.
- [x] ActualPG/Qdrantcomposition; oneindependentreviewer andImportant RED->GREEN; fullsuite, actualdev18upgrade/TemporalHistory, installed/optional/byteidentity/build/staticchecks; cleanup andhonestD2scope.
