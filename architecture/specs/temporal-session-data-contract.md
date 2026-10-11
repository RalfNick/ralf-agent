# Temporal 外置 Session 数据契约

日期：2026-10-11。状态：**目标规格，尚未交付完整链路**。

dev66 已验收原生／顺序的外置保存和持久 Turn，见[指南](../../docs/temporal-session-data-writes.md)。
高级根／成员地址、最终 Parent 保存、全配置／旧新版本等完整六组门槛继续开放。

本契约落实 R01/R02/R14 与 H1/H2/H3，依赖[能力绑定](agent-capability-binding-contract.md)、
[入口与 Session](agent-facade-session-contract.md)、[Run/Action](run-command-contract.md)。
它规定下一阶段实现必须遵守的边界，不新增公共 SDK 配置字段。
当前 dev60–63 的 Temporal Session 仍由 History 保存有界 Conversation；dev64 仅补齐
默认 Session 回执端口及 Local 外置默认 SQLite 恢复证据，不能关闭 Temporal 外置数据验收。

## 1. 唯一权威与资源职责

| 对象 | 责任 | 禁止承担的责任 |
| --- | --- | --- |
| 原 Agent/Workflow/Parent History | 固定发布、模型/工具执行、数据读采纳、写意图/回执/未知核验、结果提交与取消 | 不以当前配置覆盖原发布 |
| 原 Session Coordinator History | 原 Namespace UUID 下的 Turn 身份/顺序、busy、启动意图、静默检查与 idle CAS rebind | 不另行运行模型/工具，不成为业务写入或业务终态权威 |
| Session 数据后端 | scoped read/CAS append、稳定 message_id 与精确已提交回执 | 不授予执行租约，不推测 Run 成功，不调度业务 |
| Facade/客户端 | 提交命令、重连、纯观察、显式取消与资源生命周期 | 不以内存锁代替持久占用，不在 wait 中执行数据保存 |

原业务 Run 持有数据完成门禁。Parent 的根 Conversation 保存是该原 Parent 的受管理
最终阶段，不通过另一个临时业务 Run 或 Session Coordinator 决定业务终态。
这样可避免“Coordinator 等 Run 静默，Run 又等 Coordinator 保存”的循环等待。
Session Coordinator 只在原根及实际启动后代确认静默后采纳 Conversation 投影和释放 Turn。
可见终态和静默分开：取消可先被观察到，未结束的实际写及未知回执仍保持占用。

## 2. 选择、身份与地址

目标：Worker 宿主注册允许的 Session 数据资源及 namespace，每 Agent 可 inherit/ref/disabled，
由宿主权限限制选择。必需持久会话不允许 disabled；不支持的组合在命令接受前拒绝。
这些选择尚未成为 Temporal 的第十类绑定，不允许直接把 Local 绑定对象传进 Workflow。

固定资源描述至少覆盖实际存储身份、端口协议、namespace、Scope、原声明路径以及实际
客户端/方法身份。backend_id 只是声明身份，不足以区分同名不同 SQLite 文件、Redis db/prefix
或 PostgreSQL 实际数据库。客户端/连接池/凭据只留在 Worker，History 保存非敏感版本化描述。
对支持的原生适配器校验物理资源；自定义资源须提供可核验且稳定的资源契约，不能仅信任字符串。
别名变更不回写原 Run。相同 display name 不允许改变忙碌 Session 的真实地址。

SessionKey 仍包含原 Temporal Namespace UUID、Scope 和 namespace；选择外置资源时还必须
包含固定的真实数据资源身份。原 Namespace UUID 不因客户端地址变化而变成另一执行权威。
相反，不同 Temporal Namespace、独立 Local 权威不能通过共享数据库获得跨权威租约。
Redis/PG CAS 只防止数据冲突；跨独立权威会话租约仍需单独设计与验收。

| 数据用途 | 固定地址规则 |
| --- | --- |
| 原生/顺序持久会话 | 原根 Session 地址；顺序成员必须共享获准资源/namespace，禁止部分步骤偷偷改库 |
| Graph/Team/Dynamic/嵌套根 Conversation | 原 SessionKey 固定根资源；原 Parent 写最终聚合结果 |
| 复合成员私有 Session | 根 Session 身份加原声明/成员路径；与根 Conversation 分开，不采用随机 Turn RunID 作为跨 Turn 身份 |
| Facts/Knowledge/Vector/Artifact | 保持各自资源、来源与 namespace 契约，不作为 Session 会话数据的替身 |

复合投影与嵌套必须保留原成员路径。动态新增节点只能使用已授权定义及原采纳计划的稳定节点
身份；未定义的跨 Turn 私有延续规则必须拒绝，不能以临时路径意外串接另一个 Agent 的历史。
idle rebind 只能在原 Session 地址内更新定义/绑定版本。移动物理资源属于显式迁移协议，
不能借 rebind 自动搬迁历史，也不能创建第二个占用持有者。

## 3. 读快照与上下文

原 Context Activity 从固定数据端口有界读取。原 History 在模型派发前采纳并保存 read snapshot：
实际 Scope/地址、revision、数据内容或不可变引用及摘要、原成员与绑定证据。不得在 History 重放
时重新读取当前 Session 来替换已采纳的上下文。Snapshot 数据不是执行状态权威。

根 Conversation、成员私有 Session、Knowledge 引用和 Facts 引用独立分类。不能把另一个
成员的私有记忆作为根对话，也不能以“最后一个响应”替代完整来源证据。
上下文摘要/压缩和大结果卸载复用原受管理阶段，并保留原读快照与 Artifact 引用。
读失败尚未采纳时可以重试；已接受模型请求恢复必须使用原请求。数据变化在下一次合法读阶段
进入上下文，不造成原模型动作重新执行。

## 4. 写意图、回执与未知结果

原 History 先采纳写意图：原 Action/阶段、资源/Scope/地址、expected_revision、稳定 message_id、
完整消息与摘要、预算/身份、对应模型或 Parent 聚合证据，然后派发受管理 Activity。

原生/顺序可以保持逐步骤消息保存语义，步骤完成门禁由原 Run 持有，最终 Turn 保存证据指向
最后实际提交的记录。复合成员私有保存由原成员 Run 持有；根 Conversation 由原 Parent 保存。
同一逻辑保存不得因根/成员两层装配而写两次。History 的成功对话投影只在整个 Turn 合法成功
后产生；步骤已有记录可能在后续失败后保留，不能伪造数据事务回滚。

后端 append 必须原子 CAS，并支持稳定 message_id 去重。不同载荷不能使用相同 ID 声称原保存
成功。重复 append 返回原 revision 时，仍需按原写意图核验精确 receipt，不能把 ACK 当作证据。
完成值须为有限 JSON，拒绝 deferred/惰性返回。

精确回执接口为 `inspect_message(scope, session_id, message_id)`，返回实际地址、当前 revision
以及该原消息的提交 revision 和完整消息，或明确 `receipt=None`。sync/native async 的结果契约一致。
缺失不能伪造成功，核验不能扫描模型历史并推测业务写入。默认 SQLite 用原始字符串 ID 索引及消息投影原子点查（旧写者触发独立失效）；内存可扫描
持有的 ID，但不复制整个消息历史。核验单条记录不意味着任意大小消息没有预算限制。

| 观察 | 原权威采纳规则 |
| --- | --- |
| ACK + 匹配原消息的准确 receipt | 记录 received receipt，再采纳保存完成，才允许相应成功提交 |
| timeout/连接中断/进程退出 | 保存 UNKNOWN；Turn 持续占用，重连核验原 ID |
| 原 ID 存在且原消息/revision 合法 | 采纳原写，不重新调用模型/工具或 append |
| 原 ID 缺失、当前 revision 等于原 CAS 基点 | 活跃合法 Run 可按原意图重试保存；取消 Run 不重新派发 |
| 原 ID 冲突、基点已改变、资源变化或核验不完整 | 拒绝成功确认；保留未知/冲突证据与占用，要求明确修复协议 |

数据回执接收与保存完成采纳需要独立持久化窗口与崩溃测试。中间失败不能静默确认符合原发布，
也不能让未知保存丢失后释放 Turn。取消后的迟到回执只结算原保存证据，不把业务状态改回成功。
历史保留/清理不能删除仍关联未知操作的写意图与回执。

## 5. 生命周期、版本与验收门槛

注册资源默认 borrowed；Worker/装配容器只关闭自己拥有的池与客户端。SQLite 留在创建线程，
ThreadedMemoryAdapter 只用于明确线程安全的同步后端，真实线程退出前不能释放原执行租约。
调用方 wait 取消/HTTP 断连只结束观察，业务取消必须显式提交。Worker 停止必须等待实际受管理
操作完成，或由原 History 保持可恢复未知事实；不能靠 asyncio Task 已结束推断处理器退出。

默认 History Session 协议及旧 Manifest 保持原行为。外置数据通过显式新协议启用，旧 Worker
在任何模型/工具/数据 I/O 前拒绝不支持的发布。新 Worker 重放旧 History 不新增外置保存。
模型摘要、记忆提炼、Context 与能力绑定均维持原版本身份。代码/解释器指纹迁移遵守既有 Worker 规则。

完成验收须分别证明：

1. 原生/顺序/Graph/并行/Team/Plan/DAG/嵌套及 managed 组合，根/成员地址和来源隔离。
2. 原始读采纳、写前、真实写已提交但 ACK 丢失、receipt 接收未采纳、Parent 最终保存等进程/Worker 窗口。
3. 审批重启、重复命令、忙碌拒绝、idle rebind、取消时真实线程/Activity 未结束及迟到回执。
4. 内存离线默认、SQLite 同宿主重启、真实 Redis/PostgreSQL；内存不能充当持久分布式默认。
5. 旧 wheel 默认发布/数据/回执双向兼容、新协议旧 Worker 派发前拒绝与实际 History 重放。
6. 配置/拥有与借用、安装包/core-only、可替换端口共同测试及实际多 Worker 证据。

默认端口 dev64 验收见[精确 Session 回执指南](../../docs/session-receipts.md)。本规格、内部测试与
真实数据库运行都不能替代真实模型质量或外部首用验收；完整 H1/H2/H3/M1 继续开放。


## dev65 实际依赖范围

仅交付固定资源／有界读／原 History 证据采纳，见[实际指南](../../docs/temporal-session-data-reads.md)。读地址是原 stateless Run/node 私有地址，尚非本规格的持久 SessionKey／跨 Turn 路径；没有外置自动保存。当前 native/sequence 允许此读子集，显式 SessionTurn 与选中来源的高级组合接受前拒绝。完整写／根保存／物理会话租约与上列六组验收保持目标，不被此增量替换。
