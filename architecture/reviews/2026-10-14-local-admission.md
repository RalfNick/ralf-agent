# dev116：Local 部署 root 准入、恢复与独立审查

日期：2026-10-14；前序为 dev115 本地提交 `aa426fb`。本批沿[第三阶段支持矩阵](../../docs/phase3-support-matrix.md)实现批次 2 的 Local 部署准入。Temporal 部署级 History 准入仍为必须继续交付的门槛；本记录不能代表批次 2 或整个第三阶段已关闭。

本批最终冻结源码与独立安装各 **1067 passed、零失败／零跳过**，402 产品文件逐字节一致。Local 部署准入验收通过；Temporal 准入及后续阶段门槛仍开放。仅本地提交，不推送远端。接入指南见[部署准入](../../docs/deployment-admission.md)，精确约束见[契约](../specs/deployment-admission-contract.md)和[批次计划](../../docs/superpowers/plans/2026-10-14-deployment-admission.md)。

## 实现边界

- `DeploymentAdmissionPolicy` 是独立、不可变 portable DTO；不改变 dev115 Local／既有 Temporal ExecutionPolicy identities。Local SDK、Profile `admission_policy/bounded` 与同步／异步注册工厂接通原 Builder。错误类型、子类及惰性配置不能成为已完成策略。
- 原 SQLite 数据库保存完整部署策略及 root claims；部署上限跨 Scope，Scope 上限独立。子 Run 沿原父链共享根占用，不把预算或单 Run 并发当作部署容量。
- 构造取得原 Coordinator 后独立事务安装策略、登记 legacy occupied roots。历史原发布保持原字节，旧占用超限不阻止原恢复；新 root 仍按额度拒绝。
- Builder 宿主 `admission_policy=` 可在保留原 Profile identity 的条件下恢复 legacy Run。Profile 与宿主双源提前拒绝，避免偷偷覆盖；配置别名／principal／省略策略不能移动已固定数据库治理。
- 新 root 在原命令／Run／预算／事件事务内占位。`CapacityExceeded` 为没有接受新 Run 的瞬时拒绝，已接受重复命令先返回原回执。新子 Run 沿原身份继承，不重复占 root 额度。
- optional 五方法端口固定原 Store／backend／方法绑定，mandatory ExecutionStore v1 不变。代理不暴露 SQL 仍可恢复；已激活 SQLite 的 mandatory 插入边界拒绝隐藏可选端口后的绕过。
- Schema 16 保留原 Session、native publications 与期限数据。默认省略不新增策略／Manifest／请求／Schema 1；旧 dev115 Reader 的拒绝及原默认／legacy 完整字节由最终兼容探针验收。
- 占用释放须原树 terminal／quiet、持久 reservation／unknown／辅助写入和停止义务全部符合要求，再检查真实 drive／线程／并行所有者结束。金额零不代表无保留，取消或关闭也不是释放证据。
- 原公开 `workflow.local_admission` 显示 root、固定策略、held 和 host failure；绑定无法确认时不伪造已释放。恢复原绑定、沿原 Run 核验／结束实际工作，再刷新或重试新提交。

## 测试先行与独立审查

配置任务先复现了 SDK 缺少 `admission_policy`、Profile 不认识新角色、Registry 不能注册以及 Builder 缺宿主恢复参数的 RED。精确 JSON／TOML、同步／异步工厂与 legacy 恢复检查分别执行，未用第一个 SDK 失败遮盖其他入口缺口。宿主参数恢复保持原 Profile、Manifest、release digest；双源即使相同也拒绝。

独立可替换端口检查验证 ConnectionHidden 代理、广告版本／缺方法、异步／generator 方法、惰性／错误 policy、holders tuple／Scope、nonbool release 回执及 Store／策略漂移。错误 release 在原事务内实际尝试修改 claim 后，被错误回执校验回滚，原占用仍保留。首次 foreign Scope 测试夹具缺少完整准入 Manifest／digest，被原插入 guard 正常拒绝；修正夹具后 35 项全部通过。这是测试构造错误，不登记为生产漏洞 RED。

独立最小 H3 数据验证新增 4 个参考 SDK 流程：

1. 默认 grounded managed memory 提炼完成，实际 fact 与阶段回执一致。
2. 模型摘要完成，SQLiteArtifactStore 大结果实际落盘并通过原引用读取。
3. 原生 Session history 连续两 Turn，第二轮接回第一轮原模型消息。
4. Team ReceiptParentCompletion 与受管理 verifier child 完成，原 verdict adopted、children settled。

每条流程仅配置一个 root 额度，原实际操作结束、无未知义务后 holder 清空并接受下一 root；4 项独立源码检查通过，未发现完成状态被误判为永久占位。所有模型均为确定性夹具，不产生真实模型质量成绩，也不扩展到所有数据／编排组合。未知辅助数据的保留由相应 Store／恢复用例验证，不从上述完成案例外推。

## 实际进程范围

6 个实际 POSIX 场景分别使用 SDK、JSON、TOML 的固定配置：

- 原 owner 到达持久审批后 SIGKILL，原 claim 在新 owner 中仍持有；同一命令返回原回执，新 root 满额拒绝。另一 Scope 不能读取原 Run／holder，也不能绕过部署总额。
- 原审批命令提交后再次 SIGKILL；使用同一数据库、Scope、Profile／策略与工具版本恢复原 Run，只产生一次业务文件写入，保持原 EffectKey；完成后接受下一 root，重复恢复不再执行原工具。
- handler 已 fsync 业务文件但效果回执尚未返回时进程 exit 77；冷恢复为未知效果，取消后终态仍保留原 claim，新 root 继续拒绝，不自动重发业务。

每组三个配置对应 6 个 SIGKILL owner 和 3 个实际效果窗口崩溃进程。正常恢复进程与崩溃 PID 须在最终源码／安装清理记录中核验实际退出。fixture 使用当前产品的真实 import origin，不假设源码 checkout；固定 wheel 验收应核对独立 site-packages。环境仅含必要执行路径／编码及产品定位，不继承密钥，不调用网络服务。

## 最终验收表

| 门槛 | 必要证据 | 当前登记 |
| --- | --- | --- |
| 策略与公开装配 | DTO、SDK、Profile JSON／TOML、sync／async 工厂、宿主 legacy 恢复、双源／错误返回预检、owned 清理 | 71 配置＋18 独立策略案例，最终源码／安装均通过；既有两种 ExecutionPolicy identities 不变 |
| 原 Store 与 Schema | 默认 1、旧数据激活、15→16、原事务回滚、immutable policy、并发原子准入、Scope 额度与 mandatory 插入拒绝 | 27 Store 案例，最终源码／安装均通过；两条实际线程／独立 Store 仅一条原子占位成功，均已结束；旧 Reader 实际拒绝 Schema 16 |
| 可替换执行存储 | 隐藏 conn/path 的五方法代理、原绑定、lazy／malformed refusal、typed tuple/bool、错误回执回滚、foreign locator 拒绝 | 35 可替换端口案例，源码／安装均通过；真实错误回执的 claim 修改随事务回滚 |
| 业务与释放 | 重复原回执、legacy 超限恢复、嵌套共享根、未知／零保留／辅助及实际线程义务、直接控制和关闭 | 21 核心案例、3 legacy 编排、10 独立审查案例，源码／安装均通过；实际线程、模型／工具零额度未知与子树义务分别核验 |
| H3 正常数据组合 | 默认记忆提炼、模型摘要与 durable Artifact、native Session、ParentCompletion adopted | 4 个所选 SDK 数据组合，最终源码／安装均通过；不外推所有组合／真实模型质量 |
| 真实进程恢复 | SDK／JSON／TOML 6 个场景、原 PIDs、完整发布和 effect key、单次业务文件写入、未知后持续满额 | 源码／安装各 6 真实进程案例通过；合计 12 SIGKILL＋6 exit77 原 owner 均实际确认不存在，另 36 正常子进程退出均由 fixture 核对 |
| 诊断与恢复 | 原 workflow.local_admission、held 不确定时 host failure、恢复原绑定及原证据后刷新 | 释放宿主失败公开可见，恢复原绑定后刷新可安全继续；held=None 明确表示绑定／读取未确认，不伪造腾位 |
| 固定安装与兼容 | 仓库外 wheel、产品逐字节、默认完整声明／Manifest／历史回执、旧 Reader／Worker 身份 | 402 产品逐字节一致；原 dev115 默认／已完成回执与原嵌套 Profile／Manifest／release／回执匹配并实际恢复。Coding composition 与 native 来源门槛拒绝原发布，保留 immutable dev115 Worker；本批不重跑真实 Temporal History |
| 工程与提交 | Ruff、格式、空白、CI 安装入口、本地提交 | 全批 Ruff、格式与 Git 空白检查通过，CI YAML 可解析；CI 增加安装后准入检查，未运行远端 CI；仅本地提交 |

中途失败、测试假设修正和不同冻结版本必须保留原范围。前阶段全回归不是当前源码全回归；局部检查、源码测试和 installed wheel 验收分别登记。本表验收 Local 部署准入范围；没有将前轮 1066 项检查或阶段二全量当成最终 1067 项证据。

## 剩余必需门槛

Temporal 配置首期纯预检拒绝，不能把可选角色或共享 policy 值算作部署容量已经支持。下一批沿原部署定位的 CommandRegistry History 原子准入、Scope 命令身份、原 Run/Parent epoch 与原停止证据接通；SDK 启动不确定不得释放，EffectJournal 不担任另一执行权威。真实多客户端、Scope、重启、unknown／真实 handler、History replay 和固定安装共同验收后，才能关闭批次 2 容量部分。

本批不提供 force release、TTL 逐出、排队、公平调度或跨 SQLite 数据库容量。第三阶段观察／控制、可信身份／ACL／审计／保留，以及框架备份恢复／迁移继续保留原必需门槛。第一阶段 dev99／第二阶段 dev113 的模型与服务证据只按原范围复用；这批内部夹具不证明新模型质量、外部采用或 AgentScope／LangGraph 优势。

## 最终产物与保留证据

最终 wheel SHA-256：`ae3e396f3bccd356c7410c3d805870fd6149305a10fb632e2c87a3f6b6a1605a`。实际导入为 `/private/tmp/ralf-agent-dev116-root/installed-venv/lib/python3.12/site-packages/ralf_agent`，依赖库借用现有运行环境，产品来自独立安装并校验 402 份源／wheel／安装内容一致。全部 52 个所选测试模块及 process worker 在 checkout 外同冻结执行，测试字节和产品冻结摘要复核通过。

私有证据根 `/private/tmp/ralf-agent-dev116-root` 保留最终源／安装 XML 和日志、前轮 1066 项日志、固定 wheel、默认／legacy 与 Worker 门槛、实际进程清理、产品及测试摘要。初轮 Core／Profile 的 5 failed／87 passed（原 pending child 查找和 Node Store 投影）、旧嵌套 1 failed／2 passed（基础组件 Manifest 治理字段漂移）、调整发布位置后的 Node 重建 3 failed／103 passed，均在本轮审查登记，不改写为首轮通过。原 10 项独立 review 包括已拒绝模型、取消工具、纯准备、已知 verifier child、收到无效 evidence 提案及未知／冷恢复窗口；普通未治理旧协议不增加 closed＋received 变体。治理下闭合保留原收到的提案，adopted_verdict 仍为 None，不清原证据。

旧 Reader 与真实独立 Store 并发探针保留在 `/private/tmp/ralf-agent-dev116-storage-audit` 并复制到根验收目录。所有新模型均为确定性夹具，本批没有真实模型或网络服务调用；dev99／dev113 的质量及环境证据仅沿原冻结范围引用，没有声明新的质量、性能优势或框架整体对齐。
