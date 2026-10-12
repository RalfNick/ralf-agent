# Standard Skill Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task-by-task. One final fresh strongest read-only reviewer; no implementation subagents. Steps use checkbox syntax.

**Goal:** Replaceable pure Skill document parsing and fixed-file default catalog compatible with original native read tools.
**Architecture:** ParsedSkillDocument/ParserPort → bounded YAML parser → original owned File snapshot and existing Memory/Catalog/Source1 → original Skills binding/Local/History. No new execution authority.
**Tech Stack:** Python3.11+, standard library and opt-in PyYAML>=6,<7; existing contracts.
**Spec:** docs/superpowers/specs/2026-10-12-skill-documents-design.md

## Global Constraints

- Base3de04c2/dev79; inline/local commits only/no push. Keepdev79 until requiredactualsixpass then80.
- Parsed value exact SkillSpec and optional license/compatibility/metadata/allowed-tools. License/allowed-tools≤4096UTF8bytes; compatibility≤500chars/2000bytes; metadata≤64stringpairs, keys≤256chars/1024bytes, values≤4096bytes; totalmetadata≤65536UTF8bytes.
- YAML document≤16777216UTF8bytes, header≤65536bytes, firstline---/closing---, UTF8BOM/CRLF. Depth≤16/aliases≤32/events≤4096, duplicates/unsafe tags/cycles/multiple docs refused. Required name originalASCIIslug1..64/parentmatch, description1..1024chars/4096bytes; exact known topfields. Metadata.version ifpresent is SkillSpec version≤256bytes otherwise1.
- Explicitpaths1..1000 and≤max_skills; safe/unique endingSKILL.md. Filepercap1..16777216/default1MiB, rawaggregate64MiB enforcedearly; maxskills1..1000/default100. Original root/file/Scope/actual-handler close and parseridentity checked before+after; no refresh.
- Default YAML optionalextra; core imports workwithoutit. Pure parser borrowed/no lifecycle; custom SDK parser supported. ExistingJSONdefaults/Source1/protocols/22templatesbyteidentityunchanged; no recursive discovery/resources/automaticContext/plugin/Sandbox/qualityclaim.

## Review Focus

- YAML alias/cycle/duplicate/tag/depth work is bounded before materializing metadata (Task1).
- Changing optional frontmatter/parser while body same still invalidates fixed release/file snapshot (Task2).
- Root-level parent name/cwd/unsafe paths never weaken original FD/revision ownership (Task2).
- Borrowed custom parser lazy/malformed results/identity changes fail without executing unintended hooks; no permission from allowed-tools (Tasks1–3).
- Missing optional dependency/core-only import/config and partial assembly close are honest; installed/actual optional paths cannot skip (Tasks3/4).

---

### Task 1: Pure value/port and bounded native YAML parser

**Files:** create src/ralf_agent/skill_documents.py and tests/test_skill_documents.py; modify exports/pyproject optionalextra.
**Interfaces:** produces ParsedSkillDocument(skill,metadata=None).to_dict, SkillDocumentParser.identity/parse(text,*,parent_name), YamlSkillDocumentParser(*,version). Native parse produces exact immutable value with preservedbody/version; no I/O beyond optional import.

- [x] Prepare optionalPyYAML from primary package into owned temporary wheelhouse, installdevelopmentenv only. Record actual packageversion/exit; no silent parserfallback.
- [x] Write failing pure/parser tests: all declared types/limits, block/folded/quoted/Unicode/BOM/CRLF/optionalmetadata/versions, parent mismatch, duplicates/unsafe tags/multiple docs/cycle/alias/event/depth caps and zero copyhooks. Expected missingAPI before product.
- [x] Implement strict value/port and complete safe YAML parsing with pre-materialization bounds; exports and optionalextra. Core missingdependency typed failure/importlazy.
- [x] Run `.venv/bin/python -m pytest tests/test_skill_documents.py tests/test_skills.py tests/test_skill_review.py -q -W error`; Expected pass, formalcompletion/finalbatchcommit.

### Task 2: Original frozen file adapter

**Files:** create src/ralf_agent/filesystem_skill_documents.py and tests/test_filesystem_skill_documents.py; inspect original filesystem_skills.py/filesystem_workspace.py for shared guard/refactor only if preservesexactbehavior.
**Interfaces:** consumes pure parser/value and originalWorkspace; produces FileSkillDocumentCatalog exact Specconstructor, original SkillCatalogPort snapshots and fixed parser/file/metadata identity. Borrowsparser/ownsroot.

- [x] Write failing tests: explicitmulti/root-level paths, body/optionalmetadata/identity drift, unsafe paths/aliases/rootmove, unavailablefile, partial cleanup/missingdependency pre-root; earlyaggregate cap/readcount and realblockedhandlerclose. Custom parser sync/identity/lazy/malformed/samebodydifferentmetadata rules.
- [x] Implement original full-operation ownership/fixed versions and parser checks; pure configuration before allocations, readremainingcap before retaining, borrowedparser notclosed.
- [x] Run new plus tests/test_skill_documents.py tests/test_filesystem_skills.py tests/test_filesystem_workspace.py tests/test_workspace_review.py; Expected pass, originalJSONidentityunchanged. Formalcompletion/finalbatchcommit.

### Task 3: Default declaration and actual Source1/binding recovery

**Files:** modify skill_factories.py registration/validation (new dedicatedfactorymodule if clearer); create tests/test_skill_document_configuration.py tests/test_skill_document_execution.py tests/test_skill_document_temporal_service.py.
**Interfaces:** new async tools/skills-markdown exactconfig fromSpec, originalBuildContext ownsSource+catalog and reusesregisteredskills role. Customparser viaSDK orcustomtoolsfactory, no new kernel/protocol.

- [x] Write trueRED configuration/ownership tests for JSON/TOML/explicitScope/invalidoptionpreflight and partialcleanup; default parser/file and nativeSource1 snapshots.
- [x] Write/run sixLocal originalapproval/restart/savedresults with separate parsedcatalogs and allowed-tools no privilege; purecustomparserreplacement independent ofYAMLdefault.
- [x] RequiredactualTemporal ownedservice six originalcompositions/Workerrestart/repeatedapprovals/History/savedreads/fixedmembers, zeroSKIP. No new authority; Source1/skillsprotocol1 unchanged. Onlyafteractualpass bump80.
- [x] Run allnew offline plus existingSkillCatalog/binding contracts; Expected pass; formalcompletion/finalbatchcommit.

### Task 4: Frozen package and capability delivery

**Files:** parser/file/declaredguide, architecture/reviews/2026-10-12-skill-documents.md, capability/status/progress/remaining/harness/CHANGELOG/CI/version.
**Interfaces:** honest bounded standard-document profile, customparser guide and verified install/recovery defaults.

- [ ] Freshcore import/customparser tests withoutYAML, optionalYAML+SDK contractandactualservicezeroSKIP; exact269+new module/wheel/sdist/installhashes; runnableinstalledexamples, actualold79 defaultLocal/CLI/Temporal/native two-way compatibility/22templatesunchanged.
- [ ] Solefreshstrongestreadonlyreview; allfindings/declines regradedbefore ONE unifiedImportantTDDpass; Minorsdeferred/nore-review.
- [ ] Greenfullsuite, rebuiltclosurepackage/docs, allownedservicesactualstopwait, localmain/formalTask4/closurecommit; exhaustiveRulings/minorscollected andownSDDarchive. WholegoalR01–R26active, no implicitfullstandardecosystem/H4 completion.

Expanded YAML alias graphs also fit4096 visited values and65536 aggregate UTF8 scalar bytes before ordinary JSON copying. Source event/alias/depth checks remain separate.
