# Per-Agent Read-only Workspace Binding Design

Baseline 93c32b8/dev75. Active design under the user’s continuous implementation and local-commit-only authorization; no push. Implementation remains inline with one final fresh read-only review.

Intent: turn the existing read-only Workspace into a usable per-Agent capability in Local and Temporal without adding another execution authority. Users can keep a shared host registry, select one fixed Workspace source per Agent, and independently replace its WorkspacePort. SDK and declarative construction must work; original approval, Action identity, thread ownership and saved evidence remain intact.

## Public contract

`WorkspaceBindingResource(registry: ToolRegistry, *, names: tuple[str, ...])` borrows the original registry. `names` accepts tuple/list, 1..256 unique plain nonempty strings of at most128 characters/512 UTF8 bytes without ASCII controls or DEL. All named manifests must be native WorkspaceToolSource version string "1" read-only registrations and must have identical full source identity (root, version, caps). Tool names retain their host prefixes. No filesystem I/O, discovery, allocation or close is performed by the binding resource.

Resource `identity` is detached finite JSON: kind workspace-binding-resource, version string "1", full source identity and pinned named Tool manifests. Recompute/compare live original registry manifests before returning; mutation/removal/version drift fails DefinitionMismatch. Record actual fixed registered tools, not decorative root metadata. The original ToolSource still checks live source/port identity and performs root/path/Scope checks at dispatch.

`BindingCatalog.register('workspace', id, version, resource)` accepts only this native borrowed resource. Scope is the existing trusted catalog Scope; no selectors/subroots are supported. Wrapper borrows the replaceable port through existing Source/Registry; it grants no new capabilities and owns no clients.

`inherit`: preserve existing exact effective grants/records/default manifest bytes; there is no implicit host Workspace selection.
`ref`: intersect already-effective AgentSpec/tool_set grants with the resource named registrations. Preserve all non-Workspace grants. Exclude other Workspace-aware tool grants. Any matching-name manifest disagreement refuses; require at least one matching Workspace tool already granted, so an explicit reference cannot be unused metadata. Never add tools, rename names, expand tool_set or reroute same tool to another root.
`disabled`: remove every native Workspace-aware tool grant; preserve non-Workspace business tools. Explicit choice is recorded even when no Workspace tools were initially granted.

Workspace-aware means original source metadata kind workspace-tool-source/version1. This is a trusted native transport boundary, not a sandbox for arbitrary Python or plugins that falsify manifests. Other business tools may implement file access; Workspace selection does not isolate them.

## Shared pure selection and execution authorities

A pure helper `select_workspace_tools(names, manifests, resource_identity=None)` is shared by Local resolver and Temporal History effective_step. Disabled selects no Workspace entries; reference validates full selected identity and each matching named manifest. Return stable original tool-name tuple; never perform I/O or execute handlers.

Local resolver adds workspace records only for explicit mode; no extra StepComponents client field is necessary because the actual capability is the filtered original tool grants. Bound manifest kernel local-bindings-11 only when any Agent uses explicit workspace. Existing inherited legacy records remain exact. Native/sequence/graph/team/dynamic/nested members use existing descriptor paths and child projection.

Temporal catalog emits workspace records with the pinned resource identity, and pure effective_step uses History manifest tools. Optin manifest marks workspace_binding_protocol1 only when the host catalog registers Workspace resources; even disabled-only selections require this explicit host optin. Validation rejects explicit workspace choices without this protocol, refuses selectors/Scope mismatch/unregistered resource and ungranted tools before accepting execution. selected_runtime requires no new workspace client or context field: original fixed registered handlers perform all reads. Original runtime validates catalog object/manifest and Source validates live root during dispatch. This is no additional state machine or remote data authority.

## Assembly

ComponentRegistry default sync factory kind workspace/registered-tools accepts exactly {names:[...]}. It wraps context.tools already assembled in both Local and Temporal, so no duplicate roots or hidden filesystem work. Runtime Profile binding_components uses the existing workspace role declaration and binding_kind mapping. Normal ToolSource async assembly still owns port then Source and closes Source/handlers before port. Workspace resource adds no close and does not close borrowed registry/source/port.

Multiple roots use existing SDK fixed prefixes/custom original tools factory; each resource lists one source's registered names. Declarative single-root workspace-read can be reused without reconstructing a port. No new base dependencies or starter changes.

## Acceptance

- MissingAPI/role tests RED first. Native registry/resource validation, mixed roots/caps, lazy/foreign manifests and identity mutation refused; records/results detached; no FS I/O in resource methods.
- Actual Local native/sequence/graph/team/dynamic/nested definitions expose only selected source tools; malicious provider proposal for excluded root is rejected by original admission without read. Other business grants remain, tool_set cannot expand, disabled removes only Workspace grants.
- Actual approval restart with original root resource preserves receipt; resource/name/version change fails before execution. Saved result survives later content change. True Source cancellation ownership unchanged.
- JSON/TOML normal Profile sync/async construction wraps original registry and borrows lifetime; preflight invalid declaration creates no clients/DB; partial cleanup unchanged. SDK custom Memory/FS ports can replace beneath Source.
- Temporal pure History tests and required actual native/sequence/composite/nested member selection and approval/Worker restart/History replay; nonselected roots never read. Resource drift refuses current Worker, no old result resend. No required service skip.
- Fresh core and temporal SDK installed usage, dev75 default Local/CLI/Temporal bidirectional old-new compatibility and22 unchanged starter templates; older worker rejects explicit new workspace before I/O.
- One whole-batch fresh read-only review, Important RED→GREEN unified pass, frozen fullsource/build/wheel/sdist/sourcehash/doc/realservice gates, stop and wait owned original sessions, localcommit/formal completion only; no push/model-quality claim.

## Scope boundary

This delivers read-only per-Agent root/source tool selection, not file writes, per-path ACL/subroots, leasing, automatic Context loading, Skills, Sandbox or Runner. Root identity movement needs new release, original saved results are original authority evidence; no transaction/anti-malicious-writer guarantee. C1 controls deferred in dev75 remain a separate documented issue. Full R01–R26/H1/H4 remain open.
