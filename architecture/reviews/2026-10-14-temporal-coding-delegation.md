# dev106：原 Temporal History 的有限 Coding 委托

状态：有限 Temporal Agent／顺序 Coding 子集已验收；完整通用集成未完成。
基线为已验收 dev105 的本地提交 `b518304`。本批仅覆盖 Temporal 原生 Agent／顺序
Workflow Coding 委托，复用原 Run／Action／History 与同一个 PG EffectJournal。
图／并行／Team／Dynamic／嵌套 Temporal Coding 明确拒绝。dev99 参考链路保持冻结；
完整 R01–R26、R13、Coding G1–G8、第二阶段、专用原生认证和真实任务质量继续开放。

## 有限实现边界

- 显式 `TemporalRuntime(coding_execution=True)`／Profile execution 选项发布
  `temporal-3`、binding protocol 11、`dispatch_admission=history-1` 与 Coding
  protocol 1；省略／False 保留默认声明与 Local／Temporal 发布字节。
- SDK／JSON／TOML 的异步 `tools/codex-coding-postgres` 工厂借用具体且相同的原
  PostgresEffectJournal，登记一个 shared RunnerJournal view 与各独立 Runner。
  `runner/registered-tool` 精确借用已授予工具的实际资源；inherit／ref／disabled
  保留工具权限交集，不另造资源或重复关闭。
- 纯 History 状态先固定原 native intent，再固定 Tool 请求。原 SDK invocation／
  Workflow epoch／Scope／请求／release／实际 process owner 绑定先于阶段 grant；
  每阶段只许可一次。Local 与 Temporal 共用纯阶段规则和一个原生循环，History
  中没有 PG、SDK、文件、进程或时钟 I/O。完整 Worker 物理检查不进入重放规则。
- PG resource intent 覆盖 prepare 前窗口，与原 dispatch 同连接／锁／事务提交。
  原回执先 PG 后 History；Activity 重投、超时或遗失回复不产生新 attempt，不再次
  提交 Thread／Turn。恢复仅查询、采纳、停止原资源，不创建替代容器或环境。
- 原候选、native fence、实际 owner 结束、效果分类与预算分别记录。Run 取消／异常
  可保持 cancelling；interrupt ACK、Activity 结束或 Worker Task 消失不单独构成
  停止证明。unknown 效果与原额度 hold 不因 native fence 清空。
- 首部署要求同宿主、原私有根目录及原 Docker Unix 端点。无可信 container ID 的
  create 窗口若无法确认原 namespace 缺席和原 owner 结束，继续保留未决记录并
  fail closed；此不可确定窗口未因有限 absence 恢复案例而整体关闭。
- owned Assembly／Host 关闭先隔离新业务，在原 Client／Worker／PG 接收方仍可用时
  处理原待停止资源，然后排空实际调用和逆序清理。失败、超时或观察者取消保留原
  ledger 与同循环 retry handle；borrowed Client 和借用资源由实际调用方拥有。

使用和可检查配置见[Temporal Coding 指南](../../docs/temporal-coding.md)，
责任边界见[委托契约](../specs/delegated-coding-action-contract.md)。

## 原生配置失败与修复

早期两次实际未保护配置的探针中，App Server 改写原 `config.toml`，严格内容／inode
检查正确拒绝漂移，但原容器清理无法完成。保留 `temporal-native-control.log` 与
`temporal-native-control-wait.log` 的失败。两个确切的自有原 CID 随后手动停止并
移除，记录在 `manual-failed-probe-stop.json`；该操作保留 config drift，不补写成功
回执，也不作为自动停止路径已经通过的证据。

修复限定 PG／History Runner 的新物理声明 `configuration_readonly=True`：保留原
两个 writable workspace／state 目录 bind，增加原 `state/config.toml` 到
`/home/ralf/.codex/config.toml` 的精确 readonly file bind。校验固定三个 mount 的
源、目标、RW=False 与 rprivate propagation；文件不能通过目录别名或替换 mountpoint
改写。原内容、inode、owner、mode 校验保持，不修补已漂移配置。

修复后的实际原生控制探针通过：原配置内容和 pinned inode 不变，原 CID 已移除，
History 取消终态与重放通过，PG pending resources 为空。它是无认证的控制／容器
生命周期探针，不是成功真实 CodingTask，不证明提供方连接或模型质量。

Local 环境 omitted／False 的 identity 与 create argv 保持基线字节；四个 Local
Runner 公共方法 `execute / reconcile / stop_existing / aclose` 的 executable digest
保持。环境 constructor／create／container-validation 三个方法因新 readonly 声明
而改变并纳入 Worker publication；不声称全部环境实现摘要未变。

## 独立审查闭环

同一审查上下文的详细证据保存于
`/private/tmp/ralf-agent-dev106-root/independent-review.md`。

1. **P1：native await 失败被标为 undispatched，错误释放原预留。** 现在进入 Coding
   await 前记录可能已派发；遗失响应回归保留原 Action outcome_unknown、原预算
   unknown=1 与 stop_needed，不追加 Action／attempt。
2. **P1：unknown reconciliation 提前退出，跳过 killed-owner 结束采纳。** 仅捕获
   RunnerOutcomeUnknown 后继续原 fence／实际 owner 死亡核对和 History Update，
   保留未知效果，其他错误仍是失败。
3. **P2：纯 permission verifier helper 未完整固定。** `_record`、生命周期 helper、
   resource receipt helper、Runner／PG 实际内部依赖纳入精确 publication。独立 drift
   probe 修改 `_record` 后被 DefinitionMismatch 拒绝；阻断完整 Worker discovery
   的 probe 仍可执行纯 History 验证。

同一审查者已复验上述问题和 readonly 修复，冻结切片未发现未解决的可复现 P1／P2
阻断。独立 readonly／publication／runtime／History／authority／close／rules 检查
为 67 passed／1 actual-PG 配置跳过（5.01 秒）；该跳过不算服务证据。

## 验证登记

私有证据根目录：`/private/tmp/ralf-agent-dev106-root`。源码回归、测试修订、
固定安装与实际服务分开登记，原失败记录保留。

| 检查 | 当前证据／状态 |
| --- | --- |
| 实际 PG native resource／readonly 检查 | `native-readonly-pg.log`：30 passed／零跳过，12.12 秒 |
| 原 Local／legacy 回归 | `native-readonly-legacy.log`：90 passed，50.71 秒；默认 identity／argv 与公共方法 pin 核对另行保留 |
| 受保护实际原生控制 | `temporal-native-readonly.log`：1 passed／7 deselected，12.15 秒；配置内容／inode、原 CID、History replay、PG pending 核对通过；无认证／模型质量结论 |
| 独立审查最终切片 | 67 passed／1 配置跳过，5.01 秒；两项 P1／helper-pinning P2 已由同一审查者复验 |
| 实际 Temporal／PG 确定性 peer 恢复 | 七个开发案例此前通过：Agent、Turn 后 Worker 崩溃、两 Agent bound sequence、claim／prepare／Turn grant 后崩溃、candidate response 遗失；原 History 证据与 peer 证据分开保存 |
| 最新冻结源码服务矩阵 | `temporal-frozen-final.log`：8 passed／零跳过，69.84 秒；七项实际 History／PG＋确定性 peer 与一项实际 Codex 控制分别保存，每例原 History replay；版本／格式后固定 wheel 复验另列 |
| owned真实关闭／成功回执 | `temporal-owned-final.log`：加严后1 passed／零跳过，6.60秒；停止失败保留Worker／Client／PG和同一账本，同一Assembly重试确认原stop与实际end成功回执、相同CID／attempt，零新Thread／Turn；最终释放和原History replay通过 |
| 独立安装服务矩阵 | `installed-services-final.log`：39 passed／零跳过，80.26秒；八项实际History／PG恢复和原生控制、加严owned关闭，以及30项PG／native resource／readonly检查。安装环境位于checkout外，每项原History replay按测试断言完成 |
| 全模块源码回归与测试修订 | 首轮578模块覆盖：9054 passed／653配置依赖跳过／1旧future-version断言失败；运行中Source／Test输入哈希不变。新增协议11后将未来版本断言改为12，并加严owned History成功回执断言；两文件定向23 passed／1服务配置跳过，生产源码哈希保持，实际owned复验1 passed／零跳过，6.60秒。原失败保留，不把定向结果伪记为重新跑过整套 |
| 固定 wheel 安装／文档示例 | checkout外固定wheel加载dev106，SDK／metadata／Runner来源均为独立site-packages；指南SDK／JSON／TOML身份和声明相同（无模型或服务I/O）。完整安装176模块：原生边界275 passed／10配置跳过（65.37秒）；其余1900 passed／408配置跳过（124.88秒）。合计2175 passed／418配置跳过；实际服务另列，不用skip代替部署证明 |
| 实际 dev105 Worker 兼容门禁 | 实际已安装 dev105 Worker 在零 Activity 注册、零 SDK Worker 构造／业务调用前拒绝新版 protocol 11；默认 basic／ordinary／tracked Runtime 与 Profile 字节相等，显式 False 保持；7份保存的旧 Run／Parent History 在源码、已安装105／106均重放通过。Local源码／固定安装各20组同数据库双向恢复／60阶段通过 |
| 制品／模块一致性 | 374产品模块源码／wheel／独立安装逐字节相等：337旧模块保持、30旧模块改变、7新模块；三份Codex JSON保持基线。固定wheel SHA-256见下；最终sdist完整测试／fixture／文档核对由交付脚本登记 |
| 最终静态／文档链接 | Ruff、1027文件格式、Git空白与10份变更文档的相对链接通过；SDK／JSON／TOML guide身份在独立安装中一致 |
| 自有服务退出与本地冻结提交 | 自有Temporal／PG服务编排器退出0，Docker仍可访问，6个确切自有PG／原生容器ID均确认缺席；私有证据`services-stopped.json`。本记录随本批仅本地提交，未推送 |

固定 peer 是受控子进程协议夹具；实际 Temporal／PG 成功不将其改为真实 Codex 模型
任务。此前 `temporal-faults.log` 的 fixture query-order 失败、原生配置漂移失败、首轮旧future-version断言及安装测试git依赖失败、
RED／中间集成失败保持原记录，不删除或合并为通过。后续修复与正式冻结重跑分开登记。

冻结基线 identity／create argv fixture 独立从已验收 dev105 wheel 导出，去除测试对 Git 历史和完整 checkout 的依赖。归一化只替换私有路径和物理 pin；当前 omitted／False 仍逐项比较固定值。文件在最终 sdist 中显式包含；早期路径别名归一化失败保留。

## 最终交付结论

本批有限 Agent／sequence 委托已验收。全模块回归发现的唯一旧未来版本断言
已在测试中修订并定向复验；生产源码在全模块回归与固定安装期间保持不变。复杂 Temporal Coding 仍拒绝；
跨宿主、不可确定 create／CID 恢复、原生认证、真实 Coding 任务质量与完整 R13／
G1–G8／R01–R26／第二阶段继续开放。dev99 不重新评测，不扩大冻结范围。

固定 wheel SHA-256：`fec9ebbeed1c1e2c19b8b8244796751a4aad96826778c4b7f76a606e43aafbb2`。
