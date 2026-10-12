# 原生 Workspace 写入的真实 Temporal 生命周期验收

基线 `11581df`／dev80，沿 R13/R19/R21 和原 Run／Action／Runner 契约推进。
补齐 dev77 延期的实际原生写入取消、关闭和第二 owner 租约窗口证据。
本阶段复用原 FD、WriteJournal、Source2、WorkerExecutionOwner、Temporal History 和 PostgreSQL EffectJournal；
不增加执行权威，不把 SDK Task 取消当作真实线程结束。

## 场景与责任

自有本地 Temporal／PostgreSQL，显式 Agent、顺序、Graph、Team、Dynamic、嵌套六种原定义。
只允许对测试临时根的 `note` 写入，首次审批后在真实 `os.replace` 前阻塞原 handler。
观测线程实际开始，重复原审批，提交显式 Run 取消，并尝试以零等待关闭 Assembly。
未退出时关闭必须报告 `CloseIncomplete`、原 Root FD／租约保持，第二原生 owner 不得取得该根。
关闭后的原 Engine 不接受业务推进；观测使用原 Client／Scope／原 History。
未实际退出的线程不能被记为已停止；可见业务取消与真实静止证据分别记录，不允许取消后的成功或新成员业务派发。

释放原阻塞点后，必须看到真实 handler 返回／线程结束，再排空原实际调用及原结束通知，关闭 Worker 与 owned 资源。
实际退出后第二 owner 才能打开原根，查询同一稳定效果键的原本地回执；不得通过重放原写处理器找回结果。
原文件效果最多一次。重新装配原 Profile／Worker，只查询或核验原取消／未知效果，保持原取消结果和稳定回执、固定发布。
History replay 必须通过。记录业务状态、quiescent、未知效果和实际结束各自证据；发现矛盾先写失败复现再修正，不自行放宽验收条件。

## 测试边界

真实服务用显式配置选择，普通无服务测试可跳过，但本批必要源码／安装服务验收必须零跳过。
阻塞仅匹配测试根的 `note` 原生 replace，不影响 SDK／pytest 其他文件操作。
线程阻塞最多30秒、事件启动等待15秒、单场景90秒；finally 始终释放阻塞并关闭所有原 Assembly。
自有服务限回环及临时 Unix socket，原启动进程实际停止并等待退出；不启动 Docker 服务、下载镜像或调用模型。
保持原 JSON／工具／默认发布和22 starter，真实旧 dev80 双向兼容证明不可用源码模拟替代。

## 交付判定

这是已交付原生写能力的实际运行与恢复门槛；优先复用已有实现。
若测试直接通过，增加证据及可重复测试；若失败，在同一阶段按实际问题修复原层职责并固定协议兼容边界。
本批另外允许独立处理 dev80 两项文档 Minor：明确默认 YAML merge key 限制，并恢复历史 dev79 段落标题；它们不改解析行为。
产品保持 dev80，所有必要实际场景通过后才升级 dev81。全量／全新安装／固定源码包及旧兼容门槛继续沿原流程验收。
Sandbox／Runner／selector／自动目录阶段／治理／真实质量仍是后续能力，完整 R01–R26 保持 ACTIVE。

追加两项明确的回执接收边界故障注入（Agent／Graph）：原始 PostgreSQL 意图真实保存，测试代理仅在原 Assembly 退出前拒绝 received，不伪造业务或效果；新 Worker 向原生 journal 查询真实文件回执并更新原 History。它不代表实际 PostgreSQL 服务崩溃验证。其余六类默认后端生命周期证据独立保留。

## 发现缺口后的版本化工具结束协议（Task2 前置）

真实故障注入证明：回执已采纳、预算unknown=0、state=cancelled，但原协议有意保留remote_uncertain，因为查询不证明旧handler停止。不得直接清除此标志。需要显式的原History工具实际结束证据。

提供可替换 `ToolExecutionPort`（普通固定identity及async execute(operation, *, proof, on_end=None)/wait(*, wait_timeout=30)/aclose(*, wait_timeout=30)），默认 `ToolExecutionOwner(*, version, max_calls=8)`复用既有ContextExecutionOwner的真实async任务／委派线程／通知拥有，不增加业务状态机。max_calls为1..256，包含尚未结束或未获History确认的调用；资源owned/borrowed由原装配账本负责。

TemporalRuntime增加显式tool_execution=None注入。Temporal Profile新增仅Temporal支持的 `tool_execution` 组件，adapter=tracked，config仅version（必填）和max_calls（默认8）；纯预检先于数据／文件／Worker分配。Local不接受此组件；默认未配置的Manifest／DTO／22模板保持原字节。

启用时在原temporal-3 Manifest发布 `tool_execution_protocol`：精确version整数1、owner普通有界identity、execute/wait/aclose各方法固定实现摘要。整体至多64KiB，普通JSON最多4096值／深度16／标量UTF8总64KiB；不接受惰性方法或对象复制钩子。旧Worker必须在任何Activity/model/tool前拒绝新协议。

原History在工具派发意图内保存原Action、请求摘要、执行epoch及结束状态。只给启用的原tool envelope增加原release_digest；原Scope/run/action/attempt/effect/operation/manifest均保留。执行前通过专用 `admit_tool_dispatch` Update复核原请求／当前取消状态；同一实际operation不执行两次。容量拒绝与取消在开始前发生时必须给准确未开始证据，不能留假活动记录。

真实Owner保持业务operation及实际线程，观察者取消不销毁它们。实际全部退出后，向固定原Workflow/run_id/namespace及Scope提交专用 `tool_execution_ended` Update，proof精确scope/action_id/release_digest/request_digest/execution_epoch。History严格比对原意图，幂等采纳，拒绝错Scope/Action/摘要/epoch和无意图证明；RPC取消／丢失应重试查询/同一结束通知，禁止补造结束。借用Client或身份变化不能转向其他Workflow。

效果回执与实际停止证据独立。查询可确认效果／结清预算，但不能独自清除执行未知；原Tool结束证明才清除它自己拥有的停止未知，保留模型／其他阶段的不确定性和未核验效果。新协议的quiescent及后续业务派发需要所有原Tool实际结束；取消保持终态，迟到回执或结束不能改为success。原ACK／reconcile在终态可继续，不创建新业务Action。原记录在History持久化，Worker重启不重算；新增诊断tool_executions只在启用发布出现。

Assembly在停止Worker／关闭Source、Root、客户端前排空原ToolOwner及结束通知；零等待失败可重试且保持原租约。单独SDK调用未提供固定Client／结束回调不得启动该协议下的工具。此功能属于执行生命周期；不改变Source2效果语义，不提供Sandbox或任意外部Peer停止保证。

追加验收：公共默认owner无SDK核心可用、自定义owner注入／恶意惰性／身份变化、纯History结束顺序／幂等／错证明／未知效果与实际结束分别门禁、实际Agent/Graph丢失回执并重启后原查询恢复停止确认，以及真实旧80Worker新marker执行前拒绝。保持原默认六类与旧80双向恢复验收。

兼容门槛细化：旧80忽略未知Manifest扩展键，因此仅新增marker不足以拒绝。显式工具生命周期发布使用temporal-3／binding_protocol=3，并必须携带tool_execution_protocol1。新代码兼容原1/2（新marker缺席）；既有Context read marker在新3发布仍保持它自己version1，组合验证扩展到3；发布工具marker在原Context／数据发布之后，旧80在已知binding门槛拒绝，不能靠未知字段猜测。

最终审查统一修复细化：原History保存每个工具意图的独占 invocation_id（随机有界 token，由固定Activity回调先于派发创建，作为专用Update证据，不改业务request_digest）。admission/end都必须携带该token；同一token重复观察只能查原grant，另一token必须拒绝且不能提交原owner停止证明。Owner操作只会按同一claim执行一次；已经停止的意图不得重新派发。取消在持久grant之前拒绝；grant之后可完成原业务但不能打开终态。

容量／关闭拒绝等真实未开始证明也需要受管理通知：在既有ContextExecutionOwner内提供同一proof的无operation结束通知登记，不消耗业务调用槽但有独立有界通知容量；通知失败／观察者取消保持owned，wait/aclose必须等待原ACK。达到通知容量应在History admission之前拒绝并保留可重试记录，不伪造完成。不能在execute拒绝catch里直接await后丢弃通知。默认ToolExecutionOwner显式提供此机械通知能力；可替换端口必须通过自身execute登记no-start回调或明确的受管理notification方法保持相同契约，固定metadata包含相应方法。

自定义owner端口的execute/wait/aclose返回必须是完成值：不得返回coroutine/Future/generator/asyncgenerator/上下文管理器等惰性结果。公共采纳边界安全处置并明确拒绝，不能将其当成Activity业务回执。closure malformed值不释放原资源。上述三项全部先真实RED，再同一修复pass GREEN及完整suite；不新增执行权威。

通知实现裁定（前述第四方法要求被本段替代）：ToolExecutionPort仍为三个方法；Runtime固定 notification-only ContextExecutionOwner，以每个原请求／invocation的机械通知槽包住执行owner调用，并在真实operation或准确未开始完成后重试原结束通知。通知槽固定max256、在History admission前预留，方法与容量在新protocol元数据固定；不得在业务任务仍活跃时通知。自定义owner若execute返回/抛错不能自动证明真实停止，必须以它回调的准确结束为准。Runtime wait/close同时排空原Toolowner和notificationowner，默认无新协议路径不变。
