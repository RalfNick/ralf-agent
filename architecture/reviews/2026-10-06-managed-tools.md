# Managed tools and MCP review — dev11

Date: 2026-10-06. Base `9406f7d`; independently reviewed implementation `60609d2`. Fresh reviewer: gpt-6-astra, read-only checkout, no delegation. Scope: [specification](../../docs/superpowers/specs/2026-10-06-managed-tools-design.md), [plan](../../docs/superpowers/plans/2026-10-06-managed-tools.md) and G2 tool path.

## Findings and disposition

No Critical findings. The reviewer initially assessed two Important and two Minor findings and concluded not ready to merge before repairs. The implementer keeps the two interoperability/validation findings Important and treats the exception normalization findings as public Python SDK error-boundary fixes: callers handling the declared errors would otherwise receive unrelated TypeError/AttributeError. All four enter one TDD repair pass, with no second review.

| Finding | Reproduction and fix |
| --- | --- |
| Session-local discovery cursors fail | A real peer issues a per-process UUID cursor. Old code starts a fresh peer for page two and fails. Default stdio now exhausts bounded discovery in one initialized session, preserving raw tool descriptors and returning a valid aggregate tools response. |
| Reserved key accepted before approval | With additionalProperties=true or omitted, Registry accepts a caller-forged key, then handler rejection creates a false unknown write. The caller Schema now explicitly excludes that field; Tool-node rejection precedes Action creation, approval and credits. Legitimate extra fields remain allowed. |
| Malformed negotiation leaks TypeError | An object/array protocolVersion triggers unhashable set membership. String validation now produces ToolSourceError; real peer cleanup still runs. |
| Boolean field Schema leaks AttributeError | JSON Schema boolean property definitions are valid but cannot satisfy the mapping's declared string requirement. A type guard now rejects with ValidationError without registry publication. |

Eight regression cases failed before the repair. The final focused source/MCP/Tool/starter suites pass **69 cases in 3.99s**, warnings as errors. Complete final verification is recorded in [implementation progress](../../docs/implementation-progress.md). No reviewer has independently verified the repaired diff; the implementer's RED→GREEN and full-suite verification provide the repair evidence.

## Evidence reviewed

The reviewer read all changed implementation files, tests, specification, plan, ledger rulings and documentation. It ran **61 new tests plus 102 existing lifecycle/executor/Workflow tests**, with warnings as errors and an empty inherited environment except PATH; all passed. Its independent offline probes identified the four findings above. Checkout stayed clean.

The supplied pre-repair evidence was a complete **864-test suite**, lint/format/build, and actual outside-checkout dev10→dev11 installation. Native and Graph v1 receipts/Manifest/history stayed fixed; all five old starter dictionaries had identical hashes; queued Chat dispatched once then zero; demo and MCP applications each wrote once; 114 public names and pip check passed. Actual dev10 refused an unfinished Tool v2 before dispatch. Refreshed post-repair artifact evidence is distinguished in implementation progress.

## Scope rulings retained

| Reviewer exclusion / decision | Ruling and consequence |
| --- | --- |
| Live MCP, HTTP/OAuth, persistent transport interoperability | Default delivery is offline-verified POSIX stdio. These other modes have no compatibility evidence or default implementation. |
| Real-model quality, performance and framework superiority | Not measured. Runtime regressions cannot establish task quality or AgentScope parity. |
| Arbitrary custom sources/transports/reconcilers and truthful versions | Trusted host contracts. The framework cannot prove hidden behavior or a falsely unchanged identity; authors must supply conformance and lifecycle handling. |
| Sandbox security and descendants escaping process groups | Process groups manage cooperative trusted peers; they do not isolate or control deliberately escaped work. Managed sandbox Runners remain separate. |
| Other systems and Python versions | Local evidence is macOS/Python 3.12. The existing 3.11–3.13 CI is not a locally executed matrix. |
| Supplied install/build/full suite evidence | Reviewed as implementer evidence, not independently rerun by the reviewer. |
| General root Schema rewrites, non-Tool v2, migrations, parallel and future capabilities | Reserved-key mapping intentionally supports flat roots; non-Tool plans stay canonical v1. Unsupported combinations need explicit adapters/future increments. |
| Aggregating stdio discovery | Keeps session cursors valid without adding a new transport API. Callers receive the full bounded tools response rather than one native page. |
| Repairing the two initially Minor error types | Stable SDK error handling matters at extension boundaries. Cost is two guards and four regression cases; failure semantics and feature scope stay unchanged. |

Existing native/Graph compatibility stays on local-4 and plan v1; Tool-bearing plans use v2. This increment narrows the tool coverage gap while leaving bounded parallelism, dynamic planning/ChildRun/teams, remote data adapters, sandbox/distributed execution and remaining M1 acceptance outstanding.
