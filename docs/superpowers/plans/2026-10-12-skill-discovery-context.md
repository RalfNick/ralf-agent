# Skills Discovery Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline task-by-task. One final fresh strongest read-only reviewer; no implementer agents. Steps use checkboxes.

**Goal:** Provide replaceable automatic scoped skill metadata discovery through original Knowledge/Context adoption.
**Architecture:** Pure SkillSelector → borrowed SkillDirectoryRetriever → exact native KnowledgeContext → original Local/Temporal Context/History and original skill_get Tool Action. No hidden Harness I/O or new authority.
**Tech Stack:** Python3.11+, original catalogs, optional YAML/Temporal only.
**Spec:** docs/superpowers/specs/2026-10-12-skill-discovery-context-design.md (native KnowledgeContext DTO contract is authoritative).

## Global Constraints

- Baseb3cb8ce/dev81. User continuously authorizes completeR01–R26, local commits/no push; no repeatapprovalmenus. Spec/plan written beforecode, inline/no implementers, one strongestfresh readonlyreview.
- Passive metadata only: no instructions/get/plugin/toolpermissions; scoped catalog list is actualownedread throughmemory_call andoriginalContextread gates.
- Selector ordinary fixedidentity/pure syncselect, limit1..100; directory max_entries1..1000; namesnonemptyunique≤1000 orNone. versionUTF8nonblank≤256; originalnamespace scope and KnowledgeContextprotocol unchanged.
- Completepagination,total,uniqueorder/catalogdigest beforeselection; no silenttruncation/automaticassetdownload/modelcall. Defaults/22templates unchanged.
- ActualsixLocal/sixTemporal+restart/replay/cancel; installedsource tests zeroSKIP, old81actualdefaultcompat/release-rejection and actualownedserviceexit/wait.
- Product stays81 until requiredactual sixcoverage; final82 build/full/docs/install/review/compat gates. FullR01–R26ACTIVE.

## Review Focus

- Automaticdirectory access cannot leak otherScope/names or grantskill_get/businesspermissions.
- Completepagination andcopy/type/Unicode/cyclicmetadata bounds precedevalidation andselector; malformedcustomports/lazy results refused.
- Catalog/selector object, methods, identity fixed throughawait andbeforemodeldisclosure; truthful actualthreads/closing ownedfiles retained.
- Recovery adopts originalacceptedreferences instead of newselection; sourcechanged evidence refuses, terminalcancel cannotpublishsuccess.
- NativeKnowledge Context/DTO/version and perAgent inherit/ref/disabled/namespace retain originalsemantics; olddefaultbyteidentity and actualpackageprovenance.

### Task 1: Pure selector and native directory retriever

**Files:** create src/ralf_agent/skill_selection.py, skill_retrieval.py; modify __init__.py and query_retrieval.py nativecomposition; create tests/test_skill_selection.py, test_skill_retrieval.py.
**Interfaces:** SkillSelector/LexicalSkillSelector(version="1"), SkillDirectoryRetriever(catalog, *,version,names=None,selector=None,max_entries=1000) originalretrieve/validate → RetrievalResult/RetrievedChunk; original KnowledgeContext handlesreferences/limits.

- [ ] Read spec and taskbrief; write publicAPI/normalEnglishChinese/empty/no-match/limit/name/scope/paging/digest/metadata/identity/sourcevalidation tests beforecode.
- [ ] Run focusedtrueRED missingAPI beforeimplementation. Implement deterministicboundedselector andfixedborrowedcatalog read; ordinary revalidate beforecopy, no catalogget/bodyI/O. Fix exactnative metadata/rules, usedchars andoriginalsourcequery.
- [ ] Add maliciouslazy/disallowed/duplicate selection/methoddrift/foreignscope/unboundedpage/forge/getnevercalled andactualblockedthread/close cases; watchneededfailbeforefix.
- [ ] Run .venv/bin/python -m pytest tests/test_skill_selection.py tests/test_skill_retrieval.py tests/test_skills.py tests/test_skill_tools.py tests/test_query_retrieval.py tests/test_temporal_knowledge_bindings.py -q -W error; formalrecordandlocalcommit.

### Task 2: Default declarations and original execution chains

**Files:** create src/ralf_agent/skill_retrieval_factories.py; modify runtime_builder.py originalregistration; create tests/test_skill_retrieval_configuration.py, test_skill_retrieval_execution.py, test_skill_retrieval_temporal_service.py; docs/skill-discovery.md.
**Interfaces:** knowledge/skills-directory-file and knowledge/skills-directory-markdown; borrowedretriever/nativeKnowledgeContext, ownedcatalogoriginalBuildContext; originalperAgentknowledge selectsresource.

- [ ] Tests purepreflight noallocation, JSONdefault/noYAML, optionalmarkdown/scoped names/defaultselector/config limits/asyncowncleanup BEFOREfactoryimplementation.
- [ ] Implement narrowexplicit originalcatalog factories withoutduplicateparserownership; names/namespace/limits validation before rootallocation; adapterwrapper originalKnowledgeContext.
- [ ] SixLocaldefinitions modelreceivesdirectory beforefirstdecision thenoriginalauthorizedskill_get, no additionalpermissions; Agent/Graphrestart originalSnapshot/approval/selectioncount, sourcefailureandcancel.
- [ ] StartownTemporal onlyafterpreflight; actualsix + managedContextread identity/lease/cancel/Workerrestart/History; source/instructionsread onlyoriginalauthorized tool. Installedfinaleight/sixrequiredcases zeroSKIP.
- [ ] Run originalskills/binding/knowledge/context/assemblyfocusedregression, recordformalTask2; localcommit.

### Task 3: Frozen verified capability delivery

**Files:** pyproject/version/CI/guides/status/progress/remaining/harness/CHANGELOG and architecture/reviews/2026-10-12-skill-discovery-context.md.
**Interfaces:** actualpassive directorydefaultsubset, honestH3/H4/qualityboundary.

- [ ] Solefresh strongestread-onlyreview; regradeALLfindings ANDDeclined BEFOREoneunifiedImportanttrueRED→GREENpass; deferMinors/no re-review.
- [ ] Fullgreensuite, freshcore+SDKinstalledcontracts/actualservicezeroSKIP, frozenmodules/wheel/sdist/installhashes/docs/guides/CIargv; actualold81defaultsLocal/CLI/Temporal/nativebidirectional22templates, newadapterrelease actualpreI/Orejection.
- [ ] Stopandactualwait originalownedservices/Workers; main/formalclosurelocalcommits, finaldocrebuildpayloadcheck; archiveonlythisplanSDD with exhaustive rulings/costs/minors; wholeR01–R26goalACTIVE, no push.
