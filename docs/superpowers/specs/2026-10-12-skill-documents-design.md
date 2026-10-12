# Standard Skill Documents Design

Baseline3de04c2/dev79. Increment of approved R13/H4 roadmap; user wants flexible ports with usable defaults, continuous development/local commits only. Preserve original Source1, bound Skills role and Local/Temporal authority. No automatic permission grant or script execution.

## Evidence and chosen approach

Primary format reviewed2026-10-12: [Agent Skills specification](https://agentskills.io/specification). Required YAML frontmatter name/description then Markdown; directory/name match, description≤1024chars; optional license/compatibility/metadata/experimental allowed-tools. User-referenced local AgentScope skill/_local_loader.py provides asynchronous frontmatter discovery and mtime cache. Reuse the format concept, not mtime-only refresh or hidden grants. RALF retains immutable content, original root/revisions and managed handler ownership.

Use a replaceable pure synchronous parser and explicit file catalog. Default YAML parser uses optional maintained PyYAML>=6,<7, never a handwritten partial YAML implementation. Existing JSON/Markdown defaults/dependencies and22 starter bytes remain unchanged. Initial file paths explicit, no recursive directory discovery; associated resources and automatic Context remain later work.

## Pure values and parser

`ParsedSkillDocument(skill,metadata=None)` is frozen, requires ordinary SkillSpec and optional exact metadata fields license/compatibility/metadata/allowed-tools. Metadata detached via ordinary finite JSON; license and allowed-tools nonblank UTF8 max4096bytes, compatibility1..500chars/max2000bytes; metadata map at most64 ordinary string keys/values, key1..256chars/max1024bytes, value≤4096bytes, total metadata≤65536UTF8bytes. No implicit tool policies. `to_dict()` exact {skill:SkillSpec.to_dict(),metadata:dict}. Reject subclasses/lazy/custom hooks before any copy.

`SkillDocumentParser` has ordinary finiteJSON identity and synchronous `parse(text,*,parent_name)->ParsedSkillDocument`. Pure parsing only, no model/tool/file I/O. SDK replacement uses this constructor contract, no additional executor/authority. Native result adoption verifies exact value type, parent name and all existing SkillSpec limits. Parser identities/methods fixed at File construction; parser borrowed, has no resource lifecycle.

`YamlSkillDocumentParser(*,version)` validates nonblank ordinary behavior version≤256bytes, requires optional dependency or clear ValidationError. Identity pins kind/version/behavior/PyYAMLversion/format limits. UTF8 text at most16777216bytes, optional leading UTF8BOM, frontmatter starts first line with--- and ends---, CRLF supported, header≤65536bytes. Full safe YAML parsing with no arbitrary object construction; reject multiple docs, duplicate/nonstring keys, unsafe tags, cycles/excess depth>16/alias references>32/parse events>4096. Bound parsing before constructing final metadata. Required name follows original RALF ASCII slug1..64 (document this narrower name profile), matches parent_name; description nonblank1..1024chars and≤4096bytes. Top-level fields exactly name/description/license/compatibility/metadata/allowed-tools. Missing/invalid/empty bodies refuse as existing SkillSpec; instruction body preserves its original Markdown after delimiter. SkillSpec.version from metadata.version if present, otherwise1, always valid≤256bytes. Optional fields remain informational and affect pinned original file identity; allowed-tools NEVER grants tools, installs dependencies or runs code.

## File adapter

`FileSkillDocumentCatalog(root,*,version,paths=("SKILL.md",),parser=None,scopes=DEFAULT_SCOPES,max_skills=100,max_bytes=1048576)` owns original FileSystemWorkspace and borrows explicit parser or creates pure YAML default. Paths ordinary list/tuple1..1000 and≤max_skills, unique original safe relative paths ending SKILL.md. Parent name from the last directory of path, or fixed original root basename for root SKILL.md. Metadata validation/limits/parser-sync capability before root allocation. No scanning, YAML import in pure config validator or partial parser fallback.

Read whole files via original safeWorkspace, each≤max_bytes1..16777216, default1MiB; aggregate raw files≤64MiB enforced per-read remaining allowance before retention. Parse original snapshots, build existing immutable Memory catalog; catalog_digest remains original ordered list metadata including bodyhash/version. Identity additionally pins original root/path/file revisions, parser identity/implementation and informational metadata. Every list/get checks original root/file versions and parser identity before+after snapshot; no silent refresh. Original Workspace operation covers full file/cached snapshot interval and failed close retains activeFD. Constructor failures close owned root; borrowed parser never closed. Rebuild catalog and release explicitly to update.

Avoid duplicating ownership rules: locate a shared internal frozen-file guard if worthwhile, but preserve existing FileSystemSkillCatalog API, identity and behavior byte-for-byte. No unrelated refactor.

## Default configuration and replacement

Add async `tools/skills-markdown` factory with exact root/version/paths/scopes/max_skills/max_entries/max_bytes/prefix/requires_approval/cost; reuse original pure options/preflight and owned Source-before-catalog cleanup. Parser default YAML; custom parser via SDK FileSkillDocumentCatalog(parser=...) or custom tool factory, documented. No new Agent role or protocol; registered Skills ref/disabled works unchanged. Add optional project extra skills=[PyYAML>=6,<7]. Native class imports PyYAML lazily so core-only import remains valid. No automatic package install by framework.

## Acceptance

Parser/value TDD: literal/block/folded/quoted multiline Unicode/CRLF/BOM/defaultversion and optional metadata; strict limits/name parent/multiple docs/duplicate keys/unsafe tags/nested aliases/cycles; malformed/lazy custom parser results and identity. File TDD: optional dependency failure/invalidoptions before root, early raw aggregate cap, unsafe aliases/symlink/hardlink/drift/rootmoves and originalFD ownership/cleanup; unchanged original JSON defaults.

Declared JSON/TOML default/explicitScope and borrowed custom parser; partialcleanup. Original Source1/Skills role six Local and actual Temporal compositions restore approvals/Worker restarts/saved results/History with fixed parsed catalogs. No text-based permission grant. Fresh core-only tests without PyYAML skip only optional parser/file path cases (not count as evidence); optional installed YAML+SDK actual cases requiredzeroSKIP. Exact source/wheel/sdist/core/optional install payloads; installed runnable guide/custom parser; actual old79 default Local/CLI/Temporal/native two-way compatibility/22 originalstarterbytes; source full, sole fresh readonlyreview, all findings/declines disposed before unified ImportantTDD pass, ownedservicesstopactualwait/local commits/ownSDD archive. Keep dev79 until required actual six pass, then dev80. FullR01–R26 remains ACTIVE.

## Remaining

Recursive discovery, asynchronous/remote loaders, associated resource views/selectors, automatic index/context activation, plugin installation, Sandbox/Runner and real quality are separate. This is bounded standard YAML/document adaptation, not complete AgentSkills ecosystem support or wholeH4.
