# Per-Agent Skills Binding Design

Baseline cd1653e/dev78. Architectural increment of approved R01/R13/H4 roadmap. User requests continuous completion, individual defaults and replaceable components, only local commits. Not a new authority or prompt executor.

## Chosen design

Add SkillBindingResource(registry,*,names) selecting one original skill-tool-source registration family. Borrow registry, own no Sources/catalogs, perform no I/O. Resource identity {kind:"skill-binding-resource",version:"1",source,tools}; source exact native fields kind/version/behavior_version/catalog/max_entries/max_bytes, catalog ordinary immutable identity with catalog_digest. Every named manifest native read-only skill_list/get, no effect-key or reconciler. Names ordinary finite list/tuple1..256, each1..128 chars/512UTF8 bytes/no control, distinct. Registrations same source canonical identity; unrelated tools cannot masquerade as Skills. Full resource checks against original manifest preserve bool/int JSON distinctions.

AgentBindingDescriptor.skills already exists. Enable ref/inherit/disabled for Local and Temporal. Inherit retains old behavior and no added default field. Explicit ref chooses catalog resource by component_id/version, no selector initially. Effective tools = original Agent tools intersect tool_set intersect skills resource for Skills tools; ordinary business and Workspace tools remain original grants. Disabled removes native skill-source tools only. Explicit resource with no granted matching tool rejects before model/action. Binding never adds a tool, instructions, runtime Client or business permissions. Multi-root and native source mismatch refuse; original read Action validates full scoped immutable metadata, content and thread lifetime.

Config kind skills/registered-tools reuses already-built ToolRegistry; validate names and fields before I/O, require original registry context, cleanup original owned sources/catalogs on partial failure. Local RuntimeBuilder and TemporalRuntimeBuilder support role. Scope remains original host and catalog authorization. Catalog own/client lease and Source borrowing unchanged.

## Compatibility

New opt-in Local binding kernel local-bindings-13. Local original descriptor resolution/manifest fixed identity must demonstrably reject on old78; kernel number alone is not proof. Default kernels unchanged. New Temporal skills_binding_protocol=1 for explicit role producer, original History state validates typed protocol/resource before execution. Old78 Workers must refuse new explicit binding before ANY model/tool Activity, not silently ignore descriptor. Producer role registration plus explicit disabled admission both require protocol checking; inherited roles add no new fields. Verify the actual old Worker gate rather than assume unknown fields are rejected. Direct ordinary SkillToolSource read tools/default old workflows remain byte-compatible. Parent root/member release and nested dynamic paths use original fixed binding descriptors; no independent scheduling.

## Acceptance

TDD pure resource names/source/effect/digest/alias/canonical types/borrowed lifecycle; original ToolSet/Workspace intersection and disabled behavior; no permission from instruction text; pure JSON/TOML declarations, denied Scope and partial cleanup. All six Local compositions recover original approvals and saved reads with independent catalogs. Actual Temporal service six compositions, Worker restart, repeated commands/approvals, History replay, fixed per-member catalogs; old78 default Local/CLI/Temporal/native two-way compatibility,22 starter bytes, real old78 Worker opt-in pre-Activity refusal. Core/SDK fresh wheel, exact source/wheel/sdist hashes, runnable guide, full tests, sole read-only review, original services stopped/waited, local commit.

## Not delivered by this increment

Per-skill selector/resource views, automatic index/context phase, standard YAML loader, async catalogs, plugin install, Sandbox/Runner, real-model quality and complete R01–R26 remain separate. Completing binding does not complete H4.
