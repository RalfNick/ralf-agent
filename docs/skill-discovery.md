# Automatic skill directory discovery

`SkillDirectoryRetriever` exposes permitted skill names and descriptions through
the original Retriever and KnowledgeContext interfaces. The default
`LexicalSkillSelector` selects metadata by deterministic name/description matches,
including Chinese character bigrams. This is a basic matching implementation;
custom selectors can replace it through a pure synchronous `SkillSelector` port.

```python
import asyncio
from ralf_agent import (
    InMemorySkillCatalog,
    SkillSpec,
    SkillDirectoryRetriever,
    KnowledgeContext,
    Scope,
)


async def main():
    catalog = InMemorySkillCatalog(
        [SkillSpec("billing", "Invoice payment help", "Use approved tools")], version="1"
    )
    context = KnowledgeContext(
        SkillDirectoryRetriever(catalog, version="1", names=["billing"]), namespace="skills"
    )
    try:
        references = await context.references(Scope(), "invoice")
        await context.validate(Scope(), references)
        print(references)
    finally:
        catalog.close()


asyncio.run(main())
```

The returned references use the existing Knowledge provenance format. Their
metadata has `reference_kind="skill-directory"` and `permissions="none"`; it
contains no instruction body. The original Context builder inserts them as
passive reference evidence before model decisions. The original model tool
Action still reads a body through `skill_get`, with its own approvals and grants.
Directory discovery does not register tools or grant business permissions.

Explicit host directory authorization and model tool authorization are separate:
Scope and the optional name allowlist limit discovered metadata; AgentSpec,
ToolSet, Skills binding and host policy govern callable tools. Configure each
explicitly. Native `KnowledgeBindingResource` supports per-Agent
inherit/ref/disabled and allowed namespace selection. All namespaces of a single
directory resource use the same declared catalog and name allowlist.

For Profile assembly, choose `knowledge.adapter="skills-directory-file"` with
`config={"root": "skills", "version": "1"}` for the original `skills.json` plus
Markdown catalog. `"skills-directory-markdown"` instead uses declared standard
`SKILL.md` paths and the optional `skills` dependency. Both use the original
catalog validators and owned root lifecycle. Additional options are `names`,
`namespace` (default `skills`), `limit` (default5, range1–100), `max_chars`
(default8000, range2–65536), `max_entries` (default1000, range1–1000), and
`selector={"adapter": "lexical", "config": {"version": "1"}}`. Original catalog
options `scopes`, `max_skills`, `max_bytes`, and `manifest` or `paths` remain
available. Tool-only policy options are rejected here.

Catalog, selector, methods and configuration are fixed at publication. Complete
catalog metadata must fit the configured allowance; excess entries fail rather
than being silently truncated. References are revalidated before model
disclosure. Source changes require a new version/Profile; they invalidate old
references. Empty queries select sorted names; nonempty unmatched queries return
no metadata. No model or asset download runs in the selector.

The Retriever borrows its catalog. Profile factories own catalogs through the
original resource ledger. Actual synchronous catalog reads use the original
thread tracker; Context read ownership and native file guards retain running
reads through observer cancellation and retriable close. In Temporal, explicitly
enable `execution.context_reads=True` for actual read/end evidence gates. Original
History handles response adoption and recovery; no Skills scheduler is added.

This stage provides passive metadata discovery. Automatic body loading, plugin
activation, semantic skill selection, Sandbox and Runner remain separate
capabilities. See [skill tools](skills.md), [Skills binding](skills-bindings.md)
and [remaining work](remaining-work.md).
