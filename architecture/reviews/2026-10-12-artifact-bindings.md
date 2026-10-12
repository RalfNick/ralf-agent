# dev84 Artifact bindings — accepted subset

Baseline:30e1746 / dev83. Local commits only; no push and no paid model calls.
Spec: [Artifact bindings](../../docs/superpowers/specs/2026-10-12-artifact-bindings-design.md).
Plan: [implementation](../../docs/superpowers/plans/2026-10-12-artifact-bindings.md).

## Implemented subset

Borrowed ArtifactBindingResource and scoped async views, fixed physical identities and
host namespace allowlists. Default memory/SQLite/POSIX JSON stores and custom sync/async
ports reuse original actual-handler owners. Pure Context prediction and derivation keep
summary/provider/projection settings; explicit disabled never fabricates a write receipt.
Local ref/disabled uses bindings15; Temporal joint binding5/artifacts1 uses original
History admission and managed phases. Inherited releases retain their original routes.
Profiles reuse nested ArtifactStore factories, owned declarations and borrowed injection.
All six native/sequence/graph/Team/dynamic/nested compositions have actual SQLite/file
routing, approval restart, lost write ACK verification and History replay evidence.

## Evidence before final review

- Task1:187 passed69.18s; Task2:186 passed23.45s.
- Task3 unified:155 passed237.48s, no required skips. Includes independent Worker
  crash/read fencing, actual async replacement/cancellation, old83 two-way Local/CLI/
  Temporal/native Sandbox compatibility,22 unchanged starters and actual old Worker
  refusal before any Activity.19 compatibility Workers stopped and waited; own Sandbox
  invocation finally observed not_found.
- Documentation:5 original standalone code blocks and4 default-store variants pass;
  these are offline assembly examples, not live model quality.
- Full frozen suite, fresh installed core/SDK/services, package provenance, sole fresh
  review and actual owned service exit were pending at this checkpoint; see final acceptance below.

## Recovery limits

For new joint5/ref only, original History can fence and recreate an Artifact read or
verify once per durable phase/artifact if no allowed dispatch grant ever existed.
Late old grants are denied; already granted reads and legacy1–4 never use this retry.
Content verification after a writer ACK is lost may permit succeeded/verified while
unknown_remote_execution and nonquiescent remain. Actual end requires original History
proof; a local PID wait does not fabricate it. Remote stores/binary transfer/GC/cache/
retention/cross-host governance and complete R01–R26 remain open.

## Decisions made before final review

Ruling: resource/versionrequired256UTF8; namespaces1..256 ordinaryUTF8≤512bytes/noNUL; ArtifactJSON1MiB unchanged. Borrowed asyncview usesoriginaltracked memory_call forsyncbackends, originalScopebeforeafterI/O — costifwrong: cannotclaim larger/binary/remote artifacts or arbitrary opaque customstopcertification.

Ruling: explicit ref/disabled requires declaredpureContextbindingport with BOTH metadata prediction and realization; customManagedContexts supportedonlythroughthisport. Incompatiblecontext failspreRun, inheritbyteidentical. Weakvaluecache keyedoriginalobject/resource/selection; valueholdorigins preventsidreuse — costifwrong: no universal binding arbitraryContext or fallback; customportauthor needsconformance.

Ruling: Dev83M1actualTemporalSandboxCI/M2typedmissingServerVersion remainseparatelydeferred, notsilentlyfixedinArtifactbatch — costifwrong: knowncoverage/typeconsistency gaps stayopen untilseparatework; allcapabilitiesgoalstillactive.

Task1BASEda5f86a /root84/private/tmp/ralf-agent-dev84-vrv35fgn pointer/private/tmp/ralf-agent-dev84-root. Old83installed Artifactrole ValidationError beforeIO. Initialoldmarker5probe usedUNBOUNDkernel andunknownfieldsignored (no falsefutureclaim); correctedActualold83runtimeBindingCatalog→temporal-3 verified binding5 DefinitionMismatch beforeANYIO. Ruling: Artifactpublisher MUSTtemporal-3 binding_catalog+recognized5+Artifact1; markeronunboundkernelalone isnotadmissionproof — costifwrong: olderWorker couldignoreunknownfields, requiredactualold83refusal remainsTask3/4. NoProductcodeyet.

Task1resource5880 actualexit1/read19FAIL1.11s missingArtifactBindingResource validRED; initialruffB018 beforetest correctednotRED. Sourceinspection memory_call executes sync oncoordinator, NOTthreaded. AlloriginalArtifact defaults RLock+SQLitecheck_same_thread=False. RulingBEFOREcode: asyncView sync_mode=thread(default) usesoriginalambientThreadExecutionTracker/fallbackresource tracker; explicitcoordinator supports thread-affine customstore andblocksloop. Asyncusesmemory_call andcompletedrawvalidation; standaloneResource.wait_for_calls drainsfallback tracker, borrowedbackendneverclosed — costifwrong: customsyncPort mustdeclare/selectthreadsafe orcoordinator, defaultThreaddispatchnottransparentforaffineclients. Spec/planrefinedbeforeproduct; no inventedbusinessauthority.

Task2rollbackdebug correctedtestfactoryregistration misplacedbyhunk, actual3PASS1.02s customunmanagedrefusal/real-threadcancel/ownedrollback. Final22672 exit0/read186PASS23.12s includes12realSQLite/file sixcompositions+6committedcrashwindows+approvalrestart+asyncclients+weakcache/oldbinding/Context contracts. Ruff/diffPASS; isolatedSDKguide originalcodePASS. Ruling: stateunchanged/noI/O weakcache onlywhileactualphaseholdsderivedobject; customports matchingmetadata muststillreturn ManagedContextPipeline bounded1MiBidentity — costifwrong: arbitraryContextobjects unsupported explicitbinding; customportauthors oweconformance. Task2completecommitnext; stay83.

Task3BASE9f33cc4 briefread. RulingBEFOREcode: hostpublishes purepredictions finiteapprovedresource/namespace+disabled templates percompatibleContext; originalHistoryselectsfixedJSON only, noPythonpredictor/clientI/O. Actualruntimeprediction-realization equality beforedispatch; pinoriginalbindingmethods. Incompatible unusedContext mayremainregistered butexplicitselection refusebeforeRun. Costifwrong: metadataCartesian Context×namespace boundedpolicygrowth; explicitconfiguration needsmanageablecatalog; no arbitraryunregisteredselector. Old83 boundkernel5refusalalreadyverifiedTask1 beforeimplementation.

USER2026-10-12 explicitlyrequestedparallelacceleration; priorinline/nodelgationpreference superseded. Ruling: threeagents independentexclusivefiles (recoverytests, old83compat, docs), rootproductionintegration/solefinalfreshreadonlyreview/allImportantunifiedpass/frozenfull/build/commits. Costifwrong: sharedfilesystem/service risks controlledbyexclusivefileowners+uniqueScopequeue+noagentsbuild/Git/servicecleanup; changesrootintegratedbeforefinaltests. CurrentownTemporalhealthSERVING verifiedaddress17287, PID12900/session19994. Agents recovery_tests,compatibility,docs eachstartedforknone; nootherplanSDDreads ormods.

Recoveryparallelthird real4FAIL31.62s: originaldeliveredArtifactread killedBEFOREHistorygrant permanentlyfails, despiteoldHistoryprovablyunadmitted; receipt2succeeded/verified/countersbutnonquiescent expected originaluncertainwriter rule, notbug. RulingBEFOREcorechange: protocol5only durableone retry per phase/artifact foractivity_outcome_unknown + noallowedHistorygrant, fenceoldoriginalAction before replacement; admitted read neverretry/noendfake/old1–4 unchanged. Costifwrong: requiresatomicHistoryadmissiontruthfulports; boundedextraordinaryreadActivity noextraeffects/budget, remainingreadfailclosesRun. Originalunknownwritercontentreceipt stillNOTend andnonquiescent stays; externalactualstopproof broadergoalopen. Specrefined andrealfailedtestkeptbyagent; rootofflineREDnext.

Task3integration rootnew5 pregrant-read unit4PASS3.72s and original54PASS4.45s; real recovery agent9PASS41.38s, compat10PASS60.59s (19ownedWorkers gracefullyexited; ownSandboxnot_found), docs5blocks+4variantsPASS. Rootproduction f4b9445. Integratedtaskdone26217 actualexit1/read1FAIL154PASS237.56s: dynamic-file fixturefixed8 immediateparentdrive observations exhausted before originalasyncchild-control Activityended. SavedactualHistoryroot84/task3-dynamic-failed-history.json proves8 driveUpdates accepted within1.47s; originalControl Activitystillpending andlaterWorkerclose causedtimeout. Ruling: use bounded30s conditionconvergence withoriginalsameapprovalcommandID, terminal-onlystop, 50msyield, matching existingapprove_all contract. NotproductionRED andnoProductchange. Actualtarget39394 exit0/read1PASS15.29s. Costifwrong: boundedtest could stilltime out withdiagnostics; cannotmaskfailedterminal orduplicateeffect. Testlocalcommit recordedbyretrytaskdone. Docsoriginal5blocksrerunafterformat and4variantsrerunwithwhitespace-independentpathremoval allPASS. Task3notcomplete until unifiedrerun.

## Deferred existing minors

Dev83 M1: actual Temporal Sandbox CI omission. Dev83 M2: missing ServerVersion can
raise an untyped error. Both remain separately deferred; this batch does not claim
to fix them. New review findings and any Declined list will be regraded together
before one unified Important RED→GREEN pass. No second review.

## Sole independent review and unified fix pass

One fresh read-only gpt-6-astra/high review of30e1746..005e9de found7 Important
and2 new Minor. Both new Minor were regradedImportant: a custom read cannot ignore
caller max_bytes, and lazy-return rejection must close returned coroutines/generators.
All9 findings and all7 Declined behaviors were regraded before one fix pass; no re-review.
Original backend/receiver/callable and sealed namespace/Scope guards now reject custom
equality substitutions. Reads keep immutable original metadata, independently check the
delegated reference and enforce limits before I/O. Local weak original-port pins guard
assembly/first use/cache reuse without retaining retired Contexts; pure prediction
arguments are detached and full source/target/mode/preserved-policy proof is required.
Temporal registration fingerprints and coordinated policy copies are checked; known
incompatible inherited default ports are omitted without hiding genuine predictor errors.
Explicit artifact_bindings=True supports disabled-only SDK/Profile publication with an
empty scoped Catalog; defaultFalse is omitted from old Profile identity.

Initial31 real failing cases across review reproductions, plus3 added alias/sealed-guard
cases, are corrected. Original lazy coordinator and genuine custom predictor refusal were
already passing and are not claimed as new RED. Final focused272 passed31.24s;
actual disabled-only Temporal1 passed4.52s. Source full/fresh install/provenance and
actual owned-service exit were pending at this checkpoint; final evidence appears below.

All Declined rulings stand with explicit costs: content is not writer-end proof;
trusted Python ports owe truthful internals, without adversarial isolation guarantees;
standalone borrowed calls require draining the resource tracker before caller close;
opaque/native fingerprint expansion remains a separate compatibility boundary;
remote/binary/GC/cache/cross-host governance/quality/full R01–R26 and AgentScope parity
remain separate targets; executor final gates are not inferred; dev83 M1/M2 remain
deferred. These decisions do not weaken concrete original-reference/receiver guards.

## Final acceptance

最终源码5431 passed／447配置跳过（678.60s），核心104／SDK242安装、真实源码51／安装51（均零跳过）、旧83双向兼容／22原模板／旧Worker零Activity拒绝及291模块一致通过。九类Important经一轮34项有效失败复现统一修复；本任务Temporal PID12900／session19994实际退出0并已等待，用户Docker平台保留。完整R01–R26、远端／binary／GC／cache／治理与真实质量继续开放。

Five standalone docs blocks andfour store variants pass both source and isolated installedSDK. Core-only104 andSDK242 contracts, coreold83three andSDKold83ten compatibility cases pass; both immutable old83 environments remain byte-identical to their287-module snapshots. No paid models; offline business8/8 and planning3/3 report model_quality=null. First full attempt had the stale selector assertion and one unexplained20s fixture timeout; only the assertion was changed, isolatedData/Receipt28 pass and final complete run passes without increasing timeout. Build and full were never concurrent; installed actual tests used separate scopes/queues. Final docs-only rebuild and exact payload/CI/link provenance are checked separately below.

Final docs-only wheel/sdist rebuild and fresh core/SDK reinstalls preserve all291 frozen product hashes. Sdist811 docs/tests/examples/evals/config payloads match exact checkout bytes;201 independently parsed CI pytest file arguments resolve,11 changed Markdown documents have475 valid local links. This rebuild happened after the full run ended, without repeating unchanged business execution.
