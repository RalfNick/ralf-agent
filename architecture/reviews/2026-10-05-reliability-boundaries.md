# Ralf-Agent 可靠性边界 Review

日期：2026-10-05；基线：`f806a55`／0.1.0.dev2；修复版本：0.1.0.dev3／`local-3`。范围为用户提供的七个最小复现和相关 Local 扩展契约。基线 141 项测试全部通过，新增回归仍确认以下漏洞，因此原测试数不能作为可靠性结论。

## 1. 七项发现与处置

| 优先级 | 复现问题 | 修复及验证 |
| --- | --- | --- |
| P1 | 硬链接或 Store 构造后的 chdir 使同一数据库取得不同锁／WAL | 构造时固定 canonical 绝对路径；连接前及 WAL 前拒绝多硬链接和非普通主文件；租约获取、事务开始复核 dev/inode。真实子进程验证 chdir／symlink 仍不能取得第二份锁，硬链接在 WAL 前拒绝 |
| P1 | async policy 的 coroutine 被忽略，写工具继续执行 | 构造拒绝异步、异步 callable 及惰性 generator；运行时拒绝意外 awaitable／generator，关闭 coroutine／generator，不预留或派发工具调用 |
| P2 | submit 去重摘要包含当前默认配置，配置别名变化后无法取回回执 | 摘要只含调用方 definition、input、budget、session_id；命令查重先于 Manifest／Context 解析，首次接受才固定 Release。配置移除时也返回原 Run，不新增事件／预算；调用方参数变化保持冲突 |
| P2 | 自定义 Provider 返回空输出时仍成功，完成语义依赖 Provider 实现 | 抽出纯 `decisions.final_output`，在公共采纳前及节点完成时校验。拒绝缺失输出、空白文本和 JSON 编码后的空文本；显式 Schema 允许 null 时合法，False／0／空对象和数组不误拒绝，工具提案不要求最终输出 |
| P2 | await append 期间替换后端，仍以原 Manifest 确认成功 | 读取和保存固定使用捕获的 Session 组件；等待后、节点及 Run 终态提交前复核当前发布与实际组件身份。变化使 Run 失败，已发生外部写入可能保留 |
| P2 | 完成 Run 的 Task／Lock 永久保留 | 完成回调清理对应 Task；统计持锁者和排队调用者，只在无调用者、无执行中调用时移除锁。连续 100 Run 清空映射；取消 owner／waiter 时仍保持原锁及活跃效果归属 |
| P2 | NaN 到期时间被 SQLite 变成永久记忆，两个后端行为不同 | 两后端在写入前统一检查有限 int／float Unix 秒或 None，并归一化数值。拒绝 NaN／无穷／布尔等，不消费 CAS 或改变数据；None、过去及未来时间保持一致 |

独立复核额外发现 JSON 编码空文本与 generator 授权两个同类绕过，均通过 RED→GREEN 回归修复。证据来自真实 SQLite、子进程排他锁、受控异步等待及真实写回调；没有调用生产服务或付费模型。

## 2. 当前保证及升级边界

单 Coordinator、固定发布、不可变已采纳结果、未知效果保留和预算原子预留仍由 LocalEngine 与执行日志裁定。Session／长期记忆不承担执行权威。最终记忆写与 Run 提交不是跨后端事务；本轮避免错误成功确认，不能撤销已经发出的写。

本地数据库目录、主文件和 WAL／锁文件需由运行方控制。普通路径别名检查不等于任意恶意文件系统变更防护，也不提供网络文件系统或跨主机租约。

dev3 使用 `local-3`；SQLite Schema 和 ExecutionStore 端口仍为 v1。dev1／dev2 Run 可按 ID 观察、取消及人工核验，继续执行需要原版本。旧 submit 摘要含 Manifest，尚未自动迁移；历史提交重放也需原版本。去重在配置别名变化后保持稳定的保证适用于 dev3 首次接受的请求。不能修改历史 Manifest、清空执行日志或创建新 Run 来绕过未知效果。

## 3. 推进 Temporal／并行前的架构门槛

| 门槛 | 实现边界 | 必须通过的行为验收 |
| --- | --- | --- |
| Harness 与 ToolExecutor | Harness 消费固定快照和回复，产生纯 Proposal；Engine 固定 Action 身份并条件采纳。Executor 消费不可变 DispatchEnvelope、返回结构化 EffectObservation，不修改 Run 或自行重试 | 提案脱离 Engine 可验证；重复／过时采纳不创建新 Action；权限、审批、预算和派发意图完成后才执行工具 |
| 分阶段恢复证据 | 完整 ModelResponse 保存先于解析／DecisionCommit，EffectReceipt 保存先于 ResultCommit；已收到、已采纳、未确认效果分别表达 | 在两个阶段之间真实终止进程，恢复不重问已保存模型回复、不重做已确认写；取消后的晚到证据保留且不推进 Run |
| 规模治理 | RecallQuery 在后端做分页、范围、TTL、版本和来源授权筛选；Session 占用与未决效果使用事务索引；运行容量与 credits 分开 | 数据增长不触发全量 namespace／Run JSON 扫描；超载有明确排队／拒绝语义；取消但仍执行的调用继续占容量 |
| 独立 Temporal 权威 | Workflow／History 负责唯一状态推进；数据库投影只查询，执行跨存储交接具有稳定身份和耐久确认 | Local／Temporal 复用重复命令、审批、取消、未知效果、旧结果、恢复以及 Continue-As-New 黑盒契约；通过真实探针再声明支持 |

`decisions.final_output` 仅是纯校验的第一步。模型提案生成、审批、效果派发／核验及结果合并仍集中在 LocalEngine；模型完整回复和工具回执尚没有独立持久恢复窗口。执行存储可替换也没有实现新的调度权威。以上内容继续作为未交付门槛，不能用本轮 bug 修复替代验收。

## 4. 验证记录

最终测试、构建与安装验证记录见 [实现进展](../../docs/implementation-progress.md)。本次 30 轮额外排队／取消压力复核每轮包含 12 个 waiter，确认 shielded 工具结束前保留归属、完成后相关内存映射清空。已发布支持范围见 [实现状态](../../docs/implementation-status.md)，适配器约束见 [扩展指南](../../docs/extending.md)。离线运行验证不代表模型任务质量或企业部署验收。
