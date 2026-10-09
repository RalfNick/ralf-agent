# dev36 / H2b3 — Authorized composite root namespaces

One LocalEngine/SQLite authority manages root admission, original binding revisions,
child execution/evidence and final result. Separate borrowed conversation resources
allow the shared Runtime to open same logical IDs in independent authorized namespaces.

The configured descriptor fixes resource/default/allowlist/selection in the Session
binding and independently on the admitted Run, including namespace=None. Existing
release checks validate both before effects, including descendants; atomic
final-save validation repeats the check. Parent IDs use canonical physical
keys so member histories cannot collide. Ordinary member defaults, explicit member
bindings and default None behavior retain their semantics.

Configured descriptors atomically enable semantic schema4; default raw/native/
composite1/2/3 remain compatible. Marker3/prepare_conversations is optional; marker2
keeps default composite support. Borrowed resources require actual colocated
SQLiteMemory; failed construction never closes a borrowed backend. Profile-specific
configuration, remote/shared Temporal Sessions, full H2/H3 and enterprise governance
remain pending. This is a storage namespace contract, not enterprise authentication.

## Fresh review and correction

One independent, read-only reviewer inspected the captured dev35→dev36 SDK delta
and public contract/tests. HEAD5626c17 remains unchanged; the starting dirty dev35
snapshot and its actual wheel were captured before dev36 edits. The reviewer ran
34 focused tests and found one Important issue, no Critical or Minor issues.

A configured None conversation could lose its original binding descriptor and
silently become a legacy conversation after the host resource was removed. The
reproduction completed two model decisions and one tool effect. It was graded
Important by the actual user effect and fixed in one RED→GREEN pass: three evidence
corruption cases initially failed; independent Run evidence now refuses them before
dispatch. A genuine legacy Turn still succeeds in a database later upgraded to4.
The Run evidence and Turn admission are written in the same original transaction;
there is no additional execution authority or post-admission identity rewrite.
Atomic final save repeats the same validation. No second review was dispatched.

## Final evidence

- Task gates:102 and154 passed; final focused composite/namespace gate:79 passed.
- Full source regression, warnings as errors: **2431 passed,56 skipped**. Skips are
  explicit service/optional configuration gates; those services were not rerun.
- Actual installed wheel outside the checkout: **297 contract tests passed**.
- **32 actual-wheel recovery scenarios:**10 schema1/2/3 cases in each direction
  between captured dev35 and dev36; six schema4 red-root and six explicit-None
  cases recover original Turns, approval/control receipts, manifests and final
  results without duplicate effects. Old readonly/writable SDKs refuse all12
  schema4 cases before dispatch. Effects are audited by stable Action effect keys.
- Captured dev35 wheel matches148 starting SDK modules; dev36 wheel/sdist/installed
  package match all149 current SDK modules byte-for-byte. Dependencies, extras and
  console scripts are unchanged;294 public exports resolve with optional clients
  blocked;20 installed starter trees are identical to dev35.
- Ruff, format, Git whitespace, changed-document local links and package hygiene
  pass. No private workspace, environment file, database or credential-shaped
  content is packaged. Source and installed tests use offline fixture Providers;
  no real-model task-quality or enterprise/AgentScope parity claim follows.

## Rulings and costs

1. Continue the approved architecture in the current feature checkout and preserve
   dirty dev35/dev36, the branch and private evidence. Cost: work is uncommitted and
   the local evidence must be retained; there is no automatic integration.
2. Keep the host root conversation resource separate from member defaults and use
   canonical parent addresses. Cost: explicit namespaced parent/member IDs are
   opaque storage keys; default None addresses retain their original form.
3. Review the captured starting source/wheel delta rather than an empty unchanged
   HEAD range. Cost: this incremental review evidence remains local until committed.
4. Accept the reviewer's scope exclusion for remote/Temporal routing, enterprise
   authorization and dedicated Profile declarations. Users get the published
   colocated Local SDK subset; cost: these other combinations remain unavailable.
5. Accept that the reviewer verified focused suites only; the implementer owns and
   completed the post-fix full/installed/wheel gates above. Cost: offline regression
   does not establish unconfigured service behavior or real-model quality.
6. Exclude unrelated dev35 changes from this fresh incremental review while
   preserving and regressing the starting workspace. Cost: this review judges dev36,
   not every historical change against HEAD.

Deferred minors: none reported. Next capability gates remain remote Session
semantics, Temporal capability bindings and H3 managed default chains. No paid
call, automatic commit/push or publication.
