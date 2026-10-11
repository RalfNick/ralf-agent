# dev70 Temporal Profile Host 验收

基线4186fe2/dev69；冻结0.1.0.dev70。完整 R01–R26/H1–H5/M1 仍 ACTIVE。
本记录子集的独立审查、一次统一修复、冻结回归／服务／安装／兼容／停止门槛均通过；不关闭完整目标。

## 交付范围

- 最多32个显式不可变 Profile，全 Catalog 工厂／路径／环境预检先于构造 I/O。
- Shared BuildContext owned ledger，部分构造的真实 Task／明确桥接线程保留清理责任。
- 一 Host、可信 Scope、借用 SDK Client；固定实际 namespace UUID/endpoint 与原 Release 队列。
- 默认切换仅选择已托管版本，新 Facade 固定选择，原 Run／Session 按原 History／Coordinator 绑定重连。
- 未声明的原 Registry 队列启动前拒绝；未知／跨 Scope 引用不会派发模型或工具。
- 所有版本实际模型／摘要／工具／Session 与 Context Owner 排空后再停所有 Worker，最后一次释放共享资源。
- Temporal 专用 PostgreSQL EffectJournal 声明，复用既有耐久效果证据，不新增业务执行权威。
- 无 SDK／服务时安装模块只写 Catalog；真实网络运行需显式服务地址。

## 当前证据

- Task1原装配／Catalog／资源120 passed/2.81s；Task2路由／native及graph Session／SDK生命周期120 passed/3.84s（两组有重叠）。
- Journal配置3个缺失能力 RED→76个相关 GREEN/1.77s；无 Session Profile 模型 Scope 1 RED→72相关 GREEN/2.36s。
- 真实 Temporal/PG，独立 Worker完整间隔、默认切换、审批与重复回执、native/graph Session显式idle rebind和原History replay：3 passed/30.64s。
- 真实共享 async model/summary、tool线程、Session append线程关闭窗口：4 passed/9.73s。缺失原Registry队列与安装示例的扩充复验随后通过。
- 冻结源码原53实际服务 passed/453.23s；冻结Host9 passed/47.04s（含1个离线配置）；独立安装同组62 passed/504.83s，无跳过。
- 独立安装相关契约104 passed/1个未配置服务跳过，最小安装90 passed/31个可选SDK跳过；两组有重叠，不合计。
- 241个产品模块在冻结源码、wheel、sdist与两个实际安装环境完全一致；版本/Metadata均0.1.0.dev70，无源码路径泄漏。Fresh core默认Profile/Host缺SDK拒绝、原生保存和图两Turn、离线模块通过。
- 真实旧69→70→69：Local审批／原Session／类型化回执／默认Profile／21种starter和产物引用保持；Temporal默认审批及native save-v1 Session/Turn/History均通过，每个工具各只调用一次。旧69在I/O前拒绝新journal声明。
- 完整第一次冻结回归4059 passed/328 skipped/1 failed，469.96s；失败是现有恢复夹具将业务终态误认为Session已空闲。只增加原busy门禁的5秒有界观察，50项相关回归通过；未修改产品；第二次完整回归 **4060 passed/328 configured skips，650.66s**，exit0。隔离Temporal/Redis/PG已由原runner28616停止并等待，stopped标记确认。只保留本地提交，无推送。

## 边界

旧未配置 Profile 的 Manifest／native save-v1 与默认请求保留；显式 Profile 的无 Session模型请求补齐原 Scope。
新 Journal 声明由旧69和Local Profile接受前拒绝。新 Host 不自动迁移旧代码／资源或下载历史版本，
完整部署版本／配置迁移、跨权威租约、容量／保留、自动监督、企业 IAM和真实质量尚未完成。
关闭只证明支持的实际调用、线程与通知责任已排空，不代表业务全部完成、业务取消或任意外部效果停止。

未调用真实模型；不使用历史密钥；仅本地提交，不推送、不发布。

## 独立审查与统一修复

本批仅一次 fresh-context Astra 只读审查：无Critical，4Important、1Minor；审查者报告两组离线测试通过，有重叠，不合计到执行者结果。4项Important都按实际用户影响采纳，在一轮统一修复中9项RED→72项相关GREEN。

1. 普通Facade重新信任可变Engine／新namespace UUID：Host原Scope/Client/queue/release与UUID进入每次普通RPC，漂移拒绝。
2. 普通open／重提忽略旧队列：原SDK队列／类型在query/Update/start前验证，不派发未托管历史版本。
3. 准入漂移阻止清理：在原创建循环排空原RPC supervisor，保留全部实际处理器与end通知门禁，再停Worker／释放资源。
4. 最后status已观察到新binding却返回旧ref：最终SessionRef与revision必须吻合。

Deferred minors：SDK启动选项未知字段／无效timeout可能先读namespace再拒绝。目前只是只读RPC与错误诊断局限，不派发模型／工具；已写入指南与R04剩余清单，未在此修复轮扩大范围。

## 实施判断与代价

以下按作出顺序保留全部判断：

- Ruling: refine and implement already authorized R04/H1/H5 continuously without repeated spec/plan/finish permission menus — user explicitly requests continuing until all capabilities and existing architecture defines original-release routing/owned resources — cost if wrong: user corrections may require adjusting this documented design detail before delivery.

- Ruling: add Temporal-only effect_journal PostgreSQL declaration/factory in Task3 — R04 explicitly requires full component configuration and actual writes/approvals; existing PostgresEffectJournal remains the evidence port, not a new execution authority — cost if wrong: larger batch/API validation surface; users still need an explicit remote DSN/stable backend and restore original resources, with Local catalogs unchanged and old69 readers rejecting new declarations before I/O.

- Ruling: stateless explicit runtime_profile requests carry original state Scope just like existing Session/binding requests; legacy unprofiled three-field request and Manifest remain exact — actual configured default otherwise cannot execute, and no caller-supplied authority is invented — cost if wrong: old explicit Profile failed/no-Session Histories may require their original Worker code; live old-default compatibility and new History replay still required.

- Ruling: review-package script rejects empty committed range4186fe2..HEAD; use explicit BASE→current worktree package listing all tracked/untracked files, then final commit after gates — preserves user local-after-completion order and reviews real new code rather than empty range — cost if wrong: later edits need test/gate proof; reviewer does not certify frozen final build.

- Final: Ruling: automatic omitted code/resource recovery, hot migration/deployment versions and process supervision remain deferred — Host requires explicit original versions/queues as original authorities do — cost if wrong: operator must restore code/resources manually.

- Final: Ruling: cross-authority leases, enterprise IAM, global quotas/retention and long-lived Facade retention remain unaccepted — this delivery owns finite explicit versions and lifecycle, not production service governance — cost if wrong: long-running hosts need admission limits/reuse and can grow retained Facades; remains R19/R23/R24 work.

- Final: Ruling: undeclared private background work remains unsupported — only declared actual tasks/bridges can prove stopped before owned release — cost if wrong: private tasks may outlive resources and must be bridged explicitly.

- Final: Ruling: live semantic quality and outside-developer adoption remain unverified — mechanical scripted proofs are not model/business quality — cost if wrong: application success still needs its own oracle/evaluation.

- Final: Ruling: final frozen package/install/full/old69 compatibility remains executor work — reviewer did not certify unexecuted delivery gates — cost if wrong: defects there can block local commit until fixed.

- Final: Ruling: supplied actual9+53 results were not independently repeated by reviewer — their source logs and executor frozen installed gates supply evidence, not a second review — cost if wrong: incorrect fixtures may overstate mechanical confidence.

- Ruling: change only recovery fixture to bounded wait for original Session status.busy false after businessterminal — original _blocker explicitly retains hosting/_drive_users/_operation_active beyond businessstate and must keep doing so — cost if wrong: 5-second gate could reveal a true stuck owner; all effect/model/append counts and receipts still enforced, final full suite must rerun after this observed failure. No second reviewer or production fix pass added.


最终Ruff／621文件格式／Git空白／CI YAML和11文档494本地链接通过。CI声明安装/core与真实Host组；GitHub及Python3.11/3.13矩阵未在本机执行。最终sdist的656份文档／测试／配置文件与源码一致；产品241模块与wheel／sdist／两个实际安装环境一致。
