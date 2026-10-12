# dev77 子集验收：受管理 Workspace 写入

基线0501054/dev76；不新增执行权威。WritePort／Memory／POSIX 默认、原生 Source2、
JSON／TOML、每 Agent 交集与 Local kernel12／Temporal protocol2 为本批子集。
初始候选记录如下；最终冻结、安装、旧76兼容和审查修复结果见末尾。没有推送或真实模型质量声明。

Task1：公共 API44 true RED（1.09s）→142相关 GREEN（1.18s）；正式142 passed（1.07s）。
Task2：文件公共 API18 true RED（1.08s）→105相关通过（3.39s）；
rename 后正文变化／父目录移动两项 true RED（0.54s）→107 passed（2.92s）。
真实 os._exit 窗口2 true RED／5个既有通过（8.01s）→114 passed（7.70s）；
临时目录项持久化1 true RED／关闭失败原检查已通过（0.54s）→116 passed（7.99s），
正式116 passed（7.82s）。覆盖写前／rename后／回执后、篡改正文／相同文本不同inode／临时正文，
真实跨进程租约与关闭请求后的实际线程。

Task3：Source API8 true RED（修正不存在的Registry.names fixture后0.56s）→119 passed（7.84s）。
配置／绑定初始包含错误abuild base_dir参数和Store.get_run fixture；纠正公开API并使用原纯Journal契约fixture后，
10 true RED／5个非法配置已拒绝（0.96s）→85 passed（5.96s）。
追加 malformed tool metadata三项 true RED、1个错误Echo工厂fixture（3.35s），纯边界改成类型化拒绝，
工厂显式登记后32 passed（3.16s）。Local真实文件丢失响应回归已由现有实现通过（0.49s），
不声称它额外RED；原Run重启只查询回执，一次文件写入、重复审批与历史结果复用均核验。
最终离线相关130 passed（6.02s），组间有重叠。

真实源码六类 Temporal＋PostgreSQL：native／sequence／graph／team／dynamic／nested，
6 passed（30.88s），无跳过。固定根、审批重启、重复控制、原PG回执采纳、每根仅一个已确认文件效果、
后来修改文件而不重执行、原History重放通过。自有Temporal5751／17279与PG43508／Unix socket56377
仍运行，仅供本批后续安装／冻结验证；必须等待原会话退出后才最终提交。
版本在六项实际服务通过后才升0.1.0.dev77。

判断与代价，按顺序保留：

- 持续授权覆盖重复架构设计／计划／收口菜单，inline且只本地提交；判断错误须发布前修订，没有远端授权。
- 文件回执与单根所有权是下游证据，原Engine／History仍唯一调度；代价：任意外部写者／多写者事务需单独协议，不能声称Sandbox。
- Memory采用独立实例UUID和单调版本，避免共享可变根身份及ABA；代价：重新创建Memory不能恢复旧可变Run，应选择File默认。
- 独占下游SQLite使用FULL同步rollback journal，避免地址移动后的WAL checkpoint；代价：吞吐需另行实测优化，不提供并发数据库写者。
- 原生Source2只允许自身核验器或无核验器的幂等重试，保留准确请求证据；代价：其他核验语义需独立版本ToolSource，Port仍可替换。

前一批readonly C1路径／live drift错误分类Minor未混入本批修改。
完整R01–R26、Workspace append/delete/mkdir、selector／ACL、GC、远端租约、Skills、Sandbox、Runner与企业治理仍开放。

正式Task3：203 passed（12.10s），所有新增离线及原相关契约，无跳过；范围0501054→0501054（最终本地批次提交尚待验收）。三个实现Task已完成，交付Task4进行中。

## Independent review and executor disposition (before product changes)
One fresh read-only Astra review covered all35 paths. Critical0, Important3, Minor1. All findings regraded by user effect before the unified fix pass.
1. Important retained: filesystem alias bypass can destroy predecessor evidence. Fix uses original parent physical identity and filesystem-resolved target identity; when a pending target is absent, conservatively hold that physical parent for new writes. No universal casefold assumption. Cost: unrelated writes in that same directory may wait while an absent prepared target remains unknown.
2. Important retained: DELETE+FULL lacks a durable rollback commit barrier. Configure and validate DELETE+EXTRA on every connection. Official [SQLite synchronous documentation](https://www.sqlite.org/pragma.html#pragma_synchronous) distinguishes this from process-exit tests. Cost: additional directory synchronization; no hardware power-loss test claim.
3. Important retained: native edits replace0644/0755/0640 with0600. Preserve ordinary rwx bits before temporary-file fsync, including recovery; new files stay0600. Special permission bits/owner/ACL remain separate. Cost: privileged special bits are intentionally not carried to a newly owned inode.
Final: minor (deferred): actual Temporal native blocked-writer cancellation/close/lease window has not been directly exercised; actual six-composition tests demonstrate approval/restart/results only. Offline writer cancellation and existing actual generic handler-close tests are evidence, not a substitute. Complete planned cancellation acceptance stays open; do not fix this Minor in this pass.
### Considered but declined: complete executor rulings
1. Final: Ruling: SDK approval override — Keep explicit host ToolPolicy; default factory always requires approval — cost if wrong: A custom host can intentionally relax approval and must own that decision.
2. Final: Ruling: Missing native reconciler — Keep explicit None with idempotent retry; reject foreign native callbacks — cost if wrong: Custom reconciliation semantics need a separately versioned source.
3. Final: Ruling: Caller effect keys — Reserved argument rejection and InvocationContext injection remain authoritative — cost if wrong: Any new source must preserve this reserved-key contract.
4. Final: Ruling: Identity ordinary-type normalization — Accept canonical detached receipt normalization without changed Scope/request/CAS — cost if wrong: Non-authoritative identical subclasses are normalized, not preserved.
5. Final: Ruling: Historical receipts after later edits — Confirm historical effects without rewriting current files — cost if wrong: Receipt does not establish current content.
6. Final: Ruling: Equal foreign content — Keep original device/inode/content/ancestor proof — cost if wrong: Lost original inode stays unknown even when bytes match.
7. Final: Ruling: Query replay of a prepared intent — Query never performs replacement; only original request replay may do so — cost if wrong: An unpublished write needs explicit original execution, not query.
8. Final: Ruling: Different key on the same canonical target — Existing predecessor query confirms only already applied proof — cost if wrong: Alias bypass is separately fixed as Important finding1.
9. Final: Ruling: Global asyncio cancellation — Retain original real-handler tracker and port active-operation guard — cost if wrong: Real stopped-handler evidence is mandatory for new adapters.
10. Final: Ruling: Queued calls after close — Admission checks closing after the write mutex — cost if wrong: Queued calls fail rather than silently reopen resources.
11. Final: Ruling: Partial close — Mark closing before release and retain lease on connection-close failure — cost if wrong: A failed close may require retry and retains ownership.
12. Final: Ruling: Metadata symlink/hardlink/moved address — Keep physical pinned identities and pre-SQL lease checks — cost if wrong: Trusted-host boundary does not provide hostile-process isolation.
13. Final: Ruling: Arbitrary external writers — Remain outside transactional guarantee — cost if wrong: The host must avoid uncoordinated mutations during native writes.
14. Final: Ruling: Overlapping parent/child roots — Exact-root lease does not exclude independently configured overlapping roots — cost if wrong: Host must not configure multiple writers to overlapping file trees.
15. Final: Ruling: Rename source-directory fsync — Do not raise a duplicate finding; commit durability is covered by Important finding2 — cost if wrong: Correctness still depends on required filesystem barriers and native SQLite VFS.
16. Final: Ruling: Capacity before temporary file creation — Temporary I/O may precede capacity rejection, but target and journal stay unchanged — cost if wrong: There can be avoidable bounded temporary I/O.
17. Final: Ruling: Pre-intent orphan temporary file — No effect receipt or blind replay; retention remains separate — cost if wrong: Crash orphans accumulate until future bounded cleanup.
18. Final: Ruling: Source2 grant expansion — Retain registered-manifest equality and grant intersection — cost if wrong: New environment roles require independent admission tests.
19. Final: Ruling: Local/Temporal version downgrade — Generated release uses kernel12/protocol2; actual old Worker rejects — cost if wrong: Host deployment must route old/new incompatible releases correctly.
20. Final: Ruling: Manually removing protocol2 — No demonstrated supported execution bypass; producer and runtime equality remain authoritative — cost if wrong: Arbitrary constructed manifests are not a supported migration mechanism.
21. Final: Ruling: Other binding protocols — Session topology is published after Source2 extension — cost if wrong: Future publisher ordering changes require regression coverage.
22. Final: Ruling: Long/whitespace prefix — Inherited validation behavior, no authority or target mutation defect — cost if wrong: Some declarations fail later name validation rather than early validation.
23. Final: Ruling: Memory identity/ABA — Keep instance UUID, monotonic revisions and detached locked data — cost if wrong: Memory recreation cannot resume the previous mutable dataset.
24. Final: Ruling: Third authority — Downstream journal records evidence only; original Engine/History owns state — cost if wrong: No arbitrary distributed execution backend guarantee is implied.
25. Final: Ruling: Candidate documentation — Keep explicit pending final gates and wider capability boundaries — cost if wrong: Evidence supplied to reviewer is not independently rerun by the reviewer.
Final: Ruling: this batch may deliver the verified write subset with the Minor actual cancellation window explicitly deferred — no broader acceptance claim is justified — cost if wrong: that actual native cancellation gate still has to run before complete planned acceptance.

Ruling: use actual parent device/inode and native target lookup for pending address equivalence; if the pending name is absent, hold all new writes in that physical parent — avoids filesystem collation assumptions and protects create-only aliases — cost if wrong: unrelated creates in that directory wait for original recovery.
Ruling: configure and verify SQLite DELETE+EXTRA on every fresh/reopened connection — rollback commit must synchronize journal deletion before publishing a file or returning a receipt — cost if wrong: extra directory synchronization overhead; process tests still do not prove hardware power-loss behavior.
Ruling: preserve only existing ordinary rwx bits on replacement, before temporary fsync; newly created files remain0600 — keeps scripts/configuration usable without copying privileged bits to a newly owned inode — cost if wrong: setuid/setgid/sticky, ownership and ACL preservation require an explicit future permission contract.
Unified review RED: session13190 actualexit1/read11 failures (9 true regressions, 2 fixture mismatches corrected below) in1.48s before product changes: three native aliases (leaf/parent/Unicode), two absent-target parent holds, two fresh/reopened EXTRA checks, three ordinary permission modes and one actual crash/recovery executable mode. Preliminary full86463 intentionally interrupted with actualexit2 before product changes, not a passing full suite.

Correction to RED count: first run had9 true regressions plus2 fixture exception mismatches (OSError is wrapped as WorkspaceError). The two absent-parent cases receive a separate RED check against the exact prior installed candidate before claiming coverage.

Unified fixes: corrected absent-parent RED27481 actualexit1/read2FAIL9deselected2.55s against exact pre-fix installed candidate; current GREEN67956 actualexit0/read11PASS3.16s. Together initial9trueRED plus corrected2trueRED cover all Important findings. Native filesystem parent/inode lookup (no universal casefold), conservative absent-parent hold, every-connection DELETE+EXTRA, ordinary rwx preservation applied in ONE pass; no Minor implementation or re-review. Full fixed freeze follows related suite.

Final frozen source hash264 modules recorded before full71253. Build92819 actualexit0/readdev77wheel+sdist; fresh venv58915/28701 and offlineinstall45901/98159 allactualexit0. Final core72464 actualexit0/read100PASS4.96s; SDK15790 actualexit0/read214PASS10.00s; source real7602 actualexit0/read6PASS34.63s; installed real42797 actualexit0/read6PASS30.17s, zero configured skips. Actual Local59274/CLI93463/defaultTemporal57189/native53921 actualexit0/read76↔77 saved approvals/effects/History/Session and22 unchanged starters. Module264 allsource/wheel/sdist/core/SDK identities exact, docs720/links579, threeinstalledguide examples, bothpipchecks and Ruff974 actualexit0. Final oldWorker31468/full71253 stillrunning; original owned5751/43508 retained until their required stop+actualwait. No product edits after freeze and no commit yet.

Final oldWorker31468 actualexit0/read: installed76 rejects frozen77 Source2 before any Activity/model/tool; original child stopped and waited. Source264 hash remains unchanged. Full71253 stillrunning; no finalfull count inferred and no commit yet.

## Final frozen acceptance

源码全量实际退出0：4615 passed／351 configured skipped（700.98s）；跳过不计通过。统一修复相关214 passed（13.22s），安装core100（4.96s）／SDK214（10.00s）；源码真实6（34.63s）／安装真实6（30.17s）无跳过。264模块与wheel／sdist／两个实际安装一致；720文档载荷、579链接和三个安装示例通过，文档收口后重新构建验证。实际旧76↔77 Local／CLI／默认Temporal／native Session及22模板通过；旧76 Worker在Activity前拒绝新协议。Temporal5751和PG43508均停止并等待原会话实际退出0。三个Important全部TDD修复且冻结全量通过；没有第二审查，实际原生取消窗口Minor延期。仅本地提交，完整目标active。

Final: fixed native alias pending-target ownership — test_published_pending_write_is_confirmed_before_native_alias_replacement and absent-target regressions RED→GREEN; final suite4615 passed/351 configured skips.
Final: fixed rollback commit durability — test_every_native_journal_connection_uses_delete_extra fresh/reopened RED→GREEN; final suite4615/351.
Final: fixed ordinary file permissions — test_replacing_text_preserves_existing_ordinary_permissions and actual crash recovery executable test RED→GREEN; final suite4615/351.

本地实现提交4219ead83d353b079a148c3e25cbf57709c0ac92；正式Task4于提交后实际退出0：214 passed（13.09s），范围0501054→4219ead。四个Task已完成，目标R01–R26仍active；唯一延期Minor与全部判断／代价在上文，日志随本批SDD归档。没有push。
